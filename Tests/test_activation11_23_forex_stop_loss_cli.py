"""Activation 11.23 -- Forex stop-loss CLI plumbing (``--stop-loss``).

Exercises the real CLI functions in ``main.py`` (``_parse_paper_order_args``,
``_resolve_stop_loss``, ``_run_paper_buy_command``, ``_run_paper_sell_command``)
against one temporary SQLite database, proving a new, optional
``--stop-loss PRICE`` flag is parsed once by the shared paper-order
parser and forwarded unchanged to
``PaperTradingEngine.submit_order(stop_loss=...)`` for Forex BUY/SELL
orders -- CLI input plumbing ONLY (Activation 11 roadmap "Activation
awal": analysis / paper forex / no leverage live / no autonomous
execution). Directional stop-loss validation itself remains solely
``PaperTradingEngine``'s (Activation 11.14) responsibility; nothing in
``main.py`` duplicates it.

Boundary spied (not replaced): ``PaperTradingEngine.submit_order`` is
wrapped (not stubbed) so this test can capture the exact keyword
arguments (including ``stop_loss``) it was called with, while still
calling straight through to the real, unmodified method underneath --
so every one of its real 17 pre-trade gates still runs for real. This
is the "narrow spy" the roadmap step explicitly permits. The parser is
never bypassed: every scenario drives ``_run_paper_buy_command``/
``_run_paper_sell_command`` with a raw ``argv`` list, exactly as a real
CLI invocation would.

Boundary mocked (module-level, network only, mirrors every other
``Tests/test_activation1*_*_paper_workflow.py`` file in this suite):
``Orchestration.market_price_tool._fetch_real_prices``.

Nothing else is mocked. In particular, never mocked: AccountRepository,
OrderRepository, TradeRepository, PositionRepository,
SnapshotRepository, PaperTradingEngine, ExecutionService,
OrderLifecycleService, ReconciliationEngine.

Run directly: ``python Tests/test_activation11_23_forex_stop_loss_cli.py``
-- no external test framework required, matching every other
``Tests/test_*.py``/``*_proof.py`` script in this suite.
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path
from typing import List

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import Orchestration.market_price_tool as market_price_tool_module  # noqa: E402

from Business.account_balance_service import AccountBalanceService  # noqa: E402
from Business.execution_policy_config import load_execution_policy  # noqa: E402
from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.notification_builder import NotificationBuilder  # noqa: E402
from Business.notification_dispatcher import NotificationDispatcher  # noqa: E402
from Business.notification_manager import NotificationManager  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Business.maximum_drawdown_engine import MaximumDrawdownEngine  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Business.portfolio_snapshot_service import PortfolioSnapshotService  # noqa: E402
from Business.reconciliation_engine import ReconciliationEngine  # noqa: E402
from Business.unrealized_pnl_engine import UnrealizedPnLEngine  # noqa: E402

from Core.bootstrap import (  # noqa: E402
    DEFAULT_CRYPTO_ACCOUNT_ID,
    DEFAULT_FOREX_ACCOUNT_ID,
    DEFAULT_PAPER_ACCOUNT_ID,
    DEFAULT_US_ACCOUNT_ID,
)
from Core.exceptions import ValidationError  # noqa: E402
from Core.init_command import run_init  # noqa: E402
from Core.init_crypto_command import run_init_crypto  # noqa: E402
from Core.init_forex_command import run_init_forex  # noqa: E402
from Core.init_us_command import run_init_us  # noqa: E402

from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402

from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_approval_repository import (  # noqa: E402
    OrderApprovalRepository,
)
from Repository.persistence.order_idempotency_repository import (  # noqa: E402
    OrderIdempotencyRepository,
)
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.portfolio_snapshot_repository import (  # noqa: E402
    PortfolioSnapshotRepository,
)
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.snapshot_repository import SnapshotRepository  # noqa: E402
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402
from Repository.persistence.watchlist_repository import WatchlistRepository  # noqa: E402

import main as cli  # noqa: E402

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
# Fixed, deterministic scenario data
# ---------------------------------------------------------------------------

FOREX_SYMBOL = "EUR/USD"
US_SYMBOL = "AAPL"
FOREX_BUY_ALLOCATION = "0.05"
FOREX_SELL_QUANTITY = "1000"
EXECUTED_AT = "2026-01-06T15:00:00+00:00"

FOREX_CURRENT_PRICE = 1.10
FOREX_PREVIOUS_PRICE = 1.09
BUY_STOP_LOSS = "1.0950"  # below entry -- valid LONG protective side
SELL_STOP_LOSS = "1.1050"  # above entry -- valid SHORT protective side

received_symbols: List[str] = []


def _fake_fetch_real_prices(symbol: str):
    """Deterministic stand-in for ``_fetch_real_prices`` -- the sole
    network boundary in this flow. Returns a fixed (current, previous)
    tuple for EUR/USD and AAPL; ``(None, None)`` for anything else.
    """
    received_symbols.append(symbol)
    if symbol == FOREX_SYMBOL:
        return FOREX_CURRENT_PRICE, FOREX_PREVIOUS_PRICE
    if symbol == US_SYMBOL:
        return 150.0, 149.0
    return None, None


# ---------------------------------------------------------------------------
# Minimal application namespace: real constructors only
# ---------------------------------------------------------------------------


class MinimalApp:
    """Duck-typed namespace exposing exactly the collaborators the CLI
    functions under test read from ``app``. Every attribute is a real,
    unmodified production object, built with its actual constructor --
    mirrors ``Tests/test_activation11_22_forex_market_routing.py``'s own
    ``MinimalApp``.
    """

    def __init__(self, database_manager: DatabaseManager) -> None:
        self.account_repository = AccountRepository(database_manager)
        self.watchlist_repository = WatchlistRepository(database_manager)
        self.position_repository = PositionRepository(database_manager)
        self.order_repository = OrderRepository(database_manager)
        self.trade_repository = TradeRepository(database_manager)
        self.snapshot_repository = SnapshotRepository(database_manager)
        self.portfolio_snapshot_repository = PortfolioSnapshotRepository(database_manager)
        order_idempotency_repository = OrderIdempotencyRepository(database_manager)
        order_approval_repository = OrderApprovalRepository(database_manager)

        self.market_price_tool = market_price_tool_module.MarketPriceTool()
        self.unrealized_pnl_engine = UnrealizedPnLEngine(self.market_price_tool)

        execution_policy = load_execution_policy()
        order_lifecycle_service = OrderLifecycleService(self.order_repository)
        execution_service = ExecutionService(self.order_repository, self.trade_repository, execution_policy)
        account_balance_service = AccountBalanceService(self.account_repository)
        position_manager = PositionManager(self.position_repository)

        notification_builder = NotificationBuilder()
        notification_dispatcher = NotificationDispatcher(channels=[])
        notification_manager = NotificationManager(notification_dispatcher)

        self.paper_trading_engine = PaperTradingEngine(
            order_lifecycle_service=order_lifecycle_service,
            execution_service=execution_service,
            account_repository=self.account_repository,
            position_repository=self.position_repository,
            order_idempotency_repository=order_idempotency_repository,
            kill_switch_engaged=False,
            max_order_value=1_000_000_000.0,
            execution_policy=execution_policy,
            account_balance_service=account_balance_service,
            position_manager=position_manager,
            notification_manager=notification_manager,
            notification_builder=notification_builder,
            order_approval_repository=order_approval_repository,
            halted_markets=frozenset(),
            halted_symbols=frozenset(),
            max_daily_loss=None,
            max_position_value=None,
        )

        maximum_drawdown_engine = MaximumDrawdownEngine()
        self.portfolio_snapshot_service = PortfolioSnapshotService(
            account_repository=self.account_repository,
            position_repository=self.position_repository,
            unrealized_pnl_engine=self.unrealized_pnl_engine,
            maximum_drawdown_engine=maximum_drawdown_engine,
            portfolio_snapshot_repository=self.portfolio_snapshot_repository,
        )

        self.reconciliation_engine = ReconciliationEngine(
            order_repository=self.order_repository,
            trade_repository=self.trade_repository,
            account_repository=self.account_repository,
            position_repository=self.position_repository,
        )


def _build_app(db_config: DatabaseConfig) -> MinimalApp:
    database = SQLiteDatabase(db_config)
    database.connect()
    database_manager = DatabaseManager(database, db_config)
    return MinimalApp(database_manager)


# ---------------------------------------------------------------------------
# submit_order spy -- narrow, call-through
# ---------------------------------------------------------------------------

submit_order_calls: List[dict] = []


def _install_submit_order_spy(engine: PaperTradingEngine):
    """Wrap (not replace) ``engine.submit_order`` so every call records
    the full keyword arguments (including ``stop_loss``) it was
    called with, then delegates to the real, unmodified bound method
    -- every one of ``PaperTradingEngine``'s real pre-trade gates
    still runs. Returns the original bound method so callers can
    restore it afterwards.
    """
    original = engine.submit_order

    def spy(self, **kwargs):
        submit_order_calls.append(dict(kwargs))
        return original(**kwargs)

    engine.submit_order = types.MethodType(spy, engine)
    return original


def _uninstall_submit_order_spy(engine: PaperTradingEngine, original) -> None:
    engine.submit_order = original


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------


def main() -> int:
    tmp_dir = tempfile.mkdtemp(prefix="activation11_23_forex_stop_loss_cli_")
    db_path = Path(tmp_dir) / "activation11_23_forex_stop_loss_cli.db"
    cfg = DatabaseConfig(db_path=db_path)

    previous_market_env = os.environ.get("AIOS_MARKET")
    original_fetch_real_prices = market_price_tool_module._fetch_real_prices

    try:
        # --- Setup: real init + init-us + init-crypto + init-forex, same DB
        print("=" * 70)
        print("[Setup] run_init()/run_init_us()/run_init_crypto()/run_init_forex()")
        print("=" * 70)
        check(run_init(db_config=cfg, print_fn=lambda s: None) == 0, "run_init() succeeded")
        check(run_init_us(db_config=cfg, print_fn=lambda s: None) == 0, "run_init_us() succeeded")
        check(run_init_crypto(db_config=cfg, print_fn=lambda s: None) == 0, "run_init_crypto() succeeded")
        check(run_init_forex(db_config=cfg, print_fn=lambda s: None) == 0, "run_init_forex() succeeded")

        app = _build_app(cfg)

        # Real, persisted "usable recommendation" snapshots for EUR/USD
        # and AAPL -- same pattern every other market's routing test in
        # this suite already uses.
        app.snapshot_repository.create(
            scan_time=EXECUTED_AT,
            symbol=FOREX_SYMBOL,
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
            status="success",
            evidence_summary="Forex scan: deterministic Activation 11.23 test fixture.",
        )
        app.snapshot_repository.create(
            scan_time=EXECUTED_AT,
            symbol=US_SYMBOL,
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
            status="success",
            evidence_summary="US scan: deterministic Activation 11.23 regression fixture.",
        )

        market_price_tool_module._fetch_real_prices = _fake_fetch_real_prices

        # --- Scenario A: BUY forwards stop-loss ----------------------------
        print("\n" + "=" * 70)
        print("[Scenario A] paper buy EUR/USD --market forex --stop-loss 1.0950")
        print("=" * 70)
        submit_order_calls.clear()
        original_submit_order = _install_submit_order_spy(app.paper_trading_engine)
        try:
            buy_rc = cli._run_paper_buy_command(
                app,
                [
                    FOREX_SYMBOL,
                    "--allocation",
                    FOREX_BUY_ALLOCATION,
                    "--market",
                    "forex",
                    "--executed-at",
                    EXECUTED_AT,
                    "--stop-loss",
                    BUY_STOP_LOSS,
                ],
            )
        finally:
            _uninstall_submit_order_spy(app.paper_trading_engine, original_submit_order)

        check(len(submit_order_calls) == 1, f"submit_order() called exactly once for BUY (found {len(submit_order_calls)})")
        if submit_order_calls:
            buy_call = submit_order_calls[-1]
            check(buy_call.get("stop_loss") == 1.0950, f"BUY forwarded stop_loss=1.0950 (found {buy_call.get('stop_loss')!r})")
            check(buy_call.get("account_id") == DEFAULT_FOREX_ACCOUNT_ID, "BUY resolved account_id == 'forex-usd'")
            check(buy_call.get("symbol") == FOREX_SYMBOL, "BUY submitted symbol == 'EUR/USD'")
            check(buy_call.get("action") == "BUY", "BUY submitted action == 'BUY'")
        check(buy_rc == 0, f"Forex BUY with a valid stop-loss succeeds end-to-end (rc={buy_rc})")

        # --- Scenario B: SELL forwards stop-loss ----------------------------
        print("\n" + "=" * 70)
        print("[Scenario B] paper sell EUR/USD --market forex --stop-loss 1.1050")
        print("=" * 70)
        submit_order_calls.clear()
        original_submit_order = _install_submit_order_spy(app.paper_trading_engine)
        try:
            sell_rc = cli._run_paper_sell_command(
                app,
                [
                    FOREX_SYMBOL,
                    "--quantity",
                    FOREX_SELL_QUANTITY,
                    "--market",
                    "forex",
                    "--executed-at",
                    EXECUTED_AT,
                    "--stop-loss",
                    SELL_STOP_LOSS,
                ],
            )
        finally:
            _uninstall_submit_order_spy(app.paper_trading_engine, original_submit_order)

        check(len(submit_order_calls) == 1, f"submit_order() called exactly once for SELL (found {len(submit_order_calls)})")
        if submit_order_calls:
            sell_call = submit_order_calls[-1]
            check(sell_call.get("stop_loss") == 1.1050, f"SELL forwarded stop_loss=1.1050 (found {sell_call.get('stop_loss')!r})")
            check(sell_call.get("account_id") == DEFAULT_FOREX_ACCOUNT_ID, "SELL resolved account_id == 'forex-usd'")
            check(sell_call.get("symbol") == FOREX_SYMBOL, "SELL submitted symbol == 'EUR/USD'")
            check(sell_call.get("action") == "SELL", "SELL submitted action == 'SELL'")
        # This SELL has no open position of the correct direction --
        # it is acceptable/expected for it to fail on a different,
        # already-known business rule (per roadmap "PRODUCTION E2E
        # EXPECTATION"); this scenario only asserts forwarding.
        check(sell_rc in (0, 1), f"Forex SELL command returns a clean exit code (rc={sell_rc})")

        # --- Scenario C: missing stop remains None (non-Forex) --------------
        print("\n" + "=" * 70)
        print("[Scenario C] paper buy AAPL --market us (no --stop-loss)")
        print("=" * 70)
        submit_order_calls.clear()
        original_submit_order = _install_submit_order_spy(app.paper_trading_engine)
        try:
            us_rc = cli._run_paper_buy_command(
                app,
                [US_SYMBOL, "--allocation", "0.01", "--market", "us", "--executed-at", EXECUTED_AT],
            )
        finally:
            _uninstall_submit_order_spy(app.paper_trading_engine, original_submit_order)

        check(us_rc == 0, "US paper buy without --stop-loss still succeeds")
        check(len(submit_order_calls) == 1, f"submit_order() called exactly once for US BUY (found {len(submit_order_calls)})")
        if submit_order_calls:
            us_call = submit_order_calls[-1]
            check(us_call.get("stop_loss") is None, f"missing --stop-loss forwards stop_loss=None (found {us_call.get('stop_loss')!r})")
            check(us_call.get("account_id") == DEFAULT_US_ACCOUNT_ID, "US BUY resolved account_id == 'us-usd'")

        # --- Scenario D: invalid stop input rejected before submit_order ----
        print("\n" + "=" * 70)
        print("[Scenario D] paper buy EUR/USD --market forex --stop-loss not-a-number")
        print("=" * 70)
        submit_order_calls.clear()
        original_submit_order = _install_submit_order_spy(app.paper_trading_engine)
        try:
            invalid_rc = cli._run_paper_buy_command(
                app,
                [
                    FOREX_SYMBOL,
                    "--allocation",
                    FOREX_BUY_ALLOCATION,
                    "--market",
                    "forex",
                    "--executed-at",
                    EXECUTED_AT,
                    "--stop-loss",
                    "not-a-number",
                ],
            )
        finally:
            _uninstall_submit_order_spy(app.paper_trading_engine, original_submit_order)

        check(invalid_rc == 1, "invalid --stop-loss value exits 1")
        check(len(submit_order_calls) == 0, "submit_order() was NOT called for an invalid --stop-loss value")

        # Also confirm this on the SELL side.
        submit_order_calls.clear()
        original_submit_order = _install_submit_order_spy(app.paper_trading_engine)
        try:
            invalid_sell_rc = cli._run_paper_sell_command(
                app,
                [
                    FOREX_SYMBOL,
                    "--quantity",
                    FOREX_SELL_QUANTITY,
                    "--market",
                    "forex",
                    "--executed-at",
                    EXECUTED_AT,
                    "--stop-loss",
                    "abc",
                ],
            )
        finally:
            _uninstall_submit_order_spy(app.paper_trading_engine, original_submit_order)

        check(invalid_sell_rc == 1, "invalid --stop-loss value on SELL exits 1")
        check(len(submit_order_calls) == 0, "submit_order() was NOT called for an invalid SELL --stop-loss value")

        # --- Scenario E: --executed-at compatibility (already exercised
        # inline above in Scenario A/B, both flags supplied together) ------
        print("\n" + "=" * 70)
        print("[Scenario E] --executed-at and --stop-loss both forwarded correctly")
        print("=" * 70)
        submit_order_calls.clear()
        original_submit_order = _install_submit_order_spy(app.paper_trading_engine)
        try:
            combo_rc = cli._run_paper_buy_command(
                app,
                [
                    FOREX_SYMBOL,
                    "--allocation",
                    "0.01",
                    "--market",
                    "forex",
                    "--executed-at",
                    EXECUTED_AT,
                    "--stop-loss",
                    BUY_STOP_LOSS,
                ],
            )
        finally:
            _uninstall_submit_order_spy(app.paper_trading_engine, original_submit_order)
        check(len(submit_order_calls) == 1, "submit_order() called exactly once for the combo scenario")
        if submit_order_calls:
            combo_call = submit_order_calls[-1]
            check(combo_call.get("executed_at") == EXECUTED_AT, "combo scenario forwarded the exact --executed-at value")
            check(combo_call.get("stop_loss") == 1.0950, "combo scenario forwarded the exact --stop-loss value")
        check(combo_rc == 0, f"combo BUY (valid --executed-at + --stop-loss) succeeds (rc={combo_rc})")

        # --- Scenario F: AIOS_MARKET restoration -----------------------------
        print("\n" + "=" * 70)
        print("[Scenario F] AIOS_MARKET restoration across success/reject/exception")
        print("=" * 70)

        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            "AIOS_MARKET restored after the successful Forex BUY (Scenario A)",
        )

        # rejected path (Scenario D, invalid stop-loss)
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            "AIOS_MARKET restored after the rejected (invalid stop-loss) Forex BUY",
        )

        # exception path
        def _raise_boom(**kwargs):
            raise RuntimeError("boom -- simulated unexpected failure")

        original_submit_order = app.paper_trading_engine.submit_order
        app.paper_trading_engine.submit_order = _raise_boom
        try:
            try:
                cli._run_paper_buy_command(
                    app,
                    [
                        FOREX_SYMBOL,
                        "--allocation",
                        FOREX_BUY_ALLOCATION,
                        "--market",
                        "forex",
                        "--executed-at",
                        EXECUTED_AT,
                        "--stop-loss",
                        BUY_STOP_LOSS,
                    ],
                )
                check(False, "expected RuntimeError to propagate out of _run_paper_buy_command")
            except RuntimeError:
                check(True, "RuntimeError propagated (submit_order's own failure is not swallowed)")
        finally:
            app.paper_trading_engine.submit_order = original_submit_order
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            "AIOS_MARKET restored to its original value even after an unhandled exception",
        )

        # --- Scenario G: existing regression (11.22 market routing) --------
        print("\n" + "=" * 70)
        print("[Scenario G] Activation 11.22 regression re-run")
        print("=" * 70)
        import subprocess

        result = subprocess.run(
            [sys.executable, str(_PROJECT_ROOT / "Tests" / "test_activation11_22_forex_market_routing.py")],
            capture_output=True,
            text=True,
        )
        check(result.returncode == 0, "test_activation11_22_forex_market_routing.py exits 0 (unaffected by this step)")
        if result.returncode != 0:
            print(result.stdout[-3000:])
            print(result.stderr[-3000:])

    finally:
        market_price_tool_module._fetch_real_prices = original_fetch_real_prices
        if previous_market_env is None:
            os.environ.pop("AIOS_MARKET", None)
        else:
            os.environ["AIOS_MARKET"] = previous_market_env

    print("\n" + "=" * 70)
    print(f"RESULT: {_PASS} passed, {_FAIL} failed")
    print("=" * 70)
    if _FAILURES:
        print("\nFailed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())