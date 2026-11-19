"""Diem vao: nap cau hinh, khoi tao model, chay worker camera va API server."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from app.alerting import AlertManager
from app.api import EventBus, create_app
from app.config import Config
from app.db import Database
from app.detector import DetectorUnavailable, PPEDetector
from app.evidence import EvidenceStore
from app.pipeline import CameraSpec, CameraWorker
from app.rules import RuleEngine

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("ppe")


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)-14s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(ROOT / "data" / "ppe.log", encoding="utf-8"),
        ],
    )

    class _DropDeprecation(logging.Filter):
        """Ultralytics 8.4 canh bao tham so `half` moi lan predict: bo qua."""

        def filter(self, record: logging.LogRecord) -> bool:
            return "'half' is deprecated" not in record.getMessage()

    drop = _DropDeprecation()
    for name in ("ultralytics", "ultralytics.utils", "ultralytics.engine.predictor"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.ERROR)
        lg.addFilter(drop)
    logging.getLogger().addFilter(drop)


def spec_from_dict(cam: dict, cfg: Config) -> CameraSpec:
    return CameraSpec(
        id=cam["id"],
        name=cam.get("name", cam["id"]),
        source=str(cam.get("source", cam["id"])),
        zone=cam.get("zone", "default"),
        enabled=bool(cam.get("enabled", True)),
        polygon=cam.get("polygon"),
        width=int(cfg.get("camera.width", 1280)),
        height=int(cfg.get("camera.height", 720)),
        speed=float(cfg.get("camera.demo_speed", 1.0)),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser("ppe-monitor", description="He thong giam sat PPE cong truong")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--camera", action="append", default=[],
                    metavar="ID=SOURCE",
                    help="Them camera tam thoi, vd: --camera cam1=0 --camera cam2=rtsp://...")
    ap.add_argument("--demo", action="store_true", help="Chay camera demo tu anh mau")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)

    cfg = Config(args.config)
    cfg.ensure_dirs()
    (ROOT / "data").mkdir(exist_ok=True)
    setup_logging(args.verbose)

    db = Database(cfg.path_of("app.data_dir", "data") / "ppe.db")
    evidence = EvidenceStore(cfg.path_of("app.evidence_dir", "evidence"))
    bus = EventBus()

    # ---------------- model ----------------
    weights = cfg.path_of("model.weights", "weights/ppe_yolov8.pt")
    try:
        detector = PPEDetector(
            weights=weights,
            device=str(cfg.get("model.device", "auto")),
            imgsz=int(cfg.get("model.imgsz", 640)),
            half=bool(cfg.get("model.half", True)),
            conf_person=float(cfg.get("model.conf_person", 0.35)),
            conf_ppe=float(cfg.get("model.conf_ppe", 0.25)),
            iou=float(cfg.get("model.iou", 0.5)),
            max_det=int(cfg.get("model.max_det", 300)),
        )
    except DetectorUnavailable as exc:
        log.error("Khong nap duoc model: %s", exc)
        log.error("Chay:  python scripts/download_model.py")
        return 2

    log.info("Model: %s | device=%s | half=%s | items=%s",
             detector.weights, detector.device, detector.half,
             sorted(detector.known_items))

    # ---------------- rule engine + alerts ----------------
    zones = cfg.get("rules.zones", {}) or {}
    rules = RuleEngine(
        required_by_zone={k: list(v.get("required", [])) for k, v in zones.items()},
        confirm_frames=int(cfg.get("rules.confirm_frames", 12)),
        cooldown_sec=float(cfg.get("rules.cooldown_sec", 180)),
        unknown_grace=int(cfg.get("rules.unknown_grace", 0)),
        known_items=detector.known_items,
    )
    alert_mgr = AlertManager(cfg.get("alerts", {}) or {})

    from app.sounder import Sounder

    sounder = Sounder(cfg.get("sounder", {}) or {})
    if sounder.enabled:
        log.info("Loa canh bao: mode=%s target=%s", sounder.mode, sounder.url or "local")

    # ---------------- xac thuc + luu tru ----------------
    from app.auth import Auth

    auth = Auth(cfg.get("auth", {}) or {})
    if auth.enabled:
        log.info("Xac thuc: bat buoc dang nhap | %s user | localhost mien=%s",
                 len(auth.users), auth.allow_localhost)

    from app.retention import Retention

    retention = Retention(
        db,
        cfg.path_of("app.evidence_dir", "evidence"),
        cfg.get("retention", {}) or {},
    )
    retention.start()

    # ---------------- camera ----------------
    workers: dict[str, CameraWorker] = {}
    pipeline_cfg = cfg.get("tracking", {}) or {}
    pipeline_cfg = {
        **pipeline_cfg,
        "infer_stride": cfg.get("model.infer_stride", 2),
        "clip_seconds": cfg.get("app.clip_seconds", 6),
        "width": cfg.get("camera.width", 1280),
        "height": cfg.get("camera.height", 720),
        "max_width": cfg.get("camera.max_width", 1920),
        "demo_speed": cfg.get("camera.demo_speed", 1.0),
    }

    def spawn_worker(cam: dict) -> CameraWorker:
        spec = spec_from_dict(cam, cfg)
        w = CameraWorker(spec, detector, rules, alert_mgr, evidence, db,
                         pipeline_cfg, ROOT, bus=bus, sounder=sounder)
        w.start()
        workers[spec.id] = w
        return w

    def stop_worker(cam_id: str) -> None:
        w = workers.pop(cam_id, None)
        if w:
            w.stop()
            w.join(timeout=5)

    def restart_worker(cam: dict) -> None:
        stop_worker(cam["id"])
        spawn_worker(cam)

    # Nap camera tu config + tham so dong lenh
    cam_list = list(cfg.cameras())
    for item in args.camera:
        if "=" not in item:
            log.error("Sai dinh dang --camera: %s", item)
            continue
        cid, src = item.split("=", 1)
        cam_list.append({"id": cid, "name": cid, "source": src, "zone": "default"})

    if args.demo or cfg.get("app.demo", False):
        demo_img = cfg.path_of("app.demo_image", "assets/demo_site.jpg")
        if demo_img.exists():
            cam_list.append({
                "id": "demo",
                "name": "Camera demo",
                "source": f"demo:{demo_img}",
                "zone": "default",
                "enabled": True,
            })
        else:
            log.warning("Khong thay anh demo: %s", demo_img)

    for cam in cam_list:
        db.upsert_camera(cam)
        if cam.get("enabled", True):
            spawn_worker(cam)

    # ---------------- app ----------------
    app = create_app({
        "db": db,
        "bus": bus,
        "cfg": cfg,
        "workers": workers,
        "detector": detector,
        "alert_mgr": alert_mgr,
        "sounder": sounder,
        "auth": auth,
        "retention": retention,
        "static_dir": ROOT / "static",
        "evidence_dir": evidence.root,
        "started_at": time.time(),
        "spawn_worker": spawn_worker,
        "stop_worker": stop_worker,
        "restart_worker": restart_worker,
    })

    host = args.host or str(cfg.get("app.host", "127.0.0.1"))
    port = args.port or int(cfg.get("app.port", 8000))
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
    log.info("Dashboard: %s", url)

    if not args.no_browser and cfg.get("app.open_browser", True):
        threading.Timer(1.6, lambda: webbrowser.open(url)).start()

    def _shutdown(*_):
        log.info("Dang dung he thong...")
        for cid in list(workers):
            stop_worker(cid)
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)
    except (ValueError, OSError):
        pass

    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
