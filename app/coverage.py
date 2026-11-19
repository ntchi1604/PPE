"""Do phu nhan dien: model hien tai biet nhung bo phan nao.

Cau hoi thuong gap: "sao chi thay bao thieu ao, khong thay bao thieu day dai?"

Ly do: model co 19 lop, chi phu 7 bo phan PPE. Cac bo phan khac (day dai,
dong phuc, mat na han, quan phan quang, mat na phong doc) khong co lop nao
trong model hien tai -> he thong tu dong bo qua yeu cau, khong bao sai.

Module nay tinh ro phan phu do de hien thi len dashboard, thay vi de nguoi
van hanh tuong nham la he thong bo sot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import app.classes as C

if TYPE_CHECKING:  # pragma: no cover
    from app.detector import PPEDetector


def coverage(detector: "PPEDetector" | None, zones: dict | None = None) -> dict:
    """Tra ve ma tran phu: moi PPE co lop duong / lop am / ca hai / khong co."""
    zones = zones or {}

    if detector is None:
        return {"ok": False, "error": "chua nap model", "items": [], "zones": []}

    pos: set[str] = set()
    neg: set[str] = set()
    equipment: set[str] = set()
    for raw in detector.names.values():
        norm = C.normalize(raw)
        if C.is_person(norm):
            continue
        if norm.startswith("equipment:"):
            equipment.add(norm)
        elif C.is_negative(norm):
            neg.add(C.positive_of(norm))
        else:
            pos.add(norm)

    items = []
    for item in C.ITEMS:
        has_pos = item in pos
        has_neg = item in neg
        if has_pos and has_neg:
            level = "full"          # bao duoc ca "co" lan "thieu"
        elif has_neg:
            level = "negative_only"  # chi bao duoc "thieu"
        elif has_pos:
            level = "positive_only"  # chi bao duoc "co" — khong ket luan duoc thieu
        else:
            level = "none"           # model khong biet bo phan nay
        items.append({
            "item": item,
            "label_vi": C.label_vi(item),
            "region": C.ITEM_REGION.get(item, "body"),
            "positive_class": has_pos,
            "negative_class": has_neg,
            "level": level,
            "usable": has_neg,
        })

    usable = {i["item"] for i in items if i["usable"]}
    detected = sorted(pos | neg)
    missing = [i["item"] for i in items if not i["usable"]]

    zone_rows = []
    for zname, zcfg in zones.items():
        required = list((zcfg or {}).get("required", []) or [])
        enforced = [r for r in required if r in usable]
        skipped = [r for r in required if r not in usable]
        zone_rows.append({
            "zone": zname,
            "name": (zcfg or {}).get("name", zname),
            "required": required,
            "enforced": enforced,
            "skipped": skipped,
            "skipped_labels": [C.label_vi(s) for s in skipped],
        })

    return {
        "ok": True,
        "model_path": str(getattr(detector, "weights", "")),
        "num_classes": len(detector.names),
        "classes": detected,
        "equipment": sorted(equipment),
        "items": items,
        "usable_items": sorted(usable),
        "missing_items": missing,
        "missing_labels": [C.label_vi(m) for m in missing],
        "zones": zone_rows,
        "summary": {
            "full": sum(1 for i in items if i["level"] == "full"),
            "partial": sum(1 for i in items if i["level"] in ("positive_only", "negative_only")),
            "none": sum(1 for i in items if i["level"] == "none"),
            "total": len(items),
        },
        "note": (
            "Bo phan co level='none' khong co lop trong model: he thong tu dong "
            "bo qua yeu cau, khong bao sai. Muon giam sat them, gan nhan va "
            "train lai: python scripts/prepare_dataset.py --root dataset"
        ),
    }
