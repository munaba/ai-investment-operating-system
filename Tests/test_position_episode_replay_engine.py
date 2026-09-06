"""Standalone regression checks for
``Business.position_episode_replay_engine.PositionEpisodeReplayEngine``.

Covers ACTIVATION 7 (performance per strategy) episode replay:

* constructor requires a ``TradeHoldingPeriodEngine`` collaborator;
* ``replay()`` on an empty list returns an empty list;
* a single BUY with no closing SELL -> one still-open episode
  (``closed=False``), never fabricated as closed;
* BUY -> full SELL -> exactly one closed episode, ``opening_trade`` is
  the BUY, ``trades`` holds both;
* BUY -> partial SELL -> full SELL -> one closed episode containing
  all three trades, ``opening_trade`` is the first BUY;
* BUY -> full SELL -> reopen (new BUY) -> two independent episodes:
  the first closed, the second open;
* multiple full BUY/SELL cycles -> multiple independent closed
  episodes, each with its own correct ``opening_trade``;
* an unknown action (neither BUY nor SELL) is skipped entirely --
  belongs to no episode;
* the input list (and its ``Trade`` elements) are never mutated;
* deterministic: replaying the same input twice yields equal results.

Uses hand-built ``Trade`` instances directly plus a real
``TradeHoldingPeriodEngine`` -- no database, no repository, no I/O,
matching ``Tests/test_trade_holding_period_engine.py``.

Run directly with ``python Tests/test_position_episode_replay_engine.py``
-- no external test framework required.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.position_episode_replay_engine import (  # noqa: E402
    PositionEpisodeReplayEngine,
)
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


def _trade(trade_id, order_id, action, quantity, executed_at, symbol="BBCA", account_id="paper"):
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


def _engine() -> PositionEpisodeReplayEngine:
    return PositionEpisodeReplayEngine(TradeHoldingPeriodEngine())


def scenario_empty_list_returns_empty_list():
    print("\n[Scenario 1] replay() on an empty list returns an empty list")
    result = _engine().replay([])
    check(result == [], "empty trades -> empty episode list")


def scenario_single_open_buy_is_one_open_episode():
    print("\n[Scenario 2] a single BUY with no closing SELL -> one still-open episode")
    buy = _trade(1, 100, "BUY", 100.0, "2026-08-01T09:00:00+00:00")
    result = _engine().replay([buy])
    check(len(result) == 1, "exactly one episode")
    check(result[0].closed is False, "episode is open, never fabricated as closed")
    check(result[0].opening_trade.trade_id == 1, "opening_trade is the BUY")
    check([t.trade_id for t in result[0].trades] == [1], "episode holds the BUY")


def scenario_buy_full_sell_is_one_closed_episode():
    print("\n[Scenario 3] BUY -> full SELL -> one closed episode")
    buy = _trade(1, 100, "BUY", 100.0, "2026-08-01T09:00:00+00:00")
    sell = _trade(2, 101, "SELL", 100.0, "2026-08-01T13:00:00+00:00")
    result = _engine().replay([buy, sell])
    check(len(result) == 1, "exactly one episode")
    check(result[0].closed is True, "episode is closed")
    check(result[0].opening_trade.trade_id == 1, "opening_trade is the BUY")
    check([t.trade_id for t in result[0].trades] == [1, 2], "episode holds BUY then SELL")


def scenario_partial_then_full_sell_single_episode():
    print("\n[Scenario 4] BUY -> partial SELL -> full SELL -> one closed episode with all three trades")
    buy = _trade(1, 100, "BUY", 100.0, "2026-08-01T09:00:00+00:00")
    partial = _trade(2, 101, "SELL", 40.0, "2026-08-01T10:00:00+00:00")
    close = _trade(3, 102, "SELL", 60.0, "2026-08-01T13:00:00+00:00")
    result = _engine().replay([buy, partial, close])
    check(len(result) == 1, "exactly one episode")
    check(result[0].closed is True, "episode is closed")
    check(result[0].opening_trade.trade_id == 1, "opening_trade is the first BUY")
    check(
        [t.trade_id for t in result[0].trades] == [1, 2, 3],
        "episode holds opening BUY, partial SELL, and closing SELL",
    )


def scenario_reopen_produces_two_independent_episodes():
    print("\n[Scenario 5] BUY -> full SELL -> reopen BUY -> two independent episodes")
    buy1 = _trade(1, 100, "BUY", 100.0, "2026-08-01T09:00:00+00:00")
    sell1 = _trade(2, 101, "SELL", 100.0, "2026-08-01T13:00:00+00:00")
    buy2 = _trade(3, 102, "BUY", 30.0, "2026-08-01T15:00:00+00:00")
    result = _engine().replay([buy1, sell1, buy2])
    check(len(result) == 2, "exactly two episodes")
    check(result[0].closed is True, "first episode is closed")
    check(result[0].opening_trade.trade_id == 1, "first episode opened by buy1")
    check([t.trade_id for t in result[0].trades] == [1, 2], "first episode holds buy1+sell1")
    check(result[1].closed is False, "second episode is still open")
    check(result[1].opening_trade.trade_id == 3, "second episode opened by buy2")
    check([t.trade_id for t in result[1].trades] == [3], "second episode holds only buy2")


def scenario_multiple_closed_episodes():
    print("\n[Scenario 6] multiple full BUY/SELL cycles -> multiple independent closed episodes")
    buy1 = _trade(1, 100, "BUY", 100.0, "2026-08-01T09:00:00+00:00")
    sell1 = _trade(2, 101, "SELL", 100.0, "2026-08-01T10:00:00+00:00")
    buy2 = _trade(3, 102, "BUY", 50.0, "2026-08-01T11:00:00+00:00")
    sell2 = _trade(4, 103, "SELL", 50.0, "2026-08-01T12:00:00+00:00")
    buy3 = _trade(5, 104, "BUY", 20.0, "2026-08-01T13:00:00+00:00")
    sell3 = _trade(6, 105, "SELL", 20.0, "2026-08-01T14:00:00+00:00")
    result = _engine().replay([buy1, sell1, buy2, sell2, buy3, sell3])
    check(len(result) == 3, "exactly three closed episodes")
    check(all(episode.closed for episode in result), "every episode is closed")
    check(
        [episode.opening_trade.trade_id for episode in result] == [1, 3, 5],
        "each episode's opening_trade is its own first BUY, in order",
    )
    check(
        [[t.trade_id for t in episode.trades] for episode in result]
        == [[1, 2], [3, 4], [5, 6]],
        "each episode's trades are scoped to its own BUY/SELL pair",
    )


def scenario_unknown_action_skipped_entirely():
    print("\n[Scenario 7] an unknown action belongs to no episode")
    buy = _trade(1, 100, "BUY", 100.0, "2026-08-01T09:00:00+00:00")
    weird = _trade(2, 101, "DIVIDEND", 0.0, "2026-08-01T09:30:00+00:00")
    sell = _trade(3, 102, "SELL", 100.0, "2026-08-01T13:00:00+00:00")
    result = _engine().replay([buy, weird, sell])
    check(len(result) == 1, "exactly one episode")
    check(
        [t.trade_id for t in result[0].trades] == [1, 3],
        "the unknown-action trade is skipped, never counted in the episode",
    )


def scenario_no_mutation_of_input():
    print("\n[Scenario 8] input trades list and elements are never mutated")
    buy = _trade(1, 100, "BUY", 100.0, "2026-08-01T09:00:00+00:00")
    sell = _trade(2, 101, "SELL", 100.0, "2026-08-01T13:00:00+00:00")
    trades = [buy, sell]
    before = copy.deepcopy(trades)
    _engine().replay(trades)
    check(trades == before, "trades list and elements are byte-for-byte unchanged after replay()")


def scenario_deterministic_replay():
    print("\n[Scenario 9] replaying the same input twice yields equal results")
    buy = _trade(1, 100, "BUY", 100.0, "2026-08-01T09:00:00+00:00")
    sell = _trade(2, 101, "SELL", 100.0, "2026-08-01T13:00:00+00:00")
    trades = [buy, sell]
    engine = _engine()
    first = engine.replay(trades)
    second = engine.replay(trades)
    check(
        [(e.closed, e.opening_trade.trade_id, [t.trade_id for t in e.trades]) for e in first]
        == [(e.closed, e.opening_trade.trade_id, [t.trade_id for t in e.trades]) for e in second],
        "replay() is a pure function -- same input always produces the same episodes",
    )


def main() -> int:
    scenario_empty_list_returns_empty_list()
    scenario_single_open_buy_is_one_open_episode()
    scenario_buy_full_sell_is_one_closed_episode()
    scenario_partial_then_full_sell_single_episode()
    scenario_reopen_produces_two_independent_episodes()
    scenario_multiple_closed_episodes()
    scenario_unknown_action_skipped_entirely()
    scenario_no_mutation_of_input()
    scenario_deterministic_replay()

    print(f"\n{'=' * 70}\nRESULTS: {_PASS} passed, {_FAIL} failed\n{'=' * 70}")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())