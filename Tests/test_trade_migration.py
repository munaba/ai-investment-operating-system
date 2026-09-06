"""Standalone regression checks for ``Database.migrations_trades.TRADES_MIGRATIONS``.

Covers Sprint 4 STEP 4 (Trades):

* migration ``version=5`` applies idempotently and creates the
  ``trades`` table with the expected columns/types;
* the ``account_id`` foreign key rejects a trade pointing at a
  non-existent account;
* the ``order_id`` foreign key rejects a trade pointing at a
  non-existent order;
* a trade referencing a real account + real order is accepted.

Run directly with ``python Tests/test_trade_migration.py`` -- no
external test framework required, matching ``test_order_migration.py``.
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
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
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


def _seed_order(db: SQLiteDatabase, account_id: str = "paper-id", symbol: str = "BBCA") -> int:
    now = "2026-08-01T00:00:00+00:00"
    result = db.execute(
        """
        INSERT INTO orders
            (account_id, symbol, action, quantity, requested_price,
             filled_price, filled_quantity, status, reason,
             created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (account_id, symbol, "BUY", 100.0, 9500.0, 9500.0, 100.0,
         "FILLED", "test order", now, now),
    )
    return result.lastrowid


def scenario_migration_applies_and_is_idempotent():
    print("\n[Scenario 1] version=5 applies and is idempotent")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "trades_migration.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)
            runner.apply(ORDERS_MIGRATIONS)
            applied = runner.apply(TRADES_MIGRATIONS)
            check(len(applied) == 1, "exactly one migration applied on first run")
            check(applied[0].version == 5, "applied migration is version=5")
            check(applied[0].name == "create_trades_table", "applied migration name matches")

            applied_again = runner.apply(TRADES_MIGRATIONS)
            check(applied_again == [], "second apply() is a no-op (idempotent)")

            versions = runner.applied_versions()
            check(5 in versions, "version 5 recorded in schema_migrations")
        finally:
            db.disconnect()


def scenario_table_shape():
    print("\n[Scenario 2] trades table has expected columns")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "trades_shape.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)
            runner.apply(ORDERS_MIGRATIONS)
            runner.apply(TRADES_MIGRATIONS)
            result = db.execute("PRAGMA table_info(trades)")
            columns = {row["name"]: row["type"] for row in result.rows}
            expected = {
                "trade_id": "INTEGER",
                "order_id": "INTEGER",
                "account_id": "TEXT",
                "symbol": "TEXT",
                "action": "TEXT",
                "quantity": "REAL",
                "fill_price": "REAL",
                "fee": "REAL",
                "tax": "REAL",
                "executed_at": "TEXT",
            }
            for col_name, col_type in expected.items():
                check(col_name in columns, f"column '{col_name}' exists")
                check(columns.get(col_name) == col_type, f"column '{col_name}' is {col_type}")

            pk_columns = [row["name"] for row in db.execute("PRAGMA table_info(trades)").rows if row["pk"] == 1]
            check(pk_columns == ["trade_id"], "trade_id is the sole PRIMARY KEY (surrogate integer)")
        finally:
            db.disconnect()


def scenario_account_foreign_key_enforced():
    print("\n[Scenario 3] account_id foreign key rejects a non-existent account")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "trades_account_fk.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)
            runner.apply(ORDERS_MIGRATIONS)
            runner.apply(TRADES_MIGRATIONS)
            _seed_account(db, "real-account")
            order_id = _seed_order(db, "real-account")
            now = "2026-08-01T00:00:00+00:00"

            try:
                db.execute(
                    """
                    INSERT INTO trades
                        (order_id, account_id, symbol, action, quantity,
                         fill_price, fee, tax, executed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (order_id, "does-not-exist", "BBCA", "BUY", 100.0,
                     9500.0, 100.0, 50.0, now),
                )
                check(False, "trade referencing a non-existent account_id rejected by FK")
            except Exception:
                check(True, "trade referencing a non-existent account_id rejected by FK")
        finally:
            db.disconnect()


def scenario_order_foreign_key_enforced():
    print("\n[Scenario 4] order_id foreign key rejects a non-existent order")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "trades_order_fk.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)
            runner.apply(ORDERS_MIGRATIONS)
            runner.apply(TRADES_MIGRATIONS)
            _seed_account(db, "real-account")
            now = "2026-08-01T00:00:00+00:00"

            try:
                db.execute(
                    """
                    INSERT INTO trades
                        (order_id, account_id, symbol, action, quantity,
                         fill_price, fee, tax, executed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (999999, "real-account", "BBCA", "BUY", 100.0,
                     9500.0, 100.0, 50.0, now),
                )
                check(False, "trade referencing a non-existent order_id rejected by FK")
            except Exception:
                check(True, "trade referencing a non-existent order_id rejected by FK")

            order_id = _seed_order(db, "real-account")
            db.execute(
                """
                INSERT INTO trades
                    (order_id, account_id, symbol, action, quantity,
                     fill_price, fee, tax, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (order_id, "real-account", "BBCA", "BUY", 100.0,
                 9500.0, 100.0, 50.0, now),
            )
            check(True, "trade referencing a real order_id and account_id is accepted")
        finally:
            db.disconnect()


def scenario_no_status_check_constraint_by_design():
    print("\n[Scenario 5] trades has no status CHECK constraint (LOCKED: no domain field requires one)")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "trades_no_status.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)
            runner.apply(ORDERS_MIGRATIONS)
            runner.apply(TRADES_MIGRATIONS)
            result = db.execute("PRAGMA table_info(trades)")
            columns = {row["name"] for row in result.rows}
            check("status" not in columns, "trades table has no 'status' column")
        finally:
            db.disconnect()


def main() -> int:
    scenario_migration_applies_and_is_idempotent()
    scenario_table_shape()
    scenario_account_foreign_key_enforced()
    scenario_order_foreign_key_enforced()
    scenario_no_status_check_constraint_by_design()

    print("\n" + "=" * 60)
    print(f"TRADE MIGRATION TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())