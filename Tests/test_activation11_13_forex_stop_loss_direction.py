"""Standalone regression checks for Activation 11.13 -- direction-aware
``stop_loss``/``take_profit`` validation in
``Business.position_manager.PositionManager.set_stop_loss_take_profit``.

Generalizes the pre-11.13 LONG-only rule using the already-persisted
``Position.direction`` (Activation 11.11/11.12):

* LONG (the default -- covers every pre-existing IDX/US/Crypto
  position unchanged): ``stop_loss`` below ``average_price``,
  ``take_profit`` above it.
* SHORT (Forex only, per Activation 11.12): the mirror image --
  ``stop_loss`` above ``average_price``, ``take_profit`` below it.
* Either direction: ``stop_loss``/``take_profit`` exactly equal to
  ``average_price`` is invalid.
* ``direction`` is read from the loaded ``Position`` (never accepted
  as an argument) and is never mutated by this method.

This file exercises ``PositionManager`` + a real ``PositionRepository``
(+ a real ``AccountRepository`` for opening a Forex SHORT via
``apply_trade``) against a temporary SQLite database -- no mocking of
``PositionManager`` itself, matching ``Tests/test_position_manager.py``
and ``Tests/test_activation11_12_forex_short_position_manager.py``'s
established style.

Run directly with
``python Tests/test_activation11_13_forex_stop_loss_direction.py`` --
no external test framework required.
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


def _build_service(tmp_dir: str, db_name: str = "forex_sl_tp_direction.db"):
    """Build a real PositionManager wired to real repositories, with a
    'forex-id' (asset_class='forex') and a 'paper-id' (stock_id)
    account already created.
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


def _open_long(service, tmp_symbol="BBCA"):
    """Open a LONG position (non-Forex account) at average_price 1.1000."""
    return service.apply_trade(
        _trade(account_id="paper-id", symbol=tmp_symbol, action="BUY",
               quantity=100.0, fill_price=1.1000)
    )


def _open_short(service, symbol="EURUSD"):
    """Open a Forex SHORT position at average_price 1.1000."""
    return service.apply_trade(
        _trade(account_id="forex-id", symbol=symbol, action="SELL",
               quantity=10_000.0, fill_price=1.1000)
    )


# ---------------------------------------------------------------------------
# A -- LONG stop-loss valid
# ---------------------------------------------------------------------------
def scenario_a_long_stop_loss_valid():
    print("\n[Scenario A] LONG stop_loss below average_price is valid")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        position = _open_long(service)

        updated = service.set_stop_loss_take_profit(position.position_id, stop_loss=1.0950, take_profit=None)
        check(updated.stop_loss == 1.0950, "LONG stop_loss 1.0950 (< 1.1000) is accepted")
        check(updated.direction == "LONG", "direction stays LONG")


# ---------------------------------------------------------------------------
# B -- LONG stop-loss invalid above
# ---------------------------------------------------------------------------
def scenario_b_long_stop_loss_invalid_above():
    print("\n[Scenario B] LONG stop_loss above average_price is rejected")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        position = _open_long(service)

        raised = False
        try:
            service.set_stop_loss_take_profit(position.position_id, stop_loss=1.1050, take_profit=None)
        except ValidationError:
            raised = True
        check(raised, "LONG stop_loss 1.1050 (> 1.1000) is rejected")
        unchanged = repo.get_by_id(position.position_id)
        check(unchanged.stop_loss is None, "rejected update did not write stop_loss")


# ---------------------------------------------------------------------------
# C -- LONG take-profit valid
# ---------------------------------------------------------------------------
def scenario_c_long_take_profit_valid():
    print("\n[Scenario C] LONG take_profit above average_price is valid")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        position = _open_long(service)

        updated = service.set_stop_loss_take_profit(position.position_id, stop_loss=None, take_profit=1.1050)
        check(updated.take_profit == 1.1050, "LONG take_profit 1.1050 (> 1.1000) is accepted")


# ---------------------------------------------------------------------------
# D -- LONG take-profit invalid below
# ---------------------------------------------------------------------------
def scenario_d_long_take_profit_invalid_below():
    print("\n[Scenario D] LONG take_profit below average_price is rejected")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        position = _open_long(service)

        raised = False
        try:
            service.set_stop_loss_take_profit(position.position_id, stop_loss=None, take_profit=1.0950)
        except ValidationError:
            raised = True
        check(raised, "LONG take_profit 1.0950 (< 1.1000) is rejected")
        unchanged = repo.get_by_id(position.position_id)
        check(unchanged.take_profit is None, "rejected update did not write take_profit")


# ---------------------------------------------------------------------------
# E -- SHORT stop-loss valid
# ---------------------------------------------------------------------------
def scenario_e_short_stop_loss_valid():
    print("\n[Scenario E] SHORT stop_loss above average_price is valid")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        position = _open_short(service)
        check(position.direction == "SHORT", "opened position is SHORT")

        updated = service.set_stop_loss_take_profit(position.position_id, stop_loss=1.1050, take_profit=None)
        check(updated.stop_loss == 1.1050, "SHORT stop_loss 1.1050 (> 1.1000) is accepted")
        check(updated.direction == "SHORT", "direction stays SHORT")


# ---------------------------------------------------------------------------
# F -- SHORT stop-loss invalid below
# ---------------------------------------------------------------------------
def scenario_f_short_stop_loss_invalid_below():
    print("\n[Scenario F] SHORT stop_loss below average_price is rejected")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        position = _open_short(service)

        raised = False
        try:
            service.set_stop_loss_take_profit(position.position_id, stop_loss=1.0950, take_profit=None)
        except ValidationError:
            raised = True
        check(raised, "SHORT stop_loss 1.0950 (< 1.1000) is rejected")
        unchanged = repo.get_by_id(position.position_id)
        check(unchanged.stop_loss is None, "rejected update did not write stop_loss")


# ---------------------------------------------------------------------------
# G -- SHORT take-profit valid
# ---------------------------------------------------------------------------
def scenario_g_short_take_profit_valid():
    print("\n[Scenario G] SHORT take_profit below average_price is valid")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        position = _open_short(service)

        updated = service.set_stop_loss_take_profit(position.position_id, stop_loss=None, take_profit=1.0950)
        check(updated.take_profit == 1.0950, "SHORT take_profit 1.0950 (< 1.1000) is accepted")


# ---------------------------------------------------------------------------
# H -- SHORT take-profit invalid above
# ---------------------------------------------------------------------------
def scenario_h_short_take_profit_invalid_above():
    print("\n[Scenario H] SHORT take_profit above average_price is rejected")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        position = _open_short(service)

        raised = False
        try:
            service.set_stop_loss_take_profit(position.position_id, stop_loss=None, take_profit=1.1050)
        except ValidationError:
            raised = True
        check(raised, "SHORT take_profit 1.1050 (> 1.1000) is rejected")
        unchanged = repo.get_by_id(position.position_id)
        check(unchanged.take_profit is None, "rejected update did not write take_profit")


# ---------------------------------------------------------------------------
# I -- Equal stop-loss rejected, both directions
# ---------------------------------------------------------------------------
def scenario_i_equal_stop_loss_rejected():
    print("\n[Scenario I] stop_loss == average_price is rejected for LONG and SHORT")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)

        long_position = _open_long(service)
        raised = False
        try:
            service.set_stop_loss_take_profit(long_position.position_id, stop_loss=1.1000, take_profit=None)
        except ValidationError:
            raised = True
        check(raised, "LONG stop_loss == average_price is rejected")

        short_position = _open_short(service)
        raised = False
        try:
            service.set_stop_loss_take_profit(short_position.position_id, stop_loss=1.1000, take_profit=None)
        except ValidationError:
            raised = True
        check(raised, "SHORT stop_loss == average_price is rejected")


# ---------------------------------------------------------------------------
# J -- Equal take-profit rejected, both directions
# ---------------------------------------------------------------------------
def scenario_j_equal_take_profit_rejected():
    print("\n[Scenario J] take_profit == average_price is rejected for LONG and SHORT")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)

        long_position = _open_long(service)
        raised = False
        try:
            service.set_stop_loss_take_profit(long_position.position_id, stop_loss=None, take_profit=1.1000)
        except ValidationError:
            raised = True
        check(raised, "LONG take_profit == average_price is rejected")

        short_position = _open_short(service)
        raised = False
        try:
            service.set_stop_loss_take_profit(short_position.position_id, stop_loss=None, take_profit=1.1000)
        except ValidationError:
            raised = True
        check(raised, "SHORT take_profit == average_price is rejected")


# ---------------------------------------------------------------------------
# K -- Persistence
# ---------------------------------------------------------------------------
def scenario_k_persistence():
    print("\n[Scenario K] valid SHORT stop_loss/take_profit round-trip through the repository")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)
        position = _open_short(service)

        service.set_stop_loss_take_profit(position.position_id, stop_loss=1.1050, take_profit=1.0950)

        stored = repo.get_by_id(position.position_id)
        check(stored.direction == "SHORT", "persisted direction is SHORT")
        check(stored.stop_loss == 1.1050, "persisted stop_loss matches")
        check(stored.take_profit == 1.0950, "persisted take_profit matches")


# ---------------------------------------------------------------------------
# L -- Direction remains unchanged
# ---------------------------------------------------------------------------
def scenario_l_direction_unchanged():
    print("\n[Scenario L] set_stop_loss_take_profit() never mutates Position.direction")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)

        long_position = _open_long(service)
        service.set_stop_loss_take_profit(long_position.position_id, stop_loss=1.0950, take_profit=1.1050)
        check(repo.get_by_id(long_position.position_id).direction == "LONG", "LONG direction untouched")

        short_position = _open_short(service)
        service.set_stop_loss_take_profit(short_position.position_id, stop_loss=1.1050, take_profit=1.0950)
        check(repo.get_by_id(short_position.position_id).direction == "SHORT", "SHORT direction untouched")


# ---------------------------------------------------------------------------
# M -- direction-aware proof: mirrored acceptance/rejection
# ---------------------------------------------------------------------------
def scenario_m_direction_aware_proof():
    print("\n[Scenario M] LONG/SHORT stop_loss rules are true mirror images, not blanket acceptance")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo, _ = _build_service(tmp)

        long_below = _open_long(service, tmp_symbol="BBCA1")
        updated = service.set_stop_loss_take_profit(long_below.position_id, stop_loss=1.0950, take_profit=None)
        check(updated.stop_loss == 1.0950, "LONG stop below entry succeeds")

        short_below = _open_short(service, symbol="EURUSD1")
        raised = False
        try:
            service.set_stop_loss_take_profit(short_below.position_id, stop_loss=1.0950, take_profit=None)
        except ValidationError:
            raised = True
        check(raised, "SHORT stop below entry fails")

        short_above = _open_short(service, symbol="EURUSD2")
        updated = service.set_stop_loss_take_profit(short_above.position_id, stop_loss=1.1050, take_profit=None)
        check(updated.stop_loss == 1.1050, "SHORT stop above entry succeeds")

        long_above = _open_long(service, tmp_symbol="BBCA2")
        raised = False
        try:
            service.set_stop_loss_take_profit(long_above.position_id, stop_loss=1.1050, take_profit=None)
        except ValidationError:
            raised = True
        check(raised, "LONG stop above entry fails")


def main() -> int:
    scenario_a_long_stop_loss_valid()
    scenario_b_long_stop_loss_invalid_above()
    scenario_c_long_take_profit_valid()
    scenario_d_long_take_profit_invalid_below()
    scenario_e_short_stop_loss_valid()
    scenario_f_short_stop_loss_invalid_below()
    scenario_g_short_take_profit_valid()
    scenario_h_short_take_profit_invalid_above()
    scenario_i_equal_stop_loss_rejected()
    scenario_j_equal_take_profit_rejected()
    scenario_k_persistence()
    scenario_l_direction_unchanged()
    scenario_m_direction_aware_proof()

    print(f"\n{_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())