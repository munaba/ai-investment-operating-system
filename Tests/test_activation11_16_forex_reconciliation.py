"""Standalone regression checks for Activation 11.16 -- Forex
reconciliation / state consistency
(``Business.reconciliation_engine.ReconciliationEngine``, extended).

Implements the roadmap's Activation 11 FOREX acceptance-gate item
"margin, pip value, stop-loss, dan maximum loss harus terbukti benar
melalui test numerik dan reconciliation", for the reconciliation half:
after a real Forex paper BUY/SELL, ``ReconciliationEngine.
reconcile_account()`` must be able to recompute direction/stop-loss
validity/pip value/required margin/maximum loss from persisted state
and detect a mismatch when persisted state is corrupted.

Drives every positive scenario through the real production path
(``Business.paper_trading_engine.PaperTradingEngine.submit_order()``),
following ``Tests/test_activation11_15_forex_margin_enforcement.py``'s
established harness (``_build_engine``/``check`` style) and
``Tests/test_reconciliation_engine.py``'s pattern of driving
``ReconciliationEngine`` off the same real repositories the engine
under test just wrote through -- no fabricated ``Position``/``Trade``
objects handed straight to ``ReconciliationEngine`` for any positive
scenario.

WHICH PRICE (see also ``Business.reconciliation_engine.
ReconciliationEngine._check_forex_state``'s own inline rationale):
margin and maximum-loss reconstruction both use ``Position.
average_price`` -- PositionManager's own quantity-weighted entry
basis, correct across multiple merged trades, and the exact reference
price ``is_stop_loss_side_valid`` is already defined against for an
existing position. Neither ``Trade.fill_price`` (single-trade, not
representative of a merged position) nor ``Order.requested_price``
(pre-trade only) is used.

RISK-STATE MISMATCH LIMITATION (Scenario K, roadmap-required):
``pip_value``/``required_margin``/``maximum_loss`` are derived-only --
no schema persists any of the three (LOCKED, this Activation does not
change that). There is therefore no persisted field for any of those
three to independently corrupt and compare against a recomputation:
the only way this engine can report a mismatch for them is if the
recomputation itself cannot be performed at all (a ``ValidationError``
from the underlying policy function -- see ``FOREX_PIP_VALUE_MISMATCH``
/ ``FOREX_MARGIN_MISMATCH``/``FOREX_MAX_LOSS_MISMATCH`` below). Since
every currently-supported pair/quantity/price/stop-loss combination
this Activation can legally persist is valid input to all three policy
functions, no test below manufactures a call to those three that
raises. Scenario K instead corrupts ``Position.quantity`` directly (a
value the pre-existing, generic Trade<->Position invariant already
covers, and continues to cover unmodified for a Forex account) to
prove a deterministic mismatch is still detected end-to-end for a
Forex position -- exactly what the roadmap brief's own Scenario K text
anticipates ("If a particular mismatch cannot currently be represented
because risk values are derived, do NOT add schema just for this
test. Document the limitation.").

Run directly with
``python Tests/test_activation11_16_forex_reconciliation.py`` -- no
external test framework required.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Business.reconciliation_engine import ReconciliationEngine  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
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


# ---------------------------------------------------------------------------
# Harness -- mirrors Tests/test_activation11_15_forex_margin_enforcement.py
# ---------------------------------------------------------------------------


def _build_engine(db_path: Path, *, forex_cash: float = 10_000_000.0):
    """Build a real PaperTradingEngine + ReconciliationEngine wired to
    real repositories over ``db_path``, with a single 'forex-id'
    (asset_class='forex') account. ``forex_cash`` defaults generously
    high -- this file's focus is reconciliation, not the margin
    boundary itself (already covered by Activation 11.15's own test
    file), so scenarios below should never be pretrade-rejected for
    insufficient margin.
    """
    cfg = DatabaseConfig(db_path=db_path)
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
        cash=forex_cash,
        equity=forex_cash,
        buying_power=forex_cash,
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
    reconciliation_engine = ReconciliationEngine(
        order_repository=order_repo,
        trade_repository=trade_repo,
        account_repository=account_repo,
        position_repository=position_repo,
    )
    repos = {
        "account": account_repo,
        "position": position_repo,
        "order": order_repo,
        "trade": trade_repo,
        "idempotency": idempotency_repo,
    }
    return engine, reconciliation_engine, repos


_ORDER_SEQ = [0]


def _submit(engine, *, symbol, action, quantity, requested_price, stop_loss):
    _ORDER_SEQ[0] += 1
    return engine.submit_order(
        account_id="forex-id",
        symbol=symbol,
        action=action,
        quantity=quantity,
        requested_price=requested_price,
        executed_at=f"2026-08-17T10:{_ORDER_SEQ[0]:02d}:00+00:00",
        signal_evidence={"note": "forex reconciliation test"},
        user_approval=True,
        idempotency_key=f"reconciliation-{_ORDER_SEQ[0]:04d}",
        stop_loss=stop_loss,
    )


# ---------------------------------------------------------------------------
# Scenarios A/C/E/G -- Forex LONG lifecycle (EUR/USD), reconciling after
# every step: open, add, partial reduction, close.
# ---------------------------------------------------------------------------


def scenario_long_lifecycle():
    print("\n[Scenarios A/C/E/G] Forex LONG open -> add -> partial reduce -> close, "
          "reconciling after every step")
    with tempfile.TemporaryDirectory() as tmp:
        engine, reconciliation, repos = _build_engine(Path(tmp) / "long.db")

        # -- A: LONG open --------------------------------------------------
        _submit(
            engine, symbol="EURUSD", action="BUY", quantity=10_000.0,
            requested_price=1.1000, stop_loss=1.0950,
        )
        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position is not None and position.direction == "LONG", "[A] LONG Position opened")
        check(position.quantity == 10_000.0, "[A] Position.quantity == 10,000")
        check(position.average_price == 1.1000, "[A] Position.average_price == 1.1000")

        result = reconciliation.reconcile_account("forex-id")
        check(result.consistent, "[A] LONG open reconciles CONSISTENT")
        check(result.violations == [], "[A] no violations")

        # -- C: LONG add ------------------------------------------------
        _submit(
            engine, symbol="EURUSD", action="BUY", quantity=5_000.0,
            requested_price=1.1020, stop_loss=1.0950,
        )
        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position.quantity == 15_000.0, "[C] Position.quantity == 15,000 after add")

        result = reconciliation.reconcile_account("forex-id")
        check(result.consistent, "[C] LONG add reconciles CONSISTENT")

        # -- E: LONG partial reduction -----------------------------------
        _submit(
            engine, symbol="EURUSD", action="SELL", quantity=5_000.0,
            requested_price=1.1030, stop_loss=1.0950,
        )
        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position.quantity == 10_000.0, "[E] Position.quantity == 10,000 after partial reduce")
        check(position.direction == "LONG", "[E] Position.direction still LONG after partial reduce")

        result = reconciliation.reconcile_account("forex-id")
        check(result.consistent, "[E] LONG partial reduction reconciles CONSISTENT")

        # -- G: LONG close -------------------------------------------------
        _submit(
            engine, symbol="EURUSD", action="SELL", quantity=10_000.0,
            requested_price=1.1050, stop_loss=1.0950,
        )
        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position is None, "[G] no OPEN position remains after full close")

        result = reconciliation.reconcile_account("forex-id")
        check(result.consistent, "[G] LONG close reconciles CONSISTENT")

        return tmp  # kept alive by caller for the restart/recovery scenario


# ---------------------------------------------------------------------------
# Scenarios B/D/F/H -- Forex SHORT lifecycle (GBP/USD), reconciling after
# every step: open, add, partial reduction, close.
# ---------------------------------------------------------------------------


def scenario_short_lifecycle():
    print("\n[Scenarios B/D/F/H] Forex SHORT open -> add -> partial reduce -> close, "
          "reconciling after every step")
    with tempfile.TemporaryDirectory() as tmp:
        engine, reconciliation, repos = _build_engine(Path(tmp) / "short.db")

        # -- B: SHORT open (SELL with no OPEN position, Forex-only) ------
        _submit(
            engine, symbol="GBPUSD", action="SELL", quantity=10_000.0,
            requested_price=1.2500, stop_loss=1.2550,
        )
        position = repos["position"].get_open_position("forex-id", "GBPUSD")
        check(position is not None and position.direction == "SHORT", "[B] SHORT Position opened")
        check(position.quantity == 10_000.0, "[B] Position.quantity == 10,000")
        check(position.average_price == 1.2500, "[B] Position.average_price == 1.2500")

        result = reconciliation.reconcile_account("forex-id")
        check(result.consistent, "[B] SHORT open reconciles CONSISTENT")
        check(result.violations == [], "[B] no violations")

        # -- D: SHORT add (SELL merging into existing SHORT) --------------
        _submit(
            engine, symbol="GBPUSD", action="SELL", quantity=5_000.0,
            requested_price=1.2480, stop_loss=1.2550,
        )
        position = repos["position"].get_open_position("forex-id", "GBPUSD")
        check(position.quantity == 15_000.0, "[D] Position.quantity == 15,000 after add")
        check(position.direction == "SHORT", "[D] Position.direction still SHORT after add")

        result = reconciliation.reconcile_account("forex-id")
        check(result.consistent, "[D] SHORT add reconciles CONSISTENT")

        # -- F: SHORT partial reduction (BUY against the SHORT) -----------
        _submit(
            engine, symbol="GBPUSD", action="BUY", quantity=5_000.0,
            requested_price=1.2470, stop_loss=1.2550,
        )
        position = repos["position"].get_open_position("forex-id", "GBPUSD")
        check(position.quantity == 10_000.0, "[F] Position.quantity == 10,000 after partial reduce")
        check(position.direction == "SHORT", "[F] Position.direction still SHORT after partial reduce")

        result = reconciliation.reconcile_account("forex-id")
        check(result.consistent, "[F] SHORT partial reduction reconciles CONSISTENT")

        # -- H: SHORT close -------------------------------------------------
        _submit(
            engine, symbol="GBPUSD", action="BUY", quantity=10_000.0,
            requested_price=1.2460, stop_loss=1.2550,
        )
        position = repos["position"].get_open_position("forex-id", "GBPUSD")
        check(position is None, "[H] no OPEN position remains after full close")

        result = reconciliation.reconcile_account("forex-id")
        check(result.consistent, "[H] SHORT close reconciles CONSISTENT")


# ---------------------------------------------------------------------------
# Restart / recovery -- close the DB/application boundary and reconcile again
# through a fresh connection to the same SQLite file.
# ---------------------------------------------------------------------------


def scenario_restart_recovery():
    print("\n[Restart/recovery] Forex state survives a fresh DB connection and "
          "still reconciles CONSISTENT")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "restart.db"
        engine, reconciliation, repos = _build_engine(db_path)

        _submit(
            engine, symbol="EURUSD", action="BUY", quantity=10_000.0,
            requested_price=1.1000, stop_loss=1.0950,
        )
        _submit(
            engine, symbol="EURUSD", action="SELL", quantity=4_000.0,
            requested_price=1.1030, stop_loss=1.0950,
        )

        position_before = repos["position"].get_open_position("forex-id", "EURUSD")
        account_before = repos["account"].get_by_id("forex-id")

        result_before = reconciliation.reconcile_account("forex-id")
        check(result_before.consistent, "[Restart] CONSISTENT before restart")

        # -- close/reopen the DB/application boundary --------------------
        cfg = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg)
        account_repo2 = AccountRepository(manager2)
        position_repo2 = PositionRepository(manager2)
        order_repo2 = OrderRepository(manager2)
        trade_repo2 = TradeRepository(manager2)
        reconciliation2 = ReconciliationEngine(
            order_repository=order_repo2,
            trade_repository=trade_repo2,
            account_repository=account_repo2,
            position_repository=position_repo2,
        )

        position_after = position_repo2.get_open_position("forex-id", "EURUSD")
        account_after = account_repo2.get_by_id("forex-id")
        check(
            position_after is not None
            and position_after.quantity == position_before.quantity
            and position_after.average_price == position_before.average_price
            and position_after.direction == position_before.direction
            and position_after.stop_loss == position_before.stop_loss,
            "[Restart] Position state survives reconnect",
        )
        check(account_after.cash == account_before.cash, "[Restart] Account.cash survives reconnect")

        result_after = reconciliation2.reconcile_account("forex-id")
        check(result_after.consistent, "[Restart] CONSISTENT again through the fresh connection")


# ---------------------------------------------------------------------------
# Scenario I -- stop-loss corruption
# ---------------------------------------------------------------------------


def scenario_i_stop_loss_corruption():
    print("\n[Scenario I] Forex LONG stop-loss corruption is detected, not repaired")
    with tempfile.TemporaryDirectory() as tmp:
        engine, reconciliation, repos = _build_engine(Path(tmp) / "corrupt_sl.db")

        _submit(
            engine, symbol="EURUSD", action="BUY", quantity=10_000.0,
            requested_price=1.1000, stop_loss=1.0950,
        )
        position = repos["position"].get_open_position("forex-id", "EURUSD")

        # Directly corrupt the persisted stop_loss to the wrong side of
        # average_price for a LONG (1.1050 > 1.1000) -- bypasses the
        # production pipeline entirely, exactly like every other
        # corruption scenario in this suite; ReconciliationEngine itself
        # never performs this write.
        repos["position"].update(
            position_id=position.position_id,
            quantity=position.quantity,
            average_price=position.average_price,
            realized_pnl=position.realized_pnl,
            status=position.status,
            stop_loss=1.1050,
            take_profit=position.take_profit,
            buy_fee_accumulated=position.buy_fee_accumulated,
            direction=position.direction,
        )

        result = reconciliation.reconcile_account("forex-id")
        check(not result.consistent, "[I] corrupted stop-loss reconciles INCONSISTENT")
        check(
            any("FOREX_STOP_LOSS_INVALID" in v for v in result.violations),
            "[I] violation explicitly tagged FOREX_STOP_LOSS_INVALID",
        )

        position_after = repos["position"].get_by_id(position.position_id)
        check(
            position_after.stop_loss == 1.1050,
            "[I] no-repair: corrupted stop_loss is still 1.1050 after reconciliation",
        )


# ---------------------------------------------------------------------------
# Scenario J -- direction corruption
# ---------------------------------------------------------------------------


def scenario_j_direction_corruption():
    print("\n[Scenario J] Forex position direction corruption is detected, not repaired")
    with tempfile.TemporaryDirectory() as tmp:
        engine, reconciliation, repos = _build_engine(Path(tmp) / "corrupt_dir.db")

        _submit(
            engine, symbol="EURUSD", action="BUY", quantity=10_000.0,
            requested_price=1.1000, stop_loss=1.0950,
        )
        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position.direction == "LONG", "[J] sanity: position opened LONG from a BUY")

        # Corrupt persisted direction relative to trade history (this
        # account's only trade so far is a BUY, which always opens LONG)
        # -- bypasses the production pipeline entirely.
        repos["position"].update(
            position_id=position.position_id,
            quantity=position.quantity,
            average_price=position.average_price,
            realized_pnl=position.realized_pnl,
            status=position.status,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            buy_fee_accumulated=position.buy_fee_accumulated,
            direction="SHORT",
        )

        result = reconciliation.reconcile_account("forex-id")
        check(not result.consistent, "[J] corrupted direction reconciles INCONSISTENT")
        check(
            any("FOREX_DIRECTION_MISMATCH" in v for v in result.violations),
            "[J] violation explicitly tagged FOREX_DIRECTION_MISMATCH",
        )

        position_after = repos["position"].get_by_id(position.position_id)
        check(
            position_after.direction == "SHORT",
            "[J] no-repair: corrupted direction is still SHORT after reconciliation",
        )


# ---------------------------------------------------------------------------
# Scenario K -- risk-state mismatch (quantity corruption; see module
# docstring's "RISK-STATE MISMATCH LIMITATION" for why pip
# value/margin/maximum loss themselves cannot be independently
# corrupted without inventing schema).
# ---------------------------------------------------------------------------


def scenario_k_risk_state_mismatch():
    print("\n[Scenario K] Forex position quantity mismatch is detected (generic "
          "Trade<->Position invariant, unmodified, still covers Forex positions)")
    with tempfile.TemporaryDirectory() as tmp:
        engine, reconciliation, repos = _build_engine(Path(tmp) / "corrupt_qty.db")

        _submit(
            engine, symbol="EURUSD", action="BUY", quantity=10_000.0,
            requested_price=1.1000, stop_loss=1.0950,
        )
        position = repos["position"].get_open_position("forex-id", "EURUSD")

        repos["position"].update(
            position_id=position.position_id,
            quantity=12_345.0,
            average_price=position.average_price,
            realized_pnl=position.realized_pnl,
            status=position.status,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            buy_fee_accumulated=position.buy_fee_accumulated,
            direction=position.direction,
        )

        result = reconciliation.reconcile_account("forex-id")
        check(not result.consistent, "[K] corrupted quantity reconciles INCONSISTENT")
        check(
            any("quantity" in v and "12345.0" in v for v in result.violations),
            "[K] violation reports the quantity mismatch",
        )

        position_after = repos["position"].get_by_id(position.position_id)
        check(
            position_after.quantity == 12_345.0,
            "[K] no-repair: corrupted quantity is still 12,345.0 after reconciliation",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    scenario_long_lifecycle()
    scenario_short_lifecycle()
    scenario_restart_recovery()
    scenario_i_stop_loss_corruption()
    scenario_j_direction_corruption()
    scenario_k_risk_state_mismatch()

    print(f"\n{'=' * 70}\nTOTAL: {_PASS} passed, {_FAIL} failed\n{'=' * 70}")
    if _FAILURES:
        print("\nFailed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    sys.exit(0)