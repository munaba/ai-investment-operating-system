"""Standalone regression checks for
``Business.account_balance_service.AccountBalanceService``.

Covers Sprint 4 STEP 7 (cash balance / business layer):

* BUY debits cash by ``quantity * fill_price``, SELL credits it;
* ``equity``/``buying_power`` are read back unchanged -- never
  recomputed by this service;
* insufficient cash on a BUY raises ValidationError and leaves the
  Account completely untouched (no repository write);
* an unknown ``trade.action`` raises ValidationError;
* a ``trade.account_id`` that does not exist raises ValidationError;
* this service never touches Position/Portfolio/Trade tables (no such
  repository reference exists on the instance at all).

Run directly with ``python Tests/test_account_balance_service.py`` --
no external test framework required, matching
``test_execution_service.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.account_balance_service import AccountBalanceService  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.models import Trade  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402

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


def _build_service(tmp_dir: str):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "account_balance_service.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    account_repo.create(
        account_id="paper-id",
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=100_000_000.0,
        equity=120_000_000.0,
        buying_power=100_000_000.0,
    )
    return AccountBalanceService(account_repo), account_repo


def _trade(trade_id=1, order_id=1, account_id="paper-id", action="BUY", quantity=100.0, fill_price=9500.0):
    return Trade(
        trade_id=trade_id,
        order_id=order_id,
        account_id=account_id,
        symbol="BBCA",
        action=action,
        quantity=quantity,
        fill_price=fill_price,
        fee=0.0,
        tax=0.0,
        executed_at="2026-08-01T10:00:00+00:00",
    )


def scenario_buy_debits_cash():
    print("\n[Scenario 1] BUY debits cash by quantity * fill_price")
    with tempfile.TemporaryDirectory() as tmp:
        service, account_repo = _build_service(tmp)
        trade = _trade(action="BUY", quantity=100.0, fill_price=9500.0)

        result = service.apply_trade(trade)

        check(result.cash == 100_000_000.0 - 950_000.0, "cash decreased by exactly trade_value")
        check(result.equity == 120_000_000.0, "equity left unchanged")
        check(result.buying_power == 100_000_000.0, "buying_power left unchanged")

        stored = account_repo.get_by_id("paper-id")
        check(stored.cash == result.cash, "the new cash value was actually persisted")


def scenario_sell_credits_cash():
    print("\n[Scenario 2] SELL credits cash by quantity * fill_price")
    with tempfile.TemporaryDirectory() as tmp:
        service, account_repo = _build_service(tmp)
        trade = _trade(action="SELL", quantity=50.0, fill_price=9600.0)

        result = service.apply_trade(trade)

        check(result.cash == 100_000_000.0 + 480_000.0, "cash increased by exactly trade_value")
        check(result.equity == 120_000_000.0, "equity left unchanged")
        check(result.buying_power == 100_000_000.0, "buying_power left unchanged")


def scenario_insufficient_cash_rejected():
    print("\n[Scenario 3] a BUY exceeding current cash is rejected, no write happens")
    with tempfile.TemporaryDirectory() as tmp:
        service, account_repo = _build_service(tmp)
        trade = _trade(action="BUY", quantity=1_000_000.0, fill_price=9500.0)

        raised = False
        try:
            service.apply_trade(trade)
        except ValidationError:
            raised = True
        check(raised, "apply_trade() raises ValidationError when trade_value exceeds cash")

        unchanged = account_repo.get_by_id("paper-id")
        check(unchanged.cash == 100_000_000.0, "cash is completely untouched after rejection")


def scenario_unknown_action_rejected():
    print("\n[Scenario 4] an unknown trade.action is rejected")
    with tempfile.TemporaryDirectory() as tmp:
        service, account_repo = _build_service(tmp)
        trade = _trade(action="SHORT")

        raised = False
        try:
            service.apply_trade(trade)
        except ValidationError:
            raised = True
        check(raised, "apply_trade() rejects an unrecognized action")

        unchanged = account_repo.get_by_id("paper-id")
        check(unchanged.cash == 100_000_000.0, "cash is untouched after an unknown-action rejection")


def scenario_missing_account_rejected():
    print("\n[Scenario 5] a non-existent trade.account_id is rejected")
    with tempfile.TemporaryDirectory() as tmp:
        service, _ = _build_service(tmp)
        trade = _trade(account_id="does-not-exist")

        raised = False
        try:
            service.apply_trade(trade)
        except ValidationError:
            raised = True
        check(raised, "apply_trade() raises ValidationError for a non-existent account_id")


def scenario_no_position_or_trade_dependency():
    print("\n[Scenario 6] no Position/Trade repository dependency exists on the service")
    with tempfile.TemporaryDirectory() as tmp:
        service, _ = _build_service(tmp)
        attrs = sorted(vars(service).keys())
        check(
            attrs == ["_account_repository"],
            "AccountBalanceService holds exactly one collaborator: _account_repository",
        )


def main() -> int:
    scenario_buy_debits_cash()
    scenario_sell_credits_cash()
    scenario_insufficient_cash_rejected()
    scenario_unknown_action_rejected()
    scenario_missing_account_rejected()
    scenario_no_position_or_trade_dependency()

    print("\n" + "=" * 60)
    print(f"SPRINT 4 STEP 7 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())