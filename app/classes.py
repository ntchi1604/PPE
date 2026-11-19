"""Anh xa ten lop cua model sang ten chuan noi bo.

Model `construction-ppe-yolov8` (19 lop):
    0  Boots                 1  Ear-Protection        2  Glass
    3  Glove                 4  Hard_hat              5  Mask
    6  No-Boots              7  No-Ear-Protection     8  No-Glass
    9  No-Glove             10  No-Helmet            11  No-Mask
   12  No-Vest              13  Worker              14  Vest
   15  Circular_Saw         16  Fire_Extinguisher   17  Fire_prevention_Net
   18  Welding_Equipment

Chuan noi bo:
    person          - nguoi
    <item>          - co PPE
    no_<item>       - khong co PPE (lop am tinh)
    equipment:*     - thiet bi cong truong (khong phai PPE ca nhan)
"""

from __future__ import annotations

PERSON = "person"

# Ten lop model -> ten chuan
ALIASES: dict[str, str] = {
    # nguoi
    "Worker": PERSON,
    "Person": PERSON,
    "person": PERSON,
    "worker": PERSON,
    "0": PERSON,
    # PPE duong tinh
    "Hard_hat": "helmet",
    "Hardhat": "helmet",
    "Hard hat": "helmet",
    "Helmet": "helmet",
    "helmet": "helmet",
    "Vest": "vest",
    "Safety_Vest": "vest",
    "vest": "vest",
    "Glove": "gloves",
    "Gloves": "gloves",
    "gloves": "gloves",
    "Boots": "boots",
    "Safety_Boots": "boots",
    "boots": "boots",
    "Mask": "mask",
    "mask": "mask",
    "Glass": "goggles",
    "Goggles": "goggles",
    "goggles": "goggles",
    "Ear-Protection": "ear",
    "Ear_Protection": "ear",
    "Harness": "harness",
    "harness": "harness",
    "Safety_Harness": "harness",
    "Fall_Harness": "harness",
    "Safety_Suit": "suit",
    "Coverall": "suit",
    "uniform": "suit",
    "Uniform": "suit",
    "Hi_Vis_Pants": "hi_vis_pants",
    "Reflective_Pants": "hi_vis_pants",
    "Welding_Mask": "welding_mask",
    "Welding_Shield": "welding_mask",
    "Welding_Helmet": "welding_mask",
    "Respirator": "respirator",
    "Gas_Mask": "respirator",
    "Dust_Mask": "respirator",
    # PPE am tinh
    "No-Helmet": "no_helmet",
    "No_Helmet": "no_helmet",
    "no_helmet": "no_helmet",
    "NO-Hardhat": "no_helmet",
    "No-Vest": "no_vest",
    "No_Vest": "no_vest",
    "no_vest": "no_vest",
    "NO-Safety Vest": "no_vest",
    "No-Glove": "no_gloves",
    "No_Glove": "no_gloves",
    "no_gloves": "no_gloves",
    "No-Boots": "no_boots",
    "No_Boots": "no_boots",
    "no_boots": "no_boots",
    "No-Mask": "no_mask",
    "No_Mask": "no_mask",
    "no_mask": "no_mask",
    "No-Glass": "no_goggles",
    "No_Glass": "no_goggles",
    "no_goggles": "no_goggles",
    "no_goggle": "no_goggles",
    "No-Goggle": "no_goggles",
    "No_Goggle": "no_goggles",
    "No-Ear-Protection": "no_ear",
    "No_Ear_Protection": "no_ear",
    "no_ear": "no_ear",
    "No-Harness": "no_harness",
    "No_Harness": "no_harness",
    "no_harness": "no_harness",
    "No-Safety_Suit": "no_suit",
    "No_Suit": "no_suit",
    "No-Hi_Vis_Pants": "no_hi_vis_pants",
    "No-Reflective_Pants": "no_hi_vis_pants",
    "No-Welding_Mask": "no_welding_mask",
    "No-Welding_Shield": "no_welding_mask",
    "No-Respirator": "no_respirator",
    "No-Gas_Mask": "no_respirator",
    # thiet bi cong truong
    "Circular_Saw": "equipment:saw",
    "Fire_Extinguisher": "equipment:extinguisher",
    "Fire_prevention_Net": "equipment:fire_net",
    "Welding_Equipment": "equipment:welder",
    "forklift": "equipment:forklift",
    "Forklift": "equipment:forklift",
}

# Vung co the tren bbox nguoi (ti le chieu cao, tinh tu dinh dau)
REGIONS: dict[str, tuple[float, float]] = {
    "head": (0.00, 0.28),
    "torso": (0.16, 0.68),
    "hands": (0.30, 0.88),
    "feet": (0.78, 1.00),
    "body": (0.00, 1.00),
}

# PPE -> vung co the tuong ung
ITEM_REGION: dict[str, str] = {
    "helmet": "head",
    "goggles": "head",
    "mask": "head",
    "ear": "head",
    "respirator": "head",
    "welding_mask": "head",
    "vest": "torso",
    "suit": "torso",
    "harness": "torso",
    "gloves": "hands",
    "boots": "feet",
    "hi_vis_pants": "feet",
}

# Danh sach PPE ca nhan ma he thong quan ly
ITEMS: list[str] = [
    "helmet", "vest", "gloves", "boots", "mask", "goggles",
    "ear", "harness", "suit", "respirator", "welding_mask", "hi_vis_pants",
]

# Nhan hien thi tieng Viet
LABELS_VI: dict[str, str] = {
    "helmet": "Mũ bảo hộ",
    "vest": "Áo phản quang",
    "gloves": "Găng tay",
    "boots": "Giày bảo hộ",
    "mask": "Khẩu trang",
    "goggles": "Kính bảo hộ",
    "ear": "Chụp tai",
    "harness": "Dây đai an toàn",
    "suit": "Đồng phục bảo hộ",
    "respirator": "Mặt nạ phòng độc",
    "welding_mask": "Mặt nạ hàn",
    "hi_vis_pants": "Quần phản quang",
}

# Nhan hien thi tieng Viet cho thiet bi cong truong
EQUIPMENT_LABELS_VI: dict[str, str] = {
    "equipment:saw": "Máy cắt",
    "equipment:extinguisher": "Bình chữa cháy",
    "equipment:fire_net": "Lưới chống cháy",
    "equipment:welder": "Thiết bị hàn",
    "equipment:forklift": "Xe nâng",
}


def normalize(name: str) -> str:
    """Chuyen ten lop model sang ten chuan noi bo."""
    if name in ALIASES:
        return ALIASES[name]
    return ALIASES.get(name.strip(), name.strip().lower())


def is_person(cls_name: str) -> bool:
    return cls_name == PERSON


def is_negative(cls_name: str) -> bool:
    return cls_name.startswith("no_")


def positive_of(neg_name: str) -> str:
    return neg_name[3:] if neg_name.startswith("no_") else neg_name


def label_vi(item: str) -> str:
    return LABELS_VI.get(item, EQUIPMENT_LABELS_VI.get(item, item))
