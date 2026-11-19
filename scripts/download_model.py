"""Tai trong so model PPE (chi can chay mot lan).

Uu tien model da huan luyen tu dataset Ultralytics Construction-PPE
(thang 11/2026, CC BY 4.0) vi no co lop am tinh no_vest/no_helmet day du.

    python scripts/download_model.py              # tai model mac dinh
    python scripts/download_model.py --list       # xem cac lua chon
    python scripts/download_model.py --name old   # model 19 lop cu
    python scripts/download_model.py --url <url>  # nguon tu chon
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MIN_BYTES = 5_000_000

# name -> (ten tep trong weights/, danh sach URL du phong, mo ta)
SOURCES: dict[str, tuple[str, list[str], str]] = {
    "ppe26": (
        "ppe26.pt",
        [
            "https://github.com/ntchi1604/PPE/releases/latest/download/ppe26.pt",
        ],
        "12 lop, dataset Ultralytics Construction-PPE (khuyen dung)",
    ),
    "old": (
        "ppe_yolov8.pt",
        [
            "https://huggingface.co/killuminati1/construction-ppe-yolov8/resolve/main/best.pt",
            "https://hf-mirror.com/killuminati1/construction-ppe-yolov8/resolve/main/best.pt",
        ],
        "19 lop, construction-ppe-yolov8 (khong co lop am tinh cho ao)",
    ),
}

DEFAULT = "ppe26"


def download(url: str, dest: Path) -> bool:
    print(f"  -> {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "PPE-Monitor/1.0"})
    tmp = dest.with_suffix(".part")
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
        tmp.replace(dest)
        return True
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        print(f"     lỗi: {exc}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default=DEFAULT, choices=sorted(SOURCES),
                    help="chon model co san")
    ap.add_argument("--url", help="nguon tu chon (ghi de --name)")
    ap.add_argument("--dest", help="duong dan luu, mac dinh weights/<ten>")
    ap.add_argument("--list", action="store_true", help="liet ke cac model")
    ap.add_argument("--force", action="store_true", help="tai lai du da co")
    args = ap.parse_args()

    if args.list:
        print("Cac model co san:")
        for name, (fname, urls, desc) in sorted(SOURCES.items()):
            mark = " *" if name == DEFAULT else "  "
            print(f"{mark} {name:<8} {fname:<18} {desc}")
        print(f"\n  * = mac dinh. Dung: python scripts/download_model.py --name <ten>")
        return 0

    filename, urls, desc = SOURCES[args.name]
    if args.url:
        urls = [args.url]
        filename = args.dest or filename
    dest = Path(args.dest) if args.dest else ROOT / "weights" / filename
    if not dest.is_absolute():
        dest = ROOT / dest

    print(f"Model: {args.name} — {desc}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and not args.force:
        size = dest.stat().st_size
        if size >= MIN_BYTES:
            print(f"Đã có: {dest} ({size / 1e6:.1f} MB)")
            print("Dùng --force để tải lại.")
            return 0

    print("Đang tải trọng số YOLO PPE...")
    for url in urls:
        if download(url, dest):
            print(f"\nXong: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
            print(f"Kiểm tra config.yaml: model.weights phải trỏ tới weights/{filename}")
            return 0

    print("\nTải thất bại. Tải thủ công một trong các địa chỉ:")
    for url in urls:
        print(f"  {url}")
    print(f"  -> lưu thành {dest}")
    print("\nHoặc huan luyen lai tu dataset Ultralytics Construction-PPE:")
    print("  python scripts/fetch_dataset.py")
    print("  python scripts/train_ppe.py --data dataset-public/construction-ppe/data.yaml "
          "--model yolov8s.pt --epochs 120 --copy-to weights/ppe26.pt")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
