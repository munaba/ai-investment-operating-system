"""Standalone regression checks for Activation 4 Session 1's new CLI
commands in ``main.py``:

    * ``watchlist remove SYMBOL``
    * ``recommendation SYMBOL``
    * ``paper buy SYMBOL --allocation X``
    * ``paper sell SYMBOL --quantity X``

Covers exactly the 7 proof points the Session 1 brief requires:

    1. ``watchlist remove`` calls ``WatchlistRepository.remove()``.
    2. ``recommendation SYMBOL`` reads the latest scan snapshot for
       that symbol and displays it, with real ``N/A`` markers for
       fields that have no source (risk / suggested allocation /
       estimated cost without a chosen allocation).
    3. Allocation quantity is computed from actual account cash and
       IDX lot size -- never a hardcoded/zero capital.
    4. ``paper buy`` submits through
       ``PaperTradingEngine.submit_order()`` -- never a second/
       duplicated validation or persistence path.
    5. ``paper sell`` submits through
       ``PaperTradingEngine.submit_order()`` the same way.
    6. ``scan`` still never creates an order -- it has no
       ``paper_trading_engine`` reference at all in its call path.
    7. Explicit user approval (``user_approval=True``) is passed
       through to ``submit_order()`` for both buy and sell, and only
       because the CLI command itself was invoked (no other approval
       source is read).

Run directly with ``python Tests/test_activation4_session1_cli_commands.py``
-- no external test framework required, matching
``test_manual_scan_command.py``/``test_paper_trading_engine.py``. Uses
only stdlib ``unittest.mock`` plus hand-rolled fakes for
``ApplicationGraph`` collaborators -- never a real database/network
call.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import main  # noqa: E402
from Business.execution_policy_config import ExecutionPolicy  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.models import Account, Position, RankingSnapshot, Trade  # noqa: E402
from Orchestration.tool_result import ToolResult  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


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
# Fakes
# ---------------------------------------------------------------------------


class FakeWatchlistRepository:
    def __init__(self, tickers: Optional[List[str]] = None) -> None:
        self._tickers: List[str] = list(tickers or [])
        self.add_calls: List[str] = []
        self.remove_calls: List[str] = []

    def add(self, ticker: str) -> None:
        self.add_calls.append(ticker)
        if ticker not in self._tickers:
            self._tickers.append(ticker)

    def remove(self, ticker: str) -> None:
        self.remove_calls.append(ticker)
        if ticker in self._tickers:
            self._tickers.remove(ticker)

    def list_all(self) -> List[str]:
        return list(self._tickers)


class FakeSnapshotRepository:
    def __init__(self, rows: Optional[List[RankingSnapshot]] = None) -> None:
        self._rows = rows or []

    def list_latest(self) -> List[RankingSnapshot]:
        return list(self._rows)


class FakeAccountRepository:
    def __init__(self, account: Optional[Account] = None) -> None:
        self._account = account

    def get_by_id(self, account_id: str) -> Optional[Account]:
        if self._account is not None and self._account.account_id == account_id:
            return self._account
        return None


class FakePositionRepository:
    def __init__(self, position: Optional[Position] = None) -> None:
        self._position = position

    def get_open_position(self, account_id: str, symbol: str) -> Optional[Position]:
        return self._position


class FakePaperTradingEngine:
    """Records every ``submit_order()`` call's kwargs and either
    returns a caller-supplied ``Trade`` or raises a caller-supplied
    exception -- proves the CLI never touches Order/Trade/Account/
    Position persistence directly, only through this one entry point.
    """

    def __init__(self, trade: Optional[Trade] = None, raises: Optional[Exception] = None) -> None:
        self._trade = trade
        self._raises = raises
        self.calls: List[Dict[str, Any]] = []

    def submit_order(self, **kwargs: Any) -> Trade:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        assert self._trade is not None
        return self._trade


class FakeMarketPriceTool:
    """Stands in for ``Orchestration.market_price_tool.MarketPriceTool``
    -- records the ``ToolContext`` passed and returns a fixed price
    (never a real network/yfinance call in this test).
    """

    def __init__(self, price: Optional[float] = None) -> None:
        self._price = price
        self.contexts: List[Any] = []

    def execute(self, context: Any) -> ToolResult:
        self.contexts.append(context)
        return ToolResult(success=True, output={"symbol": "TEST", "price": self._price, "trend": "unknown"}, error=None, metadata={})


class FakePortfolioSnapshotService:
    """Activation 7 FIX test-fixture update: stands in for
    ``Business.portfolio_snapshot_service.PortfolioSnapshotService``
    for CLI tests that don't care about snapshot content -- records
    calls, never raises, mirrors the shape
    ``main._run_post_trade_snapshot_and_reconciliation`` actually
    calls (``take_snapshot(account_id)``).
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def take_snapshot(self, account_id: str):
        self.calls.append(account_id)
        return None


class _FakeReconciliationResult:
    def __init__(self, consistent: bool = True, violations=None) -> None:
        self.consistent = consistent
        self.violations = violations or []

    @property
    def status(self) -> str:
        return "CONSISTENT" if self.consistent else "INCONSISTENT"


class FakeReconciliationEngine:
    """Activation 7 FIX test-fixture update: stands in for
    ``Business.reconciliation_engine.ReconciliationEngine`` for CLI
    tests -- always reports CONSISTENT by default, mirroring
    ``main._run_post_trade_snapshot_and_reconciliation``'s call shape
    (``reconcile_account(account_id)``).
    """

    def __init__(self, consistent: bool = True) -> None:
        self.consistent = consistent
        self.calls: list[str] = []

    def reconcile_account(self, account_id: str):
        self.calls.append(account_id)
        return _FakeReconciliationResult(consistent=self.consistent)


class FakeApp:
    """Stands in for ``Core.composition_root.ApplicationGraph`` --
    only the attributes each command under test actually reads.
    """

    def __init__(
        self,
        watchlist_repository: Optional[FakeWatchlistRepository] = None,
        snapshot_repository: Optional[FakeSnapshotRepository] = None,
        account_repository: Optional[FakeAccountRepository] = None,
        position_repository: Optional[FakePositionRepository] = None,
        paper_trading_engine: Optional[FakePaperTradingEngine] = None,
        market_price_tool: Optional[FakeMarketPriceTool] = None,
        portfolio_snapshot_service: Optional[FakePortfolioSnapshotService] = None,
        reconciliation_engine: Optional[FakeReconciliationEngine] = None,
    ) -> None:
        self.watchlist_repository = watchlist_repository or FakeWatchlistRepository()
        self.snapshot_repository = snapshot_repository or FakeSnapshotRepository()
        self.account_repository = account_repository or FakeAccountRepository()
        self.position_repository = position_repository or FakePositionRepository()
        self.paper_trading_engine = paper_trading_engine or FakePaperTradingEngine()
        self.market_price_tool = market_price_tool or FakeMarketPriceTool()
        # Activation 7 FIX: main._run_paper_buy_command()/
        # _run_paper_sell_command() now call
        # main._run_post_trade_snapshot_and_reconciliation() after a
        # successful trade, which reads exactly these two attributes.
        # Default to inert, always-succeeding fakes so every existing
        # scenario in this file keeps exercising only what it already
        # tests (PaperTradingEngine wiring), unaffected by blockers
        # 2/3's new post-trade step.
        self.portfolio_snapshot_service = portfolio_snapshot_service or FakePortfolioSnapshotService()
        self.reconciliation_engine = reconciliation_engine or FakeReconciliationEngine()
        self.agent_name = "fake-agent"
        self.provider_name = "fake-provider"


def _account(cash: float = 100_000_000.0, account_id: str = "paper") -> Account:
    return Account(
        account_id=account_id,
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=cash,
        equity=cash,
        buying_power=cash,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def _snapshot(
    symbol: str = "BBCA",
    recommendation: str = "BUY",
    confidence: str = "HIGH",
    scan_time: str = "2026-08-11T00:00:00+00:00",
    status: str = "success",
    error_message: Optional[str] = None,
) -> RankingSnapshot:
    return RankingSnapshot(
        snapshot_id=1,
        scan_time=scan_time,
        symbol=symbol,
        recommendation=recommendation,
        confidence=confidence,
        priority=1,
        rank=1,
        status=status,
        score=80,
        score_breakdown_json=None,
        evidence_summary="strong volume + bullish trend",
        error_message=error_message,
    )


def _trade(action: str, quantity: float, fill_price: float) -> Trade:
    return Trade(
        trade_id=1,
        order_id=1,
        account_id="paper",
        symbol="BBCA",
        action=action,
        quantity=quantity,
        fill_price=fill_price,
        fee=0.0,
        tax=0.0,
        executed_at="2026-08-11T00:00:00+00:00",
    )


class BoomError(Exception):
    """Distinct, unwrapped exception type used to prove propagation."""


# ---------------------------------------------------------------------------
# 1. watchlist remove
# ---------------------------------------------------------------------------


def scenario_watchlist_remove_calls_repository():
    print("\n[1] 'watchlist remove SYMBOL' calls WatchlistRepository.remove()")
    repo = FakeWatchlistRepository(tickers=["BBCA", "TLKM"])
    app = FakeApp(watchlist_repository=repo)

    with redirect_stdout(io.StringIO()):
        exit_code = main._run_watchlist_command(app, ["remove", "TLKM"])

    check(exit_code == 0, "exit code is 0 on success")
    check(repo.remove_calls == ["TLKM"], "WatchlistRepository.remove() was called exactly once with 'TLKM'")
    check("TLKM" not in repo.list_all(), "TLKM is actually gone from the watchlist afterward")
    check("BBCA" in repo.list_all(), "unrelated ticker BBCA is untouched")


def scenario_watchlist_remove_multiple_and_case_insensitive():
    print("\n[1b] 'watchlist remove' accepts multiple tickers and upper-cases them")
    repo = FakeWatchlistRepository(tickers=["BBCA", "TLKM", "BMRI"])
    app = FakeApp(watchlist_repository=repo)

    with redirect_stdout(io.StringIO()):
        main._run_watchlist_command(app, ["remove", "tlkm", "bmri"])

    check(repo.remove_calls == ["TLKM", "BMRI"], "both tickers removed, upper-cased")


def scenario_watchlist_remove_no_args_usage():
    print("\n[1c] 'watchlist remove' with no ticker prints usage and returns 1")
    repo = FakeWatchlistRepository()
    app = FakeApp(watchlist_repository=repo)

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main._run_watchlist_command(app, ["remove"])

    check(exit_code == 1, "exit code is 1 with no ticker supplied")
    check(repo.remove_calls == [], "repository.remove() was never called")
    check("Usage" in buf.getvalue(), "usage message printed")


# ---------------------------------------------------------------------------
# 2. recommendation SYMBOL
# ---------------------------------------------------------------------------


def scenario_recommendation_reads_latest_snapshot_for_symbol():
    print("\n[2] 'recommendation SYMBOL' reads the latest scan snapshot filtered by symbol")
    rows = [
        _snapshot(symbol="TLKM", recommendation="WAIT", confidence="MEDIUM"),
        _snapshot(symbol="BBCA", recommendation="BUY", confidence="HIGH"),
    ]
    app = FakeApp(snapshot_repository=FakeSnapshotRepository(rows))

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main._run_recommendation_command(app, ["BBCA"])
    output = buf.getvalue()

    check(exit_code == 0, "exit code is 0")
    check("BBCA" in output, "output includes the requested symbol")
    check("BUY" in output, "output includes BBCA's own signal, not TLKM's")
    check("HIGH" in output, "output includes BBCA's own confidence")
    check("strong volume + bullish trend" in output, "output includes the real evidence_summary as 'reason'")
    check("2026-08-11T00:00:00+00:00" in output, "output includes the real scan_time as data timestamp")


def scenario_recommendation_shows_na_for_gap_fields():
    print("\n[2b] 'recommendation SYMBOL' shows N/A for fields with no real source (risk/suggested allocation/estimated cost/stop)")
    rows = [_snapshot(symbol="BBCA")]
    app = FakeApp(snapshot_repository=FakeSnapshotRepository(rows), position_repository=FakePositionRepository(position=None))

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_recommendation_command(app, ["BBCA"])
    output = buf.getvalue()

    check("N/A" in output, "output contains at least one honest N/A marker")
    check("Risk" in output and "N/A" in output.split("Risk")[1].splitlines()[0], "Risk field is N/A, not invented")
    check(
        "Stop Loss       : N/A" in output,
        "Stop Loss is N/A when no open position exists (never a guessed number)",
    )


def scenario_recommendation_shows_real_stop_when_position_exists():
    print("\n[2c] 'recommendation SYMBOL' shows a real stop_loss when an open Position already has one")
    rows = [_snapshot(symbol="BBCA")]
    position = Position(
        position_id=1,
        account_id="paper",
        symbol="BBCA",
        quantity=100.0,
        average_price=9000.0,
        realized_pnl=0.0,
        status="open",
        stop_loss=8500.0,
        take_profit=9500.0,
        created_at="2026-08-01T00:00:00+00:00",
        updated_at="2026-08-01T00:00:00+00:00",
    )
    app = FakeApp(snapshot_repository=FakeSnapshotRepository(rows), position_repository=FakePositionRepository(position=position))

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_recommendation_command(app, ["BBCA"])
    output = buf.getvalue()

    check("8500.0" in output, "output shows the real, persisted stop_loss (never invented) when one exists")


def scenario_recommendation_no_snapshot_found():
    print("\n[2d] 'recommendation SYMBOL' with no scan data tells the user to scan first, does not crash")
    app = FakeApp(snapshot_repository=FakeSnapshotRepository([]))

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main._run_recommendation_command(app, ["BBCA"])
    output = buf.getvalue()

    check(exit_code == 0, "exit code is 0 (informational, not a crash)")
    check("scan" in output.lower(), "output tells the user to run scan first")


# ---------------------------------------------------------------------------
# 3. Allocation uses actual cash + IDX lot adjustment
# ---------------------------------------------------------------------------


def scenario_allocation_uses_actual_cash_and_lot_size():
    print("\n[3] allocation quantity is computed from actual cash, allocation %, price, and IDX lot size")
    # cash=100,000,000; allocation=5%; price=9,500 -> target=5,000,000
    # raw_qty = floor(5,000,000 / 9,500) = 526 -> lot-adjusted to nearest 100 below = 500
    qty = main._compute_allocation_quantity(cash=100_000_000.0, allocation=0.05, price=9_500.0, lot_size=100)
    check(qty == 500, f"quantity is lot-adjusted correctly (got {qty}, expected 500)")
    check(qty % 100 == 0, "quantity is always an exact multiple of the IDX lot size")


def scenario_allocation_never_uses_zero_capital():
    print("\n[3b] allocation never computes a non-zero quantity from zero/negative cash (never capital=0)")
    qty_zero_cash = main._compute_allocation_quantity(cash=0.0, allocation=0.05, price=9_500.0, lot_size=100)
    check(qty_zero_cash == 0, "zero cash produces zero quantity, not a fabricated positive number")

    qty_real_cash = main._compute_allocation_quantity(cash=100_000_000.0, allocation=0.05, price=9_500.0, lot_size=100)
    check(qty_real_cash > 0, "real, positive cash produces a real, positive quantity")


def scenario_allocation_too_small_for_one_lot():
    print("\n[3c] allocation too small to afford even one lot returns 0, not a negative/fractional lot")
    qty = main._compute_allocation_quantity(cash=1_000_000.0, allocation=0.001, price=9_500.0, lot_size=100)
    check(qty == 0, "sub-one-lot allocation correctly yields 0")


# ---------------------------------------------------------------------------
# 4 & 7. paper buy submits through PaperTradingEngine with explicit approval
# ---------------------------------------------------------------------------


def scenario_paper_buy_submits_through_paper_trading_engine():
    print("\n[4] 'paper buy SYMBOL --allocation X' submits through PaperTradingEngine.submit_order()")
    account = _account(cash=100_000_000.0)
    snapshot = _snapshot(symbol="BBCA", recommendation="BUY")
    engine = FakePaperTradingEngine(trade=_trade("BUY", 500, 9_500.0))
    price_tool = FakeMarketPriceTool(price=9_500.0)
    app = FakeApp(
        account_repository=FakeAccountRepository(account),
        snapshot_repository=FakeSnapshotRepository([snapshot]),
        paper_trading_engine=engine,
        market_price_tool=price_tool,
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main._run_paper_buy_command(app, ["BBCA", "--allocation", "0.05"])
    output = buf.getvalue()

    check(exit_code == 0, "exit code is 0 on a successful buy")
    check(len(engine.calls) == 1, "PaperTradingEngine.submit_order() was called exactly once")
    call = engine.calls[0]
    check(call["account_id"] == "paper", "account_id passed through is the real account_id")
    check(call["symbol"] == "BBCA", "symbol passed through matches the requested symbol")
    check(call["action"] == "BUY", "action is BUY")
    check(call["quantity"] == 500, "quantity is the lot-adjusted allocation quantity, not a fabricated number")
    check(call["requested_price"] == 9_500.0, "requested_price is the real fetched price, not a fabricated number")
    check(call["signal_evidence"] is snapshot, "signal_evidence is the real snapshot from the latest scan, not fabricated")
    check("Order FILLED" in output, "success output confirms the fill")


def scenario_paper_buy_passes_explicit_approval():
    print("\n[7a] 'paper buy' passes user_approval=True to submit_order() -- the command itself is the approval")
    account = _account(cash=100_000_000.0)
    snapshot = _snapshot(symbol="BBCA")
    engine = FakePaperTradingEngine(trade=_trade("BUY", 500, 9_500.0))
    app = FakeApp(
        account_repository=FakeAccountRepository(account),
        snapshot_repository=FakeSnapshotRepository([snapshot]),
        paper_trading_engine=engine,
        market_price_tool=FakeMarketPriceTool(price=9_500.0),
    )

    with redirect_stdout(io.StringIO()):
        main._run_paper_buy_command(app, ["BBCA", "--allocation", "0.05"])

    check(engine.calls[0]["user_approval"] is True, "user_approval is exactly True")
    check(isinstance(engine.calls[0]["idempotency_key"], str) and engine.calls[0]["idempotency_key"].strip() != "", "a real, non-blank idempotency_key is supplied")


def scenario_paper_buy_rejects_without_prior_recommendation():
    print("\n[4b] 'paper buy' refuses to submit when there is no prior recommendation snapshot (flow: scan -> recommendation -> approval -> order)")
    account = _account(cash=100_000_000.0)
    engine = FakePaperTradingEngine()
    app = FakeApp(
        account_repository=FakeAccountRepository(account),
        snapshot_repository=FakeSnapshotRepository([]),  # no scan data at all
        paper_trading_engine=engine,
        market_price_tool=FakeMarketPriceTool(price=9_500.0),
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main._run_paper_buy_command(app, ["BBCA", "--allocation", "0.05"])

    check(exit_code == 1, "exit code is 1")
    check(len(engine.calls) == 0, "submit_order() is never called without a prior recommendation")


def scenario_paper_buy_engine_rejection_propagates_as_clean_error():
    print("\n[4c] a ValidationError from PaperTradingEngine is reported cleanly, not swallowed or re-validated")
    account = _account(cash=100_000_000.0)
    snapshot = _snapshot(symbol="BBCA")
    boom = ValidationError("Insufficient cash", details={"reason": "INSUFFICIENT_CASH"})
    engine = FakePaperTradingEngine(raises=boom)
    app = FakeApp(
        account_repository=FakeAccountRepository(account),
        snapshot_repository=FakeSnapshotRepository([snapshot]),
        paper_trading_engine=engine,
        market_price_tool=FakeMarketPriceTool(price=9_500.0),
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main._run_paper_buy_command(app, ["BBCA", "--allocation", "0.05"])
    output = buf.getvalue()

    check(exit_code == 1, "exit code is 1 on rejection")
    check("INSUFFICIENT_CASH" in output, "the engine's real rejection reason is shown, not a generic message")
    check(len(engine.calls) == 1, "submit_order() was still the single call made (no retry loop, no second path)")


# ---------------------------------------------------------------------------
# 5 & 7. paper sell submits through PaperTradingEngine with explicit approval
# ---------------------------------------------------------------------------


def scenario_paper_sell_submits_through_paper_trading_engine():
    print("\n[5] 'paper sell SYMBOL --quantity X' submits through PaperTradingEngine.submit_order()")
    account = _account(cash=100_000_000.0)
    snapshot = _snapshot(symbol="BBCA")
    engine = FakePaperTradingEngine(trade=_trade("SELL", 100, 9_600.0))
    app = FakeApp(
        account_repository=FakeAccountRepository(account),
        snapshot_repository=FakeSnapshotRepository([snapshot]),
        paper_trading_engine=engine,
        market_price_tool=FakeMarketPriceTool(price=9_600.0),
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main._run_paper_sell_command(app, ["BBCA", "--quantity", "100"])
    output = buf.getvalue()

    check(exit_code == 0, "exit code is 0 on a successful sell")
    check(len(engine.calls) == 1, "PaperTradingEngine.submit_order() was called exactly once")
    call = engine.calls[0]
    check(call["action"] == "SELL", "action is SELL")
    check(call["quantity"] == 100.0, "quantity is exactly the caller-supplied --quantity, not recomputed via allocation")
    check(call["requested_price"] == 9_600.0, "requested_price is the real fetched price")
    check("Order FILLED" in output, "success output confirms the fill")


def scenario_paper_sell_passes_explicit_approval():
    print("\n[7b] 'paper sell' passes user_approval=True to submit_order()")
    account = _account(cash=100_000_000.0)
    snapshot = _snapshot(symbol="BBCA")
    engine = FakePaperTradingEngine(trade=_trade("SELL", 100, 9_600.0))
    app = FakeApp(
        account_repository=FakeAccountRepository(account),
        snapshot_repository=FakeSnapshotRepository([snapshot]),
        paper_trading_engine=engine,
        market_price_tool=FakeMarketPriceTool(price=9_600.0),
    )

    with redirect_stdout(io.StringIO()):
        main._run_paper_sell_command(app, ["BBCA", "--quantity", "100"])

    check(engine.calls[0]["user_approval"] is True, "user_approval is exactly True")


def scenario_paper_sell_rejects_bad_quantity():
    print("\n[5b] 'paper sell' rejects a non-numeric/non-positive --quantity before ever calling the engine")
    account = _account(cash=100_000_000.0)
    engine = FakePaperTradingEngine()
    app = FakeApp(account_repository=FakeAccountRepository(account), paper_trading_engine=engine)

    with redirect_stdout(io.StringIO()):
        exit_code_bad = main._run_paper_sell_command(app, ["BBCA", "--quantity", "not-a-number"])
    with redirect_stdout(io.StringIO()):
        exit_code_neg = main._run_paper_sell_command(app, ["BBCA", "--quantity", "-5"])

    check(exit_code_bad == 1, "non-numeric quantity rejected with exit code 1")
    check(exit_code_neg == 1, "negative quantity rejected with exit code 1")
    check(len(engine.calls) == 0, "submit_order() is never called for an invalid quantity")


# ---------------------------------------------------------------------------
# 6. scan never creates an order
# ---------------------------------------------------------------------------


class FakeManualScanServiceNoOrders:
    def __init__(self, report) -> None:
        self._report = report
        self.calls: List[str] = []

    def run_scan(self, generated_at: str):
        self.calls.append(generated_at)
        return self._report


def scenario_scan_never_touches_paper_trading_engine():
    print("\n[6] 'scan' never creates an order -- it has no paper_trading_engine reference in its call path")
    from Business.report_service import Report

    report = Report(generated_at="irrelevant", recommendations=[], total_symbols=0)
    scan_service = FakeManualScanServiceNoOrders(report)

    class ScanOnlyApp:
        """Deliberately has NO paper_trading_engine attribute at all --
        if _run_manual_scan/_run_scan_command ever touched it, this
        would raise AttributeError, proving the coupling doesn't exist.
        """

        def __init__(self) -> None:
            self.manual_scan_service = scan_service
            self.snapshot_repository = FakeSnapshotRepository([])

        def __getattr__(self, name):
            if name == "paper_trading_engine":
                raise AssertionError("scan command must never touch paper_trading_engine")
            raise AttributeError(name)

    app = ScanOnlyApp()

    raised = False
    try:
        with redirect_stdout(io.StringIO()):
            main._run_manual_scan(app)
    except AssertionError:
        raised = True

    check(not raised, "_run_manual_scan() never accesses app.paper_trading_engine")
    check(len(scan_service.calls) == 1, "run_scan() was called exactly once")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_SCENARIOS = [
    scenario_watchlist_remove_calls_repository,
    scenario_watchlist_remove_multiple_and_case_insensitive,
    scenario_watchlist_remove_no_args_usage,
    scenario_recommendation_reads_latest_snapshot_for_symbol,
    scenario_recommendation_shows_na_for_gap_fields,
    scenario_recommendation_shows_real_stop_when_position_exists,
    scenario_recommendation_no_snapshot_found,
    scenario_allocation_uses_actual_cash_and_lot_size,
    scenario_allocation_never_uses_zero_capital,
    scenario_allocation_too_small_for_one_lot,
    scenario_paper_buy_submits_through_paper_trading_engine,
    scenario_paper_buy_passes_explicit_approval,
    scenario_paper_buy_rejects_without_prior_recommendation,
    scenario_paper_buy_engine_rejection_propagates_as_clean_error,
    scenario_paper_sell_submits_through_paper_trading_engine,
    scenario_paper_sell_passes_explicit_approval,
    scenario_paper_sell_rejects_bad_quantity,
    scenario_scan_never_touches_paper_trading_engine,
]

if __name__ == "__main__":
    for scenario in _SCENARIOS:
        scenario()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 4 SESSION 1 CLI COMMAND TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    sys.exit(0)