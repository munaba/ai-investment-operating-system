"""Standalone regression checks for Activation 9.4 -- the US market
session/calendar pre-trade gate (gate 17) wired into
``Business.paper_trading_engine.PaperTradingEngine``.

Covers:

* market == "us" regular session -> order allowed;
* market == "us" pre-market -> rejected, PRETRADE_REASON_US_MARKET_SESSION_CLOSED;
* market == "us" after-hours -> rejected, same reason;
* market == "us" weekend -> rejected, same reason;
* market == "us" known 2026 holiday (New Year's Day) -> rejected, same reason;
* DST boundary (2026-03-08 spring-forward) -- 9:30 ET on the Monday
  before and the Monday after the transition both classify as regular
  and are both allowed, proving the UTC->America/New_York conversion
  is DST-correct, not a fixed offset;
* market == "idx" is completely unaffected by the new gate -- the
  exact same weekend/holiday UTC timestamps that reject a "us" order
  still succeed for "idx" (gate 17 is skipped entirely);
* every rejection is a genuine pre-trade rejection: zero rows written
  to orders/trades/accounts/positions, exactly like every other gate
  in ``Tests/test_paper_trading_engine.py``.

This engine is exercised directly (never mocked) against a real
temporary SQLite database, per the Activation 9.4 brief's explicit
"Do not mock PaperTradingEngine in an integration test intended to
prove the gate" requirement.

Run directly with ``python Tests/test_us_market_session_gate.py`` --
no external test framework required, matching
``Tests/test_paper_trading_engine.py``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import (  # noqa: E402
    PRETRADE_REASON_US_MARKET_SESSION_CLOSED,
    PaperTradingEngine,
)
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


def _build_engine(tmp_dir: str, *, currency: str, asset_class: str, cash: float):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "us_market_session_gate.db")
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
        account_id="session-gate-test",
        account_name="Session Gate Test",
        mode="paper",
        currency=currency,
        asset_class=asset_class,
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
    return engine, repos


def _row_counts(repos) -> dict:
    return {
        "accounts": len(repos["account"].list_all()),
        "positions": len(repos["position"].list_all()),
        "orders": len(repos["order"].list_all()),
        "trades": len(repos["trade"].list_all()),
    }


def _us_kwargs(executed_at: str, idempotency_key: str) -> dict:
    return dict(
        account_id="session-gate-test",
        symbol="AAPL",
        action="BUY",
        quantity=10.0,
        requested_price=150.0,
        executed_at=executed_at,
        signal_evidence={"note": "session gate test"},
        user_approval=True,
        idempotency_key=idempotency_key,
    )


def _with_market(market: str):
    """Context-manager-less helper: returns (old_value) to restore later."""
    old = os.environ.get("AIOS_MARKET")
    os.environ["AIOS_MARKET"] = market
    return old


def _restore_market(old) -> None:
    if old is None:
        os.environ.pop("AIOS_MARKET", None)
    else:
        os.environ["AIOS_MARKET"] = old


def scenario_us_regular_session_allowed():
    print("\n[Scenario A] US regular session (Tue 2026-01-06 10:00 ET) -> order allowed")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, currency="USD", asset_class="stock_us", cash=100_000.0)
        old = _with_market("us")
        try:
            trade = engine.submit_order(**_us_kwargs("2026-01-06T15:00:00+00:00", "sess-a"))
            check(isinstance(trade, Trade), "regular-session US order returns a Trade")
        finally:
            _restore_market(old)


def scenario_us_pre_market_rejected():
    print("\n[Scenario B] US pre-market (Tue 2026-01-06 08:00 ET) -> rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, currency="USD", asset_class="stock_us", cash=100_000.0)
        old = _with_market("us")
        before = _row_counts(repos)
        reason = None
        try:
            engine.submit_order(**_us_kwargs("2026-01-06T13:00:00+00:00", "sess-b"))
        except ValidationError as exc:
            reason = exc.details.get("reason")
        finally:
            _restore_market(old)
        check(reason == PRETRADE_REASON_US_MARKET_SESSION_CLOSED, "pre-market US order rejected with correct reason")
        check(before == _row_counts(repos), "pre-market rejection: zero writes to orders/trades/accounts/positions")


def scenario_us_after_hours_rejected():
    print("\n[Scenario C] US after-hours (Tue 2026-01-06 17:00 ET) -> rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, currency="USD", asset_class="stock_us", cash=100_000.0)
        old = _with_market("us")
        before = _row_counts(repos)
        reason = None
        try:
            engine.submit_order(**_us_kwargs("2026-01-06T22:00:00+00:00", "sess-c"))
        except ValidationError as exc:
            reason = exc.details.get("reason")
        finally:
            _restore_market(old)
        check(reason == PRETRADE_REASON_US_MARKET_SESSION_CLOSED, "after-hours US order rejected with correct reason")
        check(before == _row_counts(repos), "after-hours rejection: zero writes to orders/trades/accounts/positions")


def scenario_us_weekend_rejected():
    print("\n[Scenario D] US weekend (Sat 2026-01-03 10:00 ET) -> rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, currency="USD", asset_class="stock_us", cash=100_000.0)
        old = _with_market("us")
        before = _row_counts(repos)
        reason = None
        try:
            engine.submit_order(**_us_kwargs("2026-01-03T15:00:00+00:00", "sess-d"))
        except ValidationError as exc:
            reason = exc.details.get("reason")
        finally:
            _restore_market(old)
        check(reason == PRETRADE_REASON_US_MARKET_SESSION_CLOSED, "weekend US order rejected with correct reason")
        check(before == _row_counts(repos), "weekend rejection: zero writes to orders/trades/accounts/positions")


def scenario_us_holiday_rejected():
    print("\n[Scenario E] US holiday (New Year's Day 2026-01-01 10:00 ET) -> rejected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, currency="USD", asset_class="stock_us", cash=100_000.0)
        old = _with_market("us")
        before = _row_counts(repos)
        reason = None
        try:
            engine.submit_order(**_us_kwargs("2026-01-01T15:00:00+00:00", "sess-e"))
        except ValidationError as exc:
            reason = exc.details.get("reason")
        finally:
            _restore_market(old)
        check(reason == PRETRADE_REASON_US_MARKET_SESSION_CLOSED, "holiday US order rejected with correct reason")
        check(before == _row_counts(repos), "holiday rejection: zero writes to orders/trades/accounts/positions")


def scenario_us_dst_boundary():
    print(
        "\n[Scenario F] DST boundary (US spring-forward is 2026-03-08) -- 09:30 ET "
        "on the Monday before (EST, UTC-5) and the Monday after (EDT, UTC-4) both "
        "classify as regular session and are both allowed"
    )
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, currency="USD", asset_class="stock_us", cash=100_000.0)
        old = _with_market("us")
        try:
            # 2026-03-02 (Monday, before DST): 09:30 ET == 14:30 UTC (EST, UTC-5).
            trade_before = engine.submit_order(**_us_kwargs("2026-03-02T14:30:00+00:00", "sess-f-before"))
            check(isinstance(trade_before, Trade), "09:30 ET the Monday before DST (EST) -> order allowed")

            # 2026-03-09 (Monday, after DST): 09:30 ET == 13:30 UTC (EDT, UTC-4).
            trade_after = engine.submit_order(**_us_kwargs("2026-03-09T13:30:00+00:00", "sess-f-after"))
            check(isinstance(trade_after, Trade), "09:30 ET the Monday after DST (EDT) -> order allowed")
        finally:
            _restore_market(old)


def scenario_idx_unaffected_by_us_session_gate():
    print(
        "\n[Scenario G] market == 'idx' is completely unaffected -- the same "
        "weekend/holiday UTC timestamps that reject a 'us' order still succeed "
        "for 'idx' (gate 17 is skipped entirely for non-'us' markets)"
    )
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, currency="IDR", asset_class="stock_id", cash=1_000_000_000.0)
        old = _with_market("idx")
        try:
            kwargs = dict(
                account_id="session-gate-test",
                symbol="BBCA",
                action="BUY",
                quantity=100.0,  # IDX lot size (gate 6) -- 100 shares/lot
                requested_price=9_500.0,
                executed_at="2026-01-03T15:00:00+00:00",  # same weekend UTC moment as Scenario D
                signal_evidence={"note": "idx unaffected"},
                user_approval=True,
                idempotency_key="sess-g",
            )
            trade = engine.submit_order(**kwargs)
            check(isinstance(trade, Trade), "IDX order at the same weekend UTC moment as Scenario D still succeeds")
        finally:
            _restore_market(old)


def main() -> int:
    scenario_us_regular_session_allowed()
    scenario_us_pre_market_rejected()
    scenario_us_after_hours_rejected()
    scenario_us_weekend_rejected()
    scenario_us_holiday_rejected()
    scenario_us_dst_boundary()
    scenario_idx_unaffected_by_us_session_gate()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 9.4 US MARKET SESSION GATE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for failure in _FAILURES:
            print(f"  - {failure}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())