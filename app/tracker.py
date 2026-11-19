"""Tracker nhe cho bbox nguoi: du doan tuyen tinh + ghep cap theo IoU.

Khong phu thuoc thu vien ngoai. Du on dinh cho camera cong truong co chuyen dong
cham va toc do khung hinh 15-30 fps.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

Box = tuple[float, float, float, float]

_ids = itertools.count(1)


def iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = ix2 - ix1, iy2 - iy1
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0


@dataclass
class Track:
    track_id: int
    bbox: Box
    conf: float
    hits: int = 1
    age: int = 0
    misses: int = 0
    velocity: tuple[float, float] = (0.0, 0.0)
    trail: list[tuple[float, float]] = field(default_factory=list)

    def predict(self) -> Box:
        dx, dy = self.velocity
        x1, y1, x2, y2 = self.bbox
        return (x1 + dx, y1 + dy, x2 + dx, y2 + dy)

    def update(self, bbox: Box, conf: float) -> None:
        px1, py1, px2, py2 = self.bbox
        nx1, ny1, nx2, ny2 = bbox
        self.velocity = (
            0.5 * self.velocity[0] + 0.5 * ((nx1 + nx2) - (px1 + px2)) / 2.0,
            0.5 * self.velocity[1] + 0.5 * ((ny1 + ny2) - (py1 + py2)) / 2.0,
        )
        self.bbox = bbox
        self.conf = conf
        self.hits += 1
        self.misses = 0
        cx, cy = (nx1 + nx2) / 2.0, (ny1 + ny2) / 2.0
        self.trail.append((cx, cy))
        if len(self.trail) > 60:
            self.trail.pop(0)


class PersonTracker:
    def __init__(self, iou_threshold: float = 0.30, max_age: int = 30,
                 min_hits: int = 3, max_ghost: int = 2):
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.min_hits = min_hits
        # Cho phep thieu vai khung van giu track de ve overlay, tranh nhay
        self.max_ghost = max_ghost
        self.tracks: list[Track] = []

    def update(self, detections: list[dict]) -> list[Track]:
        """detections: [{'bbox': (x1,y1,x2,y2), 'conf': float}]"""
        for t in self.tracks:
            t.age += 1
            if t.misses > 0:
                t.bbox = t.predict()

        candidates: list[tuple[float, int, int]] = []
        for ti, track in enumerate(self.tracks):
            pred = track.bbox
            for di, det in enumerate(detections):
                score = iou(pred, det["bbox"])
                if score >= self.iou_threshold:
                    candidates.append((score, ti, di))

        candidates.sort(reverse=True)
        used_tracks: set[int] = set()
        used_dets: set[int] = set()
        for score, ti, di in candidates:
            if ti in used_tracks or di in used_dets:
                continue
            used_tracks.add(ti)
            used_dets.add(di)
            self.tracks[ti].update(detections[di]["bbox"], detections[di]["conf"])

        for ti, track in enumerate(self.tracks):
            if ti not in used_tracks:
                track.misses += 1

        for di, det in enumerate(detections):
            if di in used_dets:
                continue
            self.tracks.append(Track(next(_ids), det["bbox"], det["conf"]))

        self.tracks = [t for t in self.tracks if t.misses <= self.max_age]
        # Tra ve ca track vua thieu vai khung (ghost) de overlay khong nhap nhay
        return [
            t for t in self.tracks
            if t.hits >= self.min_hits and t.misses <= self.max_ghost
        ]

    def drop(self, track_id: int) -> None:
        self.tracks = [t for t in self.tracks if t.track_id != track_id]
