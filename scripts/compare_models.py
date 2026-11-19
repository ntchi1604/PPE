"""Doi chieu model cu va model moi tren cung khung hinh video that."""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.classes as C  # noqa: E402
from app.detector import PPEDetector  # noqa: E402

VIDEOS = ["assets/vest.mp4", "assets/vest1.mp4"]
MODELS = [
    ("cu", ROOT / "weights" / "ppe_yolov8.pt"),
    ("moi", ROOT / "weights" / "ppe26.pt"),
]
FRAMES = 40


def sample(path: Path, n: int) -> list:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, total // (n + 1))
    out = []
    for i in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, step * (i + 1))
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        if w > 1280:
            frame = cv2.resize(frame, (1280, int(h * 1280 / w)))
        out.append(frame)
    cap.release()
    return out


def main() -> int:
    for name, wp in MODELS:
        print(f"\n{'=' * 62}\nMODEL {name}: {wp.name}\n{'=' * 62}")
        if not wp.exists():
            print("  khong co tep")
            continue
        try:
            det = PPEDetector(wp, device="0", imgsz=640, half=True)
        except Exception as exc:
            print(f"  nap that bai: {exc}")
            continue
        print(f"  so lop      {len(det.names)}")
        print(f"  lop         {', '.join(sorted(det.names.values()))}")
        print(f"  item dung   {', '.join(sorted(det.known_items))}")

        for rel in VIDEOS:
            vp = ROOT / rel
            frames = sample(vp, FRAMES)
            if not frames:
                print(f"  {rel}: khong doc duoc")
                continue
            t0 = time.time()
            hits = Counter()
            persons = 0
            for f in frames:
                for d in det.detect(f):
                    if C.is_person(d.cls_name):
                        persons += 1
                    else:
                        hits[d.cls_name] += 1
            dt = (time.time() - t0) / max(1, len(frames)) * 1000
            print(f"  {rel}  {len(frames)} khung · {dt:.0f} ms/khung")
            print(f"    nguoi      {persons}")
            top = ", ".join(f"{k}={v}" for k, v in hits.most_common(12))
            print(f"    phat hien  {top or 'khong co'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
