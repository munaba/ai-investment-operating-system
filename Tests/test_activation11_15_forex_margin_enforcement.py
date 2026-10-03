"""Standalone regression checks for Activation 11.15 -- Forex
required-margin enforcement in the real paper order path
(``Business.paper_trading_engine.PaperTradingEngine.submit_order()``).

Implements the roadmap's Activation 11 FOREX acceptance-gate item
"margin, pip value, stop-loss, dan maximum loss harus terbukti benar
melalui test numerik dan reconciliation", for the margin half only:

* ``Account.asset_class == "forex"`` ONLY: a paper order is rejected
  (``PRETRADE_REASON_FOREX_INSUFFICIENT_MARGIN``, zero writes) when
  the required margin (``Business.forex_margin_policy.
  calculate_required_margin`` -- ``price * quantity`` at 1:1 paper
  leverage) for the order's incremental NEW exposure exceeds
  ``Account.cash``.
* Margin is required only for NEW exposure, never for the gross order
  quantity: a BUY/SELL that reduces an existing opposite-direction
  position is never incorrectly margin-checked against its own gross
  notional.
* IDX/US/Crypto orders are completely unaffected -- this gate never
  evaluates for a non-Forex account.

This file exercises a real ``PaperTradingEngine`` + real
``PositionManager``/``PositionRepository``/``AccountRepository`` (+
the other Sprint 4 collaborators ``OrderLifecycleService``/
``ExecutionService``/``OrderIdempotencyRepository``) against a
temporary SQLite database, following
``Tests/test_activation11_14_forex_stop_loss_enforcement.py``'s
established harness (``_build_engine``/``_row_counts``/
``_expect_pretrade_rejection`` style).

Run directly with
``python Tests/test_activation11_15_forex_margin_enforcement.py``
-- no external test framework required.
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
from Business.paper_trading_engine import (  # noqa: E402
    PRETRADE_REASON_FOREX_INSUFFICIENT_MARGIN,
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


def _build_engine(tmp_dir: str, *, forex_cash: float):
    """Build a real PaperTradingEngine wired to real repositories, with
    a single 'forex-id' (asset_class='forex') account whose starting
    ``cash`` is the scenario-supplied ``forex_cash`` -- every scenario
    needs a different exact cash figure to exercise the margin
    boundary, unlike Activation 11.14's fixed-cash harness.
    """
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "forex_margin_enforcement.db")
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
        signal_evidence={"note": "forex margin test"},
        user_approval=True,
        idempotency_key="margin-req-001",
    )
    kwargs.update(overrides)
    return kwargs


def _expect_pretrade_rejection(engine, repos, reason: str, description: str, **overrides) -> None:
    before = _row_counts(repos)
    account_before = repos["account"].get_by_id("forex-id")

    raised_reason = None
    try:
        engine.submit_order(**_forex_kwargs(**overrides))
    except ValidationError as exc:
        raised_reason = exc.details.get("reason")

    check(raised_reason == reason, f"{description}: ValidationError reason == '{reason}'")

    after = _row_counts(repos)
    check(before == after, f"{description}: zero writes to accounts/positions/orders/trades")

    account_after = repos["account"].get_by_id("forex-id")
    check(
        account_before.cash == account_after.cash,
        f"{description}: Account.cash unchanged",
    )


# ---------------------------------------------------------------------------
# A -- BUY insufficient margin (fresh account, no existing position)
# ---------------------------------------------------------------------------
def scenario_a_buy_insufficient_margin():
    print("\n[Scenario A] Forex BUY insufficient margin rejects, zero writes, cash unchanged")
    with tempfile.TemporaryDirectory() as tmp:
        # cash 10,000 < required_margin 10,000 * 1.1000 = 11,000
        engine, repos = _build_engine(tmp, forex_cash=10_000.0)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_FOREX_INSUFFICIENT_MARGIN,
            "Forex BUY (new LONG) with cash 10,000 < required margin 11,000",
            action="BUY", quantity=10_000.0, requested_price=1.1000, stop_loss=1.0950,
        )


# ---------------------------------------------------------------------------
# B -- BUY exactly affordable
# ---------------------------------------------------------------------------
def scenario_b_buy_exact_margin():
    print("\n[Scenario B] Forex BUY with cash == required margin succeeds")
    with tempfile.TemporaryDirectory() as tmp:
        # cash 11,000 == required_margin 10,000 * 1.1000 = 11,000
        engine, repos = _build_engine(tmp, forex_cash=11_000.0)
        trade = engine.submit_order(**_forex_kwargs(
            action="BUY", quantity=10_000.0, requested_price=1.1000, stop_loss=1.0950,
        ))
        check(isinstance(trade, Trade), "submit_order() returns a Trade")

        order = repos["order"].get_by_id(trade.order_id)
        check(order.status == "FILLED", "Order.status == FILLED")

        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position is not None, "a Position was created")
        check(position.direction == "LONG", "Position.direction == LONG")
        check(position.quantity == 10_000.0, "Position.quantity == 10,000")
        check(position.average_price == 1.1000, "Position.average_price == 1.1000")

        account = repos["account"].get_by_id("forex-id")
        check(account.cash == 0.0, "Account.cash == 0.0 after spending the full exact margin")


# ---------------------------------------------------------------------------
# C -- BUY with spare margin
# ---------------------------------------------------------------------------
def scenario_c_buy_spare_margin():
    print("\n[Scenario C] Forex BUY with cash > required margin succeeds")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, forex_cash=50_000.0)
        trade = engine.submit_order(**_forex_kwargs(
            action="BUY", quantity=10_000.0, requested_price=1.1000, stop_loss=1.0950,
        ))
        check(isinstance(trade, Trade), "submit_order() returns a Trade")

        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position is not None and position.direction == "LONG", "LONG Position created")

        account = repos["account"].get_by_id("forex-id")
        check(account.cash == 39_000.0, "Account.cash == 39,000 (50,000 - 11,000 required margin)")


# ---------------------------------------------------------------------------
# D -- SELL opens SHORT but insufficient margin
# ---------------------------------------------------------------------------
def scenario_d_sell_short_insufficient_margin():
    print("\n[Scenario D] Forex SELL opening SHORT with insufficient margin rejects, zero writes")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, forex_cash=10_000.0)
        _expect_pretrade_rejection(
            engine, repos, PRETRADE_REASON_FOREX_INSUFFICIENT_MARGIN,
            "Forex SELL (new SHORT) with cash 10,000 < required margin 11,000",
            action="SELL", quantity=10_000.0, requested_price=1.1000, stop_loss=1.1050,
        )


# ---------------------------------------------------------------------------
# E -- SELL opens SHORT exactly affordable
# ---------------------------------------------------------------------------
def scenario_e_sell_short_exact_margin():
    print("\n[Scenario E] Forex SELL opening SHORT with cash == required margin succeeds")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, forex_cash=11_000.0)
        trade = engine.submit_order(**_forex_kwargs(
            action="SELL", quantity=10_000.0, requested_price=1.1000, stop_loss=1.1050,
        ))
        check(isinstance(trade, Trade), "submit_order() returns a Trade")

        order = repos["order"].get_by_id(trade.order_id)
        check(order.status == "FILLED", "Order.status == FILLED")

        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position is not None, "a Position was created")
        check(position.direction == "SHORT", "Position.direction == SHORT")
        check(position.quantity == 10_000.0, "Position.quantity == 10,000")

        account = repos["account"].get_by_id("forex-id")
        # SELL credits gross_value (fee/tax default to 0.0): 11,000 + 11,000 = 22,000
        check(account.cash == 22_000.0, "Account.cash == 22,000 after the SELL credits gross_value")


# ---------------------------------------------------------------------------
# F -- SELL adds to existing SHORT: only incremental exposure is margin-checked
# ---------------------------------------------------------------------------
def scenario_f_sell_adds_to_short_incremental_only():
    print("\n[Scenario F] Forex SELL adding to an existing SHORT margin-checks only the increment")
    with tempfile.TemporaryDirectory() as tmp:
        # Opening SELL: 5,000 @ 1.1000 -> required_margin 5,500, cash exactly covers it.
        engine, repos = _build_engine(tmp, forex_cash=5_500.0)
        engine.submit_order(**_forex_kwargs(
            action="SELL", quantity=5_000.0, requested_price=1.1000, stop_loss=1.1050,
            idempotency_key="f-req-1",
        ))
        account_after_open = repos["account"].get_by_id("forex-id")
        # cash: 5,500 + gross_value(5,500) = 11,000
        check(account_after_open.cash == 11_000.0, "cash == 11,000 after opening SHORT 5,000 @ 1.1000")

        # Second SELL adds 8,000 more to the SHORT. A naive/incorrect
        # implementation that margin-checked the FULL resulting SHORT
        # quantity (5,000 + 8,000 = 13,000) would require
        # 13,000 * 1.1000 = 14,300 -- more than the current cash
        # (11,000) -- and would incorrectly reject. The correct,
        # incremental-only check only requires margin for the NEW
        # 8,000 units: 8,000 * 1.1000 = 8,800 <= 11,000 -> accepted.
        trade = engine.submit_order(**_forex_kwargs(
            action="SELL", quantity=8_000.0, requested_price=1.1000, stop_loss=1.1050,
            idempotency_key="f-req-2",
        ))
        check(isinstance(trade, Trade), "second SELL (adds to SHORT) accepted on incremental margin only")

        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position.direction == "SHORT", "Position.direction stays SHORT")
        check(position.quantity == 13_000.0, "Position.quantity == 13,000 after the merge")

        account_after_add = repos["account"].get_by_id("forex-id")
        # cash: 11,000 + gross_value(8,000 * 1.1000 = 8,800) = 19,800
        check(account_after_add.cash == 19_800.0, "cash == 19,800 after the second SELL credits its gross_value")


# ---------------------------------------------------------------------------
# G -- SELL reduces existing LONG: never margin-checked as new exposure
# ---------------------------------------------------------------------------
def scenario_g_sell_reduces_long_no_margin_required():
    print("\n[Scenario G] Forex SELL fully reducing an existing LONG is never margin-checked")
    with tempfile.TemporaryDirectory() as tmp:
        # cash intentionally far below the gross sell notional
        # (10,000 * 1.1000 = 11,000) a fresh BUY-equivalent margin
        # check would require -- the LONG position itself is seeded
        # directly (PositionRepository.create), bypassing the engine,
        # so no BUY funding is needed to set this scenario up.
        engine, repos = _build_engine(tmp, forex_cash=100.0)
        repos["position"].create(
            account_id="forex-id",
            symbol="EURUSD",
            quantity=10_000.0,
            average_price=1.1000,
            realized_pnl=0.0,
            status="open",
            direction="LONG",
        )

        trade = engine.submit_order(**_forex_kwargs(
            action="SELL", quantity=10_000.0, requested_price=1.1000, stop_loss=1.0950,
        ))
        check(
            isinstance(trade, Trade),
            "SELL fully reducing the LONG is accepted despite cash 100 << gross notional 11,000",
        )

        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position is None, "Position is fully closed (no longer OPEN) after the full reduce")

        closed = repos["position"].list_all()[0]
        check(closed.status == "closed", "the closed Position's status == 'closed'")
        check(closed.quantity == 0.0, "the closed Position's quantity == 0.0")

        account = repos["account"].get_by_id("forex-id")
        # SELL always credits gross_value regardless of exposure
        # direction (unchanged, out-of-scope AccountBalanceService
        # cash-ledger behavior): 100 + 10,000 * 1.1000 = 11,100.
        check(account.cash == 11_100.0, "cash == 11,100 after the SELL credits its gross_value")


# ---------------------------------------------------------------------------
# H -- BUY reduces existing SHORT: never margin-checked as new exposure
# ---------------------------------------------------------------------------
def scenario_h_buy_reduces_short_no_margin_required():
    print("\n[Scenario H] Forex BUY partially reducing an existing SHORT is never margin-checked")
    with tempfile.TemporaryDirectory() as tmp:
        # Existing SHORT is larger (8,000) than the reducing BUY
        # (4,000). Cash (5,000) is deliberately: (a) sufficient for
        # the actual BUY debit this reducing trade needs
        # (4,000 * 1.1000 = 4,400 <= 5,000), but (b) far below what a
        # naive/incorrect implementation would require if it
        # (incorrectly) computed required margin off the RESULTING/
        # total exposure (8,000 + 4,000 = 12,000 -> 12,000 * 1.1000 =
        # 13,200 > 5,000) instead of recognizing this trade reduces
        # exposure and needs zero new margin.
        engine, repos = _build_engine(tmp, forex_cash=5_000.0)
        repos["position"].create(
            account_id="forex-id",
            symbol="EURUSD",
            quantity=8_000.0,
            average_price=1.1000,
            realized_pnl=0.0,
            status="open",
            direction="SHORT",
        )

        trade = engine.submit_order(**_forex_kwargs(
            action="BUY", quantity=4_000.0, requested_price=1.1000, stop_loss=1.1050,
        ))
        check(
            isinstance(trade, Trade),
            "BUY partially reducing the SHORT is accepted (zero new-exposure margin required)",
        )

        position = repos["position"].get_open_position("forex-id", "EURUSD")
        check(position is not None, "the SHORT Position is still OPEN (partial reduce)")
        check(position.direction == "SHORT", "Position.direction stays SHORT")
        check(position.quantity == 4_000.0, "Position.quantity == 4,000 (8,000 - 4,000)")

        account = repos["account"].get_by_id("forex-id")
        # BUY debits gross_value + fee + tax (default fee/tax 0.0):
        # 5,000 - 4,000 * 1.1000 = 600.0
        check(account.cash == 600.0, "cash == 600 after the BUY debits its own gross_value")


# ---------------------------------------------------------------------------
# I -- IDX regression (unaffected by the Forex margin gate)
# ---------------------------------------------------------------------------
def scenario_i_idx_regression():
    print("\n[Scenario I] existing IDX order is unaffected by the Forex margin gate")
    with tempfile.TemporaryDirectory() as tmp:
        engine, repos = _build_engine(tmp, forex_cash=0.0)
        cfg = DatabaseConfig(db_path=Path(tmp) / "forex_margin_enforcement.db")
        # Reuse the same engine's account_repository to add a second,
        # non-Forex account to the same already-migrated database.
        repos["account"].create(
            account_id="paper-id",
            account_name="Paper Indonesia",
            mode="paper",
            currency="IDR",
            asset_class="stock_id",
            cash=100_000_000.0,
            equity=100_000_000.0,
            buying_power=100_000_000.0,
        )
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
            # stop_loss deliberately omitted -- defaults to None, and
            # the Forex margin gate is scoped to asset_class ==
            # "forex" only, so this IDX BUY never evaluates it.
        )
        check(isinstance(trade, Trade), "IDX BUY (non-Forex) still succeeds unaffected")
        position = repos["position"].get_open_position("paper-id", "BBCA")
        check(position is not None and position.direction == "LONG", "IDX Position opens LONG as before")


def main() -> int:
    scenario_a_buy_insufficient_margin()
    scenario_b_buy_exact_margin()
    scenario_c_buy_spare_margin()
    scenario_d_sell_short_insufficient_margin()
    scenario_e_sell_short_exact_margin()
    scenario_f_sell_adds_to_short_incremental_only()
    scenario_g_sell_reduces_long_no_margin_required()
    scenario_h_buy_reduces_short_no_margin_required()
    scenario_i_idx_regression()

    print(f"\n{_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())