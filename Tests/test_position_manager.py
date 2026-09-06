"""Standalone regression checks for
``Business.position_manager.PositionManager``.

Covers Sprint 4 STEP 8 (position lifecycle / business layer):

* first BUY creates a new OPEN Position;
* a second BUY merges into the existing OPEN position using a
  quantity-weighted average price;
* SELL partial reduces quantity, leaves average_price untouched,
  status stays "open", realized_pnl accumulates using the OLD
  average_price (Activation 3.6 STEP 3);
* SELL full drives quantity to zero, flips status to "closed", and
  finalizes realized_pnl the same way;
* SELL with no OPEN position raises ValidationError;
* SELL for more than currently held raises ValidationError, no write;
* a BUY after the prior position CLOSED creates a brand-new Position
  (never merges into the closed one);
* an unknown trade.action raises ValidationError;
* this service never touches Account/Trade/Order tables (no such
  repository reference exists on the instance at all).

Run directly with ``python Tests/test_position_manager.py`` -- no
external test framework required, matching
``test_account_balance_service.py``.
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


def _build_service(tmp_dir: str):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "position_manager.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
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
    return PositionManager(position_repo), position_repo


def _trade(trade_id=1, order_id=1, account_id="paper-id", symbol="BBCA",
           action="BUY", quantity=100.0, fill_price=9500.0):
    return Trade(
        trade_id=trade_id,
        order_id=order_id,
        account_id=account_id,
        symbol=symbol,
        action=action,
        quantity=quantity,
        fill_price=fill_price,
        fee=0.0,
        tax=0.0,
        executed_at="2026-08-01T10:00:00+00:00",
    )


def scenario_first_buy_creates_position():
    print("\n[Scenario 1] first BUY creates a new OPEN Position")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)
        trade = _trade(action="BUY", quantity=100.0, fill_price=9500.0)

        position = service.apply_trade(trade)

        check(position.position_id is not None, "apply_trade() returns a Position with a position_id")
        check(position.quantity == 100.0, "quantity == trade.quantity")
        check(position.average_price == 9500.0, "average_price == trade.fill_price")
        check(position.realized_pnl == 0.0, "realized_pnl is the LOCKED 0.0 placeholder on a fresh position")
        check(position.status == "open", "status is 'open'")

        stored = repo.get_open_position("paper-id", "BBCA")
        check(stored is not None and stored.position_id == position.position_id, "persisted as the OPEN position")


def scenario_second_buy_merges_weighted_average():
    print("\n[Scenario 2] second BUY merges into the OPEN position, weighted average")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)
        service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0))

        result = service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9700.0))

        expected_avg = (100.0 * 9500.0 + 100.0 * 9700.0) / 200.0
        check(result.quantity == 200.0, "quantity is the sum of both BUYs")
        check(result.average_price == expected_avg, "average_price is the correct quantity-weighted average")
        check(result.status == "open", "status stays 'open' after a merge")

        all_positions = repo.list_by_account("paper-id")
        check(len(all_positions) == 1, "merge does not create a second Position row")


def scenario_sell_partial_reduces_quantity():
    print("\n[Scenario 3] SELL partial reduces quantity, leaves average_price untouched")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)
        service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0))

        result = service.apply_trade(_trade(action="SELL", quantity=40.0, fill_price=9800.0))

        check(result.quantity == 60.0, "quantity decreased by exactly the SELL quantity")
        check(result.average_price == 9500.0, "average_price is untouched by a SELL")
        check(result.status == "open", "status stays 'open' after a partial SELL")
        expected_pnl = (9800.0 - 9500.0) * 40.0
        check(
            result.realized_pnl == expected_pnl,
            "realized_pnl (Activation 3.6 STEP 3) == (fill_price - OLD average_price) * sell_quantity",
        )


def scenario_sell_full_closes_position():
    print("\n[Scenario 4] SELL full drives quantity to zero and closes the Position")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)
        service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0))

        result = service.apply_trade(_trade(action="SELL", quantity=100.0, fill_price=9800.0))

        check(result.quantity == 0.0, "quantity is zero after a full SELL")
        check(result.status == "closed", "status becomes 'closed'")
        expected_pnl = (9800.0 - 9500.0) * 100.0
        check(
            result.realized_pnl == expected_pnl,
            "realized_pnl (Activation 3.6 STEP 3) == (fill_price - OLD average_price) * sell_quantity",
        )

        still_open = repo.get_open_position("paper-id", "BBCA")
        check(still_open is None, "no OPEN position remains for this account+symbol")


def scenario_sell_partial_then_partial_accumulates_realized_pnl():
    print("\n[Scenario 4b] two successive partial SELLs accumulate realized_pnl, average_price never moves")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)
        service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0))

        first = service.apply_trade(_trade(action="SELL", quantity=30.0, fill_price=9800.0))
        expected_first_pnl = (9800.0 - 9500.0) * 30.0
        check(first.quantity == 70.0, "first partial SELL leaves 70.0 remaining")
        check(first.average_price == 9500.0, "average_price still untouched after first partial SELL")
        check(first.realized_pnl == expected_first_pnl, "realized_pnl after first partial SELL")

        second = service.apply_trade(_trade(action="SELL", quantity=20.0, fill_price=9400.0))
        expected_second_delta = (9400.0 - 9500.0) * 20.0
        expected_total_pnl = expected_first_pnl + expected_second_delta
        check(second.quantity == 50.0, "second partial SELL leaves 50.0 remaining")
        check(second.average_price == 9500.0, "average_price still untouched after second partial SELL")
        check(
            second.realized_pnl == expected_total_pnl,
            "realized_pnl accumulates across successive SELLs (uses OLD average_price each time, "
            "including a losing SELL below average_price)",
        )
        check(second.status == "open", "status stays 'open' -- still 50.0 remaining")


def scenario_sell_without_position_rejected():
    print("\n[Scenario 5] SELL with no OPEN position raises ValidationError")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)

        raised = False
        try:
            service.apply_trade(_trade(action="SELL", quantity=10.0, fill_price=9500.0))
        except ValidationError:
            raised = True
        check(raised, "apply_trade() raises ValidationError selling with no OPEN position")

        check(repo.list_by_account("paper-id") == [], "no Position row was created by the rejected SELL")


def scenario_oversell_rejected():
    print("\n[Scenario 6] SELL for more than currently held raises ValidationError, no write")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)
        service.apply_trade(_trade(action="BUY", quantity=50.0, fill_price=9500.0))

        raised = False
        try:
            service.apply_trade(_trade(action="SELL", quantity=100.0, fill_price=9500.0))
        except ValidationError:
            raised = True
        check(raised, "apply_trade() raises ValidationError when SELL exceeds held quantity")

        unchanged = repo.get_open_position("paper-id", "BBCA")
        check(unchanged.quantity == 50.0, "position quantity is completely untouched after rejection")


def scenario_buy_after_closed_creates_new_position():
    print("\n[Scenario 7] BUY on a CLOSED position creates a new Position (never merges into it)")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)
        service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0))
        closed = service.apply_trade(_trade(action="SELL", quantity=100.0, fill_price=9800.0))
        check(closed.status == "closed", "setup: position is now CLOSED")

        reopened = service.apply_trade(_trade(action="BUY", quantity=50.0, fill_price=10_000.0))

        check(reopened.position_id != closed.position_id, "a brand-new Position row was created")
        check(reopened.quantity == 50.0, "new position's quantity is just the new BUY's quantity")
        check(reopened.average_price == 10_000.0, "new position's average_price is just the new BUY's fill_price")
        check(reopened.status == "open", "new position's status is 'open'")

        all_positions = repo.list_by_account("paper-id")
        check(len(all_positions) == 2, "the CLOSED position and the new OPEN position both exist")


def scenario_unknown_action_rejected():
    print("\n[Scenario 8] an unknown trade.action is rejected")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)

        raised = False
        try:
            service.apply_trade(_trade(action="SHORT"))
        except ValidationError:
            raised = True
        check(raised, "apply_trade() rejects an unrecognized action")

        check(repo.list_by_account("paper-id") == [], "no Position row was created for an unknown action")


def scenario_new_position_has_no_stop_loss_take_profit():
    print("\n[Scenario 10] a brand-new Position (first BUY) has no stop_loss/take_profit configured")
    with tempfile.TemporaryDirectory() as tmp:
        service, _ = _build_service(tmp)
        position = service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0))
        check(position.stop_loss is None, "fresh Position's stop_loss is None")
        check(position.take_profit is None, "fresh Position's take_profit is None")


def scenario_set_stop_loss_take_profit_persists():
    print("\n[Scenario 11] set_stop_loss_take_profit() persists valid LONG levels")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)
        position = service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0))

        updated = service.set_stop_loss_take_profit(position.position_id, stop_loss=9000.0, take_profit=10000.0)

        check(updated.stop_loss == 9000.0, "stop_loss is persisted")
        check(updated.take_profit == 10000.0, "take_profit is persisted")
        check(updated.quantity == 100.0, "quantity is untouched by set_stop_loss_take_profit()")
        check(updated.average_price == 9500.0, "average_price is untouched by set_stop_loss_take_profit()")
        check(updated.realized_pnl == 0.0, "realized_pnl is untouched by set_stop_loss_take_profit()")
        check(updated.status == "open", "status is untouched by set_stop_loss_take_profit()")

        stored = repo.get_by_id(position.position_id)
        check(stored.stop_loss == 9000.0, "stop_loss is actually persisted to the repository")
        check(stored.take_profit == 10000.0, "take_profit is actually persisted to the repository")


def scenario_set_stop_loss_take_profit_allows_null():
    print("\n[Scenario 12] set_stop_loss_take_profit(None, None) is valid and stores NULL")
    with tempfile.TemporaryDirectory() as tmp:
        service, _ = _build_service(tmp)
        position = service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0))

        updated = service.set_stop_loss_take_profit(position.position_id, stop_loss=None, take_profit=None)

        check(updated.stop_loss is None, "stop_loss stays None when explicitly passed as None")
        check(updated.take_profit is None, "take_profit stays None when explicitly passed as None")


def scenario_set_stop_loss_take_profit_rejects_invalid_long_levels():
    print("\n[Scenario 13] set_stop_loss_take_profit() rejects invalid LONG levels, no write happens")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)
        position = service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0))

        raised = False
        try:
            service.set_stop_loss_take_profit(position.position_id, stop_loss=9500.0, take_profit=None)
        except ValidationError:
            raised = True
        check(raised, "stop_loss >= average_price is rejected")
        unchanged = repo.get_by_id(position.position_id)
        check(unchanged.stop_loss is None, "rejected stop_loss update did not change the Position")

        raised = False
        try:
            service.set_stop_loss_take_profit(position.position_id, stop_loss=None, take_profit=9500.0)
        except ValidationError:
            raised = True
        check(raised, "take_profit <= average_price is rejected")
        unchanged = repo.get_by_id(position.position_id)
        check(unchanged.take_profit is None, "rejected take_profit update did not change the Position")

        raised = False
        try:
            service.set_stop_loss_take_profit(999999, stop_loss=9000.0, take_profit=10000.0)
        except ValidationError:
            raised = True
        check(raised, "set_stop_loss_take_profit() on a non-existent position_id raises ValidationError")


def scenario_buy_merge_preserves_stop_loss_take_profit():
    print("\n[Scenario 14] a BUY merge preserves the existing stop_loss/take_profit unchanged")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)
        position = service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0))
        service.set_stop_loss_take_profit(position.position_id, stop_loss=9000.0, take_profit=10000.0)

        merged = service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9700.0))

        check(merged.quantity == 200.0, "merge still sums quantity correctly")
        check(merged.stop_loss == 9000.0, "stop_loss is preserved unchanged across a BUY merge")
        check(merged.take_profit == 10000.0, "take_profit is preserved unchanged across a BUY merge")


def scenario_sell_preserves_stop_loss_take_profit():
    print("\n[Scenario 15] a partial SELL preserves the existing stop_loss/take_profit unchanged")
    with tempfile.TemporaryDirectory() as tmp:
        service, repo = _build_service(tmp)
        position = service.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0))
        service.set_stop_loss_take_profit(position.position_id, stop_loss=9000.0, take_profit=10000.0)

        result = service.apply_trade(_trade(action="SELL", quantity=40.0, fill_price=9800.0))

        check(result.quantity == 60.0, "partial SELL still reduces quantity correctly")
        check(result.stop_loss == 9000.0, "stop_loss is preserved unchanged across a partial SELL")
        check(result.take_profit == 10000.0, "take_profit is preserved unchanged across a partial SELL")


def scenario_no_account_or_trade_dependency():
    print("\n[Scenario 9] no Trade/Order repository dependency exists on the service "
          "(Activation 11.12: an OPTIONAL account_repository collaborator was added, "
          "defaulting to None -- see test_activation11_12_forex_short_position_manager.py)")
    with tempfile.TemporaryDirectory() as tmp:
        service, _ = _build_service(tmp)
        attrs = sorted(vars(service).keys())
        check(
            attrs == ["_account_repository", "_position_repository"],
            "PositionManager holds exactly two collaborators: "
            "_position_repository and (Activation 11.12, optional) _account_repository",
        )
        check(
            service._account_repository is None,
            "_account_repository defaults to None when the constructor is not given one "
            "(this test's _build_service() only ever passes position_repo, matching every "
            "pre-11.12 call site) -- preserves pre-11.12 behavior byte-for-byte",
        )


def main() -> int:
    scenario_first_buy_creates_position()
    scenario_second_buy_merges_weighted_average()
    scenario_sell_partial_reduces_quantity()
    scenario_sell_full_closes_position()
    scenario_sell_partial_then_partial_accumulates_realized_pnl()
    scenario_sell_without_position_rejected()
    scenario_oversell_rejected()
    scenario_buy_after_closed_creates_new_position()
    scenario_unknown_action_rejected()
    scenario_new_position_has_no_stop_loss_take_profit()
    scenario_set_stop_loss_take_profit_persists()
    scenario_set_stop_loss_take_profit_allows_null()
    scenario_set_stop_loss_take_profit_rejects_invalid_long_levels()
    scenario_buy_merge_preserves_stop_loss_take_profit()
    scenario_sell_preserves_stop_loss_take_profit()
    scenario_no_account_or_trade_dependency()

    print("\n" + "=" * 60)
    print(f"SPRINT 4 STEP 8 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())