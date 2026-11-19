"""Gui canh bao da kenh: Telegram, webhook, MQTT, luu noi bo."""

from __future__ import annotations

import json
import logging
import queue
import smtplib
import threading
import time
from email.message import EmailMessage
from typing import Any

import cv2
import numpy as np

import app.classes as C

log = logging.getLogger("ppe.alerts")


def compose_text(cam_name: str, cam_id: str, track_id: int, missing: list[str],
                 zone: str, when: float, confidence: float) -> str:
    labels = ", ".join(C.label_vi(m) for m in missing)
    return (
        f"⚠️ VI PHẠM PPE\n"
        f"Camera: {cam_name} ({cam_id})\n"
        f"Khu vực: {zone}\n"
        f"Đối tượng: #{track_id}\n"
        f"Thiếu: {labels}\n"
        f"Độ tin cậy: {confidence:.0%}\n"
        f"Thời gian: {time.strftime('%H:%M:%S %d/%m/%Y', time.localtime(when))}"
    )


class AlertManager:
    """Hang doi gui canh bao tren mot luong nen, khong chan pipeline."""

    def __init__(self, cfg: dict, evidence_url: str = "/evidence"):
        self.cfg = cfg or {}
        self.evidence_url = evidence_url.rstrip("/")
        self._q: queue.Queue[dict] = queue.Queue(maxsize=256)
        self._worker = threading.Thread(target=self._run, daemon=True, name="alert-sender")
        self._worker.start()
        self._stats = {"sent": 0, "failed": 0, "dropped": 0}

    # ---------- API ----------
    def submit(self, payload: dict, frame: np.ndarray | None = None) -> None:
        payload = dict(payload)
        payload["frame"] = frame
        try:
            self._q.put_nowait(payload)
        except queue.Full:
            self._stats["dropped"] += 1

    def stats(self) -> dict:
        return dict(self._stats, queued=self._q.qsize())

    # ---------- worker ----------
    def _run(self) -> None:
        while True:
            payload = self._q.get()
            try:
                self._deliver(payload)
            except Exception as exc:  # pragma: no cover - phu thuoc mang ngoai
                self._stats["failed"] += 1
                log.warning("gui canh bao that bai: %s", exc)
            finally:
                self._q.task_done()
                # Gian nhip de tranh spam API ben ngoai
                time.sleep(float(self.cfg.get("min_interval_sec", 1.0)))

    def _deliver(self, p: dict) -> None:
        text = p["text"]
        frame = p.get("frame")
        channels = 0

        tg = self.cfg.get("telegram") or {}
        if tg.get("enabled") and tg.get("token") and tg.get("chat_id"):
            channels += 1
            self._telegram(tg, text, frame)

        wh = self.cfg.get("webhook") or {}
        if wh.get("enabled") and wh.get("url"):
            channels += 1
            self._webhook(wh, p)

        mq = self.cfg.get("mqtt") or {}
        if mq.get("enabled") and mq.get("host"):
            channels += 1
            self._mqtt(mq, p)

        if self.cfg.get("email", {}).get("enabled"):
            channels += 1
            self._email(self.cfg["email"], text, p)

        if channels:
            self._stats["sent"] += 1

    def _telegram(self, tg: dict, text: str, frame: np.ndarray | None) -> None:
        import requests

        base = f"https://api.telegram.org/bot{tg['token']}"
        if frame is not None:
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
            if ok:
                requests.post(
                    f"{base}/sendPhoto",
                    data={"chat_id": str(tg["chat_id"]), "caption": text[:1024]},
                    files={"photo": ("violation.jpg", buf.tobytes(), "image/jpeg")},
                    timeout=12,
                )
                return
        requests.post(
            f"{base}/sendMessage",
            data={"chat_id": str(tg["chat_id"]), "text": text[:4096]},
            timeout=12,
        )

    def _webhook(self, wh: dict, p: dict) -> None:
        import requests

        body: dict[str, Any] = {k: v for k, v in p.items() if k != "frame"}
        r = requests.post(wh["url"], json=body, timeout=10,
                          headers=wh.get("headers") or {})
        r.raise_for_status()

    def _mqtt(self, mq: dict, p: dict) -> None:
        import paho.mqtt.publish as publish

        payload = json.dumps({k: v for k, v in p.items() if k != "frame"}, ensure_ascii=False)
        publish.single(
            mq.get("topic", "ppe/alerts"),
            payload,
            hostname=mq.get("host", "localhost"),
            port=int(mq.get("port", 1883)),
            qos=int(mq.get("qos", 0)),
            retain=bool(mq.get("retain", False)),
        )

    def _email(self, em: dict, text: str, p: dict) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"[PPE] Vi pham tai {p.get('cam_id', '?')}"
        msg["From"] = em.get("from", "ppe@localhost")
        msg["To"] = ", ".join(em.get("to", []))
        msg.set_content(text)
        with smtplib.SMTP(em.get("host", "localhost"), int(em.get("port", 25)), timeout=12) as s:
            if em.get("tls"):
                s.starttls()
            if em.get("user"):
                s.login(em["user"], em.get("password", ""))
            s.send_message(msg)
