"""Activation 10.7 -- Multi-asset crypto wallet/balance evidence test.

The Activation 10.7 audit concluded the paper wallet/balance
requirement is already COMPLETE: ``Account.cash`` (one quote-currency
balance per account) plus ``Position`` (keyed by ``account_id`` +
``symbol``, one row per base-asset holding) already provide the paper
spot semantics the roadmap asks for. The one concrete gap the audit
found was evidentiary, not architectural: no existing test proves BTC-
USD and ETH-USD can coexist, independently, under the single
``crypto-usd`` account. This test closes exactly that gap.

NO PRODUCTION CODE CHANGE. This file exercises the real, unmodified
production collaborators against one temporary SQLite database:

    init + init-crypto
    -> paper BUY BTC-USD (real PaperTradingEngine.submit_order)
    -> paper BUY ETH-USD (real PaperTradingEngine.submit_order)
    -> both positions coexist under 'crypto-usd', independently correct
    -> shared Account.cash reflects both BUYs (compute_buy_required_cash,
       the same shared formula PaperTradingEngine/AccountBalanceService
       both already use -- not reimplemented here)
    -> ReconciliationEngine.reconcile_account('crypto-usd') -- CONSISTENT
       with both assets open
    -> paper SELL BTC-USD (full quantity)
    -> BTC position closes; ETH position is completely untouched
    -> shared Account.cash reflects the SELL
    -> ReconciliationEngine.reconcile_account('crypto-usd') -- CONSISTENT
       again, after BTC closes
    -> PositionRepository.list_by_account('crypto-usd') sees both
       symbols while both are open (Step H minimum evidence)

Deliberately mirrors ``Tests/test_activation10_1_crypto_paper_workflow.
py``'s real-collaborators-only approach (same production constructors,
same style), but calls ``PaperTradingEngine.submit_order()`` directly
instead of going through the CLI/allocation-sizing/market-price-tool
path -- this test is about wallet/balance evidence for two symbols at
once, not about CLI dispatch or provider-symbol resolution (already
covered by Activation 10.1). Nothing is mocked: no network boundary is
touched by this flow at all, since ``requested_price`` is supplied
directly to ``submit_order()``, exactly like every other non-CLI test
in this suite already does.

Never mocked: AccountRepository, OrderRepository, TradeRepository,
PositionRepository, PaperTradingEngine, ExecutionService,
OrderLifecycleService, AccountBalanceService, PositionManager,
ReconciliationEngine.

Run directly: ``python Tests/test_activation10_7_crypto_multi_asset_wallet.py``
-- no external test framework required, matching every other
``Tests/test_*``/``*_proof.py`` script in this suite.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import List

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.account_balance_service import (  # noqa: E402
    AccountBalanceService,
    compute_buy_required_cash,
)
from Business.execution_policy_config import load_execution_policy  # noqa: E402
from Business.execution_service import ExecutionService  # noqa: E402
from Business.notification_builder import NotificationBuilder  # noqa: E402
from Business.notification_dispatcher import NotificationDispatcher  # noqa: E402
from Business.notification_manager import NotificationManager  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Business.reconciliation_engine import ReconciliationEngine  # noqa: E402

from Core.bootstrap import DEFAULT_CRYPTO_ACCOUNT_ID  # noqa: E402
from Core.init_command import run_init  # noqa: E402
from Core.init_crypto_command import run_init_crypto  # noqa: E402

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
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402

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

BTC_SYMBOL = "BTC-USD"
ETH_SYMBOL = "ETH-USD"

# BTC-USD: step_size=0.001, quantity_precision=3, minimum_notional=10.0,
# price_tick=0.01 (Business.crypto_quantity_policy / crypto_price_policy
# defaults). quantity=1.000 @ price=100.00 -> order_value=100.0, well
# above the minimum notional, on-tick, on-step.
BTC_BUY_QUANTITY = 1.0
BTC_BUY_PRICE = 100.0

# ETH-USD: step_size=0.01, quantity_precision=2, minimum_notional=10.0,
# price_tick=0.01. quantity=2.00 @ price=50.00 -> order_value=100.0,
# same shape as the BTC order above, deliberately different symbol
# conventions (different step/precision) to prove isolation is real,
# not coincidental.
ETH_BUY_QUANTITY = 2.0
ETH_BUY_PRICE = 50.0

# Crypto fee policy default (Business.crypto_fee_policy): taker_fee_rate
# is a flat placeholder amount (not a percentage), identical for BTC-USD
# and ETH-USD, and tax is always 0.0 for crypto (Business.us_market_
# policy.resolve_fee_tax, market == "crypto" branch). Both
# PaperTradingEngine gate 8 and ExecutionService resolve this from the
# same shared function, so it is never reimplemented here as a literal
# guess -- it is the documented default every other Activation 10 test
# already relies on.
CRYPTO_TAKER_FEE = 0.20
CRYPTO_TAX = 0.0

BTC_SELL_PRICE = 110.0  # on-tick (0.01), any positive price is valid

EXECUTED_AT = "2026-01-06T15:00:00+00:00"


# ---------------------------------------------------------------------------
# Minimal application namespace: real constructors only
# ---------------------------------------------------------------------------


class MinimalApp:
    """Duck-typed namespace exposing exactly the collaborators this
    scenario needs, mirroring ``Tests/test_activation10_1_crypto_paper_
    workflow.py``'s own ``MinimalApp`` -- every attribute is a real,
    unmodified production object built with its actual constructor.
    Trimmed relative to that file: no ``market_price_tool``/
    ``UnrealizedPnLEngine``/``PortfolioSnapshotService``/
    ``SnapshotRepository`` -- this scenario calls
    ``PaperTradingEngine.submit_order()`` directly with an explicit
    ``requested_price``, so no price-provider boundary or ranking-
    snapshot prerequisite is exercised here at all.
    """

    def __init__(self, database_manager: DatabaseManager) -> None:
        self.account_repository = AccountRepository(database_manager)
        self.position_repository = PositionRepository(database_manager)
        self.order_repository = OrderRepository(database_manager)
        self.trade_repository = TradeRepository(database_manager)
        order_idempotency_repository = OrderIdempotencyRepository(database_manager)
        order_approval_repository = OrderApprovalRepository(database_manager)

        execution_policy = load_execution_policy()
        order_lifecycle_service = OrderLifecycleService(self.order_repository)
        execution_service = ExecutionService(self.order_repository, self.trade_repository, execution_policy)
        self.account_balance_service = AccountBalanceService(self.account_repository)
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
            account_balance_service=self.account_balance_service,
            position_manager=position_manager,
            notification_manager=notification_manager,
            notification_builder=notification_builder,
            order_approval_repository=order_approval_repository,
            halted_markets=frozenset(),
            halted_symbols=frozenset(),
            max_daily_loss=None,
            max_position_value=None,
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
    tmp_dir = tempfile.mkdtemp(prefix="activation10_7_crypto_multi_asset_")
    db_path = Path(tmp_dir) / "activation10_7_crypto_multi_asset.db"
    cfg = DatabaseConfig(db_path=db_path)

    previous_market_env = os.environ.get("AIOS_MARKET")

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
        os.environ["AIOS_MARKET"] = "crypto"

        # --- Step A: initial state ------------------------------------------
        print("\n" + "=" * 70)
        print("[Step A] initial crypto-usd state")
        print("=" * 70)
        crypto_account_initial = app.account_repository.get_by_id(DEFAULT_CRYPTO_ACCOUNT_ID)
        check(crypto_account_initial is not None, "crypto-usd account exists")
        initial_cash = crypto_account_initial.cash

        btc_position_initial = app.position_repository.get_open_position(DEFAULT_CRYPTO_ACCOUNT_ID, BTC_SYMBOL)
        eth_position_initial = app.position_repository.get_open_position(DEFAULT_CRYPTO_ACCOUNT_ID, ETH_SYMBOL)
        check(btc_position_initial is None, "no BTC-USD open position before any order [ ] crypto-usd exists")
        check(eth_position_initial is None, "no ETH-USD open position before any order")

        # --- Step B: BUY BTC-USD --------------------------------------------
        print("\n" + "=" * 70)
        print("[Step B] paper BUY BTC-USD (direct submit_order)")
        print("=" * 70)
        btc_buy_trade = app.paper_trading_engine.submit_order(
            account_id=DEFAULT_CRYPTO_ACCOUNT_ID,
            symbol=BTC_SYMBOL,
            action="BUY",
            quantity=BTC_BUY_QUANTITY,
            requested_price=BTC_BUY_PRICE,
            executed_at=EXECUTED_AT,
            signal_evidence="activation10.7-btc-buy-evidence",
            user_approval=True,
            idempotency_key="activation10.7-btc-buy",
        )
        check(btc_buy_trade.action == "BUY", "BTC BUY trade recorded")
        check(btc_buy_trade.fee == CRYPTO_TAKER_FEE, f"BTC BUY fee == {CRYPTO_TAKER_FEE} (found {btc_buy_trade.fee})")

        btc_position_after_buy = app.position_repository.get_open_position(DEFAULT_CRYPTO_ACCOUNT_ID, BTC_SYMBOL)
        check(btc_position_after_buy is not None, "BTC open position can be created [ ] BTC position can be created")
        check(
            btc_position_after_buy is not None and btc_position_after_buy.quantity == BTC_BUY_QUANTITY,
            f"BTC quantity == {BTC_BUY_QUANTITY} (found {btc_position_after_buy.quantity if btc_position_after_buy else None})",
        )
        check(
            btc_position_after_buy is not None and btc_position_after_buy.average_price == BTC_BUY_PRICE,
            f"BTC average_price == {BTC_BUY_PRICE} (found "
            f"{btc_position_after_buy.average_price if btc_position_after_buy else None})",
        )

        # --- Step C: BUY ETH-USD, BTC remains open --------------------------
        print("\n" + "=" * 70)
        print("[Step C] paper BUY ETH-USD (BTC-USD remains open)")
        print("=" * 70)
        eth_buy_trade = app.paper_trading_engine.submit_order(
            account_id=DEFAULT_CRYPTO_ACCOUNT_ID,
            symbol=ETH_SYMBOL,
            action="BUY",
            quantity=ETH_BUY_QUANTITY,
            requested_price=ETH_BUY_PRICE,
            executed_at=EXECUTED_AT,
            signal_evidence="activation10.7-eth-buy-evidence",
            user_approval=True,
            idempotency_key="activation10.7-eth-buy",
        )
        check(eth_buy_trade.action == "BUY", "ETH BUY trade recorded")
        check(eth_buy_trade.fee == CRYPTO_TAKER_FEE, f"ETH BUY fee == {CRYPTO_TAKER_FEE} (found {eth_buy_trade.fee})")

        btc_position_after_eth_buy = app.position_repository.get_open_position(DEFAULT_CRYPTO_ACCOUNT_ID, BTC_SYMBOL)
        eth_position_after_buy = app.position_repository.get_open_position(DEFAULT_CRYPTO_ACCOUNT_ID, ETH_SYMBOL)

        check(
            btc_position_after_eth_buy is not None,
            "BTC position still exists after ETH BUY [ ] BTC and ETH positions coexist",
        )
        check(eth_position_after_buy is not None, "ETH open position can be created [ ] ETH position can be created")
        check(
            btc_position_after_eth_buy is not None and btc_position_after_eth_buy.quantity == BTC_BUY_QUANTITY,
            f"BTC quantity unchanged by the ETH BUY (found "
            f"{btc_position_after_eth_buy.quantity if btc_position_after_eth_buy else None}) "
            f"[ ] BTC quantity is independent",
        )
        check(
            eth_position_after_buy is not None and eth_position_after_buy.quantity == ETH_BUY_QUANTITY,
            f"ETH quantity == {ETH_BUY_QUANTITY} (found "
            f"{eth_position_after_buy.quantity if eth_position_after_buy else None}) "
            f"[ ] ETH quantity is independent",
        )

        # --- Step D: shared USD cash after both BUYs -------------------------
        print("\n" + "=" * 70)
        print("[Step D] shared USD cash after BTC BUY + ETH BUY")
        print("=" * 70)
        expected_cash_after_buys = (
            initial_cash
            - compute_buy_required_cash(BTC_BUY_QUANTITY * BTC_BUY_PRICE, btc_buy_trade.fee, btc_buy_trade.tax)
            - compute_buy_required_cash(ETH_BUY_QUANTITY * ETH_BUY_PRICE, eth_buy_trade.fee, eth_buy_trade.tax)
        )
        crypto_account_after_buys = app.account_repository.get_by_id(DEFAULT_CRYPTO_ACCOUNT_ID)
        check(
            crypto_account_after_buys is not None and crypto_account_after_buys.cash == expected_cash_after_buys,
            f"crypto-usd cash reflects both BUYs from the shared quote pool "
            f"(expected {expected_cash_after_buys}, found "
            f"{crypto_account_after_buys.cash if crypto_account_after_buys else None}) "
            f"[ ] shared USD cash reflects both BUYs",
        )

        # --- Step H (evidence, ahead of the SELL): account-level aggregation
        print("\n" + "=" * 70)
        print("[Step H] PositionRepository.list_by_account('crypto-usd') sees both symbols")
        print("=" * 70)
        positions_while_both_open = app.position_repository.list_by_account(DEFAULT_CRYPTO_ACCOUNT_ID)
        symbols_while_both_open = {p.symbol for p in positions_while_both_open if p.status == "open"}
        check(
            symbols_while_both_open == {BTC_SYMBOL, ETH_SYMBOL},
            f"list_by_account('crypto-usd') shows both open symbols simultaneously "
            f"(found {symbols_while_both_open})",
        )

        # --- Step G (before SELL): reconciliation with both assets open -----
        print("\n" + "=" * 70)
        print("[Step G] ReconciliationEngine.reconcile_account('crypto-usd') with BTC + ETH open")
        print("=" * 70)
        reconciliation_both_open = app.reconciliation_engine.reconcile_account(DEFAULT_CRYPTO_ACCOUNT_ID)
        check(
            reconciliation_both_open.consistent is True and len(reconciliation_both_open.violations) == 0,
            f"crypto-usd is CONSISTENT with BTC + ETH simultaneously open "
            f"(violations: {reconciliation_both_open.violations}) "
            f"[ ] reconciliation passes with BTC + ETH simultaneously",
        )

        # --- Step E: SELL BTC-USD completely, ETH must be untouched ----------
        print("\n" + "=" * 70)
        print("[Step E] paper SELL BTC-USD (full quantity) -- ETH-USD must be untouched")
        print("=" * 70)
        eth_quantity_before_sell = eth_position_after_buy.quantity
        eth_average_price_before_sell = eth_position_after_buy.average_price
        cash_before_sell = crypto_account_after_buys.cash

        btc_sell_trade = app.paper_trading_engine.submit_order(
            account_id=DEFAULT_CRYPTO_ACCOUNT_ID,
            symbol=BTC_SYMBOL,
            action="SELL",
            quantity=BTC_BUY_QUANTITY,
            requested_price=BTC_SELL_PRICE,
            executed_at=EXECUTED_AT,
            signal_evidence="activation10.7-btc-sell-evidence",
            user_approval=True,
            idempotency_key="activation10.7-btc-sell",
        )
        check(btc_sell_trade.action == "SELL", "BTC SELL trade recorded")

        btc_position_after_sell = app.position_repository.get_open_position(DEFAULT_CRYPTO_ACCOUNT_ID, BTC_SYMBOL)
        eth_position_after_sell = app.position_repository.get_open_position(DEFAULT_CRYPTO_ACCOUNT_ID, ETH_SYMBOL)

        check(
            btc_position_after_sell is None,
            f"BTC position closes according to PositionManager semantics after selling the full quantity "
            f"(open position now: {btc_position_after_sell})",
        )
        check(
            eth_position_after_sell is not None,
            "ETH position still OPEN after the BTC SELL [ ] selling BTC does not mutate ETH",
        )
        check(
            eth_position_after_sell is not None and eth_position_after_sell.quantity == eth_quantity_before_sell,
            f"ETH quantity unchanged by the BTC SELL (before={eth_quantity_before_sell}, "
            f"after={eth_position_after_sell.quantity if eth_position_after_sell else None})",
        )
        check(
            eth_position_after_sell is not None
            and eth_position_after_sell.average_price == eth_average_price_before_sell,
            f"ETH average_price unchanged by the BTC SELL (before={eth_average_price_before_sell}, "
            f"after={eth_position_after_sell.average_price if eth_position_after_sell else None})",
        )

        # --- Step F: cash after SELL ------------------------------------------
        print("\n" + "=" * 70)
        print("[Step F] shared USD cash after BTC SELL")
        print("=" * 70)
        expected_cash_after_sell = (
            cash_before_sell
            + (BTC_BUY_QUANTITY * BTC_SELL_PRICE)
            - btc_sell_trade.fee
            - btc_sell_trade.tax
        )
        crypto_account_after_sell = app.account_repository.get_by_id(DEFAULT_CRYPTO_ACCOUNT_ID)
        check(
            crypto_account_after_sell is not None and crypto_account_after_sell.cash == expected_cash_after_sell,
            f"crypto-usd cash reflects the BTC SELL (expected {expected_cash_after_sell}, found "
            f"{crypto_account_after_sell.cash if crypto_account_after_sell else None}) "
            f"[ ] shared USD cash reflects BTC SELL",
        )

        # --- Step G (after SELL): reconciliation after BTC closes ------------
        print("\n" + "=" * 70)
        print("[Step G] ReconciliationEngine.reconcile_account('crypto-usd') after BTC closes")
        print("=" * 70)
        reconciliation_after_close = app.reconciliation_engine.reconcile_account(DEFAULT_CRYPTO_ACCOUNT_ID)
        check(
            reconciliation_after_close.consistent is True and len(reconciliation_after_close.violations) == 0,
            f"crypto-usd is CONSISTENT after BTC closes, ETH still open "
            f"(violations: {reconciliation_after_close.violations}) "
            f"[ ] reconciliation passes after BTC closes",
        )

        print("\n" + "=" * 70)
        print(f"RESULT: {_PASS} PASS, {_FAIL} FAIL")
        print("=" * 70)
        return 0 if _FAIL == 0 else 1

    finally:
        if previous_market_env is None:
            os.environ.pop("AIOS_MARKET", None)
        else:
            os.environ["AIOS_MARKET"] = previous_market_env


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)