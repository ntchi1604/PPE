"""Rule engine: lam muot theo thoi gian, xac nhan vi pham, chong bao gia."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

import app.classes as C
from app.associator import PersonState

# Trang thai muot theo track
_ALPHA = 0.55          # he so EMA: cang cao cang bam khung hinh moi
_UNKNOWN_DECAY = 0.85  # dong gop cua 'unknown' vao bo dem vi pham


@dataclass
class TrackMemory:
    """Bo nho muot theo track_id: diem tin cay duong/am va chuoi vi pham."""
    pos: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    neg: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    streak: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_seen: float = 0.0
    zone: str = "default"


@dataclass
class Violation:
    track_id: int
    missing: list[str]
    zone: str
    confidence: float
    ts: float


class RuleEngine:
    """Xu ly tat ca camera. Khoa theo (cam_id, track_id)."""

    def __init__(
        self,
        required_by_zone: dict[str, list[str]],
        confirm_frames: int = 12,
        cooldown_sec: float = 180.0,
        unknown_grace: int = 0,
        known_items: set[str] | None = None,
    ):
        self.required_by_zone = required_by_zone
        self.confirm_frames = max(1, confirm_frames)
        self.cooldown_sec = cooldown_sec
        self.unknown_grace = unknown_grace
        self.known_items = known_items or set()
        self._mem: dict[tuple[str, int], TrackMemory] = {}
        self._last_alert: dict[tuple[str, int, str], float] = {}

    def required_for(self, zone: str) -> list[str]:
        if zone == "__outside__":
            return []
        items = self.required_by_zone.get(zone) or self.required_by_zone.get("default") or []
        # Chi ap dung item ma model thuc su nhan dien duoc
        return [i for i in items if i in self.known_items]

    def update(
        self,
        cam_id: str,
        track_id: int,
        state: PersonState,
        zone: str,
        now: float | None = None,
    ) -> Violation | None:
        now = now or time.time()
        key = (cam_id, track_id)
        mem = self._mem.setdefault(key, TrackMemory())
        mem.last_seen = now
        mem.zone = zone

        required = set(self.required_for(zone))

        for item in self.known_items:
            p = state.positive.get(item, 0.0)
            n = state.negative.get(item, 0.0)
            mem.pos[item] = _ALPHA * p + (1 - _ALPHA) * mem.pos[item]
            mem.neg[item] = _ALPHA * n + (1 - _ALPHA) * mem.neg[item]

        for item in self.known_items:
            if item not in required:
                mem.streak[item] = 0
                continue

            status = self._smoothed_status(mem, item)
            if status == "missing":
                mem.streak[item] += 1
            elif status == "ok":
                mem.streak[item] = 0
            else:  # unknown: tru dan thay vi reset tuc thi
                if self.unknown_grace and mem.streak[item] >= self.confirm_frames:
                    mem.streak[item] = max(0, mem.streak[item] - 1)
                else:
                    mem.streak[item] = int(mem.streak[item] * _UNKNOWN_DECAY)

        confirmed = [i for i in required if mem.streak[i] >= self.confirm_frames]
        if not confirmed:
            return None

        # Cooldown theo (camera, track, bo vi pham)
        signature = ",".join(sorted(confirmed))
        ck = (cam_id, track_id, signature)
        if now - self._last_alert.get(ck, 0.0) < self.cooldown_sec:
            return None
        self._last_alert[ck] = now

        # Reset chuoi de khong ban lai lien tuc sau khi da canh bao
        for item in confirmed:
            mem.streak[item] = 0

        conf = sum(mem.neg[i] for i in confirmed) / max(1, len(confirmed))
        return Violation(track_id, sorted(confirmed), zone, conf, now)

    @staticmethod
    def _smoothed_status(mem: TrackMemory, item: str) -> str:
        p, n = mem.pos[item], mem.neg[item]
        if p >= 0.22 and p >= n * 1.05:
            return "ok"
        if n >= 0.18 and n > p:
            return "missing"
        return "unknown"

    def gc(self, max_idle_sec: float = 300.0, now: float | None = None) -> None:
        now = now or time.time()
        stale = [k for k, m in self._mem.items() if now - m.last_seen > max_idle_sec]
        for k in stale:
            self._mem.pop(k, None)
        for k in [k for k, ts in self._last_alert.items() if now - ts > max_idle_sec * 4]:
            self._last_alert.pop(k, None)

    def snapshot(self, cam_id: str, track_id: int) -> dict:
        mem = self._mem.get((cam_id, track_id))
        if not mem:
            return {}
        return {
            "pos": {k: round(v, 3) for k, v in mem.pos.items()},
            "neg": {k: round(v, 3) for k, v in mem.neg.items()},
            "streak": dict(mem.streak),
        }
