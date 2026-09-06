"""Standalone regression checks for
``Business.daily_performance_service.DailyPerformanceService``
(Activation 5.3).

Proves against a real on-disk SQLite file (real ``AccountRepository``/
``PositionRepository``/``TradeRepository``/
``PortfolioSnapshotRepository``/``DailyPerformanceRepository`` + real
migrations, real ``PositionManager`` for BUY/SELL setup, real
``UnrealizedPnLEngine``/``MaximumDrawdownEngine``):

* realized_result sums real Position.realized_pnl across all
  positions (open + closed) for the account;
* unrealized_result is computed from real open positions via the
  real, unmodified UnrealizedPnLEngine formula;
* fees/tax/number_of_executions are summed/counted only over Trade
  rows whose executed_at falls within [start_timestamp, end_timestamp]
  -- trades outside the period are excluded;
* net_result == realized_result + unrealized_result - fees - tax;
* starting_equity/ending_equity are read from the latest
  PortfolioSnapshot at/before each boundary, and are None when no
  qualifying snapshot exists (GAP, not fabricated);
* drawdown is computed via the real MaximumDrawdownEngine over the
  real equity curve within the period;
* number_of_signals is always None (GAP, not fabricated);
* the row is actually persisted (row exists after a real reconnect /
  restart);
* computing daily performance creates no Order and no Trade row
  (read-only / observational);
* an unknown account raises ValidationError with no partial write;
* no scheduler/background execution surface exists on the service;
* no calendar/timezone/trading-day logic exists on the service.

Market price is supplied via the same small, duck-typed test double
(``_FixedPriceTool``) already used by
``Tests/test_portfolio_snapshot_service.py``/
``Tests/activation_3_7_step4_proof.py`` -- the real
``MarketPriceTool`` in production is never modified.

Run directly with ``python Tests/test_daily_performance_service.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.daily_performance_service import DailyPerformanceService  # noqa: E402
from Business.maximum_drawdown_engine import MaximumDrawdownEngine  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Business.unrealized_pnl_engine import UnrealizedPnLEngine  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_daily_performance import DAILY_PERFORMANCE_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.models import DailyPerformance, Trade  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Orchestration.tool_result import ToolResult  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.daily_performance_repository import DailyPerformanceRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.portfolio_snapshot_repository import PortfolioSnapshotRepository  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
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


class _FixedPriceTool:
    """Test double for ``MarketPriceTool`` -- same ``execute(context)``
    contract, fixed price instead of a live network/yfinance call.
    Mirrors ``Tests/test_portfolio_snapshot_service.py``'s own test
    double exactly.
    """

    def __init__(self, price):
        self._price = price

    def execute(self, context):
        symbol = context.parameters.get("symbol")
        return ToolResult(
            success=True,
            output={"symbol": symbol, "price": self._price, "trend": "manual-fixture"},
            error=None,
            metadata={},
        )


def _make_trade(order_repo, trade_repo, symbol="BBCA", account_id="paper-id", action="BUY",
                 quantity=100.0, fill_price=9500.0, fee=0.0, tax=0.0,
                 executed_at="2026-08-05T10:00:00+00:00"):
    """Persist a real Order + Trade row via the real repositories and
    return the resulting ``Trade`` -- mirrors how a real
    ``ExecutionService`` would produce a ``Trade`` for
    ``PositionManager.apply_trade`` to consume, so
    ``TradeRepository.list_by_account`` (which
    ``DailyPerformanceService`` reads) actually sees these trades.
    """
    order = order_repo.create(
        account_id=account_id, symbol=symbol, action=action, quantity=quantity,
        requested_price=fill_price, filled_price=fill_price, status="FILLED",
        reason="test fixture", filled_quantity=quantity,
    )
    return trade_repo.create(
        order_id=order.order_id, account_id=account_id, symbol=symbol, action=action,
        quantity=quantity, fill_price=fill_price, fee=fee, tax=tax, executed_at=executed_at,
    )


def _build(tmp_dir: str, db_name: str, price: float, account_id: str = "paper-id"):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / db_name)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
    MigrationRunner(db).apply(DAILY_PERFORMANCE_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    account_repo = AccountRepository(manager)
    account_repo.create(
        account_id=account_id, account_name="Paper Indonesia", mode="paper",
        currency="IDR", asset_class="stock_id",
        cash=100_000_000.0, equity=100_000_000.0, buying_power=100_000_000.0,
    )
    position_repo = PositionRepository(manager)
    position_manager = PositionManager(position_repo)
    order_repo = OrderRepository(manager)
    trade_repo = TradeRepository(manager)
    snapshot_repo = PortfolioSnapshotRepository(manager)
    daily_performance_repo = DailyPerformanceRepository(manager)

    service = DailyPerformanceService(
        account_repository=account_repo,
        position_repository=position_repo,
        trade_repository=trade_repo,
        portfolio_snapshot_repository=snapshot_repo,
        unrealized_pnl_engine=UnrealizedPnLEngine(_FixedPriceTool(price)),
        maximum_drawdown_engine=MaximumDrawdownEngine(),
        daily_performance_repository=daily_performance_repo,
    )
    return (db, cfg, manager, account_repo, position_repo, position_manager,
            order_repo, trade_repo, snapshot_repo, daily_performance_repo, service)


def scenario_no_activity_period():
    print("\n[Scenario 1] Account with no positions/trades/snapshots: all-zero, no fabrication")
    with tempfile.TemporaryDirectory() as tmp:
        db, *_rest, service = _build(tmp, "dp_svc_empty.db", price=10_000.0)
        try:
            row = service.compute_daily_performance(
                "paper-id", "2026-08-11T00:00:00+00:00", "2026-08-11T23:59:59+00:00"
            )
            check(isinstance(row, DailyPerformance), "compute_daily_performance() returns a DailyPerformance")
            check(row.realized_result == 0.0, "realized_result is 0.0 with no positions at all")
            check(row.unrealized_result == 0.0, "unrealized_result is 0.0 with no open positions")
            check(row.fees == 0.0, "fees is 0.0 with no trades in period")
            check(row.tax == 0.0, "tax is 0.0 with no trades in period")
            check(row.net_result == 0.0, "net_result is 0.0 when every component is 0.0")
            check(row.number_of_executions == 0, "number_of_executions is 0 with no trades in period")
            check(row.starting_equity is None, "starting_equity is None -- no qualifying snapshot (GAP, not fabricated)")
            check(row.ending_equity is None, "ending_equity is None -- no qualifying snapshot (GAP, not fabricated)")
            check(row.number_of_signals is None, "number_of_signals is None -- no Signal entity exists (GAP)")
            check(row.drawdown == 0.0, "drawdown is 0.0 with no snapshots in period")
            check(bool(row.timestamp), "timestamp is populated")
        finally:
            db.disconnect()


def scenario_realized_and_unrealized_result():
    print("\n[Scenario 2] BUY then partial SELL: realized_result/unrealized_result reflect real state")
    with tempfile.TemporaryDirectory() as tmp:
        db, cfg, manager, account_repo, position_repo, position_manager, order_repo, trade_repo, snap_repo, dp_repo, service = _build(
            tmp, "dp_svc_realized.db", price=9_900.0
        )
        try:
            position_manager.apply_trade(_make_trade(order_repo, trade_repo, action="BUY", quantity=100.0, fill_price=9500.0))
            position_manager.apply_trade(_make_trade(
                order_repo, trade_repo, action="SELL", quantity=40.0, fill_price=9700.0,
                executed_at="2026-08-05T11:00:00+00:00",
            ))

            position = position_repo.get_open_position("paper-id", "BBCA")
            expected_realized = (9700.0 - 9500.0) * 40.0
            check(position.realized_pnl == expected_realized, "sanity: Position.realized_pnl matches PositionManager's own formula")

            row = service.compute_daily_performance(
                "paper-id", "2026-08-01T00:00:00+00:00", "2026-08-31T23:59:59+00:00"
            )
            check(row.realized_result == expected_realized, f"realized_result == real Position.realized_pnl (got {row.realized_result})")

            remaining_qty = 60.0
            expected_unrealized = (9900.0 - 9500.0) * remaining_qty
            check(row.unrealized_result == expected_unrealized, "unrealized_result reflects the remaining open quantity only")
        finally:
            db.disconnect()


def scenario_fees_tax_filtered_to_period():
    print("\n[Scenario 3] fees/tax/number_of_executions only count Trades inside the period")
    with tempfile.TemporaryDirectory() as tmp:
        db, cfg, manager, account_repo, position_repo, position_manager, order_repo, trade_repo, snap_repo, dp_repo, service = _build(
            tmp, "dp_svc_period.db", price=9_500.0
        )
        try:
            # Inside the period
            position_manager.apply_trade(_make_trade(
                order_repo, trade_repo, action="BUY", quantity=10.0, fill_price=9500.0, fee=100.0, tax=50.0,
                executed_at="2026-08-11T09:00:00+00:00",
            ))
            position_manager.apply_trade(_make_trade(
                order_repo, trade_repo, action="BUY", quantity=10.0, fill_price=9500.0, fee=200.0, tax=75.0,
                executed_at="2026-08-11T15:00:00+00:00",
            ))
            # Outside the period (before)
            position_manager.apply_trade(_make_trade(
                order_repo, trade_repo, action="BUY", quantity=10.0, fill_price=9500.0, fee=999.0, tax=999.0,
                executed_at="2026-08-10T23:59:58+00:00",
            ))
            # Outside the period (after)
            position_manager.apply_trade(_make_trade(
                order_repo, trade_repo, action="BUY", quantity=10.0, fill_price=9500.0, fee=999.0, tax=999.0,
                executed_at="2026-08-12T00:00:01+00:00",
            ))

            row = service.compute_daily_performance(
                "paper-id", "2026-08-11T00:00:00+00:00", "2026-08-11T23:59:59+00:00"
            )
            check(row.fees == 300.0, f"fees sums only in-period trades (got {row.fees})")
            check(row.tax == 125.0, f"tax sums only in-period trades (got {row.tax})")
            check(row.number_of_executions == 2, f"number_of_executions counts only in-period trades (got {row.number_of_executions})")
        finally:
            db.disconnect()


def scenario_net_result_derivation():
    print("\n[Scenario 4] net_result == realized_result + unrealized_result - fees - tax")
    with tempfile.TemporaryDirectory() as tmp:
        db, cfg, manager, account_repo, position_repo, position_manager, order_repo, trade_repo, snap_repo, dp_repo, service = _build(
            tmp, "dp_svc_net.db", price=9_800.0
        )
        try:
            position_manager.apply_trade(_make_trade(
                order_repo, trade_repo, action="BUY", quantity=50.0, fill_price=9500.0, fee=100.0, tax=50.0,
                executed_at="2026-08-11T09:00:00+00:00",
            ))
            row = service.compute_daily_performance(
                "paper-id", "2026-08-11T00:00:00+00:00", "2026-08-11T23:59:59+00:00"
            )
            expected_net = row.realized_result + row.unrealized_result - row.fees - row.tax
            check(row.net_result == expected_net, f"net_result matches independent derivation (got {row.net_result}, expected {expected_net})")
        finally:
            db.disconnect()


def scenario_starting_ending_equity_and_drawdown():
    print("\n[Scenario 5] starting_equity/ending_equity/drawdown sourced from real PortfolioSnapshot history")
    with tempfile.TemporaryDirectory() as tmp:
        db, cfg, manager, account_repo, position_repo, position_manager, order_repo, trade_repo, snap_repo, dp_repo, service = _build(
            tmp, "dp_svc_equity.db", price=9_500.0
        )
        try:
            snap_repo.create(
                account_id="paper-id", cash=100_000_000.0, market_value=0.0, equity=100_000_000.0,
                realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                timestamp="2026-08-10T23:00:00+00:00",
            )
            snap_repo.create(
                account_id="paper-id", cash=99_000_000.0, market_value=1_200_000.0, equity=100_200_000.0,
                realized_pnl=0.0, unrealized_pnl=200_000.0, drawdown=0.0,
                timestamp="2026-08-11T12:00:00+00:00",
            )
            snap_repo.create(
                account_id="paper-id", cash=99_000_000.0, market_value=900_000.0, equity=99_900_000.0,
                realized_pnl=0.0, unrealized_pnl=-100_000.0, drawdown=0.003,
                timestamp="2026-08-11T18:00:00+00:00",
            )
            # After the period -- must not affect ending_equity/drawdown
            snap_repo.create(
                account_id="paper-id", cash=99_000_000.0, market_value=2_000_000.0, equity=101_000_000.0,
                realized_pnl=0.0, unrealized_pnl=1_000_000.0, drawdown=0.0,
                timestamp="2026-08-12T09:00:00+00:00",
            )

            row = service.compute_daily_performance(
                "paper-id", "2026-08-11T00:00:00+00:00", "2026-08-11T23:59:59+00:00"
            )
            check(row.starting_equity == 100_000_000.0, f"starting_equity == latest snapshot at/before start (got {row.starting_equity})")
            check(row.ending_equity == 99_900_000.0, f"ending_equity == latest snapshot at/before end (got {row.ending_equity})")

            independent_curve = [100_200_000.0, 99_900_000.0]
            independent = MaximumDrawdownEngine().calculate(independent_curve)
            check(row.drawdown == independent.maximum_drawdown, f"drawdown matches an independent MaximumDrawdownEngine computation over in-period equity (got {row.drawdown}, expected {independent.maximum_drawdown})")
        finally:
            db.disconnect()


def scenario_persisted_and_readable_after_restart():
    print("\n[Scenario 6] row is persisted and readable after a real reconnect")
    with tempfile.TemporaryDirectory() as tmp:
        db_name = "dp_svc_restart.db"
        db, cfg, manager, account_repo, position_repo, position_manager, order_repo, trade_repo, snap_repo, dp_repo, service = _build(
            tmp, db_name, price=9_500.0
        )
        row = service.compute_daily_performance(
            "paper-id", "2026-08-11T00:00:00+00:00", "2026-08-11T23:59:59+00:00"
        )
        db.disconnect()

        db2 = SQLiteDatabase(DatabaseConfig(db_path=cfg.db_path))
        db2.connect()
        try:
            manager2 = DatabaseManager(db2, cfg)
            repo2 = DailyPerformanceRepository(manager2)
            reread = repo2.get_by_id(row.daily_performance_id)
            check(reread is not None, "row exists after process restart / fresh connection")
            check(reread.net_result == row.net_result, "net_result survives restart")
            check(reread.timestamp == row.timestamp, "timestamp survives restart")
        finally:
            db2.disconnect()


def scenario_read_only_creates_no_order_or_trade():
    print("\n[Scenario 7] compute_daily_performance() creates no Order and no Trade (read-only/observational)")
    with tempfile.TemporaryDirectory() as tmp:
        db, cfg, manager, account_repo, position_repo, position_manager, order_repo, trade_repo, snap_repo, dp_repo, service = _build(
            tmp, "dp_svc_readonly.db", price=9_500.0
        )
        try:
            position_manager.apply_trade(_make_trade(order_repo, trade_repo, action="BUY", quantity=100.0, fill_price=9500.0))

            orders_before = len(order_repo.list_all())
            trades_before = len(trade_repo.list_all())

            service.compute_daily_performance("paper-id", "2026-08-01T00:00:00+00:00", "2026-08-31T23:59:59+00:00")
            service.compute_daily_performance("paper-id", "2026-08-01T00:00:00+00:00", "2026-08-31T23:59:59+00:00")

            orders_after = len(order_repo.list_all())
            trades_after = len(trade_repo.list_all())

            check(orders_after == orders_before, f"no Order rows created (before={orders_before}, after={orders_after})")
            check(trades_after == trades_before, f"no Trade rows created (before={trades_before}, after={trades_after})")

            rows = dp_repo.list_by_account("paper-id")
            check(len(rows) == 2, "two daily_performance rows were persisted (append-only, one per call)")
        finally:
            db.disconnect()


def scenario_unknown_account_raises():
    print("\n[Scenario 8] Unknown account raises ValidationError, no partial write")
    with tempfile.TemporaryDirectory() as tmp:
        db, cfg, manager, account_repo, position_repo, position_manager, order_repo, trade_repo, snap_repo, dp_repo, service = _build(
            tmp, "dp_svc_unknown.db", price=9_500.0
        )
        try:
            raised = False
            try:
                service.compute_daily_performance("does-not-exist", "2026-08-11T00:00:00+00:00", "2026-08-11T23:59:59+00:00")
            except ValidationError:
                raised = True
            check(raised, "compute_daily_performance() raises ValidationError for an unknown account_id")
            check(dp_repo.list_all() == [], "no daily_performance row was persisted for the failed attempt")
        finally:
            db.disconnect()


def scenario_no_scheduler_or_background_execution():
    print("\n[Scenario 9] No scheduler/daemon/background surface exists on the service")
    forbidden_substrings = ("schedule", "daemon", "background", "loop_forever", "cron")
    import inspect
    source = inspect.getsource(DailyPerformanceService)
    for token in forbidden_substrings:
        check(token not in source.lower(), f"DailyPerformanceService source contains no '{token}' concept")


def scenario_no_calendar_or_timezone_logic():
    print("\n[Scenario 10] No calendar/timezone/trading-day logic exists on the service")
    forbidden_substrings = ("midnight", "trading_day", "tzinfo", "zoneinfo", "pytz", "calendar")
    import inspect
    source = inspect.getsource(DailyPerformanceService)
    # Only inspect executable code, not the module/class docstrings, which
    # legitimately discuss (and disclaim) these concepts in prose.
    import ast
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc and node.body and isinstance(node.body[0], ast.Expr):
                node.body = node.body[1:]
    executable_source = ast.unparse(tree) if hasattr(ast, "unparse") else source
    for token in forbidden_substrings:
        check(token not in executable_source.lower(), f"DailyPerformanceService executable code contains no '{token}' concept")


def main() -> int:
    scenario_no_activity_period()
    scenario_realized_and_unrealized_result()
    scenario_fees_tax_filtered_to_period()
    scenario_net_result_derivation()
    scenario_starting_ending_equity_and_drawdown()
    scenario_persisted_and_readable_after_restart()
    scenario_read_only_creates_no_order_or_trade()
    scenario_unknown_account_raises()
    scenario_no_scheduler_or_background_execution()
    scenario_no_calendar_or_timezone_logic()

    print(f"\n{'=' * 60}")
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print("=" * 60)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
