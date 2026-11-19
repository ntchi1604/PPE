"""Xuat bao cao: CSV, Excel nhieu sheet, va bao cao HTML in duoc."""

from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path
from typing import Any

import app.classes as C
from app.db import Database

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    HAS_XLSX = True
except ImportError:  # pragma: no cover
    HAS_XLSX = False


HEADER_FILL = PatternFill("solid", fgColor="1F2937") if HAS_XLSX else None
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11) if HAS_XLSX else None
THIN = Side(style="thin", color="D1D5DB") if HAS_XLSX else None
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN) if HAS_XLSX else None


def _fmt_time(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def violations_csv(db: Database, days: float = 7.0, cam_id: str | None = None) -> str:
    since = time.time() - days * 86400
    rows = db.list_violations(limit=100000, cam_id=cam_id, since=since)

    buf = io.StringIO()
    buf.write("\ufeff")  # BOM de Excel doc dung tieng Viet
    w = csv.writer(buf)
    w.writerow([
        "STT", "Thoi gian", "Camera", "Khu vuc", "Doi tuong",
        "Thieu", "Do tin cay", "Da xu ly", "Nguoi xu ly", "Anh", "Clip",
    ])
    for i, r in enumerate(rows, 1):
        missing = r["missing"] if isinstance(r["missing"], list) else json.loads(r["missing"])
        w.writerow([
            i,
            _fmt_time(r["ts"]),
            r["cam_id"],
            r["zone"],
            f"#{r['track_id']}",
            "; ".join(C.label_vi(m) for m in missing),
            f"{r['confidence'] * 100:.0f}%",
            "Co" if r["acknowledged"] else "Chua",
            r.get("ack_by") or "",
            r.get("image") or "",
            r.get("clip") or "",
        ])
    return buf.getvalue()


def _style_sheet(ws, widths: list[int]) -> None:
    for idx, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"


def summary_xlsx(db: Database, days: float = 7.0) -> bytes:
    """Workbook 4 sheet: Tong hop, Vi pham, Theo thiet bi, Theo gio."""
    if not HAS_XLSX:
        raise RuntimeError("Thieu openpyxl: pip install openpyxl")

    since = time.time() - days * 86400
    violations = db.list_violations(limit=100000, since=since)
    counts = db.violation_counts(since)
    summary = db.summary(since)
    hourly = db.hourly_series(since)
    cams = {c["id"]: c for c in db.list_cameras()}

    wb = Workbook()

    # ---- Sheet 1: Tong hop ----
    ws = wb.active
    ws.title = "Tong hop"
    ws["A1"] = "BAO CAO GIAM SAT AN TOAN PPE"
    ws["A1"].font = Font(bold=True, size=15)
    ws["A2"] = f"Ky bao cao: {days:g} ngay gan nhat"
    ws["A2"].font = Font(italic=True, color="6B7280")
    ws["A3"] = f"Xuat luc: {_fmt_time(time.time())}"
    ws["A3"].font = Font(italic=True, color="6B7280")

    by_item: dict[str, int] = {}
    by_zone: dict[str, int] = {}
    by_cam: dict[str, int] = {}
    for r in counts:
        for item in json.loads(r["missing"]):
            by_item[item] = by_item.get(item, 0) + r["n"]
        by_zone[r["zone"]] = by_zone.get(r["zone"], 0) + r["n"]
        by_cam[r["cam_id"]] = by_cam.get(r["cam_id"], 0) + r["n"]

    kpis = [
        ("Tong vi pham", summary["total"]),
        ("Chua xu ly", summary["unack"]),
        ("Da xu ly", summary["total"] - summary["unack"]),
        ("So camera co vi pham", summary["cameras"]),
        ("So doi tuong vi pham", summary["tracks"]),
        ("Ti le xu ly", f"{(1 - summary['unack'] / summary['total']) * 100:.1f}%"
         if summary["total"] else "0%"),
    ]
    row = 5
    ws.cell(row=row, column=1, value="CHI SO").font = Font(bold=True)
    ws.cell(row=row, column=2, value="GIA TRI").font = Font(bold=True)
    for label, value in kpis:
        row += 1
        ws.cell(row=row, column=1, value=label)
        ws.cell(row=row, column=2, value=value)

    row += 2
    ws.cell(row=row, column=1, value="VI PHAM THEO THIET BI").font = Font(bold=True)
    for item, n in sorted(by_item.items(), key=lambda x: -x[1]):
        row += 1
        ws.cell(row=row, column=1, value=C.label_vi(item))
        ws.cell(row=row, column=2, value=n)

    row += 2
    ws.cell(row=row, column=1, value="VI PHAM THEO KHU VUC").font = Font(bold=True)
    for zone, n in sorted(by_zone.items(), key=lambda x: -x[1]):
        row += 1
        ws.cell(row=row, column=1, value=zone)
        ws.cell(row=row, column=2, value=n)

    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 16

    # ---- Sheet 2: Chi tiet vi pham ----
    ws2 = wb.create_sheet("Vi pham")
    headers = ["STT", "Thoi gian", "Camera", "Ten camera", "Khu vuc",
               "Doi tuong", "Thieu", "Do tin cay", "Da xu ly", "Nguoi xu ly"]
    ws2.append(headers)
    for i, r in enumerate(violations, 1):
        missing = r["missing"] if isinstance(r["missing"], list) else json.loads(r["missing"])
        cam = cams.get(r["cam_id"], {})
        ws2.append([
            i,
            _fmt_time(r["ts"]),
            r["cam_id"],
            cam.get("name", r["cam_id"]),
            r["zone"],
            f"#{r['track_id']}",
            ", ".join(C.label_vi(m) for m in missing),
            r["confidence"],
            "Co" if r["acknowledged"] else "Chua",
            r.get("ack_by") or "",
        ])
    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row):
        for cell in row:
            cell.border = BORDER
    for row in ws2.iter_rows(min_row=2, min_col=8, max_col=8):
        for cell in row:
            cell.number_format = "0%"
    _style_sheet(ws2, [6, 20, 14, 24, 16, 12, 34, 12, 12, 16])

    # ---- Sheet 3: Theo camera ----
    ws3 = wb.create_sheet("Theo camera")
    ws3.append(["Camera", "Ten", "Khu vuc", "So vi pham", "Ti le"])
    total = max(1, sum(by_cam.values()))
    for cam_id, n in sorted(by_cam.items(), key=lambda x: -x[1]):
        ws3.append([
            cam_id,
            cams.get(cam_id, {}).get("name", cam_id),
            cams.get(cam_id, {}).get("zone", ""),
            n,
            n / total,
        ])
    for row in ws3.iter_rows(min_row=2, max_row=ws3.max_row):
        for cell in row:
            cell.border = BORDER
    for row in ws3.iter_rows(min_row=2, min_col=5, max_col=5):
        for cell in row:
            cell.number_format = "0.0%"
    _style_sheet(ws3, [16, 26, 16, 14, 10])

    # ---- Sheet 4: Theo gio ----
    ws4 = wb.create_sheet("Theo gio")
    ws4.append(["Gio (tu dau ky)", "So vi pham"])
    for h in hourly:
        ws4.append([h["bucket"], h["n"]])
    _style_sheet(ws4, [18, 14])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def report_html(db: Database, days: float = 7.0) -> str:
    """Bao cao mot trang, in duoc bang Ctrl+P."""
    since = time.time() - days * 86400
    violations = db.list_violations(limit=200, since=since)
    summary = db.summary(since)
    counts = db.violation_counts(since)

    by_item: dict[str, int] = {}
    for r in counts:
        for item in json.loads(r["missing"]):
            by_item[item] = by_item.get(item, 0) + r["n"]

    rows = "\n".join(
        f"<tr><td>{_fmt_time(v['ts'])}</td><td>{v['cam_id']}</td>"
        f"<td>#{v['track_id']}</td>"
        f"<td>{', '.join(C.label_vi(m) for m in v['missing'])}</td>"
        f"<td>{v['confidence'] * 100:.0f}%</td>"
        f"<td>{'Đã xử lý' if v['acknowledged'] else 'Chờ xử lý'}</td></tr>"
        for v in violations
    )
    bars = "\n".join(
        f"<div class='bar'><span>{C.label_vi(k)}</span>"
        f"<div class='track'><div class='fill' style='width:{v / max(1, max(by_item.values())) * 100:.0f}%'></div></div>"
        f"<b>{v}</b></div>"
        for k, v in sorted(by_item.items(), key=lambda x: -x[1])
    )

    return f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<title>Báo cáo PPE — {days:g} ngày</title>
<style>
 body{{font:14px/1.6 "Segoe UI",system-ui,sans-serif;max-width:900px;margin:32px auto;color:#111}}
 h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#666;font-size:12px;margin-bottom:24px}}
 .kpi{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}}
 .kpi div{{border:1px solid #ddd;border-radius:8px;padding:12px 18px;min-width:130px}}
 .kpi b{{display:block;font-size:24px}} .kpi span{{color:#666;font-size:11px;text-transform:uppercase;letter-spacing:.5px}}
 table{{width:100%;border-collapse:collapse;margin-top:12px;font-size:12.5px}}
 th,td{{border:1px solid #e5e7eb;padding:7px 10px;text-align:left}}
 th{{background:#f9fafb;font-size:11px;text-transform:uppercase;color:#666}}
 .bar{{display:grid;grid-template-columns:150px 1fr 40px;gap:10px;align-items:center;margin-bottom:6px;font-size:12.5px}}
 .track{{height:8px;background:#f3f4f6;border-radius:99px;overflow:hidden}}
 .fill{{height:100%;background:#ef4444;border-radius:99px}}
 @media print{{body{{margin:0}} .noprint{{display:none}}}}
</style></head><body>
<h1>Báo cáo giám sát an toàn PPE</h1>
<div class="sub">Kỳ báo cáo: {days:g} ngày gần nhất · Xuất lúc {_fmt_time(time.time())}</div>
<div class="kpi">
  <div><b>{summary['total']}</b><span>Tổng vi phạm</span></div>
  <div><b>{summary['unack']}</b><span>Chưa xử lý</span></div>
  <div><b>{summary['cameras']}</b><span>Camera</span></div>
  <div><b>{summary['tracks']}</b><span>Đối tượng</span></div>
</div>
<h3>Vi phạm theo thiết bị</h3>
{bars or '<p>Không có dữ liệu</p>'}
<h3>Chi tiết vi phạm</h3>
<table><thead><tr><th>Thời gian</th><th>Camera</th><th>Đối tượng</th>
<th>Thiếu</th><th>Tin cậy</th><th>Trạng thái</th></tr></thead>
<tbody>{rows or '<tr><td colspan=6>Không có vi phạm</td></tr>'}</tbody></table>
<p class="noprint" style="margin-top:24px"><button onclick="print()">In báo cáo</button></p>
</body></html>"""
