"""Tai trong so model PPE tu Hugging Face (chi can chay mot lan)."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "weights" / "ppe_yolov8.pt"

URLS = [
    "https://huggingface.co/killuminati1/construction-ppe-yolov8/resolve/main/best.pt",
    "https://hf-mirror.com/killuminati1/construction-ppe-yolov8/resolve/main/best.pt",
]

MIN_BYTES = 5_000_000


def download(url: str) -> bool:
    print(f"  -> {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "PPE-Monitor/1.0"})
    tmp = DEST.with_suffix(".part")
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r     {done / 1e6:6.1f}/{total / 1e6:.1f} MB", end="")
        print()
        if tmp.stat().st_size < MIN_BYTES:
            tmp.unlink(missing_ok=True)
            print("     tệp quá nhỏ, bỏ qua")
            return False
        tmp.replace(DEST)
        return True
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        print(f"     lỗi: {exc}")
        return False


def main() -> int:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    if DEST.exists() and DEST.stat().st_size >= MIN_BYTES:
        print(f"Đã có: {DEST} ({DEST.stat().st_size / 1e6:.1f} MB)")
        return 0
    print("Đang tải trọng số YOLOv8 PPE...")
    for url in URLS:
        if download(url):
            print(f"\nXong: {DEST} ({DEST.stat().st_size / 1e6:.1f} MB)")
            return 0
    print("\nTải thất bại. Tải thủ công:")
    print(f"  {URLS[0]}")
    print(f"  -> lưu thành {DEST}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
