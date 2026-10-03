"""Standalone regression checks for ``Database.migrations_orders.ORDERS_MIGRATIONS``.

Covers Sprint 4 STEP 3 (Orders):

* migration ``version=4`` applies idempotently and creates the
  ``orders`` table with the expected columns/types;
* the ``status`` SQL ``CHECK`` constraint (generated from
  ``Database.order_constants``) rejects out-of-domain values and
  accepts every value in ``ORDER_STATUSES``;
* the ``account_id`` foreign key rejects an order pointing at a
  non-existent account.

Run directly with ``python Tests/test_order_migration.py`` -- no
external test framework required, matching
``test_account_migration.py``.
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
from Database.order_constants import ORDER_STATUSES  # noqa: E402
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


def _seed_account(db: SQLiteDatabase, account_id: str = "paper-id") -> None:
    now = "2026-08-01T00:00:00+00:00"
    db.execute(
        """
        INSERT INTO accounts
            (account_id, account_name, mode, currency, asset_class,
             cash, equity, buying_power, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (account_id, f"Account {account_id}", "paper", "IDR", "stock_id",
         100_000_000.0, 100_000_000.0, 100_000_000.0, now, now),
    )


def scenario_migration_applies_and_is_idempotent():
    print("\n[Scenario 1] version=4 applies and is idempotent")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "orders_migration.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)
            applied = runner.apply(ORDERS_MIGRATIONS)
            # Activation 5.1 fixture update: ORDERS_MIGRATIONS now
            # declares three migrations (version=4 create_orders_table,
            # version=13 add_orders_filled_at_column, version=15
            # add_orders_analysis_snapshot_id_column -- see
            # Database.migrations_orders), so a first-run apply() over the
            # whole tuple now applies three, not two. This is a genuine
            # change to what ORDERS_MIGRATIONS contains, not a change in
            # migration-runner behavior -- MigrationRunner.apply() itself
            # is untouched.
            check(len(applied) == 3, "exactly three migrations applied on first run")
            check(applied[0].version == 4, "first applied migration is version=4")
            check(applied[0].name == "create_orders_table", "first applied migration name matches")
            check(applied[1].version == 13, "second applied migration is version=13")
            check(
                applied[1].name == "add_orders_filled_at_column",
                "second applied migration name matches",
            )
            check(applied[2].version == 15, "third applied migration is version=15")
            check(
                applied[2].name == "add_orders_analysis_snapshot_id_column",
                "third applied migration name matches",
            )

            applied_again = runner.apply(ORDERS_MIGRATIONS)
            check(applied_again == [], "second apply() is a no-op (idempotent)")

            versions = runner.applied_versions()
            check(4 in versions, "version 4 recorded in schema_migrations")
            check(13 in versions, "version 13 recorded in schema_migrations")
            check(15 in versions, "version 15 recorded in schema_migrations")
        finally:
            db.disconnect()


def scenario_table_shape():
    print("\n[Scenario 2] orders table has expected columns")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "orders_shape.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)
            runner.apply(ORDERS_MIGRATIONS)
            result = db.execute("PRAGMA table_info(orders)")
            columns = {row["name"]: row["type"] for row in result.rows}
            expected = {
                "order_id": "INTEGER",
                "account_id": "TEXT",
                "symbol": "TEXT",
                "action": "TEXT",
                "quantity": "REAL",
                "requested_price": "REAL",
                "filled_price": "REAL",
                "filled_quantity": "REAL",
                "status": "TEXT",
                "reason": "TEXT",
                "created_at": "TEXT",
                "updated_at": "TEXT",
                # Activation 3.4 STEP 2 fixture update: filled_at is the
                # new column added by version=13 (see
                # Database.migrations_orders).
                "filled_at": "TEXT",
            }
            for col_name, col_type in expected.items():
                check(col_name in columns, f"column '{col_name}' exists")
                check(columns.get(col_name) == col_type, f"column '{col_name}' is {col_type}")

            pk_columns = [row["name"] for row in db.execute("PRAGMA table_info(orders)").rows if row["pk"] == 1]
            check(pk_columns == ["order_id"], "order_id is the sole PRIMARY KEY (surrogate integer)")
        finally:
            db.disconnect()


def scenario_status_check_constraint():
    print("\n[Scenario 3] CHECK constraint rejects invalid status, accepts every ORDER_STATUSES value")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "orders_status_check.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)
            runner.apply(ORDERS_MIGRATIONS)
            _seed_account(db)
            now = "2026-08-01T00:00:00+00:00"

            try:
                db.execute(
                    """
                    INSERT INTO orders
                        (account_id, symbol, action, quantity, requested_price,
                         filled_price, filled_quantity, status, reason,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("paper-id", "BBCA", "BUY", 100.0, 9500.0, 0.0, 0.0,
                     "BOGUS_STATUS", "test", now, now),
                )
                check(False, "invalid status 'BOGUS_STATUS' rejected by CHECK constraint")
            except Exception:
                check(True, "invalid status 'BOGUS_STATUS' rejected by CHECK constraint")

            for valid_status in ORDER_STATUSES:
                db.execute(
                    """
                    INSERT INTO orders
                        (account_id, symbol, action, quantity, requested_price,
                         filled_price, filled_quantity, status, reason,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("paper-id", f"SYM-{valid_status}", "BUY", 1.0, 1.0, 0.0, 0.0,
                     valid_status, "test", now, now),
                )
            check(True, "every value in ORDER_STATUSES is accepted by CHECK constraint")
        finally:
            db.disconnect()


def scenario_account_foreign_key_enforced():
    print("\n[Scenario 4] account_id foreign key rejects a non-existent account")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "orders_fk.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)
            runner.apply(ORDERS_MIGRATIONS)
            now = "2026-08-01T00:00:00+00:00"

            try:
                db.execute(
                    """
                    INSERT INTO orders
                        (account_id, symbol, action, quantity, requested_price,
                         filled_price, filled_quantity, status, reason,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("does-not-exist", "BBCA", "BUY", 100.0, 9500.0, 0.0, 0.0,
                     "NEW", "test", now, now),
                )
                check(False, "order referencing a non-existent account_id rejected by FK")
            except Exception:
                check(True, "order referencing a non-existent account_id rejected by FK")

            _seed_account(db, "real-account")
            db.execute(
                """
                INSERT INTO orders
                    (account_id, symbol, action, quantity, requested_price,
                     filled_price, filled_quantity, status, reason,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("real-account", "BBCA", "BUY", 100.0, 9500.0, 0.0, 0.0,
                 "NEW", "test", now, now),
            )
            check(True, "order referencing a real account_id is accepted")
        finally:
            db.disconnect()


def scenario_filled_quantity_defaults_to_zero():
    print("\n[Scenario 5] filled_quantity defaults to 0 when omitted")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "orders_default.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)
            runner.apply(ORDERS_MIGRATIONS)
            _seed_account(db)
            now = "2026-08-01T00:00:00+00:00"

            db.execute(
                """
                INSERT INTO orders
                    (account_id, symbol, action, quantity, requested_price,
                     filled_price, status, reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("paper-id", "BBCA", "BUY", 100.0, 9500.0, 0.0,
                 "NEW", "test", now, now),
            )
            row = db.execute(
                "SELECT filled_quantity FROM orders WHERE symbol = 'BBCA'"
            ).rows[0]
            check(row["filled_quantity"] == 0, "filled_quantity column DEFAULTs to 0 when omitted from INSERT")
        finally:
            db.disconnect()


def main() -> int:
    scenario_migration_applies_and_is_idempotent()
    scenario_table_shape()
    scenario_status_check_constraint()
    scenario_account_foreign_key_enforced()
    scenario_filled_quantity_defaults_to_zero()

    print("\n" + "=" * 60)
    print(f"ORDER MIGRATION TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())