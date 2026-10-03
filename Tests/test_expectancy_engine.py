"""Standalone regression checks for
``Business.expectancy_engine.ExpectancyEngine``.

Covers Sprint 6 STEP 5 (expectancy computed purely from an
already-built ``PositionPerformanceStatistics`` -- never from
``Position`` directly):

* constructor takes no dependency;
* all-win / all-loss / 50-50 / mixed-with-breakeven scenarios match
  the LOCKED DECISION formula exactly;
* zero closed positions returns ``0.0`` (no ``ZeroDivisionError``);
* the input ``PositionPerformanceStatistics`` is never mutated;
* the return value is a real ``ExpectancyResult`` instance with
  exactly one field;
* ``ExpectancyEngine``'s public API is exactly ``{"calculate"}``.

Builds ``PositionPerformanceStatistics`` instances directly -- no
``Position``, no database, no repository, no I/O, matching every other
``Tests/test_*.py`` file in this project.

Run directly with ``python Tests/test_expectancy_engine.py`` -- no
external test framework required.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.expectancy_engine import (  # noqa: E402
    ExpectancyEngine,
    ExpectancyResult,
)
from Business.position_performance_engine import (  # noqa: E402
    PositionPerformanceStatistics,
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


def _statistics(
    winning_positions: int,
    losing_positions: int,
    breakeven_positions: int = 0,
    average_win: float = 0.0,
    average_loss: float = 0.0,
    gross_profit: float = 0.0,
    gross_loss: float = 0.0,
    net_profit: float = 0.0,
) -> PositionPerformanceStatistics:
    return PositionPerformanceStatistics(
        winning_positions=winning_positions,
        losing_positions=losing_positions,
        breakeven_positions=breakeven_positions,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_profit=net_profit,
        average_win=average_win,
        average_loss=average_loss,
    )


def scenario_constructor_no_dependency():
    print("\n[Scenario 1] constructor takes no dependency")
    engine = ExpectancyEngine()
    check(isinstance(engine, ExpectancyEngine), "constructs an ExpectancyEngine instance")


def scenario_all_win():
    print("\n[Scenario 2] all positions win (win=10, loss=0, average_win=100)")
    engine = ExpectancyEngine()
    statistics = _statistics(winning_positions=10, losing_positions=0, average_win=100.0, average_loss=0.0)
    result = engine.calculate(statistics)
    check(isinstance(result, ExpectancyResult), "returns an ExpectancyResult instance")
    check(result.expectancy == 100.0, "expectancy == 100.0 when every closed position wins")
    check(isinstance(result.expectancy, float), "expectancy is a float when all positions win")
    check(statistics.winning_positions == 10, "statistics.winning_positions still 10 after calculate()")
    check(statistics.losing_positions == 0, "statistics.losing_positions still 0 after calculate()")
    check(statistics.average_win == 100.0, "statistics.average_win still 100.0 after calculate()")


def scenario_all_loss():
    print("\n[Scenario 3] all positions lose (win=0, loss=10, average_loss=80)")
    engine = ExpectancyEngine()
    statistics = _statistics(winning_positions=0, losing_positions=10, average_win=0.0, average_loss=80.0)
    result = engine.calculate(statistics)
    check(isinstance(result, ExpectancyResult), "returns an ExpectancyResult instance when all positions lose")
    check(result.expectancy == -80.0, "expectancy == -80.0 when every closed position loses")
    check(result.expectancy < 0, "expectancy is negative when every closed position loses")
    check(statistics.losing_positions == 10, "statistics.losing_positions still 10 after calculate()")
    check(statistics.average_loss == 80.0, "statistics.average_loss still 80.0 after calculate()")


def scenario_fifty_fifty():
    print("\n[Scenario 4] 50/50 win-loss split (win=5, loss=5, average_win=120, average_loss=60)")
    engine = ExpectancyEngine()
    statistics = _statistics(winning_positions=5, losing_positions=5, average_win=120.0, average_loss=60.0)
    result = engine.calculate(statistics)
    check(result.expectancy == 30.0, "expectancy == (0.5 * 120) - (0.5 * 60) == 30.0")
    check(result.expectancy > 0, "expectancy is positive for a profitable 50/50 split")
    check(statistics.winning_positions == 5, "statistics.winning_positions still 5 after calculate()")
    check(statistics.losing_positions == 5, "statistics.losing_positions still 5 after calculate()")


def scenario_with_breakeven():
    print("\n[Scenario 5] with breakeven positions diluting both rates (win=4, loss=4, breakeven=2)")
    engine = ExpectancyEngine()
    statistics = _statistics(
        winning_positions=4,
        losing_positions=4,
        breakeven_positions=2,
        average_win=100.0,
        average_loss=50.0,
    )
    result = engine.calculate(statistics)
    check(result.expectancy == 20.0, "expectancy == (0.4 * 100) - (0.4 * 50) == 20.0 with breakeven diluting the rates")
    check(
        result.expectancy != ((4 / 8) * 100.0) - ((4 / 8) * 50.0),
        "expectancy is NOT computed against winning+losing alone (would wrongly be 25.0, ignoring breakeven)",
    )
    check(statistics.breakeven_positions == 2, "statistics.breakeven_positions still 2 after calculate()")


def scenario_no_positions():
    print("\n[Scenario 6] no closed positions at all")
    engine = ExpectancyEngine()
    statistics = _statistics(winning_positions=0, losing_positions=0, breakeven_positions=0)
    result = engine.calculate(statistics)
    check(isinstance(result, ExpectancyResult), "returns an ExpectancyResult instance even with zero positions")
    check(result.expectancy == 0.0, "expectancy == 0.0 when total_closed_positions is 0 (no ZeroDivisionError)")
    check(isinstance(result.expectancy, float), "expectancy is a float (0.0), not an int or None, for zero positions")


def scenario_only_breakeven_still_zero_division_safe():
    print("\n[Scenario 7] only breakeven positions (winning=0, losing=0, breakeven>0)")
    engine = ExpectancyEngine()
    statistics = _statistics(winning_positions=0, losing_positions=0, breakeven_positions=3)
    result = engine.calculate(statistics)
    check(result.expectancy == 0.0, "expectancy == 0.0 when only breakeven positions exist (win_rate and loss_rate both 0)")
    check(statistics.breakeven_positions == 3, "statistics.breakeven_positions still 3 after calculate()")


def scenario_input_not_mutated():
    print("\n[Scenario 8] input PositionPerformanceStatistics is never mutated")
    engine = ExpectancyEngine()
    statistics = _statistics(
        winning_positions=4,
        losing_positions=4,
        breakeven_positions=2,
        average_win=100.0,
        average_loss=50.0,
    )
    statistics_before = copy.deepcopy(statistics)
    engine.calculate(statistics)
    check(statistics == statistics_before, "the input PositionPerformanceStatistics is unchanged after calculate()")
    check(statistics.winning_positions == statistics_before.winning_positions, "winning_positions field unchanged")
    check(statistics.losing_positions == statistics_before.losing_positions, "losing_positions field unchanged")
    check(statistics.breakeven_positions == statistics_before.breakeven_positions, "breakeven_positions field unchanged")
    check(statistics.average_win == statistics_before.average_win, "average_win field unchanged")
    check(statistics.average_loss == statistics_before.average_loss, "average_loss field unchanged")


def scenario_output_is_dataclass_instance():
    print("\n[Scenario 9] output dataclass shape")
    engine = ExpectancyEngine()
    statistics = _statistics(winning_positions=0, losing_positions=0)
    result = engine.calculate(statistics)
    fields = set(vars(result).keys())
    check(fields == {"expectancy"}, "ExpectancyResult has exactly one LOCKED field, no more")
    check(len(fields) == 1, "ExpectancyResult has exactly one field total")
    check(hasattr(result, "expectancy"), "ExpectancyResult exposes an 'expectancy' attribute")


def scenario_no_public_method_other_than_calculate():
    print("\n[Scenario 10] ExpectancyEngine exposes only calculate() publicly")
    public_methods = {name for name in dir(ExpectancyEngine) if not name.startswith("_")}
    check(public_methods == {"calculate"}, "ExpectancyEngine's public API is exactly {'calculate'}")
    check("calculate" in public_methods, "'calculate' is present in ExpectancyEngine's public API")
    check(len(public_methods) == 1, "ExpectancyEngine exposes exactly one public method")


def scenario_negative_expectancy_mixed():
    print("\n[Scenario 11] a losing system: low win rate, small average win, large average loss")
    engine = ExpectancyEngine()
    statistics = _statistics(
        winning_positions=2,
        losing_positions=8,
        breakeven_positions=0,
        average_win=50.0,
        average_loss=30.0,
    )
    result = engine.calculate(statistics)
    # win_rate = 0.2, loss_rate = 0.8 -> (0.2*50) - (0.8*30) = 10 - 24 = -14
    check(result.expectancy == -14.0, "expectancy == (0.2 * 50) - (0.8 * 30) == -14.0 for a losing system")
    check(result.expectancy < 0, "expectancy is negative for a system with a low win rate and large average loss")


def scenario_result_independent_of_gross_and_net_fields():
    print("\n[Scenario 12] gross_profit/gross_loss/net_profit are ignored by the formula")
    engine = ExpectancyEngine()
    baseline = _statistics(winning_positions=5, losing_positions=5, average_win=120.0, average_loss=60.0)
    with_noise = _statistics(
        winning_positions=5,
        losing_positions=5,
        average_win=120.0,
        average_loss=60.0,
        gross_profit=999_999.0,
        gross_loss=999_999.0,
        net_profit=-999_999.0,
    )
    result_baseline = engine.calculate(baseline)
    result_with_noise = engine.calculate(with_noise)
    check(
        result_baseline.expectancy == result_with_noise.expectancy,
        "expectancy is unaffected by gross_profit/gross_loss/net_profit -- only winning/losing/breakeven/average_win/average_loss matter",
    )


def scenario_zero_average_win_with_wins_present():
    print("\n[Scenario 13] winning_positions > 0 but average_win == 0.0 (already STEP 3's result, not recomputed)")
    engine = ExpectancyEngine()
    statistics = _statistics(winning_positions=3, losing_positions=3, average_win=0.0, average_loss=40.0)
    result = engine.calculate(statistics)
    # win_rate = 0.5, loss_rate = 0.5 -> (0.5*0) - (0.5*40) = -20
    check(result.expectancy == -20.0, "expectancy == (0.5 * 0.0) - (0.5 * 40.0) == -20.0, average_win used as-is from STEP 3")


def main() -> int:
    scenario_constructor_no_dependency()
    scenario_all_win()
    scenario_all_loss()
    scenario_fifty_fifty()
    scenario_with_breakeven()
    scenario_no_positions()
    scenario_only_breakeven_still_zero_division_safe()
    scenario_input_not_mutated()
    scenario_output_is_dataclass_instance()
    scenario_no_public_method_other_than_calculate()
    scenario_negative_expectancy_mixed()
    scenario_result_independent_of_gross_and_net_fields()
    scenario_zero_average_win_with_wins_present()

    print("\n" + "=" * 60)
    print(f"EXPECTANCY ENGINE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())