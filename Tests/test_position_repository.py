"""Standalone regression checks for
``Repository.persistence.position_repository.PositionRepository``.

Covers Sprint 4 STEP 2 (Position persistence):

* create/get_by_id/get_open_position/list_by_account/list_all/update
  happy paths;
* ``status`` validation raises ``ValidationError`` for out-of-domain
  values (existing exception, no new exception class introduced);
* ``position_id`` is repository-generated (autoincrement), never
  caller-supplied;
* a position can be reopened after being closed -- proves
  ``position_id``, not ``(account_id, symbol)``, is the identity;
* this repository performs no averaging/merge/P&L computation --
  ``update`` persists exactly the values the caller supplies.

Run directly with ``python Tests/test_position_repository.py`` -- no
external test framework required, matching ``test_account_repository.py``.
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
from Database.position_constants import POSITION_STATUSES  # noqa: E402
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
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "positions_repo.db")
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


def scenario_create_and_get():
    print("\n[Scenario 1] create / get_by_id happy path")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        position = repo.create(
            account_id="paper-id",
            symbol="BBCA",
            quantity=100.0,
            average_price=9500.0,
            realized_pnl=0.0,
            status="open",
        )
        check(position.position_id is not None, "create() returns a position_id (repository-generated)")
        check(position.symbol == "BBCA", "create() returns position with correct symbol")
        check(position.created_at == position.updated_at, "created_at == updated_at on creation")

        fetched = repo.get_by_id(position.position_id)
        check(fetched is not None, "get_by_id() finds the created position")
        check(fetched.quantity == 100.0, "get_by_id() returns correct quantity")
        check(fetched.status == "open", "get_by_id() returns correct status")

        missing = repo.get_by_id(999999)
        check(missing is None, "get_by_id() returns None for missing position")


def scenario_get_open_position():
    print("\n[Scenario 2] get_open_position() finds the open row, not closed ones")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        repo.create("paper-id", "BBCA", 0.0, 0.0, 500.0, "closed")
        open_position = repo.create("paper-id", "BBCA", 200.0, 9600.0, 0.0, "open")

        found = repo.get_open_position("paper-id", "BBCA")
        check(found is not None, "get_open_position() finds the open row")
        check(found.position_id == open_position.position_id, "get_open_position() returns the correct row")

        none_found = repo.get_open_position("paper-id", "TLKM")
        check(none_found is None, "get_open_position() returns None when no open position exists")


def scenario_list_by_account_and_list_all():
    print("\n[Scenario 3] list_by_account() / list_all()")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        repo.create("paper-id", "BBCA", 100.0, 9500.0, 0.0, "open")
        repo.create("paper-id", "TLKM", 50.0, 3200.0, 0.0, "open")

        by_account = repo.list_by_account("paper-id")
        check(len(by_account) == 2, "list_by_account() returns all positions for the account")
        ids = [p.position_id for p in by_account]
        check(ids == sorted(ids), "list_by_account() ordered by position_id ascending")

        by_account_missing = repo.list_by_account("does-not-exist")
        check(by_account_missing == [], "list_by_account() returns empty list for unknown account")

        all_positions = repo.list_all()
        check(len(all_positions) == 2, "list_all() returns every position")


def scenario_update_mutates_in_place():
    print("\n[Scenario 4] update() mutates in place, no merge/average computation")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        created = repo.create("paper-id", "BBCA", 100.0, 9500.0, 0.0, "open")

        repo.update(created.position_id, quantity=300.0, average_price=9700.0, realized_pnl=15000.0, status="open")
        updated = repo.get_by_id(created.position_id)

        check(updated.quantity == 300.0, "quantity updated to exactly the caller-supplied value")
        check(updated.average_price == 9700.0, "average_price updated to exactly the caller-supplied value")
        check(updated.realized_pnl == 15000.0, "realized_pnl updated to exactly the caller-supplied value")
        check(updated.updated_at >= created.created_at, "updated_at is refreshed by update()")
        check(updated.account_id == "paper-id", "account_id unchanged by update()")


def scenario_position_can_reopen_after_close():
    print("\n[Scenario 5] a new OPEN position after CLOSE gets a distinct position_id")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        first = repo.create("paper-id", "BBCA", 100.0, 9500.0, 0.0, "open")
        repo.update(first.position_id, quantity=0.0, average_price=9500.0, realized_pnl=500.0, status="closed")

        reopened = repo.create("paper-id", "BBCA", 50.0, 9800.0, 0.0, "open")
        check(reopened.position_id != first.position_id, "reopened position gets a new, distinct position_id")

        closed_row = repo.get_by_id(first.position_id)
        check(closed_row.status == "closed", "original closed row is untouched by the reopen")
        check(closed_row.realized_pnl == 500.0, "original closed row's realized_pnl is preserved")

        open_lookup = repo.get_open_position("paper-id", "BBCA")
        check(open_lookup.position_id == reopened.position_id, "get_open_position() now finds the reopened row")


def scenario_invalid_status_raises_validation_error():
    print("\n[Scenario 6] invalid status raises ValidationError (existing exception, no new class)")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        try:
            repo.create("paper-id", "BBCA", 100.0, 9500.0, 0.0, "pending")
            check(False, "invalid status on create() raises ValidationError")
        except ValidationError:
            check(True, "invalid status on create() raises ValidationError")
        except Exception as exc:  # noqa: BLE001
            check(False, f"invalid status on create() raised wrong exception type: {type(exc).__name__}")

        created = repo.create("paper-id", "TLKM", 50.0, 3200.0, 0.0, "open")
        try:
            repo.update(created.position_id, quantity=50.0, average_price=3200.0, realized_pnl=0.0, status="bogus")
            check(False, "invalid status on update() raises ValidationError")
        except ValidationError:
            check(True, "invalid status on update() raises ValidationError")
        except Exception as exc:  # noqa: BLE001
            check(False, f"invalid status on update() raised wrong exception type: {type(exc).__name__}")


def scenario_domain_values_consistent_with_single_source_of_truth():
    print("\n[Scenario 7] every POSITION_STATUSES value passes both Python and SQL layers")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        count = 0
        for status in POSITION_STATUSES:
            repo.create("paper-id", f"SYM-{status}", 1.0, 1.0, 0.0, status)
            count += 1
        check(
            len(repo.list_all()) == count,
            f"all {count} POSITION_STATUSES values inserted successfully",
        )


def scenario_stop_loss_take_profit_persist_and_read_back():
    print("\n[Scenario 9] stop_loss/take_profit (Activation 3.8 STEP 2) persist and read back")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        created = repo.create(
            account_id="paper-id",
            symbol="BBCA",
            quantity=100.0,
            average_price=9500.0,
            realized_pnl=0.0,
            status="open",
            stop_loss=9000.0,
            take_profit=10000.0,
        )
        check(created.stop_loss == 9000.0, "create() returns the supplied stop_loss")
        check(created.take_profit == 10000.0, "create() returns the supplied take_profit")

        fetched = repo.get_by_id(created.position_id)
        check(fetched.stop_loss == 9000.0, "get_by_id() reads back stop_loss")
        check(fetched.take_profit == 10000.0, "get_by_id() reads back take_profit")

        repo.update(
            created.position_id,
            quantity=100.0,
            average_price=9500.0,
            realized_pnl=0.0,
            status="open",
            stop_loss=9100.0,
            take_profit=10200.0,
        )
        updated = repo.get_by_id(created.position_id)
        check(updated.stop_loss == 9100.0, "update() overwrites stop_loss with the new value")
        check(updated.take_profit == 10200.0, "update() overwrites take_profit with the new value")


def scenario_stop_loss_take_profit_default_to_none():
    print("\n[Scenario 10] stop_loss/take_profit default to None/NULL when omitted")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        created = repo.create("paper-id", "BBCA", 100.0, 9500.0, 0.0, "open")
        check(created.stop_loss is None, "create() without stop_loss/take_profit defaults stop_loss to None")
        check(created.take_profit is None, "create() without stop_loss/take_profit defaults take_profit to None")

        fetched = repo.get_by_id(created.position_id)
        check(fetched.stop_loss is None, "get_by_id() reads back stop_loss as None (SQL NULL)")
        check(fetched.take_profit is None, "get_by_id() reads back take_profit as None (SQL NULL)")


def scenario_positions_migration_additive_and_idempotent():
    print("\n[Scenario 11] version=14 stop_loss/take_profit migration applies additively and idempotently")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "positions_migration_additive.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)
            applied = runner.apply(POSITIONS_MIGRATIONS)
            check(len(applied) == 4, "exactly four positions migrations applied on first run")
            check(applied[0].version == 3, "first applied migration is version=3")
            check(applied[1].version == 14, "second applied migration is version=14")
            check(applied[2].version == 17, "third applied migration is version=17")
            check(applied[3].version == 18, "fourth applied migration is version=18")
            check(
                applied[1].name == "add_positions_stop_loss_take_profit_columns",
                "second applied migration name matches",
            )
            check(
                applied[2].name == "add_positions_buy_fee_accumulated_column",
                "third applied migration name matches",
            )
            check(
                applied[3].name == "add_positions_direction_column",
                "fourth applied migration name matches",
            )

            applied_again = runner.apply(POSITIONS_MIGRATIONS)
            check(applied_again == [], "second apply() is a no-op (idempotent)")

            columns = {row["name"] for row in db.execute("PRAGMA table_info(positions)").rows}
            check("stop_loss" in columns, "positions table has a stop_loss column")
            check("take_profit" in columns, "positions table has a take_profit column")
            check("buy_fee_accumulated" in columns, "positions table has a buy_fee_accumulated column")
            check("direction" in columns, "positions table has a direction column")
        finally:
            db.disconnect()


def scenario_migration_preserves_existing_rows():
    print("\n[Scenario 12] applying version=14 to a database with existing rows does not lose data")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "positions_migration_preserve.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            runner.apply(ACCOUNTS_MIGRATIONS)
            # Simulate a database that only has version=3 applied (pre-Activation-3.8),
            # already holding a real position row, then apply the full tuple (which now
            # also includes version=14) on top of it.
            from Database.migrations import Migration

            pre_existing_migration = tuple(m for m in POSITIONS_MIGRATIONS if m.version == 3)
            runner.apply(pre_existing_migration)

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
                     status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("paper-id", "BBCA", 100.0, 9500.0, 0.0, "open", now, now),
            )

            applied = runner.apply(POSITIONS_MIGRATIONS)
            check(
                len(applied) == 3,
                "version=14, version=17, and version=18 all apply on top of an already-migrated version=3 database",
            )
            check(applied[0].version == 14, "the first newly applied migration is version=14")
            check(applied[1].version == 17, "the second newly applied migration is version=17")
            check(applied[2].version == 18, "the third newly applied migration is version=18")

            row = db.execute("SELECT * FROM positions WHERE symbol = 'BBCA'").rows[0]
            check(row["quantity"] == 100.0, "pre-existing row's quantity is untouched")
            check(row["average_price"] == 9500.0, "pre-existing row's average_price is untouched")
            check(row["status"] == "open", "pre-existing row's status is untouched")
            check(row["buy_fee_accumulated"] == 0.0, "pre-existing row backfills buy_fee_accumulated to 0.0")
            check(row["stop_loss"] is None, "pre-existing row backfills stop_loss to NULL")
            check(row["take_profit"] is None, "pre-existing row backfills take_profit to NULL")
            check(row["direction"] == "LONG", "pre-existing row backfills direction to 'LONG'")
        finally:
            db.disconnect()


def scenario_stop_loss_take_profit_survive_restart():
    print("\n[Scenario 13] stop_loss/take_profit survive closing and reopening the same database")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "positions_restart.db"
        cfg = DatabaseConfig(db_path=db_path)
        db = SQLiteDatabase(cfg)
        db.connect()
        MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
        MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
        manager = DatabaseManager(db, cfg)
        account_repo = AccountRepository(manager)
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
        position_repo = PositionRepository(manager)
        created = position_repo.create(
            "paper-id", "BBCA", 100.0, 9500.0, 0.0, "open",
            stop_loss=9000.0, take_profit=10000.0,
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
            check(reread.stop_loss == 9000.0, "stop_loss survives a database restart")
            check(reread.take_profit == 10000.0, "take_profit survives a database restart")
        finally:
            db2.disconnect()


def scenario_no_business_logic_methods_exist():
    print("\n[Scenario 8] PositionRepository has no merge/average/P&L business-logic methods")
    forbidden_names = ("merge", "buy", "sell", "close_position", "average", "compute_pnl", "reduce")
    for name in forbidden_names:
        check(not hasattr(PositionRepository, name), f"PositionRepository has no '{name}' method")


def main() -> int:
    scenario_create_and_get()
    scenario_get_open_position()
    scenario_list_by_account_and_list_all()
    scenario_update_mutates_in_place()
    scenario_position_can_reopen_after_close()
    scenario_invalid_status_raises_validation_error()
    scenario_domain_values_consistent_with_single_source_of_truth()
    scenario_stop_loss_take_profit_persist_and_read_back()
    scenario_stop_loss_take_profit_default_to_none()
    scenario_positions_migration_additive_and_idempotent()
    scenario_migration_preserves_existing_rows()
    scenario_stop_loss_take_profit_survive_restart()
    scenario_no_business_logic_methods_exist()

    print("\n" + "=" * 60)
    print(f"POSITION REPOSITORY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())