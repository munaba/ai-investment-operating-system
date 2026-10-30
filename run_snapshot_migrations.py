from __future__ import annotations

import sys
import logging
from typing import List

import sqlite3

from Core.exceptions import DatabaseError
from Database.database_config import DatabaseConfig
from Database.migrations import MigrationRunner
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS
from Database.sqlite_database import SQLiteDatabase


def _conflicting_duplicates(database: SQLiteDatabase) -> List[tuple]:
    """Return list of (scan_time, symbol) groups where other columns differ."""
    rows = database.execute(
        """
        SELECT scan_time, symbol,
               COUNT(DISTINCT status) AS d_status,
               COUNT(DISTINCT recommendation) AS d_rec,
               COUNT(DISTINCT confidence) AS d_conf,
               COUNT(DISTINCT priority) AS d_prio,
               COUNT(DISTINCT rank) AS d_rank,
               COUNT(DISTINCT score) AS d_score,
               COUNT(DISTINCT score_breakdown_json) AS d_sb,
               COUNT(DISTINCT evidence_summary) AS d_es,
               COUNT(DISTINCT error_message) AS d_em
        FROM ranking_snapshots
        GROUP BY scan_time, symbol
        HAVING COUNT(*) > 1
        """
    ).rows
    conflicts = []
    for r in rows:
        scan_time, symbol = r["scan_time"], r["symbol"]
        other_keys = [k for k in r.keys() if k not in ("scan_time", "symbol")]
        if any(r[k] > 1 for k in other_keys):
            conflicts.append((scan_time, symbol))
    return conflicts


def run_snapshot_migrations() -> int:
    """Apply ``SNAPSHOTS_MIGRATIONS`` to the production database.

    Manual, standalone operation. Adds a pre-flight check before v12:
    conflicting duplicate (scan_time, symbol) groups (other columns
    differ) cause an immediate error and NO deletion.
    """
    database: SQLiteDatabase | None = None
    try:
        config = DatabaseConfig.from_env()
        database = SQLiteDatabase(config)
        database.connect()

        conflicts = _conflicting_duplicates(database)
        if conflicts:
            groups = ", ".join(f"({s},{sym})" for s, sym in conflicts)
            raise DatabaseError(
                f"conflicting duplicate (scan_time, symbol) groups: {groups}"
            )

        runner = MigrationRunner(database)
        applied = runner.apply(list(SNAPSHOTS_MIGRATIONS))

        if applied:
            for record in applied:
                logging.getLogger(__name__).info(
                    f"Applied migration {record.version} '{record.name}'"
                )
            print(f"Applied {len(applied)} migration(s).")
        else:
            print("No pending snapshot migrations -- database already up to date.")

        return 0
    except DatabaseError as exc:
        print(f"Snapshot migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.disconnect()


def main() -> int:
    return run_snapshot_migrations()


if __name__ == "__main__":
    sys.exit(main())
