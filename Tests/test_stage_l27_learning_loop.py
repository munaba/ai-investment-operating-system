"""
Stage L27 proof suite -- Learning Loop (Stage L27, additive component).

Scope: dedicated regression suite for
``Orchestration.learning_loop.LearningLoopError``,
``Orchestration.learning_loop.LearningLoopResult``, and
``Orchestration.learning_loop.LearningLoop`` only. No Composition Root
wiring assertions beyond a plain construction/attribute smoke check,
no automatic invocation from StockAgent/RuntimeAnalysisPipeline/
DecisionEngine/DecisionPolicy/PolicyGuard/ExecutionIntent/
ExecutionPlanner/ExecutionCoordinator/PortfolioEngine/PortfolioRisk, no
model update, no background/autonomous behaviour -- all explicitly out
of scope for L27.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l18_reflection.py`` through
``test_stage_l26_portfolio_risk.py``: a global pass/fail counter,
plain fixtures, and a ``main()`` runner. No ``unittest`` module is
used, matching the existing convention.

Invariant coverage:
    I1  -- an approved portfolio risk result produces recorded=True,
           signal="POSITIVE", and violation_count=0.
    I2  -- notes for an approved result contains the exposure_level and
           diversification_level.
    I3  -- a not-approved portfolio risk result produces recorded=True,
           signal="NEGATIVE".
    I4  -- violation_count for a not-approved result equals the length
           of the input's violations sequence.
    I5  -- notes for a not-approved result contains the violation
           count.
    I6  -- a portfolio risk result missing a required attribute raises
           LearningLoopError (not AttributeError).
    I7  -- LearningLoopResult is a frozen dataclass.
    I8  -- LearningLoopResult declares exactly four fields.
    I9  -- LearningLoopError subclasses Core.exceptions.AgentError.
    I10 -- LearningLoop holds no instance attributes (stateless) and is
           deterministic across repeated calls with the same input.
    I11 -- an empty violations tuple on a not-approved result produces
           violation_count=0.
    I12 -- Core.composition_root.build_application() exposes a
           LearningLoop instance on ApplicationGraph.learning_loop.
"""

from __future__ import annotations

import dataclasses
import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.learning_loop import (
    LearningLoop,
    LearningLoopError,
    LearningLoopResult,
)

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


class _FakePortfolioRiskResult:
    """Minimal stand-in for
    Orchestration.portfolio_risk.PortfolioRiskResult.

    LearningLoop.learn() only reads ``approved``, ``exposure_level``,
    ``diversification_level``, and ``violations`` off its argument, so
    a lightweight plain object is sufficient and keeps this suite
    independent of PortfolioRisk.
    """

    def __init__(
        self,
        approved: bool = True,
        exposure_level: str = "LOW",
        diversification_level: str = "DIVERSIFIED",
        violations=(),
        notes: str = "",
    ) -> None:
        self.approved = approved
        self.exposure_level = exposure_level
        self.diversification_level = diversification_level
        self.violations = violations
        self.notes = notes


class _PortfolioRiskResultMissingField:
    """Stand-in risk result object deliberately missing 'violations'."""

    def __init__(self) -> None:
        self.approved = False
        self.exposure_level = "HIGH"
        self.diversification_level = "CONCENTRATED"


# ---------------------------------------------------------------------------
# Group 1 -- LearningLoopError
# ---------------------------------------------------------------------------
def scenario_learning_loop_error_is_agent_error() -> None:
    check(
        issubclass(LearningLoopError, AgentError),
        "I9: LearningLoopError subclasses Core.exceptions.AgentError, "
        "same convention as PortfolioRiskError/PortfolioEngineError/"
        "ExecutionCoordinatorError/ExecutionPlannerError/"
        "ExecutionIntentError/PolicyGuardError/DecisionPolicyError/"
        "DecisionEngineError/ReflectionError",
    )
    err = LearningLoopError("boom")
    check(isinstance(err, Exception), "LearningLoopError is constructible with a plain message")


# ---------------------------------------------------------------------------
# Group 2 -- LearningLoopResult (value shape) -- I7, I8
# ---------------------------------------------------------------------------
def scenario_result_is_frozen_dataclass() -> None:
    result = LearningLoop().learn(_FakePortfolioRiskResult())

    check(dataclasses.is_dataclass(result), "LearningLoopResult is a dataclass")

    frozen = False
    try:
        result.recorded = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(
        frozen,
        "I7: LearningLoopResult is frozen -- field reassignment raises "
        "FrozenInstanceError",
    )


def scenario_result_has_expected_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(LearningLoopResult)}
    check(
        field_names == {"recorded", "signal", "violation_count", "notes"},
        "I8: LearningLoopResult declares exactly four fields "
        "(recorded, signal, violation_count, notes)",
    )


# ---------------------------------------------------------------------------
# Group 3 -- approved portfolio risk result -- I1, I2
# ---------------------------------------------------------------------------
def scenario_approved_result_is_recorded_positive() -> None:
    result = LearningLoop().learn(
        _FakePortfolioRiskResult(approved=True, exposure_level="LOW", diversification_level="DIVERSIFIED")
    )
    check(
        result.recorded is True and result.signal == "POSITIVE" and result.violation_count == 0,
        "I1: an approved portfolio risk result produces recorded=True, "
        "signal='POSITIVE', and violation_count=0",
    )


def scenario_approved_notes_contains_levels() -> None:
    result = LearningLoop().learn(
        _FakePortfolioRiskResult(approved=True, exposure_level="MODERATE", diversification_level="DIVERSIFIED")
    )
    check(
        "MODERATE" in result.notes and "DIVERSIFIED" in result.notes,
        "I2: notes for an approved result contains the exposure_level "
        "and diversification_level",
    )


# ---------------------------------------------------------------------------
# Group 4 -- not-approved portfolio risk result -- I3, I4
# ---------------------------------------------------------------------------
def scenario_not_approved_result_is_recorded_negative() -> None:
    result = LearningLoop().learn(
        _FakePortfolioRiskResult(approved=False, violations=("v1", "v2"))
    )
    check(
        result.recorded is True and result.signal == "NEGATIVE",
        "I3: a not-approved portfolio risk result produces recorded=True, "
        "signal='NEGATIVE'",
    )


def scenario_violation_count_matches_input_length() -> None:
    result = LearningLoop().learn(
        _FakePortfolioRiskResult(approved=False, violations=("a", "b", "c"))
    )
    check(
        result.violation_count == 3,
        "I4: violation_count for a not-approved result equals the "
        "length of the input's violations sequence",
    )


# ---------------------------------------------------------------------------
# Group 5 -- notes content for not-approved -- I5
# ---------------------------------------------------------------------------
def scenario_not_approved_notes_contains_violation_count() -> None:
    result = LearningLoop().learn(
        _FakePortfolioRiskResult(approved=False, violations=("x", "y"))
    )
    check(
        "2" in result.notes,
        "I5: notes for a not-approved result contains the violation count",
    )


# ---------------------------------------------------------------------------
# Group 6 -- empty violations on not-approved -- I11
# ---------------------------------------------------------------------------
def scenario_empty_violations_produces_zero_count() -> None:
    result = LearningLoop().learn(
        _FakePortfolioRiskResult(approved=False, violations=())
    )
    check(
        result.violation_count == 0,
        "I11: an empty violations tuple on a not-approved result "
        "produces violation_count=0",
    )


# ---------------------------------------------------------------------------
# Group 7 -- missing attribute -- I6
# ---------------------------------------------------------------------------
def scenario_missing_attribute_raises_learning_loop_error() -> None:
    raised_type = None
    try:
        LearningLoop().learn(_PortfolioRiskResultMissingField())
    except LearningLoopError:
        raised_type = LearningLoopError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is LearningLoopError,
        "I6: LearningLoop.learn() raises LearningLoopError (not "
        "AttributeError) when the portfolio risk result object is "
        "missing a required attribute ('violations')",
    )


# ---------------------------------------------------------------------------
# Group 8 -- statelessness / determinism -- I10
# ---------------------------------------------------------------------------
def scenario_learning_loop_has_no_instance_attributes() -> None:
    loop = LearningLoop()
    check(
        vars(loop) == {},
        "I10: a LearningLoop instance holds no instance attributes "
        "(vars() is empty), confirming it is safe to reuse across calls",
    )


def scenario_learning_loop_is_deterministic() -> None:
    loop = LearningLoop()
    first = loop.learn(_FakePortfolioRiskResult(approved=True, exposure_level="HIGH", diversification_level="DIVERSIFIED"))
    second = loop.learn(_FakePortfolioRiskResult(approved=True, exposure_level="HIGH", diversification_level="DIVERSIFIED"))

    check(
        first == second,
        "I10: LearningLoop.learn() is deterministic -- the same input "
        "portfolio risk result always produces an equal "
        "LearningLoopResult",
    )


# ---------------------------------------------------------------------------
# Group 9 -- composition root wiring smoke check -- I12
# ---------------------------------------------------------------------------
def scenario_composition_root_exposes_learning_loop() -> None:
    from Core.composition_root import build_application

    graph = build_application()
    check(
        isinstance(graph.learning_loop, LearningLoop),
        "I12: Core.composition_root.build_application() exposes a "
        "LearningLoop instance on ApplicationGraph.learning_loop",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_learning_loop_error_is_agent_error,
        # Group 2
        scenario_result_is_frozen_dataclass,
        scenario_result_has_expected_fields,
        # Group 3
        scenario_approved_result_is_recorded_positive,
        scenario_approved_notes_contains_levels,
        # Group 4
        scenario_not_approved_result_is_recorded_negative,
        scenario_violation_count_matches_input_length,
        # Group 5
        scenario_not_approved_notes_contains_violation_count,
        # Group 6
        scenario_empty_violations_produces_zero_count,
        # Group 7
        scenario_missing_attribute_raises_learning_loop_error,
        # Group 8
        scenario_learning_loop_has_no_instance_attributes,
        scenario_learning_loop_is_deterministic,
        # Group 9
        scenario_composition_root_exposes_learning_loop,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"STAGE L27 LEARNING LOOP RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())