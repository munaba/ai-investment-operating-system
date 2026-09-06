"""Standalone regression checks for Activation 9.4 Step 2 -- the
optional ``--executed-at <ISO-8601 timestamp>`` flag on the existing
``paper buy``/``paper sell`` CLI path in ``main.py``.

Covers exactly the 3 focused proof points the Step 2 brief requires
(the 4th, US regular/pre-market E2E determinism, lives in
``Tests/test_activation9_us_e2e_acceptance.py``; gate-17 rejection of
a closed-session timestamp is proven directly against the engine in
``Tests/test_us_market_session_gate.py``):

    A. An explicit ``--executed-at`` value reaches
       ``PaperTradingEngine.submit_order()`` unchanged.
    B. Omitting ``--executed-at`` preserves the exact pre-Activation-
       9.4 production default (``datetime.now(timezone.utc)``-based,
       asserted without a flaky exact wall-clock comparison).
    C. A malformed ``--executed-at`` value is rejected cleanly, with
       ``submit_order()`` never called and no silent fallback to
       ``datetime.now()``.

Uses the same fakes/spy pattern already established by
``Tests/test_activation4_session1_cli_commands.py`` (``FakeApp``,
``FakePaperTradingEngine``, etc.) -- narrowest possible spy at the
``PaperTradingEngine.submit_order()`` boundary only, never a mock of
the whole engine or a real database.

Run directly with
``python Tests/test_activation9_4_step2_executed_at_cli.py`` -- no
external test framework required, matching every other
``Tests/test_*`` script in this suite.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import main  # noqa: E402
from Database.models import Account, RankingSnapshot, Trade  # noqa: E402
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
# Fakes (mirrors Tests/test_activation4_session1_cli_commands.py exactly)
# ---------------------------------------------------------------------------


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
    def get_open_position(self, account_id: str, symbol: str):
        return None


class FakePaperTradingEngine:
    """Records every ``submit_order()`` call's kwargs -- the narrowest
    possible spy point, proving what the CLI actually submits without
    mocking the whole engine.
    """

    def __init__(self, trade: Optional[Trade] = None) -> None:
        self._trade = trade
        self.calls: List[Dict[str, Any]] = []

    def submit_order(self, **kwargs: Any) -> Trade:
        self.calls.append(kwargs)
        assert self._trade is not None
        return self._trade


class FakeMarketPriceTool:
    def __init__(self, price: Optional[float] = None) -> None:
        self._price = price

    def execute(self, context: Any) -> ToolResult:
        return ToolResult(success=True, output={"symbol": "TEST", "price": self._price, "trend": "unknown"}, error=None, metadata={})


class FakePortfolioSnapshotService:
    def take_snapshot(self, account_id: str):
        return None


class _FakeReconciliationResult:
    consistent = True
    violations: List[Any] = []
    status = "CONSISTENT"


class FakeReconciliationEngine:
    def reconcile_account(self, account_id: str):
        return _FakeReconciliationResult()


class FakeApp:
    def __init__(
        self,
        snapshot_repository: Optional[FakeSnapshotRepository] = None,
        account_repository: Optional[FakeAccountRepository] = None,
        paper_trading_engine: Optional[FakePaperTradingEngine] = None,
        market_price_tool: Optional[FakeMarketPriceTool] = None,
    ) -> None:
        self.snapshot_repository = snapshot_repository or FakeSnapshotRepository()
        self.account_repository = account_repository or FakeAccountRepository()
        self.position_repository = FakePositionRepository()
        self.paper_trading_engine = paper_trading_engine or FakePaperTradingEngine()
        self.market_price_tool = market_price_tool or FakeMarketPriceTool()
        self.portfolio_snapshot_service = FakePortfolioSnapshotService()
        self.reconciliation_engine = FakeReconciliationEngine()
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


def _snapshot(symbol: str = "BBCA", recommendation: str = "BUY") -> RankingSnapshot:
    return RankingSnapshot(
        snapshot_id=1,
        scan_time="2026-08-11T00:00:00+00:00",
        symbol=symbol,
        recommendation=recommendation,
        confidence="HIGH",
        priority=1,
        rank=1,
        status="success",
        score=80,
        score_breakdown_json=None,
        evidence_summary="strong volume + bullish trend",
        error_message=None,
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


def _standard_app() -> "tuple[FakeApp, FakePaperTradingEngine]":
    account = _account()
    snapshot = _snapshot()
    engine = FakePaperTradingEngine(trade=_trade("BUY", 500, 9_500.0))
    app = FakeApp(
        account_repository=FakeAccountRepository(account),
        snapshot_repository=FakeSnapshotRepository([snapshot]),
        paper_trading_engine=engine,
        market_price_tool=FakeMarketPriceTool(price=9_500.0),
    )
    return app, engine


# ---------------------------------------------------------------------------
# A. Explicit --executed-at reaches PaperTradingEngine unchanged
# ---------------------------------------------------------------------------


def scenario_buy_explicit_executed_at_reaches_engine_unchanged():
    print("\n[A1] 'paper buy ... --executed-at TS' reaches PaperTradingEngine.submit_order() byte-for-byte")
    app, engine = _standard_app()
    supplied = "2026-01-06T15:00:00+00:00"

    with redirect_stdout(io.StringIO()):
        exit_code = main._run_paper_buy_command(app, ["BBCA", "--allocation", "0.05", "--executed-at", supplied])

    check(exit_code == 0, "exit code is 0")
    check(len(engine.calls) == 1, "submit_order() called exactly once")
    check(engine.calls[0]["executed_at"] == supplied, "submitted executed_at == CLI supplied executed_at")


def scenario_sell_explicit_executed_at_reaches_engine_unchanged():
    print("\n[A2] 'paper sell ... --executed-at TS' reaches PaperTradingEngine.submit_order() byte-for-byte")
    account = _account()
    engine = FakePaperTradingEngine(trade=_trade("SELL", 100, 9_500.0))
    app = FakeApp(
        account_repository=FakeAccountRepository(account),
        snapshot_repository=FakeSnapshotRepository([_snapshot()]),
        paper_trading_engine=engine,
        market_price_tool=FakeMarketPriceTool(price=9_500.0),
    )
    supplied = "2026-01-06T15:00:00+00:00"

    with redirect_stdout(io.StringIO()):
        exit_code = main._run_paper_sell_command(app, ["BBCA", "--quantity", "100", "--executed-at", supplied])

    check(exit_code == 0, "exit code is 0")
    check(len(engine.calls) == 1, "submit_order() called exactly once")
    check(engine.calls[0]["executed_at"] == supplied, "submitted executed_at == CLI supplied executed_at")


# ---------------------------------------------------------------------------
# B. Default behavior (--executed-at omitted) preserved
# ---------------------------------------------------------------------------


def scenario_buy_omitted_executed_at_uses_current_utc_time():
    print("\n[B1] 'paper buy' without --executed-at still generates a real current-UTC-time executed_at")
    app, engine = _standard_app()
    before = datetime.now(timezone.utc)

    with redirect_stdout(io.StringIO()):
        exit_code = main._run_paper_buy_command(app, ["BBCA", "--allocation", "0.05"])

    after = datetime.now(timezone.utc)
    check(exit_code == 0, "exit code is 0")
    check(len(engine.calls) == 1, "submit_order() called exactly once")
    submitted_raw = engine.calls[0]["executed_at"]
    submitted = datetime.fromisoformat(submitted_raw)
    # Loose window (not an exact wall-clock assertion) -- inherently
    # non-flaky: only proves it's a genuine "now", not any fixed value.
    check(
        before - timedelta(seconds=5) <= submitted <= after + timedelta(seconds=5),
        f"executed_at ({submitted_raw}) falls within the real current-UTC-time window "
        f"[{before.isoformat()}, {after.isoformat()}]",
    )


def scenario_sell_omitted_executed_at_uses_current_utc_time():
    print("\n[B2] 'paper sell' without --executed-at still generates a real current-UTC-time executed_at")
    account = _account()
    engine = FakePaperTradingEngine(trade=_trade("SELL", 100, 9_500.0))
    app = FakeApp(
        account_repository=FakeAccountRepository(account),
        snapshot_repository=FakeSnapshotRepository([_snapshot()]),
        paper_trading_engine=engine,
        market_price_tool=FakeMarketPriceTool(price=9_500.0),
    )
    before = datetime.now(timezone.utc)

    with redirect_stdout(io.StringIO()):
        exit_code = main._run_paper_sell_command(app, ["BBCA", "--quantity", "100"])

    after = datetime.now(timezone.utc)
    check(exit_code == 0, "exit code is 0")
    submitted = datetime.fromisoformat(engine.calls[0]["executed_at"])
    check(
        before - timedelta(seconds=5) <= submitted <= after + timedelta(seconds=5),
        "executed_at falls within the real current-UTC-time window",
    )


# ---------------------------------------------------------------------------
# C. Invalid --executed-at rejected cleanly, no silent fallback
# ---------------------------------------------------------------------------


def scenario_buy_invalid_executed_at_rejected_cleanly():
    print("\n[C1] 'paper buy ... --executed-at <malformed>' is rejected cleanly, submit_order() never called")
    app, engine = _standard_app()

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main._run_paper_buy_command(app, ["BBCA", "--allocation", "0.05", "--executed-at", "not-a-timestamp"])
    output = buf.getvalue()

    check(exit_code == 1, "exit code is 1 for a malformed --executed-at value")
    check(len(engine.calls) == 0, "submit_order() is never called for an invalid --executed-at (no silent datetime.now() fallback)")
    check("Invalid --executed-at" in output, "a clear error message names the invalid --executed-at value")


def scenario_sell_invalid_executed_at_rejected_cleanly():
    print("\n[C2] 'paper sell ... --executed-at <malformed>' is rejected cleanly, submit_order() never called")
    account = _account()
    engine = FakePaperTradingEngine(trade=_trade("SELL", 100, 9_500.0))
    app = FakeApp(
        account_repository=FakeAccountRepository(account),
        snapshot_repository=FakeSnapshotRepository([_snapshot()]),
        paper_trading_engine=engine,
        market_price_tool=FakeMarketPriceTool(price=9_500.0),
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main._run_paper_sell_command(app, ["BBCA", "--quantity", "100", "--executed-at", "2026-13-99T99:99:99"])
    output = buf.getvalue()

    check(exit_code == 1, "exit code is 1 for a malformed --executed-at value")
    check(len(engine.calls) == 0, "submit_order() is never called for an invalid --executed-at (no silent datetime.now() fallback)")
    check("Invalid --executed-at" in output, "a clear error message names the invalid --executed-at value")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_SCENARIOS = [
    scenario_buy_explicit_executed_at_reaches_engine_unchanged,
    scenario_sell_explicit_executed_at_reaches_engine_unchanged,
    scenario_buy_omitted_executed_at_uses_current_utc_time,
    scenario_sell_omitted_executed_at_uses_current_utc_time,
    scenario_buy_invalid_executed_at_rejected_cleanly,
    scenario_sell_invalid_executed_at_rejected_cleanly,
]

if __name__ == "__main__":
    for scenario in _SCENARIOS:
        scenario()

    print("\n" + "=" * 70)
    print(f"ACTIVATION 9.4 STEP 2 --executed-at CLI TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 70)
    if _FAILURES:
        print("\nFailed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    sys.exit(0)
