"""Activation 10.6 -- crypto exchange availability policy acceptance
test.

Exercises ``Business.crypto_exchange_availability_policy.
CryptoExchangeAvailabilityPolicy`` both directly (pure checks) and
through the real, unmodified ``Business.paper_trading_engine.
PaperTradingEngine`` pre-trade validation gate (market == "crypto"
branch, gate 19). Mirrors ``Tests/
test_activation10_5_crypto_24_7_policy.py``'s own ``_build_engine``/
real-collaborators-only structure (no mocking of the engine itself).

Required test cases (see Activation 10.6 brief):

    A. default available -> crypto BUY continues to work
    B. explicit unavailable -> crypto BUY rejected, zero financial-
       state mutation
    C. recovery -> same valid crypto BUY succeeds once available again
    D. SELL unavailable -> rejected with zero financial-state mutation
       (position pre-created while available)
    E. IDX isolation -> IDX behavior unchanged with crypto unavailable
    F. US isolation -> US behavior unchanged with crypto unavailable
    G. market/availability distinction -> CryptoMarketPolicy allows
       trading while CryptoExchangeAvailabilityPolicy reports
       unavailable, independently
    H. environment/config restoration between scenarios
    I. Activation 10.1 regression
    J. Activation 10.5 regression

Configuration tests: unset -> available, "true" -> available,
"false" -> unavailable, invalid -> ConfigurationError.

Run directly:
``python Tests/test_activation10_6_crypto_exchange_availability.py``
-- no external test framework required, matching every other
``Tests/test_*.py`` script in this suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.account_balance_service import AccountBalanceService  # noqa: E402
from Business.crypto_exchange_availability_policy import (  # noqa: E402
    CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR,
    CryptoExchangeAvailabilityPolicy,
    load_crypto_exchange_availability_policy,
)
from Business.crypto_market_policy import (  # noqa: E402
    CryptoMarketPolicy,
    load_crypto_market_policy,
)
from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import (  # noqa: E402
    PRETRADE_REASON_CRYPTO_EXCHANGE_UNAVAILABLE,
    PaperTradingEngine,
)
from Business.position_manager import PositionManager  # noqa: E402
from Business.reconciliation_engine import ReconciliationEngine  # noqa: E402

from Core.config import config as _config  # noqa: E402
from Core.exceptions import ConfigurationError, ValidationError  # noqa: E402

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
# NOTE -- AIOS paper-market injected/configurable state, not a live
# exchange signal (see Business.crypto_exchange_availability_policy
# module docstring).
# ---------------------------------------------------------------------------

CRYPTO_ACCOUNT_ID = "crypto-exchange-avail-test-id"
CRYPTO_SYMBOL = "BTC-USD"
CRYPTO_PRICE = 100.00
CRYPTO_QTY = 0.1
EXECUTED_AT = "2026-08-17T10:00:00+00:00"  # Monday, well within 24/7 policy


def _clear_env() -> None:
    os.environ.pop(CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR, None)
    os.environ.pop("AIOS_MARKET", None)


def _build_engine(tmp_dir: str, *, cash: float = 1_000_000.0):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "crypto_exchange_avail.db")
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
        account_name="Crypto Exchange Availability Test Account",
        mode="paper",
        currency="USD",
        asset_class="crypto",
        cash=cash,
        equity=cash,
        buying_power=cash,
    )
    # Also an IDX account, for the IDX isolation scenario.
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
    # Also a US account, for the US isolation scenario.
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


def _submit_crypto(engine, *, idempotency_key: str, action: str = "BUY", quantity: float = CRYPTO_QTY):
    os.environ["AIOS_MARKET"] = "crypto"
    try:
        return engine.submit_order(
            account_id=CRYPTO_ACCOUNT_ID,
            symbol=CRYPTO_SYMBOL,
            action=action,
            quantity=quantity,
            requested_price=CRYPTO_PRICE,
            executed_at=EXECUTED_AT,
            signal_evidence={"note": "activation 10.6 test"},
            user_approval=True,
            idempotency_key=idempotency_key,
        )
    finally:
        os.environ.pop("AIOS_MARKET", None)


# ---------------------------------------------------------------------------
# G -- pure policy checks: market vs availability independence
# ---------------------------------------------------------------------------


def scenario_market_vs_availability_distinction():
    print("\n[Scenario G] CryptoMarketPolicy and CryptoExchangeAvailabilityPolicy are independent")
    _clear_env()
    try:
        market_policy = load_crypto_market_policy()
        check(isinstance(market_policy, CryptoMarketPolicy), "load_crypto_market_policy() returns a CryptoMarketPolicy")
        moment = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
        check(market_policy.is_trading_allowed(moment) is True, "G: CryptoMarketPolicy allows trading (24/7, unaffected)")

        os.environ[CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR] = "false"
        try:
            availability_policy = load_crypto_exchange_availability_policy()
        finally:
            _clear_env()
        check(
            isinstance(availability_policy, CryptoExchangeAvailabilityPolicy),
            "load_crypto_exchange_availability_policy() returns a CryptoExchangeAvailabilityPolicy",
        )
        check(availability_policy.is_available() is False, "G: CryptoExchangeAvailabilityPolicy reports unavailable")
        # Re-check market policy is untouched by the availability override.
        check(
            market_policy.is_trading_allowed(moment) is True,
            "G: CryptoMarketPolicy still allows trading -- independent of availability override",
        )
    finally:
        _clear_env()


# ---------------------------------------------------------------------------
# Direct pure CryptoExchangeAvailabilityPolicy checks + config tests
# ---------------------------------------------------------------------------


def scenario_policy_pure_checks_and_config():
    print("\n[Scenario Config] CryptoExchangeAvailabilityPolicy direct checks + configuration parsing")
    _clear_env()
    try:
        # unset -> available
        policy = load_crypto_exchange_availability_policy()
        check(policy.is_available() is True, "Config: unset env var -> available == True")

        # "true" -> available
        os.environ[CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR] = "true"
        policy_true = load_crypto_exchange_availability_policy()
        check(policy_true.is_available() is True, 'Config: "true" -> available == True')

        # "false" -> unavailable
        os.environ[CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR] = "false"
        policy_false = load_crypto_exchange_availability_policy()
        check(policy_false.is_available() is False, 'Config: "false" -> available == False')

        # invalid -> ConfigurationError, not silently treated as False
        os.environ[CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR] = "abc"
        raised = None
        try:
            load_crypto_exchange_availability_policy()
        except ConfigurationError:
            raised = True
        check(raised is True, 'Config: "abc" raises ConfigurationError (never silently False)')

        # Direct value-object checks.
        check(CryptoExchangeAvailabilityPolicy(available=True).is_available() is True, "Direct: available=True -> is_available() True")
        check(CryptoExchangeAvailabilityPolicy(available=False).is_available() is False, "Direct: available=False -> is_available() False")
    finally:
        _clear_env()


# ---------------------------------------------------------------------------
# A -- default available
# ---------------------------------------------------------------------------


def scenario_default_available():
    print("\n[Scenario A] default available -> crypto BUY continues to work")
    _clear_env()
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        try:
            trade = _submit_crypto(engine, idempotency_key="crypto-avail-a")
            check(isinstance(trade, Trade), "A: crypto BUY accepted with no availability override (default available)")
        finally:
            _clear_env()


# ---------------------------------------------------------------------------
# B -- explicit unavailable
# ---------------------------------------------------------------------------


def scenario_explicit_unavailable():
    print("\n[Scenario B] explicit unavailable -> crypto BUY rejected, zero financial-state mutation")
    _clear_env()
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        before = _row_counts(repos)
        account_before = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)

        os.environ[CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR] = "false"
        raised = None
        try:
            _submit_crypto(engine, idempotency_key="crypto-avail-b")
        except ValidationError as exc:
            raised = exc.details.get("reason")
        finally:
            _clear_env()

        check(
            raised == PRETRADE_REASON_CRYPTO_EXCHANGE_UNAVAILABLE,
            f"B: rejected under CRYPTO_EXCHANGE_UNAVAILABLE (got {raised!r})",
        )
        after = _row_counts(repos)
        check(before == after, "B: Order/Trade/Position counts unchanged")
        account_after = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)
        check(account_before.cash == account_after.cash, "B: Cash unchanged")


# ---------------------------------------------------------------------------
# C -- recovery
# ---------------------------------------------------------------------------


def scenario_recovery():
    print("\n[Scenario C] recovery -- same valid crypto BUY succeeds once available again")
    _clear_env()
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)

        os.environ[CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR] = "false"
        raised = None
        try:
            _submit_crypto(engine, idempotency_key="crypto-avail-c-blocked")
        except ValidationError as exc:
            raised = exc.details.get("reason")
        finally:
            _clear_env()
        check(raised == PRETRADE_REASON_CRYPTO_EXCHANGE_UNAVAILABLE, "C: initial BUY rejected while unavailable")

        # Recovery: no override set (defaults to available) -> BUY succeeds.
        try:
            trade = _submit_crypto(engine, idempotency_key="crypto-avail-c-recovered")
            check(isinstance(trade, Trade), "C: same BUY succeeds once availability restored")
        finally:
            _clear_env()


# ---------------------------------------------------------------------------
# D -- SELL unavailable
# ---------------------------------------------------------------------------


def scenario_sell_unavailable():
    print("\n[Scenario D] SELL unavailable -> rejected with zero financial-state mutation")
    _clear_env()
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)

        # Pre-create a position while available.
        try:
            buy_trade = _submit_crypto(engine, idempotency_key="crypto-avail-d-buy", action="BUY", quantity=1.0)
            check(isinstance(buy_trade, Trade), "D: setup BUY (1.0 BTC-USD) accepted while available")
        finally:
            _clear_env()

        before = _row_counts(repos)
        account_before = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)
        position_before = repos["position"].get_open_position(CRYPTO_ACCOUNT_ID, CRYPTO_SYMBOL)

        os.environ[CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR] = "false"
        raised = None
        try:
            _submit_crypto(engine, idempotency_key="crypto-avail-d-sell", action="SELL", quantity=0.5)
        except ValidationError as exc:
            raised = exc.details.get("reason")
        finally:
            _clear_env()

        check(
            raised == PRETRADE_REASON_CRYPTO_EXCHANGE_UNAVAILABLE,
            f"D: SELL rejected under CRYPTO_EXCHANGE_UNAVAILABLE (got {raised!r})",
        )
        after = _row_counts(repos)
        check(before == after, "D: Order/Trade/Position counts unchanged by rejected SELL")
        account_after = repos["account"].get_by_id(CRYPTO_ACCOUNT_ID)
        check(account_before.cash == account_after.cash, "D: Cash unchanged by rejected SELL")
        position_after = repos["position"].get_open_position(CRYPTO_ACCOUNT_ID, CRYPTO_SYMBOL)
        check(
            position_before is not None
            and position_after is not None
            and position_before.quantity == position_after.quantity,
            "D: Position quantity unchanged by rejected SELL",
        )


# ---------------------------------------------------------------------------
# E -- IDX isolation
# ---------------------------------------------------------------------------


def scenario_idx_isolation():
    print("\n[Scenario E] IDX isolation -- crypto unavailable does not leak into IDX")
    _clear_env()
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        os.environ[CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR] = "false"
        os.environ["AIOS_MARKET"] = "idx"
        try:
            trade = engine.submit_order(
                account_id="idx-test-id",
                symbol="BBCA",
                action="BUY",
                quantity=100.0,
                requested_price=9500.0,
                executed_at=EXECUTED_AT,
                signal_evidence={"note": "idx isolation"},
                user_approval=True,
                idempotency_key="crypto-avail-e",
            )
        finally:
            _clear_env()
        check(isinstance(trade, Trade), "E: IDX order accepted even though CRYPTO_EXCHANGE_AVAILABLE=false")
        check(trade.quantity == 100.0, "E: IDX Trade.quantity unchanged")


# ---------------------------------------------------------------------------
# F -- US isolation
# ---------------------------------------------------------------------------


def scenario_us_isolation():
    print("\n[Scenario F] US isolation -- crypto unavailable does not leak into US")
    _clear_env()
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        os.environ[CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR] = "false"
        os.environ["AIOS_MARKET"] = "us"
        try:
            trade = engine.submit_order(
                account_id="us-test-id",
                symbol="AAPL",
                action="BUY",
                quantity=10.0,
                requested_price=190.00,
                executed_at="2026-01-06T15:00:00+00:00",  # Tuesday, US regular session
                signal_evidence={"note": "us isolation"},
                user_approval=True,
                idempotency_key="crypto-avail-f",
            )
        finally:
            _clear_env()
        check(isinstance(trade, Trade), "F: US order accepted even though CRYPTO_EXCHANGE_AVAILABLE=false")
        check(trade.quantity == 10.0, "F: US Trade.quantity unchanged")


# ---------------------------------------------------------------------------
# Crypto BUY -> SELL -> reconciliation while available (mirrors
# Activation 10.5's own E2E scenario, re-proven here with gate 19 in
# place and available=True).
# ---------------------------------------------------------------------------


def scenario_crypto_e2e_available():
    print("\n[Scenario E2E] Crypto BUY -> SELL -> reconciliation while available")
    _clear_env()
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, manager = _build_engine(tmp)
        try:
            buy_trade = _submit_crypto(engine, idempotency_key="crypto-avail-e2e-buy", action="BUY", quantity=1.0)
            check(isinstance(buy_trade, Trade), "E2E: setup BUY (1.0 BTC-USD) accepted")

            sell_trade = _submit_crypto(engine, idempotency_key="crypto-avail-e2e-sell", action="SELL", quantity=0.5)
            check(isinstance(sell_trade, Trade), "E2E: SELL accepted")
        finally:
            _clear_env()

        account_repo = repos["account"]
        order_repo = repos["order"]
        trade_repo = repos["trade"]
        position_repo = repos["position"]
        reconciliation_engine = ReconciliationEngine(order_repo, trade_repo, account_repo, position_repo)
        result = reconciliation_engine.reconcile_account(CRYPTO_ACCOUNT_ID, starting_cash=1_000_000.0)
        check(result.consistent is True, "E2E: Reconciliation consistent == True")
        check(result.violations == [], "E2E: Reconciliation violations == []")


# ---------------------------------------------------------------------------
# I/J -- Activation 10.1 / Activation 10.5 regression (subprocesses)
# ---------------------------------------------------------------------------


def _run_regression_script(relative_path: str, label: str) -> None:
    result = subprocess.run(
        [sys.executable, str(_PROJECT_ROOT / relative_path)],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    check(result.returncode == 0, f"{label}: exits 0 (all PASS)")
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-4000:])


def scenario_activation_regressions():
    print("\n[Scenario Regression] Activation 10.1 + Activation 10.5 regression suites")
    _run_regression_script("Tests/test_activation10_1_crypto_paper_workflow.py", "Activation 10.1 regression (I)")
    _run_regression_script("Tests/test_activation10_5_crypto_24_7_policy.py", "Activation 10.5 regression (J)")


def main() -> int:
    scenario_market_vs_availability_distinction()
    scenario_policy_pure_checks_and_config()
    scenario_default_available()
    scenario_explicit_unavailable()
    scenario_recovery()
    scenario_sell_unavailable()
    scenario_idx_isolation()
    scenario_us_isolation()
    scenario_crypto_e2e_available()
    scenario_activation_regressions()

    # H -- environment restoration: verify no scenario above leaked
    # env var state into this final check.
    check(
        os.environ.get(CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR) is None,
        "H: CRYPTO_EXCHANGE_AVAILABLE is unset at end of run (no cross-scenario contamination)",
    )
    check(
        os.environ.get("AIOS_MARKET") is None,
        "H: AIOS_MARKET is unset at end of run (no cross-scenario contamination)",
    )

    print(f"\n{'=' * 70}")
    print(f"Activation 10.6 crypto exchange availability policy: {_PASS} PASS, {_FAIL} FAIL")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())