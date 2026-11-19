"""Script tien ich: kiem tra moi truong, model va nguon hinh truoc khi chay that."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = "  [OK]  "
BAD = " [FAIL] "
WARN = " [WARN] "


def line(status: str, text: str) -> None:
    print(status + text)


def check_python() -> bool:
    v = sys.version_info
    line(OK if v >= (3, 10) else BAD, f"Python {v.major}.{v.minor}.{v.micro} (cần >= 3.10)")
    return v >= (3, 10)


def check_packages() -> bool:
    ok = True
    for mod, name in [
        ("torch", "torch"), ("cv2", "opencv-python"), ("ultralytics", "ultralytics"),
        ("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("yaml", "pyyaml"),
        ("numpy", "numpy"), ("requests", "requests"),
    ]:
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", "?")
            line(OK, f"{name:<18} {ver}")
        except Exception as exc:
            ok = False
            line(BAD, f"{name:<18} thiếu ({exc})")
    return ok


def check_cuda() -> bool:
    try:
        import torch
    except Exception:
        return False
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        line(OK, f"CUDA {torch.version.cuda} · {torch.cuda.get_device_name(0)} "
                 f"({props.total_memory / 1e9:.1f} GB)")
        return True
    line(WARN, "Không có CUDA — chạy CPU (chậm hơn ~15-25 lần)")
    return True


def model_path() -> "Path":
    """Doi tuong tro toi trong so dang cau hinh trong config.yaml."""
    from app.config import Config

    rel = Config().get("model.weights", "weights/ppe26.pt")
    p = Path(rel)
    return p if p.is_absolute() else ROOT / p


def check_model() -> bool:
    weights = model_path()
    if not weights.exists():
        line(BAD, f"Thiếu trọng số: {weights.name}  ({weights.parent})")
        line("      ", "Chạy: python scripts/download_model.py")
        return False
    line(OK, f"Trọng số {weights.name} ({weights.stat().st_size / 1e6:.1f} MB)")
    return True


def check_assets() -> bool:
    img = ROOT / "assets" / "demo_site.jpg"
    if img.exists():
        line(OK, f"Ảnh demo {img.name}")
    else:
        line(WARN, "Chưa có ảnh demo (chế độ --demo sẽ bỏ qua)")
    return True


def run_inference() -> bool:
    try:
        import cv2
        from app.detector import PPEDetector
    except Exception as exc:
        line(BAD, f"Không import được module: {exc}")
        return False

    try:
        det = PPEDetector(model_path())
    except Exception as exc:
        line(BAD, f"Không nạp được model: {exc}")
        return False

    line(OK, f"Model nạp thành công · device={det.device} · "
             f"{len(det.names)} lớp · PPE={sorted(det.known_items)}")

    img_path = ROOT / "assets" / "demo_site.jpg"
    if not img_path.exists():
        return True
    frame = cv2.imread(str(img_path))
    det.detect(frame)  # warm-up
    t0 = time.perf_counter()
    for _ in range(5):
        dets = det.detect(frame)
    ms = (time.perf_counter() - t0) / 5 * 1000
    persons = sum(1 for d in dets if d.cls_name == "person")
    line(OK, f"Suy luận {ms:.0f} ms/khung · {persons} người · {len(dets)} đối tượng")
    line(OK, f"Ước tính {1000 / ms:.0f} FPS trên GPU hiện tại")
    return True


def main() -> int:
    print("\n=== KIỂM TRA HỆ THỐNG PPE MONITOR ===\n")
    checks = [
        check_python(),
        check_packages(),
        check_cuda(),
        check_model(),
        check_assets(),
    ]
    print()
    if all(checks):
        run_inference()
        print("\nSẵn sàng. Chạy:  python run.py --demo\n")
        return 0
    print("\nCòn lỗi ở trên. Sửa rồi chạy lại script này.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
