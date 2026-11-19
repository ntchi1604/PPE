"""Chuan bi cau truc dataset YOLO cho PPE cong truong day du.

    python scripts/prepare_dataset.py --root dataset
    python scripts/prepare_dataset.py --root dataset --classes full

Tao:
    dataset/
      images/{train,val,test}
      labels/{train,val,test}
      data.yaml
      README.md          huong dan gan nhan tung lop

Sau khi gan nhan, chay: python scripts/train_ppe.py --data dataset/data.yaml
"""

from __future__ import annotations

import argparse
from pathlib import Path

BASE_CLASSES = [
    "Worker",          # 0  nguoi
    "Hard_hat",        # 1  mu bao ho
    "No-Helmet",       # 2  khong mu
    "Vest",            # 3  ao phan quang
    "No-Vest",         # 4  khong ao phan quang
    "Glove",           # 5  gang tay
    "No-Glove",        # 6
    "Boots",           # 7  giay bao ho
    "No-Boots",        # 8
    "Mask",            # 9  khau trang
    "No-Mask",         # 10
    "Glass",           # 11 kinh bao ho
    "No-Glass",        # 12
    "Ear-Protection",  # 13 chup tai
    "No-Ear-Protection",  # 14
]

FULL_CLASSES = BASE_CLASSES + [
    "Harness",             # 15 day dai an toan
    "No-Harness",          # 16
    "Safety_Suit",         # 17 dong phuc bao ho dai tay
    "No-Safety_Suit",      # 18
    "Hi_Vis_Pants",        # 19 quan phan quang
    "No-Hi_Vis_Pants",     # 20
    "Welding_Mask",        # 21 mat na han
    "No-Welding_Mask",     # 22
    "Respirator",          # 23 mat na phong doc
    "No-Respirator",       # 24
    "Fire_Extinguisher",   # 25 binh chua chay (thiet bi, khong phai PPE ca nhan)
    "Circular_Saw",        # 26 may cat
    "Welding_Equipment",   # 27 thiet bi han
]

GUIDE = """# Hướng dẫn gán nhãn dataset PPE

## Nguyên tắc quan trọng nhất

Mỗi người cần **cả lớp dương tính và lớp âm tính** khi có thể:

- Người đội mũ → vẽ `Hard_hat` quanh mũ
- Người không đội mũ → vẽ `No-Helmet` quanh vùng đầu
- Người mặc áo phản quang → `Vest`
- Người không mặc → `No-Vest` quanh thân trên

Lớp âm tính là thứ giúp hệ thống kết luận "thiếu" thay vì chỉ "không thấy".
Thiếu lớp âm tính, model sẽ im lặng khi công nhân bỏ mũ — đây là lỗi phổ biến
nhất khi tự gán nhãn.

## Quy tắc vẽ hộp

| Lớp | Vẽ quanh |
|---|---|
| Worker | Toàn thân người, từ đỉnh đầu tới chân (kể cả khi bị che một phần) |
| Hard_hat / No-Helmet | Vùng đầu, sát viền mũ hoặc viền tóc |
| Vest / No-Vest | Thân trên, từ vai tới hông |
| Glove / No-Glove | Bàn tay, cả hai tay là hai hộp riêng |
| Boots / No-Boots | Bàn chân tới mắt cá |
| Mask / No-Mask | Nửa dưới mặt |
| Glass / No-Glass | Vùng mắt |
| Ear-Protection / No-Ear-Protection | Hai bên tai |
| Harness / No-Harness | Đai ngực + đai chân, vẽ hộp bao trọn dây đai |
| Safety_Suit / No-Safety_Suit | Thân trên + tay dài |
| Hi_Vis_Pants / No-Hi_Vis_Pants | Thân dưới, từ hông tới gối |
| Welding_Mask / No-Welding_Mask | Mặt nạ hàn che cả mặt |
| Respirator / No-Respirator | Mặt nạ che mũi miệng |

## Mẹo tăng độ chính xác

1. **Đa dạng ánh sáng**: nắng gắt, ngược sáng, trong bóng râm, hoàng hôn.
2. **Đa dạng góc**: chính diện, nghiêng 45°, từ trên cao (camera gắn cột).
3. **Đa dạng khoảng cách**: người cách camera 3 m tới 40 m.
4. **Che khuất**: người đứng sau giàn giáo, sau xe, sau người khác — vẫn gán nhãn.
5. **Mũ nhiều màu**: trắng, vàng, xanh, đỏ, cam — tất cả đều là `Hard_hat`.
6. **Mũ cầm tay**: KHÔNG gán `Hard_hat` (không đội trên đầu).
7. **Mũ treo trên cọc**: KHÔNG gán.
8. **Bóng người**: KHÔNG gán.

## Số lượng khuyến nghị

| Lớp | Ảnh tối thiểu | Ảnh nên có |
|---|---|---|
| Worker | 800 | 2500 |
| Hard_hat / No-Helmet | 600 | 2000 |
| Vest / No-Vest | 600 | 2000 |
| các lớp còn lại | 300 | 1000 |

## Quy trình

1. Chụp ảnh từ chính camera công trường sẽ triển khai — quan trọng hơn ảnh mạng.
2. Gán nhãn bằng Label Studio hoặc Roboflow.
3. Export định dạng **YOLOv8** (một tệp .txt mỗi ảnh, tọa độ chuẩn hóa).
4. Chia 80% train / 15% val / 5% test, **chia theo ngày chụp** (không chia ngẫu
   nhiên từng ảnh) để tránh rò rỉ dữ liệu giữa các khung hình liên tiếp.
5. Chạy `python scripts/train_ppe.py --data dataset/data.yaml`

## Đánh giá kết quả

| Chỉ số | Ngưỡng đạt |
|---|---|
| mAP50 toàn bộ | > 0.80 |
| mAP50 `Worker` | > 0.85 |
| mAP50 `Hard_hat` | > 0.82 |
| mAP50 `No-Helmet` | > 0.75 |
| mAP50 `Vest` | > 0.80 |
| mAP50 `No-Vest` | > 0.72 |
| Recall lớp âm tính | > 0.75 (bỏ sót vi phạm là lỗi nặng nhất) |

Recall quan trọng hơn precision với lớp âm tính: bỏ sót một người không đội mũ
nguy hiểm hơn báo nhầm ba lần.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="dataset")
    ap.add_argument("--classes", choices=["base", "full"], default="full")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    classes = BASE_CLASSES if args.classes == "base" else FULL_CLASSES

    for split in ("train", "val", "test"):
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        (root / "labels" / split).mkdir(parents=True, exist_ok=True)

    names = "\n".join(f"  {i}: {name}" for i, name in enumerate(classes))
    yaml_text = (
        f"# Dataset PPE cong truong - {len(classes)} lop\n"
        f"path: {root.as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n\n"
        "names:\n"
        f"{names}\n"
    )
    (root / "data.yaml").write_text(yaml_text, encoding="utf-8")
    (root / "README.md").write_text(GUIDE, encoding="utf-8")

    print(f"\nDa tao dataset tai: {root}")
    print(f"  {len(classes)} lop")
    print(f"  images/{{train,val,test}}")
    print(f"  labels/{{train,val,test}}")
    print(f"  data.yaml")
    print(f"  README.md  <- doc truoc khi gan nhan\n")
    print("Buoc tiep theo:")
    print("  1. Chep anh vao dataset/images/train (va val, test)")
    print("  2. Gan nhan YOLO vao dataset/labels/train (v.v.)")
    print(f"  3. python scripts/train_ppe.py --data {root / 'data.yaml'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
