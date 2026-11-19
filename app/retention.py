"""Don dep du lieu cu: vi pham, anh, clip, nhat ky.

Chay trong mot luong nen cua server, kiem tra moi 30 phut.

Chinh trong config.yaml:

    retention:
      enabled: true
      violation_days: 180      # giu ban ghi vi pham bao lau
      evidence_days: 60        # giu anh/clip bao lau (nang hon nhieu)
      event_days: 30
      keep_acknowledged: true  # giu ban ghi da xu ly lau hon (bang chung phap ly)
      ack_days: 365
      max_gb: 20               # tran dung luong thu muc evidence
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path

log = logging.getLogger("ppe.retention")


class Retention:
    def __init__(self, db, evidence_dir: Path, cfg: dict | None):
        self.db = db
        self.evidence_dir = Path(evidence_dir)
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled", True))
        self.violation_days = float(self.cfg.get("violation_days", 180))
        self.evidence_days = float(self.cfg.get("evidence_days", 60))
        self.event_days = float(self.cfg.get("event_days", 30))
        self.keep_acknowledged = bool(self.cfg.get("keep_acknowledged", True))
        self.ack_days = float(self.cfg.get("ack_days", 365))
        self.max_gb = float(self.cfg.get("max_gb", 0))  # 0 = khong gioi han
        self.interval_sec = float(self.cfg.get("interval_sec", 1800))

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_run: float = 0.0
        self.last_stats: dict = {}

    # ---------------- vong doi ----------------
    def start(self) -> None:
        if not self.enabled:
            log.info("Don dep du lieu: tat")
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="retention")
        self._thread.start()
        log.info(
            "Don dep du lieu: vi pham %g ngay, bang chung %g ngay, su kien %g ngay",
            self.violation_days, self.evidence_days, self.event_days,
        )

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # Cho 60s sau khoi dong de khong tranh I/O voi luc nap model
        if self._stop.wait(60):
            return
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:  # pragma: no cover
                log.warning("don dep that bai: %s", exc)
            if self._stop.wait(self.interval_sec):
                return

    # ---------------- thao tac ----------------
    def run_once(self) -> dict:
        now = time.time()
        stats = {"violations": 0, "files": 0, "bytes": 0, "events": 0, "trimmed": 0}

        # 1. Ban ghi vi pham qua han (giu lai ban da xu ly neu cau hinh)
        cutoff = now - self.violation_days * 86400
        if self.keep_acknowledged:
            ack_cutoff = now - self.ack_days * 86400
            stats["violations"] = self.db.prune_violations(
                unack_before=cutoff, ack_before=ack_cutoff
            )
        else:
            stats["violations"] = self.db.prune_violations(before=cutoff)

        # 2. Nhat ky su kien
        stats["events"] = self.db.prune_events(now - self.event_days * 86400)

        # 3. Tep bang chung: xoa theo ngay, roi theo dung luong
        ev_cutoff = now - self.evidence_days * 86400
        files, total = self._prune_files(ev_cutoff)
        stats["files"] = files
        stats["bytes"] = total

        # 4. Tran dung luong: xoa cu nhat truoc cho toi khi duoi nguong
        if self.max_gb > 0:
            stats["trimmed"] = self._trim_to_size(self.max_gb * 1024 ** 3)

        # 5. Thu gon database
        if stats["violations"] or stats["events"]:
            try:
                self.db.vacuum()
            except Exception:
                pass

        self.last_run = now
        self.last_stats = stats
        if any(stats[k] for k in ("violations", "files", "events", "trimmed")):
            log.info(
                "Don dep: xoa %s vi pham, %s tep (%.1f MB), %s su kien, %s tep qua han dung luong",
                stats["violations"], stats["files"],
                stats["bytes"] / 1024 ** 2, stats["events"], stats["trimmed"],
            )
        return stats

    def _prune_files(self, older_than: float) -> tuple[int, int]:
        if not self.evidence_dir.exists():
            return 0, 0
        removed = 0
        freed = 0
        for p in self.evidence_dir.rglob("*"):
            if not p.is_file():
                continue
            try:
                if p.stat().st_mtime < older_than:
                    size = p.stat().st_size
                    p.unlink()
                    removed += 1
                    freed += size
            except OSError:
                continue
        # Xoa thu muc rong
        for d in sorted(self.evidence_dir.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            if d.is_dir():
                try:
                    d.rmdir()
                except OSError:
                    pass
        return removed, freed

    def _trim_to_size(self, limit_bytes: float) -> int:
        if not self.evidence_dir.exists():
            return 0
        files = [p for p in self.evidence_dir.rglob("*") if p.is_file()]
        total = sum(p.stat().st_size for p in files if p.exists())
        if total <= limit_bytes:
            return 0
        files.sort(key=lambda p: p.stat().st_mtime)
        removed = 0
        for p in files:
            if total <= limit_bytes:
                break
            try:
                size = p.stat().st_size
                p.unlink()
                total -= size
                removed += 1
            except OSError:
                continue
        return removed

    def disk_usage(self) -> dict:
        if not self.evidence_dir.exists():
            return {"files": 0, "bytes": 0, "gb": 0.0}
        files = [p for p in self.evidence_dir.rglob("*") if p.is_file()]
        total = sum(p.stat().st_size for p in files if p.exists())
        return {"files": len(files), "bytes": total, "gb": round(total / 1024 ** 3, 2)}

    def info(self) -> dict:
        free = 0
        try:
            free = shutil.disk_usage(str(self.evidence_dir)).free
        except OSError:
            pass
        return {
            "enabled": self.enabled,
            "violation_days": self.violation_days,
            "evidence_days": self.evidence_days,
            "last_run": self.last_run,
            "last_stats": self.last_stats,
            "evidence": self.disk_usage(),
            "disk_free_gb": round(free / 1024 ** 3, 1),
        }
