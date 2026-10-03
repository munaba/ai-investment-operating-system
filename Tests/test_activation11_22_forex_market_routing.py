"""Activation 11.22 -- Forex market routing (``--market forex``).

Exercises the real CLI functions in ``main.py`` (``_configure_cli_market``,
``_run_paper_buy_command``, ``_run_paper_sell_command``) against one
temporary SQLite database, proving ``--market forex`` now reaches the
already-tested ``PaperTradingEngine`` Forex path instead of dying
immediately with ``"Unsupported market"`` -- and that IDX/US/Crypto
routing, and the existing Forex pair-universe validation, are all
unaffected.

This step is market-context/account-routing ONLY (Activation 11
roadmap "Activation awal": analysis / paper forex / no leverage live /
no autonomous execution). It deliberately does NOT add ``--stop-loss``
to the CLI, so a real Forex BUY/SELL submitted through this step is
EXPECTED to still be rejected by ``PaperTradingEngine``'s own,
pre-existing Forex-stop-loss gate (``PRETRADE_REASON_FOREX_STOP_LOSS_
REQUIRED``) -- that rejection is itself the proof the order reached
the real Forex business path (a structurally different failure than
the pre-Activation-11.22 ``"Unsupported market: 'forex'"`` CLI-layer
rejection this step removes).

Boundary spied (not replaced): ``PaperTradingEngine.submit_order`` is
wrapped (not stubbed) so this test can capture the exact
``account_id``/``symbol``/``action`` it was called with, and the
``AIOS_MARKET`` value active at call time, while still calling straight
through to the real, unmodified method underneath -- so every one of
its real 17 pre-trade gates still runs for real. This is the "narrow
spy" the roadmap step explicitly permits.

Boundary mocked (module-level, network only, mirrors every other
``Tests/test_activation1*_*_paper_workflow.py`` file in this suite):
``Orchestration.market_price_tool._fetch_real_prices``.

Nothing else is mocked. In particular, never mocked: AccountRepository,
OrderRepository, TradeRepository, PositionRepository,
SnapshotRepository, PaperTradingEngine, ExecutionService,
OrderLifecycleService, ReconciliationEngine.

Run directly: ``python Tests/test_activation11_22_forex_market_routing.py``
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
from Business.paper_trading_engine import (  # noqa: E402
    PRETRADE_REASON_FOREX_STOP_LOSS_REQUIRED,
    PaperTradingEngine,
)
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
UNSUPPORTED_FOREX_SYMBOL = "USD/JPY"  # well-formed, but NOT in
                                       # Business.forex_pip_policy.SUPPORTED_PIP_VALUE_PAIRS
US_SYMBOL = "AAPL"
CRYPTO_SYMBOL = "BTC-USD"
IDX_SYMBOL = "BBCA"

FOREX_CURRENT_PRICE = 1.10
FOREX_PREVIOUS_PRICE = 1.09
FOREX_BUY_ALLOCATION = "0.05"
FOREX_SELL_QUANTITY = "1000"
EXECUTED_AT = "2026-01-06T15:00:00+00:00"

received_symbols: List[str] = []


def _fake_fetch_real_prices(symbol: str):
    """Deterministic stand-in for ``_fetch_real_prices`` -- the sole
    network boundary in this flow. Records every symbol it is called
    with and returns a fixed (current, previous) tuple for the exact
    Forex pair under test; ``(None, None)`` for anything else (matches
    every other market's price fixture in this test suite -- IDX/US/
    Crypto regression scenarios below never rely on a real price, they
    only assert routing/rejection behavior that does not require one).
    """
    received_symbols.append(symbol)
    if symbol == FOREX_SYMBOL:
        return FOREX_CURRENT_PRICE, FOREX_PREVIOUS_PRICE
    return None, None


# ---------------------------------------------------------------------------
# Minimal application namespace: real constructors only
# ---------------------------------------------------------------------------


class MinimalApp:
    """Duck-typed namespace exposing exactly the collaborators the CLI
    functions under test read from ``app``. Every attribute is a real,
    unmodified production object, built with its actual constructor --
    mirrors ``Tests/test_activation10_1_crypto_paper_workflow.py``'s own
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
# submit_order spy -- narrow, call-through (Requirement: "prove the
# actual CLI command routing, not merely call a helper in isolation";
# "acceptable to spy at the final boundary: PaperTradingEngine.
# submit_order(), but the test must execute the real command-routing
# logic").
# ---------------------------------------------------------------------------

submit_order_calls: List[dict] = []


def _install_submit_order_spy(engine: PaperTradingEngine):
    """Wrap (not replace) ``engine.submit_order`` so every call records
    ``account_id``/``symbol``/``action`` and the ``AIOS_MARKET`` value
    active at call time, then delegates to the real, unmodified bound
    method -- every one of ``PaperTradingEngine``'s real pre-trade
    gates still runs. Returns the original bound method so callers can
    restore it afterwards.
    """
    original = engine.submit_order

    def spy(self, **kwargs):
        submit_order_calls.append(
            {
                "account_id": kwargs.get("account_id"),
                "symbol": kwargs.get("symbol"),
                "action": kwargs.get("action"),
                "aios_market": os.environ.get("AIOS_MARKET"),
            }
        )
        return original(**kwargs)

    engine.submit_order = types.MethodType(spy, engine)
    return original


def _uninstall_submit_order_spy(engine: PaperTradingEngine, original) -> None:
    engine.submit_order = original


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------


def main() -> int:
    tmp_dir = tempfile.mkdtemp(prefix="activation11_22_forex_routing_")
    db_path = Path(tmp_dir) / "activation11_22_forex_routing.db"
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

        forex_account_before = app.account_repository.get_by_id(DEFAULT_FOREX_ACCOUNT_ID)
        idx_account_before = app.account_repository.get_by_id(DEFAULT_PAPER_ACCOUNT_ID)
        check(forex_account_before is not None, "forex-usd account exists after init-forex")
        check(idx_account_before is not None, "IDX 'paper' account exists after init")
        idx_cash_before = idx_account_before.cash if idx_account_before else None

        # Prerequisite: a real, persisted "usable recommendation" for
        # EUR/USD, written through the real SnapshotRepository.create()
        # -- same pattern every other market's routing test in this
        # suite already uses (Forex scan/analysis wiring is out of
        # scope for this atomic step).
        app.snapshot_repository.create(
            scan_time=EXECUTED_AT,
            symbol=FOREX_SYMBOL,
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
            status="success",
            evidence_summary="Forex scan: deterministic Activation 11.22 test fixture.",
        )
        forex_snapshot = cli._latest_snapshot_for_symbol(app, FOREX_SYMBOL)
        check(
            forex_snapshot is not None and forex_snapshot.status == "success",
            "a usable EUR/USD RankingSnapshot is resolvable before any order is placed",
        )

        # Patch ONLY the network boundary for the scenario's duration.
        market_price_tool_module._fetch_real_prices = _fake_fetch_real_prices

        # --- I. Unsupported Forex pair rejected cleanly, no gate reached --
        print("\n" + "=" * 70)
        print("[Test I] paper buy USD/JPY --market forex -> rejected cleanly")
        print("=" * 70)
        forex_orders_before_unsupported = app.order_repository.list_by_account(DEFAULT_FOREX_ACCOUNT_ID)
        unsupported_rc = cli._run_paper_buy_command(
            app,
            [UNSUPPORTED_FOREX_SYMBOL, "--allocation", FOREX_BUY_ALLOCATION, "--market", "forex"],
        )
        check(unsupported_rc == 1, "unsupported Forex pair BUY exits 1")
        forex_orders_after_unsupported = app.order_repository.list_by_account(DEFAULT_FOREX_ACCOUNT_ID)
        check(
            len(forex_orders_after_unsupported) == len(forex_orders_before_unsupported),
            "unsupported Forex pair BUY writes no Order",
        )
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            "AIOS_MARKET restored after a rejected (unsupported-pair) Forex order",
        )

        # --- A. --market forex is accepted (dispatch-level gate) ----------
        print("\n" + "=" * 70)
        print("[Test A] _configure_cli_market accepts 'forex'")
        print("=" * 70)
        check(
            cli._configure_cli_market(["--market", "forex"]) == 0,
            "main._configure_cli_market(['--market', 'forex']) returns 0 (accepted)",
        )
        os.environ["AIOS_MARKET"] = previous_market_env if previous_market_env is not None else "idx"
        if previous_market_env is None:
            os.environ.pop("AIOS_MARKET", None)

        # --- B/C/D/E(rejected). paper buy EUR/USD --market forex ----------
        print("\n" + "=" * 70)
        print("[Test B/C/D] paper buy EUR/USD --allocation 0.05 --market forex")
        print("=" * 70)
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
                ],
            )
        finally:
            _uninstall_submit_order_spy(app.paper_trading_engine, original_submit_order)

        check(
            buy_rc == 1,
            "paper buy EUR/USD ... --market forex exits 1 -- EXPECTED (no --stop-loss "
            "wired yet; PaperTradingEngine's own Forex stop-loss gate rejects it)",
        )
        check(
            FOREX_SYMBOL in received_symbols,
            f"the price boundary was reached for 'EUR/USD' (received: {received_symbols}) -- "
            "proves the command reached the Forex business path, not an immediate "
            "'Unsupported market' CLI-layer rejection",
        )
        check(len(submit_order_calls) == 1, f"submit_order() was called exactly once (found {len(submit_order_calls)})")
        if submit_order_calls:
            buy_call = submit_order_calls[-1]
            check(
                buy_call["account_id"] == DEFAULT_FOREX_ACCOUNT_ID,
                f"Forex BUY resolved account_id == 'forex-usd' before submission (found "
                f"{buy_call['account_id']!r}) -- Test B",
            )
            check(
                buy_call["symbol"] == FOREX_SYMBOL,
                f"Forex BUY submitted symbol == 'EUR/USD' (found {buy_call['symbol']!r})",
            )
            check(buy_call["action"] == "BUY", f"Forex BUY submitted action == 'BUY' (found {buy_call['action']!r})")
            check(
                buy_call["aios_market"] == "forex",
                f"AIOS_MARKET == 'forex' during submit_order() -- Test D (found {buy_call['aios_market']!r})",
            )

        forex_orders_after_buy = app.order_repository.list_by_account(DEFAULT_FOREX_ACCOUNT_ID)
        check(
            len(forex_orders_after_buy) == len(forex_orders_before_unsupported),
            "the rejected Forex BUY (missing stop-loss) wrote no persisted Order",
        )
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            "AIOS_MARKET restored after the rejected (missing-stop-loss) Forex BUY -- Test E",
        )

        # Confirm *why* it was rejected -- the real, unmodified Forex
        # stop-loss gate, not a generic/unrelated failure -- by calling
        # the real engine directly with the exact same shape the CLI
        # used (no stop_loss kwarg), proving the rejection reason.
        try:
            app.paper_trading_engine.submit_order(
                account_id=DEFAULT_FOREX_ACCOUNT_ID,
                symbol=FOREX_SYMBOL,
                action="BUY",
                quantity=1000.0,
                requested_price=FOREX_CURRENT_PRICE,
                executed_at=EXECUTED_AT,
                signal_evidence=forex_snapshot,
                user_approval=True,
                idempotency_key="test-forex-stop-loss-reason-check",
            )
            check(False, "direct submit_order() without stop_loss should have raised ValidationError")
        except ValidationError as exc:
            check(
                exc.details.get("reason") == PRETRADE_REASON_FOREX_STOP_LOSS_REQUIRED,
                f"rejection reason is FOREX_STOP_LOSS_REQUIRED, the real PaperTradingEngine "
                f"Forex gate (found {exc.details.get('reason')!r})",
            )

        # --- B/C/D/E(rejected). paper sell EUR/USD --market forex ---------
        print("\n" + "=" * 70)
        print("[Test B/C/D] paper sell EUR/USD --quantity 1000 --market forex")
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
                ],
            )
        finally:
            _uninstall_submit_order_spy(app.paper_trading_engine, original_submit_order)

        check(
            sell_rc == 1,
            "paper sell EUR/USD ... --market forex exits 1 -- EXPECTED (no open Forex "
            "position exists, and no --stop-loss is wired yet)",
        )
        check(len(submit_order_calls) == 1, f"submit_order() was called exactly once for SELL (found {len(submit_order_calls)})")
        if submit_order_calls:
            sell_call = submit_order_calls[-1]
            check(
                sell_call["account_id"] == DEFAULT_FOREX_ACCOUNT_ID,
                f"Forex SELL resolved account_id == 'forex-usd' before submission (found "
                f"{sell_call['account_id']!r}) -- Test C",
            )
            check(
                sell_call["symbol"] == FOREX_SYMBOL,
                f"Forex SELL submitted symbol == 'EUR/USD' (found {sell_call['symbol']!r})",
            )
            check(sell_call["action"] == "SELL", f"Forex SELL submitted action == 'SELL' (found {sell_call['action']!r})")
            check(
                sell_call["aios_market"] == "forex",
                f"AIOS_MARKET == 'forex' during SELL submit_order() -- Test D (found {sell_call['aios_market']!r})",
            )
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            "AIOS_MARKET restored after the rejected Forex SELL",
        )

        # --- E(exception path). AIOS_MARKET restored even on an
        # unexpected (non-ValidationError) exception from submit_order --
        print("\n" + "=" * 70)
        print("[Test E] AIOS_MARKET restored even if submit_order() raises unexpectedly")
        print("=" * 70)

        def _raise_boom(**kwargs):
            raise RuntimeError("boom -- simulated unexpected failure")

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
                    ],
                )
                check(False, "expected RuntimeError to propagate out of _run_paper_buy_command")
            except RuntimeError:
                check(True, "RuntimeError propagated (submit_order's own failure is not swallowed)")
        finally:
            app.paper_trading_engine.submit_order = original_submit_order
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            "AIOS_MARKET restored to its original value even after an unhandled "
            "exception from submit_order() -- 'finally' contract holds -- Test E",
        )

        # --- F/G/H. IDX/US/Crypto regression -------------------------------
        print("\n" + "=" * 70)
        print("[Test F/G/H] IDX/US/Crypto --market routing is unchanged")
        print("=" * 70)
        check(
            cli._configure_cli_market(["--market", "idx"]) == 0,
            "_configure_cli_market(['--market', 'idx']) still returns 0 -- Test F",
        )
        check(
            cli._configure_cli_market(["--market", "us"]) == 0,
            "_configure_cli_market(['--market', 'us']) still returns 0 -- Test G",
        )
        check(
            cli._configure_cli_market(["--market", "crypto"]) == 0,
            "_configure_cli_market(['--market', 'crypto']) still returns 0 -- Test H",
        )
        os.environ["AIOS_MARKET"] = previous_market_env if previous_market_env is not None else "idx"
        if previous_market_env is None:
            os.environ.pop("AIOS_MARKET", None)

        # A still-unsupported top-level market is still rejected exactly
        # as before this Activation (proves the allowlist widening did
        # not accidentally become "accept anything").
        bogus_rc = cli._configure_cli_market(["--market", "bogus"])
        check(bogus_rc == 1, "_configure_cli_market(['--market', 'bogus']) still rejects an unknown market")

        # US paper buy/sell routing (account_id == 'us-usd') still works,
        # untouched by this step's Forex-only additions -- reuses the
        # real US account already created by init-us above.
        app.snapshot_repository.create(
            scan_time=EXECUTED_AT,
            symbol=US_SYMBOL,
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
            status="success",
            evidence_summary="US scan: deterministic Activation 11.22 regression fixture.",
        )

        def _fake_fetch_with_us(symbol: str):
            received_symbols.append(symbol)
            if symbol == US_SYMBOL:
                return 150.0, 149.0
            if symbol == FOREX_SYMBOL:
                return FOREX_CURRENT_PRICE, FOREX_PREVIOUS_PRICE
            return None, None

        market_price_tool_module._fetch_real_prices = _fake_fetch_with_us

        us_rc = cli._run_paper_buy_command(
            app,
            [US_SYMBOL, "--allocation", "0.01", "--market", "us", "--executed-at", EXECUTED_AT],
        )
        check(us_rc == 0, "US paper buy still succeeds -- Test G regression")
        us_orders = app.order_repository.list_by_account(DEFAULT_US_ACCOUNT_ID)
        check(len(us_orders) == 1, f"exactly 1 Order exists under 'us-usd' (found {len(us_orders)})")
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            "AIOS_MARKET restored after the successful US BUY -- Test E (successful path)",
        )

        # --- Isolation: the Forex account/order activity never touched
        # the IDX 'paper' account.
        idx_orders_after = app.order_repository.list_by_account(DEFAULT_PAPER_ACCOUNT_ID)
        idx_account_after = app.account_repository.get_by_id(DEFAULT_PAPER_ACCOUNT_ID)
        check(len(idx_orders_after) == 0, "no order was written to the IDX 'paper' account by any Forex activity")
        check(
            idx_account_after is not None and idx_account_after.cash == idx_cash_before,
            "IDX 'paper' cash unchanged by any Forex activity",
        )

        forex_account_after = app.account_repository.get_by_id(DEFAULT_FOREX_ACCOUNT_ID)
        check(
            forex_account_after is not None and forex_account_after.cash == forex_account_before.cash,
            "forex-usd cash unchanged -- no Forex order in this step ever actually executed "
            "(all rejected pre-stop-loss, as expected)",
        )

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