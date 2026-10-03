"""Activation 10.3 -- crypto price tick acceptance test.

Exercises ``Business.crypto_price_policy.CryptoPricePolicy`` both
directly (pure arithmetic check) and through the real, unmodified
``Business.paper_trading_engine.PaperTradingEngine`` pre-trade
validation gate (market == "crypto" branch), against one temporary
SQLite database. Mirrors ``Tests/
test_activation10_2_crypto_quantity_policy.py``'s own
``_build_engine``/``_expect_pretrade_rejection`` structure and
real-collaborators-only approach (no mocking of the engine itself).

Required test cases (see Activation 10.3 brief):

    A. a price exactly aligned to the configured tick is accepted
    B. a price between ticks is rejected
    C. precision-safe (Decimal) comparison behaves deterministically
    D. real crypto BUY reaches the engine with a valid tick price
    E. real crypto SELL reaches the engine with a valid tick price
    F. a rejected price creates no Order/Trade/Cash/Position mutation
    G. price tick and minimum-notional validation do not conflict --
       a valid-tick price below minimum notional fails for minimum
       notional, not price tick; an invalid-tick price that also
       produces a small notional fails for price tick (checked first,
       per the existing gate sequence)
    H. Activation 10.2 quantity-policy regression is unaffected
    I. IDX price behavior is unaffected
    J. US (Activation 9) price/order behavior is unaffected

Run directly: ``python Tests/test_activation10_3_crypto_price_tick.py``
-- no external test framework required, matching every other
``Tests/test_*.py`` script in this suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.account_balance_service import AccountBalanceService  # noqa: E402
from Business.crypto_price_policy import (  # noqa: E402
    CryptoPricePolicy,
    load_crypto_price_policy,
)
from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import (  # noqa: E402
    PRETRADE_REASON_BELOW_MINIMUM_NOTIONAL,
    PRETRADE_REASON_INVALID_PRICE_TICK,
    PaperTradingEngine,
)
from Business.position_manager import PositionManager  # noqa: E402
from Business.reconciliation_engine import ReconciliationEngine  # noqa: E402

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
# Business.crypto_price_policy module docstring). This test's scenario
# data uses the module's own default BTC-USD policy (price_tick=0.01)
# unless a scenario explicitly overrides it via env var.
# ---------------------------------------------------------------------------

CRYPTO_ACCOUNT_ID = "crypto-price-tick-test-id"
CRYPTO_SYMBOL = "BTC-USD"
# 100.00 is aligned to a 0.01 tick and, at quantity 0.1, exactly meets
# the Activation 10.2 minimum-notional default (10.0) -- same
# constants Tests/test_activation10_2_crypto_quantity_policy.py uses,
# reused deliberately so the two Activations' defaults are proven
# mutually compatible (Requirement 4 of the Activation 10.3 brief).
CRYPTO_PRICE = 100.00


def _build_engine(tmp_dir: str, *, cash: float = 1_000_000.0):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "crypto_price_tick.db")
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
        account_name="Crypto Price Tick Test Account",
        mode="paper",
        currency="USD",
        asset_class="crypto",
        cash=cash,
        equity=cash,
        buying_power=cash,
    )
    # Also an IDX account, for Test I (regression, isolation).
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
    # Also a US account, for Test J (regression, isolation).
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
        signal_evidence={"note": "activation 10.3 test"},
        user_approval=True,
        idempotency_key="crypto-tick-req-001",
    )
    kwargs.update(overrides)
    return kwargs


def _expect_pretrade_rejection(engine, repos, reason: str, description: str, **overrides) -> None:
    before = _row_counts(repos)
    key = overrides.get("idempotency_key", "crypto-tick-req-001")
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
# A/B/C -- pure CryptoPricePolicy checks
# ---------------------------------------------------------------------------


def scenario_policy_pure_checks():
    print("\n[Scenario 0] CryptoPricePolicy pure arithmetic checks")
    policy = load_crypto_price_policy(CRYPTO_SYMBOL)
    check(policy.price_tick == 0.01, "BTC-USD default price_tick == 0.01")

    # A - valid aligned price
    check(policy.is_price_valid(100.00), "A: price 100.00 is valid (exact tick multiple)")
    check(policy.is_price_valid(0.01), "A: price 0.01 is valid (one tick)")

    # B - invalid tick (price between ticks)
    check(not policy.is_price_valid(100.005), "B: price 100.005 rejected (between ticks)")
    check(not policy.is_price_valid(0.015), "B: price 0.015 rejected (between ticks)")

    # C - precision-safe comparison: values where naive binary float
    # modulo could misbehave (0.1 + 0.2 != 0.3 territory), proven
    # deterministic via Decimal(str(x)).
    tricky_policy = CryptoPricePolicy(price_tick=0.1)
    check(
        tricky_policy.is_price_valid(0.3),
        "C: price 0.3 valid under price_tick=0.1 (Decimal-safe -- naive float modulo would misfire here)",
    )
    check(
        tricky_policy.is_price_valid(35.7),
        "C: price 35.7 valid under price_tick=0.1 (357 exact ticks, Decimal-safe)",
    )
    check(
        not tricky_policy.is_price_valid(35.75),
        "C: price 35.75 rejected under price_tick=0.1 (not an exact tick multiple)",
    )

    # Non-positive / non-numeric defensive checks.
    check(not policy.is_price_valid(-100.00), "price policy rejects a negative price")
    check(not policy.is_price_valid(0.0), "price policy rejects a zero price")


# ---------------------------------------------------------------------------
# B through the real engine (pre-trade rejection, zero mutation)
# ---------------------------------------------------------------------------


def scenario_engine_rejects_invalid_tick():
    print("\n[Scenario B] engine rejects a crypto price not aligned to the configured tick")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine,
            repos,
            PRETRADE_REASON_INVALID_PRICE_TICK,
            "Scenario B",
            quantity=0.1,
            requested_price=100.005,
            idempotency_key="crypto-tick-req-b",
        )


def scenario_engine_rejects_invalid_tick_env_override():
    print("\n[Scenario B2] engine rejects an off-tick price under an env-var override tick")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        os.environ["CRYPTO_BTC_USD_PRICE_TICK"] = "0.5"
        try:
            _expect_pretrade_rejection(
                engine,
                repos,
                PRETRADE_REASON_INVALID_PRICE_TICK,
                "Scenario B2",
                quantity=0.1,
                requested_price=100.25,
                idempotency_key="crypto-tick-req-b2",
            )
        finally:
            os.environ.pop("CRYPTO_BTC_USD_PRICE_TICK", None)


# ---------------------------------------------------------------------------
# A/D/E -- happy path through the real engine
# ---------------------------------------------------------------------------


def scenario_engine_accepts_valid_tick_buy():
    print("\n[Scenario A/D] engine accepts BUY with a valid tick price -> Order/Trade/Position/Cash")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        account_before = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)

        os.environ["AIOS_MARKET"] = "crypto"
        try:
            trade = engine.submit_order(
                **_default_kwargs(quantity=0.1, requested_price=CRYPTO_PRICE, idempotency_key="crypto-tick-req-a")
            )
        finally:
            os.environ.pop("AIOS_MARKET", None)

        check(isinstance(trade, Trade), "A/D: submit_order() returns a Trade instance")
        check(trade.action == "BUY", "D: Trade.action == BUY")
        check(trade.fill_price == CRYPTO_PRICE, "A: Trade.fill_price == exact tick-aligned price")

        order = repos["order"].get_by_id(trade.order_id)
        check(order is not None and order.status == "FILLED", "D: Order.status == FILLED")

        position = repos["position"].get_open_position(CRYPTO_ACCOUNT_ID, CRYPTO_SYMBOL)
        check(position is not None and position.quantity == 0.1, "D: Position opened with quantity 0.1")

        account_after = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)
        check(account_after.cash < account_before.cash, "D: Cash mutation applied (cash decreased on BUY)")


def scenario_engine_accepts_valid_tick_sell():
    print("\n[Scenario E] engine accepts SELL with a valid tick price")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, manager = _build_engine(tmp)

        os.environ["AIOS_MARKET"] = "crypto"
        try:
            buy_trade = engine.submit_order(
                **_default_kwargs(quantity=1.0, requested_price=CRYPTO_PRICE, idempotency_key="crypto-tick-req-e-buy")
            )
            check(isinstance(buy_trade, Trade), "E: setup BUY (1.0 BTC-USD) accepted")

            sell_trade = engine.submit_order(
                **_default_kwargs(
                    action="SELL",
                    quantity=0.5,
                    requested_price=CRYPTO_PRICE,
                    idempotency_key="crypto-tick-req-e-sell",
                )
            )
            check(isinstance(sell_trade, Trade), "E: valid tick-price crypto SELL accepted")
            check(sell_trade.action == "SELL", "E: Trade.action == SELL")

            position = repos["position"].get_open_position(CRYPTO_ACCOUNT_ID, CRYPTO_SYMBOL)
            check(
                position is not None and abs(position.quantity - 0.5) < 1e-9,
                "E: Position reduced to 0.5 after SELL",
            )
        finally:
            os.environ.pop("AIOS_MARKET", None)

        # Reconciliation stays consistent (mirrors Activation 10.2's
        # own Test J).
        account_repo = repos["account"]
        order_repo = repos["order"]
        trade_repo = repos["trade"]
        position_repo = repos["position"]
        reconciliation_engine = ReconciliationEngine(order_repo, trade_repo, account_repo, position_repo)
        result = reconciliation_engine.reconcile_account(CRYPTO_ACCOUNT_ID, starting_cash=1_000_000.0)
        check(result.consistent is True, "Reconciliation: reconcile_account() consistent == True")
        check(result.violations == [], "Reconciliation: reconcile_account() violations == []")


# ---------------------------------------------------------------------------
# F -- rejected price creates no order (covered structurally by
# _expect_pretrade_rejection in Scenarios B/B2 above, and explicitly
# re-asserted here against a fresh engine for clarity).
# ---------------------------------------------------------------------------


def scenario_rejected_price_creates_no_order():
    print("\n[Scenario F] rejected off-tick price leaves order/trade/cash/position counts unchanged")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        before = _row_counts(repos)
        account_before = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)

        raised = None
        os.environ["AIOS_MARKET"] = "crypto"
        try:
            engine.submit_order(
                **_default_kwargs(quantity=0.1, requested_price=99.999, idempotency_key="crypto-tick-req-f")
            )
        except ValidationError as exc:
            raised = exc.details.get("reason")
        finally:
            os.environ.pop("AIOS_MARKET", None)

        check(raised == PRETRADE_REASON_INVALID_PRICE_TICK, "F: rejected for INVALID_PRICE_TICK")
        after = _row_counts(repos)
        check(before == after, "F: Order/Trade/Position counts unchanged")
        account_after = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)
        check(account_before.cash == account_after.cash, "F: Cash unchanged")


# ---------------------------------------------------------------------------
# G -- price tick / minimum-notional gate-ordering interaction
# ---------------------------------------------------------------------------


def scenario_tick_and_minimum_notional_interaction():
    print("\n[Scenario G] price tick and minimum-notional validation do not conflict")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)

        # G1: a valid-tick price whose notional is below the
        # configured minimum must fail for minimum-notional, not tick.
        _expect_pretrade_rejection(
            engine,
            repos,
            PRETRADE_REASON_BELOW_MINIMUM_NOTIONAL,
            "Scenario G1 (valid tick, below minimum notional)",
            quantity=0.05,
            requested_price=CRYPTO_PRICE,  # tick-aligned; 0.05 * 100.00 == 5.0 < 10.0 minimum
            idempotency_key="crypto-tick-req-g1",
        )

        # G2: an invalid-tick price that also produces a small
        # notional must fail for price tick first -- price-tick is
        # checked immediately after gate 7, before minimum-notional,
        # per the existing (now-extended) gate sequence.
        _expect_pretrade_rejection(
            engine,
            repos,
            PRETRADE_REASON_INVALID_PRICE_TICK,
            "Scenario G2 (invalid tick, also small notional)",
            quantity=0.05,
            requested_price=99.995,  # off-tick AND 0.05 * 99.995 < 10.0
            idempotency_key="crypto-tick-req-g2",
        )


# ---------------------------------------------------------------------------
# H -- Activation 10.2 quantity-policy regression
# ---------------------------------------------------------------------------


def scenario_quantity_policy_regression():
    print("\n[Scenario H] Activation 10.2 quantity-policy regression suite")
    result = subprocess.run(
        [sys.executable, str(_PROJECT_ROOT / "Tests" / "test_activation10_2_crypto_quantity_policy.py")],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    check(result.returncode == 0, "H: Tests/test_activation10_2_crypto_quantity_policy.py exits 0 (all PASS)")
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-4000:])


# ---------------------------------------------------------------------------
# I/J -- IDX and US regression / isolation
# ---------------------------------------------------------------------------


def scenario_idx_price_behavior_unaffected():
    print("\n[Scenario I] IDX price behavior is unaffected by crypto price-tick policy")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)

        os.environ["AIOS_MARKET"] = "idx"
        try:
            # An IDX price that would be "off-tick" under the crypto
            # BTC-USD default (0.01) is not even checked for
            # market == "idx" -- proves crypto's price-tick policy has
            # not leaked into IDX. Use a price with sub-cent precision
            # that only a crypto tick check would reject.
            trade = engine.submit_order(
                account_id="idx-test-id",
                symbol="BBCA",
                action="BUY",
                quantity=100.0,
                requested_price=9500.005,
                executed_at="2026-08-16T10:00:00+00:00",
                signal_evidence={"note": "idx regression"},
                user_approval=True,
                idempotency_key="idx-tick-req-i",
            )
            check(isinstance(trade, Trade), "I: IDX order with sub-cent price accepted (no crypto tick leak)")
            check(trade.quantity == 100.0, "I: Trade.quantity == 100.0 (unchanged IDX behavior)")
        finally:
            os.environ.pop("AIOS_MARKET", None)


def scenario_us_price_behavior_unaffected():
    print("\n[Scenario J] US (Activation 9) price/order behavior is unaffected by crypto price-tick policy")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)

        os.environ["AIOS_MARKET"] = "us"
        try:
            trade = engine.submit_order(
                account_id="us-test-id",
                symbol="AAPL",
                action="BUY",
                quantity=10.0,
                requested_price=190.005,
                executed_at="2026-01-06T15:00:00+00:00",  # Tuesday, US regular session
                signal_evidence={"note": "us regression"},
                user_approval=True,
                idempotency_key="us-tick-req-j",
            )
            check(isinstance(trade, Trade), "J: US order with sub-cent price accepted (no crypto tick leak)")
            check(trade.quantity == 10.0, "J: Trade.quantity == 10.0 (unchanged US behavior)")
        finally:
            os.environ.pop("AIOS_MARKET", None)


def main() -> int:
    scenario_policy_pure_checks()
    scenario_engine_rejects_invalid_tick()
    scenario_engine_rejects_invalid_tick_env_override()
    scenario_engine_accepts_valid_tick_buy()
    scenario_engine_accepts_valid_tick_sell()
    scenario_rejected_price_creates_no_order()
    scenario_tick_and_minimum_notional_interaction()
    scenario_quantity_policy_regression()
    scenario_idx_price_behavior_unaffected()
    scenario_us_price_behavior_unaffected()

    print(f"\n{'=' * 70}")
    print(f"Activation 10.3 crypto price tick: {_PASS} PASS, {_FAIL} FAIL")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())