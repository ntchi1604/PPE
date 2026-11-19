"""Canh bao tai cho: loa IP, coi hut, TTS tren may chu.

Ba kieu thiet bi:
  - Loa IP nhan HTTP GET co tham so text (Dahua, Hikvision ISAPI, thiet bi tu che)
  - Loa IP nhan HTTP POST JSON
  - Loa tren may chay server (Windows SAPI qua PowerShell)
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import quote

log = logging.getLogger("ppe.sounder")


class Sounder:
    """Hang doi phat am thanh, khong chan pipeline."""

    def __init__(self, cfg: dict | None):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled", False))
        self.mode = self.cfg.get("mode", "http_get")  # http_get | http_post | local_tts | mqtt
        self.url = self.cfg.get("url", "")
        self.method = self.cfg.get("method", "GET").upper()
        self.payload_key = self.cfg.get("payload_key", "text")
        self.extra = self.cfg.get("extra", {}) or {}
        self.cooldown = float(self.cfg.get("cooldown_sec", 20))
        self.volume = int(self.cfg.get("volume", 90))
        self.voice_rate = int(self.cfg.get("rate", 2))

        self._q: "queue.Queue[tuple[str, float]]" = queue.Queue(maxsize=64)
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self.stats = {"played": 0, "failed": 0, "skipped": 0}

        if self.enabled:
            threading.Thread(target=self._run, daemon=True, name="sounder").start()

    def announce(self, cam_id: str, message: str) -> None:
        if not self.enabled:
            return
        now = time.time()
        with self._lock:
            if now - self._last.get(cam_id, 0.0) < self.cooldown:
                self.stats["skipped"] += 1
                return
            self._last[cam_id] = now
        try:
            self._q.put_nowait((message, now))
        except queue.Full:
            self.stats["skipped"] += 1

    def _run(self) -> None:
        while True:
            message, _ = self._q.get()
            try:
                self._play(message)
                self.stats["played"] += 1
            except Exception as exc:  # pragma: no cover
                self.stats["failed"] += 1
                log.warning("loa that bai: %s", exc)
            finally:
                self._q.task_done()

    def _play(self, message: str) -> None:
        if self.mode == "local_tts":
            self._local_tts(message)
        elif self.mode == "http_post":
            self._http_post(message)
        elif self.mode == "mqtt":
            self._mqtt(message)
        else:
            self._http_get(message)

    # ---------------- backends ----------------
    def _http_get(self, message: str) -> None:
        import requests

        params = dict(self.extra)
        params[self.payload_key] = message
        r = requests.get(self.url, params=params, timeout=4)
        r.raise_for_status()

    def _http_post(self, message: str) -> None:
        import requests

        body = dict(self.extra)
        body[self.payload_key] = message
        r = requests.post(self.url, json=body, timeout=4)
        r.raise_for_status()

    def _mqtt(self, message: str) -> None:
        import paho.mqtt.publish as publish

        publish.single(
            self.cfg.get("topic", "ppe/sounder"),
            json.dumps({"text": message}, ensure_ascii=False),
            hostname=self.cfg.get("host", "localhost"),
            port=int(self.cfg.get("port", 1883)),
        )

    def _local_tts(self, message: str) -> None:
        """Doc bang SAPI cua Windows, khong can thu vien ngoai."""
        if sys.platform != "win32":
            raise RuntimeError("local_tts chi ho tro Windows")
        safe = message.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"$s.Volume = {self.volume};"
            f"$s.Rate = {self.voice_rate};"
            f"$s.Speak('{safe}')"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=25, check=False,
        )


def compose_speech(cam_name: str, missing: list[str]) -> str:
    """Cau thong bao ngan, ro rang, doc duoc tai cong truong on."""
    import app.classes as C

    if not missing:
        return f"Cảnh báo. Camera {cam_name}. Kiểm tra an toàn."
    labels = ", ".join(C.label_vi(m) for m in missing)
    return (
        f"Chú ý. Có người không đeo {labels} tại {cam_name}. "
        f"Đề nghị bổ sung ngay."
    )
