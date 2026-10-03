"""Standalone regression checks for
``Database.migrations_snapshots.SNAPSHOTS_MIGRATIONS``.

Covers Sprint 5 STEP 3 (version=10) AND Activation 2.7 (version=11):

* migration ``version=10`` applies idempotently and creates the
  ``ranking_snapshots`` table with the expected columns/types;
* ``snapshot_id`` is the sole surrogate PRIMARY KEY;
* version=10 does not collide with, and does not require, versions
  6-9 (the reserved-but-not-yet-implemented ``analysis_snapshots``/
  ``recommendations``/``portfolio_snapshots``/``daily_performance``
  range) -- ``ranking_snapshots`` applies cleanly on top of just
  1-5 (watchlist/accounts/positions/orders/trades);
* version=11 extends the SAME table in place with ``status``/
  ``score``/``score_breakdown_json``/``evidence_summary``/
  ``error_message``, and relaxes ``recommendation``/``confidence``/
  ``priority``/``rank`` to nullable, without ever creating a second,
  competing table;
* a database that already has version=10 rows keeps every row, with
  its own ``snapshot_id``, intact after version=11 runs (the
  rename/rebuild/copy/drop sequence), and the ``AUTOINCREMENT``
  counter survives a restart afterwards.

Run directly with ``python Tests/test_snapshot_migration.py`` -- no
external test framework required, matching ``test_trade_migration.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Database.database_config import DatabaseConfig  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.migrations_watchlist import WATCHLIST_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


def _apply_prior_migrations(db: SQLiteDatabase) -> None:
    """Apply every migration this STEP does not own (1-5), leaving
    6-9 untouched/unapplied on purpose -- ranking_snapshots (10) does
    not depend on the reserved-but-not-yet-implemented 6-9 range.
    """
    runner = MigrationRunner(db)
    runner.apply(WATCHLIST_MIGRATIONS)
    runner.apply(ACCOUNTS_MIGRATIONS)
    runner.apply(POSITIONS_MIGRATIONS)
    runner.apply(ORDERS_MIGRATIONS)
    runner.apply(TRADES_MIGRATIONS)


def scenario_migration_applies_and_is_idempotent():
    print("\n[Scenario 1] version=10 and version=11 apply and are idempotent")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "snapshots_migration.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            _apply_prior_migrations(db)
            runner = MigrationRunner(db)
            applied = runner.apply(SNAPSHOTS_MIGRATIONS)
            check(len(applied) == 2, "exactly two migrations applied on first run (v10, v11)")
            check(applied[0].version == 10, "first applied migration is version=10")
            check(applied[1].version == 11, "second applied migration is version=11")
            check(
                applied[0].name == "create_ranking_snapshots_table",
                "v10 migration name matches",
            )
            check(
                applied[1].name == "extend_ranking_snapshots_for_status_and_analysis",
                "v11 migration name matches",
            )

            applied_again = runner.apply(SNAPSHOTS_MIGRATIONS)
            check(applied_again == [], "second apply() is a no-op (idempotent)")

            versions = runner.applied_versions()
            check(10 in versions, "version 10 recorded in schema_migrations")
            check(11 in versions, "version 11 recorded in schema_migrations")
            check(6 not in versions, "version 6 was never applied (still reserved, untouched)")
            check(7 not in versions, "version 7 was never applied (still reserved, untouched)")
            check(8 not in versions, "version 8 was never applied (still reserved, untouched)")
            check(9 not in versions, "version 9 was never applied (still reserved, untouched)")
        finally:
            db.disconnect()


def scenario_table_shape():
    print("\n[Scenario 2] ranking_snapshots table has the v11 columns")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "snapshots_shape.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            _apply_prior_migrations(db)
            MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
            result = db.execute("PRAGMA table_info(ranking_snapshots)")
            columns = {row["name"]: row["type"] for row in result.rows}
            expected = {
                "snapshot_id": "INTEGER",
                "scan_time": "TEXT",
                "symbol": "TEXT",
                "status": "TEXT",
                "recommendation": "TEXT",
                "confidence": "TEXT",
                "priority": "INTEGER",
                "rank": "INTEGER",
                "score": "INTEGER",
                "score_breakdown_json": "TEXT",
                "evidence_summary": "TEXT",
                "error_message": "TEXT",
            }
            for col_name, col_type in expected.items():
                check(col_name in columns, f"column '{col_name}' exists")
                check(columns.get(col_name) == col_type, f"column '{col_name}' is {col_type}")

            check(
                "instrument_id" not in columns,
                "ranking_snapshots has no 'instrument_id' column (that is the "
                "different, reserved-at-version=6 analysis_snapshots schema)",
            )
            check(
                "payload_json" not in columns,
                "ranking_snapshots has no 'payload_json' column (same reason)",
            )
            check(
                "analysis_type" not in columns,
                "ranking_snapshots has no 'analysis_type' column (same reason)",
            )

            pk_columns = [
                row["name"] for row in db.execute("PRAGMA table_info(ranking_snapshots)").rows
                if row["pk"] == 1
            ]
            check(
                pk_columns == ["snapshot_id"],
                "snapshot_id is the sole PRIMARY KEY (surrogate integer)",
            )
        finally:
            db.disconnect()


def scenario_no_foreign_keys_and_nullable_recommendation_fields():
    print("\n[Scenario 3] ranking_snapshots has no FKs; recommendation/confidence/priority/rank are nullable")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "snapshots_no_fk.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            _apply_prior_migrations(db)
            MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
            fk_result = db.execute("PRAGMA foreign_key_list(ranking_snapshots)")
            check(len(fk_result.rows) == 0, "ranking_snapshots declares no foreign keys")

            result = db.execute("PRAGMA table_info(ranking_snapshots)")
            notnull = {row["name"]: row["notnull"] for row in result.rows}
            check(notnull["status"] == 1, "'status' is NOT NULL (defaults to 'success')")
            check(notnull["scan_time"] == 1, "'scan_time' is still NOT NULL")
            check(notnull["symbol"] == 1, "'symbol' is still NOT NULL")
            for col in ("recommendation", "confidence", "priority", "rank"):
                check(notnull[col] == 0, f"'{col}' is nullable (Activation 2.7, for error rows)")
            for col in ("score", "score_breakdown_json", "evidence_summary", "error_message"):
                check(notnull[col] == 0, f"'{col}' is nullable")

            # An error row (no recommendation/confidence/priority/rank/score
            # at all) must be insertable -- this is the exact shape a
            # failed symbol persists as.
            db.execute(
                """
                INSERT INTO ranking_snapshots (scan_time, symbol, status, error_message)
                VALUES (?, ?, ?, ?)
                """,
                ("2026-08-04T00:00:00+00:00", "FAILX", "error", "missing 'watchlist' SkillResult"),
            )
            row = db.execute(
                "SELECT * FROM ranking_snapshots WHERE symbol = 'FAILX'"
            ).rows[0]
            check(row["status"] == "error", "error row's status round-trips")
            check(row["recommendation"] is None, "error row has no recommendation")
            check(row["error_message"] == "missing 'watchlist' SkillResult", "error row's error_message round-trips")
        finally:
            db.disconnect()


def scenario_insert_and_select_row():
    print("\n[Scenario 4] a row can be inserted and read back")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "snapshots_insert.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            _apply_prior_migrations(db)
            MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
            now = "2026-08-01T00:00:00+00:00"
            result = db.execute(
                """
                INSERT INTO ranking_snapshots
                    (scan_time, symbol, recommendation, confidence, priority, rank)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now, "BBCA", "SELL", "LOW", 1, 1),
            )
            check(result.lastrowid is not None, "insert assigns a surrogate snapshot_id")

            rows = db.execute(
                "SELECT * FROM ranking_snapshots WHERE symbol = ?", ("BBCA",)
            ).rows
            check(len(rows) == 1, "exactly one row is stored for the inserted symbol")
            check(rows[0]["scan_time"] == now, "stored scan_time round-trips exactly")
            check(rows[0]["recommendation"] == "SELL", "stored recommendation round-trips exactly")
        finally:
            db.disconnect()


def scenario_restart_preserves_v10_rows_and_autoincrement():
    print("\n[Scenario 5] a v10-only database upgraded to v11 keeps every row and the autoincrement counter")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "snapshots_restart.db"
        cfg = DatabaseConfig(db_path=db_path)

        # --- "before": only version=10 applied, two rows inserted ---
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            _apply_prior_migrations(db)
            v10_only = tuple(m for m in SNAPSHOTS_MIGRATIONS if m.version == 10)
            MigrationRunner(db).apply(v10_only)
            db.execute(
                """
                INSERT INTO ranking_snapshots
                    (scan_time, symbol, recommendation, confidence, priority, rank)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("2026-08-01T00:00:00+00:00", "BBCA", "BUY", "HIGH", 1, 1),
            )
            result = db.execute(
                """
                INSERT INTO ranking_snapshots
                    (scan_time, symbol, recommendation, confidence, priority, rank)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("2026-08-01T00:00:00+00:00", "TLKM", "SELL", "LOW", 2, 2),
            )
            last_v10_id = result.lastrowid
            check(last_v10_id == 2, "second v10 row got snapshot_id=2 (sanity check before upgrade)")
        finally:
            db.disconnect()

        # --- "restart": reconnect (simulates app restart), then apply v11 ---
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            applied = MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
            check(len(applied) == 1, "only version=11 is pending on the upgrade run")
            check(applied[0].version == 11, "the pending migration is version=11")

            rows = db.execute("SELECT * FROM ranking_snapshots ORDER BY snapshot_id ASC").rows
            check(len(rows) == 2, "both pre-existing rows survived the v10->v11 rebuild")
            check(rows[0]["symbol"] == "BBCA" and rows[0]["snapshot_id"] == 1, "row 1 keeps its original snapshot_id")
            check(rows[1]["symbol"] == "TLKM" and rows[1]["snapshot_id"] == 2, "row 2 keeps its original snapshot_id")
            check(rows[0]["status"] == "success", "pre-existing rows backfill to status='success'")
            check(rows[0]["recommendation"] == "BUY", "pre-existing recommendation is preserved verbatim")
            check(rows[0]["score"] is None, "pre-existing rows have no score (never computed for them)")

            # AUTOINCREMENT counter must have survived the rebuild: the
            # next inserted row must NOT reuse snapshot_id=1 or 2.
            new_result = db.execute(
                """
                INSERT INTO ranking_snapshots (scan_time, symbol, status, error_message)
                VALUES (?, ?, ?, ?)
                """,
                ("2026-08-02T00:00:00+00:00", "ASII", "error", "simulated failure"),
            )
            check(
                new_result.lastrowid == 3,
                "a new row after the upgrade continues the sequence at snapshot_id=3, "
                "never reusing 1 or 2 (AUTOINCREMENT counter survived rebuild)",
            )
        finally:
            db.disconnect()

        # --- second restart: nothing pending, data still intact ---
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            applied_again = MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
            check(applied_again == [], "a further restart applies nothing new (fully migrated)")
            rows = db.execute("SELECT * FROM ranking_snapshots ORDER BY snapshot_id ASC").rows
            check(len(rows) == 3, "all three rows (2 pre-upgrade + 1 post-upgrade) are still present")
        finally:
            db.disconnect()


def main() -> int:
    scenario_migration_applies_and_is_idempotent()
    scenario_table_shape()
    scenario_no_foreign_keys_and_nullable_recommendation_fields()
    scenario_insert_and_select_row()
    scenario_restart_preserves_v10_rows_and_autoincrement()

    print("\n" + "=" * 60)
    print(f"SNAPSHOT MIGRATION TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())