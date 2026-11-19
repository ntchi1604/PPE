"""Ghep PPE voi nguoi va tinh trang thai tuan thu theo tung vung co the.

Cach lam: bbox PPE phai co tam nam trong bbox nguoi (mo rong nhe) VA thuoc dung
dai doc cua vung co the. Sau do so sanh do tin cay lop duong tinh va lop am tinh.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import app.classes as C
from app.detector import Detection

Box = tuple[float, float, float, float]


def _region_band(box: Box, region: str) -> Box:
    x1, y1, x2, y2 = box
    h = y2 - y1
    lo, hi = C.REGIONS[region]
    return (x1, y1 + h * lo, x2, y1 + h * hi)


def _inside(point: tuple[float, float], box: Box, pad: float = 0.10) -> bool:
    cx, cy = point
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    return (x1 - w * pad) <= cx <= (x2 + w * pad) and (y1 - h * pad) <= cy <= (y2 + h * pad)


def _vertical_ratio(point_y: float, box: Box) -> float:
    y1, y2 = box[1], box[3]
    h = y2 - y1
    if h <= 0:
        return 0.5
    return max(0.0, min(1.0, (point_y - y1) / h))


def _region_for_ratio(ratio: float) -> str:
    """Vung chua ti le doc cua tam PPE."""
    for name in ("head", "torso", "hands", "feet"):
        lo, hi = C.REGIONS[name]
        if lo <= ratio <= hi:
            return name
    return "body"


@dataclass
class PersonState:
    """Trang thai tuan thu cua mot nguoi trong khung hinh hien tai."""
    bbox: Box
    person_conf: float
    # item -> conf lon nhat cua lop duong tinh / lop am tinh
    positive: dict[str, float] = field(default_factory=dict)
    negative: dict[str, float] = field(default_factory=dict)
    # item -> 'ok' | 'missing' | 'unknown'
    status: dict[str, str] = field(default_factory=dict)

    def missing_items(self) -> list[str]:
        return [i for i, s in self.status.items() if s == "missing"]


def associate(detections: list[Detection], known_items: set[str]) -> list[PersonState]:
    persons = [d for d in detections if C.is_person(d.cls_name)]
    ppe = [d for d in detections if not C.is_person(d.cls_name)]

    states: list[PersonState] = []
    for person in persons:
        state = PersonState(bbox=person.bbox, person_conf=person.conf)
        for item in known_items:
            state.positive[item] = 0.0
            state.negative[item] = 0.0

        for det in ppe:
            if det.cls_name.startswith("equipment:"):
                continue
            if not _inside((det.cx, det.cy), person.bbox):
                continue

            ratio = _vertical_ratio(det.cy, person.bbox)
            band = _region_for_ratio(ratio)

            if C.is_negative(det.cls_name):
                item = C.positive_of(det.cls_name)
                # Lop am tinh thuong nam sat dau / than: chi can tam trong nguoi
                if band in ("head", "torso", "hands", "feet"):
                    state.negative[item] = max(state.negative[item], det.conf)
            else:
                item = det.cls_name
                expected = C.ITEM_REGION.get(item)
                if expected and band != expected and band != "body":
                    # PPE lech vung: giam trong so thay vi loai han
                    if _band_distance(band, expected) > 1:
                        continue
                    state.positive[item] = max(state.positive[item], det.conf * 0.75)
                else:
                    state.positive[item] = max(state.positive[item], det.conf)

        _resolve(state, known_items)
        states.append(state)

    return states


_ORDER = ["head", "torso", "hands", "feet", "body"]


def _band_distance(a: str, b: str) -> int:
    try:
        return abs(_ORDER.index(a) - _ORDER.index(b))
    except ValueError:
        return 9


def _resolve(state: PersonState, known_items: set[str], pos_thr: float = 0.25,
             neg_thr: float = 0.20) -> None:
    """Quyet dinh trang thai tung item tu conf duong/am trong khung hinh."""
    for item in sorted(known_items):
        pos = state.positive.get(item, 0.0)
        neg = state.negative.get(item, 0.0)
        if pos >= pos_thr and pos >= neg * 1.05:
            state.status[item] = "ok"
        elif neg >= neg_thr and neg > pos:
            state.status[item] = "missing"
        else:
            state.status[item] = "unknown"


def equipment_present(detections: list[Detection]) -> set[str]:
    return {d.cls_name for d in detections if d.cls_name.startswith("equipment:")}
