"""Standalone regression checks for
``Business.strategy_performance_engine.StrategyPerformanceEngine``.

Covers ACTIVATION 7 (performance per strategy) pure aggregation:

* constructor takes no dependency;
* ``calculate()`` on an empty list returns an empty dict;
* a single strategy's episodes aggregate into one
  ``StrategyPerformanceStatistics`` row with correct win/loss/
  breakeven counts and gross/net/average fields;
* multiple distinct strategy labels each get their own independent
  row -- no cross-contamination;
* ``"mixed"`` is treated as just another ordinary strategy label (the
  service layer decides when to use it -- this engine only groups by
  whatever label it is given);
* zero-pnl episodes count as breakeven, never winning/losing;
* ``average_win``/``average_loss`` are ``0.0`` (never a
  ZeroDivisionError) when there are no winners/losers for that
  strategy;
* the input list is never mutated;
* deterministic: calculating the same input twice yields equal
  results.

Uses hand-built ``EpisodeStrategyOutcome`` instances directly -- no
database, no repository, no I/O, matching
``Tests/test_position_performance_engine.py``-style pure engines.

Run directly with ``python Tests/test_strategy_performance_engine.py``
-- no external test framework required.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.strategy_performance_engine import (  # noqa: E402
    EpisodeStrategyOutcome,
    StrategyPerformanceEngine,
)

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


def scenario_empty_list_returns_empty_dict():
    print("\n[Scenario 1] calculate() on an empty list returns an empty dict")
    result = StrategyPerformanceEngine().calculate([])
    check(result == {}, "empty outcomes -> empty dict")


def scenario_single_strategy_aggregates_correctly():
    print("\n[Scenario 2] a single strategy's episodes aggregate correctly")
    outcomes = [
        EpisodeStrategyOutcome(strategy="manual", realized_pnl=100.0),
        EpisodeStrategyOutcome(strategy="manual", realized_pnl=-40.0),
        EpisodeStrategyOutcome(strategy="manual", realized_pnl=0.0),
    ]
    result = StrategyPerformanceEngine().calculate(outcomes)
    check(list(result.keys()) == ["manual"], "exactly one strategy group")
    stats = result["manual"]
    check(stats.strategy == "manual", "strategy label preserved")
    check(stats.closed_episodes == 3, "closed_episodes counts every outcome")
    check(stats.winning_episodes == 1, "one winning episode")
    check(stats.losing_episodes == 1, "one losing episode")
    check(stats.breakeven_episodes == 1, "one breakeven episode (0.0 pnl)")
    check(stats.gross_profit == 100.0, "gross_profit sums positive pnl only")
    check(stats.gross_loss == 40.0, "gross_loss sums abs(negative pnl) only")
    check(stats.net_profit == 60.0, "net_profit = gross_profit - gross_loss")
    check(stats.average_win == 100.0, "average_win = gross_profit / winning_episodes")
    check(stats.average_loss == 40.0, "average_loss = gross_loss / losing_episodes")


def scenario_multiple_strategies_no_cross_contamination():
    print("\n[Scenario 3] multiple distinct strategies each get their own independent row")
    outcomes = [
        EpisodeStrategyOutcome(strategy="manual", realized_pnl=100.0),
        EpisodeStrategyOutcome(strategy="recommendation_following", realized_pnl=50.0),
        EpisodeStrategyOutcome(strategy="recommendation_following", realized_pnl=-20.0),
        EpisodeStrategyOutcome(strategy="mixed", realized_pnl=-10.0),
    ]
    result = StrategyPerformanceEngine().calculate(outcomes)
    check(
        set(result.keys()) == {"manual", "recommendation_following", "mixed"},
        "all three distinct strategy labels present, mixed treated as an ordinary label",
    )
    check(result["manual"].closed_episodes == 1, "manual group has its own single episode")
    check(
        result["recommendation_following"].closed_episodes == 2,
        "recommendation_following group has its own two episodes",
    )
    check(result["mixed"].closed_episodes == 1, "mixed group has its own single episode")
    check(result["manual"].net_profit == 100.0, "manual net_profit unaffected by other groups")
    check(
        result["recommendation_following"].net_profit == 30.0,
        "recommendation_following net_profit = 50 - 20, unaffected by other groups",
    )
    check(result["mixed"].net_profit == -10.0, "mixed net_profit unaffected by other groups")


def scenario_zero_division_guard():
    print("\n[Scenario 4] average_win/average_loss are 0.0 (never ZeroDivisionError) with no winners/losers")
    all_losses = [EpisodeStrategyOutcome(strategy="manual", realized_pnl=-5.0)]
    result = StrategyPerformanceEngine().calculate(all_losses)
    check(result["manual"].average_win == 0.0, "no winners -> average_win is 0.0")
    check(result["manual"].average_loss == 5.0, "one loser -> average_loss computed normally")

    all_wins = [EpisodeStrategyOutcome(strategy="manual", realized_pnl=5.0)]
    result2 = StrategyPerformanceEngine().calculate(all_wins)
    check(result2["manual"].average_loss == 0.0, "no losers -> average_loss is 0.0")


def scenario_no_mutation_of_input():
    print("\n[Scenario 5] input outcomes list is never mutated")
    outcomes = [
        EpisodeStrategyOutcome(strategy="manual", realized_pnl=100.0),
        EpisodeStrategyOutcome(strategy="manual", realized_pnl=-40.0),
    ]
    before = copy.deepcopy(outcomes)
    StrategyPerformanceEngine().calculate(outcomes)
    check(outcomes == before, "outcomes list and elements are byte-for-byte unchanged after calculate()")


def scenario_deterministic_calculate():
    print("\n[Scenario 6] calculating the same input twice yields equal results")
    outcomes = [
        EpisodeStrategyOutcome(strategy="manual", realized_pnl=100.0),
        EpisodeStrategyOutcome(strategy="recommendation_following", realized_pnl=-40.0),
    ]
    engine = StrategyPerformanceEngine()
    first = engine.calculate(outcomes)
    second = engine.calculate(outcomes)
    check(first == second, "calculate() is a pure function -- same input always produces the same result")


def main() -> int:
    scenario_empty_list_returns_empty_dict()
    scenario_single_strategy_aggregates_correctly()
    scenario_multiple_strategies_no_cross_contamination()
    scenario_zero_division_guard()
    scenario_no_mutation_of_input()
    scenario_deterministic_calculate()

    print(f"\n{'=' * 70}\nRESULTS: {_PASS} passed, {_FAIL} failed\n{'=' * 70}")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())