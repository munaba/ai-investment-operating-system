"""Standalone regression checks for
``Business.maximum_drawdown_engine.MaximumDrawdownEngine``.

Covers Sprint 6 STEP 6 (Maximum Drawdown computed purely from an
already-built equity curve -- never from ``Position``/``Trade``
directly, never computing the equity curve itself):

* constructor takes no dependency;
* empty / single-point / strictly-increasing / all-equal curves all
  yield 0.0;
* a single drawdown, multiple drawdowns, and a fully-recovered
  drawdown all match the LOCKED DECISION formula exactly;
* the input list is never mutated;
* the return value is a real ``MaximumDrawdownResult`` instance with
  exactly one field;
* ``MaximumDrawdownEngine``'s public API is exactly ``{"calculate"}``.

Uses plain ``List[float]`` equity curves directly -- no ``Position``,
no ``Trade``, no database, no repository, no I/O, matching every
other ``Tests/test_*.py`` file in this project.

Run directly with ``python Tests/test_maximum_drawdown_engine.py`` --
no external test framework required.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.maximum_drawdown_engine import (  # noqa: E402
    MaximumDrawdownEngine,
    MaximumDrawdownResult,
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


def scenario_empty_list():
    print("\n[Scenario 1] empty equity curve")
    engine = MaximumDrawdownEngine()
    result = engine.calculate([])
    check(isinstance(result, MaximumDrawdownResult), "returns a MaximumDrawdownResult instance for an empty list")
    check(result.maximum_drawdown == 0.0, "maximum_drawdown == 0.0 for an empty equity curve")
    check(isinstance(result.maximum_drawdown, float), "maximum_drawdown is a float for an empty equity curve")
    check(result.maximum_drawdown is not None, "maximum_drawdown is never None for an empty equity curve")


def scenario_single_point():
    print("\n[Scenario 2] single equity point [100]")
    engine = MaximumDrawdownEngine()
    result = engine.calculate([100.0])
    check(result.maximum_drawdown == 0.0, "maximum_drawdown == 0.0 for a single-point equity curve")
    check(isinstance(result, MaximumDrawdownResult), "returns a MaximumDrawdownResult instance for a single-point curve")
    result_other = engine.calculate([1_000_000.0])
    check(result_other.maximum_drawdown == 0.0, "maximum_drawdown == 0.0 for a single-point curve regardless of magnitude")


def scenario_always_rising():
    print("\n[Scenario 3] strictly rising equity [100, 110, 120, 130]")
    engine = MaximumDrawdownEngine()
    result = engine.calculate([100.0, 110.0, 120.0, 130.0])
    check(result.maximum_drawdown == 0.0, "maximum_drawdown == 0.0 when equity never dips below its running peak")
    result_longer = engine.calculate([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
    check(result_longer.maximum_drawdown == 0.0, "maximum_drawdown == 0.0 for a longer strictly-rising curve")


def scenario_one_drawdown():
    print("\n[Scenario 4] a single drawdown [100, 120, 90]")
    engine = MaximumDrawdownEngine()
    result = engine.calculate([100.0, 120.0, 90.0])
    check(result.maximum_drawdown == 0.25, "maximum_drawdown == (120 - 90) / 120 == 0.25")
    check(result.maximum_drawdown > 0.0, "maximum_drawdown is positive when equity dips below its peak")
    check(result.maximum_drawdown <= 1.0, "maximum_drawdown never exceeds 1.0 for positive equity values")


def scenario_many_drawdowns():
    print("\n[Scenario 5] multiple drawdowns [100, 130, 120, 140, 100, 150]")
    engine = MaximumDrawdownEngine()
    result = engine.calculate([100.0, 130.0, 120.0, 140.0, 100.0, 150.0])
    expected = 40.0 / 140.0
    check(abs(result.maximum_drawdown - expected) < 1e-12, "maximum_drawdown == 40/140, the deepest of several drawdowns")
    check(result.maximum_drawdown > 0.0, "maximum_drawdown is positive when at least one drawdown occurs")
    smaller_drawdown = (130.0 - 120.0) / 130.0
    check(result.maximum_drawdown != smaller_drawdown, "maximum_drawdown picks the deepest dip, not an earlier shallower one")


def scenario_full_recovery():
    print("\n[Scenario 6] full recovery after a drawdown [100, 120, 90, 150]")
    engine = MaximumDrawdownEngine()
    result = engine.calculate([100.0, 120.0, 90.0, 150.0])
    check(result.maximum_drawdown == 0.25, "maximum_drawdown stays 0.25 even after equity fully recovers and makes a new high")
    check(result.maximum_drawdown != 0.0, "maximum_drawdown is not reset to 0.0 just because equity later recovers")


def scenario_all_equal():
    print("\n[Scenario 7] flat equity curve [100, 100, 100, 100]")
    engine = MaximumDrawdownEngine()
    result = engine.calculate([100.0, 100.0, 100.0, 100.0])
    check(result.maximum_drawdown == 0.0, "maximum_drawdown == 0.0 when every equity point is identical")
    result_two = engine.calculate([50.0, 50.0])
    check(result_two.maximum_drawdown == 0.0, "maximum_drawdown == 0.0 for a flat two-point curve")


def scenario_constructor_no_dependency():
    print("\n[Scenario 8] constructor takes no dependency")
    engine = MaximumDrawdownEngine()
    check(isinstance(engine, MaximumDrawdownEngine), "constructs a MaximumDrawdownEngine instance")
    import inspect
    params = [p for p in inspect.signature(MaximumDrawdownEngine.__init__).parameters if p != "self"]
    check(params == [], "MaximumDrawdownEngine.__init__ takes no parameter beyond self")
    check(callable(MaximumDrawdownEngine), "MaximumDrawdownEngine is constructible with no arguments")


def scenario_input_not_mutated():
    print("\n[Scenario 9] input equity curve is never mutated")
    engine = MaximumDrawdownEngine()
    equity_curve = [100.0, 130.0, 120.0, 140.0, 100.0, 150.0]
    equity_curve_before = copy.deepcopy(equity_curve)
    engine.calculate(equity_curve)
    check(equity_curve == equity_curve_before, "the input equity curve list is unchanged after calculate()")
    check(len(equity_curve) == len(equity_curve_before), "calculate() does not add or remove elements from the input list")
    check(equity_curve[0] == 100.0, "first element of the input equity curve is unchanged")
    check(equity_curve[-1] == 150.0, "last element of the input equity curve is unchanged")


def scenario_output_is_dataclass_instance():
    print("\n[Scenario 10] output dataclass shape")
    engine = MaximumDrawdownEngine()
    result = engine.calculate([])
    fields = set(vars(result).keys())
    check(fields == {"maximum_drawdown"}, "MaximumDrawdownResult has exactly one LOCKED field, no more")
    check(len(fields) == 1, "MaximumDrawdownResult has exactly one field total")
    check(hasattr(result, "maximum_drawdown"), "MaximumDrawdownResult exposes a 'maximum_drawdown' attribute")


def scenario_no_public_method_other_than_calculate():
    print("\n[Scenario 11] MaximumDrawdownEngine exposes only calculate() publicly")
    public_methods = {name for name in dir(MaximumDrawdownEngine) if not name.startswith("_")}
    check(public_methods == {"calculate"}, "MaximumDrawdownEngine's public API is exactly {'calculate'}")
    check("calculate" in public_methods, "'calculate' is present in MaximumDrawdownEngine's public API")
    check(len(public_methods) == 1, "MaximumDrawdownEngine exposes exactly one public method")


def scenario_drawdown_at_the_very_end():
    print("\n[Scenario 12] the deepest drawdown is the final point, with no recovery")
    engine = MaximumDrawdownEngine()
    result = engine.calculate([200.0, 250.0, 180.0, 220.0, 100.0])
    # peak sequence: 200, 250, 250, 250, 250
    # drawdowns:       0,   0, 0.28, 0.12, 0.6
    expected = (250.0 - 100.0) / 250.0
    check(abs(result.maximum_drawdown - expected) < 1e-12, "maximum_drawdown correctly picks up the deepest drawdown even at the last point")
    check(result.maximum_drawdown > (250.0 - 180.0) / 250.0, "maximum_drawdown at the final point is deeper than the intermediate dip")


def scenario_two_point_drop():
    print("\n[Scenario 13] minimal two-point drop [200, 100]")
    engine = MaximumDrawdownEngine()
    result = engine.calculate([200.0, 100.0])
    check(result.maximum_drawdown == 0.5, "maximum_drawdown == (200 - 100) / 200 == 0.5 for a simple two-point drop")


def main() -> int:
    scenario_empty_list()
    scenario_single_point()
    scenario_always_rising()
    scenario_one_drawdown()
    scenario_many_drawdowns()
    scenario_full_recovery()
    scenario_all_equal()
    scenario_constructor_no_dependency()
    scenario_input_not_mutated()
    scenario_output_is_dataclass_instance()
    scenario_no_public_method_other_than_calculate()
    scenario_drawdown_at_the_very_end()
    scenario_two_point_drop()

    print("\n" + "=" * 60)
    print(f"MAXIMUM DRAWDOWN ENGINE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())