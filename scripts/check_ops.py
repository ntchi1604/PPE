"""Kiem tra nhanh cac module van hanh: retention, bao cao, bang chung, do phu."""

from __future__ import annotations

import json
import sys

import requests

# Console Windows mac dinh cp1252: ep UTF-8 de in duoc nhan tieng Viet
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

B = "http://127.0.0.1:8000"


def main() -> int:
    ok = True

    print("=== retention ===")
    r = requests.get(f"{B}/api/retention", timeout=10).json()
    for k in ("enabled", "violation_days", "evidence_days", "violations", "db_size_mb"):
        print(f"  {k:<16} {r.get(k)}")
    print(f"  evidence         {r.get('evidence')}")
    print(f"  disk_free_gb     {r.get('disk_free_gb')}")
    run = requests.post(f"{B}/api/retention/run", timeout=30).json()
    print(f"  chay don dep     {run}")

    print("=== do phu ===")
    cov = requests.get(f"{B}/api/coverage", timeout=10).json()
    s = cov["summary"]
    print(f"  day du {s['full']} · mot phan {s['partial']} · khong co {s['none']} / {s['total']}")
    print(f"  dung duoc: {', '.join(cov['usable_items'])}")
    print(f"  thieu    : {', '.join(cov['missing_items'])}")
    for z in cov["zones"]:
        if z["skipped"]:
            print(f"  zone {z['zone']:<12} bo qua: {', '.join(z['skipped_labels'])}")

    print("=== excel ===")
    x = requests.get(f"{B}/api/reports/summary.xlsx?days=30", timeout=30)
    open("data/_test.xlsx", "wb").write(x.content)
    try:
        from openpyxl import load_workbook

        wb = load_workbook("data/_test.xlsx")
        print(f"  sheets: {wb.sheetnames}")
        ws = wb["Tong hop"]
        print(f"  tieu de: {ws['A1'].value}")
        kpis = [(ws.cell(row, 1).value, ws.cell(row, 2).value) for row in range(6, 12)]
        print(f"  KPI: {kpis}")
        print(f"  dong du lieu vi pham: {wb['Vi pham'].max_row - 1}")
    finally:
        import os

        os.remove("data/_test.xlsx")

    print("=== csv ===")
    c = requests.get(f"{B}/api/reports/violations.csv?days=30", timeout=30)
    txt = c.content.decode("utf-8-sig")
    lines = txt.splitlines()
    print(f"  dong dau: {lines[0][:100]}")
    print(f"  so dong : {len(lines)}")

    print("=== bao cao html ===")
    h = requests.get(f"{B}/api/reports/report.html?days=30", timeout=30)
    print(f"  HTTP {h.status_code} · {len(h.content)} bytes · co <table>: {'<table>' in h.text}")

    print("=== bang chung ===")
    v = requests.get(f"{B}/api/violations?limit=5", timeout=10).json()
    print(f"  so vi pham tra ve: {len(v)}")
    for row in v[:3]:
        print(f"  #{row['id']} {row['cam_id']} t{row['track_id']} missing={row['missing']} "
              f"conf={row['confidence']:.2f}")
        if row.get("clip"):
            rc = requests.get(f"{B}/{row['clip']}", timeout=30)
            print(f"    clip  HTTP {rc.status_code} · {len(rc.content)} bytes · "
                  f"{rc.headers.get('content-type')}")
            ok = ok and rc.status_code == 200 and len(rc.content) > 10000
        if row.get("image"):
            ri = requests.get(f"{B}/{row['image']}", timeout=20)
            print(f"    anh   HTTP {ri.status_code} · {len(ri.content)} bytes")
            ok = ok and ri.status_code == 200

    print()
    print("KET QUA:", "DAT" if ok else "CO LOI")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
