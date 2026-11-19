"""Pipeline camera: doc khung hinh -> nhan dien -> tracking -> rule -> canh bao."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np

import app.classes as C
from app.alerting import AlertManager, compose_text
from app.associator import PersonState, _inside, associate, equipment_present
from app.db import Database
from app.detector import Detection, PPEDetector
from app.evidence import EvidenceStore
from app.rules import RuleEngine
from app.tracker import PersonTracker

log = logging.getLogger("ppe.pipeline")

Box = tuple[float, float, float, float]

COLOR_OK = (94, 197, 34)
COLOR_BAD = (68, 68, 239)
COLOR_UNK = (11, 158, 245)
COLOR_INFO = (230, 230, 230)


# --------------------------------------------------------------------------- #
# Nguon hinh
# --------------------------------------------------------------------------- #
class Source:
    """Giao dien nguon hinh."""

    def read(self) -> tuple[bool, np.ndarray | None]:
        raise NotImplementedError

    def release(self) -> None:
        pass


class OpenCVSource(Source):
    """Camera IP RTSP, webcam USB, hoac tep video."""

    def __init__(self, uri: str | int, width: int = 1280, height: int = 720,
                 max_width: int = 1920, loop: bool = False):
        self.uri = uri
        backend = cv2.CAP_FFMPEG if isinstance(uri, str) and "://" in uri else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(uri, backend)
        if isinstance(uri, int):
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.max_width = max_width
        self.loop = loop
        self._frame_interval = 1.0 / max(1.0, self.cap.get(cv2.CAP_PROP_FPS) or 25.0)
        self._last = 0.0

    @property
    def opened(self) -> bool:
        return self.cap.isOpened()

    def read(self):
        ok, frame = self.cap.read()
        if not ok and self.loop:
            # Tep video: quay lai dau thay vi ket thuc nguon
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
        if not ok:
            return False, None
        # Giam nhip doc de bam kip thoi gian thuc tu camera IP
        now = time.time()
        drift = now - self._last
        if drift > 0 and drift < self._frame_interval * 0.5:
            time.sleep(self._frame_interval - drift)
        self._last = time.time()
        # Ha do phan giai khung lon: 4K decode cham gap 4-6 lan, khong can cho model 640px
        h, w = frame.shape[:2]
        if w > self.max_width:
            scale = self.max_width / w
            frame = cv2.resize(frame, (self.max_width, int(h * scale)),
                               interpolation=cv2.INTER_AREA)
        return True, frame

    def release(self) -> None:
        self.cap.release()


class DemoSource(Source):
    """Gia lap camera bang cach lia mot cua so doc tren anh cong truong lon.

    Dung de kiem chung toan bo pipeline khi chua co camera that.
    """

    def __init__(self, image_path: str | Path, size: tuple[int, int] = (1280, 720),
                 speed: float = 1.0):
        img = cv2.imread(str(image_path))
        if img is None:
            raise FileNotFoundError(f"Khong doc duoc anh demo: {image_path}")
        self.img = img
        self.w, self.h = size
        self.speed = speed
        self.x = 0.0
        self.y = 0.0
        self.dx = 1.6 * speed
        self.dy = 0.9 * speed
        self.max_x = max(0, img.shape[1] - self.w)
        self.max_y = max(0, img.shape[0] - self.h)

    def read(self):
        time.sleep(1 / 20.0)
        crop = self.img[int(self.y):int(self.y) + self.h, int(self.x):int(self.x) + self.w]
        if crop.size == 0:
            crop = self.img[: self.h, : self.w]
        if crop.shape[0] != self.h or crop.shape[1] != self.w:
            crop = cv2.resize(crop, (self.w, self.h))
        self.x += self.dx
        self.y += self.dy
        if self.x <= 0 or self.x >= self.max_x:
            self.dx = -self.dx
            self.x = max(0.0, min(float(self.max_x), self.x))
        if self.y <= 0 or self.y >= self.max_y:
            self.dy = -self.dy
            self.y = max(0.0, min(float(self.max_y), self.y))
        return True, crop.copy()


def make_source(source: str, cfg: dict, root: Path) -> Source:
    """source: '0' | 'rtsp://...' | 'file:path' | 'demo:path' | 'demo'"""
    max_width = int(cfg.get("max_width", 1920))
    if source.startswith("demo"):
        path = source.split(":", 1)[1] if ":" in source else "assets/demo_site.jpg"
        p = Path(path)
        if not p.is_absolute():
            p = root / p
        size = (int(cfg.get("width", 1280)), int(cfg.get("height", 720)))
        return DemoSource(p, size=size, speed=float(cfg.get("speed", 1.0)))
    if source.startswith("file:"):
        path = source.split(":", 1)[1]
        p = Path(path)
        if not p.is_absolute():
            p = root / p
        return OpenCVSource(str(p), max_width=max_width, loop=True)
    if source.isdigit():
        return OpenCVSource(int(source), max_width=max_width)
    return OpenCVSource(source, max_width=max_width)


# --------------------------------------------------------------------------- #
# Ve overlay
# --------------------------------------------------------------------------- #
def draw_person(frame: np.ndarray, state: PersonState, track_id: int,
                required: list[str], zone: str, ghost: bool = False,
                bbox: Box | None = None) -> None:
    x1, y1, x2, y2 = (int(v) for v in (bbox or state.bbox))
    missing = [i for i in required if state.status.get(i) == "missing"]

    if ghost:
        # Track tam thoi mat detection: ve mo, khong nhan, khong doi mau do
        cv2.rectangle(frame, (x1, y1), (x2, y2), (150, 150, 150), 1, cv2.LINE_AA)
        return

    color = COLOR_BAD if missing else COLOR_OK
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    tag = f"#{track_id} {zone}"
    if missing:
        tag += " | " + ",".join(C.label_vi(m) for m in missing)
    (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 8, y1), color, -1)
    cv2.putText(frame, tag, (x1 + 4, max(12, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (12, 12, 12), 1, cv2.LINE_AA)

    # Nhan trang thai tung item ben trong bbox
    y = y1 + 16
    for item in required:
        st = state.status.get(item, "unknown")
        if st == "ok":
            mark, c = f"+ {C.label_vi(item)}", COLOR_OK
        elif st == "missing":
            mark, c = f"- {C.label_vi(item)}", COLOR_BAD
        else:
            continue
        cv2.putText(frame, mark, (x1 + 6, min(y2 - 4, y)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, c, 1, cv2.LINE_AA)
        y += 15


def draw_hud(frame: np.ndarray, cam_name: str, fps: float, persons: int,
             violations: int, online: bool) -> None:
    h = frame.shape[0]
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 30), (24, 26, 30), -1)
    dot = COLOR_OK if online else COLOR_BAD
    cv2.circle(frame, (14, 15), 5, dot, -1)
    text = f"{cam_name}  |  {fps:4.1f} fps  |  nguoi: {persons}  |  vi pham: {violations}"
    cv2.putText(frame, text, (28, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                COLOR_INFO, 1, cv2.LINE_AA)
    if not online:
        cv2.putText(frame, "MAT KET NOI", (frame.shape[1] - 160, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_BAD, 2, cv2.LINE_AA)


def draw_polygon(frame: np.ndarray, polygon: list[list[float]] | None,
                 zone: str) -> None:
    if not polygon or len(polygon) < 3:
        return
    pts = np.array([[int(x), int(y)] for x, y in polygon], dtype=np.int32)
    overlay = frame.copy()
    cv2.fillPoly(overlay, [pts], (40, 120, 40))
    cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, frame)
    cv2.polylines(frame, [pts], True, (120, 200, 120), 1, cv2.LINE_AA)
    cv2.putText(frame, zone, (int(pts[:, 0].min()) + 6, int(pts[:, 1].min()) + 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 220, 160), 1, cv2.LINE_AA)


def point_in_polygon(pt: tuple[float, float], poly: list[list[float]]) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1):
            inside = not inside
    return inside


# --------------------------------------------------------------------------- #
# Worker
# --------------------------------------------------------------------------- #
@dataclass
class CameraSpec:
    id: str
    name: str
    source: str
    zone: str = "default"
    enabled: bool = True
    polygon: list[list[float]] | None = None
    width: int = 1280
    height: int = 720
    speed: float = 1.0


class CameraWorker(threading.Thread):
    def __init__(
        self,
        spec: CameraSpec,
        detector: PPEDetector,
        rules: RuleEngine,
        alert_mgr: AlertManager,
        evidence: EvidenceStore,
        db: Database,
        cfg: dict,
        root: Path,
        bus=None,
        sounder=None,
    ):
        super().__init__(daemon=True, name=f"cam-{spec.id}")
        self.spec = spec
        self.detector = detector
        self.rules = rules
        self.alert_mgr = alert_mgr
        self.evidence = evidence
        self.db = db
        self.cfg = cfg
        self.root = root
        self.bus = bus
        self.sounder = sounder

        self.infer_stride = max(1, int(cfg.get("infer_stride", 2)))
        self.clip_seconds = float(cfg.get("clip_seconds", 6.0))
        self.buffer: deque[tuple[float, np.ndarray]] = deque(maxlen=int(self.clip_seconds * 25))
        self.tracker = PersonTracker(
            iou_threshold=float(cfg.get("iou_threshold", 0.30)),
            max_age=int(cfg.get("max_age", 30)),
            min_hits=int(cfg.get("min_hits", 3)),
        )

        self._lock = threading.Lock()
        self._latest_jpeg: bytes | None = None
        self._latest_frame: np.ndarray | None = None
        self._annotated: np.ndarray | None = None
        self._state_cache: dict[int, PersonState] = {}
        self._display: list[tuple[int, Box, PersonState, bool]] = []
        self._display_tracks: dict[int, object] = {}
        self._running = threading.Event()
        self._running.set()
        self._online = False
        self._fps = 0.0
        self._persons = 0
        self._recent_alerts: deque[float] = deque(maxlen=64)
        self._last_status_push = 0.0
        self._frame_count = 0
        self._last_time = time.time()

    # ---------------- API cho server ----------------
    def stop(self) -> None:
        self._running.clear()

    def latest(self) -> tuple[bytes | None, np.ndarray | None]:
        with self._lock:
            return self._latest_jpeg, None if self._latest_frame is None else self._latest_frame.copy()

    def status(self) -> dict:
        now = time.time()
        recent = sum(1 for t in self._recent_alerts if now - t < 300)
        return {
            "id": self.spec.id,
            "name": self.spec.name,
            "zone": self.spec.zone,
            "online": self._online,
            "fps": round(self._fps, 1),
            "persons": self._persons,
            "alerts_5m": recent,
            "resolution": list(self._latest_frame.shape[1::-1]) if self._latest_frame is not None else None,
        }

    # ---------------- vong lap ----------------
    def run(self) -> None:
        retry_delay = 2.0
        while self._running.is_set():
            source: Source | None = None
            try:
                source = make_source(self.spec.source, self.cfg, self.root)
                self._online = True
                self.db.log_event("info", self.spec.id, "Bat dau nhan tin hieu camera")
                self._loop(source)
            except Exception as exc:
                self._online = False
                log.warning("[%s] loi nguon hinh: %s", self.spec.id, exc)
                self.db.log_event("error", self.spec.id, f"Loi nguon hinh: {exc}")
                self.db.update_status(self.spec.id, False, 0, 0, 0, str(exc))
                if self._running.is_set():
                    time.sleep(retry_delay)
                    retry_delay = min(30.0, retry_delay * 1.5)
            finally:
                if source is not None:
                    source.release()
        self._online = False
        self.db.update_status(self.spec.id, False, 0, 0, 0, "da dung")

    def _loop(self, source: Source) -> None:
        required = self.rules.required_for(self.spec.zone)
        consecutive_fail = 0

        while self._running.is_set():
            ok, frame = source.read()
            if not ok or frame is None:
                consecutive_fail += 1
                self._online = False
                if consecutive_fail > 30:
                    raise RuntimeError("mat luong khung hinh")
                time.sleep(0.2)
                continue
            consecutive_fail = 0
            self._online = True
            self._frame_count += 1

            if self._frame_count % self.infer_stride != 0:
                # Khung khong nhan dien: ve lai overlay tren khung moi, day box
                # theo van toc track -> chuyen dong muot, khong nhap nhay
                self._advance_display()
                self._encode(self._annotate(frame, self._display, time.time()))
                continue

            t0 = time.perf_counter()
            detections = self.detector.detect(frame)
            latency_ms = (time.perf_counter() - t0) * 1000.0

            # Buffer cho clip bang chung
            self.buffer.append((time.time(), frame.copy()))

            persons = [d for d in detections if C.is_person(d.cls_name)]
            tracks = self.tracker.update([{"bbox": d.bbox, "conf": d.conf} for d in persons])
            states = associate(detections, self.detector.known_items)
            self._person_states = states
            self._persons = len(states)

            # Ghep track <-> state bang IoU lon nhat
            mapping = _match(states, tracks)
            now = time.time()

            # Chi track co nhan dien that trong khung nay moi duoc danh gia vi pham
            fresh_ids: set[int] = set()
            for track, state in mapping:
                if track.misses == 0:
                    fresh_ids.add(track.track_id)
                    self._state_cache[track.track_id] = state

            # Track vua thieu detection: giu state cu de box khong tat
            in_mapping = {tr.track_id for tr, _ in mapping}
            for track in tracks:
                if track.track_id in fresh_ids or track.track_id in in_mapping:
                    continue
                cached = self._state_cache.get(track.track_id)
                if cached is not None:
                    mapping.append((track, cached))

            for track, state in mapping:
                if track.track_id not in fresh_ids:
                    continue
                zone = self._zone_of(state.bbox)
                required = self.rules.required_for(zone)
                violation = self.rules.update(self.spec.id, track.track_id, state, zone, now)
                if violation:
                    self._fire(violation, state, frame, zone, track.track_id, required)

            # Danh sach hien thi: (track_id, bbox, state, ghost)
            self._display = [
                (tr.track_id, tr.bbox, st, tr.track_id not in fresh_ids)
                for tr, st in mapping
            ]
            self._display_tracks = {t.track_id: t for t in tracks}

            # Don dep dinh ky
            if self._frame_count % 600 == 0:
                self.rules.gc()
                self._prune_state_cache()

            self._fps = 0.85 * self._fps + 0.15 * (1000.0 / max(1.0, latency_ms * self.infer_stride))
            self._encode(self._annotate(frame, self._display, now))
            self.db.update_status(self.spec.id, True, self._fps, latency_ms, self._persons, None)

            self._emit_status(now)

    def _prune_state_cache(self, max_entries: int = 512) -> None:
        if len(self._state_cache) <= max_entries:
            return
        # Xoa cac track khong con trong tracker
        alive = {t.track_id for t in self.tracker.tracks}
        for tid in [k for k in self._state_cache if k not in alive]:
            self._state_cache.pop(tid, None)

    def _advance_display(self) -> None:
        """Day bbox hien thi theo van toc track de chuyen dong lien tuc."""
        if not self._display:
            return
        moved = []
        for tid, bbox, st, ghost in self._display:
            tr = self._display_tracks.get(tid)
            if tr is not None:
                dx, dy = tr.velocity
                bbox = (bbox[0] + dx, bbox[1] + dy, bbox[2] + dx, bbox[3] + dy)
                # Tao ban sao: khong duoc sua state goc trong cache
                st = replace(st, bbox=bbox)
            moved.append((tid, bbox, st, ghost))
        self._display = moved

    def _annotate(self, frame: np.ndarray, display: list, now: float):
        out = frame.copy()
        draw_polygon(out, self.spec.polygon, self.spec.zone)
        for tid, bbox, state, ghost in display:
            zone = self._zone_of(bbox)
            required = self.rules.required_for(zone)
            draw_person(out, state, tid, required, zone, ghost=ghost, bbox=bbox)
        draw_hud(out, self.spec.name, self._fps, self._persons,
                 len(self._recent_alerts), self._online)
        return out

    def _zone_of(self, bbox: Box) -> str:
        if self.spec.polygon and len(self.spec.polygon) >= 3:
            foot = ((bbox[0] + bbox[2]) / 2.0, bbox[3])
            if not point_in_polygon(foot, self.spec.polygon):
                return "__outside__"
        return self.spec.zone

    def _encode(self, frame: np.ndarray) -> None:
        with self._lock:
            self._latest_frame = frame
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
        if ok:
            with self._lock:
                self._latest_jpeg = buf.tobytes()

    def _fire(self, violation, state: PersonState, frame: np.ndarray,
              zone: str, track_id: int, required: list[str]) -> None:
        self._recent_alerts.append(violation.ts)

        # Anh bang chung co overlay rieng
        snap = frame.copy()
        draw_person(snap, state, track_id, required, zone)
        draw_hud(snap, self.spec.name, self._fps, self._persons,
                 len(self._recent_alerts), self._online)
        meta = self.evidence.save(
            self.spec.id, track_id, violation.missing, snap, self.buffer,
            zone, violation.confidence,
        )
        vid = self.db.add_violation(
            self.spec.id, track_id, violation.missing, zone,
            violation.ts, meta["image"], meta["clip"], violation.confidence,
        )

        text = compose_text(self.spec.name, self.spec.id, track_id,
                            violation.missing, zone, violation.ts, violation.confidence)
        self.alert_mgr.submit({
            "id": vid,
            "cam_id": self.spec.id,
            "cam_name": self.spec.name,
            "track_id": track_id,
            "missing": violation.missing,
            "zone": zone,
            "ts": violation.ts,
            "confidence": round(violation.confidence, 4),
            "image": meta["image"],
            "image_url": f"/{meta['image']}" if meta["image"] else None,
            "clip": meta["clip"],
            "text": text,
        }, snap)

        if self.bus is not None:
            self.bus.publish("violation", {
                "id": vid,
                "cam_id": self.spec.id,
                "cam_name": self.spec.name,
                "track_id": track_id,
                "missing": violation.missing,
                "zone": zone,
                "ts": violation.ts,
                "image_url": f"/{meta['image']}" if meta["image"] else None,
                "text": text,
            })

        # Canh bao tai cho: loa IP / TTS
        if self.sounder is not None:
            from app.sounder import compose_speech

            self.sounder.announce(
                self.spec.id,
                compose_speech(self.spec.name, violation.missing),
            )

        log.info("[%s] vi pham #%s thieu %s", self.spec.id, track_id, violation.missing)

    def _emit_status(self, now: float) -> None:
        if self.bus is None or now - self._last_status_push < 1.0:
            return
        self._last_status_push = now
        self.bus.publish("status", self.status())


def _match(states: list[PersonState], tracks: list) -> list[tuple]:
    """Ghep moi state voi mot track theo IoU lon nhat."""
    from app.tracker import iou

    pairs: list[tuple[float, int, int]] = []
    for si, st in enumerate(states):
        for ti, tr in enumerate(tracks):
            score = iou(st.bbox, tr.bbox)
            if score > 0.2:
                pairs.append((score, si, ti))
    pairs.sort(reverse=True)

    used_s: set[int] = set()
    used_t: set[int] = set()
    out = []
    for _, si, ti in pairs:
        if si in used_s or ti in used_t:
            continue
        used_s.add(si)
        used_t.add(ti)
        out.append((tracks[ti], states[si]))

    # Track chua ghep: van cho hien thi voi state gan nhat
    for ti, tr in enumerate(tracks):
        if ti in used_t:
            continue
        nearest = _nearest_state(tr, states, used_s)
        if nearest is not None:
            out.append((tr, nearest))
    return out


def _nearest_state(track, states: list[PersonState], used: set[int]):
    from app.tracker import iou

    best, best_score = None, 0.05
    for si, st in enumerate(states):
        if si in used:
            continue
        score = iou(track.bbox, st.bbox)
        if score > best_score:
            best, best_score = st, score
    return best
