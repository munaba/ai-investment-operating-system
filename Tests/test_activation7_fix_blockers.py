"""Standalone regression checks for Activation 7 FIX (the 3 Live
Readiness Gate blockers fixed after the Activation 7 audit):

    1. ``PaperTradingEngine.submit_order()`` no longer silently
       swallows an ``ORDER_EXECUTED`` notification failure
       (``Business/paper_trading_engine.py``).
    2. ``PortfolioSnapshotService.take_snapshot()`` is now wired into
       an existing production flow -- the ``paper buy``/``paper
       sell`` CLI commands, via the new
       ``main._run_post_trade_snapshot_and_reconciliation()`` helper.
    3. ``ReconciliationEngine`` (formula unchanged) is now
       constructed in ``Core.composition_root`` and invoked from that
       same helper; an INCONSISTENT result surfaces as a visible
       failure (non-zero return + printed error + logged error).

Every scenario below drives the REAL ``PaperTradingEngine.
submit_order()``, the REAL ``PortfolioSnapshotService.
take_snapshot()``, the REAL ``ReconciliationEngine.
reconcile_account()``, and the REAL ``main.
_run_post_trade_snapshot_and_reconciliation()`` against a real
on-disk SQLite database -- no mocked business logic, no formula
reimplemented here. Only the market-price source (a fixed-price test
double for ``MarketPriceTool``, the same pattern already used by
``Tests/test_portfolio_snapshot_service.py``) and the notification
channel (a small ``send()`` double) are fakes -- both are I/O
boundaries the codebase already fakes in its own existing tests.

Proves, concretely:

* Scenario 1/2: a failing notification channel no longer raises an
  unhandled exception out of ``submit_order()``, the trade is still
  returned and still fully committed (Order/Trade/Account/Position/
  idempotency-key rows all correct), and the failure is actually
  logged (captured via a handler attached to the real
  ``Business.paper_trading_engine`` logger) -- not silent.
* Scenario 3: a working channel still receives the event (no
  regression to the happy path).
* Scenario 4: calling the real CLI-level helper after a real trade
  persists a real ``PortfolioSnapshot`` row whose fields are derived
  from the actual persisted ``Account``/``Position`` state and the
  real (fixed-price-double) market price -- never a fabricated
  default.
* Scenario 5: the same call, on a genuinely consistent account,
  reports CONSISTENT and returns 0 -- no false failure.
* Scenario 6: after directly corrupting a real ``orders`` row via raw
  SQL (simulating the exact kind of partial-write corruption
  ``ReconciliationEngine`` exists to catch), the same call detects
  INCONSISTENT, prints a labelled "RECONCILIATION FAILURE" message,
  logs an error, and returns a non-zero status -- a real violation is
  actually surfaced, not just a happy path re-confirmed.
* Scenario 7: that same corrupted-state check does not itself mutate
  or "fix" any trading row -- ``ReconciliationEngine`` stays
  read-only, and no state is further damaged by running it.

Run directly with ``python Tests/test_activation7_fix_blockers.py``
-- no external test framework required, matching every other
standalone test file in this repository.
"""

from __future__ import annotations

import io
import logging
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import main  # noqa: E402
from Business.account_balance_service import AccountBalanceService  # noqa: E402
from Business.execution_service import ExecutionService  # noqa: E402
from Business.maximum_drawdown_engine import MaximumDrawdownEngine  # noqa: E402
from Business.notification_builder import NotificationBuilder  # noqa: E402
from Business.notification_dispatcher import NotificationDispatcher  # noqa: E402
from Business.notification_manager import NotificationManager  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Business.portfolio_snapshot_service import PortfolioSnapshotService  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Business.reconciliation_engine import ReconciliationEngine  # noqa: E402
from Business.unrealized_pnl_engine import UnrealizedPnLEngine  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Orchestration.tool_result import ToolResult  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_idempotency_repository import (  # noqa: E402
    OrderIdempotencyRepository,
)
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.portfolio_snapshot_repository import (  # noqa: E402
    PortfolioSnapshotRepository,
)
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


# ---------------------------------------------------------------------------
# Test doubles for I/O boundaries only (never business logic)
# ---------------------------------------------------------------------------


class _FixedPriceTool:
    """Same test double as ``Tests/test_portfolio_snapshot_service.py`` --
    ``MarketPriceTool``'s real ``execute(context)`` contract, fixed
    price instead of a live network call.
    """

    def __init__(self, price: float) -> None:
        self._price = price

    def execute(self, context):
        symbol = context.parameters.get("symbol")
        return ToolResult(
            success=True,
            output={"symbol": symbol, "price": self._price, "trend": "manual-fixture"},
            error=None,
            metadata={},
        )


class _RaisingChannel:
    """Notification channel double that always fails on send() --
    exercises blocker 1's failure path."""

    def __init__(self) -> None:
        self.attempts = 0

    def send(self, event) -> None:
        self.attempts += 1
        raise RuntimeError("simulated Telegram outage")


class _RecordingChannel:
    """Notification channel double that always succeeds -- proves the
    happy path is unaffected by the blocker 1 fix."""

    def __init__(self) -> None:
        self.sent = []

    def send(self, event) -> None:
        self.sent.append(event)


class _ListLogHandler(logging.Handler):
    """Captures log records emitted by a real logger, so we can prove
    the notification/reconciliation failures are actually logged
    (not just "doesn't crash")."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


# ---------------------------------------------------------------------------
# Real-database test rig (mirrors Tests/test_paper_trading_engine.py and
# Tests/test_portfolio_snapshot_service.py's own _build() helpers)
# ---------------------------------------------------------------------------


def _build(tmp_dir: str, db_name: str, *, price: float, channel, cash: float = 100_000_000.0):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / db_name)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(IDEMPOTENCY_MIGRATIONS)
    MigrationRunner(db).apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    account_repo = AccountRepository(manager)
    account_repo.create(
        account_id="paper-id", account_name="Paper Indonesia", mode="paper",
        currency="IDR", asset_class="stock_id",
        cash=cash, equity=cash, buying_power=cash,
    )
    position_repo = PositionRepository(manager)
    order_repo = OrderRepository(manager)
    trade_repo = TradeRepository(manager)
    idempotency_repo = OrderIdempotencyRepository(manager)
    portfolio_snapshot_repo = PortfolioSnapshotRepository(manager)

    order_lifecycle_service = OrderLifecycleService(order_repo)
    execution_service = ExecutionService(order_repo, trade_repo)
    account_balance_service = AccountBalanceService(account_repo)
    position_manager = PositionManager(position_repo)
    notification_builder = NotificationBuilder()
    notification_manager = NotificationManager(NotificationDispatcher([channel]))

    engine = PaperTradingEngine(
        order_lifecycle_service=order_lifecycle_service,
        execution_service=execution_service,
        account_repository=account_repo,
        position_repository=position_repo,
        order_idempotency_repository=idempotency_repo,
        kill_switch_engaged=False,
        max_order_value=1_000_000_000.0,
        account_balance_service=account_balance_service,
        position_manager=position_manager,
        notification_builder=notification_builder,
        notification_manager=notification_manager,
    )

    # Mirrors Core.composition_root's own wiring exactly: same
    # collaborators reused, no second instance of any repository.
    unrealized_pnl_engine = UnrealizedPnLEngine(_FixedPriceTool(price))
    maximum_drawdown_engine = MaximumDrawdownEngine()
    portfolio_snapshot_service = PortfolioSnapshotService(
        account_repository=account_repo,
        position_repository=position_repo,
        unrealized_pnl_engine=unrealized_pnl_engine,
        maximum_drawdown_engine=maximum_drawdown_engine,
        portfolio_snapshot_repository=portfolio_snapshot_repo,
    )
    reconciliation_engine = ReconciliationEngine(
        order_repository=order_repo,
        trade_repository=trade_repo,
        account_repository=account_repo,
        position_repository=position_repo,
    )

    # Stands in for Core.composition_root.ApplicationGraph -- only the
    # two attributes main._run_post_trade_snapshot_and_reconciliation()
    # actually reads.
    app = SimpleNamespace(
        portfolio_snapshot_service=portfolio_snapshot_service,
        reconciliation_engine=reconciliation_engine,
    )

    repos = {
        "account": account_repo,
        "position": position_repo,
        "order": order_repo,
        "trade": trade_repo,
        "idempotency": idempotency_repo,
        "portfolio_snapshot": portfolio_snapshot_repo,
    }
    return cfg, engine, app, repos


def _submit_kwargs(**overrides) -> dict:
    kwargs = dict(
        account_id="paper-id",
        symbol="BBCA",
        action="BUY",
        quantity=100.0,
        requested_price=9500.0,
        executed_at="2026-08-13T10:00:00+00:00",
        signal_evidence={"rsi": 28.0, "note": "oversold bounce"},
        user_approval=True,
        idempotency_key="req-a7fix-001",
    )
    kwargs.update(overrides)
    return kwargs


def _attach_capture(logger_name: str) -> _ListLogHandler:
    handler = _ListLogHandler()
    logging.getLogger(logger_name).addHandler(handler)
    return handler


def _detach_capture(logger_name: str, handler: _ListLogHandler) -> None:
    logging.getLogger(logger_name).removeHandler(handler)


# ---------------------------------------------------------------------------
# Scenario 1: ORDER_EXECUTED notification failure is no longer silent
# ---------------------------------------------------------------------------


def scenario_notification_failure_is_logged_not_silent():
    print("\n[Scenario 1] Blocker 1: ORDER_EXECUTED notification failure is logged, not swallowed silently")
    with tempfile.TemporaryDirectory() as tmp:
        channel = _RaisingChannel()
        cfg, engine, app, repos = _build(tmp, "s1.db", price=9600.0, channel=channel)

        handler = _attach_capture("Business.paper_trading_engine")
        try:
            trade = engine.submit_order(**_submit_kwargs())
        finally:
            _detach_capture("Business.paper_trading_engine", handler)

        check(trade is not None and trade.trade_id is not None, "submit_order() still returns a real Trade despite notification failure")
        check(channel.attempts == 1, "the failing channel's send() was actually attempted exactly once")

        error_records = [r for r in handler.records if r.levelno >= logging.ERROR]
        check(len(error_records) == 1, "exactly one ERROR-level log record was emitted for the notification failure")
        if error_records:
            message = error_records[0].getMessage()
            check("ORDER_EXECUTED notification failed" in message, "log message clearly identifies an ORDER_EXECUTED notification failure")
            check(str(trade.trade_id) in message, "log message includes the trade_id so the failure is traceable to this trade")
            check(error_records[0].exc_info is not None, "log record carries exc_info (the actual exception), not just a bare message")


def scenario_trading_state_fully_committed_despite_notification_failure():
    print("\n[Scenario 2] Blocker 1: trading state (Order/Trade/Account/Position/idempotency) is fully committed even though notification failed")
    with tempfile.TemporaryDirectory() as tmp:
        channel = _RaisingChannel()
        cfg, engine, app, repos = _build(tmp, "s2.db", price=9600.0, channel=channel)

        trade = engine.submit_order(**_submit_kwargs())

        order = repos["order"].get_by_id(trade.order_id)
        check(order is not None and order.status == "FILLED", "Order row exists and is FILLED")

        trades = repos["trade"].list_by_account("paper-id")
        check(len(trades) == 1 and trades[0].trade_id == trade.trade_id, "exactly one Trade row exists, matching the returned Trade")

        account = repos["account"].get_by_id("paper-id")
        expected_cash = 100_000_000.0 - (100.0 * 9500.0) - trade.fee - trade.tax
        check(abs(account.cash - expected_cash) < 1e-6, "Account.cash was really debited by the real BUY (fee/tax-correct), not skipped")

        positions = repos["position"].list_by_account("paper-id")
        check(len(positions) == 1 and positions[0].quantity == 100.0, "Position row exists with the correct quantity")

        idem = repos["idempotency"].get_by_key("req-a7fix-001")
        check(idem is not None and idem.trade_id == trade.trade_id, "idempotency key was recorded, linked to the real trade")


def scenario_working_channel_still_receives_event():
    print("\n[Scenario 3] Blocker 1 regression check: a working notification channel still receives ORDER_EXECUTED normally")
    with tempfile.TemporaryDirectory() as tmp:
        channel = _RecordingChannel()
        cfg, engine, app, repos = _build(tmp, "s3.db", price=9600.0, channel=channel)

        handler = _attach_capture("Business.paper_trading_engine")
        try:
            trade = engine.submit_order(**_submit_kwargs())
        finally:
            _detach_capture("Business.paper_trading_engine", handler)

        check(len(channel.sent) == 1, "the working channel actually received the ORDER_EXECUTED event")
        check(channel.sent[0].event_type.value == "ORDER_EXECUTED", "the received event has the correct event_type")
        error_records = [r for r in handler.records if r.levelno >= logging.ERROR]
        check(len(error_records) == 0, "no error is logged when the notification actually succeeds")


# ---------------------------------------------------------------------------
# Scenario 4/5: portfolio snapshot production wiring (blocker 2)
# ---------------------------------------------------------------------------


def scenario_snapshot_is_really_persisted_from_production_flow():
    print("\n[Scenario 4] Blocker 2: main._run_post_trade_snapshot_and_reconciliation() really persists a PortfolioSnapshot from real state")
    with tempfile.TemporaryDirectory() as tmp:
        channel = _RecordingChannel()
        cfg, engine, app, repos = _build(tmp, "s4.db", price=9700.0, channel=channel)

        before = repos["portfolio_snapshot"].list_by_account("paper-id")
        check(len(before) == 0, "no snapshot exists before any trade (sanity)")

        trade = engine.submit_order(**_submit_kwargs())

        buf = io.StringIO()
        with redirect_stdout(buf):
            status = main._run_post_trade_snapshot_and_reconciliation(app, "paper-id")

        check(status == 0, "helper returns 0 on a genuinely consistent account")

        snapshots = repos["portfolio_snapshot"].list_by_account("paper-id")
        check(len(snapshots) == 1, "exactly one PortfolioSnapshot row now exists, written by the real production call path")

        if snapshots:
            snap = snapshots[0]
            account = repos["account"].get_by_id("paper-id")
            expected_market_value = 100.0 * 9700.0  # real open position * the fixed real price
            check(abs(snap.cash - account.cash) < 1e-6, "snapshot.cash matches the real, already-debited Account.cash exactly")
            check(abs(snap.market_value - expected_market_value) < 1e-6, "snapshot.market_value is computed from the real open Position and real price, not a fabricated number")
            check(abs(snap.equity - (snap.cash + snap.market_value)) < 1e-6, "snapshot.equity == cash + market_value")


def scenario_reconciliation_reports_consistent_on_healthy_account():
    print("\n[Scenario 5] Blocker 3: reconciliation genuinely runs and reports CONSISTENT (no false failure) on a healthy account")
    with tempfile.TemporaryDirectory() as tmp:
        channel = _RecordingChannel()
        cfg, engine, app, repos = _build(tmp, "s5.db", price=9700.0, channel=channel)
        engine.submit_order(**_submit_kwargs())

        buf = io.StringIO()
        with redirect_stdout(buf):
            status = main._run_post_trade_snapshot_and_reconciliation(app, "paper-id")
        output = buf.getvalue()

        check(status == 0, "helper returns 0 for a consistent account")
        check("RECONCILIATION FAILURE" not in output, "no failure banner printed when the account is actually consistent")

        # Cross-check directly against the real engine, independent of the helper.
        result = app.reconciliation_engine.reconcile_account("paper-id")
        check(result.status == "CONSISTENT", "ReconciliationEngine.reconcile_account() itself reports CONSISTENT")


# ---------------------------------------------------------------------------
# Scenario 6/7: reconciliation actually detects a real violation and
# surfaces it as a failure, without mutating anything further (blocker 3)
# ---------------------------------------------------------------------------


def scenario_inconsistency_is_detected_and_surfaced_as_failure():
    print("\n[Scenario 6] Blocker 3: a genuine Order<->Trade corruption is actually detected, printed, logged, and returns non-zero")
    with tempfile.TemporaryDirectory() as tmp:
        channel = _RecordingChannel()
        cfg, engine, app, repos = _build(tmp, "s6.db", price=9700.0, channel=channel)
        trade = engine.submit_order(**_submit_kwargs())

        # Simulate the exact kind of partial-write corruption
        # ReconciliationEngine's invariant 1 exists to catch: the
        # FILLED order's filled_quantity no longer matches its own
        # trade's quantity (e.g. as could happen from a crash between
        # independently-committed statements). Raw SQL, not the
        # repository API -- deliberately bypassing normal writes to
        # simulate real corruption, exactly like
        # Tests/activation_3_2_independent_proof.py's own raw-SQL
        # technique.
        con = sqlite3.connect(str(cfg.db_path))
        con.execute(
            "UPDATE orders SET filled_quantity = ? WHERE order_id = ?",
            (999.0, trade.order_id),
        )
        con.commit()
        con.close()

        handler = _attach_capture("main")
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                status = main._run_post_trade_snapshot_and_reconciliation(app, "paper-id")
        finally:
            _detach_capture("main", handler)
        output = buf.getvalue()

        check(status == 1, "helper returns non-zero when the account is genuinely INCONSISTENT")
        check("RECONCILIATION FAILURE" in output, "a clear RECONCILIATION FAILURE banner is printed -- not silent")
        check(str(trade.order_id) in output, "the printed violation identifies the specific corrupted order")

        error_records = [r for r in handler.records if r.levelno >= logging.ERROR]
        check(len(error_records) == 1, "the inconsistency is also logged as an ERROR (visible outside stdout too)")

        # Cross-check directly against the real engine.
        result = app.reconciliation_engine.reconcile_account("paper-id")
        check(result.status == "INCONSISTENT", "ReconciliationEngine.reconcile_account() itself reports INCONSISTENT")
        check(any(str(trade.order_id) in v for v in result.violations), "the real violations list names the corrupted order")


def scenario_reconciliation_check_does_not_mutate_trading_state():
    print("\n[Scenario 7] Blocker 3: detecting INCONSISTENT does not itself corrupt/mutate/fix any further trading state (read-only)")
    with tempfile.TemporaryDirectory() as tmp:
        channel = _RecordingChannel()
        cfg, engine, app, repos = _build(tmp, "s7.db", price=9700.0, channel=channel)
        trade = engine.submit_order(**_submit_kwargs())

        con = sqlite3.connect(str(cfg.db_path))
        con.execute(
            "UPDATE orders SET filled_quantity = ? WHERE order_id = ?",
            (999.0, trade.order_id),
        )
        con.commit()
        con.close()

        before_order = repos["order"].get_by_id(trade.order_id)
        before_trades = repos["trade"].list_by_account("paper-id")
        before_account = repos["account"].get_by_id("paper-id")
        before_positions = repos["position"].list_by_account("paper-id")

        buf = io.StringIO()
        with redirect_stdout(buf):
            main._run_post_trade_snapshot_and_reconciliation(app, "paper-id")

        after_order = repos["order"].get_by_id(trade.order_id)
        after_trades = repos["trade"].list_by_account("paper-id")
        after_account = repos["account"].get_by_id("paper-id")
        after_positions = repos["position"].list_by_account("paper-id")

        check(before_order.filled_quantity == after_order.filled_quantity == 999.0, "the (deliberately corrupted) order row is untouched by the reconciliation call -- not silently 'fixed'")
        check(len(before_trades) == len(after_trades) == 1, "no Trade row was added or removed by reconciliation")
        check(before_account.cash == after_account.cash, "Account.cash is untouched by reconciliation")
        check(len(before_positions) == len(after_positions), "no Position row was added or removed by reconciliation")


def main_test() -> int:
    scenario_notification_failure_is_logged_not_silent()
    scenario_trading_state_fully_committed_despite_notification_failure()
    scenario_working_channel_still_receives_event()
    scenario_snapshot_is_really_persisted_from_production_flow()
    scenario_reconciliation_reports_consistent_on_healthy_account()
    scenario_inconsistency_is_detected_and_surfaced_as_failure()
    scenario_reconciliation_check_does_not_mutate_trading_state()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 7 FIX BLOCKERS TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main_test())