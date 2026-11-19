"""Tai dataset Ultralytics Construction-PPE va chuan bi data.yaml.

Chi can chay mot lan cho moi may.

    python scripts/fetch_dataset.py
    python scripts/fetch_dataset.py --force          # tai lai tu dau
    python scripts/fetch_dataset.py --keep-zip       # giu lai tep zip

Dataset: 1.000 anh (800 train / 200 val), 12 lop, CC BY 4.0, thang 11/2026.
https://docs.ultralytics.com/datasets/detect/construction-ppe

Tai xong, huan luyen ngay:

    python scripts/train_ppe.py --data dataset-public/construction-ppe/data.yaml ^
        --model yolov8s.pt --epochs 120 --copy-to weights/ppe26.pt
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

URL = "https://github.com/ultralytics/assets/releases/download/v0.0.0/construction-ppe.zip"
ZIP_NAME = "construction-ppe.zip"
INNER = "construction-ppe"
MIN_ZIP_BYTES = 400_000_000

EXPECTED_CLASSES = [
    "helmet", "gloves", "vest", "boots", "goggles", "Person",
    "no_helmet", "no_goggle", "no_gloves", "no_boots", "forklift", "no_vest",
]


def download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    print(f"  -> {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "PPE-Monitor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while chunk := r.read(1 << 21):
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done / total * 100
                    print(f"\r     {done / 1e6:7.1f}/{total / 1e6:.1f} MB  ({pct:5.1f}%)",
                          end="")
        print()
        tmp.replace(dest)
        return True
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        print(f"\n     lỗi: {exc}")
        return False


def write_yaml(target: Path) -> Path:
    """Ghi data.yaml voi duong dan tuyet doi de YOLO tim thay dataset."""
    yaml_path = target / "data.yaml"
    lines = [
        "# Ultralytics Construction-PPE dataset, thang 11/2026, CC BY 4.0",
        "# https://docs.ultralytics.com/datasets/detect/construction-ppe",
        f"path: {target.as_posix()}",
        "train: images/train",
        "val: images/val",
        "",
        "names:",
    ]
    lines += [f"  {i}: {name}" for i, name in enumerate(EXPECTED_CLASSES)]
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return yaml_path


def report(target: Path) -> bool:
    """In so anh va so hop theo lop. Tra False neu cau truc thieu."""
    ok = True
    for split in ("train", "val"):
        imgs = list((target / "images" / split).glob("*.*"))
        lbls = list((target / "labels" / split).glob("*.txt"))
        print(f"  {split:<6} {len(imgs):>4} anh · {len(lbls):>4} nhãn")
        if not imgs or len(imgs) != len(lbls):
            ok = False

    hist: Counter = Counter()
    for lbl in (target / "labels" / "train").glob("*.txt"):
        for line in lbl.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip():
                hist[line.split()[0]] += 1

    if hist:
        print("  hộp theo lớp:")
        for i, name in enumerate(EXPECTED_CLASSES):
            n = hist.get(str(i), 0)
            print(f"    {i:>2} {name:<12} {n:>5}")
        print(f"  tổng hộp train: {sum(hist.values())}")
    else:
        ok = False
    return ok


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="dataset-public",
                    help="thu muc chua dataset (mac dinh dataset-public)")
    ap.add_argument("--url", default=URL, help="nguon zip khac")
    ap.add_argument("--force", action="store_true", help="tai lai du da co")
    ap.add_argument("--keep-zip", action="store_true", help="giu tep zip sau khi giai nen")
    args = ap.parse_args()

    dest = Path(args.root)
    if not dest.is_absolute():
        dest = ROOT / dest
    target = dest / INNER
    zip_path = dest / ZIP_NAME

    if target.exists() and not args.force:
        n = len(list((target / "images" / "train").glob("*.*")))
        if n >= 700:
            print(f"Đã có dataset: {target} ({n} ảnh train)")
            report(target)
            print(f"\nDùng --force để tải lại.")
            print(f"data.yaml: {write_yaml(target)}")
            return 0

    # Tai zip (dung lai tep da co neu dung luong hop ly)
    if zip_path.exists() and zip_path.stat().st_size >= MIN_ZIP_BYTES and not args.force:
        print(f"Dùng lại zip đã tải: {zip_path} "
              f"({zip_path.stat().st_size / 1e6:.0f} MB)")
    else:
        print("Đang tải dataset (~618 MB, mất vài phút)...")
        if not download(args.url, zip_path):
            print("\nTải thất bại. Tải thủ công:")
            print(f"  {args.url}")
            print(f"  -> lưu thành {zip_path}")
            print(f"  rồi chạy lại lệnh này.")
            return 1

    print("Đang giải nén...")
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(dest)
    except zipfile.BadZipFile as exc:
        print(f"  zip hỏng: {exc}")
        print(f"  xóa {zip_path} rồi chạy lại.")
        return 1

    if not target.exists():
        print(f"  không thấy {INNER} trong zip")
        return 1

    print(f"\nDataset: {target}")
    ok = report(target)
    print(f"\ndata.yaml: {write_yaml(target)}")

    if not args.keep_zip:
        try:
            zip_path.unlink()
            print(f"Đã xóa {zip_path.name} (dùng --keep-zip để giữ lại)")
        except OSError:
            pass

    print("\nHuấn luyện:")
    print(f"  python scripts/train_ppe.py --data {target.name}/data.yaml ^")
    print("      --model yolov8s.pt --epochs 120 --copy-to weights/ppe26.pt")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
