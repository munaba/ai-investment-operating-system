"""Activation 10.2 -- crypto quantity precision / step size / minimum
notional acceptance test.

Exercises ``Business.crypto_quantity_policy.CryptoQuantityPolicy`` both
directly (pure arithmetic checks) and through the real, unmodified
``Business.paper_trading_engine.PaperTradingEngine`` pre-trade
validation gate (market == "crypto" branch), against one temporary
SQLite database. Mirrors ``Tests/test_paper_trading_engine.py``'s own
``_build_engine``/``_expect_pretrade_rejection`` structure and
real-collaborators-only approach (no mocking of the engine itself).

Required test cases (see Activation 10.2 brief):

    A. valid crypto quantity is accepted
    B. quantity exceeding supported precision is rejected
    C. quantity not aligned to step size is rejected
    D. quantity x price below minimum notional is rejected
    E. quantity x price exactly at minimum notional is accepted
    F. a larger, clearly-valid order is accepted
    G. real crypto BUY creates Order/Trade/Position/Cash mutation
    H. real crypto SELL works through the existing engine
    I. every rejected order leaves Trade/Position/Cash count unchanged
    J. reconciliation stays consistent after accepted BUY/SELL
    K. IDX lot-size regression is unaffected
    L. US fractional-share regression is unaffected

Run directly: ``python Tests/test_activation10_2_crypto_quantity_policy.py``
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
from Business.execution_policy_config import load_execution_policy  # noqa: E402
from Business.crypto_quantity_policy import (  # noqa: E402
    CryptoQuantityPolicy,
    load_crypto_quantity_policy,
)
from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import (  # noqa: E402
    PRETRADE_REASON_BELOW_MINIMUM_NOTIONAL,
    PRETRADE_REASON_INVALID_LOT_SIZE,
    PaperTradingEngine,
)
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
# Business.crypto_quantity_policy module docstring). This test's
# scenario data uses the module's own default BTC-USD policy
# (step_size=0.001, quantity_precision=3, minimum_notional=10.0)
# unless a scenario explicitly overrides it via env var.
# ---------------------------------------------------------------------------

CRYPTO_ACCOUNT_ID = "crypto-test-id"
CRYPTO_SYMBOL = "BTC-USD"
CRYPTO_PRICE = 100.0  # -> minimum-notional-satisfying quantity is 0.1


def _build_engine(tmp_dir: str, *, cash: float = 1_000_000.0):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "crypto_quantity_policy.db")
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
        account_name="Crypto Test Account",
        mode="paper",
        currency="USD",
        asset_class="crypto",
        cash=cash,
        equity=cash,
        buying_power=cash,
    )
    # Also an IDX account, for Test K (regression, isolation).
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
    # Also a US account, for Test L (regression, isolation).
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
        signal_evidence={"note": "activation 10.2 test"},
        user_approval=True,
        idempotency_key="crypto-req-001",
    )
    kwargs.update(overrides)
    return kwargs


def _expect_pretrade_rejection(engine, repos, reason: str, description: str, **overrides) -> None:
    before = _row_counts(repos)
    key = overrides.get("idempotency_key", "crypto-req-001")
    idem_before = repos["idempotency"].get_by_key(key)
    account_before = repos["account"].get_by_id(overrides.get("account_id", CRYPTO_ACCOUNT_ID))
    cash_before = account_before.cash if account_before is not None else None

    raised_reason = None
    try:
        os.environ["AIOS_MARKET"] = overrides.pop("market", "crypto")
        engine.submit_order(**_default_kwargs(**overrides))
    except ValidationError as exc:
        raised_reason = exc.details.get("reason")
    finally:
        os.environ.pop("AIOS_MARKET", None)

    check(raised_reason == reason, f"{description}: ValidationError reason == '{reason}' (got {raised_reason!r})")

    after = _row_counts(repos)
    check(before == after, f"{description}: zero writes to orders/trades/positions")

    idem_after = repos["idempotency"].get_by_key(key)
    check(idem_before == idem_after, f"{description}: idempotency key state unchanged")

    account_after = repos["account"].get_by_id(overrides.get("account_id", CRYPTO_ACCOUNT_ID))
    cash_after = account_after.cash if account_after is not None else None
    check(cash_before == cash_after, f"{description}: cash unchanged")


# ---------------------------------------------------------------------------
# A/B/C/D/E/F -- pure CryptoQuantityPolicy checks
# ---------------------------------------------------------------------------


def scenario_policy_pure_checks():
    print("\n[Scenario 0] CryptoQuantityPolicy pure arithmetic checks")
    policy = load_crypto_quantity_policy(CRYPTO_SYMBOL)
    check(policy.step_size == 0.001, "BTC-USD default step_size == 0.001")
    check(policy.quantity_precision == 3, "BTC-USD default quantity_precision == 3")
    check(policy.minimum_notional == 10.0, "BTC-USD default minimum_notional == 10.0")

    # A - valid quantity
    check(policy.is_quantity_valid(0.001), "A: quantity 0.001 is valid (exact step, exact precision)")
    check(policy.is_quantity_valid(0.1), "A: quantity 0.1 is valid")

    # B - invalid precision (more decimal digits than quantity_precision allows)
    check(not policy.is_quantity_valid(0.0015), "B: quantity 0.0015 rejected (exceeds precision)")

    # C - invalid step size (independent of precision): configure a
    # symbol whose step_size does not evenly divide a quantity that
    # nonetheless satisfies quantity_precision, proving the step check
    # is not merely a restatement of the precision check.
    coarse_step_policy = CryptoQuantityPolicy(step_size=0.002, quantity_precision=3, minimum_notional=10.0)
    check(
        round(0.003, 3) == 0.003,
        "C: sanity - 0.003 satisfies quantity_precision=3",
    )
    check(
        not coarse_step_policy.is_quantity_valid(0.003),
        "C: quantity 0.003 rejected under step_size=0.002 despite satisfying precision alone",
    )
    check(
        coarse_step_policy.is_quantity_valid(0.004),
        "C: quantity 0.004 accepted under step_size=0.002 (exact multiple)",
    )

    # D - below minimum notional
    check(
        not policy.meets_minimum_notional(0.05, CRYPTO_PRICE),
        "D: 0.05 x 100.0 == 5.0 is below minimum_notional 10.0",
    )

    # E - exactly at minimum notional
    check(
        policy.meets_minimum_notional(0.1, CRYPTO_PRICE),
        "E: 0.1 x 100.0 == 10.0 meets minimum_notional 10.0 exactly",
    )

    # F - above minimum notional
    check(
        policy.meets_minimum_notional(1.0, CRYPTO_PRICE),
        "F: 1.0 x 100.0 == 100.0 is above minimum_notional 10.0",
    )


# ---------------------------------------------------------------------------
# B/C/D through the real engine (pre-trade rejection, zero mutation)
# ---------------------------------------------------------------------------


def scenario_engine_rejects_invalid_precision():
    print("\n[Scenario B] engine rejects a crypto quantity exceeding supported precision")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine,
            repos,
            PRETRADE_REASON_INVALID_LOT_SIZE,
            "Scenario B",
            quantity=0.0015,
            idempotency_key="crypto-req-b",
        )


def scenario_engine_rejects_invalid_step():
    print("\n[Scenario C] engine rejects a crypto quantity not aligned to step size")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        # 0.0025 has 4 decimal digits -> also fails BTC-USD's
        # quantity_precision=3, but every value here is at minimum
        # notional-satisfying scale; the pure-policy check above
        # (Scenario 0, Test C) already isolates step-size rejection
        # from precision rejection in complete independence. This
        # engine-level scenario proves the *wiring*: an env-var
        # override can reconfigure BTC-USD's step_size independently
        # via Business.crypto_quantity_policy.load_crypto_quantity_policy.
        os.environ["CRYPTO_BTC_USD_STEP_SIZE"] = "0.002"
        os.environ["CRYPTO_BTC_USD_QUANTITY_PRECISION"] = "3"
        try:
            _expect_pretrade_rejection(
                engine,
                repos,
                PRETRADE_REASON_INVALID_LOT_SIZE,
                "Scenario C",
                quantity=0.003,
                requested_price=CRYPTO_PRICE,
                idempotency_key="crypto-req-c",
            )
        finally:
            os.environ.pop("CRYPTO_BTC_USD_STEP_SIZE", None)
            os.environ.pop("CRYPTO_BTC_USD_QUANTITY_PRECISION", None)


def scenario_engine_rejects_below_minimum_notional():
    print("\n[Scenario D] engine rejects a crypto order below minimum notional")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine,
            repos,
            PRETRADE_REASON_BELOW_MINIMUM_NOTIONAL,
            "Scenario D",
            quantity=0.05,
            requested_price=CRYPTO_PRICE,
            idempotency_key="crypto-req-d",
        )


# ---------------------------------------------------------------------------
# E/F/G/H/I/J -- happy path through the real engine
# ---------------------------------------------------------------------------


def scenario_engine_accepts_exact_minimum_notional_buy():
    print("\n[Scenario E/G] engine accepts BUY exactly at minimum notional -> Order/Trade/Position/Cash")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        account_before = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)

        os.environ["AIOS_MARKET"] = "crypto"
        try:
            trade = engine.submit_order(
                **_default_kwargs(quantity=0.1, requested_price=CRYPTO_PRICE, idempotency_key="crypto-req-e")
            )
        finally:
            os.environ.pop("AIOS_MARKET", None)

        check(isinstance(trade, Trade), "E/G: submit_order() returns a Trade instance")
        check(trade.quantity == 0.1, "E/G: Trade.quantity == 0.1 (exact minimum-notional quantity)")
        check(trade.symbol == CRYPTO_SYMBOL, "E/G: Trade.symbol == BTC-USD")
        check(trade.action == "BUY", "E/G: Trade.action == BUY")

        order = repos["order"].get_by_id(trade.order_id)
        check(order is not None and order.status == "FILLED", "G: Order.status == FILLED")

        trades = repos["trade"].list_by_order(trade.order_id)
        check(len(trades) == 1, "G: exactly one Trade row exists for the order")

        position = repos["position"].get_open_position(CRYPTO_ACCOUNT_ID, CRYPTO_SYMBOL)
        check(position is not None and position.quantity == 0.1, "G: Position opened with quantity 0.1")

        account_after = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)
        check(account_after.cash < account_before.cash, "G: Cash mutation applied (cash decreased on BUY)")
        # Activation 10.4 (crypto maker/taker fee): crypto BUY/SELL now
        # carries a non-zero default taker fee (see
        # Business.crypto_fee_policy._DEFAULT_CRYPTO_FEE_POLICIES) --
        # this assertion is updated to account for that fee, using the
        # same shared Business.us_market_policy.resolve_fee_tax()
        # selection function PaperTradingEngine/ExecutionService
        # themselves use, rather than re-asserting the pre-10.4
        # zero-fee assumption. gross_value + fee (+ 0.0 tax for
        # crypto) is exactly Business.account_balance_service.
        # compute_buy_required_cash()'s own formula.
        buy_fee, buy_tax = resolve_fee_tax("crypto", "BUY", load_execution_policy(), symbol=CRYPTO_SYMBOL)
        check(
            account_after.cash == account_before.cash - (0.1 * CRYPTO_PRICE) - buy_fee - buy_tax,
            "G: Cash decreased by exactly the order's gross value plus crypto taker fee/tax "
            "(Activation 10.4 default fee, no longer 0.0)",
        )


def scenario_engine_accepts_larger_valid_buy_then_sell():
    print("\n[Scenario F/H/I/J] larger BUY, then SELL, reconciliation stays consistent")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, manager = _build_engine(tmp)

        os.environ["AIOS_MARKET"] = "crypto"
        try:
            buy_trade = engine.submit_order(
                **_default_kwargs(quantity=1.0, requested_price=CRYPTO_PRICE, idempotency_key="crypto-req-f")
            )
            check(isinstance(buy_trade, Trade), "F: larger valid BUY (1.0 BTC-USD) accepted")

            # I - attempt an invalid SELL first (below minimum notional
            # on the SELL side too, per Requirement 4), prove it is
            # rejected with zero Trade/Position mutation beyond the
            # BUY above.
            before = _row_counts(repos)
            raised = None
            try:
                engine.submit_order(
                    **_default_kwargs(
                        action="SELL",
                        quantity=0.05,
                        requested_price=CRYPTO_PRICE,
                        idempotency_key="crypto-req-i-sell",
                    )
                )
            except ValidationError as exc:
                raised = exc.details.get("reason")
            check(
                raised == PRETRADE_REASON_BELOW_MINIMUM_NOTIONAL,
                "I: below-minimum-notional SELL also rejected (Requirement 4)",
            )
            after = _row_counts(repos)
            check(before == after, "I: rejected SELL leaves Trade/Position counts unchanged")

            # H - a valid SELL
            sell_trade = engine.submit_order(
                **_default_kwargs(
                    action="SELL",
                    quantity=0.5,
                    requested_price=CRYPTO_PRICE,
                    idempotency_key="crypto-req-h",
                )
            )
            check(isinstance(sell_trade, Trade), "H: valid crypto SELL accepted")
            check(sell_trade.action == "SELL", "H: Trade.action == SELL")

            position = repos["position"].get_open_position(CRYPTO_ACCOUNT_ID, CRYPTO_SYMBOL)
            check(
                position is not None and abs(position.quantity - 0.5) < 1e-9,
                "H: Position reduced to 0.5 after SELL",
            )
        finally:
            os.environ.pop("AIOS_MARKET", None)

        # J - reconciliation
        account_repo = repos["account"]
        order_repo = repos["order"]
        trade_repo = repos["trade"]
        position_repo = repos["position"]
        reconciliation_engine = ReconciliationEngine(order_repo, trade_repo, account_repo, position_repo)
        account = account_repo.get_by_id(CRYPTO_ACCOUNT_ID)
        result = reconciliation_engine.reconcile_account(CRYPTO_ACCOUNT_ID, starting_cash=1_000_000.0)
        check(result.consistent is True, f"J: reconcile_account('{CRYPTO_ACCOUNT_ID}') consistent == True")
        check(result.violations == [], f"J: reconcile_account('{CRYPTO_ACCOUNT_ID}') violations == []")


# ---------------------------------------------------------------------------
# K/L -- IDX and US regression / isolation
# ---------------------------------------------------------------------------


def scenario_idx_lot_rule_unaffected():
    print("\n[Scenario K] IDX lot-size rule is unaffected by crypto quantity policy")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)

        os.environ["AIOS_MARKET"] = "idx"
        try:
            # A quantity that would be perfectly valid under the crypto
            # policy (0.1) must still be rejected under IDX's 100-share
            # lot rule -- proves crypto's policy has not leaked into IDX.
            before = _row_counts(repos)
            raised = None
            try:
                engine.submit_order(
                    account_id="idx-test-id",
                    symbol="BBCA",
                    action="BUY",
                    quantity=0.1,
                    requested_price=9500.0,
                    executed_at="2026-08-16T10:00:00+00:00",
                    signal_evidence={"note": "idx regression"},
                    user_approval=True,
                    idempotency_key="idx-req-k-invalid",
                )
            except ValidationError as exc:
                raised = exc.details.get("reason")
            check(raised == PRETRADE_REASON_INVALID_LOT_SIZE, "K: fractional quantity rejected under IDX lot rule")
            after = _row_counts(repos)
            check(before == after, "K: rejected IDX order leaves Trade/Position counts unchanged")

            # A valid IDX lot (100 shares) still works.
            trade = engine.submit_order(
                account_id="idx-test-id",
                symbol="BBCA",
                action="BUY",
                quantity=100.0,
                requested_price=9500.0,
                executed_at="2026-08-16T10:00:00+00:00",
                signal_evidence={"note": "idx regression valid"},
                user_approval=True,
                idempotency_key="idx-req-k-valid",
            )
            check(isinstance(trade, Trade), "K: valid 100-share IDX lot still accepted")
            check(trade.quantity == 100.0, "K: Trade.quantity == 100.0 (unchanged IDX behavior)")
        finally:
            os.environ.pop("AIOS_MARKET", None)


def scenario_us_fractional_policy_unaffected():
    print("\n[Scenario L] US fractional-share policy is unaffected by crypto quantity policy")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)

        os.environ["AIOS_MARKET"] = "us"
        os.environ.pop("US_FRACTIONAL_SHARES_ENABLED", None)
        os.environ.pop("US_FRACTIONAL_MIN_QUANTITY", None)
        os.environ.pop("US_FRACTIONAL_QUANTITY_PRECISION", None)
        try:
            # Default US policy: fractional disabled, whole shares only.
            # A crypto-policy-valid quantity (0.1) must still be
            # rejected on the US market -- proves no leak either way.
            before = _row_counts(repos)
            raised = None
            try:
                engine.submit_order(
                    account_id="us-test-id",
                    symbol="AAPL",
                    action="BUY",
                    quantity=0.1,
                    requested_price=190.0,
                    executed_at="2026-01-06T15:00:00+00:00",  # Tuesday, US regular session
                    signal_evidence={"note": "us regression"},
                    user_approval=True,
                    idempotency_key="us-req-l-invalid",
                )
            except ValidationError as exc:
                raised = exc.details.get("reason")
            check(raised == PRETRADE_REASON_INVALID_LOT_SIZE, "L: fractional quantity rejected under default US policy")
            after = _row_counts(repos)
            check(before == after, "L: rejected US order leaves Trade/Position counts unchanged")

            # A valid whole-share US order still works.
            trade = engine.submit_order(
                account_id="us-test-id",
                symbol="AAPL",
                action="BUY",
                quantity=10.0,
                requested_price=190.0,
                executed_at="2026-01-06T15:00:00+00:00",
                signal_evidence={"note": "us regression valid"},
                user_approval=True,
                idempotency_key="us-req-l-valid",
            )
            check(isinstance(trade, Trade), "L: valid whole-share US order still accepted")
            check(trade.quantity == 10.0, "L: Trade.quantity == 10.0 (unchanged US behavior)")
        finally:
            os.environ.pop("AIOS_MARKET", None)


def main() -> int:
    scenario_policy_pure_checks()
    scenario_engine_rejects_invalid_precision()
    scenario_engine_rejects_invalid_step()
    scenario_engine_rejects_below_minimum_notional()
    scenario_engine_accepts_exact_minimum_notional_buy()
    scenario_engine_accepts_larger_valid_buy_then_sell()
    scenario_idx_lot_rule_unaffected()
    scenario_us_fractional_policy_unaffected()

    print(f"\n{'=' * 70}")
    print(f"Activation 10.2 crypto quantity policy: {_PASS} PASS, {_FAIL} FAIL")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())