"""Don dep bang chung cu va vacuum database.

    python scripts/cleanup.py --days 30
    python scripts/cleanup.py --days 30 --dry-run
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="giu lai bao nhieu ngay")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(ROOT / "data" / "ppe.db"))
    args = ap.parse_args()

    cutoff = time.time() - args.days * 86400
    db_path = Path(args.db)
    removed_files = 0
    freed = 0

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, image, clip FROM violations WHERE ts < ?", (cutoff,)
    ).fetchall()

    for r in rows:
        for key in ("image", "clip"):
            rel = r[key]
            if not rel:
                continue
            p = ROOT / rel
            if p.exists():
                if args.dry_run:
                    print(f"  se xoa: {p}")
                else:
                    freed += p.stat().st_size
                    p.unlink(missing_ok=True)
                    removed_files += 1

    print(f"\n{len(rows)} vi pham cu hon {args.days} ngay")
    print(f"{removed_files} tep ({freed / 1e6:.1f} MB)"
          + (" [dry-run, chua xoa]" if args.dry_run else ""))

    if not args.dry_run:
        con.execute("DELETE FROM violations WHERE ts < ?", (cutoff,))
        con.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        con.commit()
        con.execute("VACUUM")
        print("Da xoa ban ghi va vacuum database")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
