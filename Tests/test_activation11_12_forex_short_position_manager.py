"""Standalone regression checks for Activation 11.12 -- Forex SHORT-
position semantics in ``Business.position_manager.PositionManager``.

Implements the ONE piece of Activation 11.10's LOCKED persistence
decision (Decision C) still outstanding after Activation 11.11 made
``Position.direction`` persistable:

* Forex (``Account.asset_class == "forex"``) SELL with no OPEN
  position opens a SHORT position instead of raising.
* Direction is immutable for a position's lifetime -- a same-direction
  trade (BUY on LONG / SELL on SHORT) merges (quantity-weighted
  average price); an opposite-direction trade (SELL on LONG / BUY on
  SHORT) reduces/closes, with direction-signed realized P/L.
* Same-trade reversal (close-and-flip) stays a ``ValidationError``.
* Non-Forex accounts keep the pre-11.12 "SELL with no OPEN position"
  -> ``ValidationError`` behavior unchanged.

This file exercises ``PositionManager`` + a real ``PositionRepository``
(+ a real ``AccountRepository`` for the Forex-detection lookup) against
a temporary SQLite database -- no mocking of ``PositionManager``
itself, no ``PaperTradingEngine`` involved, matching
``Tests/test_position_manager.py``'s and
``Tests/test_activation11_11_position_direction_persistence.py``'s
established style.

Run directly with
``python Tests/test_activation11_12_forex_short_position_manager.py``
-- no external test framework required.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.position_manager import PositionManager  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.models import Trade  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402

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


def _build_service(tmp_dir: str, db_name: str = "forex_position_manager.db"):
    """Build a real PositionManager wired to real repositories, with
    a 'forex-id' (asset_class='forex'), 'paper-id' (stock_id),
    'us-usd' (stock_us), and 'crypto-usd' (crypto) account already
    created -- covers scenario K (non-Forex regression) without any
    extra per-scenario setup.
    """
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / db_name)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    account_repo.create(
        account_id="forex-id",
        account_name="Forex USD",
        mode="paper",
        currency="USD",
        asset_class="forex",
        cash=100_000.0,
        equity=100_000.0,
        buying_power=100_000.0,
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
    position_repo = PositionRepository(manager)
    service = PositionManager(position_repo, account_repo)
    return service, position_repo, account_repo


def _trade(trade_id=1, order_id=1, account_id="forex-id", symbol="EURUSD",
           action="SELL", quantity=10_000.0, fill_price=1.1000,
           fee=0.0, tax=0.0):
    return Trade(
        trade_id=trade_id,
        order_id=order_id,
        account_id=account_id,
        symbol=symbol,
        action=action,
        quantity=quantity,
        fill_price=fill_price,
        fee=fee,
        tax=tax,
        executed_at="2026-08-17T10:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# A -- Forex SELL opens SHORT
# ---------------------------------------------------------------------------
def scenario_a_forex_sell_opens_short():
    print("\n[Scenario A] Forex SELL with no OPEN position opens a SHORT")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        position = service.apply_trade(
            _trade(action="SELL", quantity=10_000.0, fill_price=1.1000)
        )

        check(position.direction == "SHORT", "direction == 'SHORT'")
        check(position.quantity == 10_000.0, "quantity == 10,000")
        check(position.average_price == 1.1000, "average_price == 1.1000 (the SELL's fill_price)")
        check(position.status == "open", "status == 'open'")
        check(position.realized_pnl == 0.0, "realized_pnl seeded at 0.0 on a fresh SHORT, like a fresh LONG")

        stored = repo.get_open_position("forex-id", "EURUSD")
        check(
            stored is not None and stored.position_id == position.position_id,
            "the new SHORT is persisted as the OPEN position for forex-id/EURUSD",
        )
        return position.position_id


# ---------------------------------------------------------------------------
# B -- Forex SELL merges into SHORT
# ---------------------------------------------------------------------------
def scenario_b_forex_sell_merges_short():
    print("\n[Scenario B] a second Forex SELL merges into the existing SHORT")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        service.apply_trade(_trade(action="SELL", quantity=10_000.0, fill_price=1.1000))

        merged = service.apply_trade(
            _trade(trade_id=2, order_id=2, action="SELL", quantity=5_000.0, fill_price=1.1050)
        )

        expected_avg = (10_000.0 * 1.1000 + 5_000.0 * 1.1050) / 15_000.0
        check(merged.direction == "SHORT", "direction stays 'SHORT' after merging a second SELL")
        check(merged.quantity == 15_000.0, "quantity == 15,000 (10,000 + 5,000)")
        check(
            abs(merged.average_price - expected_avg) < 1e-9,
            f"average_price == quantity-weighted average ({expected_avg})",
        )
        check(merged.status == "open", "status stays 'open' after a same-direction merge")

        stored = repo.get_open_position("forex-id", "EURUSD")
        check(stored.quantity == 15_000.0, "the merged SHORT is what's persisted as OPEN")
        return service, repo


# ---------------------------------------------------------------------------
# C -- Forex BUY reduces SHORT
# ---------------------------------------------------------------------------
def scenario_c_forex_buy_reduces_short():
    print("\n[Scenario C] a Forex BUY reduces the existing SHORT with direction-signed P/L")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        service.apply_trade(_trade(action="SELL", quantity=10_000.0, fill_price=1.1000))
        service.apply_trade(
            _trade(trade_id=2, order_id=2, action="SELL", quantity=5_000.0, fill_price=1.1050)
        )
        position_before = repo.get_open_position("forex-id", "EURUSD")
        average_price = position_before.average_price

        reduced = service.apply_trade(
            _trade(trade_id=3, order_id=3, action="BUY", quantity=5_000.0, fill_price=1.0900,
                   fee=1.5, tax=0.5)
        )

        expected_pnl_delta = (average_price - 1.0900) * 5_000.0
        expected_realized_pnl = 0.0 + expected_pnl_delta - 1.5 - 0.5

        check(reduced.quantity == 10_000.0, "remaining quantity == 10,000 (15,000 - 5,000)")
        check(reduced.direction == "SHORT", "direction stays 'SHORT' while the position is still open")
        check(
            abs(reduced.realized_pnl - expected_realized_pnl) < 1e-9,
            "realized_pnl uses (average_price - fill_price) * quantity - fee - tax (SHORT formula)",
        )
        check(reduced.average_price == average_price, "average_price is left untouched by a reduce")
        check(reduced.status == "open", "status stays 'open' (10,000 still held)")


# ---------------------------------------------------------------------------
# D -- Forex BUY closes SHORT
# ---------------------------------------------------------------------------
def scenario_d_forex_buy_closes_short():
    print("\n[Scenario D] a Forex BUY for the exact remaining quantity closes the SHORT")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        service.apply_trade(_trade(action="SELL", quantity=10_000.0, fill_price=1.1000))
        service.apply_trade(
            _trade(trade_id=2, order_id=2, action="SELL", quantity=5_000.0, fill_price=1.1050)
        )
        service.apply_trade(
            _trade(trade_id=3, order_id=3, action="BUY", quantity=5_000.0, fill_price=1.0900)
        )
        remaining = repo.get_open_position("forex-id", "EURUSD")
        check(remaining.quantity == 10_000.0, "sanity check: 10,000 remaining before the closing BUY")

        closed = service.apply_trade(
            _trade(trade_id=4, order_id=4, action="BUY", quantity=10_000.0, fill_price=1.0800)
        )

        check(closed.quantity == 0.0, "quantity == 0 after the closing BUY")
        check(closed.status == "closed", "status == 'closed'")
        check(closed.direction == "SHORT", "direction remains 'SHORT' on the now-closed row")

        still_open = repo.get_open_position("forex-id", "EURUSD")
        check(still_open is None, "no OPEN position remains for forex-id/EURUSD -- the closed row is not reopened")
        return closed.position_id


# ---------------------------------------------------------------------------
# E -- After SHORT is closed, new BUY opens LONG
# ---------------------------------------------------------------------------
def scenario_e_new_buy_after_short_closed_opens_long():
    print("\n[Scenario E] a fresh BUY after the SHORT closed opens a brand-new LONG row")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        service.apply_trade(_trade(action="SELL", quantity=10_000.0, fill_price=1.1000))
        closed = service.apply_trade(
            _trade(trade_id=2, order_id=2, action="BUY", quantity=10_000.0, fill_price=1.0800)
        )
        check(closed.status == "closed", "sanity check: the SHORT is closed")

        reopened = service.apply_trade(
            _trade(trade_id=3, order_id=3, action="BUY", quantity=2_000.0, fill_price=1.0950)
        )

        check(reopened.direction == "LONG", "the new position opens as direction == 'LONG'")
        check(reopened.quantity == 2_000.0, "quantity == trade.quantity on the new LONG")
        check(reopened.status == "open", "status == 'open' on the new LONG")
        check(
            reopened.position_id != closed.position_id,
            "a NEW position row is created -- the closed SHORT row is not reused",
        )

        stored = repo.get_open_position("forex-id", "EURUSD")
        check(
            stored is not None and stored.position_id == reopened.position_id,
            "the new LONG is what's persisted as OPEN",
        )


# ---------------------------------------------------------------------------
# F -- Forex BUY opens LONG
# ---------------------------------------------------------------------------
def scenario_f_forex_buy_opens_long():
    print("\n[Scenario F] a Forex BUY on a fresh account still opens a LONG")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        position = service.apply_trade(
            _trade(action="BUY", symbol="GBPUSD", quantity=8_000.0, fill_price=1.2500)
        )

        check(position.direction == "LONG", "direction == 'LONG'")
        check(position.quantity == 8_000.0, "quantity == trade.quantity")
        check(position.average_price == 1.2500, "average_price == trade.fill_price")
        check(position.status == "open", "status == 'open'")


# ---------------------------------------------------------------------------
# G -- Forex BUY merges LONG
# ---------------------------------------------------------------------------
def scenario_g_forex_buy_merges_long():
    print("\n[Scenario G] a second Forex BUY merges into the existing LONG")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        service.apply_trade(_trade(action="BUY", symbol="GBPUSD", quantity=8_000.0, fill_price=1.2500))

        merged = service.apply_trade(
            _trade(trade_id=2, order_id=2, action="BUY", symbol="GBPUSD",
                   quantity=2_000.0, fill_price=1.2600)
        )

        expected_avg = (8_000.0 * 1.2500 + 2_000.0 * 1.2600) / 10_000.0
        check(merged.direction == "LONG", "direction stays 'LONG'")
        check(merged.quantity == 10_000.0, "quantity == 10,000 (8,000 + 2,000)")
        check(
            abs(merged.average_price - expected_avg) < 1e-9,
            f"average_price == quantity-weighted average ({expected_avg})",
        )


# ---------------------------------------------------------------------------
# H -- Forex SELL reduces LONG
# ---------------------------------------------------------------------------
def scenario_h_forex_sell_reduces_long():
    print("\n[Scenario H] a Forex SELL reduces an existing LONG using the unchanged LONG realized-P/L formula")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        service.apply_trade(_trade(action="BUY", symbol="GBPUSD", quantity=8_000.0, fill_price=1.2500))

        reduced = service.apply_trade(
            _trade(trade_id=2, order_id=2, action="SELL", symbol="GBPUSD",
                   quantity=3_000.0, fill_price=1.2700, fee=1.0, tax=0.5)
        )

        expected_pnl_delta = (1.2700 - 1.2500) * 3_000.0
        expected_realized_pnl = 0.0 + expected_pnl_delta - 1.0 - 0.5

        check(reduced.quantity == 5_000.0, "quantity == 5,000 (8,000 - 3,000)")
        check(reduced.direction == "LONG", "direction remains 'LONG'")
        check(reduced.average_price == 1.2500, "average_price is left untouched")
        check(
            abs(reduced.realized_pnl - expected_realized_pnl) < 1e-9,
            "realized_pnl uses (fill_price - average_price) * quantity - fee - tax (LONG formula, unchanged)",
        )
        check(reduced.status == "open", "status stays 'open' (5,000 still held)")


# ---------------------------------------------------------------------------
# I -- Forex SELL closes LONG
# ---------------------------------------------------------------------------
def scenario_i_forex_sell_closes_long():
    print("\n[Scenario I] a Forex SELL for the exact remaining quantity closes the LONG")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        service.apply_trade(_trade(action="BUY", symbol="GBPUSD", quantity=8_000.0, fill_price=1.2500))

        closed = service.apply_trade(
            _trade(trade_id=2, order_id=2, action="SELL", symbol="GBPUSD",
                   quantity=8_000.0, fill_price=1.2700)
        )

        check(closed.quantity == 0.0, "quantity == 0")
        check(closed.status == "closed", "status == 'closed'")
        check(closed.direction == "LONG", "direction remains 'LONG' on the now-closed row")

        still_open = repo.get_open_position("forex-id", "GBPUSD")
        check(still_open is None, "no OPEN position remains for forex-id/GBPUSD")


# ---------------------------------------------------------------------------
# J -- Same-trade reversal rejected
# ---------------------------------------------------------------------------
def scenario_j_same_trade_reversal_rejected():
    print("\n[Scenario J] a same-trade reversal (close-and-flip) is rejected on both sides")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)

        # SHORT 10,000, then BUY 15,000 in one trade -> reject.
        short_position = service.apply_trade(
            _trade(action="SELL", symbol="EURUSD", quantity=10_000.0, fill_price=1.1000)
        )
        raised = False
        try:
            service.apply_trade(
                _trade(trade_id=2, order_id=2, action="BUY", symbol="EURUSD",
                       quantity=15_000.0, fill_price=1.0900)
            )
        except ValidationError:
            raised = True
        check(raised, "BUY 15,000 against a 10,000 SHORT raises ValidationError (no same-trade flip)")

        unchanged_short = repo.get_by_id(short_position.position_id)
        check(unchanged_short.quantity == 10_000.0, "the original SHORT's quantity is unchanged after the rejected BUY")
        check(unchanged_short.status == "open", "the original SHORT's status is unchanged (still open)")
        check(unchanged_short.direction == "SHORT", "the original SHORT's direction is unchanged")

        # LONG 10,000, then SELL 15,000 in one trade -> reject.
        long_position = service.apply_trade(
            _trade(trade_id=3, order_id=3, action="BUY", symbol="GBPUSD",
                   quantity=10_000.0, fill_price=1.2500)
        )
        raised = False
        try:
            service.apply_trade(
                _trade(trade_id=4, order_id=4, action="SELL", symbol="GBPUSD",
                       quantity=15_000.0, fill_price=1.2700)
            )
        except ValidationError:
            raised = True
        check(raised, "SELL 15,000 against a 10,000 LONG raises ValidationError (no same-trade flip)")

        unchanged_long = repo.get_by_id(long_position.position_id)
        check(unchanged_long.quantity == 10_000.0, "the original LONG's quantity is unchanged after the rejected SELL")
        check(unchanged_long.status == "open", "the original LONG's status is unchanged (still open)")
        check(unchanged_long.direction == "LONG", "the original LONG's direction is unchanged")


# ---------------------------------------------------------------------------
# K -- Non-Forex SELL with no position remains rejected
# ---------------------------------------------------------------------------
def scenario_k_non_forex_sell_without_position_still_rejected():
    print("\n[Scenario K] non-Forex SELL with no OPEN position still raises ValidationError "
          "(IDX, US, Crypto -- Forex-specific behavior does not leak)")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)

        for account_id, symbol in (
            ("paper-id", "BBCA"),
            ("us-usd", "AAPL"),
            ("crypto-usd", "BTC-USD"),
        ):
            raised = False
            try:
                service.apply_trade(
                    _trade(account_id=account_id, symbol=symbol, action="SELL",
                           quantity=1.0, fill_price=100.0)
                )
            except ValidationError:
                raised = True
            check(raised, f"SELL with no OPEN position for {account_id}/{symbol} still raises ValidationError")

            still_none = repo.get_open_position(account_id, symbol)
            check(still_none is None, f"no position was created for {account_id}/{symbol}")


def scenario_k2_no_account_repository_never_opens_short():
    print("\n[Scenario K2] with NO account_repository supplied at all, even a Forex-account SELL "
          "with no OPEN position raises ValidationError (matches every pre-11.12 caller)")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "forex_no_account_repo.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
        MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
        manager = DatabaseManager(db, cfg)
        AccountRepository(manager).create(
            account_id="forex-id",
            account_name="Forex USD",
            mode="paper",
            currency="USD",
            asset_class="forex",
            cash=100_000.0,
            equity=100_000.0,
            buying_power=100_000.0,
        )
        position_repo = PositionRepository(manager)
        service = PositionManager(position_repo)  # no account_repository at all

        raised = False
        try:
            service.apply_trade(_trade(account_id="forex-id", action="SELL",
                                        quantity=10_000.0, fill_price=1.1000))
        except ValidationError:
            raised = True
        check(
            raised,
            "PositionManager(position_repo) with no account_repository never opens a SHORT, "
            "even for a Forex account -- preserves pre-11.12 behavior for callers that don't pass one",
        )


# ---------------------------------------------------------------------------
# L -- Direction survives repository round-trip
# ---------------------------------------------------------------------------
def scenario_l_direction_survives_round_trip():
    print("\n[Scenario L] direction survives a SHORT -> merge -> reduce round-trip through the repository")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)

        opened = service.apply_trade(
            _trade(action="SELL", quantity=10_000.0, fill_price=1.1000)
        )
        reread_after_open = repo.get_by_id(opened.position_id)
        check(reread_after_open.direction == "SHORT", "direction == 'SHORT' after reload following open")

        service.apply_trade(
            _trade(trade_id=2, order_id=2, action="SELL", quantity=5_000.0, fill_price=1.1050)
        )
        reread_after_merge = repo.get_by_id(opened.position_id)
        check(reread_after_merge.direction == "SHORT", "direction == 'SHORT' after reload following merge")
        check(reread_after_merge.quantity == 15_000.0, "quantity == 15,000 after reload following merge")

        service.apply_trade(
            _trade(trade_id=3, order_id=3, action="BUY", quantity=4_000.0, fill_price=1.0900)
        )
        reread_after_reduce = repo.get_by_id(opened.position_id)
        check(reread_after_reduce.direction == "SHORT", "direction == 'SHORT' after reload following reduce")
        check(reread_after_reduce.quantity == 11_000.0, "quantity == 11,000 after reload following reduce")
        check(reread_after_reduce.status == "open", "status == 'open' after reload following reduce")


def main() -> int:
    scenario_a_forex_sell_opens_short()
    scenario_b_forex_sell_merges_short()
    scenario_c_forex_buy_reduces_short()
    scenario_d_forex_buy_closes_short()
    scenario_e_new_buy_after_short_closed_opens_long()
    scenario_f_forex_buy_opens_long()
    scenario_g_forex_buy_merges_long()
    scenario_h_forex_sell_reduces_long()
    scenario_i_forex_sell_closes_long()
    scenario_j_same_trade_reversal_rejected()
    scenario_k_non_forex_sell_without_position_still_rejected()
    scenario_k2_no_account_repository_never_opens_short()
    scenario_l_direction_survives_round_trip()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 11.12 FOREX SHORT POSITION MANAGER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())