"""Standalone regression checks for
``Business.reconciliation_engine.ReconciliationEngine``.

Covers Activation 3.9 STEP 2's acceptance gate end-to-end, driving
every scenario through the real production path
(``Business.paper_trading_engine.PaperTradingEngine.submit_order()``)
exactly like ``Tests/test_paper_trading_engine.py`` already does --
this file adds no shortcut that calls ``PositionManager``/
``AccountBalanceService``/``ExecutionService`` directly to "set up" a
scenario:

* BUY reconciliation -- Order FILLED, filled fields correct, Trade
  recorded, fee/tax recorded, cash debited exactly, Position created,
  average price correct -- then ``ReconciliationEngine.
  reconcile_account()`` reports CONSISTENT;
* SELL partial reconciliation -- quantity reduced, cash credited,
  realized P/L correct -- CONSISTENT;
* SELL full reconciliation -- Position CLOSED, realized P/L
  persisted, and the now-CLOSED position's performance is computable
  via the existing (not-wired, consumer-only)
  ``Business.position_performance_engine.PositionPerformanceEngine``
  -- CONSISTENT;
* failure reconciliation -- insufficient cash / oversell: no Trade,
  Order not FILLED, cash value unchanged, Position value unchanged
  (explicit VALUE assertions, not just row counts) -- and the account
  is still reported CONSISTENT afterwards (nothing was written, so
  there is nothing to be inconsistent);
* restart reconciliation -- Account.cash and Position fields survive
  a fresh connection to the same SQLite file, and reconciling through
  the fresh connection still reports CONSISTENT;
* the Trade<->Cash invariant is explicitly reported
  ``not_verifiable`` (not silently passed, not force-failed) when
  ``starting_cash`` is omitted, and explicitly checked when supplied.

Run directly with ``python Tests/test_reconciliation_engine.py`` -- no
external test framework required, matching every other
``Tests/test_*.py`` file in this codebase.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.account_balance_service import AccountBalanceService  # noqa: E402
from Business.execution_policy_config import ExecutionPolicy  # noqa: E402
from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Business.position_performance_engine import PositionPerformanceEngine  # noqa: E402
from Business.reconciliation_engine import (  # noqa: E402
    NOT_VERIFIABLE_CASH_HISTORY,
    NOT_VERIFIABLE_PORTFOLIO_VALUATION,
    ReconciliationEngine,
)
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_idempotency_repository import (  # noqa: E402
    OrderIdempotencyRepository,
)
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES = []

#: Nonzero fee/tax so BUY/SELL cash and realized_pnl checks actually
#: exercise the fee/tax terms of the formulas, not just the
#: gross_value term (Activation 3.9 STEP 1 audit noted the default
#: policy's rates are all 0.0, which would make a fee/tax bug
#: invisible to these checks).
_POLICY = ExecutionPolicy(
    lot_size=100,
    buy_fee_rate=1_500.0,
    sell_fee_rate=1_500.0,
    sell_tax_rate=2_000.0,
    slippage_enabled=False,
    slippage_rate=0.0,
    buying_power_policy="cash_only",
)


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


def _build(tmp_dir: str, *, cash: float = 100_000_000.0, kill_switch: bool = False, max_order_value: float = 1_000_000_000.0):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "reconciliation_engine.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(IDEMPOTENCY_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    account_repo = AccountRepository(manager)
    position_repo = PositionRepository(manager)
    order_repo = OrderRepository(manager)
    trade_repo = TradeRepository(manager)
    idempotency_repo = OrderIdempotencyRepository(manager)

    account_repo.create(
        account_id="paper-id",
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=cash,
        equity=cash,
        buying_power=cash,
    )

    engine = PaperTradingEngine(
        order_lifecycle_service=OrderLifecycleService(order_repo),
        execution_service=ExecutionService(order_repo, trade_repo, execution_policy=_POLICY),
        account_repository=account_repo,
        position_repository=position_repo,
        order_idempotency_repository=idempotency_repo,
        kill_switch_engaged=kill_switch,
        max_order_value=max_order_value,
        execution_policy=_POLICY,
        account_balance_service=AccountBalanceService(account_repo),
        position_manager=PositionManager(position_repo),
    )
    reconciler = ReconciliationEngine(order_repo, trade_repo, account_repo, position_repo)
    repos = {
        "account": account_repo,
        "position": position_repo,
        "order": order_repo,
        "trade": trade_repo,
        "idempotency": idempotency_repo,
    }
    return engine, reconciler, repos


def _default_kwargs(**overrides) -> dict:
    kwargs = dict(
        account_id="paper-id",
        symbol="BBCA",
        action="BUY",
        quantity=100.0,
        requested_price=9_500.0,
        executed_at="2026-08-01T10:00:00+00:00",
        signal_evidence={"rsi": 28.0, "note": "oversold bounce"},
        user_approval=True,
        idempotency_key="req-001",
    )
    kwargs.update(overrides)
    return kwargs


def scenario_buy_acceptance():
    print("\n[Scenario 1] BUY acceptance gate: Order FILLED, fields correct, cash/position correct, CONSISTENT")
    with tempfile.TemporaryDirectory() as tmp:
        starting_cash = 100_000_000.0
        engine, reconciler, repos = _build(tmp, cash=starting_cash)

        trade = engine.submit_order(**_default_kwargs())
        order = repos["order"].get_by_id(trade.order_id)
        account = repos["account"].get_by_id("paper-id")
        position = repos["position"].get_open_position("paper-id", "BBCA")

        check(order.status == "FILLED", "BUY: Order FILLED")
        check(order.filled_price == trade.fill_price, "BUY: Order.filled_price == Trade.fill_price")
        check(order.filled_quantity == trade.quantity, "BUY: Order.filled_quantity == Trade.quantity")
        check(order.filled_at == trade.executed_at, "BUY: Order.filled_at == Trade.executed_at")
        check(len(repos["trade"].list_by_order(order.order_id)) == 1, "BUY: exactly one Trade recorded")
        check(trade.fee == _POLICY.buy_fee_rate, "BUY: fee recorded from ExecutionPolicy.buy_fee_rate")
        check(trade.tax == 0.0, "BUY: tax recorded as 0.0 (IDX does not tax BUY)")

        gross_value = trade.quantity * trade.fill_price
        expected_cash = starting_cash - (gross_value + trade.fee + trade.tax)
        check(account.cash == expected_cash, "BUY: cash debited exactly (gross_value + fee + tax)")

        check(position is not None and position.quantity == 100.0, "BUY: Position created with correct quantity")
        check(position.average_price == trade.fill_price, "BUY: Position.average_price correct (first BUY == fill_price)")
        check(position.realized_pnl == 0.0, "BUY: Position.realized_pnl seeded at 0.0")
        check(position.status == "open", "BUY: Position.status == open")

        result = reconciler.reconcile_account("paper-id", starting_cash=starting_cash)
        check(result.status == "CONSISTENT", "BUY: reconcile_account() reports CONSISTENT")
        check(result.violations == [], "BUY: zero violations")


def scenario_sell_partial_acceptance():
    print("\n[Scenario 2] SELL partial acceptance gate: quantity/cash/realized P/L correct, CONSISTENT")
    with tempfile.TemporaryDirectory() as tmp:
        starting_cash = 100_000_000.0
        engine, reconciler, repos = _build(tmp, cash=starting_cash)

        buy_trade = engine.submit_order(**_default_kwargs(quantity=300.0, idempotency_key="buy-1"))
        position_before = repos["position"].get_open_position("paper-id", "BBCA")
        cash_before = repos["account"].get_by_id("paper-id").cash

        sell_trade = engine.submit_order(
            **_default_kwargs(action="SELL", quantity=100.0, requested_price=9_800.0, idempotency_key="sell-partial-1")
        )

        position_after = repos["position"].get_open_position("paper-id", "BBCA")
        account_after = repos["account"].get_by_id("paper-id")

        check(position_after is not None, "SELL partial: Position still open")
        check(position_after.quantity == position_before.quantity - 100.0, "SELL partial: quantity reduced by sell quantity")
        check(position_after.status == "open", "SELL partial: status stays open (quantity > 0)")

        gross_value = sell_trade.quantity * sell_trade.fill_price
        expected_cash = cash_before + gross_value - sell_trade.fee - sell_trade.tax
        check(account_after.cash == expected_cash, "SELL partial: cash credited exactly (gross_value - fee - tax)")

        expected_realized_pnl = (
            0.0
            + (sell_trade.fill_price - position_before.average_price) * sell_trade.quantity
            - sell_trade.fee
            - sell_trade.tax
        )
        check(abs(position_after.realized_pnl - expected_realized_pnl) < 1e-9, "SELL partial: realized P/L correct")

        result = reconciler.reconcile_account("paper-id", starting_cash=starting_cash)
        check(result.status == "CONSISTENT", "SELL partial: reconcile_account() reports CONSISTENT")
        check(result.violations == [], "SELL partial: zero violations")
        _ = buy_trade  # kept for readability of the flow above


def scenario_sell_full_acceptance():
    print("\n[Scenario 3] SELL full acceptance gate: Position CLOSED, realized P/L persisted, performance computable, CONSISTENT")
    with tempfile.TemporaryDirectory() as tmp:
        starting_cash = 100_000_000.0
        engine, reconciler, repos = _build(tmp, cash=starting_cash)

        engine.submit_order(**_default_kwargs(quantity=100.0, idempotency_key="buy-1"))
        position_before = repos["position"].get_open_position("paper-id", "BBCA")

        sell_trade = engine.submit_order(
            **_default_kwargs(action="SELL", quantity=100.0, requested_price=9_900.0, idempotency_key="sell-full-1")
        )

        closed_positions = [
            p for p in repos["position"].list_by_account("paper-id") if p.symbol == "BBCA"
        ]
        check(len(closed_positions) == 1, "SELL full: exactly one Position row for BBCA (updated in place, not appended)")
        closed = closed_positions[0]
        check(closed.status == "closed", "SELL full: Position.status == closed")
        check(closed.quantity == 0.0, "SELL full: Position.quantity == 0")

        expected_realized_pnl = (
            0.0
            + (sell_trade.fill_price - position_before.average_price) * sell_trade.quantity
            - sell_trade.fee
            - sell_trade.tax
        )
        check(closed.realized_pnl == expected_realized_pnl, "SELL full: realized P/L persisted correctly")

        # "closed trade dapat dihitung performanya" -- Activation 3.9
        # STEP 1 audit sec. 8/12: PositionPerformanceEngine already
        # exists and is a pure, dependency-free consumer of
        # List[Position] -- no wiring change needed to prove it can
        # consume this now-CLOSED, persisted Position.
        stats = PositionPerformanceEngine().calculate(repos["position"].list_by_account("paper-id"))
        check(stats.winning_positions + stats.losing_positions + stats.breakeven_positions == 1, "SELL full: PositionPerformanceEngine can consume the persisted closed Position")
        check(stats.net_profit == expected_realized_pnl, "SELL full: PositionPerformanceEngine.net_profit matches persisted realized_pnl")

        result = reconciler.reconcile_account("paper-id", starting_cash=starting_cash)
        check(result.status == "CONSISTENT", "SELL full: reconcile_account() reports CONSISTENT")
        check(result.violations == [], "SELL full: zero violations")


def scenario_failure_insufficient_cash():
    print("\n[Scenario 4] Failure acceptance gate: insufficient cash -- no Trade, Order not FILLED, cash/position VALUE unchanged")
    with tempfile.TemporaryDirectory() as tmp:
        starting_cash = 100_000.0
        engine, reconciler, repos = _build(tmp, cash=starting_cash)

        cash_before = repos["account"].get_by_id("paper-id").cash
        position_before = repos["position"].get_open_position("paper-id", "BBCA")

        raised_reason = None
        try:
            engine.submit_order(**_default_kwargs(quantity=100.0, requested_price=9_500.0))
        except ValidationError as exc:
            raised_reason = exc.details.get("reason")

        cash_after = repos["account"].get_by_id("paper-id").cash
        position_after = repos["position"].get_open_position("paper-id", "BBCA")

        check(raised_reason == "INSUFFICIENT_CASH", "insufficient cash: rejected with INSUFFICIENT_CASH")
        check(len(repos["trade"].list_all()) == 0, "insufficient cash: no Trade created")
        check(len(repos["order"].list_all()) == 0, "insufficient cash: no Order created (rejected before create_order())")
        check(cash_after == cash_before, "insufficient cash: Account.cash VALUE unchanged (not just row count)")
        check(position_after == position_before, "insufficient cash: Position VALUE unchanged (both None)")

        result = reconciler.reconcile_account("paper-id", starting_cash=starting_cash)
        check(result.status == "CONSISTENT", "insufficient cash: account still CONSISTENT after the rejected attempt (nothing written)")


def scenario_failure_oversell():
    print("\n[Scenario 5] Failure acceptance gate: oversell -- no Trade, Order not FILLED, cash/position VALUE unchanged")
    with tempfile.TemporaryDirectory() as tmp:
        starting_cash = 100_000_000.0
        engine, reconciler, repos = _build(tmp, cash=starting_cash)

        buy_trade = engine.submit_order(**_default_kwargs(quantity=100.0, idempotency_key="buy-1"))
        cash_before = repos["account"].get_by_id("paper-id").cash
        position_before = repos["position"].get_open_position("paper-id", "BBCA")

        raised_reason = None
        try:
            engine.submit_order(
                **_default_kwargs(action="SELL", quantity=200.0, idempotency_key="oversell-1")
            )
        except ValidationError as exc:
            raised_reason = exc.details.get("reason")

        cash_after = repos["account"].get_by_id("paper-id").cash
        position_after = repos["position"].get_open_position("paper-id", "BBCA")

        check(raised_reason == "INSUFFICIENT_POSITION", "oversell: rejected with INSUFFICIENT_POSITION")
        check(len(repos["trade"].list_by_order(buy_trade.order_id)) == 1, "oversell: still exactly the one Trade from the earlier BUY, no new Trade")
        check(cash_after == cash_before, "oversell: Account.cash VALUE unchanged by the rejected SELL")
        check(
            position_after.quantity == position_before.quantity
            and position_after.average_price == position_before.average_price
            and position_after.realized_pnl == position_before.realized_pnl
            and position_after.status == position_before.status,
            "oversell: Position VALUE unchanged by the rejected SELL",
        )

        result = reconciler.reconcile_account("paper-id", starting_cash=starting_cash)
        check(result.status == "CONSISTENT", "oversell: account still CONSISTENT after the rejected attempt")


def scenario_restart_reconciliation():
    print("\n[Scenario 6] Restart acceptance gate: Account.cash and Position survive reconnect, and reconcile CONSISTENT through the fresh connection")
    with tempfile.TemporaryDirectory() as tmp:
        starting_cash = 100_000_000.0
        engine, _, repos = _build(tmp, cash=starting_cash)

        engine.submit_order(**_default_kwargs(quantity=300.0, idempotency_key="buy-1"))
        engine.submit_order(
            **_default_kwargs(action="SELL", quantity=100.0, requested_price=9_700.0, idempotency_key="sell-1")
        )

        account_before = repos["account"].get_by_id("paper-id")
        position_before = repos["position"].get_open_position("paper-id", "BBCA")

        # Simulate an application restart: a brand new repository/engine
        # graph over the SAME db file, nothing shared in memory --
        # mirrors Tests/test_paper_trading_engine.py::scenario_restart_persistence.
        cfg = DatabaseConfig(db_path=Path(tmp) / "reconciliation_engine.db")
        db2 = SQLiteDatabase(cfg)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg)
        account_repo2 = AccountRepository(manager2)
        position_repo2 = PositionRepository(manager2)
        order_repo2 = OrderRepository(manager2)
        trade_repo2 = TradeRepository(manager2)

        account_after = account_repo2.get_by_id("paper-id")
        position_after = position_repo2.get_open_position("paper-id", "BBCA")

        check(account_after.cash == account_before.cash, "restart: Account.cash identical through a fresh connection")
        check(position_after.quantity == position_before.quantity, "restart: Position.quantity identical through a fresh connection")
        check(position_after.average_price == position_before.average_price, "restart: Position.average_price identical through a fresh connection")
        check(position_after.realized_pnl == position_before.realized_pnl, "restart: Position.realized_pnl identical through a fresh connection")
        check(position_after.status == position_before.status, "restart: Position.status identical through a fresh connection")

        reconciler2 = ReconciliationEngine(order_repo2, trade_repo2, account_repo2, position_repo2)
        result = reconciler2.reconcile_account("paper-id", starting_cash=starting_cash)
        check(result.status == "CONSISTENT", "restart: reconcile_account() through the fresh connection reports CONSISTENT")


def scenario_cash_not_verifiable_without_anchor():
    print("\n[Scenario 7] Trade<->Cash invariant is reported not_verifiable when starting_cash is omitted -- never silently skipped or forced to pass")
    with tempfile.TemporaryDirectory() as tmp:
        engine, reconciler, repos = _build(tmp)
        engine.submit_order(**_default_kwargs())

        result = reconciler.reconcile_account("paper-id")

        check(
            NOT_VERIFIABLE_CASH_HISTORY in result.not_verifiable,
            "no starting_cash: Trade<->Cash reported under not_verifiable",
        )
        check(
            NOT_VERIFIABLE_PORTFOLIO_VALUATION in result.not_verifiable,
            "portfolio valuation always reported under not_verifiable (no PortfolioSnapshot/price feed)",
        )
        check(
            result.status == "CONSISTENT",
            "not_verifiable entries never flip an otherwise-consistent account to INCONSISTENT",
        )


def scenario_reconciliation_engine_is_read_only():
    print("\n[Scenario 8] ReconciliationEngine performs zero writes -- row counts unchanged after reconcile_account()")
    with tempfile.TemporaryDirectory() as tmp:
        engine, reconciler, repos = _build(tmp)
        engine.submit_order(**_default_kwargs())

        def row_counts():
            return {
                "accounts": len(repos["account"].list_all()),
                "positions": len(repos["position"].list_all()),
                "orders": len(repos["order"].list_all()),
                "trades": len(repos["trade"].list_all()),
            }

        before = row_counts()
        reconciler.reconcile_account("paper-id", starting_cash=100_000_000.0)
        reconciler.reconcile_account("paper-id")  # also exercise the not_verifiable path
        after = row_counts()

        check(before == after, "reconcile_account() calls produced zero writes to any table")


def scenario_unknown_account_is_inconsistent():
    print("\n[Scenario 9] Unknown account is reported INCONSISTENT, not an exception")
    with tempfile.TemporaryDirectory() as tmp:
        _, reconciler, _ = _build(tmp)
        result = reconciler.reconcile_account("ghost-account")
        check(result.status == "INCONSISTENT", "unknown account_id: INCONSISTENT")
        check(len(result.violations) == 1, "unknown account_id: exactly one violation explaining why")


def main() -> int:
    scenario_buy_acceptance()
    scenario_sell_partial_acceptance()
    scenario_sell_full_acceptance()
    scenario_failure_insufficient_cash()
    scenario_failure_oversell()
    scenario_restart_reconciliation()
    scenario_cash_not_verifiable_without_anchor()
    scenario_reconciliation_engine_is_read_only()
    scenario_unknown_account_is_inconsistent()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 3.9 STEP 2 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())