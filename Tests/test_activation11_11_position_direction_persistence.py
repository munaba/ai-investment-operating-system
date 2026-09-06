"""Standalone regression checks for Activation 11.11 -- persisting
``Position.direction`` (LONG/SHORT).

Covers exactly the Activation 11.11 HARD SCOPE LIMIT: schema + model +
repository persistence only. This file does NOT exercise
``Business.position_manager.PositionManager``,
``Business.paper_trading_engine.PaperTradingEngine``, or any Forex
account/order flow -- none of those are modified by this Activation.

Scenarios (per the Activation 11.11 brief):

* A -- a position created without an explicit ``direction`` defaults
  to ``"LONG"``;
* B -- an explicit ``direction="LONG"`` round-trips exactly;
* C -- an explicit ``direction="SHORT"`` round-trips exactly;
* D -- ``update()`` can change an existing position's ``direction``
  from ``"LONG"`` to ``"SHORT"`` (persistence-only -- this is NOT
  production position-reversal behavior, which does not exist yet);
* E -- an invalid ``direction`` value is rejected by the repository
  (Python-level ``ValidationError``, backed by the SQL ``CHECK``
  constraint as the final guard);
* F -- a database containing a ``Position`` row created before the
  ``direction`` column existed (pre-version=18) backfills to
  ``"LONG"`` once the migration is applied, and no other existing
  column is disturbed.

Run directly with ``python Tests/test_activation11_11_position_direction_persistence.py``
-- no external test framework required, matching
``Tests/test_position_repository.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.position_constants import POSITION_DIRECTIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402

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


def _build_repository(tmp_dir: str):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "positions_direction_repo.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    position_repo = PositionRepository(manager)
    account_repo.create(
        account_id="paper-id",
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=100_000_000.0,
        equity=100_000_000.0,
        buying_power=100_000_000.0,
    )
    return position_repo


def scenario_a_default_direction_is_long():
    print("\n[Scenario A] create() without explicit direction defaults to LONG")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        created = repo.create("paper-id", "BBCA", 100.0, 9500.0, 0.0, "open")
        check(created.direction == "LONG", "create() returns direction == 'LONG' by default")

        fetched = repo.get_by_id(created.position_id)
        check(fetched.direction == "LONG", "get_by_id() reads back direction == 'LONG' by default")


def scenario_b_explicit_long_round_trips():
    print("\n[Scenario B] explicit direction='LONG' persists and reads back exactly")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        created = repo.create(
            account_id="paper-id",
            symbol="BBCA",
            quantity=100.0,
            average_price=9500.0,
            realized_pnl=0.0,
            status="open",
            direction="LONG",
        )
        check(created.direction == "LONG", "create() returns the explicitly supplied direction='LONG'")

        fetched = repo.get_by_id(created.position_id)
        check(fetched.direction == "LONG", "get_by_id() reads back the explicitly supplied direction='LONG'")


def scenario_c_explicit_short_round_trips():
    print("\n[Scenario C] explicit direction='SHORT' persists and reads back exactly")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        created = repo.create(
            account_id="paper-id",
            symbol="EURUSD",
            quantity=10000.0,
            average_price=1.0850,
            realized_pnl=0.0,
            status="open",
            direction="SHORT",
        )
        check(created.direction == "SHORT", "create() returns the explicitly supplied direction='SHORT'")

        fetched = repo.get_by_id(created.position_id)
        check(fetched.direction == "SHORT", "get_by_id() reads back the explicitly supplied direction='SHORT'")


def scenario_d_update_changes_direction():
    print("\n[Scenario D] update() persists a direction change (persistence contract only, not production reversal)")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        created = repo.create(
            account_id="paper-id",
            symbol="EURUSD",
            quantity=10000.0,
            average_price=1.0850,
            realized_pnl=0.0,
            status="open",
            direction="LONG",
        )
        check(created.direction == "LONG", "position created with direction='LONG'")

        repo.update(
            created.position_id,
            quantity=10000.0,
            average_price=1.0850,
            realized_pnl=0.0,
            status="open",
            direction="SHORT",
        )
        updated = repo.get_by_id(created.position_id)
        check(updated.direction == "SHORT", "update() overwrites direction with the new explicit value")


def scenario_e_invalid_direction_rejected():
    print("\n[Scenario E] invalid direction is rejected by the repository")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        try:
            repo.create(
                account_id="paper-id",
                symbol="BBCA",
                quantity=100.0,
                average_price=9500.0,
                realized_pnl=0.0,
                status="open",
                direction="INVALID",
            )
            check(False, "invalid direction on create() raises ValidationError")
        except ValidationError:
            check(True, "invalid direction on create() raises ValidationError")
        except Exception as exc:  # noqa: BLE001
            check(False, f"invalid direction on create() raised wrong exception type: {type(exc).__name__}")

        created = repo.create("paper-id", "TLKM", 50.0, 3200.0, 0.0, "open")
        try:
            repo.update(
                created.position_id,
                quantity=50.0,
                average_price=3200.0,
                realized_pnl=0.0,
                status="open",
                direction="SIDEWAYS",
            )
            check(False, "invalid direction on update() raises ValidationError")
        except ValidationError:
            check(True, "invalid direction on update() raises ValidationError")
        except Exception as exc:  # noqa: BLE001
            check(False, f"invalid direction on update() raised wrong exception type: {type(exc).__name__}")

        # Confirm every POSITION_DIRECTIONS value is accepted (mirrors
        # test_position_repository.py's status single-source-of-truth check).
        count = 0
        for direction in POSITION_DIRECTIONS:
            repo.create("paper-id", f"SYM-{direction}", 1.0, 1.0, 0.0, "open", direction=direction)
            count += 1
        check(
            len(repo.list_by_account("paper-id")) >= count,
            f"all {count} POSITION_DIRECTIONS values inserted successfully",
        )


def scenario_f_existing_rows_default_to_long_after_migration():
    print("\n[Scenario F] a Position row created before version=18 backfills to direction='LONG'")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "positions_direction_migration.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)

            # Simulate a database that only has version=3/14/17 applied
            # (pre-Activation-11.11), already holding a real position row,
            # then apply the full tuple (which now also includes
            # version=18) on top of it.
            pre_existing_migrations = tuple(m for m in POSITIONS_MIGRATIONS if m.version in (3, 14, 17))
            runner.apply(pre_existing_migrations)

            now = "2026-08-01T00:00:00+00:00"
            db.execute(
                """
                INSERT INTO accounts
                    (account_id, account_name, mode, currency, asset_class,
                     cash, equity, buying_power, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("paper-id", "Paper Indonesia", "paper", "IDR", "stock_id",
                 100_000_000.0, 100_000_000.0, 100_000_000.0, now, now),
            )
            db.execute(
                """
                INSERT INTO positions
                    (account_id, symbol, quantity, average_price, realized_pnl,
                     status, created_at, updated_at, stop_loss, take_profit,
                     buy_fee_accumulated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("paper-id", "BBCA", 100.0, 9500.0, 500.0, "open", now, now, 9000.0, None, 12.5),
            )

            applied = runner.apply(POSITIONS_MIGRATIONS)
            check(len(applied) == 1, "only version=18 remains pending and applies on top of an already-migrated database")
            check(applied[0].version == 18, "the newly applied migration is version=18")

            manager = DatabaseManager(db, cfg)
            position_repo = PositionRepository(manager)
            rows = position_repo.list_by_account("paper-id")
            check(len(rows) == 1, "the pre-existing position row is preserved (no data loss)")

            existing_position = rows[0]
            check(existing_position.direction == "LONG", "existing_position.direction == 'LONG' after migration")
            # Every other pre-existing column must be untouched by this migration.
            check(existing_position.symbol == "BBCA", "symbol unchanged by the direction migration")
            check(existing_position.quantity == 100.0, "quantity unchanged by the direction migration")
            check(existing_position.average_price == 9500.0, "average_price unchanged by the direction migration")
            check(existing_position.realized_pnl == 500.0, "realized_pnl unchanged by the direction migration")
            check(existing_position.status == "open", "status unchanged by the direction migration")
            check(existing_position.stop_loss == 9000.0, "stop_loss unchanged by the direction migration")
            check(existing_position.take_profit is None, "take_profit unchanged by the direction migration")
            check(existing_position.buy_fee_accumulated == 12.5, "buy_fee_accumulated unchanged by the direction migration")
        finally:
            db.disconnect()


def scenario_g_direction_survives_restart():
    print("\n[Scenario G] direction survives closing and reopening the database")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "positions_direction_restart.db"
        cfg = DatabaseConfig(db_path=db_path)
        db = SQLiteDatabase(cfg)
        db.connect()
        MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
        MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
        manager = DatabaseManager(db, cfg)
        AccountRepository(manager).create(
            account_id="paper-id",
            account_name="Paper Indonesia",
            mode="paper",
            currency="IDR",
            asset_class="stock_id",
            cash=100_000_000.0,
            equity=100_000_000.0,
            buying_power=100_000_000.0,
        )
        position_repo = PositionRepository(manager)
        created = position_repo.create(
            "paper-id", "EURUSD", 10000.0, 1.0850, 0.0, "open", direction="SHORT",
        )
        db.disconnect()

        cfg2 = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg2)
        db2.connect()
        try:
            manager2 = DatabaseManager(db2, cfg2)
            position_repo2 = PositionRepository(manager2)
            reread = position_repo2.get_by_id(created.position_id)
            check(reread is not None, "position is still present after reopening the database")
            check(reread.direction == "SHORT", "direction survives a database restart")
        finally:
            db2.disconnect()


def main() -> int:
    scenario_a_default_direction_is_long()
    scenario_b_explicit_long_round_trips()
    scenario_c_explicit_short_round_trips()
    scenario_d_update_changes_direction()
    scenario_e_invalid_direction_rejected()
    scenario_f_existing_rows_default_to_long_after_migration()
    scenario_g_direction_survives_restart()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 11.11 POSITION DIRECTION PERSISTENCE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())