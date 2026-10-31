#!/usr/bin/env python3
"""Purge proof script rows from live DB (NOT EXECUTED BY DEFAULT).

Usage:
    python Evaluation/purge_proof_rows.py --confirm

Requires --confirm flag. Creates backup via sqlite3.Connection.backup() to
data/investment_platform.db.bak-<timestamp> before any deletion.
Only deletes rows where date(scan_time)='2026-08-04' AND scan_time matches
the hard-coded proof pattern from Tests/activation_2_7_proof.py:
  - '2026-08-04T09:00:00+00:00' or '2026-08-04T10:00:00+00:00'
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent
_DB = _PROJ / "data" / "investment_platform.db"

PROOF_TIMESTAMPS = [
    "2026-08-04T09:00:00+00:00",
    "2026-08-04T10:00:00+00:00",
]


def main() -> int:
    if "--confirm" not in sys.argv:
        print("REFUSE: pass --confirm to execute")
        print("This script is prepared but NOT executed.")
        return 1

    if not _DB.exists():
        print(f"ERROR: DB not found: {_DB}")
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = _DB.with_suffix(f".db.bak-{ts}")
    print(f"Backing up {_DB} -> {bak}")
    src = sqlite3.connect(_DB)
    dst = sqlite3.connect(bak)
    src.backup(dst)
    dst.close()
    src.close()

    conn = sqlite3.connect(_DB)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM ranking_snapshots WHERE date(scan_time)='2026-08-04'")
    before = cur.fetchone()[0]
    print(f"Rows with date(scan_time)='2026-08-04' before: {before}")

    for t in PROOF_TIMESTAMPS:
        cur.execute("SELECT COUNT(*) FROM ranking_snapshots WHERE scan_time=?", (t,))
        print(f"  {t}: {cur.fetchone()[0]}")

    cur.execute("DELETE FROM ranking_snapshots WHERE scan_time IN (?,?)", PROOF_TIMESTAMPS)
    deleted = cur.rowcount
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM ranking_snapshots WHERE date(scan_time)='2026-08-04'")
    after = cur.fetchone()[0]
    print(f"Deleted: {deleted}, after: {after}")

    conn.close()
    print("Done. Backup preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
