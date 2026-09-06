"""Standalone regression checks for
``Business.trade_holding_period_engine.TradeHoldingPeriodEngine``.

Covers Activation 5.6 (Strategy Attribution) holding-period episode
reconstruction:

* constructor takes no dependency;
* ``calculate()`` on an empty list returns an empty dict;
* a single BUY with no closing SELL -> ``None`` (open episode, never
  fabricated as 0.0);
* BUY -> full SELL -> holding_period_seconds is the exact
  ``(sell.executed_at - buy.executed_at).total_seconds()``, assigned
  to BOTH trades;
* BUY -> partial SELL -> full SELL -> every trade in the episode
  (opening BUY, partial SELL, closing SELL) gets the SAME
  holding_period_seconds, computed from opening BUY to the CLOSING
  (quantity==0) SELL only;
* an additional BUY while quantity is already open does NOT reset the
  episode's entry time;
* BUY -> full SELL -> reopen (new BUY) -> the reopened episode gets
  its own independent holding period, and the first (closed) episode
  is unaffected;
* an unknown action (neither BUY nor SELL) maps to ``None`` and does
  not disturb episode bookkeeping;
* the input list (and its ``Trade`` elements) are never mutated;
* the return value is a plain ``dict``, keyed by every ``trade_id`` in
  the input, no extras.

Uses hand-built ``Trade`` instances directly -- no database, no
repository, no I/O, matching ``test_trade_statistics_engine.py``.

Run directly with ``python Tests/test_trade_holding_period_engine.py``
-- no external test framework required.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.trade_holding_period_engine import TradeHoldingPeriodEngine  # noqa: E402
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


def _trade(trade_id: int, action: str, quantity: float, executed_at: str,
           order_id: int = 1, account_id: str = "paper", symbol: str = "BBCA") -> Trade:
    return Trade(
        trade_id=trade_id,
        order_id=order_id,
        account_id=account_id,
        symbol=symbol,
        action=action,
        quantity=quantity,
        fill_price=9000.0,
        fee=0.0,
        tax=0.0,
        executed_at=executed_at,
    )


def scenario_constructor_no_dependency():
    print("\n[Scenario 1] constructor takes no dependency")
    engine = TradeHoldingPeriodEngine()
    check(engine is not None, "TradeHoldingPeriodEngine() constructs with zero arguments")


def scenario_empty_trade_list():
    print("\n[Scenario 2] calculate([]) returns an empty dict")
    result = TradeHoldingPeriodEngine().calculate([])
    check(result == {}, "empty input produces an empty dict, not None or an error")


def scenario_single_open_buy_is_none():
    print("\n[Scenario 3] a single BUY with no closing SELL -> None (never fabricated)")
    trades = [_trade(1, "BUY", 100.0, "2026-08-01T09:00:00+00:00")]
    result = TradeHoldingPeriodEngine().calculate(trades)
    check(result == {1: None}, "an open episode's holding period is None, never 0.0")


def scenario_buy_then_full_sell():
    print("\n[Scenario 4] BUY -> full SELL -> exact holding_period_seconds on both trades")
    trades = [
        _trade(1, "BUY", 100.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "SELL", 100.0, "2026-08-01T11:30:00+00:00"),
    ]
    result = TradeHoldingPeriodEngine().calculate(trades)
    expected_seconds = 2.5 * 3600
    check(result[1] == expected_seconds, f"opening BUY gets the full episode holding period ({expected_seconds}s)")
    check(result[2] == expected_seconds, f"closing SELL gets the SAME episode holding period ({expected_seconds}s)")


def scenario_partial_then_full_sell_shares_holding_period():
    print("\n[Scenario 5] BUY -> partial SELL -> full SELL -> every trade shares ONE holding period")
    trades = [
        _trade(1, "BUY", 100.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "SELL", 40.0, "2026-08-01T10:00:00+00:00"),
        _trade(3, "SELL", 60.0, "2026-08-01T13:00:00+00:00"),
    ]
    result = TradeHoldingPeriodEngine().calculate(trades)
    expected_seconds = 4.0 * 3600  # opening BUY (09:00) -> CLOSING sell (13:00), never the partial
    check(result[1] == expected_seconds, "opening BUY gets the closing-SELL-anchored holding period")
    check(result[2] == expected_seconds, "the partial (non-closing) SELL retroactively gets the same episode holding period once the episode closes")
    check(result[3] == expected_seconds, "the closing SELL gets the same episode holding period")


def scenario_additional_buy_does_not_reset_entry_time():
    print("\n[Scenario 6] an additional BUY while open does NOT reset the episode's entry time")
    trades = [
        _trade(1, "BUY", 100.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "BUY", 50.0, "2026-08-01T10:00:00+00:00"),
        _trade(3, "SELL", 150.0, "2026-08-01T12:00:00+00:00"),
    ]
    result = TradeHoldingPeriodEngine().calculate(trades)
    expected_seconds = 3.0 * 3600  # anchored to the FIRST buy (09:00), not the second (10:00)
    check(result[1] == expected_seconds, "first BUY anchors episode start")
    check(result[2] == expected_seconds, "second (additional) BUY shares the same episode holding period, entry time not reset")
    check(result[3] == expected_seconds, "closing SELL shares the same episode holding period")


def scenario_reopen_after_close_is_independent():
    print("\n[Scenario 7] BUY -> full SELL -> reopen (new BUY) -> independent episodes")
    trades = [
        _trade(1, "BUY", 100.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "SELL", 100.0, "2026-08-01T10:00:00+00:00"),  # episode 1 closes: 1h
        _trade(3, "BUY", 50.0, "2026-08-01T14:00:00+00:00"),    # episode 2 opens fresh
        _trade(4, "SELL", 50.0, "2026-08-01T15:30:00+00:00"),   # episode 2 closes: 1.5h
    ]
    result = TradeHoldingPeriodEngine().calculate(trades)
    check(result[1] == 3600.0, "episode 1's opening BUY holding period is exactly 1h")
    check(result[2] == 3600.0, "episode 1's closing SELL holding period is exactly 1h")
    check(result[3] == 5400.0, "reopened episode 2's opening BUY has its OWN independent holding period (1.5h)")
    check(result[4] == 5400.0, "reopened episode 2's closing SELL has the same 1.5h, unaffected by episode 1")


def scenario_still_open_episode_after_a_closed_one_is_none():
    print("\n[Scenario 8] a still-open episode after an earlier closed one stays None")
    trades = [
        _trade(1, "BUY", 100.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "SELL", 100.0, "2026-08-01T10:00:00+00:00"),
        _trade(3, "BUY", 50.0, "2026-08-01T14:00:00+00:00"),
    ]
    result = TradeHoldingPeriodEngine().calculate(trades)
    check(result[1] == 3600.0 and result[2] == 3600.0, "the closed first episode still has its real holding period")
    check(result[3] is None, "the reopened, still-open second episode is None -- never fabricated")


def scenario_unknown_action_maps_to_none():
    print("\n[Scenario 9] an unknown action (neither BUY nor SELL) maps to None and doesn't disturb bookkeeping")
    trades = [
        _trade(1, "BUY", 100.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "DIVIDEND", 0.0, "2026-08-01T09:30:00+00:00"),
        _trade(3, "SELL", 100.0, "2026-08-01T10:00:00+00:00"),
    ]
    result = TradeHoldingPeriodEngine().calculate(trades)
    check(result[2] is None, "the unknown-action trade itself is None")
    check(result[1] == 3600.0 and result[3] == 3600.0, "the surrounding BUY/SELL episode still resolves correctly, unaffected by the unknown-action trade in between")


def scenario_input_not_mutated():
    print("\n[Scenario 10] input list and Trade elements are never mutated")
    trades = [
        _trade(1, "BUY", 100.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "SELL", 100.0, "2026-08-01T10:00:00+00:00"),
    ]
    before = copy.deepcopy(trades)
    TradeHoldingPeriodEngine().calculate(trades)
    check(trades == before, "calculate() does not mutate the input trades list or its elements")


def scenario_return_type_and_keys():
    print("\n[Scenario 11] return value is a plain dict keyed by every trade_id, no extras")
    trades = [
        _trade(1, "BUY", 100.0, "2026-08-01T09:00:00+00:00"),
        _trade(2, "SELL", 100.0, "2026-08-01T10:00:00+00:00"),
    ]
    result = TradeHoldingPeriodEngine().calculate(trades)
    check(isinstance(result, dict), "calculate() returns a plain dict")
    check(set(result.keys()) == {1, 2}, "result is keyed by exactly every trade_id present in the input, no extras")


def scenario_public_api_is_exactly_calculate():
    print("\n[Scenario 12] public API is exactly {'calculate'}")
    public_methods = {name for name in dir(TradeHoldingPeriodEngine) if not name.startswith("_")}
    check(public_methods == {"calculate"}, "TradeHoldingPeriodEngine's public API is exactly {'calculate'}")


def main() -> int:
    scenario_constructor_no_dependency()
    scenario_empty_trade_list()
    scenario_single_open_buy_is_none()
    scenario_buy_then_full_sell()
    scenario_partial_then_full_sell_shares_holding_period()
    scenario_additional_buy_does_not_reset_entry_time()
    scenario_reopen_after_close_is_independent()
    scenario_still_open_episode_after_a_closed_one_is_none()
    scenario_unknown_action_maps_to_none()
    scenario_input_not_mutated()
    scenario_return_type_and_keys()
    scenario_public_api_is_exactly_calculate()

    print("\n" + "=" * 60)
    print(f"TRADE HOLDING PERIOD ENGINE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())