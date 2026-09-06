"""Standalone regression checks for
``Business.profit_factor_engine.ProfitFactorEngine``.

Covers Sprint 6 STEP 5 (profit factor computed purely from an
already-built ``PositionPerformanceStatistics`` -- never from
``Position`` directly, never recomputing ``gross_profit``/
``gross_loss``):

* constructor takes no dependency;
* profit_factor == gross_profit / gross_loss for standard cases;
* gross_loss == 0 always yields 0.0, regardless of gross_profit (no
  inf/-inf/NaN/None ever produced);
* gross_profit == 0 and gross_loss == 0 together yields 0.0;
* the engine never reads net_profit, average_win, average_loss,
  winning_positions, losing_positions, or breakeven_positions;
* the input ``PositionPerformanceStatistics`` is never mutated;
* the return value is a real ``ProfitFactorResult`` instance with
  exactly one field;
* ``ProfitFactorEngine``'s public API is exactly ``{"calculate"}``.

Builds ``PositionPerformanceStatistics`` instances directly -- no
``Position``, no database, no repository, no I/O, matching every other
``Tests/test_*.py`` file in this project.

Run directly with ``python Tests/test_profit_factor_engine.py`` -- no
external test framework required.
"""

from __future__ import annotations

import copy
import math
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.profit_factor_engine import (  # noqa: E402
    ProfitFactorEngine,
    ProfitFactorResult,
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
    gross_profit: float,
    gross_loss: float,
    winning_positions: int = 0,
    losing_positions: int = 0,
    breakeven_positions: int = 0,
    net_profit: float = 0.0,
    average_win: float = 0.0,
    average_loss: float = 0.0,
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
    engine = ProfitFactorEngine()
    check(isinstance(engine, ProfitFactorEngine), "constructs a ProfitFactorEngine instance")
    import inspect
    params = [p for p in inspect.signature(ProfitFactorEngine.__init__).parameters if p != "self"]
    check(params == [], "ProfitFactorEngine.__init__ takes no parameter beyond self")


def scenario_profit_factor_2_0():
    print("\n[Scenario 2] gross_profit=1000, gross_loss=500 -> PF=2.0")
    engine = ProfitFactorEngine()
    statistics = _statistics(gross_profit=1000.0, gross_loss=500.0)
    result = engine.calculate(statistics)
    check(isinstance(result, ProfitFactorResult), "returns a ProfitFactorResult instance")
    check(result.profit_factor == 2.0, "profit_factor == 1000 / 500 == 2.0")
    check(isinstance(result.profit_factor, float), "profit_factor is a float")


def scenario_profit_factor_0_5():
    print("\n[Scenario 3] gross_profit=500, gross_loss=1000 -> PF=0.5")
    engine = ProfitFactorEngine()
    statistics = _statistics(gross_profit=500.0, gross_loss=1000.0)
    result = engine.calculate(statistics)
    check(result.profit_factor == 0.5, "profit_factor == 500 / 1000 == 0.5")
    check(result.profit_factor < 1.0, "profit_factor below 1.0 indicates a losing system")


def scenario_zero_gross_profit():
    print("\n[Scenario 4] gross_profit=0, gross_loss=1000 -> PF=0.0")
    engine = ProfitFactorEngine()
    statistics = _statistics(gross_profit=0.0, gross_loss=1000.0)
    result = engine.calculate(statistics)
    check(result.profit_factor == 0.0, "profit_factor == 0 / 1000 == 0.0")
    check(isinstance(result.profit_factor, float), "profit_factor is a float when gross_profit is 0")


def scenario_zero_gross_loss():
    print("\n[Scenario 5] gross_profit=1000, gross_loss=0 -> PF=0.0 (guarded, not inf)")
    engine = ProfitFactorEngine()
    statistics = _statistics(gross_profit=1000.0, gross_loss=0.0)
    result = engine.calculate(statistics)
    check(result.profit_factor == 0.0, "profit_factor == 0.0 when gross_loss is 0, despite gross_profit > 0")
    check(result.profit_factor != float("inf"), "profit_factor is never inf")
    check(not math.isnan(result.profit_factor), "profit_factor is never NaN")
    check(result.profit_factor is not None, "profit_factor is never None")


def scenario_both_zero():
    print("\n[Scenario 6] gross_profit=0, gross_loss=0 -> PF=0.0")
    engine = ProfitFactorEngine()
    statistics = _statistics(gross_profit=0.0, gross_loss=0.0)
    result = engine.calculate(statistics)
    check(result.profit_factor == 0.0, "profit_factor == 0.0 when both gross_profit and gross_loss are 0")
    check(isinstance(result, ProfitFactorResult), "returns a ProfitFactorResult instance even with no activity")
    check(not math.isnan(result.profit_factor), "profit_factor is never NaN when both gross_profit and gross_loss are 0")


def scenario_ignores_net_profit():
    print("\n[Scenario 7] engine does not use net_profit")
    engine = ProfitFactorEngine()
    baseline = _statistics(gross_profit=1000.0, gross_loss=500.0, net_profit=500.0)
    noisy = _statistics(gross_profit=1000.0, gross_loss=500.0, net_profit=-999_999.0)
    result_baseline = engine.calculate(baseline)
    result_noisy = engine.calculate(noisy)
    check(
        result_baseline.profit_factor == result_noisy.profit_factor,
        "profit_factor is identical regardless of net_profit -- net_profit is never read",
    )
    check(result_noisy.profit_factor == 2.0, "profit_factor still == gross_profit / gross_loss when net_profit is wildly different")


def scenario_ignores_average_win():
    print("\n[Scenario 8] engine does not use average_win")
    engine = ProfitFactorEngine()
    baseline = _statistics(gross_profit=1000.0, gross_loss=500.0, average_win=0.0)
    noisy = _statistics(gross_profit=1000.0, gross_loss=500.0, average_win=999_999.0)
    result_baseline = engine.calculate(baseline)
    result_noisy = engine.calculate(noisy)
    check(
        result_baseline.profit_factor == result_noisy.profit_factor,
        "profit_factor is identical regardless of average_win -- average_win is never read",
    )
    check(result_noisy.profit_factor == 2.0, "profit_factor still == gross_profit / gross_loss when average_win is wildly different")


def scenario_ignores_average_loss_and_counts():
    print("\n[Scenario 9] engine does not use average_loss, winning/losing/breakeven counts")
    engine = ProfitFactorEngine()
    baseline = _statistics(gross_profit=1000.0, gross_loss=500.0)
    noisy = _statistics(
        gross_profit=1000.0,
        gross_loss=500.0,
        winning_positions=999,
        losing_positions=999,
        breakeven_positions=999,
        average_loss=999_999.0,
    )
    result_baseline = engine.calculate(baseline)
    result_noisy = engine.calculate(noisy)
    check(
        result_baseline.profit_factor == result_noisy.profit_factor,
        "profit_factor is identical regardless of average_loss/winning_positions/losing_positions/breakeven_positions",
    )


def scenario_input_not_mutated():
    print("\n[Scenario 10] input PositionPerformanceStatistics is never mutated")
    engine = ProfitFactorEngine()
    statistics = _statistics(gross_profit=1000.0, gross_loss=500.0, winning_positions=4, losing_positions=2)
    statistics_before = copy.deepcopy(statistics)
    engine.calculate(statistics)
    check(statistics == statistics_before, "the input PositionPerformanceStatistics is unchanged after calculate()")
    check(statistics.gross_profit == statistics_before.gross_profit, "gross_profit field unchanged")
    check(statistics.gross_loss == statistics_before.gross_loss, "gross_loss field unchanged")
    check(statistics.winning_positions == statistics_before.winning_positions, "winning_positions field unchanged")
    check(statistics.losing_positions == statistics_before.losing_positions, "losing_positions field unchanged")


def scenario_output_is_dataclass_instance():
    print("\n[Scenario 11] output dataclass shape")
    engine = ProfitFactorEngine()
    statistics = _statistics(gross_profit=0.0, gross_loss=0.0)
    result = engine.calculate(statistics)
    fields = set(vars(result).keys())
    check(fields == {"profit_factor"}, "ProfitFactorResult has exactly one LOCKED field, no more")
    check(len(fields) == 1, "ProfitFactorResult has exactly one field total")
    check(hasattr(result, "profit_factor"), "ProfitFactorResult exposes a 'profit_factor' attribute")


def scenario_no_public_method_other_than_calculate():
    print("\n[Scenario 12] ProfitFactorEngine exposes only calculate() publicly")
    public_methods = {name for name in dir(ProfitFactorEngine) if not name.startswith("_")}
    check(public_methods == {"calculate"}, "ProfitFactorEngine's public API is exactly {'calculate'}")
    check("calculate" in public_methods, "'calculate' is present in ProfitFactorEngine's public API")
    check(len(public_methods) == 1, "ProfitFactorEngine exposes exactly one public method")


def scenario_never_produces_special_floats():
    print("\n[Scenario 13] profit_factor is never inf/-inf/NaN/None across edge inputs")
    engine = ProfitFactorEngine()
    for gross_profit, gross_loss in [(0.0, 0.0), (1000.0, 0.0), (0.0, 1000.0), (-500.0, 0.0)]:
        statistics = _statistics(gross_profit=gross_profit, gross_loss=gross_loss)
        result = engine.calculate(statistics)
        check(
            result.profit_factor is not None
            and result.profit_factor != float("inf")
            and result.profit_factor != float("-inf")
            and not math.isnan(result.profit_factor),
            f"profit_factor is a finite float (not inf/-inf/NaN/None) for gross_profit={gross_profit}, gross_loss={gross_loss}",
        )


def main() -> int:
    scenario_constructor_no_dependency()
    scenario_profit_factor_2_0()
    scenario_profit_factor_0_5()
    scenario_zero_gross_profit()
    scenario_zero_gross_loss()
    scenario_both_zero()
    scenario_ignores_net_profit()
    scenario_ignores_average_win()
    scenario_ignores_average_loss_and_counts()
    scenario_input_not_mutated()
    scenario_output_is_dataclass_instance()
    scenario_no_public_method_other_than_calculate()
    scenario_never_produces_special_floats()

    print("\n" + "=" * 60)
    print(f"PROFIT FACTOR ENGINE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())