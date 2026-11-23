"""Export a public, read-only snapshot of the AIOS database for the dashboard.

Run from the repository root with the AIOS virtualenv:

    python Dashboard/export_snapshot.py            # reads data/investment_platform.db
    python Dashboard/export_snapshot.py --db PATH   # any other copy

The live database is opened with SQLite's read-only URI mode, so this script
can never modify it. Only the tables listed in ``EXPORTED_TABLES`` are
written; Telegram state (chat ids), raw audit payloads and free-text
operator feedback are deliberately left out.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "investment_platform.db"
DEFAULT_OUT = Path(__file__).resolve().parent / "data" / "snapshot.json"

#: table -> ORDER BY clause. Anything not listed here is never exported.
EXPORTED_TABLES: dict[str, str] = {
    "ranking_snapshots": "scan_time, rank",
    "decision_briefs": "generated_at",
    "scheduler_job_runs": "started_at",
    "watchlist": "ticker",
    "accounts": "account_id",
    "positions": "created_at",
    "orders": "created_at",
    "trades": "executed_at",
    "portfolio_snapshots": "timestamp",
    "daily_performance": "timestamp",
    "journal_entries": "decided_at",
    "risk_limits": "id",
    "operator_observation_windows": "start_at",
    "final_review_records": "reviewed_at",
}


def _expected_migration_versions() -> list[int]:
    """Versions declared in the canonical registry (empty if unavailable)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from Database.migration_registry import all_migrations
    except Exception:  # noqa: BLE001 -- export still works without it
        return []
    return [m.version for m, _domain in all_migrations()]


def export(db_path: Path, out_path: Path) -> dict:
    if not db_path.is_file():
        raise SystemExit(f"Database not found: {db_path}")

    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables: dict[str, list[dict]] = {}
        for table, order_by in EXPORTED_TABLES.items():
            if table not in existing:
                tables[table] = []
                continue
            rows = conn.execute(f'SELECT * FROM "{table}" ORDER BY {order_by}').fetchall()
            tables[table] = [dict(row) for row in rows]
        applied = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]

    snapshot = {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "migrations": {"applied": applied, "expected": _expected_migration_versions()},
        "tables": tables,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False), encoding="utf-8")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database to read (read-only)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSON file to write")
    args = parser.parse_args()

    snapshot = export(args.db, args.out)
    counts = ", ".join(f"{name}={len(rows)}" for name, rows in snapshot["tables"].items() if rows)
    print(f"Wrote {args.out} ({counts})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
