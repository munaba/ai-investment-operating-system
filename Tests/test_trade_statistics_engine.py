"""Standalone regression checks for
``Business.trade_statistics_engine.TradeStatisticsEngine``.

Covers Sprint 6 STEP 2 (execution statistics, no profit/loss):

* constructor takes no dependency;
* ``calculate()`` on an empty list returns all-zero numeric fields
  and ``None`` timestamps;
* single BUY / single SELL;
* many BUYs / many SELLs;
* mixed BUY+SELL;
* ``total_volume``/``total_fees``/``total_tax`` sums are correct;
* ``first_trade_time``/``last_trade_time`` follow list order, no
  sorting;
* the return value is a real ``TradeExecutionStatistics`` instance;
* the input list (and its ``Trade`` elements) are never mutated.

Uses hand-built ``Trade`` instances directly -- no database, no
repository, no I/O, matching every other ``Tests/test_*.py`` file in
this project.

Run directly with ``python Tests/test_trade_statistics_engine.py`` --
no external test framework required.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.trade_statistics_engine import (  # noqa: E402
    TradeExecutionStatistics,
    TradeStatisticsEngine,
)
from Database.models import Trade  # noqa: E402

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


def _trade(
    trade_id: int,
    action: str,
    quantity: float,
    fee: float,
    tax: float,
    executed_at: str,
    symbol: str = "BBCA",
) -> Trade:
    return Trade(
        trade_id=trade_id,
        order_id=1,
        account_id="paper-id",
        symbol=symbol,
        action=action,
        quantity=quantity,
        fill_price=9500.0,
        fee=fee,
        tax=tax,
        executed_at=executed_at,
    )


def scenario_constructor_no_dependency():
    print("\n[Scenario 1] constructor takes no dependency")
    engine = TradeStatisticsEngine()
    check(isinstance(engine, TradeStatisticsEngine), "constructs a TradeStatisticsEngine instance")


def scenario_empty_trade_list():
    print("\n[Scenario 2] calculate() on an empty list")
    engine = TradeStatisticsEngine()
    result = engine.calculate([])
    check(isinstance(result, TradeExecutionStatistics), "returns a TradeExecutionStatistics instance")
    check(result.total_trades == 0, "total_trades is 0 for an empty list")
    check(result.buy_trades == 0, "buy_trades is 0 for an empty list")
    check(result.sell_trades == 0, "sell_trades is 0 for an empty list")
    check(result.total_volume == 0, "total_volume is 0 for an empty list")
    check(result.total_fees == 0, "total_fees is 0 for an empty list")
    check(result.total_tax == 0, "total_tax is 0 for an empty list")
    check(result.first_trade_time is None, "first_trade_time is None for an empty list")
    check(result.last_trade_time is None, "last_trade_time is None for an empty list")


def scenario_single_buy():
    print("\n[Scenario 3] a single BUY trade")
    engine = TradeStatisticsEngine()
    trade = _trade(1, "BUY", 100.0, 5.0, 1.0, "2026-08-01T09:00:00+00:00")
    result = engine.calculate([trade])
    check(result.total_trades == 1, "total_trades == 1 for a single trade")
    check(result.buy_trades == 1, "buy_trades == 1 for a single BUY")
    check(result.sell_trades == 0, "sell_trades == 0 when only a BUY is present")
    check(result.first_trade_time == "2026-08-01T09:00:00+00:00", "first_trade_time is the single trade's executed_at")
    check(result.last_trade_time == "2026-08-01T09:00:00+00:00", "last_trade_time is the single trade's executed_at")


def scenario_single_sell():
    print("\n[Scenario 4] a single SELL trade")
    engine = TradeStatisticsEngine()
    trade = _trade(1, "SELL", 50.0, 2.0, 0.5, "2026-08-01T10:00:00+00:00")
    result = engine.calculate([trade])
    check(result.total_trades == 1, "total_trades == 1 for a single trade")
    check(result.sell_trades == 1, "sell_trades == 1 for a single SELL")
    check(result.buy_trades == 0, "buy_trades == 0 when only a SELL is present")


def scenario_many_buys():
    print("\n[Scenario 5] many BUY trades")
    engine = TradeStatisticsEngine()
    trades = [
        _trade(1, "BUY", 100.0, 5.0, 1.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "BUY", 200.0, 10.0, 2.0, "2026-08-01T09:30:00+00:00"),
        _trade(3, "BUY", 50.0, 2.5, 0.5, "2026-08-01T10:00:00+00:00"),
    ]
    result = engine.calculate(trades)
    check(result.total_trades == 3, "total_trades == 3 for three trades")
    check(result.buy_trades == 3, "buy_trades == 3 when all three are BUY")
    check(result.sell_trades == 0, "sell_trades == 0 when none are SELL")


def scenario_many_sells():
    print("\n[Scenario 6] many SELL trades")
    engine = TradeStatisticsEngine()
    trades = [
        _trade(1, "SELL", 100.0, 5.0, 1.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "SELL", 200.0, 10.0, 2.0, "2026-08-01T09:30:00+00:00"),
    ]
    result = engine.calculate(trades)
    check(result.total_trades == 2, "total_trades == 2 for two trades")
    check(result.sell_trades == 2, "sell_trades == 2 when both are SELL")
    check(result.buy_trades == 0, "buy_trades == 0 when none are BUY")


def scenario_mixed_buy_and_sell():
    print("\n[Scenario 7] mixed BUY + SELL trades")
    engine = TradeStatisticsEngine()
    trades = [
        _trade(1, "BUY", 100.0, 5.0, 1.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "SELL", 100.0, 5.0, 1.0, "2026-08-01T09:15:00+00:00"),
        _trade(3, "BUY", 50.0, 2.5, 0.5, "2026-08-01T09:30:00+00:00"),
    ]
    result = engine.calculate(trades)
    check(result.total_trades == 3, "total_trades == 3 for a mixed list")
    check(result.buy_trades == 2, "buy_trades == 2 in a mixed list")
    check(result.sell_trades == 1, "sell_trades == 1 in a mixed list")


def scenario_total_volume_fee_tax_sums():
    print("\n[Scenario 8] total_volume / total_fees / total_tax sums")
    engine = TradeStatisticsEngine()
    trades = [
        _trade(1, "BUY", 100.0, 5.0, 1.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "SELL", 30.0, 2.0, 0.25, "2026-08-01T09:15:00+00:00"),
        _trade(3, "BUY", 70.0, 3.5, 0.75, "2026-08-01T09:30:00+00:00"),
    ]
    result = engine.calculate(trades)
    check(result.total_volume == 200.0, "total_volume is the sum of quantity across all trades")
    check(result.total_fees == 10.5, "total_fees is the sum of fee across all trades")
    check(result.total_tax == 2.0, "total_tax is the sum of tax across all trades")


def scenario_first_and_last_trade_time_follow_list_order():
    print("\n[Scenario 9] first_trade_time / last_trade_time follow list order (no sorting)")
    engine = TradeStatisticsEngine()
    # Deliberately out of chronological order -- engine must NOT sort.
    trades = [
        _trade(1, "SELL", 10.0, 1.0, 0.1, "2026-08-01T12:00:00+00:00"),
        _trade(2, "BUY", 20.0, 2.0, 0.2, "2026-08-01T08:00:00+00:00"),
        _trade(3, "BUY", 30.0, 3.0, 0.3, "2026-08-01T15:00:00+00:00"),
    ]
    result = engine.calculate(trades)
    check(
        result.first_trade_time == "2026-08-01T12:00:00+00:00",
        "first_trade_time is the first element's executed_at, not the chronologically earliest",
    )
    check(
        result.last_trade_time == "2026-08-01T15:00:00+00:00",
        "last_trade_time is the last element's executed_at, not chronologically sorted",
    )


def scenario_output_is_dataclass_instance():
    print("\n[Scenario 10] output dataclass shape")
    engine = TradeStatisticsEngine()
    result = engine.calculate([])
    check(hasattr(result, "total_trades"), "result has total_trades")
    check(hasattr(result, "buy_trades"), "result has buy_trades")
    check(hasattr(result, "sell_trades"), "result has sell_trades")
    check(hasattr(result, "total_volume"), "result has total_volume")
    check(hasattr(result, "total_fees"), "result has total_fees")
    check(hasattr(result, "total_tax"), "result has total_tax")
    check(hasattr(result, "first_trade_time"), "result has first_trade_time")
    check(hasattr(result, "last_trade_time"), "result has last_trade_time")
    fields = {f for f in vars(result).keys()}
    check(
        fields == {
            "total_trades", "buy_trades", "sell_trades", "total_volume",
            "total_fees", "total_tax", "first_trade_time", "last_trade_time",
        },
        "TradeExecutionStatistics has exactly the eight LOCKED fields, no more",
    )


def scenario_input_not_mutated():
    print("\n[Scenario 11] input list and its Trade elements are never mutated")
    engine = TradeStatisticsEngine()
    trades = [
        _trade(1, "BUY", 100.0, 5.0, 1.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "SELL", 50.0, 2.0, 0.5, "2026-08-01T09:15:00+00:00"),
    ]
    trades_before = copy.deepcopy(trades)
    engine.calculate(trades)
    check(trades == trades_before, "the input list of Trade instances is unchanged after calculate()")
    check(len(trades) == 2, "calculate() does not add or remove elements from the input list")


def scenario_no_public_method_other_than_calculate():
    print("\n[Scenario 12] TradeStatisticsEngine exposes only calculate() publicly")
    public_methods = {name for name in dir(TradeStatisticsEngine) if not name.startswith("_")}
    check(public_methods == {"calculate"}, "TradeStatisticsEngine's public API is exactly {'calculate'}")


def main() -> int:
    scenario_constructor_no_dependency()
    scenario_empty_trade_list()
    scenario_single_buy()
    scenario_single_sell()
    scenario_many_buys()
    scenario_many_sells()
    scenario_mixed_buy_and_sell()
    scenario_total_volume_fee_tax_sums()
    scenario_first_and_last_trade_time_follow_list_order()
    scenario_output_is_dataclass_instance()
    scenario_input_not_mutated()
    scenario_no_public_method_other_than_calculate()

    print("\n" + "=" * 60)
    print(f"TRADE STATISTICS ENGINE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())