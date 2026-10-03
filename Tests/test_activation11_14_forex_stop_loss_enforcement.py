"""Standalone regression checks for Activation 11.14 -- Forex
stop-loss enforcement at the paper-order boundary in
``Business.paper_trading_engine.PaperTradingEngine``.

Implements Activation 11.10-H's LOCKED requirement -- "a Forex order
without stop-loss is rejected" -- plus Activation 11.13's
direction-aware validation applied at the pre-trade gate, before any
financial mutation:

* ``Account.asset_class == "forex"`` ONLY: ``stop_loss`` is REQUIRED
  on every order (BUY or SELL); missing it rejects with
  ``PRETRADE_REASON_FOREX_STOP_LOSS_REQUIRED``, zero writes.
* When supplied, ``stop_loss`` must be on the protective side of
  ``requested_price`` for the resulting/existing
  ``Position.direction`` -- LONG: below; SHORT: above; equal is
  invalid. A violation rejects with
  ``PRETRADE_REASON_INVALID_FOREX_STOP_LOSS``, zero writes.
* On success, ``Position.stop_loss`` persists the supplied value and
  ``Position.direction`` is unaffected.
* IDX/US/Crypto orders are completely unaffected -- ``stop_loss``
  defaults to ``None`` and is silently ignored for any non-Forex
  account.

This file exercises a real ``PaperTradingEngine`` + real
``PositionManager``/``PositionRepository``/``AccountRepository`` (+
the other Sprint 4 collaborators ``OrderLifecycleService``/
``ExecutionService``/``OrderIdempotencyRepository``) against a
temporary SQLite database, following ``Tests/test_paper_trading_engine.py``'s
established harness (``_build_engine``/``_row_counts``/
``_expect_pretrade_rejection`` style) plus a Forex account.

Run directly with
``python Tests/test_activation11_14_forex_stop_loss_enforcement.py``
-- no external test framework required.
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
    PRETRADE_REASON_FOREX_STOP_LOSS_REQUIRED,
    PRETRADE_REASON_INVALID_FOREX_STOP_LOSS,
    PaperTradingEngine,
)
from Business.position_manager import PositionManager  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.models import Trade  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
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


def _build_engine(tmp_dir: str, *, cash: float = 1_000_000.0):
    """Build a real PaperTradingEngine wired to real repositories, with
    a 'forex-id' (asset_class='forex'), 'paper-id' (stock_id), and
    'us-usd' (stock_us) account already created -- covers scenarios K
    (IDX) and L (US) without extra per-scenario setup.
    """
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "forex_stop_loss_enforcement.db")
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
        account_id="forex-id",
        account_name="Forex USD",
        mode="paper",
        currency="USD",
        asset_class="forex",
        cash=cash,
        equity=cash,
        buying_power=cash,
    )
    account_repo.create(
        account_id="paper-id",
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=100_000_000.0,
        equity=100_000_000.0,
        buying_power=100_000_000.0,
    )
    account_repo.create(
        account_id="us-usd",
        account_name="US Paper",
        mode="paper",
        currency="USD",
        asset_class="stock_us",
        cash=100_000.0,
        equity=100_000.0,
        buying_power=100_000.0,
    )
    account_repo.create(
        account_id="crypto-usd",
        account_name="Crypto Paper",
        mode="paper",
        currency="USD",
        asset_class="crypto",
        cash=100_000.0,
        equity=100_000.0,
        buying_power=100_000.0,
    )
    order_lifecycle_service = OrderLifecycleService(order_repo)
    execution_service = ExecutionService(order_repo, trade_repo)
    position_manager = PositionManager(position_repo, account_repo)
    engine = PaperTradingEngine(
        order_lifecycle_service=order_lifecycle_service,
        execution_service=execution_service,
        account_repository=account_repo,
        position_repository=position_repo,
        order_idempotency_repository=idempotency_repo,
        kill_switch_engaged=False,
        max_order_value=1_000_000_000.0,
        position_manager=position_manager,
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


def _forex_kwargs(**overrides) -> dict:
    kwargs = dict(
        account_id="forex-id",
        symbol="EURUSD",
        action="BUY",
        quantity=10_000.0,
        requested_price=1.1000,
        executed_at="2026-08-17T10:00:00+00:00",
        signal_evidence={"note": "forex test"},
        user_approval=True,
        idempotency_key="forex-req-001",
    )
    kwargs.update(overrides)
    return kwargs


def _expect_pretrade_rejection(engine, repos, reason: str, description: str, **overrides) -> None:
    before = _row_counts(repos)
    idempotency_before = repos["idempotency"].get_by_key(overrides.get("idempotency_key", "forex-req-001"))

    raised_reason = None
    try:
        engine.submit_order(**_forex_kwargs(**overrides))
    except ValidationError as exc:
        raised_reason = exc.details.get("reason")

    check(raised_reason == reason, f"{description}: ValidationError reason == '{reason}'")

    after = _row_counts(repos)
    check(before == after, f"{description}: zero writes to accounts/positions/orders/trades")

    idempotency_after = repos["idempotency"].get_by_key(overrides.get("idempotency_key", "forex-req-001"))
    check(
        idempotency_before == idempotency_after,
        f"{description}: idempotency key state unchanged (no stray write)",
    )


# ---------------------------------------------------------------------------
# A -- BUY missing stop
# ---------------------------------------------------------------------------
def scenario_a_buy_missing_stop():
    print("\n[Scenario A] Forex BUY without stop_loss rejects, zero writes")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_FOREX_STOP_LOSS_REQUIRED,
            "Forex BUY without stop_loss",
            action="BUY", stop_loss=None,
        )


# ---------------------------------------------------------------------------
# B -- SELL missing stop
# ---------------------------------------------------------------------------
def scenario_b_sell_missing_stop():
    print("\n[Scenario B] Forex SELL without stop_loss rejects, zero writes")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_FOREX_STOP_LOSS_REQUIRED,
            "Forex SELL without stop_loss",
            action="SELL", stop_loss=None,
        )


# ---------------------------------------------------------------------------
# C -- BUY valid stop
# ---------------------------------------------------------------------------
def scenario_c_buy_valid_stop():
    print("\n[Scenario C] Forex BUY with valid LONG stop succeeds, persists direction+stop")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        trade = engine.submit_order(**_forex_kwargs(action="BUY", stop_loss=1.0950))
        check(isinstance(trade, Trade), "submit_order() returns a Trade")

        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position is not None, "a Position was created")
        check(position.direction == "LONG", "Position.direction == LONG")
        check(position.stop_loss == 1.0950, "Position.stop_loss persisted")


# ---------------------------------------------------------------------------
# D -- SELL valid stop
# ---------------------------------------------------------------------------
def scenario_d_sell_valid_stop():
    print("\n[Scenario D] Forex SELL with valid SHORT stop succeeds, persists direction+stop")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        trade = engine.submit_order(**_forex_kwargs(action="SELL", stop_loss=1.1050))
        check(isinstance(trade, Trade), "submit_order() returns a Trade")

        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position is not None, "a Position was created")
        check(position.direction == "SHORT", "Position.direction == SHORT")
        check(position.stop_loss == 1.1050, "Position.stop_loss persisted")


# ---------------------------------------------------------------------------
# E -- BUY invalid direction
# ---------------------------------------------------------------------------
def scenario_e_buy_invalid_direction():
    print("\n[Scenario E] Forex BUY with stop above entry rejects, zero writes")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INVALID_FOREX_STOP_LOSS,
            "Forex BUY with stop 1.1050 above entry 1.1000",
            action="BUY", requested_price=1.1000, stop_loss=1.1050,
        )


# ---------------------------------------------------------------------------
# F -- SELL invalid direction
# ---------------------------------------------------------------------------
def scenario_f_sell_invalid_direction():
    print("\n[Scenario F] Forex SELL with stop below entry rejects, zero writes")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INVALID_FOREX_STOP_LOSS,
            "Forex SELL with stop 1.0950 below entry 1.1000",
            action="SELL", requested_price=1.1000, stop_loss=1.0950,
        )


# ---------------------------------------------------------------------------
# G -- Existing LONG + next order validates against LONG
# ---------------------------------------------------------------------------
def scenario_g_existing_long_next_order():
    print("\n[Scenario G] a second BUY on an existing LONG validates stop_loss against LONG")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        engine.submit_order(**_forex_kwargs(
            action="BUY", requested_price=1.1000, stop_loss=1.0950, idempotency_key="g-req-1"
        ))

        # A same-price BUY merge -- average_price stays 1.1000, so the
        # post-trade PositionManager.set_stop_loss_take_profit()
        # re-validation (against the now-merged Position's
        # average_price) agrees with this pre-trade gate's own
        # requested_price-based check.
        trade = engine.submit_order(**_forex_kwargs(
            action="BUY", requested_price=1.1000, stop_loss=1.0900, idempotency_key="g-req-2"
        ))
        check(isinstance(trade, Trade), "second BUY (merge) succeeds with a valid LONG stop")

        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position.direction == "LONG", "direction stays LONG after merge")
        check(position.stop_loss == 1.0900, "stop_loss updated to the second order's value")

        # An invalid stop for the existing LONG direction still rejects.
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INVALID_FOREX_STOP_LOSS,
            "third BUY on existing LONG with stop above entry rejects",
            action="BUY", requested_price=1.1000, stop_loss=1.1050, idempotency_key="g-req-3",
        )


# ---------------------------------------------------------------------------
# H -- Existing SHORT + next order validates against SHORT
# ---------------------------------------------------------------------------
def scenario_h_existing_short_next_order():
    print("\n[Scenario H] a second SELL on an existing SHORT validates stop_loss against SHORT")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        engine.submit_order(**_forex_kwargs(
            action="SELL", requested_price=1.1000, stop_loss=1.1050, idempotency_key="h-req-1"
        ))

        trade = engine.submit_order(**_forex_kwargs(
            action="SELL", requested_price=1.1000, stop_loss=1.1100, idempotency_key="h-req-2"
        ))
        check(isinstance(trade, Trade), "second SELL (merge into SHORT) succeeds with a valid SHORT stop")

        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position.direction == "SHORT", "direction stays SHORT after merge")
        check(position.stop_loss == 1.1100, "stop_loss updated to the second order's value")

        # An invalid stop for the existing SHORT direction still rejects.
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_INVALID_FOREX_STOP_LOSS,
            "third SELL on existing SHORT with stop below entry rejects",
            action="SELL", requested_price=1.1000, stop_loss=1.0950, idempotency_key="h-req-3",
        )


# ---------------------------------------------------------------------------
# I -- Stop-loss persistence
# ---------------------------------------------------------------------------
def scenario_i_persistence():
    print("\n[Scenario I] stop_loss round-trips exactly through PositionRepository")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        engine.submit_order(**_forex_kwargs(action="SELL", requested_price=1.1000, stop_loss=1.1075))

        position = repos["position"].get_open_position("forex-id", "EURUSD")
        reloaded = repos["position"].get_by_id(position.position_id)
        check(reloaded.stop_loss == 1.1075, "reloaded Position.stop_loss matches exactly")
        check(reloaded.direction == "SHORT", "reloaded Position.direction matches")


# ---------------------------------------------------------------------------
# J -- No direction mutation
# ---------------------------------------------------------------------------
def scenario_j_no_direction_mutation():
    print("\n[Scenario J] a valid stop_loss order never mutates Position.direction")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        engine.submit_order(**_forex_kwargs(action="BUY", requested_price=1.1000, stop_loss=1.0950))
        before = repos["position"].get_open_position("forex-id", "EURUSD")

        engine.submit_order(**_forex_kwargs(
            action="BUY", requested_price=1.1000, stop_loss=1.0900, idempotency_key="j-req-2"
        ))
        after = repos["position"].get_open_position("forex-id", "EURUSD")

        check(before.direction == "LONG" and after.direction == "LONG", "direction unchanged across the second order")


# ---------------------------------------------------------------------------
# K -- IDX regression
# ---------------------------------------------------------------------------
def scenario_k_idx_regression():
    print("\n[Scenario K] existing IDX order without stop_loss is unaffected")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp)
        trade = engine.submit_order(
            account_id="paper-id",
            symbol="BBCA",
            action="BUY",
            quantity=100.0,
            requested_price=9500.0,
            executed_at="2026-08-01T10:00:00+00:00",
            signal_evidence={"note": "idx"},
            user_approval=True,
            idempotency_key="idx-req-1",
            # stop_loss deliberately omitted -- defaults to None
        )
        check(isinstance(trade, Trade), "IDX BUY with no stop_loss still succeeds")
        position = repos["position"].get_open_position("paper-id", "BBCA")
        check(position is not None and position.direction == "LONG", "IDX Position opens LONG as before")
        check(position.stop_loss is None, "IDX Position.stop_loss stays None (never required)")


# ---------------------------------------------------------------------------
# L -- US regression
# ---------------------------------------------------------------------------
def scenario_l_us_regression():
    print("\n[Scenario L] existing US order without stop_loss is unaffected")
    previous_market_env = os.environ.get("AIOS_MARKET")
    os.environ["AIOS_MARKET"] = "us"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            engine, repos = _build_engine(tmp)
            trade = engine.submit_order(
                account_id="us-usd",
                symbol="AAPL",
                action="BUY",
                quantity=10.0,
                requested_price=150.0,
                executed_at="2026-08-17T15:00:00+00:00",  # Monday, regular US session
                signal_evidence={"note": "us"},
                user_approval=True,
                idempotency_key="us-req-1",
            )
            check(isinstance(trade, Trade), "US BUY with no stop_loss still succeeds")
            position = repos["position"].get_open_position("us-usd", "AAPL")
            check(position is not None and position.direction == "LONG", "US Position opens LONG as before")
            check(position.stop_loss is None, "US Position.stop_loss stays None (never required)")
    finally:
        if previous_market_env is None:
            os.environ.pop("AIOS_MARKET", None)
        else:
            os.environ["AIOS_MARKET"] = previous_market_env


# ---------------------------------------------------------------------------
# M -- Crypto regression
# ---------------------------------------------------------------------------
def scenario_m_crypto_regression():
    print("\n[Scenario M] existing Crypto order without stop_loss is unaffected")
    previous_market_env = os.environ.get("AIOS_MARKET")
    os.environ["AIOS_MARKET"] = "crypto"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            engine, repos = _build_engine(tmp)
            trade = engine.submit_order(
                account_id="crypto-usd",
                symbol="BTCUSDT",
                action="BUY",
                quantity=0.01,
                requested_price=50_000.0,
                executed_at="2026-08-17T15:00:00+00:00",
                signal_evidence={"note": "crypto"},
                user_approval=True,
                idempotency_key="crypto-req-1",
            )
            check(isinstance(trade, Trade), "Crypto BUY with no stop_loss still succeeds")
            position = repos["position"].get_open_position("crypto-usd", "BTCUSDT")
            check(position is not None and position.direction == "LONG", "Crypto Position opens LONG as before")
            check(position.stop_loss is None, "Crypto Position.stop_loss stays None (never required)")
    finally:
        if previous_market_env is None:
            os.environ.pop("AIOS_MARKET", None)
        else:
            os.environ["AIOS_MARKET"] = previous_market_env


def main() -> int:
    scenario_a_buy_missing_stop()
    scenario_b_sell_missing_stop()
    scenario_c_buy_valid_stop()
    scenario_d_sell_valid_stop()
    scenario_e_buy_invalid_direction()
    scenario_f_sell_invalid_direction()
    scenario_g_existing_long_next_order()
    scenario_h_existing_short_next_order()
    scenario_i_persistence()
    scenario_j_no_direction_mutation()
    scenario_k_idx_regression()
    scenario_l_us_regression()
    scenario_m_crypto_regression()

    print(f"\n{_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())