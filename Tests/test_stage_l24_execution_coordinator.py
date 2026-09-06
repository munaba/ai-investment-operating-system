"""
Stage L24 proof suite -- Execution Coordinator (Stage L24, additive component).

Scope: dedicated regression suite for
``Orchestration.execution_coordinator.ExecutionCoordinatorError``,
``Orchestration.execution_coordinator.ExecutionCoordinatorResult``, and
``Orchestration.execution_coordinator.ExecutionCoordinator`` only. No
Composition Root wiring assertions beyond a plain
construction/attribute smoke check, no automatic invocation from
StockAgent/RuntimeAnalysisPipeline/DecisionEngine/DecisionPolicy/
PolicyGuard/ExecutionIntent/ExecutionPlanner, no real order placement
or execution -- all explicitly out of scope for L24.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l18_reflection.py``, ``test_stage_l19_decision_engine.py``,
``test_stage_l20_decision_policy.py``,
``test_stage_l21_policy_guard.py``, ``test_stage_l22_execution_intent.py``,
and ``test_stage_l23_execution_planner.py``: a global pass/fail
counter, plain fixtures, and a ``main()`` runner. No ``unittest``
module is used, matching the existing convention.

Invariant coverage:
    I1  -- a planned execution plan produces coordinated=True and an
           empty hold_reason.
    I2  -- a coordinated result's action/risk_level/position_size are
           carried through unchanged.
    I3  -- a not-planned execution plan produces coordinated=False.
    I4  -- a not-planned result's hold_reason is taken from the plan's
           own skip_reason.
    I5  -- a not-planned result's action/risk_level/position_size are
           still carried through unchanged (never zeroed/substituted).
    I6  -- a not-planned plan with an empty skip_reason falls back to
           a generic hold_reason rather than an empty string.
    I7  -- notes contains the action name for both coordinated and
           held results.
    I8  -- notes contains the hold_reason text for a held result.
    I9  -- an execution plan missing a required attribute raises
           ExecutionCoordinatorError (not AttributeError).
    I10 -- ExecutionCoordinatorResult is a frozen dataclass.
    I11 -- ExecutionCoordinatorResult declares exactly seven fields.
    I12 -- ExecutionCoordinatorError subclasses Core.exceptions.AgentError.
    I13 -- ExecutionCoordinator holds no instance attributes (stateless)
           and is deterministic across repeated calls with the same
           input.
    I14 -- behavior is consistent across BUY/HOLD/SELL-shaped inputs,
           both planned and not-planned, for every action.
    I15 -- Core.composition_root.build_application() exposes an
           ExecutionCoordinator instance on
           ApplicationGraph.execution_coordinator.
    I16 -- a coordinated result has sequence_position=1; a held result
           has sequence_position=0.
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
from Orchestration.execution_coordinator import (
    ExecutionCoordinator,
    ExecutionCoordinatorError,
    ExecutionCoordinatorResult,
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


class _FakeExecutionPlan:
    """Minimal stand-in for Orchestration.execution_planner.ExecutionPlan.

    ExecutionCoordinator.coordinate() only reads ``planned``, ``action``,
    ``risk_level``, ``position_size``, and ``skip_reason`` off its
    argument, so a lightweight plain object is sufficient and keeps
    this suite independent of ExecutionPlanner.
    """

    def __init__(
        self,
        planned: bool = True,
        action: str = "BUY",
        risk_level: str = "NORMAL",
        position_size: float = 1.0,
        skip_reason: str = "",
    ) -> None:
        self.planned = planned
        self.action = action
        self.risk_level = risk_level
        self.position_size = position_size
        self.skip_reason = skip_reason


class _ExecutionPlanMissingField:
    """Stand-in execution plan object deliberately missing 'skip_reason'."""

    def __init__(self) -> None:
        self.planned = False
        self.action = "BUY"
        self.risk_level = "NORMAL"
        self.position_size = 1.0


# ---------------------------------------------------------------------------
# Group 1 -- ExecutionCoordinatorError
# ---------------------------------------------------------------------------
def scenario_execution_coordinator_error_is_agent_error() -> None:
    check(
        issubclass(ExecutionCoordinatorError, AgentError),
        "I12: ExecutionCoordinatorError subclasses Core.exceptions.AgentError, "
        "same convention as ExecutionPlannerError/ExecutionIntentError/"
        "PolicyGuardError/DecisionPolicyError/DecisionEngineError/"
        "ReflectionError",
    )
    err = ExecutionCoordinatorError("boom")
    check(isinstance(err, Exception), "ExecutionCoordinatorError is constructible with a plain message")


# ---------------------------------------------------------------------------
# Group 2 -- ExecutionCoordinatorResult (value shape) -- I10, I11
# ---------------------------------------------------------------------------
def scenario_result_is_frozen_dataclass() -> None:
    result = ExecutionCoordinator().coordinate(_FakeExecutionPlan())

    check(dataclasses.is_dataclass(result), "ExecutionCoordinatorResult is a dataclass")

    frozen = False
    try:
        result.coordinated = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(
        frozen,
        "I10: ExecutionCoordinatorResult is frozen -- field reassignment "
        "raises FrozenInstanceError",
    )


def scenario_result_has_expected_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(ExecutionCoordinatorResult)}
    check(
        field_names
        == {
            "coordinated",
            "action",
            "risk_level",
            "position_size",
            "sequence_position",
            "hold_reason",
            "notes",
        },
        "I11: ExecutionCoordinatorResult declares exactly seven fields "
        "(coordinated, action, risk_level, position_size, "
        "sequence_position, hold_reason, notes)",
    )


# ---------------------------------------------------------------------------
# Group 3 -- planned execution plan -- I1, I2
# ---------------------------------------------------------------------------
def scenario_planned_buy_is_coordinated_with_empty_hold_reason() -> None:
    result = ExecutionCoordinator().coordinate(
        _FakeExecutionPlan(planned=True, action="BUY", risk_level="NORMAL", position_size=1.0)
    )
    check(
        result.coordinated is True and result.hold_reason == "",
        "I1: a planned BUY execution plan produces coordinated=True and "
        "an empty hold_reason",
    )


def scenario_planned_fields_are_preserved() -> None:
    result = ExecutionCoordinator().coordinate(
        _FakeExecutionPlan(planned=True, action="HOLD", risk_level="LOW", position_size=0.5)
    )
    check(
        result.action == "HOLD" and result.risk_level == "LOW" and result.position_size == 0.5,
        "I2: a coordinated result's action/risk_level/position_size are "
        "carried through unchanged",
    )


# ---------------------------------------------------------------------------
# Group 4 -- not-planned execution plan -- I3, I4
# ---------------------------------------------------------------------------
def scenario_not_planned_result_is_not_coordinated() -> None:
    result = ExecutionCoordinator().coordinate(
        _FakeExecutionPlan(planned=False, skip_reason="some reason")
    )
    check(result.coordinated is False, "I3: a not-planned execution plan produces coordinated=False")


def scenario_not_planned_hold_reason_matches_skip_reason() -> None:
    result = ExecutionCoordinator().coordinate(
        _FakeExecutionPlan(planned=False, skip_reason="policy guard result was not approved")
    )
    check(
        result.hold_reason == "policy guard result was not approved",
        "I4: a not-planned result's hold_reason is taken from the plan's "
        "own skip_reason unchanged",
    )


# ---------------------------------------------------------------------------
# Group 5 -- not-planned result preserves fields -- I5
# ---------------------------------------------------------------------------
def scenario_not_planned_fields_are_still_preserved() -> None:
    result = ExecutionCoordinator().coordinate(
        _FakeExecutionPlan(
            planned=False,
            action="SELL",
            risk_level="HIGH",
            position_size=0.0,
            skip_reason="execution intent was not ready",
        )
    )
    check(
        result.action == "SELL" and result.risk_level == "HIGH" and result.position_size == 0.0,
        "I5: a not-planned result's action/risk_level/position_size are "
        "still carried through unchanged, never zeroed or substituted",
    )


# ---------------------------------------------------------------------------
# Group 6 -- empty skip_reason fallback -- I6
# ---------------------------------------------------------------------------
def scenario_not_planned_with_empty_skip_reason_uses_generic_fallback() -> None:
    result = ExecutionCoordinator().coordinate(
        _FakeExecutionPlan(planned=False, skip_reason="")
    )
    check(
        result.hold_reason == "execution plan was not planned",
        "I6: a not-planned plan with an empty skip_reason falls back "
        "to a generic hold_reason rather than an empty string",
    )


def scenario_empty_skip_reason_fallback_is_not_blank() -> None:
    result = ExecutionCoordinator().coordinate(
        _FakeExecutionPlan(planned=False, skip_reason="")
    )
    check(
        len(result.hold_reason) > 0,
        "I6: the generic fallback hold_reason is non-empty",
    )


# ---------------------------------------------------------------------------
# Group 7 -- notes content -- I7, I8
# ---------------------------------------------------------------------------
def scenario_notes_contains_action_name_when_coordinated() -> None:
    result = ExecutionCoordinator().coordinate(_FakeExecutionPlan(planned=True, action="BUY"))
    check(
        "BUY" in result.notes,
        "I7: notes contains the action name ('BUY') for a coordinated result",
    )


def scenario_notes_contains_action_name_when_held() -> None:
    result = ExecutionCoordinator().coordinate(
        _FakeExecutionPlan(planned=False, action="SELL", skip_reason="bad")
    )
    check(
        "SELL" in result.notes,
        "I7: notes contains the action name ('SELL') for a held result",
    )


def scenario_notes_contains_hold_reason_when_held() -> None:
    result = ExecutionCoordinator().coordinate(
        _FakeExecutionPlan(planned=False, skip_reason="specific reason")
    )
    check(
        "specific reason" in result.notes,
        "I8: notes contains the hold_reason text for a held result",
    )


# ---------------------------------------------------------------------------
# Group 8 -- missing attribute -- I9
# ---------------------------------------------------------------------------
def scenario_missing_attribute_raises_execution_coordinator_error() -> None:
    raised_type = None
    try:
        ExecutionCoordinator().coordinate(_ExecutionPlanMissingField())
    except ExecutionCoordinatorError:
        raised_type = ExecutionCoordinatorError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is ExecutionCoordinatorError,
        "I9: ExecutionCoordinator.coordinate() raises "
        "ExecutionCoordinatorError (not AttributeError) when the "
        "execution plan object is missing a required attribute "
        "('skip_reason')",
    )


# ---------------------------------------------------------------------------
# Group 9 -- statelessness / determinism -- I13
# ---------------------------------------------------------------------------
def scenario_execution_coordinator_has_no_instance_attributes() -> None:
    coordinator = ExecutionCoordinator()
    check(
        vars(coordinator) == {},
        "I13: an ExecutionCoordinator instance holds no instance "
        "attributes (vars() is empty), confirming it is safe to reuse "
        "across calls",
    )


def scenario_execution_coordinator_is_deterministic() -> None:
    coordinator = ExecutionCoordinator()
    first = coordinator.coordinate(_FakeExecutionPlan(planned=True, action="HOLD", position_size=0.5))
    second = coordinator.coordinate(_FakeExecutionPlan(planned=True, action="HOLD", position_size=0.5))

    check(
        first == second,
        "I13: ExecutionCoordinator.coordinate() is deterministic -- the "
        "same input execution plan always produces an equal "
        "ExecutionCoordinatorResult",
    )


# ---------------------------------------------------------------------------
# Group 10 -- consistency across actions -- I14
# ---------------------------------------------------------------------------
def scenario_all_actions_coordinated_when_planned() -> None:
    coordinator = ExecutionCoordinator()
    all_coordinated = all(
        coordinator.coordinate(_FakeExecutionPlan(planned=True, action=action)).coordinated is True
        for action in ("BUY", "HOLD", "SELL")
    )
    check(
        all_coordinated,
        "I14: BUY, HOLD, and SELL all produce coordinated=True when planned",
    )


def scenario_all_actions_held_when_not_planned() -> None:
    coordinator = ExecutionCoordinator()
    all_held = all(
        coordinator.coordinate(
            _FakeExecutionPlan(planned=False, action=action, skip_reason="x")
        ).coordinated
        is False
        for action in ("BUY", "HOLD", "SELL")
    )
    check(
        all_held,
        "I14: BUY, HOLD, and SELL all produce coordinated=False when not planned",
    )


# ---------------------------------------------------------------------------
# Group 11 -- sequence_position -- I16
# ---------------------------------------------------------------------------
def scenario_coordinated_result_has_sequence_position_one() -> None:
    result = ExecutionCoordinator().coordinate(_FakeExecutionPlan(planned=True))
    check(
        result.sequence_position == 1,
        "I16: a coordinated result has sequence_position=1",
    )


def scenario_held_result_has_sequence_position_zero() -> None:
    result = ExecutionCoordinator().coordinate(_FakeExecutionPlan(planned=False, skip_reason="x"))
    check(
        result.sequence_position == 0,
        "I16: a held result has sequence_position=0",
    )


# ---------------------------------------------------------------------------
# Group 12 -- composition root wiring smoke check -- I15
# ---------------------------------------------------------------------------
def scenario_composition_root_exposes_execution_coordinator() -> None:
    from Core.composition_root import build_application

    graph = build_application()
    check(
        isinstance(graph.execution_coordinator, ExecutionCoordinator),
        "I15: Core.composition_root.build_application() exposes an "
        "ExecutionCoordinator instance on "
        "ApplicationGraph.execution_coordinator",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_execution_coordinator_error_is_agent_error,
        # Group 2
        scenario_result_is_frozen_dataclass,
        scenario_result_has_expected_fields,
        # Group 3
        scenario_planned_buy_is_coordinated_with_empty_hold_reason,
        scenario_planned_fields_are_preserved,
        # Group 4
        scenario_not_planned_result_is_not_coordinated,
        scenario_not_planned_hold_reason_matches_skip_reason,
        # Group 5
        scenario_not_planned_fields_are_still_preserved,
        # Group 6
        scenario_not_planned_with_empty_skip_reason_uses_generic_fallback,
        scenario_empty_skip_reason_fallback_is_not_blank,
        # Group 7
        scenario_notes_contains_action_name_when_coordinated,
        scenario_notes_contains_action_name_when_held,
        scenario_notes_contains_hold_reason_when_held,
        # Group 8
        scenario_missing_attribute_raises_execution_coordinator_error,
        # Group 9
        scenario_execution_coordinator_has_no_instance_attributes,
        scenario_execution_coordinator_is_deterministic,
        # Group 10
        scenario_all_actions_coordinated_when_planned,
        scenario_all_actions_held_when_not_planned,
        # Group 11
        scenario_coordinated_result_has_sequence_position_one,
        scenario_held_result_has_sequence_position_zero,
        # Group 12
        scenario_composition_root_exposes_execution_coordinator,
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
    print(f"STAGE L24 EXECUTION COORDINATOR RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())