"""Activation 10.1 -- Production CLI crypto paper BUY/SELL +
reconciliation acceptance test.

Exercises the full production flow for the crypto market through the
real CLI functions in ``main.py`` and the real, unmodified business
services underneath them, against one temporary SQLite database:

    init + init-crypto
    -> a persisted crypto RankingSnapshot for BTC-USD (status=success)
    -> paper buy BTC-USD --allocation X --market crypto
       -> Order / Trade / Cash / Position, all under 'crypto-usd'
       -> provider symbol reaches the price boundary as 'BTC-USD',
          never 'BTC-USD.JK'
    -> paper sell BTC-USD --quantity N --market crypto
    -> ReconciliationEngine.reconcile_account('crypto-usd') -- CONSISTENT
    -> IDX isolation (the default 'paper' account is untouched throughout)
    -> AIOS_MARKET restored to its original value, on success and on
       a rejected order
    -> an unsupported crypto symbol is rejected cleanly, with no
       account/order/trade created

Deliberately mirrors ``Tests/test_activation9_us_e2e_acceptance.py``'s
own structure and real-collaborators-only approach (same
``MinimalApp`` pattern, same single mocked boundary), trimmed to only
what Activation 10.1's roadmap gate actually requires: it does not
re-drive ``scan``/``recommendation`` output formatting (those are
unchanged, already covered elsewhere) -- it inserts the one
prerequisite crypto ``RankingSnapshot`` row directly via the real,
unmodified ``SnapshotRepository.create()`` (the same production
persistence boundary ``ManualScanService`` itself writes through), so
``_latest_snapshot_for_symbol`` finds a real "usable recommendation"
for BTC-USD without needing a crypto-capable ``WatchlistScanner``
wired (out of scope for this atomic step).

Boundary mocked (and ONLY this boundary): the module-level
``Orchestration.market_price_tool._fetch_real_prices`` function -- the
network call to the real data provider. This sandbox has no route to
that network, so a real lookup for BTC-USD always returns
``(None, None)``, which would otherwise make every price-dependent
step in this flow (buy, post-trade snapshot) fail for an
environmental reason, not a production defect. The fake asserts the
symbol it receives is exactly ``"BTC-USD"`` (never ``"BTC-USD.JK"``),
which is itself the Requirement 8 / Test C proof: if
``resolve_provider_symbol`` ever mis-resolved the crypto ticker, this
fake would receive the wrong symbol and return ``(None, None)``,
failing the BUY outright.

Nothing else is mocked. In particular, never mocked:
AccountRepository, OrderRepository, TradeRepository,
PositionRepository, SnapshotRepository, PortfolioSnapshotRepository,
PaperTradingEngine, ExecutionService, OrderLifecycleService,
ReconciliationEngine, PortfolioSnapshotService.

Run directly: ``python Tests/test_activation10_1_crypto_paper_workflow.py``
-- no external test framework required, matching every other
``Tests/test_*``/``*_proof.py`` script in this suite.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
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

from Core.bootstrap import DEFAULT_CRYPTO_ACCOUNT_ID, DEFAULT_PAPER_ACCOUNT_ID  # noqa: E402
from Core.init_command import run_init  # noqa: E402
from Core.init_crypto_command import run_init_crypto  # noqa: E402
from Core.market_config import CRYPTO_SYMBOLS  # noqa: E402

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

CRYPTO_SYMBOL = "BTC-USD"
UNSUPPORTED_CRYPTO_SYMBOL = "DOGE-USD"  # not in CRYPTO_SYMBOLS -- Test I
CRYPTO_CURRENT_PRICE = 100.0
CRYPTO_PREVIOUS_PRICE = 90.0
# crypto-usd starts with DEFAULT_CRYPTO_ACCOUNT_BALANCE (100,000.0 USD,
# see Core.bootstrap). allocation 0.05 -> target_capital 5,000.0 ->
# floor(5000.0 / 100.0) = 50 units, lot_size=1 (no IDX 100-share lot
# behavior applied to crypto -- Requirement 5).
CRYPTO_BUY_ALLOCATION = "0.05"
EXPECTED_BUY_QUANTITY = 50
SELL_QUANTITY = "50"
EXECUTED_AT = "2026-01-06T15:00:00+00:00"


received_symbols: List[str] = []


def _fake_fetch_real_prices(symbol: str):
    """Deterministic stand-in for ``_fetch_real_prices`` -- the sole
    network boundary in this flow. Records every symbol it is called
    with (Test C proof) and returns the fixed (current, previous)
    tuple only for an exact, unsuffixed ``"BTC-USD"`` match --
    ``"BTC-USD.JK"`` (the pre-fix mis-resolution) would NOT match and
    would fall through to ``(None, None)``, which fails the order.
    """
    received_symbols.append(symbol)
    if symbol == CRYPTO_SYMBOL:
        return CRYPTO_CURRENT_PRICE, CRYPTO_PREVIOUS_PRICE
    return None, None


# ---------------------------------------------------------------------------
# Minimal application namespace: real constructors only
# ---------------------------------------------------------------------------


class MinimalApp:
    """Duck-typed namespace exposing exactly the collaborators the CLI
    functions under test (``_run_paper_buy_command``,
    ``_run_paper_sell_command``) read from ``app``. Every attribute is
    a real, unmodified production object, built with its actual
    constructor -- mirrors ``Tests/test_activation9_us_e2e_acceptance.
    py``'s own ``MinimalApp``. ``build_application()`` itself is not
    used (it also builds a full provider/agent graph this scenario
    neither exercises nor needs).
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

        # market_price_tool: the same real, unmodified MarketPriceTool
        # class production uses -- only its module-level
        # _fetch_real_prices function is monkeypatched for the
        # scenario (see _fake_fetch_real_prices above), not this class.
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
# Scenario
# ---------------------------------------------------------------------------


def main() -> int:
    tmp_dir = tempfile.mkdtemp(prefix="activation10_1_crypto_e2e_")
    db_path = Path(tmp_dir) / "activation10_1_crypto_e2e.db"
    cfg = DatabaseConfig(db_path=db_path)

    previous_market_env = os.environ.get("AIOS_MARKET")
    original_fetch_real_prices = market_price_tool_module._fetch_real_prices

    try:
        # --- Setup: real init + real init-crypto, same DB ----------------
        print("=" * 70)
        print("[Setup] run_init() + run_init_crypto() against one temp SQLite DB")
        print("=" * 70)
        init_rc = run_init(db_config=cfg, print_fn=lambda s: None)
        check(init_rc == 0, "run_init() succeeded")
        init_crypto_rc = run_init_crypto(db_config=cfg, print_fn=lambda s: None)
        check(init_crypto_rc == 0, "run_init_crypto() succeeded")

        app = _build_app(cfg)

        idx_account_before = app.account_repository.get_by_id(DEFAULT_PAPER_ACCOUNT_ID)
        crypto_account_before = app.account_repository.get_by_id(DEFAULT_CRYPTO_ACCOUNT_ID)
        check(idx_account_before is not None, "IDX 'paper' account exists after init")
        check(crypto_account_before is not None, "crypto 'crypto-usd' account exists after init-crypto")
        idx_cash_before = idx_account_before.cash if idx_account_before else None

        # Prerequisite: a real, persisted "usable recommendation" for
        # BTC-USD, written through the real SnapshotRepository.create()
        # (the same persistence boundary ManualScanService itself
        # writes through) -- not a scan run (crypto scan wiring is out
        # of scope for this atomic step).
        app.snapshot_repository.create(
            scan_time=EXECUTED_AT,
            symbol=CRYPTO_SYMBOL,
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
            status="success",
            evidence_summary="Crypto scan: deterministic Activation 10.1 test fixture.",
        )
        btc_snapshot = cli._latest_snapshot_for_symbol(app, CRYPTO_SYMBOL)
        check(
            btc_snapshot is not None and btc_snapshot.status == "success",
            "a usable BTC-USD RankingSnapshot is resolvable before any order is placed",
        )

        # Patch ONLY the network boundary for the scenario's duration.
        market_price_tool_module._fetch_real_prices = _fake_fetch_real_prices

        # --- A/I. Unsupported crypto symbol is rejected cleanly -----------
        print("\n" + "=" * 70)
        print("[Test I] paper buy DOGE-USD --market crypto -> rejected cleanly")
        print("=" * 70)
        check(
            UNSUPPORTED_CRYPTO_SYMBOL not in CRYPTO_SYMBOLS,
            f"sanity: {UNSUPPORTED_CRYPTO_SYMBOL!r} is genuinely not in CRYPTO_SYMBOLS",
        )
        crypto_orders_before_unsupported = app.order_repository.list_by_account(DEFAULT_CRYPTO_ACCOUNT_ID)
        unsupported_rc = cli._run_paper_buy_command(
            app,
            [UNSUPPORTED_CRYPTO_SYMBOL, "--allocation", CRYPTO_BUY_ALLOCATION, "--market", "crypto"],
        )
        check(unsupported_rc == 1, "unsupported crypto symbol BUY exits 1")
        crypto_orders_after_unsupported = app.order_repository.list_by_account(DEFAULT_CRYPTO_ACCOUNT_ID)
        check(
            len(crypto_orders_after_unsupported) == len(crypto_orders_before_unsupported),
            "unsupported crypto symbol BUY writes no Order",
        )
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            "AIOS_MARKET restored after a rejected (unsupported-symbol) crypto order",
        )

        # --- A. --market crypto is accepted (dispatch-level gate) ---------
        print("\n" + "=" * 70)
        print("[Test A] _configure_cli_market accepts 'crypto'")
        print("=" * 70)
        check(
            cli._configure_cli_market(["--market", "crypto"]) == 0,
            "main._configure_cli_market(['--market', 'crypto']) returns 0 (accepted)",
        )
        os.environ["AIOS_MARKET"] = previous_market_env if previous_market_env is not None else "idx"
        if previous_market_env is None:
            os.environ.pop("AIOS_MARKET", None)

        # --- B/C/D. paper buy BTC-USD --allocation 0.05 --market crypto ---
        print("\n" + "=" * 70)
        print("[Test B/C/D] paper buy BTC-USD --allocation 0.05 --market crypto")
        print("=" * 70)
        buy_rc = cli._run_paper_buy_command(
            app,
            [
                CRYPTO_SYMBOL,
                "--allocation",
                CRYPTO_BUY_ALLOCATION,
                "--market",
                "crypto",
                "--executed-at",
                EXECUTED_AT,
            ],
        )
        check(buy_rc == 0, "paper buy BTC-USD ... --market crypto exited 0")
        check(
            CRYPTO_SYMBOL in received_symbols,
            f"the price boundary received the provider symbol exactly as 'BTC-USD' "
            f"(received: {received_symbols}) -- Requirement 8 / Test C",
        )
        check(
            "BTC-USD.JK" not in received_symbols,
            "the price boundary was NEVER called with the mis-resolved 'BTC-USD.JK'",
        )

        crypto_orders = app.order_repository.list_by_account(DEFAULT_CRYPTO_ACCOUNT_ID)
        crypto_trades = app.trade_repository.list_by_account(DEFAULT_CRYPTO_ACCOUNT_ID)
        crypto_position = app.position_repository.get_open_position(DEFAULT_CRYPTO_ACCOUNT_ID, CRYPTO_SYMBOL)
        crypto_account_after_buy = app.account_repository.get_by_id(DEFAULT_CRYPTO_ACCOUNT_ID)

        check(
            len(crypto_orders) == 1,
            f"exactly 1 Order exists under 'crypto-usd' (found {len(crypto_orders)}) -- Test B",
        )
        check(len(crypto_trades) == 1, f"exactly 1 Trade exists under 'crypto-usd' (found {len(crypto_trades)})")
        buy_trade = crypto_trades[0]
        check(buy_trade.action == "BUY", "the crypto trade is a BUY")
        check(buy_trade.symbol == CRYPTO_SYMBOL, f"the crypto trade symbol == 'BTC-USD' (found {buy_trade.symbol})")
        check(crypto_position is not None, "an open Position exists under 'crypto-usd' for BTC-USD")
        check(
            crypto_position is not None and crypto_position.quantity == EXPECTED_BUY_QUANTITY,
            f"Position quantity == {EXPECTED_BUY_QUANTITY} (found "
            f"{crypto_position.quantity if crypto_position else None})",
        )
        check(
            crypto_account_after_buy is not None and crypto_account_after_buy.cash < crypto_account_before.cash,
            f"crypto cash decreased after BUY (before={crypto_account_before.cash}, "
            f"after={crypto_account_after_buy.cash if crypto_account_after_buy else None})",
        )

        # --- G. IDX isolation after the crypto buy -------------------------
        idx_orders_after_buy = app.order_repository.list_by_account(DEFAULT_PAPER_ACCOUNT_ID)
        idx_btc_position = app.position_repository.get_open_position(DEFAULT_PAPER_ACCOUNT_ID, CRYPTO_SYMBOL)
        idx_account_after_buy = app.account_repository.get_by_id(DEFAULT_PAPER_ACCOUNT_ID)
        check(len(idx_orders_after_buy) == 0, "no order was written to the IDX 'paper' account by the crypto buy")
        check(idx_btc_position is None, "no BTC-USD position exists under the IDX 'paper' account")
        check(
            idx_account_after_buy is not None and idx_account_after_buy.cash == idx_cash_before,
            f"IDX cash unchanged by the crypto buy (before={idx_cash_before}, "
            f"after={idx_account_after_buy.cash if idx_account_after_buy else None})",
        )

        # --- H. Environment restoration after a successful crypto BUY -----
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            "AIOS_MARKET restored to its original value after the crypto BUY",
        )

        # --- F. Reconciliation after BUY ------------------------------------
        print("\n" + "=" * 70)
        print("[Test F] ReconciliationEngine.reconcile_account('crypto-usd') after BUY")
        print("=" * 70)
        reconciliation_after_buy = app.reconciliation_engine.reconcile_account(DEFAULT_CRYPTO_ACCOUNT_ID)
        check(
            reconciliation_after_buy.consistent is True,
            f"crypto-usd reconciliation is CONSISTENT after BUY (violations: {reconciliation_after_buy.violations})",
        )
        check(
            len(reconciliation_after_buy.violations) == 0,
            f"no unresolved violations for crypto-usd after BUY (found: {reconciliation_after_buy.violations})",
        )

        # --- E. paper sell BTC-USD --quantity 50 --market crypto -----------
        print("\n" + "=" * 70)
        print("[Test E] paper sell BTC-USD --quantity 50 --market crypto")
        print("=" * 70)
        crypto_cash_before_sell = app.account_repository.get_by_id(DEFAULT_CRYPTO_ACCOUNT_ID).cash
        sell_rc = cli._run_paper_sell_command(
            app,
            [
                CRYPTO_SYMBOL,
                "--quantity",
                SELL_QUANTITY,
                "--market",
                "crypto",
                "--executed-at",
                EXECUTED_AT,
            ],
        )
        check(sell_rc == 0, "paper sell BTC-USD ... --market crypto exited 0")

        crypto_position_after_sell = app.position_repository.get_open_position(DEFAULT_CRYPTO_ACCOUNT_ID, CRYPTO_SYMBOL)
        crypto_trades_after_sell = app.trade_repository.list_by_account(DEFAULT_CRYPTO_ACCOUNT_ID)
        crypto_account_after_sell = app.account_repository.get_by_id(DEFAULT_CRYPTO_ACCOUNT_ID)

        check(
            crypto_position_after_sell is None or crypto_position_after_sell.quantity == 0,
            f"crypto BTC-USD position closes after selling the full acquired quantity "
            f"(open position now: {crypto_position_after_sell})",
        )
        check(
            len(crypto_trades_after_sell) == 2,
            f"crypto trade count incremented to 2 (BUY + SELL) (found {len(crypto_trades_after_sell)})",
        )
        check(
            crypto_account_after_sell.cash > crypto_cash_before_sell,
            f"crypto cash increased after SELL (before={crypto_cash_before_sell}, "
            f"after={crypto_account_after_sell.cash})",
        )
        sell_trade = max(crypto_trades_after_sell, key=lambda t: t.trade_id)
        check(sell_trade.action == "SELL", "the most recent crypto trade is the SELL")

        # --- G. IDX isolation after the crypto sell -------------------------
        idx_orders_after_sell = app.order_repository.list_by_account(DEFAULT_PAPER_ACCOUNT_ID)
        idx_account_after_sell = app.account_repository.get_by_id(DEFAULT_PAPER_ACCOUNT_ID)
        check(len(idx_orders_after_sell) == 0, "still no order under the IDX 'paper' account after the crypto sell")
        check(
            idx_account_after_sell.cash == idx_cash_before,
            f"IDX cash still unchanged after the crypto sell (before={idx_cash_before}, "
            f"after={idx_account_after_sell.cash})",
        )

        # --- H. Environment restoration after a successful crypto SELL -----
        check(
            os.environ.get("AIOS_MARKET") == previous_market_env,
            "AIOS_MARKET restored to its original value after the crypto SELL",
        )

        # --- F. Reconciliation after SELL -----------------------------------
        print("\n" + "=" * 70)
        print("[Test F] ReconciliationEngine.reconcile_account('crypto-usd') after SELL")
        print("=" * 70)
        crypto_reconciliation = app.reconciliation_engine.reconcile_account(DEFAULT_CRYPTO_ACCOUNT_ID)
        check(
            crypto_reconciliation.consistent is True,
            f"crypto-usd reconciliation is CONSISTENT after SELL (violations: {crypto_reconciliation.violations})",
        )
        check(
            len(crypto_reconciliation.violations) == 0,
            f"no unresolved violations for crypto-usd after SELL (found: {crypto_reconciliation.violations})",
        )

        idx_reconciliation = app.reconciliation_engine.reconcile_account(DEFAULT_PAPER_ACCOUNT_ID)
        check(
            idx_reconciliation.consistent is True,
            f"IDX 'paper' account remains CONSISTENT after the entire crypto flow "
            f"(violations: {idx_reconciliation.violations})",
        )

        print("\n" + "=" * 70)
        print(f"RESULT: {_PASS} PASS, {_FAIL} FAIL")
        print("=" * 70)
        return 0 if _FAIL == 0 else 1

    finally:
        market_price_tool_module._fetch_real_prices = original_fetch_real_prices
        if previous_market_env is None:
            os.environ.pop("AIOS_MARKET", None)
        else:
            os.environ["AIOS_MARKET"] = previous_market_env


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)