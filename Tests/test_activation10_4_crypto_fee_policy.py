"""Activation 10.4 -- crypto maker/taker fee policy acceptance test.

Exercises ``Business.crypto_fee_policy.CryptoFeePolicy`` both directly
(pure rate-selection check) and through the real, unmodified
``Business.paper_trading_engine.PaperTradingEngine`` /
``Business.execution_service.ExecutionService`` paper-trade path
(``market == "crypto"``), against one temporary SQLite database.
Mirrors ``Tests/test_activation10_3_crypto_price_tick.py``'s own
``_build_engine``/``_row_counts`` structure and real-collaborators-only
approach (no mocking of the engine itself).

Required test cases (see Activation 10.4 brief):

    A. Crypto policy defaults load correctly
    B. Crypto policy environment override is picked up on fresh load
    C. Real crypto BUY uses taker fee
    D. Real crypto SELL uses taker fee
    E. Maker fee can be selected via the actual internal
       representation (``resolve_fee_tax(..., execution_liquidity=...)``
       / ``CryptoFeePolicy.fee_rate_for``), without a fake exchange
       matching engine
    F. Pre-trade (PaperTradingEngine gate 8) and persisted
       (ExecutionService/Trade.fee) effective fee agree exactly
    G. Crypto fee is isolated from IDX fee configuration
    H. Crypto fee is isolated from US fee configuration
    I. IDX fee/regression behavior is unaffected
    J. US fee/regression behavior is unaffected
    K. Reconciliation remains consistent after real crypto BUY/SELL
    L. Fee is charged exactly once (no double charge, no omission from
       required-cash)

Run directly: ``python Tests/test_activation10_4_crypto_fee_policy.py``
-- no external test framework required, matching every other
``Tests/test_*.py`` script in this suite.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.account_balance_service import AccountBalanceService  # noqa: E402
from Business.crypto_fee_policy import (  # noqa: E402
    MAKER,
    TAKER,
    CryptoFeePolicy,
    load_crypto_fee_policy,
)
from Business.execution_policy_config import load_execution_policy  # noqa: E402
from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Business.reconciliation_engine import ReconciliationEngine  # noqa: E402
from Business.us_market_policy import resolve_fee_tax  # noqa: E402

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
from Database.models import Trade  # noqa: E402

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
# NOTE -- AIOS paper-market constraints, not exchange claims (see
# Business.crypto_fee_policy module docstring). BTC-USD default:
# maker_fee_rate=0.10, taker_fee_rate=0.20 -- flat per-trade
# placeholder AMOUNTS (account-currency units), not a percentage
# multiplied against notional (see that module's "rate naming, no
# amount * rate formula" note -- this mirrors every other market's
# fee/tax placeholder in this codebase, e.g.
# Business.execution_policy_config.ExecutionPolicy).
# ---------------------------------------------------------------------------

DEFAULT_MAKER_FEE = 0.10
DEFAULT_TAKER_FEE = 0.20

CRYPTO_ACCOUNT_ID = "crypto-fee-policy-test-id"
CRYPTO_SYMBOL = "BTC-USD"
# 100.00 is aligned to the default 0.01 price tick and, at quantity
# 0.1, exactly meets the Activation 10.2 minimum-notional default
# (10.0) -- same constants Tests/test_activation10_2_crypto_quantity_
# policy.py and Tests/test_activation10_3_crypto_price_tick.py use.
CRYPTO_PRICE = 100.00


def _build_engine(tmp_dir: str, *, cash: float = 1_000_000.0):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "crypto_fee_policy.db")
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
        account_id=CRYPTO_ACCOUNT_ID,
        account_name="Crypto Fee Policy Test Account",
        mode="paper",
        currency="USD",
        asset_class="crypto",
        cash=cash,
        equity=cash,
        buying_power=cash,
    )
    # Also an IDX account, for Tests G/I (isolation/regression).
    account_repo.create(
        account_id="idx-test-id",
        account_name="IDX Test Account",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=cash,
        equity=cash,
        buying_power=cash,
    )
    # Also a US account, for Tests H/J (isolation/regression).
    account_repo.create(
        account_id="us-test-id",
        account_name="US Test Account",
        mode="paper",
        currency="USD",
        asset_class="stock_us",
        cash=cash,
        equity=cash,
        buying_power=cash,
    )

    order_lifecycle_service = OrderLifecycleService(order_repo)
    execution_service = ExecutionService(order_repo, trade_repo)
    engine = PaperTradingEngine(
        order_lifecycle_service=order_lifecycle_service,
        execution_service=execution_service,
        account_repository=account_repo,
        position_repository=position_repo,
        order_idempotency_repository=idempotency_repo,
        kill_switch_engaged=False,
        max_order_value=1_000_000_000.0,
    )
    repos = {
        "account": account_repo,
        "position": position_repo,
        "order": order_repo,
        "trade": trade_repo,
        "idempotency": idempotency_repo,
    }
    return engine, repos, manager


def _row_counts(repos) -> dict:
    return {
        "orders": len(repos["order"].list_all()),
        "trades": len(repos["trade"].list_all()),
        "positions": len(repos["position"].list_all()),
    }


def _default_kwargs(**overrides) -> dict:
    kwargs = dict(
        account_id=CRYPTO_ACCOUNT_ID,
        symbol=CRYPTO_SYMBOL,
        action="BUY",
        quantity=0.1,
        requested_price=CRYPTO_PRICE,
        executed_at="2026-08-16T10:00:00+00:00",
        signal_evidence={"note": "activation 10.4 test"},
        user_approval=True,
        idempotency_key="crypto-fee-req-001",
    )
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# A -- Crypto policy defaults
# ---------------------------------------------------------------------------


def scenario_policy_defaults():
    print("\n[Scenario A] CryptoFeePolicy defaults load correctly")
    policy = load_crypto_fee_policy(CRYPTO_SYMBOL)
    check(policy.maker_fee_rate == DEFAULT_MAKER_FEE, f"A: BTC-USD default maker_fee_rate == {DEFAULT_MAKER_FEE}")
    check(policy.taker_fee_rate == DEFAULT_TAKER_FEE, f"A: BTC-USD default taker_fee_rate == {DEFAULT_TAKER_FEE}")

    eth_policy = load_crypto_fee_policy("ETH-USD")
    check(eth_policy.maker_fee_rate == DEFAULT_MAKER_FEE, f"A: ETH-USD default maker_fee_rate == {DEFAULT_MAKER_FEE}")
    check(eth_policy.taker_fee_rate == DEFAULT_TAKER_FEE, f"A: ETH-USD default taker_fee_rate == {DEFAULT_TAKER_FEE}")

    fallback_policy = load_crypto_fee_policy("DOGE-USD")
    check(
        fallback_policy.maker_fee_rate == DEFAULT_MAKER_FEE,
        f"A: unlisted symbol fallback maker_fee_rate == {DEFAULT_MAKER_FEE}",
    )
    check(
        fallback_policy.taker_fee_rate == DEFAULT_TAKER_FEE,
        f"A: unlisted symbol fallback taker_fee_rate == {DEFAULT_TAKER_FEE}",
    )

    check(policy.fee_rate_for(MAKER) == DEFAULT_MAKER_FEE, "A: fee_rate_for(MAKER) == maker_fee_rate")
    check(policy.fee_rate_for(TAKER) == DEFAULT_TAKER_FEE, "A: fee_rate_for(TAKER) == taker_fee_rate")
    check(
        policy.fee_rate_for("garbage") == DEFAULT_TAKER_FEE,
        "A: fee_rate_for(anything-else) defaults to taker_fee_rate",
    )


# ---------------------------------------------------------------------------
# B -- Crypto policy environment override
# ---------------------------------------------------------------------------


def scenario_policy_env_override():
    print("\n[Scenario B] CryptoFeePolicy environment override is picked up on fresh load")
    os.environ["CRYPTO_BTC_USD_MAKER_FEE_RATE"] = "0.05"
    os.environ["CRYPTO_BTC_USD_TAKER_FEE_RATE"] = "0.15"
    try:
        overridden = load_crypto_fee_policy(CRYPTO_SYMBOL)
        check(overridden.maker_fee_rate == 0.05, "B: env override maker_fee_rate == 0.05")
        check(overridden.taker_fee_rate == 0.15, "B: env override taker_fee_rate == 0.15")
    finally:
        os.environ.pop("CRYPTO_BTC_USD_MAKER_FEE_RATE", None)
        os.environ.pop("CRYPTO_BTC_USD_TAKER_FEE_RATE", None)

    # Fresh load after popping the override reverts to defaults --
    # proves this policy is never cached (mirrors
    # load_crypto_quantity_policy/load_crypto_price_policy's own
    # "loaded fresh on every call" contract).
    reverted = load_crypto_fee_policy(CRYPTO_SYMBOL)
    check(
        reverted.maker_fee_rate == DEFAULT_MAKER_FEE,
        "B: policy reverts to default maker_fee_rate after env unset",
    )
    check(
        reverted.taker_fee_rate == DEFAULT_TAKER_FEE,
        "B: policy reverts to default taker_fee_rate after env unset",
    )

    # Other symbol unaffected by BTC-USD-scoped override.
    os.environ["CRYPTO_BTC_USD_MAKER_FEE_RATE"] = "0.05"
    try:
        eth_policy = load_crypto_fee_policy("ETH-USD")
        check(eth_policy.maker_fee_rate == DEFAULT_MAKER_FEE, "B: per-symbol override does not leak to ETH-USD")
    finally:
        os.environ.pop("CRYPTO_BTC_USD_MAKER_FEE_RATE", None)


# ---------------------------------------------------------------------------
# C -- Taker BUY (real engine)
# ---------------------------------------------------------------------------


def scenario_taker_buy():
    print("\n[Scenario C] real crypto BUY uses taker fee")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        account_before = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)

        os.environ["AIOS_MARKET"] = "crypto"
        try:
            trade = engine.submit_order(
                **_default_kwargs(quantity=0.1, requested_price=CRYPTO_PRICE, idempotency_key="crypto-fee-req-c")
            )
        finally:
            os.environ.pop("AIOS_MARKET", None)

        check(isinstance(trade, Trade), "C: submit_order() returns a Trade instance")
        expected_fee = DEFAULT_TAKER_FEE  # flat per-trade placeholder amount, not rate * notional
        check(abs(trade.fee - expected_fee) < 1e-9, f"C: Trade.fee == taker fee ({expected_fee}), got {trade.fee}")
        check(trade.tax == 0.0, "C: Trade.tax == 0.0 for crypto (no sell-tax leg)")

        order = repos["order"].get_by_id(trade.order_id)
        check(order is not None and order.status == "FILLED", "C: Order.status == FILLED")

        account_after = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)
        expected_cash = account_before.cash - (0.1 * CRYPTO_PRICE) - expected_fee
        check(
            abs(account_after.cash - expected_cash) < 1e-6,
            f"C: cash debited by gross_value + taker fee (expected {expected_cash}, got {account_after.cash})",
        )


# ---------------------------------------------------------------------------
# D -- Taker SELL (real engine)
# ---------------------------------------------------------------------------


def scenario_taker_sell():
    print("\n[Scenario D] real crypto SELL uses taker fee")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)

        os.environ["AIOS_MARKET"] = "crypto"
        try:
            buy_trade = engine.submit_order(
                **_default_kwargs(quantity=1.0, requested_price=CRYPTO_PRICE, idempotency_key="crypto-fee-req-d-buy")
            )
            check(isinstance(buy_trade, Trade), "D: setup BUY (1.0 BTC-USD) accepted")

            sell_trade = engine.submit_order(
                **_default_kwargs(
                    action="SELL",
                    quantity=0.5,
                    requested_price=CRYPTO_PRICE,
                    idempotency_key="crypto-fee-req-d-sell",
                )
            )
        finally:
            os.environ.pop("AIOS_MARKET", None)

        check(isinstance(sell_trade, Trade), "D: valid crypto SELL accepted")
        expected_fee = DEFAULT_TAKER_FEE  # flat per-trade placeholder amount, not rate * notional
        check(
            abs(sell_trade.fee - expected_fee) < 1e-9,
            f"D: SELL Trade.fee == taker fee ({expected_fee}), got {sell_trade.fee}",
        )
        check(sell_trade.tax == 0.0, "D: SELL Trade.tax == 0.0 for crypto (no sell-tax leg)")


# ---------------------------------------------------------------------------
# E -- Maker fee selection (policy/selection layer, no fake matching engine)
# ---------------------------------------------------------------------------


def scenario_maker_selection():
    print("\n[Scenario E] maker fee can be selected via the actual internal representation")
    execution_policy = load_execution_policy()

    taker_fee, taker_tax = resolve_fee_tax("crypto", "BUY", execution_policy, symbol=CRYPTO_SYMBOL)
    check(taker_fee == DEFAULT_TAKER_FEE, "E: resolve_fee_tax default execution_liquidity resolves taker fee")

    maker_fee, maker_tax = resolve_fee_tax(
        "crypto", "BUY", execution_policy, symbol=CRYPTO_SYMBOL, execution_liquidity=MAKER
    )
    check(maker_fee == DEFAULT_MAKER_FEE, "E: resolve_fee_tax(execution_liquidity=MAKER) resolves maker fee")
    check(maker_tax == 0.0 and taker_tax == 0.0, "E: crypto tax is 0.0 regardless of liquidity side")
    check(maker_fee != taker_fee, "E: maker and taker fees are independently selectable and distinct")

    # SELL side too -- maker/taker applies symmetrically (Requirement 4).
    maker_sell_fee, _ = resolve_fee_tax(
        "crypto", "SELL", execution_policy, symbol=CRYPTO_SYMBOL, execution_liquidity=MAKER
    )
    check(maker_sell_fee == DEFAULT_MAKER_FEE, "E: maker fee also selectable on SELL side")

    # Direct policy-object-level proof as well (no PaperTradingEngine
    # involvement at all) -- this IS the "testable without a fake
    # exchange matching engine" acceptance bar from the brief.
    custom_policy = CryptoFeePolicy(maker_fee_rate=0.07, taker_fee_rate=0.21)
    check(custom_policy.fee_rate_for(MAKER) == 0.07, "E: custom CryptoFeePolicy maker selection works")
    check(custom_policy.fee_rate_for(TAKER) == 0.21, "E: custom CryptoFeePolicy taker selection works")


# ---------------------------------------------------------------------------
# F -- Pre-trade / execution consistency
# ---------------------------------------------------------------------------


def scenario_pretrade_execution_consistency():
    print("\n[Scenario F] pre-trade required-cash fee == persisted Trade.fee")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        account_before = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)

        os.environ["AIOS_MARKET"] = "crypto"
        try:
            trade = engine.submit_order(
                **_default_kwargs(quantity=0.2, requested_price=CRYPTO_PRICE, idempotency_key="crypto-fee-req-f")
            )
        finally:
            os.environ.pop("AIOS_MARKET", None)

        account_after = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)
        gross_value = 0.2 * CRYPTO_PRICE
        actual_cash_delta = account_before.cash - account_after.cash
        # The cash debited must equal gross_value + Trade.fee + Trade.tax
        # exactly -- i.e. the same effective fee gate 8's required-cash
        # check used is the one AccountBalanceService actually applied
        # and ExecutionService actually persisted (Requirement 4).
        expected_cash_delta = gross_value + trade.fee + trade.tax
        check(
            abs(actual_cash_delta - expected_cash_delta) < 1e-9,
            "F: cash debited == gross_value + Trade.fee + Trade.tax (pre-trade and persisted fee agree)",
        )
        check(trade.fee == DEFAULT_TAKER_FEE, "F: persisted Trade.fee matches expected taker fee")


# ---------------------------------------------------------------------------
# G -- Fee isolation from IDX
# ---------------------------------------------------------------------------


def scenario_fee_isolation_from_idx():
    print("\n[Scenario G] crypto fee is isolated from non-zero IDX fee configuration")
    os.environ["EXECUTION_BUY_FEE_RATE"] = "0.05"
    os.environ["EXECUTION_SELL_FEE_RATE"] = "0.05"
    os.environ["EXECUTION_SELL_TAX_RATE"] = "0.05"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            engine, repos, _ = _build_engine(tmp)

            os.environ["AIOS_MARKET"] = "crypto"
            try:
                trade = engine.submit_order(
                    **_default_kwargs(
                        quantity=0.1, requested_price=CRYPTO_PRICE, idempotency_key="crypto-fee-req-g"
                    )
                )
            finally:
                os.environ.pop("AIOS_MARKET", None)

        expected_fee = DEFAULT_TAKER_FEE  # crypto flat taker fee amount, NOT the IDX rate
        check(
            abs(trade.fee - expected_fee) < 1e-9,
            f"G: crypto Trade.fee unaffected by non-zero IDX EXECUTION_*_RATE (expected {expected_fee}, "
            f"got {trade.fee})",
        )
        check(trade.tax == 0.0, "G: crypto Trade.tax unaffected by non-zero EXECUTION_SELL_TAX_RATE")
    finally:
        os.environ.pop("EXECUTION_BUY_FEE_RATE", None)
        os.environ.pop("EXECUTION_SELL_FEE_RATE", None)
        os.environ.pop("EXECUTION_SELL_TAX_RATE", None)


# ---------------------------------------------------------------------------
# H -- Fee isolation from US
# ---------------------------------------------------------------------------


def scenario_fee_isolation_from_us():
    print("\n[Scenario H] crypto fee is isolated from non-zero US fee configuration")
    os.environ["US_COMMISSION_RATE"] = "0.05"
    os.environ["US_REGULATORY_FEE_RATE"] = "0.05"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            engine, repos, _ = _build_engine(tmp)

            os.environ["AIOS_MARKET"] = "crypto"
            try:
                trade = engine.submit_order(
                    **_default_kwargs(
                        quantity=0.1, requested_price=CRYPTO_PRICE, idempotency_key="crypto-fee-req-h"
                    )
                )
            finally:
                os.environ.pop("AIOS_MARKET", None)

        expected_fee = DEFAULT_TAKER_FEE  # crypto flat taker fee amount, NOT the US rate
        check(
            abs(trade.fee - expected_fee) < 1e-9,
            f"H: crypto Trade.fee unaffected by non-zero US_COMMISSION_RATE (expected {expected_fee}, "
            f"got {trade.fee})",
        )
        check(trade.tax == 0.0, "H: crypto Trade.tax unaffected by non-zero US_REGULATORY_FEE_RATE")
    finally:
        os.environ.pop("US_COMMISSION_RATE", None)
        os.environ.pop("US_REGULATORY_FEE_RATE", None)


# ---------------------------------------------------------------------------
# I -- IDX regression
# ---------------------------------------------------------------------------


def scenario_idx_regression():
    print("\n[Scenario I] IDX fee behavior is unaffected by crypto fee policy")
    os.environ["EXECUTION_BUY_FEE_RATE"] = "0.001"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            engine, repos, _ = _build_engine(tmp)

            os.environ["AIOS_MARKET"] = "idx"
            try:
                trade = engine.submit_order(
                    account_id="idx-test-id",
                    symbol="BBCA",
                    action="BUY",
                    quantity=100.0,
                    requested_price=9500.0,
                    executed_at="2026-08-16T10:00:00+00:00",
                    signal_evidence={"note": "idx regression"},
                    user_approval=True,
                    idempotency_key="idx-fee-req-i",
                )
            finally:
                os.environ.pop("AIOS_MARKET", None)

        expected_fee = 0.001  # EXECUTION_BUY_FEE_RATE is a flat per-trade amount, not rate * notional
        check(isinstance(trade, Trade), "I: IDX order accepted")
        check(
            abs(trade.fee - expected_fee) < 1e-9,
            f"I: IDX Trade.fee still uses EXECUTION_BUY_FEE_RATE (expected {expected_fee}, got {trade.fee})",
        )
    finally:
        os.environ.pop("EXECUTION_BUY_FEE_RATE", None)


# ---------------------------------------------------------------------------
# J -- US regression
# ---------------------------------------------------------------------------


def scenario_us_regression():
    print("\n[Scenario J] US fee behavior is unaffected by crypto fee policy")
    os.environ["US_COMMISSION_RATE"] = "0.002"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            engine, repos, _ = _build_engine(tmp)

            os.environ["AIOS_MARKET"] = "us"
            try:
                trade = engine.submit_order(
                    account_id="us-test-id",
                    symbol="AAPL",
                    action="BUY",
                    quantity=10.0,
                    requested_price=190.0,
                    executed_at="2026-01-06T15:00:00+00:00",  # Tuesday, US regular session
                    signal_evidence={"note": "us regression"},
                    user_approval=True,
                    idempotency_key="us-fee-req-j",
                )
            finally:
                os.environ.pop("AIOS_MARKET", None)

        expected_fee = 0.002  # US_COMMISSION_RATE is a flat per-trade amount, not rate * notional
        check(isinstance(trade, Trade), "J: US order accepted")
        check(
            abs(trade.fee - expected_fee) < 1e-9,
            f"J: US Trade.fee still uses US_COMMISSION_RATE (expected {expected_fee}, got {trade.fee})",
        )
    finally:
        os.environ.pop("US_COMMISSION_RATE", None)


# ---------------------------------------------------------------------------
# K -- Reconciliation
# ---------------------------------------------------------------------------


def scenario_reconciliation():
    print("\n[Scenario K] reconciliation stays consistent after real crypto BUY/SELL")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)

        os.environ["AIOS_MARKET"] = "crypto"
        try:
            engine.submit_order(
                **_default_kwargs(quantity=1.0, requested_price=CRYPTO_PRICE, idempotency_key="crypto-fee-req-k-buy")
            )
            engine.submit_order(
                **_default_kwargs(
                    action="SELL",
                    quantity=0.5,
                    requested_price=CRYPTO_PRICE,
                    idempotency_key="crypto-fee-req-k-sell",
                )
            )
        finally:
            os.environ.pop("AIOS_MARKET", None)

        account_repo = repos["account"]
        order_repo = repos["order"]
        trade_repo = repos["trade"]
        position_repo = repos["position"]
        reconciliation_engine = ReconciliationEngine(order_repo, trade_repo, account_repo, position_repo)
        result = reconciliation_engine.reconcile_account(CRYPTO_ACCOUNT_ID, starting_cash=1_000_000.0)
        check(result.consistent is True, "K: reconcile_account() consistent == True")
        check(result.violations == [], "K: reconcile_account() violations == []")


# ---------------------------------------------------------------------------
# L -- Fee arithmetic correctness (charged exactly once)
# ---------------------------------------------------------------------------


def scenario_fee_charged_once():
    print("\n[Scenario L] fee affects cash/trade arithmetic exactly once")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        account_before = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)

        os.environ["AIOS_MARKET"] = "crypto"
        try:
            trade = engine.submit_order(
                **_default_kwargs(quantity=0.3, requested_price=CRYPTO_PRICE, idempotency_key="crypto-fee-req-l")
            )
        finally:
            os.environ.pop("AIOS_MARKET", None)

        account_after = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)
        gross_value = 0.3 * CRYPTO_PRICE
        expected_fee = DEFAULT_TAKER_FEE  # flat per-trade placeholder amount, not rate * notional
        actual_delta = account_before.cash - account_after.cash

        # If fee were double-charged, actual_delta would be
        # gross_value + 2*fee; if omitted, gross_value alone.
        check(
            abs(actual_delta - (gross_value + expected_fee)) < 1e-9,
            "L: cash impact == gross_value + fee exactly once (no double charge, no omission)",
        )
        check(
            abs(actual_delta - (gross_value + 2 * expected_fee)) > 1e-6,
            "L: cash impact is NOT gross_value + 2*fee (would indicate double charging)",
        )
        check(
            abs(actual_delta - gross_value) > 1e-6,
            "L: cash impact is NOT gross_value alone (would indicate fee omitted)",
        )
        check(trade.fee == expected_fee, "L: Trade.fee recorded exactly once, matching expected amount")


def main() -> int:
    scenario_policy_defaults()
    scenario_policy_env_override()
    scenario_taker_buy()
    scenario_taker_sell()
    scenario_maker_selection()
    scenario_pretrade_execution_consistency()
    scenario_fee_isolation_from_idx()
    scenario_fee_isolation_from_us()
    scenario_idx_regression()
    scenario_us_regression()
    scenario_reconciliation()
    scenario_fee_charged_once()

    print(f"\n{'=' * 70}")
    print(f"Activation 10.4 crypto maker/taker fee policy: {_PASS} PASS, {_FAIL} FAIL")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())