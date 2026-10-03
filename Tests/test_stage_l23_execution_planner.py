"""
Stage L23 proof suite -- Execution Planner (Stage L23, additive component).

Scope: dedicated regression suite for
``Orchestration.execution_planner.ExecutionPlannerError``,
``Orchestration.execution_planner.ExecutionPlan``, and
``Orchestration.execution_planner.ExecutionPlanner`` only. No
Composition Root wiring assertions beyond a plain
construction/attribute smoke check, no automatic invocation from
StockAgent/RuntimeAnalysisPipeline/DecisionEngine/DecisionPolicy/
PolicyGuard/ExecutionIntent, no real order placement or execution --
all explicitly out of scope for L23.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l18_reflection.py``, ``test_stage_l19_decision_engine.py``,
``test_stage_l20_decision_policy.py``,
``test_stage_l21_policy_guard.py``, and
``test_stage_l22_execution_intent.py``: a global pass/fail counter,
plain fixtures, and a ``main()`` runner. No ``unittest`` module is
used, matching the existing convention.

Invariant coverage:
    I1  -- a ready execution intent produces planned=True and an empty
           skip_reason.
    I2  -- a ready plan's action/risk_level/position_size are carried
           through unchanged.
    I3  -- a not-ready execution intent produces planned=False.
    I4  -- a not-ready plan's skip_reason is taken from the intent's
           own denial_reason.
    I5  -- a not-ready plan's action/risk_level/position_size are still
           carried through unchanged (never zeroed/substituted).
    I6  -- a not-ready intent with an empty denial_reason falls back to
           a generic skip_reason rather than an empty string.
    I7  -- notes contains the action name for both planned and skipped
           plans.
    I8  -- notes contains the skip_reason text for a skipped plan.
    I9  -- an execution intent missing a required attribute raises
           ExecutionPlannerError (not AttributeError).
    I10 -- ExecutionPlan is a frozen dataclass.
    I11 -- ExecutionPlan declares exactly six fields.
    I12 -- ExecutionPlannerError subclasses Core.exceptions.AgentError.
    I13 -- ExecutionPlanner holds no instance attributes (stateless)
           and is deterministic across repeated calls with the same
           input.
    I14 -- behavior is consistent across BUY/HOLD/SELL-shaped inputs,
           both ready and not-ready, for every action.
    I15 -- Core.composition_root.build_application() exposes an
           ExecutionPlanner instance on ApplicationGraph.execution_planner.
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
from Orchestration.execution_planner import (
    ExecutionPlan,
    ExecutionPlanner,
    ExecutionPlannerError,
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


class _FakeExecutionIntent:
    """Minimal stand-in for Orchestration.execution_intent.ExecutionIntentResult.

    ExecutionPlanner.plan() only reads ``ready``, ``action``,
    ``risk_level``, ``position_size``, and ``denial_reason`` off its
    argument, so a lightweight plain object is sufficient and keeps
    this suite independent of ExecutionIntent.
    """

    def __init__(
        self,
        ready: bool = True,
        action: str = "BUY",
        risk_level: str = "NORMAL",
        position_size: float = 1.0,
        denial_reason: str = "",
    ) -> None:
        self.ready = ready
        self.action = action
        self.risk_level = risk_level
        self.position_size = position_size
        self.denial_reason = denial_reason


class _ExecutionIntentMissingField:
    """Stand-in execution intent object deliberately missing 'denial_reason'."""

    def __init__(self) -> None:
        self.ready = False
        self.action = "BUY"
        self.risk_level = "NORMAL"
        self.position_size = 1.0


# ---------------------------------------------------------------------------
# Group 1 -- ExecutionPlannerError
# ---------------------------------------------------------------------------
def scenario_execution_planner_error_is_agent_error() -> None:
    check(
        issubclass(ExecutionPlannerError, AgentError),
        "I12: ExecutionPlannerError subclasses Core.exceptions.AgentError, "
        "same convention as ExecutionIntentError/PolicyGuardError/"
        "DecisionPolicyError/DecisionEngineError/ReflectionError",
    )
    err = ExecutionPlannerError("boom")
    check(isinstance(err, Exception), "ExecutionPlannerError is constructible with a plain message")


# ---------------------------------------------------------------------------
# Group 2 -- ExecutionPlan (value shape) -- I10, I11
# ---------------------------------------------------------------------------
def scenario_result_is_frozen_dataclass() -> None:
    result = ExecutionPlanner().plan(_FakeExecutionIntent())

    check(dataclasses.is_dataclass(result), "ExecutionPlan is a dataclass")

    frozen = False
    try:
        result.planned = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(
        frozen,
        "I10: ExecutionPlan is frozen -- field reassignment raises "
        "FrozenInstanceError",
    )


def scenario_result_has_expected_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(ExecutionPlan)}
    check(
        field_names
        == {
            "planned",
            "action",
            "risk_level",
            "position_size",
            "skip_reason",
            "notes",
        },
        "I11: ExecutionPlan declares exactly six fields (planned, "
        "action, risk_level, position_size, skip_reason, notes)",
    )


# ---------------------------------------------------------------------------
# Group 3 -- ready execution intent -- I1, I2
# ---------------------------------------------------------------------------
def scenario_ready_buy_is_planned_with_empty_skip_reason() -> None:
    result = ExecutionPlanner().plan(
        _FakeExecutionIntent(ready=True, action="BUY", risk_level="NORMAL", position_size=1.0)
    )
    check(
        result.planned is True and result.skip_reason == "",
        "I1: a ready BUY execution intent produces planned=True and an "
        "empty skip_reason",
    )


def scenario_ready_fields_are_preserved() -> None:
    result = ExecutionPlanner().plan(
        _FakeExecutionIntent(ready=True, action="HOLD", risk_level="LOW", position_size=0.5)
    )
    check(
        result.action == "HOLD" and result.risk_level == "LOW" and result.position_size == 0.5,
        "I2: a ready plan's action/risk_level/position_size are carried "
        "through unchanged",
    )


# ---------------------------------------------------------------------------
# Group 4 -- not-ready execution intent -- I3, I4
# ---------------------------------------------------------------------------
def scenario_not_ready_result_is_not_planned() -> None:
    result = ExecutionPlanner().plan(
        _FakeExecutionIntent(ready=False, denial_reason="some reason")
    )
    check(result.planned is False, "I3: a not-ready execution intent produces planned=False")


def scenario_not_ready_skip_reason_matches_denial_reason() -> None:
    result = ExecutionPlanner().plan(
        _FakeExecutionIntent(ready=False, denial_reason="conflicting entry/exit flags")
    )
    check(
        result.skip_reason == "conflicting entry/exit flags",
        "I4: a not-ready plan's skip_reason is taken from the intent's "
        "own denial_reason unchanged",
    )


# ---------------------------------------------------------------------------
# Group 5 -- not-ready plan preserves fields -- I5
# ---------------------------------------------------------------------------
def scenario_not_ready_fields_are_still_preserved() -> None:
    result = ExecutionPlanner().plan(
        _FakeExecutionIntent(
            ready=False,
            action="SELL",
            risk_level="HIGH",
            position_size=0.0,
            denial_reason="policy guard result was not approved",
        )
    )
    check(
        result.action == "SELL" and result.risk_level == "HIGH" and result.position_size == 0.0,
        "I5: a not-ready plan's action/risk_level/position_size are "
        "still carried through unchanged, never zeroed or substituted",
    )


# ---------------------------------------------------------------------------
# Group 6 -- empty denial_reason fallback -- I6
# ---------------------------------------------------------------------------
def scenario_not_ready_with_empty_denial_reason_uses_generic_fallback() -> None:
    result = ExecutionPlanner().plan(
        _FakeExecutionIntent(ready=False, denial_reason="")
    )
    check(
        result.skip_reason == "execution intent was not ready",
        "I6: a not-ready intent with an empty denial_reason falls back "
        "to a generic skip_reason rather than an empty string",
    )


def scenario_empty_denial_reason_fallback_is_not_blank() -> None:
    result = ExecutionPlanner().plan(
        _FakeExecutionIntent(ready=False, denial_reason="")
    )
    check(
        len(result.skip_reason) > 0,
        "I6: the generic fallback skip_reason is non-empty",
    )


# ---------------------------------------------------------------------------
# Group 7 -- notes content -- I7, I8
# ---------------------------------------------------------------------------
def scenario_notes_contains_action_name_when_planned() -> None:
    result = ExecutionPlanner().plan(_FakeExecutionIntent(ready=True, action="BUY"))
    check(
        "BUY" in result.notes,
        "I7: notes contains the action name ('BUY') for a planned result",
    )


def scenario_notes_contains_action_name_when_skipped() -> None:
    result = ExecutionPlanner().plan(
        _FakeExecutionIntent(ready=False, action="SELL", denial_reason="bad")
    )
    check(
        "SELL" in result.notes,
        "I7: notes contains the action name ('SELL') for a skipped result",
    )


def scenario_notes_contains_skip_reason_when_skipped() -> None:
    result = ExecutionPlanner().plan(
        _FakeExecutionIntent(ready=False, denial_reason="specific reason")
    )
    check(
        "specific reason" in result.notes,
        "I8: notes contains the skip_reason text for a skipped result",
    )


# ---------------------------------------------------------------------------
# Group 8 -- missing attribute -- I9
# ---------------------------------------------------------------------------
def scenario_missing_attribute_raises_execution_planner_error() -> None:
    raised_type = None
    try:
        ExecutionPlanner().plan(_ExecutionIntentMissingField())
    except ExecutionPlannerError:
        raised_type = ExecutionPlannerError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is ExecutionPlannerError,
        "I9: ExecutionPlanner.plan() raises ExecutionPlannerError (not "
        "AttributeError) when the execution intent object is missing a "
        "required attribute ('denial_reason')",
    )


# ---------------------------------------------------------------------------
# Group 9 -- statelessness / determinism -- I13
# ---------------------------------------------------------------------------
def scenario_execution_planner_has_no_instance_attributes() -> None:
    planner = ExecutionPlanner()
    check(
        vars(planner) == {},
        "I13: an ExecutionPlanner instance holds no instance attributes "
        "(vars() is empty), confirming it is safe to reuse across calls",
    )


def scenario_execution_planner_is_deterministic() -> None:
    planner = ExecutionPlanner()
    first = planner.plan(_FakeExecutionIntent(ready=True, action="HOLD", position_size=0.5))
    second = planner.plan(_FakeExecutionIntent(ready=True, action="HOLD", position_size=0.5))

    check(
        first == second,
        "I13: ExecutionPlanner.plan() is deterministic -- the same "
        "input execution intent always produces an equal ExecutionPlan",
    )


# ---------------------------------------------------------------------------
# Group 10 -- consistency across actions -- I14
# ---------------------------------------------------------------------------
def scenario_all_actions_planned_when_ready() -> None:
    planner = ExecutionPlanner()
    all_planned = all(
        planner.plan(_FakeExecutionIntent(ready=True, action=action)).planned is True
        for action in ("BUY", "HOLD", "SELL")
    )
    check(
        all_planned,
        "I14: BUY, HOLD, and SELL all produce planned=True when ready",
    )


def scenario_all_actions_skipped_when_not_ready() -> None:
    planner = ExecutionPlanner()
    all_skipped = all(
        planner.plan(
            _FakeExecutionIntent(ready=False, action=action, denial_reason="x")
        ).planned
        is False
        for action in ("BUY", "HOLD", "SELL")
    )
    check(
        all_skipped,
        "I14: BUY, HOLD, and SELL all produce planned=False when not ready",
    )


# ---------------------------------------------------------------------------
# Group 11 -- composition root wiring smoke check -- I15
# ---------------------------------------------------------------------------
def scenario_composition_root_exposes_execution_planner() -> None:
    from Core.composition_root import build_application

    graph = build_application()
    check(
        isinstance(graph.execution_planner, ExecutionPlanner),
        "I15: Core.composition_root.build_application() exposes an "
        "ExecutionPlanner instance on ApplicationGraph.execution_planner",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_execution_planner_error_is_agent_error,
        # Group 2
        scenario_result_is_frozen_dataclass,
        scenario_result_has_expected_fields,
        # Group 3
        scenario_ready_buy_is_planned_with_empty_skip_reason,
        scenario_ready_fields_are_preserved,
        # Group 4
        scenario_not_ready_result_is_not_planned,
        scenario_not_ready_skip_reason_matches_denial_reason,
        # Group 5
        scenario_not_ready_fields_are_still_preserved,
        # Group 6
        scenario_not_ready_with_empty_denial_reason_uses_generic_fallback,
        scenario_empty_denial_reason_fallback_is_not_blank,
        # Group 7
        scenario_notes_contains_action_name_when_planned,
        scenario_notes_contains_action_name_when_skipped,
        scenario_notes_contains_skip_reason_when_skipped,
        # Group 8
        scenario_missing_attribute_raises_execution_planner_error,
        # Group 9
        scenario_execution_planner_has_no_instance_attributes,
        scenario_execution_planner_is_deterministic,
        # Group 10
        scenario_all_actions_planned_when_ready,
        scenario_all_actions_skipped_when_not_ready,
        # Group 11
        scenario_composition_root_exposes_execution_planner,
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
    print(f"STAGE L23 EXECUTION PLANNER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())