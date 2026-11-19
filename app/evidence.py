"""Luu bang chung: anh vi pham da ve overlay, clip ngan, metadata JSON."""

from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np


class EvidenceStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        cam_id: str,
        track_id: int,
        missing: list[str],
        frame: np.ndarray,
        frames_buffer: Iterable[tuple[float, np.ndarray]],
        zone: str,
        confidence: float,
    ) -> dict:
        ts = time.time()
        day = time.strftime("%Y%m%d", time.localtime(ts))
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts))
        folder = self.root / cam_id / day
        folder.mkdir(parents=True, exist_ok=True)
        base = f"{stamp}_t{track_id}_{'-'.join(missing)}"[:120]

        image_path = folder / f"{base}.jpg"
        ok = cv2.imwrite(str(image_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            image_path = None  # type: ignore[assignment]

        clip_path = self._write_clip(folder / f"{base}.mp4", frames_buffer)

        meta = {
            "cam_id": cam_id,
            "track_id": track_id,
            "missing": missing,
            "zone": zone,
            "confidence": round(confidence, 4),
            "ts": ts,
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            "image": self._rel(image_path) if image_path else None,
            "clip": self._rel(clip_path) if clip_path else None,
        }
        with open(folder / f"{base}.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta

    def _rel(self, p: Path | None) -> str | None:
        if p is None:
            return None
        try:
            return p.relative_to(self.root.parent).as_posix()
        except ValueError:
            return p.as_posix()

    @staticmethod
    def _write_clip(path: Path, frames: Iterable[tuple[float, np.ndarray]]) -> Path | None:
        frames = list(frames)
        if len(frames) < 3:
            return None
        h, w = frames[0][1].shape[:2]
        if w % 2 or h % 2:
            w -= w % 2
            h -= h % 2
            frames = [(t, f[:h, :w]) for t, f in frames]

        for tag, fourcc in (("mp4", "mp4v"), ("avi", "MJPG")):
            target = path.with_suffix(f".{tag}")
            writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*fourcc), 12.0, (w, h))
            if not writer.isOpened():
                writer.release()
                continue
            for _, fr in frames:
                writer.write(fr)
            writer.release()
            if target.exists() and target.stat().st_size > 1024:
                return target
        return None
