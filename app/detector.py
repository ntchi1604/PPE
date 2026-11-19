"""Wrapper YOLO cho bai toan PPE. Mot model chia se giua cac camera, suy luan co khoa."""

from __future__ import annotations

import threading
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import logging

# Ultralytics 8.4 doi ten tham so `half` -> `quantize`, canh bao moi lan predict
warnings.filterwarnings("ignore", message=".*'half' is deprecated.*")


class _DropHalfWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "'half' is deprecated" not in record.getMessage()


for _name in ("ultralytics", "ultralytics.utils", "ultralytics.engine.predictor", ""):
    _lg = logging.getLogger(_name or None)
    if not any(isinstance(f, _DropHalfWarning) for f in _lg.filters):
        _lg.addFilter(_DropHalfWarning())

import app.classes as C


class DetectorUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Detection:
    cls_name: str      # ten chuan noi bo
    raw_name: str      # ten lop goc trong model
    conf: float
    bbox: tuple[float, float, float, float]

    @property
    def cx(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2.0

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2.0


class PPEDetector:
    """Boc Ultralytics YOLO. Thread-safe qua khoa suy luan."""

    def __init__(
        self,
        weights: str | Path,
        device: str = "auto",
        imgsz: int = 640,
        half: bool = True,
        conf_person: float = 0.35,
        conf_ppe: float = 0.25,
        iou: float = 0.5,
        max_det: int = 300,
    ):
        from ultralytics import YOLO  # import tre: khoi dong nhanh khi chi xem API

        self.weights = str(weights)
        if not Path(self.weights).exists():
            raise DetectorUnavailable(f"Khong tim thay trong so: {self.weights}")

        self.model = YOLO(self.weights)
        self.names: dict[int, str] = dict(self.model.names)
        self.imgsz = imgsz
        self.conf_person = conf_person
        self.conf_ppe = conf_ppe
        self.iou = iou
        self.max_det = max_det

        import torch

        if device == "auto":
            device = "0" if torch.cuda.is_available() else "cpu"
        self.device = device
        self.half = bool(half and str(device) != "cpu" and torch.cuda.is_available())

        # Warm-up: nap CUDA context va JIT truoc khung hinh dau tien
        dummy = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
        self._infer(dummy)

        self.known_items = self._known_items()

    def _known_items(self) -> set[str]:
        """Cac PPE ma model thuc su co lop duong tinh."""
        items = set()
        for name in self.names.values():
            norm = C.normalize(name)
            if C.is_negative(norm):
                items.add(C.positive_of(norm))
            elif not C.is_person(norm) and not norm.startswith("equipment:"):
                items.add(norm)
        return items

    def _infer(self, frame: np.ndarray):
        return self.model.predict(
            source=frame,
            conf=min(self.conf_person, self.conf_ppe),
            iou=self.iou,
            imgsz=self.imgsz,
            max_det=self.max_det,
            device=self.device,
            half=self.half,
            verbose=False,
        )

    def detect(self, frame: np.ndarray) -> list[Detection]:
        # Mot model chia se giua nhieu luong camera: serialize de tranh race trong torch
        with _LOCK:
            results = self._infer(frame)

        out: list[Detection] = []
        for r in results:
            if r.boxes is None:
                continue
            for b in r.boxes:
                cls_id = int(b.cls.item())
                raw = self.names.get(cls_id, str(cls_id))
                norm = C.normalize(raw)
                conf = float(b.conf.item())

                if C.is_person(norm):
                    if conf < self.conf_person:
                        continue
                elif norm.startswith("equipment:"):
                    if conf < self.conf_ppe:
                        continue
                else:
                    if conf < self.conf_ppe:
                        continue

                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
                out.append(Detection(norm, raw, conf, (x1, y1, x2, y2)))
        return out

    def info(self) -> dict:
        return {
            "weights": self.weights,
            "device": self.device,
            "half": self.half,
            "imgsz": self.imgsz,
            "classes": self.names,
            "items": sorted(self.known_items),
        }


_LOCK = threading.Lock()
