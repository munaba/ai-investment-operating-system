"""Standalone regression checks for
``Repository.persistence.order_repository.OrderRepository``.

Covers Sprint 4 STEP 3 (Order persistence):

* create/get_by_id/list_by_account/list_all/update/update_status happy
  paths;
* ``status`` validation raises ``ValidationError`` for out-of-domain
  values (existing exception, no new exception class introduced);
* ``order_id`` is repository-generated (autoincrement), never
  caller-supplied;
* ``filled_quantity`` defaults to ``0.0`` when omitted from ``create``;
* this repository performs no fill/average/fee/tax/lot/cash/portfolio
  computation -- ``update``/``update_status`` persist exactly the
  values the caller supplies.

Run directly with ``python Tests/test_order_repository.py`` -- no
external test framework required, matching
``test_position_repository.py``.
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
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.order_constants import ORDER_STATUSES  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402

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
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "orders_repo.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    order_repo = OrderRepository(manager)
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
    return order_repo


def scenario_create_and_get():
    print("\n[Scenario 1] create / get_by_id happy path")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        order = repo.create(
            account_id="paper-id",
            symbol="BBCA",
            action="BUY",
            quantity=100.0,
            requested_price=9500.0,
            filled_price=0.0,
            status="NEW",
            reason="initial order",
        )
        check(order.order_id is not None, "create() returns an order_id (repository-generated)")
        check(order.symbol == "BBCA", "create() returns order with correct symbol")
        check(order.filled_quantity == 0.0, "filled_quantity defaults to 0.0 when omitted")
        check(order.created_at == order.updated_at, "created_at == updated_at on creation")

        fetched = repo.get_by_id(order.order_id)
        check(fetched is not None, "get_by_id() finds the created order")
        check(fetched.quantity == 100.0, "get_by_id() returns correct quantity")
        check(fetched.status == "NEW", "get_by_id() returns correct status")

        missing = repo.get_by_id(999999)
        check(missing is None, "get_by_id() returns None for missing order")


def scenario_create_with_explicit_filled_quantity():
    print("\n[Scenario 2] create() accepts an explicit filled_quantity")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        order = repo.create(
            account_id="paper-id",
            symbol="BBCA",
            action="BUY",
            quantity=100.0,
            requested_price=9500.0,
            filled_price=9500.0,
            status="PARTIALLY_FILLED",
            reason="partial fill supplied by caller",
            filled_quantity=40.0,
        )
        check(order.filled_quantity == 40.0, "create() stores caller-supplied filled_quantity as-is")
        fetched = repo.get_by_id(order.order_id)
        check(fetched.filled_quantity == 40.0, "get_by_id() returns caller-supplied filled_quantity unchanged")


def scenario_list_by_account_and_list_all():
    print("\n[Scenario 3] list_by_account() / list_all()")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        repo.create("paper-id", "BBCA", "BUY", 100.0, 9500.0, 0.0, "NEW", "order 1")
        repo.create("paper-id", "TLKM", "SELL", 50.0, 3200.0, 0.0, "NEW", "order 2")

        by_account = repo.list_by_account("paper-id")
        check(len(by_account) == 2, "list_by_account() returns all orders for the account")
        ids = [o.order_id for o in by_account]
        check(ids == sorted(ids), "list_by_account() ordered by order_id ascending")

        by_account_missing = repo.list_by_account("does-not-exist")
        check(by_account_missing == [], "list_by_account() returns empty list for unknown account")

        all_orders = repo.list_all()
        check(len(all_orders) == 2, "list_all() returns every order")


def scenario_update_mutates_in_place():
    print("\n[Scenario 4] update() mutates fill fields in place, no fill computation")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        created = repo.create("paper-id", "BBCA", "BUY", 100.0, 9500.0, 0.0, "PENDING", "placed")

        repo.update(
            created.order_id,
            filled_price=9550.0,
            filled_quantity=100.0,
            status="FILLED",
            reason="fully filled",
        )
        updated = repo.get_by_id(created.order_id)

        check(updated.filled_price == 9550.0, "filled_price updated to exactly the caller-supplied value")
        check(updated.filled_quantity == 100.0, "filled_quantity updated to exactly the caller-supplied value")
        check(updated.status == "FILLED", "status updated to exactly the caller-supplied value")
        check(updated.reason == "fully filled", "reason updated to exactly the caller-supplied value")
        check(updated.updated_at >= created.created_at, "updated_at is refreshed by update()")
        check(updated.account_id == "paper-id", "account_id unchanged by update()")
        check(updated.quantity == 100.0, "quantity (requested) unchanged by update()")


def scenario_update_status_only_touches_status_and_reason():
    print("\n[Scenario 5] update_status() leaves fill fields untouched")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        created = repo.create(
            "paper-id", "BBCA", "BUY", 100.0, 9500.0, 9500.0, "PENDING", "placed",
            filled_quantity=30.0,
        )

        repo.update_status(created.order_id, status="REJECTED", reason="risk check failed")
        updated = repo.get_by_id(created.order_id)

        check(updated.status == "REJECTED", "update_status() updates status")
        check(updated.reason == "risk check failed", "update_status() updates reason")
        check(updated.filled_price == 9500.0, "update_status() leaves filled_price untouched")
        check(updated.filled_quantity == 30.0, "update_status() leaves filled_quantity untouched")
        check(updated.updated_at >= created.created_at, "updated_at is refreshed by update_status()")


def scenario_invalid_status_raises_validation_error():
    print("\n[Scenario 6] invalid status raises ValidationError (existing exception, no new class)")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        try:
            repo.create("paper-id", "BBCA", "BUY", 100.0, 9500.0, 0.0, "BOGUS", "bad status")
            check(False, "invalid status on create() raises ValidationError")
        except ValidationError:
            check(True, "invalid status on create() raises ValidationError")
        except Exception as exc:  # noqa: BLE001
            check(False, f"invalid status on create() raised wrong exception type: {type(exc).__name__}")

        created = repo.create("paper-id", "TLKM", "SELL", 50.0, 3200.0, 0.0, "NEW", "ok")
        try:
            repo.update(created.order_id, filled_price=0.0, filled_quantity=0.0, status="bogus", reason="x")
            check(False, "invalid status on update() raises ValidationError")
        except ValidationError:
            check(True, "invalid status on update() raises ValidationError")
        except Exception as exc:  # noqa: BLE001
            check(False, f"invalid status on update() raised wrong exception type: {type(exc).__name__}")

        try:
            repo.update_status(created.order_id, status="bogus", reason="x")
            check(False, "invalid status on update_status() raises ValidationError")
        except ValidationError:
            check(True, "invalid status on update_status() raises ValidationError")
        except Exception as exc:  # noqa: BLE001
            check(False, f"invalid status on update_status() raised wrong exception type: {type(exc).__name__}")


def scenario_domain_values_consistent_with_single_source_of_truth():
    print("\n[Scenario 7] every ORDER_STATUSES value passes both Python and SQL layers")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        count = 0
        for status in ORDER_STATUSES:
            repo.create("paper-id", f"SYM-{status}", "BUY", 1.0, 1.0, 0.0, status, "test")
            count += 1
        check(
            len(repo.list_all()) == count,
            f"all {count} ORDER_STATUSES values inserted successfully",
        )


def scenario_no_business_logic_methods_exist():
    print("\n[Scenario 8] OrderRepository has no execute/validate/fill/buy/sell business-logic methods")
    forbidden_names = (
        "execute_order", "validate", "fill", "buy", "sell", "merge",
        "allocate", "calculate",
    )
    for name in forbidden_names:
        check(not hasattr(OrderRepository, name), f"OrderRepository has no '{name}' method")


def main() -> int:
    scenario_create_and_get()
    scenario_create_with_explicit_filled_quantity()
    scenario_list_by_account_and_list_all()
    scenario_update_mutates_in_place()
    scenario_update_status_only_touches_status_and_reason()
    scenario_invalid_status_raises_validation_error()
    scenario_domain_values_consistent_with_single_source_of_truth()
    scenario_no_business_logic_methods_exist()

    print("\n" + "=" * 60)
    print(f"ORDER REPOSITORY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())