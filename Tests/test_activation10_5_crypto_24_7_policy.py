"""Activation 10.5 -- crypto 24/7 market policy acceptance test.

Exercises ``Business.crypto_market_policy.CryptoMarketPolicy`` both
directly (pure, deterministic checks against fixed timestamps) and
through the real, unmodified ``Business.paper_trading_engine.
PaperTradingEngine`` pre-trade validation gate (market == "crypto"
branch, gate 18). Mirrors ``Tests/
test_activation10_3_crypto_price_tick.py``'s own
``_build_engine``/``_expect_pretrade_rejection`` structure and
real-collaborators-only approach (no mocking of the engine itself).

Required test cases (see Activation 10.5 brief):

    A. Monday timestamp -> crypto order allowed
    B. Saturday timestamp -> crypto order allowed
    C. Sunday timestamp -> crypto order allowed
    D. known US equity holiday timestamp -> crypto order allowed
       (proves crypto does not accidentally reuse USMarketCalendar)
    E. boundary times (00:00 UTC, 23:59 UTC) -> both allowed
    F. a timestamp around a US DST transition -> crypto unaffected
    G. IDX regression -> IDX behavior unchanged
    H. US regression -> US session/calendar gate unchanged
    I. Crypto E2E -> real BUY -> SELL -> reconciliation, deterministic
       executed_at
    J. CryptoMarketPolicy direct test against multiple timestamps

Run directly:
``python Tests/test_activation10_5_crypto_24_7_policy.py`` -- no
external test framework required, matching every other
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
from Business.crypto_market_policy import (  # noqa: E402
    CryptoMarketPolicy,
    load_crypto_market_policy,
)
from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import (  # noqa: E402
    PRETRADE_REASON_CRYPTO_MARKET_CLOSED,
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
# NOTE -- AIOS paper-market policy, not an exchange claim (see
# Business.crypto_market_policy module docstring).
# ---------------------------------------------------------------------------

CRYPTO_ACCOUNT_ID = "crypto-24-7-test-id"
CRYPTO_SYMBOL = "BTC-USD"
# Tick-aligned (0.01) and, at quantity 0.1, well above the Activation
# 10.2 minimum-notional default (10.0) -- same constants
# Tests/test_activation10_3_crypto_price_tick.py uses.
CRYPTO_PRICE = 100.00
CRYPTO_QTY = 0.1


def _build_engine(tmp_dir: str, *, cash: float = 1_000_000.0):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "crypto_24_7.db")
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
        account_name="Crypto 24/7 Policy Test Account",
        mode="paper",
        currency="USD",
        asset_class="crypto",
        cash=cash,
        equity=cash,
        buying_power=cash,
    )
    # Also an IDX account, for the IDX regression scenario.
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
    # Also a US account, for the US regression scenario.
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


def _submit_crypto(engine, *, executed_at: str, idempotency_key: str, action: str = "BUY", quantity: float = CRYPTO_QTY):
    os.environ["AIOS_MARKET"] = "crypto"
    try:
        return engine.submit_order(
            account_id=CRYPTO_ACCOUNT_ID,
            symbol=CRYPTO_SYMBOL,
            action=action,
            quantity=quantity,
            requested_price=CRYPTO_PRICE,
            executed_at=executed_at,
            signal_evidence={"note": "activation 10.5 test"},
            user_approval=True,
            idempotency_key=idempotency_key,
        )
    finally:
        os.environ.pop("AIOS_MARKET", None)


# ---------------------------------------------------------------------------
# J -- pure CryptoMarketPolicy direct checks
# ---------------------------------------------------------------------------


def scenario_policy_pure_checks():
    print("\n[Scenario J] CryptoMarketPolicy direct checks against multiple timestamps")
    policy = load_crypto_market_policy()
    check(isinstance(policy, CryptoMarketPolicy), "load_crypto_market_policy() returns a CryptoMarketPolicy")

    moments = [
        ("Monday", datetime(2026, 8, 17, 3, 0, tzinfo=timezone.utc)),
        ("Saturday", datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc)),
        ("Sunday", datetime(2026, 8, 16, 23, 59, tzinfo=timezone.utc)),
        ("US holiday (2026-07-03 observed Independence Day)", datetime(2026, 7, 3, 15, 0, tzinfo=timezone.utc)),
        ("UTC boundary 00:00", datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)),
        ("UTC boundary 23:59", datetime(2026, 8, 17, 23, 59, tzinfo=timezone.utc)),
        ("US DST transition (2026-03-08 spring-forward)", datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)),
    ]
    for label, moment in moments:
        check(policy.is_trading_allowed(moment) is True, f"J: CryptoMarketPolicy allows {label}")


# ---------------------------------------------------------------------------
# A/B/C -- Monday/Saturday/Sunday through the real engine
# ---------------------------------------------------------------------------


def scenario_monday():
    print("\n[Scenario A] Monday crypto order accepted through the real engine")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        trade = _submit_crypto(engine, executed_at="2026-08-17T03:00:00+00:00", idempotency_key="crypto-24-7-a")
        check(isinstance(trade, Trade), "A: Monday BUY accepted")


def scenario_saturday():
    print("\n[Scenario B] Saturday crypto order accepted through the real engine")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        trade = _submit_crypto(engine, executed_at="2026-08-15T03:00:00+00:00", idempotency_key="crypto-24-7-b")
        check(isinstance(trade, Trade), "B: Saturday BUY accepted")


def scenario_sunday():
    print("\n[Scenario C] Sunday crypto order accepted through the real engine")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        trade = _submit_crypto(engine, executed_at="2026-08-16T23:59:00+00:00", idempotency_key="crypto-24-7-c")
        check(isinstance(trade, Trade), "C: Sunday BUY accepted")


# ---------------------------------------------------------------------------
# D -- known US equity holiday
# ---------------------------------------------------------------------------


def scenario_us_holiday():
    print("\n[Scenario D] known US equity holiday does not block crypto (no USMarketCalendar reuse)")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        # 2026-12-25 is Christmas Day -- a known NYSE/Nasdaq holiday
        # under Business.us_market_policy.us_market_holidays(). A US
        # order at this timestamp would be rejected by gate 17
        # (US_MARKET_SESSION_CLOSED); a crypto order at the exact same
        # timestamp must still be accepted, proving gate 18 does not
        # consult USMarketCalendar at all.
        trade = _submit_crypto(engine, executed_at="2026-12-25T15:00:00+00:00", idempotency_key="crypto-24-7-d")
        check(isinstance(trade, Trade), "D: crypto BUY on US Christmas Day holiday accepted")


# ---------------------------------------------------------------------------
# E -- UTC boundary times
# ---------------------------------------------------------------------------


def scenario_utc_boundaries():
    print("\n[Scenario E] UTC boundary times (00:00 and 23:59) both allowed")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        trade_open = _submit_crypto(engine, executed_at="2026-08-18T00:00:00+00:00", idempotency_key="crypto-24-7-e1")
        check(isinstance(trade_open, Trade), "E: 00:00 UTC accepted")
        trade_close = _submit_crypto(engine, executed_at="2026-08-18T23:59:00+00:00", idempotency_key="crypto-24-7-e2")
        check(isinstance(trade_close, Trade), "E: 23:59 UTC accepted")


# ---------------------------------------------------------------------------
# F -- DST transition
# ---------------------------------------------------------------------------


def scenario_dst_transition():
    print("\n[Scenario F] US DST transition timestamp does not affect crypto")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        # 2026-03-08 is the US spring-forward DST transition date
        # (2:00 AM -> 3:00 AM ET). A crypto order at this same UTC
        # instant must be accepted regardless.
        trade = _submit_crypto(engine, executed_at="2026-03-08T07:30:00+00:00", idempotency_key="crypto-24-7-f")
        check(isinstance(trade, Trade), "F: crypto BUY around US DST transition accepted")


# ---------------------------------------------------------------------------
# G -- IDX regression
# ---------------------------------------------------------------------------


def scenario_idx_regression():
    print("\n[Scenario G] IDX regression -- IDX behavior unchanged by crypto 24/7 gate")
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
                executed_at="2026-08-16T10:00:00+00:00",  # Sunday -- irrelevant to IDX gate 6
                signal_evidence={"note": "idx regression"},
                user_approval=True,
                idempotency_key="crypto-24-7-g",
            )
        finally:
            os.environ.pop("AIOS_MARKET", None)
        check(isinstance(trade, Trade), "G: IDX order unaffected by the new crypto-only gate 18")
        check(trade.quantity == 100.0, "G: IDX Trade.quantity unchanged")


# ---------------------------------------------------------------------------
# H -- US regression
# ---------------------------------------------------------------------------


def scenario_us_regression():
    print("\n[Scenario H] US regression -- US session/calendar gate (17) unchanged")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)

        # H1: US order during regular session on a trading day -> accepted.
        os.environ["AIOS_MARKET"] = "us"
        try:
            trade = engine.submit_order(
                account_id="us-test-id",
                symbol="AAPL",
                action="BUY",
                quantity=10.0,
                requested_price=190.00,
                executed_at="2026-01-06T15:00:00+00:00",  # Tuesday, US regular session
                signal_evidence={"note": "us regression accept"},
                user_approval=True,
                idempotency_key="crypto-24-7-h1",
            )
            check(isinstance(trade, Trade), "H: US regular-session order still accepted")
        finally:
            os.environ.pop("AIOS_MARKET", None)

        # H2: US order on a Sunday -> still rejected by gate 17,
        # proving gate 18's crypto 24/7 policy has not leaked into US.
        os.environ["AIOS_MARKET"] = "us"
        raised = None
        try:
            engine.submit_order(
                account_id="us-test-id",
                symbol="AAPL",
                action="BUY",
                quantity=10.0,
                requested_price=190.00,
                executed_at="2026-01-04T15:00:00+00:00",  # Sunday
                signal_evidence={"note": "us regression reject"},
                user_approval=True,
                idempotency_key="crypto-24-7-h2",
            )
        except ValidationError as exc:
            raised = exc.details.get("reason")
        finally:
            os.environ.pop("AIOS_MARKET", None)
        check(
            raised == "US_MARKET_SESSION_CLOSED",
            f"H: US Sunday order still rejected under US_MARKET_SESSION_CLOSED (got {raised!r})",
        )


# ---------------------------------------------------------------------------
# I -- Crypto E2E: BUY -> SELL -> reconciliation
# ---------------------------------------------------------------------------


def scenario_crypto_e2e():
    print("\n[Scenario I] Crypto E2E: BUY -> SELL -> reconciliation, deterministic executed_at")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, manager = _build_engine(tmp)

        buy_trade = _submit_crypto(
            engine,
            executed_at="2026-08-15T03:00:00+00:00",  # Saturday
            idempotency_key="crypto-24-7-i-buy",
            action="BUY",
            quantity=1.0,
        )
        check(isinstance(buy_trade, Trade), "I: setup BUY (1.0 BTC-USD) accepted")

        sell_trade = _submit_crypto(
            engine,
            executed_at="2026-08-16T23:59:00+00:00",  # Sunday
            idempotency_key="crypto-24-7-i-sell",
            action="SELL",
            quantity=0.5,
        )
        check(isinstance(sell_trade, Trade), "I: SELL accepted")
        check(sell_trade.action == "SELL", "I: Trade.action == SELL")

        position = repos["position"].get_open_position(CRYPTO_ACCOUNT_ID, CRYPTO_SYMBOL)
        check(
            position is not None and abs(position.quantity - 0.5) < 1e-9,
            "I: Position reduced to 0.5 after SELL",
        )

        account_repo = repos["account"]
        order_repo = repos["order"]
        trade_repo = repos["trade"]
        position_repo = repos["position"]
        reconciliation_engine = ReconciliationEngine(order_repo, trade_repo, account_repo, position_repo)
        result = reconciliation_engine.reconcile_account(CRYPTO_ACCOUNT_ID, starting_cash=1_000_000.0)
        check(result.consistent is True, "I: Reconciliation reconcile_account() consistent == True")
        check(result.violations == [], "I: Reconciliation reconcile_account() violations == []")


# ---------------------------------------------------------------------------
# Invalid executed_at -- fail-safe (not a required lettered case, but
# proves the "policy errors must not create an order" / "invalid
# timestamp still rejected" FAILURE SAFETY requirement).
# ---------------------------------------------------------------------------


def scenario_invalid_executed_at_fails_safe():
    print("\n[Scenario X] unparsable executed_at is rejected, not silently treated as market-open")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos, _ = _build_engine(tmp)
        before = _row_counts(repos)
        raised = None
        os.environ["AIOS_MARKET"] = "crypto"
        try:
            engine.submit_order(
                account_id=CRYPTO_ACCOUNT_ID,
                symbol=CRYPTO_SYMBOL,
                action="BUY",
                quantity=CRYPTO_QTY,
                requested_price=CRYPTO_PRICE,
                executed_at="not-a-timestamp",
                signal_evidence={"note": "invalid timestamp"},
                user_approval=True,
                idempotency_key="crypto-24-7-invalid",
            )
        except ValidationError as exc:
            raised = exc.details.get("reason")
        finally:
            os.environ.pop("AIOS_MARKET", None)
        check(
            raised == PRETRADE_REASON_CRYPTO_MARKET_CLOSED,
            f"X: unparsable executed_at rejected under CRYPTO_MARKET_CLOSED (got {raised!r})",
        )
        after = _row_counts(repos)
        check(before == after, "X: zero writes to orders/trades/positions")


# ---------------------------------------------------------------------------
# Activation 10.1-10.4 + Activation 9 regression (run as subprocesses,
# mirroring Tests/test_activation10_3_crypto_price_tick.py's own
# Scenario H pattern).
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
    print("\n[Scenario Regression] Activation 10.1-10.4 + Activation 9 regression suites")
    _run_regression_script("Tests/test_activation10_4_crypto_fee_policy.py", "Activation 10.4 regression")
    _run_regression_script("Tests/test_activation10_3_crypto_price_tick.py", "Activation 10.3 regression")
    _run_regression_script("Tests/test_activation10_2_crypto_quantity_policy.py", "Activation 10.2 regression")
    _run_regression_script("Tests/test_activation10_1_crypto_paper_workflow.py", "Activation 10.1 regression")
    _run_regression_script("Tests/test_activation9_us_e2e_acceptance.py", "Activation 9 regression")


def main() -> int:
    scenario_policy_pure_checks()
    scenario_monday()
    scenario_saturday()
    scenario_sunday()
    scenario_us_holiday()
    scenario_utc_boundaries()
    scenario_dst_transition()
    scenario_idx_regression()
    scenario_us_regression()
    scenario_crypto_e2e()
    scenario_invalid_executed_at_fails_safe()
    scenario_activation_regressions()

    print(f"\n{'=' * 70}")
    print(f"Activation 10.5 crypto 24/7 market policy: {_PASS} PASS, {_FAIL} FAIL")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())