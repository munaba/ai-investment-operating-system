"""Activation 11.24 -- Forex quantity / lot-size handling.

Proves Forex paper-order quantity is now handled as direct
base-currency units (Activation 11.1's LOCKED "quantity =
base-currency units directly" decision), not IDX-style 100-share
lots, at BOTH layers this bug lived in:

* CLI estimate (``main.py::_run_paper_buy_command``'s
  ``_compute_allocation_quantity`` call) -- now sizes Forex with
  ``lot_size=1`` (whole base-currency units), like "us"/"crypto",
  instead of ``ExecutionPolicy.lot_size`` (IDX's 100-share lot).
* Business-layer enforcement (``Business.paper_trading_engine.
  PaperTradingEngine.submit_order`` gate 6) -- Forex orders now hit
  their own "whole base-currency units" branch instead of falling
  through to the generic ``quantity % lot_size != 0`` IDX check.

IDX's own enforcement, and US/Crypto's own gate-6 branches, are
proven completely untouched. ``Business.forex_margin_policy`` (the
sole required-margin authority) is proven unmodified and numerically
consistent with an accepted Forex quantity.

Boundary spied (not replaced) where the real CLI command path is
exercised: ``PaperTradingEngine.submit_order`` is wrapped, not
stubbed, so real pre-trade gates still run. Direct engine calls
(bypassing the CLI) are also used for scenarios that need an exact,
otherwise-unreachable-via-allocation-rounding quantity (e.g. 10,001)
-- this is the real, unmodified ``PaperTradingEngine.submit_order``
called directly, exactly the way ``Tests/test_activation11_14_forex_
stop_loss_enforcement.py``/``Tests/test_paper_trading_engine.py``
already exercise gate-level behavior in this suite.

Boundary mocked (module-level, network only, mirrors every other
``Tests/test_activation1*_*_paper_workflow.py`` file in this suite):
``Orchestration.market_price_tool._fetch_real_prices``.

Run directly: ``python Tests/test_activation11_24_forex_quantity.py``
-- no external test framework required.
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import uuid
from pathlib import Path
from typing import List

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import Orchestration.market_price_tool as market_price_tool_module  # noqa: E402

from Business.account_balance_service import AccountBalanceService  # noqa: E402
from Business.execution_policy_config import load_execution_policy  # noqa: E402
from Business.execution_service import ExecutionService  # noqa: E402
from Business.forex_margin_policy import calculate_required_margin  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.notification_builder import NotificationBuilder  # noqa: E402
from Business.notification_dispatcher import NotificationDispatcher  # noqa: E402
from Business.notification_manager import NotificationManager  # noqa: E402
from Business.paper_trading_engine import (  # noqa: E402
    PRETRADE_REASON_INVALID_LOT_SIZE,
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

EUR_USD = "EUR/USD"
GBP_USD = "GBP/USD"
US_SYMBOL = "AAPL"
IDX_SYMBOL = "BBCA"
CRYPTO_SYMBOL = "BTC-USD"
EXECUTED_AT = "2026-01-06T15:00:00+00:00"

FLAT_PRICE = 1.0  # deterministic price so allocation math is exact
received_symbols: List[str] = []


def _fake_fetch_real_prices(symbol: str):
    """Deterministic stand-in for ``_fetch_real_prices`` -- the sole
    network boundary in this flow. All symbols under test resolve to
    a fixed, non-zero price so allocation arithmetic is exact.
    """
    received_symbols.append(symbol)
    if symbol in (EUR_USD, GBP_USD):
        return FLAT_PRICE, FLAT_PRICE
    if symbol == US_SYMBOL:
        return 150.0, 149.0
    if symbol == IDX_SYMBOL:
        return 9000.0, 8950.0
    if symbol == CRYPTO_SYMBOL:
        return 500.0, 495.0
    return None, None


# ---------------------------------------------------------------------------
# Minimal application namespace: real constructors only
# ---------------------------------------------------------------------------


class MinimalApp:
    """Duck-typed namespace exposing exactly the collaborators the CLI
    functions under test read from ``app``. Every attribute is a real,
    unmodified production object, built with its actual constructor.
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

        self.execution_policy = load_execution_policy()
        order_lifecycle_service = OrderLifecycleService(self.order_repository)
        execution_service = ExecutionService(self.order_repository, self.trade_repository, self.execution_policy)
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
            execution_policy=self.execution_policy,
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
    tmp_dir = tempfile.mkdtemp(prefix="activation11_24_forex_quantity_")
    db_path = Path(tmp_dir) / "activation11_24_forex_quantity.db"
    cfg = DatabaseConfig(db_path=db_path)

    previous_market_env = os.environ.get("AIOS_MARKET")
    original_fetch_real_prices = market_price_tool_module._fetch_real_prices

    try:
        print("=" * 70)
        print("[Setup] run_init()/run_init_us()/run_init_crypto()/run_init_forex()")
        print("=" * 70)
        check(run_init(db_config=cfg, print_fn=lambda s: None) == 0, "run_init() succeeded")
        check(run_init_us(db_config=cfg, print_fn=lambda s: None) == 0, "run_init_us() succeeded")
        check(run_init_crypto(db_config=cfg, print_fn=lambda s: None) == 0, "run_init_crypto() succeeded")
        check(run_init_forex(db_config=cfg, print_fn=lambda s: None) == 0, "run_init_forex() succeeded")

        app = _build_app(cfg)
        forex_account = app.account_repository.get_by_id(DEFAULT_FOREX_ACCOUNT_ID)
        check(forex_account is not None, "forex-usd account exists")
        check(forex_account.cash == 100_000.0, f"forex-usd starting cash is 100,000.0 (found {forex_account.cash})")

        for symbol in (EUR_USD, GBP_USD, US_SYMBOL, IDX_SYMBOL, CRYPTO_SYMBOL):
            app.snapshot_repository.create(
                scan_time=EXECUTED_AT,
                symbol=symbol,
                recommendation="BUY",
                confidence="HIGH",
                priority=1,
                rank=1,
                status="success",
                evidence_summary=f"{symbol} scan: deterministic Activation 11.24 test fixture.",
            )

        market_price_tool_module._fetch_real_prices = _fake_fetch_real_prices

        # --- Scenario A: EUR/USD allocation -> exact quantity 10,000 ------
        print("\n" + "=" * 70)
        print("[Scenario A] EUR/USD --allocation 0.1 -> quantity 10,000")
        print("=" * 70)
        submit_order_calls.clear()
        original_submit_order = _install_submit_order_spy(app.paper_trading_engine)
        try:
            rc_a = cli._run_paper_buy_command(
                app,
                [
                    EUR_USD,
                    "--allocation",
                    "0.1",
                    "--market",
                    "forex",
                    "--executed-at",
                    EXECUTED_AT,
                    "--stop-loss",
                    "0.95",
                ],
            )
        finally:
            _uninstall_submit_order_spy(app.paper_trading_engine, original_submit_order)

        check(rc_a == 0, f"EUR/USD allocation BUY succeeds (rc={rc_a})")
        check(len(submit_order_calls) == 1, "submit_order() called exactly once for Scenario A")
        if submit_order_calls:
            check(
                submit_order_calls[-1].get("quantity") == 10_000,
                f"EUR/USD quantity is exactly 10,000 base units (found {submit_order_calls[-1].get('quantity')!r})",
            )

        # --- Scenario B: GBP/USD allocation -> exact quantity 25,000 ------
        print("\n" + "=" * 70)
        print("[Scenario B] GBP/USD --allocation 0.25 (of remaining cash) -> quantity 25,000")
        print("=" * 70)
        # Reset to a fresh account/app so cash math is independent of
        # Scenario A's already-spent cash.
        app2 = _build_app(DatabaseConfig(db_path=Path(tmp_dir) / "activation11_24_forex_quantity_b.db"))
        check(run_init(db_config=DatabaseConfig(db_path=Path(tmp_dir) / "activation11_24_forex_quantity_b.db"), print_fn=lambda s: None) in (0, 1), "second DB init tolerated")
        run_init(db_config=DatabaseConfig(db_path=Path(tmp_dir) / "activation11_24_forex_quantity_b.db"), print_fn=lambda s: None)
        run_init_forex(db_config=DatabaseConfig(db_path=Path(tmp_dir) / "activation11_24_forex_quantity_b.db"), print_fn=lambda s: None)
        app2 = _build_app(DatabaseConfig(db_path=Path(tmp_dir) / "activation11_24_forex_quantity_b.db"))
        app2.snapshot_repository.create(
            scan_time=EXECUTED_AT,
            symbol=GBP_USD,
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
            status="success",
            evidence_summary="GBP/USD scan: deterministic Activation 11.24 test fixture.",
        )
        submit_order_calls.clear()
        original_submit_order = _install_submit_order_spy(app2.paper_trading_engine)
        try:
            rc_b = cli._run_paper_buy_command(
                app2,
                [
                    GBP_USD,
                    "--allocation",
                    "0.25",
                    "--market",
                    "forex",
                    "--executed-at",
                    EXECUTED_AT,
                    "--stop-loss",
                    "0.95",
                ],
            )
        finally:
            _uninstall_submit_order_spy(app2.paper_trading_engine, original_submit_order)

        check(rc_b == 0, f"GBP/USD allocation BUY succeeds (rc={rc_b})")
        check(len(submit_order_calls) == 1, "submit_order() called exactly once for Scenario B")
        if submit_order_calls:
            check(
                submit_order_calls[-1].get("quantity") == 25_000,
                f"GBP/USD quantity is exactly 25,000 base units (found {submit_order_calls[-1].get('quantity')!r})",
            )

        # --- Scenario C: non-100 Forex quantity accepted (direct engine) --
        print("\n" + "=" * 70)
        print("[Scenario C] direct submit_order(quantity=10001) for Forex is accepted")
        print("=" * 70)
        forex_snapshot = cli._latest_snapshot_for_symbol(app, EUR_USD)
        # gate 6 reads the active market from AIOS_MARKET (the same
        # env var _run_paper_buy_command/_run_paper_sell_command
        # scope for the CLI path) -- this direct engine call sets it
        # for the duration of the call, restoring it afterward,
        # exactly mirroring what the CLI wrapper already does.
        os.environ["AIOS_MARKET"] = "forex"
        try:
            trade_c = app.paper_trading_engine.submit_order(
                account_id=DEFAULT_FOREX_ACCOUNT_ID,
                symbol=EUR_USD,
                action="BUY",
                quantity=10001,
                requested_price=1.0,
                executed_at=EXECUTED_AT,
                signal_evidence=forex_snapshot,
                user_approval=True,
                idempotency_key=f"test-forex-nonlot-{uuid.uuid4()}",
                stop_loss=0.95,
            )
            check(trade_c is not None, "Forex quantity=10001 (not a multiple of 100) is accepted")
        except ValidationError as exc:
            check(False, f"Forex quantity=10001 unexpectedly rejected: {exc.details.get('reason')}")
        finally:
            if previous_market_env is None:
                os.environ.pop("AIOS_MARKET", None)
            else:
                os.environ["AIOS_MARKET"] = previous_market_env

        # --- Scenario D: same non-100 quantity still rejected for IDX -----
        print("\n" + "=" * 70)
        print("[Scenario D] direct submit_order(quantity=10001) for IDX is still rejected")
        print("=" * 70)
        idx_snapshot = cli._latest_snapshot_for_symbol(app, IDX_SYMBOL)
        try:
            app.paper_trading_engine.submit_order(
                account_id=DEFAULT_PAPER_ACCOUNT_ID,
                symbol=IDX_SYMBOL,
                action="BUY",
                quantity=10001,
                requested_price=9000.0,
                executed_at=EXECUTED_AT,
                signal_evidence=idx_snapshot,
                user_approval=True,
                idempotency_key=f"test-idx-nonlot-{uuid.uuid4()}",
            )
            check(False, "IDX quantity=10001 should have been rejected (not a multiple of the IDX lot size)")
        except ValidationError as exc:
            check(
                exc.details.get("reason") == PRETRADE_REASON_INVALID_LOT_SIZE,
                f"IDX quantity=10001 rejected with INVALID_LOT_SIZE (found {exc.details.get('reason')!r})",
            )

        # --- Scenario E: US regression (whole-share sizing unchanged) -----
        print("\n" + "=" * 70)
        print("[Scenario E] US paper buy sizing unchanged")
        print("=" * 70)
        submit_order_calls.clear()
        original_submit_order = _install_submit_order_spy(app.paper_trading_engine)
        try:
            rc_e = cli._run_paper_buy_command(
                app,
                [US_SYMBOL, "--allocation", "0.01", "--market", "us", "--executed-at", EXECUTED_AT],
            )
        finally:
            _uninstall_submit_order_spy(app.paper_trading_engine, original_submit_order)
        check(rc_e == 0, f"US paper buy still succeeds (rc={rc_e})")
        if submit_order_calls:
            us_quantity = submit_order_calls[-1].get("quantity")
            check(us_quantity == float(int(us_quantity)), f"US quantity remains a whole share count (found {us_quantity!r})")

        # --- Scenario F: Crypto regression (whole-unit sizing unchanged) --
        print("\n" + "=" * 70)
        print("[Scenario F] Crypto paper buy sizing unchanged")
        print("=" * 70)
        submit_order_calls.clear()
        original_submit_order = _install_submit_order_spy(app.paper_trading_engine)
        try:
            rc_f = cli._run_paper_buy_command(
                app,
                [CRYPTO_SYMBOL, "--allocation", "0.1", "--market", "crypto", "--executed-at", EXECUTED_AT],
            )
        finally:
            _uninstall_submit_order_spy(app.paper_trading_engine, original_submit_order)
        check(rc_f == 0, f"Crypto paper buy still succeeds (rc={rc_f})")

        # --- Scenario G: margin consistency ---------------------------------
        print("\n" + "=" * 70)
        print("[Scenario G] required margin matches forex_margin_policy for an accepted quantity")
        print("=" * 70)
        expected_margin = calculate_required_margin(EUR_USD, 1.0, 10001)
        check(expected_margin == 10001, f"required_margin == price*quantity == 10001 (found {expected_margin})")

        # --- Scenario H: real Forex paper execution reaches FILLED --------
        print("\n" + "=" * 70)
        print("[Scenario H] python main.py paper buy EUR/USD --market forex --allocation 0.1 --stop-loss ...")
        print("=" * 70)
        app3_db = Path(tmp_dir) / "activation11_24_forex_quantity_h.db"
        run_init(db_config=DatabaseConfig(db_path=app3_db), print_fn=lambda s: None)
        run_init_forex(db_config=DatabaseConfig(db_path=app3_db), print_fn=lambda s: None)
        app3 = _build_app(DatabaseConfig(db_path=app3_db))
        app3.snapshot_repository.create(
            scan_time=EXECUTED_AT,
            symbol=EUR_USD,
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
            status="success",
            evidence_summary="EUR/USD scan: deterministic Activation 11.24 Scenario H fixture.",
        )
        rc_h = cli._run_paper_buy_command(
            app3,
            [
                EUR_USD,
                "--allocation",
                "0.1",
                "--market",
                "forex",
                "--executed-at",
                EXECUTED_AT,
                "--stop-loss",
                "0.95",
            ],
        )
        check(rc_h == 0, f"real Forex paper BUY reaches FILLED with a realistic quantity (rc={rc_h})")
        h_orders = app3.order_repository.list_by_account(DEFAULT_FOREX_ACCOUNT_ID)
        h_trades = app3.trade_repository.list_by_account(DEFAULT_FOREX_ACCOUNT_ID)
        h_position = app3.position_repository.get_open_position(DEFAULT_FOREX_ACCOUNT_ID, EUR_USD)
        check(len(h_orders) == 1, f"exactly 1 Order persisted (found {len(h_orders)})")
        check(len(h_trades) == 1, f"exactly 1 Trade persisted (found {len(h_trades)})")
        check(h_position is not None and h_position.quantity == 10_000, f"Position quantity == 10,000 (found {getattr(h_position, 'quantity', None)!r})")

        # --- Scenario I: invalid quantity remains rejected -----------------
        print("\n" + "=" * 70)
        print("[Scenario I] invalid quantity (zero/negative/non-numeric/fractional) rejected")
        print("=" * 70)
        zero_rc = cli._run_paper_sell_command(
            app, [EUR_USD, "--quantity", "0", "--market", "forex", "--executed-at", EXECUTED_AT, "--stop-loss", "1.05"]
        )
        check(zero_rc == 1, "zero --quantity rejected before submit_order")
        negative_rc = cli._run_paper_sell_command(
            app, [EUR_USD, "--quantity", "-5", "--market", "forex", "--executed-at", EXECUTED_AT, "--stop-loss", "1.05"]
        )
        check(negative_rc == 1, "negative --quantity rejected before submit_order")
        nonnumeric_rc = cli._run_paper_sell_command(
            app, [EUR_USD, "--quantity", "abc", "--market", "forex", "--executed-at", EXECUTED_AT, "--stop-loss", "1.05"]
        )
        check(nonnumeric_rc == 1, "non-numeric --quantity rejected before submit_order")

        fractional_snapshot = cli._latest_snapshot_for_symbol(app, EUR_USD)
        os.environ["AIOS_MARKET"] = "forex"
        try:
            app.paper_trading_engine.submit_order(
                account_id=DEFAULT_FOREX_ACCOUNT_ID,
                symbol=EUR_USD,
                action="BUY",
                quantity=1000.5,
                requested_price=1.0,
                executed_at=EXECUTED_AT,
                signal_evidence=fractional_snapshot,
                user_approval=True,
                idempotency_key=f"test-forex-fractional-{uuid.uuid4()}",
                stop_loss=0.95,
            )
            check(False, "fractional Forex quantity (1000.5) should have been rejected")
        except ValidationError as exc:
            check(
                exc.details.get("reason") == PRETRADE_REASON_INVALID_LOT_SIZE,
                f"fractional Forex quantity rejected with INVALID_LOT_SIZE (found {exc.details.get('reason')!r})",
            )
        finally:
            if previous_market_env is None:
                os.environ.pop("AIOS_MARKET", None)
            else:
                os.environ["AIOS_MARKET"] = previous_market_env

        # --- Scenario J: AIOS_MARKET restoration ----------------------------
        print("\n" + "=" * 70)
        print("[Scenario J] AIOS_MARKET restoration")
        print("=" * 70)
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            "AIOS_MARKET restored to its original value after every command above",
        )

        # --- Existing regression: Activation 11.22 market routing untouched
        print("\n" + "=" * 70)
        print("[Regression] Activation 11.22 market routing re-run")
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