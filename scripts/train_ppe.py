"""Huan luyen lai model PPE voi dataset rieng cua cong truong.

    python scripts/train_ppe.py --data dataset/data.yaml
    python scripts/train_ppe.py --data dataset/data.yaml --epochs 120 --batch 16
    python scripts/train_ppe.py --data dataset/data.yaml --resume

Xuat ra: runs/ppe/train/weights/best.pt
Chep vao: weights/ppe_yolov8.pt  (hoac tro config model.weights sang duong dan moi)

Tren RTX 3060 12 GB: ~40 phut cho 100 epoch voi 2000 anh 640px.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dataset/data.yaml", help="duong dan data.yaml")
    ap.add_argument("--model", default="yolov8s.pt", help="trong so khoi dau (yolov8n/s/m/l)")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=-1, help="-1 = tu dong theo VRAM")
    ap.add_argument("--device", default="0", help="0 = GPU dau tien, cpu = CPU")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--patience", type=int, default=30, help="dung som neu khong cai thien")
    ap.add_argument("--name", default="ppe")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--copy-to", default="weights/ppe_yolov8.pt",
                    help="chep best.pt vao day khi xong; rong = khong chep")
    args = ap.parse_args()

    data = Path(args.data)
    if not data.is_absolute():
        data = ROOT / data
    if not data.exists():
        print(f"Khong tim thay {data}")
        print("Chay truoc: python scripts/prepare_dataset.py --root dataset")
        return 2

    try:
        from ultralytics import YOLO
    except ImportError:
        print("Thieu ultralytics. Cai: uv pip install --python .venv\\Scripts\\python.exe ultralytics")
        return 2

    import torch

    if args.device != "cpu" and not torch.cuda.is_available():
        print("CUDA khong san sang, chuyen sang CPU (cham hon 10-20 lan)")
        args.device = "cpu"

    n_train = len(list((data.parent / "images" / "train").glob("*.*")))
    n_val = len(list((data.parent / "images" / "val").glob("*.*")))
    print(f"Dataset: {data}")
    print(f"  train {n_train} anh · val {n_val} anh")
    if n_train < 100:
        print("  CANH BAO: duoi 100 anh train, model se kem. Nen co 800+.")

    model = YOLO(args.model)
    t0 = time.time()

    model.train(
        data=str(data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        patience=args.patience,
        project=str(ROOT / "runs" / "ppe"),
        name=args.name,
        exist_ok=True,
        resume=args.resume,
        # Tang cuong cho anh cong truong: nguoc sang, mua, bui
        hsv_h=0.015, hsv_s=0.7, hsv_v=0.5,
        degrees=8.0, translate=0.15, scale=0.5, shear=2.0,
        perspective=0.0005, flipud=0.0, fliplr=0.5,
        mosaic=1.0, mixup=0.1, copy_paste=0.1,
        cache="ram" if args.device != "cpu" else False,
        plots=True,
        verbose=True,
    )

    elapsed = (time.time() - t0) / 60
    best = ROOT / "runs" / "ppe" / args.name / "weights" / "best.pt"
    print(f"\nXong sau {elapsed:.0f} phut")
    if not best.exists():
        print(f"Khong thay {best}")
        return 1

    # ---- danh gia tren tap val ----
    print("\nDanh gia tren tap val:")
    metrics = YOLO(str(best)).val(data=str(data), imgsz=args.imgsz, device=args.device)
    try:
        names = metrics.names
        m50 = metrics.box.map50
        m5095 = metrics.box.map
        print(f"  mAP50    {m50:.4f}")
        print(f"  mAP50-95 {m5095:.4f}")
        per_class = getattr(metrics.box, "ap50", None)
        if per_class is not None:
            for idx, ap in enumerate(per_class):
                label = names.get(int(idx), str(idx)) if isinstance(names, dict) else names[int(idx)]
                flag = "  <-- thap" if float(ap) < 0.6 else ""
                print(f"    {label:<24} {float(ap):.4f}{flag}")
        if float(m50) < 0.75:
            print("\n  mAP50 duoi 0.75: kiem tra lai gan nhan, dac biet cac lop am tinh")
    except Exception as exc:  # pragma: no cover
        print(f"  khong doc duoc metrics: {exc}")

    if args.copy_to:
        dst = Path(args.copy_to)
        if not dst.is_absolute():
            dst = ROOT / dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, dst)
        print(f"\nDa chep trong so moi: {dst}")
        print("Khoi dong lai server de nap model moi.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
