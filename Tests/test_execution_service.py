"""Standalone regression checks for
``Business.execution_service.ExecutionService``.

Covers Sprint 4 STEP 6 (paper execution / business layer):

* PENDING -> FILLED happy path;
* exactly one Trade is created, with the fee/tax placeholder read from
  the canonical ExecutionPolicy (Activation 3.3 STEP 2; default
  policy still reproduces fee=0.0/tax=0.0), quantity copied from the
  Order and fill_price copied
  from Order.requested_price (LOCKED DECISION, Sprint 4 STOP
  resolution -- NOT Order.filled_price, which OrderLifecycleService
  always creates as 0.0 and nothing before execute_order() ever
  changes), and the caller-supplied executed_at persisted unchanged;
* the create_order() -> execute_order() chain (the real
  PaperTradingEngine/STEP 9 call path) produces a nonzero
  Trade.fill_price even though the Order's filled_price stays 0.0
  throughout;
* Order.status is updated to FILLED via OrderRepository.update_status;
* any status other than PENDING (NEW, VALIDATED, REJECTED, and an
  already-FILLED order) raises ValidationError and creates no Trade;
* a second execute_order() call against an already-FILLED order is
  rejected (idempotency) -- never a second Trade;
* this service never touches Account/Position (no such repository
  reference exists on the instance at all).

Run directly with ``python Tests/test_execution_service.py`` -- no
external test framework required, matching
``test_order_lifecycle_service.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402

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


def _build_service(tmp_dir: str):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "execution_service.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    order_repo = OrderRepository(manager)
    trade_repo = TradeRepository(manager)
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
    return ExecutionService(order_repo, trade_repo), order_repo, trade_repo


def _create_order(order_repo, status="PENDING", **overrides):
    kwargs = dict(
        account_id="paper-id",
        symbol="BBCA",
        action="BUY",
        quantity=100.0,
        requested_price=9500.0,
        filled_price=0.0,
        status=status,
        reason="",
    )
    kwargs.update(overrides)
    return order_repo.create(**kwargs)


def scenario_pending_to_filled_happy_path():
    print("\n[Scenario 1] PENDING -> FILLED happy path")
    with tempfile.TemporaryDirectory() as tmp:
        service, order_repo, trade_repo = _build_service(tmp)
        order = _create_order(order_repo)

        trade = service.execute_order(order.order_id, executed_at="2026-08-01T10:00:00+00:00")

        check(trade.trade_id is not None, "execute_order() returns a Trade with a trade_id")
        check(trade.order_id == order.order_id, "Trade.order_id references the executed order")
        check(trade.account_id == "paper-id", "Trade.account_id copied from the Order")
        check(trade.symbol == "BBCA", "Trade.symbol copied from the Order")
        check(trade.action == "BUY", "Trade.action copied from the Order")
        check(trade.quantity == order.quantity, "Trade.quantity == Order.quantity (full fill)")
        check(
            trade.fill_price == order.requested_price,
            "Trade.fill_price == Order.requested_price (LOCKED DECISION, Sprint 4 STOP resolution)",
        )
        check(
            trade.fill_price != order.filled_price,
            "Trade.fill_price is NOT sourced from Order.filled_price "
            "(regression guard: filled_price stays 0.0 in this fixture, "
            "same as the real OrderLifecycleService.create_order() path)",
        )
        check(trade.fee == 0.0, "Trade.fee is the LOCKED 0.0 placeholder")
        check(trade.tax == 0.0, "Trade.tax is the LOCKED 0.0 placeholder")
        check(
            trade.executed_at == "2026-08-01T10:00:00+00:00",
            "Trade.executed_at is exactly the caller-supplied value (no generated timestamp)",
        )

        updated_order = order_repo.get_by_id(order.order_id)
        check(updated_order.status == "FILLED", "Order.status is updated to FILLED")


def scenario_exactly_one_trade_created():
    print("\n[Scenario 2] exactly one Trade is created")
    with tempfile.TemporaryDirectory() as tmp:
        service, order_repo, trade_repo = _build_service(tmp)
        order = _create_order(order_repo)

        service.execute_order(order.order_id, executed_at="2026-08-01T10:00:00+00:00")

        trades = trade_repo.list_by_order(order.order_id)
        check(len(trades) == 1, "exactly one Trade row exists for the order after execution")


def scenario_non_pending_statuses_rejected():
    print("\n[Scenario 3] any status other than PENDING is rejected")
    with tempfile.TemporaryDirectory() as tmp:
        service, order_repo, trade_repo = _build_service(tmp)

        for status in ("NEW", "VALIDATED", "REJECTED", "CANCELLED", "EXPIRED", "PARTIALLY_FILLED"):
            order = _create_order(order_repo, status=status)
            raised = False
            try:
                service.execute_order(order.order_id, executed_at="2026-08-01T10:00:00+00:00")
            except ValidationError:
                raised = True
            check(raised, f"execute_order() rejects an order with status '{status}'")

            trades = trade_repo.list_by_order(order.order_id)
            check(len(trades) == 0, f"no Trade was created for a rejected '{status}' order")

            unchanged = order_repo.get_by_id(order.order_id)
            check(unchanged.status == status, f"order status '{status}' left untouched after rejection")


def scenario_already_filled_order_rejected_idempotency():
    print("\n[Scenario 4] an already-FILLED order cannot be executed again")
    with tempfile.TemporaryDirectory() as tmp:
        service, order_repo, trade_repo = _build_service(tmp)
        order = _create_order(order_repo)

        first_trade = service.execute_order(order.order_id, executed_at="2026-08-01T10:00:00+00:00")
        check(first_trade is not None, "setup: first execution succeeds")

        raised = False
        try:
            service.execute_order(order.order_id, executed_at="2026-08-01T11:00:00+00:00")
        except ValidationError:
            raised = True
        check(raised, "a second execute_order() call on the same (now FILLED) order raises ValidationError")

        trades = trade_repo.list_by_order(order.order_id)
        check(len(trades) == 1, "still exactly one Trade after the rejected second attempt")


def scenario_missing_order_rejected():
    print("\n[Scenario 5] a non-existent order_id is rejected")
    with tempfile.TemporaryDirectory() as tmp:
        service, order_repo, trade_repo = _build_service(tmp)

        raised = False
        try:
            service.execute_order(999999, executed_at="2026-08-01T10:00:00+00:00")
        except ValidationError:
            raised = True
        check(raised, "execute_order() on a non-existent order_id raises ValidationError")


def scenario_end_to_end_create_order_then_execute_order_chain():
    print("\n[Scenario 7] full OrderLifecycleService.create_order() -> ExecutionService.execute_order() chain")
    with tempfile.TemporaryDirectory() as tmp:
        service, order_repo, trade_repo = _build_service(tmp)
        lifecycle_service = OrderLifecycleService(order_repo)

        order = lifecycle_service.create_order(
            account_id="paper-id",
            symbol="BBCA",
            action="BUY",
            quantity=100.0,
            requested_price=9500.0,
        )
        check(order.status == "PENDING", "setup: create_order() leaves the order PENDING")
        check(order.filled_price == 0.0, "setup: create_order() never populates filled_price")

        trade = service.execute_order(order.order_id, executed_at="2026-08-01T10:00:00+00:00")

        check(
            trade.fill_price == 9500.0,
            "chained through OrderLifecycleService.create_order(), Trade.fill_price "
            "reflects the originally requested price, not the never-populated filled_price",
        )
        check(trade.fill_price != 0.0, "Trade.fill_price is not the 0.0 filled_price placeholder")


def scenario_no_account_or_position_dependency():
    print("\n[Scenario 6] no Account/Position dependency exists on the service")
    with tempfile.TemporaryDirectory() as tmp:
        service, _, _ = _build_service(tmp)
        attrs = sorted(vars(service).keys())
        # Activation 3.3 STEP 2 (explicit contract change): ExecutionService
        # gained one additional collaborator, _execution_policy (the
        # canonical Business.execution_policy_config.ExecutionPolicy it
        # reads fee/tax placeholder values from). No AccountRepository/
        # PositionRepository reference was added -- the property this
        # scenario actually guards (see module docstring) is unchanged.
        check(
            attrs == ["_execution_policy", "_order_repository", "_trade_repository"],
            "ExecutionService holds exactly three collaborators: "
            "_execution_policy, _order_repository, _trade_repository "
            "(no AccountRepository/PositionRepository)",
        )


def main() -> int:
    scenario_pending_to_filled_happy_path()
    scenario_exactly_one_trade_created()
    scenario_non_pending_statuses_rejected()
    scenario_already_filled_order_rejected_idempotency()
    scenario_missing_order_rejected()
    scenario_end_to_end_create_order_then_execute_order_chain()
    scenario_no_account_or_position_dependency()

    print("\n" + "=" * 60)
    print(f"SPRINT 4 STEP 6 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())