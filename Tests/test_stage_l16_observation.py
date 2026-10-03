"""
Stage L16 proof suite -- Observation Layer (Phase 2, milestone: regression
suite).

Scope: dedicated regression suite for
``Orchestration.observation.Observation``,
``Orchestration.observation.StepObservation``,
``Orchestration.observation.ObservationError``, and
``Orchestration.observation.ObservationRecorder`` only. Verifies the
implementation completed in the previous milestone. No new Observation
features, no ObservationStore, no persistence, no query API, no Runtime/
Planner/Composition-Root wiring -- all explicitly out of scope for L16
Phase 2 (locked).

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l11_runtime_analysis_pipeline.py`` /
``test_stage_l12_production_runtime_activation.py`` /
``test_stage_l13_service_skill.py`` / ``test_stage_l15_planner.py``: a
global pass/fail counter, plain ``Goal``/``ExecutionPlan``/``PlanStep``/
``ServiceResult`` fixtures (no fakes needed here -- ``ObservationRecorder``
has no Service/Skill/Planner dependency to fake out), and a ``main()``
runner.

Explicitly NOT tested here (belongs to other stages / other milestones):
Runtime, Executor, Sandbox, ToolRegistry, Observation *persistence* or
*querying* (no ObservationStore exists yet), Memory, Reflection,
StockAgent, RuntimeAnalysisPipeline, AnalysisPipeline, GoalPlanner's own
behavior (already covered by ``test_stage_l15_planner.py`` -- this file
only checks that ``ObservationRecorder`` consumes ``Goal``/
``ExecutionPlan``/``List[ServiceResult]`` correctly, not that
``GoalPlanner`` builds/executes plans correctly).
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
from Orchestration.observation import (
    Observation,
    ObservationError,
    ObservationRecorder,
    StepObservation,
)
from Orchestration.planner import ExecutionPlan, Goal, PlanStep
from Services.service_result import ServiceResult

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


# Forbidden verbs for any public, non-property attribute on Observation /
# StepObservation -- the locked "append-only, no mutation APIs" constraint.
_MUTATION_VERBS = (
    "update",
    "append",
    "merge",
    "rewrite",
    "set_",
    "add_",
    "insert",
    "remove",
    "delete",
    "mutate",
    "clear",
    "extend",
    "pop",
)


# ---------------------------------------------------------------------------
# Group 1 -- ObservationError
# ---------------------------------------------------------------------------
def scenario_observation_error_is_agent_error() -> None:
    check(
        issubclass(ObservationError, AgentError),
        "ObservationError subclasses Core.exceptions.AgentError, same convention "
        "as GoalPlannerError/PlannerError",
    )

    err = ObservationError("boom", details={"x": 1})
    check(err.message == "boom" and err.details == {"x": 1}, "ObservationError carries message/details")


# ---------------------------------------------------------------------------
# Group 2 -- StepObservation (value shape)
# ---------------------------------------------------------------------------
def scenario_step_observation_is_frozen_value_object() -> None:
    step = StepObservation(
        order=0,
        service_name="a",
        required_inputs=("x",),
        success=True,
        message="ok",
        data={"x": 1},
        error_message=None,
        execution_time_ms=1.0,
        result_metadata={},
    )

    check(dataclasses.is_dataclass(step), "StepObservation is a dataclass")

    frozen = False
    try:
        step.success = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(frozen, "StepObservation is frozen -- field reassignment raises FrozenInstanceError")

    check(
        not [m for m in dir(step) if not m.startswith("_") and callable(getattr(step, m))],
        "StepObservation exposes zero public methods (no mutation surface at all)",
    )


# ---------------------------------------------------------------------------
# Group 3 -- Observation (value shape, read-only surface, append-only)
# ---------------------------------------------------------------------------
def _empty_observation() -> Observation:
    return ObservationRecorder().record(
        goal=Goal(metadata={}),
        plan=ExecutionPlan(goal=Goal(metadata={}), steps=()),
        results=[],
    )


def scenario_observation_is_frozen() -> None:
    obs = _empty_observation()
    check(dataclasses.is_dataclass(obs), "Observation is a dataclass")

    frozen = False
    try:
        obs.steps = ()  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(frozen, "Observation is frozen -- field reassignment raises FrozenInstanceError")


def scenario_observation_exposes_no_mutation_api() -> None:
    obs = _empty_observation()
    public_callables = [
        m
        for m in dir(obs)
        if not m.startswith("_") and callable(getattr(obs, m))
    ]

    check(
        set(public_callables) == set(),
        "Observation's only public, non-dunder members are read-only @property values "
        "(step_count, all_succeeded, failed_service_names), not callables",
    )

    public_members = [m for m in dir(obs) if not m.startswith("_")]
    offending = [
        m for m in public_members if any(verb in m.lower() for verb in _MUTATION_VERBS)
    ]
    check(
        offending == [],
        "Observation exposes no member whose name suggests a mutation API "
        "(update/append/merge/rewrite/set/add/insert/remove/delete/mutate/clear/extend/pop)",
    )


def scenario_observation_properties_are_read_only_views() -> None:
    a_result = ServiceResult.ok(data={"x": 1})
    b_result = ServiceResult.fail(error=ValueError("nope"))
    plan = ExecutionPlan(
        goal=Goal(metadata={}),
        steps=(PlanStep(service_name="a"), PlanStep(service_name="b")),
    )
    obs = ObservationRecorder().record(Goal(metadata={}), plan, [a_result, b_result])

    check(obs.step_count == 2, "Observation.step_count reflects number of recorded steps")
    check(obs.all_succeeded is False, "Observation.all_succeeded is False when any step failed")
    check(
        obs.failed_service_names == ("b",),
        "Observation.failed_service_names lists only the failed steps, in order",
    )


def scenario_observation_empty_plan_all_succeeded_vacuously_true() -> None:
    obs = _empty_observation()
    check(obs.step_count == 0, "an empty plan produces a zero-step Observation")
    check(
        obs.all_succeeded is True,
        "Observation.all_succeeded is vacuously True for a zero-step Observation "
        "(matches GoalPlanner.execute_plan([]) returning [])",
    )
    check(obs.failed_service_names == (), "no failed_service_names for an empty plan")


def scenario_observation_recorded_at_is_a_float_timestamp() -> None:
    obs = _empty_observation()
    check(
        isinstance(obs.recorded_at, float) and obs.recorded_at > 0,
        "Observation.recorded_at is a plain float epoch timestamp, not a live clock/object",
    )


# ---------------------------------------------------------------------------
# Group 4 -- ObservationRecorder.record(): ordering, aggregation, telemetry
# ---------------------------------------------------------------------------
def scenario_record_preserves_execution_order() -> None:
    plan = ExecutionPlan(
        goal=Goal(metadata={}),
        steps=(
            PlanStep(service_name="first"),
            PlanStep(service_name="second"),
            PlanStep(service_name="third"),
        ),
    )
    results = [ServiceResult.ok(data={}) for _ in range(3)]
    obs = ObservationRecorder().record(Goal(metadata={}), plan, results)

    check(
        obs.plan_step_names == ("first", "second", "third"),
        "Observation.plan_step_names preserves the ExecutionPlan's step order",
    )
    check(
        [s.service_name for s in obs.steps] == ["first", "second", "third"],
        "Observation.steps preserves execution order",
    )
    check(
        [s.order for s in obs.steps] == [0, 1, 2],
        "each StepObservation.order matches its zero-based position in the plan",
    )


def scenario_record_preserves_required_inputs() -> None:
    plan = ExecutionPlan(
        goal=Goal(metadata={}),
        steps=(PlanStep(service_name="a", inputs=("in1", "in2")),),
    )
    obs = ObservationRecorder().record(Goal(metadata={}), plan, [ServiceResult.ok(data={})])

    check(
        obs.steps[0].required_inputs == ("in1", "in2"),
        "StepObservation.required_inputs carries PlanStep.inputs verbatim",
    )


def scenario_record_success_and_message_carried_through() -> None:
    plan = ExecutionPlan(goal=Goal(metadata={}), steps=(PlanStep(service_name="a"),))
    result = ServiceResult.ok(data={}, message="all good")
    obs = ObservationRecorder().record(Goal(metadata={}), plan, [result])

    step = obs.steps[0]
    check(step.success is True, "StepObservation.success carries ServiceResult.success")
    check(step.message == "all good", "StepObservation.message carries ServiceResult.message")


def scenario_record_error_message_is_string_not_exception() -> None:
    plan = ExecutionPlan(goal=Goal(metadata={}), steps=(PlanStep(service_name="a"),))
    original_error = ValueError("simulated failure")
    result = ServiceResult.fail(error=original_error)
    obs = ObservationRecorder().record(Goal(metadata={}), plan, [result])

    step = obs.steps[0]
    check(
        isinstance(step.error_message, str) and step.error_message == str(original_error),
        "StepObservation.error_message is a str() rendering of the ServiceResult's error",
    )
    check(
        not isinstance(step.error_message, Exception),
        "StepObservation.error_message is never the live Exception object itself",
    )
    check(
        not any(
            f.name == "error" or f.type is Exception
            for f in dataclasses.fields(StepObservation)
        ),
        "StepObservation has no field that could hold a raw Exception instance",
    )


def scenario_record_no_error_message_when_no_error() -> None:
    plan = ExecutionPlan(goal=Goal(metadata={}), steps=(PlanStep(service_name="a"),))
    obs = ObservationRecorder().record(Goal(metadata={}), plan, [ServiceResult.ok(data={})])

    check(
        obs.steps[0].error_message is None,
        "StepObservation.error_message is None when the ServiceResult carried no error",
    )


def scenario_record_execution_time_carried_through() -> None:
    plan = ExecutionPlan(goal=Goal(metadata={}), steps=(PlanStep(service_name="a"),))
    result = ServiceResult.ok(data={}, execution_time_ms=42.5)
    obs = ObservationRecorder().record(Goal(metadata={}), plan, [result])

    check(
        obs.steps[0].execution_time_ms == 42.5,
        "StepObservation.execution_time_ms carries ServiceResult.execution_time_ms verbatim "
        "(Observation does not measure timing itself)",
    )


def scenario_record_aggregation_later_key_wins() -> None:
    plan = ExecutionPlan(
        goal=Goal(metadata={}),
        steps=(PlanStep(service_name="a"), PlanStep(service_name="b")),
    )
    results = [
        ServiceResult.ok(data={"shared": "old", "only_a": 1}),
        ServiceResult.ok(data={"shared": "new", "only_b": 2}),
    ]
    obs = ObservationRecorder().record(Goal(metadata={}), plan, results)

    check(
        obs.aggregated_outputs == {"shared": "new", "only_a": 1, "only_b": 2},
        "Observation.aggregated_outputs merges successful steps' dict data, later-key-wins "
        "(same semantics as GoalPlanner.accumulate_context)",
    )


def scenario_record_aggregation_ignores_failed_and_non_dict() -> None:
    plan = ExecutionPlan(
        goal=Goal(metadata={}),
        steps=(
            PlanStep(service_name="a"),
            PlanStep(service_name="b"),
            PlanStep(service_name="c"),
        ),
    )
    results = [
        ServiceResult.ok(data={"kept": 1}),
        ServiceResult.fail(error=ValueError("nope")),
        ServiceResult.ok(data="not-a-dict"),
    ]
    obs = ObservationRecorder().record(Goal(metadata={}), plan, results)

    check(
        obs.aggregated_outputs == {"kept": 1},
        "Observation.aggregated_outputs ignores a failed step's data and a non-dict "
        "successful result's data",
    )


def scenario_record_data_is_shallow_copied_when_dict() -> None:
    original_data = {"a": 1}
    plan = ExecutionPlan(goal=Goal(metadata={}), steps=(PlanStep(service_name="x"),))
    result = ServiceResult.ok(data=original_data)
    obs = ObservationRecorder().record(Goal(metadata={}), plan, [result])

    check(
        obs.steps[0].data == original_data and obs.steps[0].data is not original_data,
        "StepObservation.data is a shallow copy of dict-shaped ServiceResult.data, not the "
        "same object",
    )

    original_data["a"] = 999
    check(
        obs.steps[0].data == {"a": 1},
        "mutating the caller's original data dict after recording does not affect the "
        "already-recorded Observation",
    )


def scenario_record_non_dict_data_passed_through() -> None:
    plan = ExecutionPlan(goal=Goal(metadata={}), steps=(PlanStep(service_name="x"),))
    result = ServiceResult.ok(data="a plain string payload")
    obs = ObservationRecorder().record(Goal(metadata={}), plan, [result])

    check(
        obs.steps[0].data == "a plain string payload",
        "StepObservation.data carries a non-dict payload through as-is (Observation does "
        "not reshape a Service's own domain payload)",
    )


def scenario_record_goal_metadata_is_shallow_copy() -> None:
    original_metadata = {"ticker": "BBCA.JK"}
    goal = Goal(metadata=original_metadata)
    plan = ExecutionPlan(goal=goal, steps=())
    obs = ObservationRecorder().record(goal, plan, [])

    check(
        obs.goal_metadata == original_metadata and obs.goal_metadata is not goal.metadata,
        "Observation.goal_metadata is a shallow copy of Goal.metadata, not the same dict "
        "object",
    )


def scenario_record_does_not_mutate_inputs() -> None:
    goal = Goal(metadata={"a": 1})
    plan = ExecutionPlan(goal=goal, steps=(PlanStep(service_name="x"),))
    result = ServiceResult.ok(data={"b": 2})
    results = [result]

    goal_metadata_snapshot = dict(goal.metadata)
    result_data_snapshot = dict(result.data)

    ObservationRecorder().record(goal, plan, results)

    check(goal.metadata == goal_metadata_snapshot, "record() never mutates the Goal it was given")
    check(
        result.data == result_data_snapshot,
        "record() never mutates a ServiceResult's data",
    )
    check(len(plan.steps) == 1, "record() never mutates the ExecutionPlan it was given")


def scenario_record_mismatched_length_raises_observation_error() -> None:
    plan = ExecutionPlan(
        goal=Goal(metadata={}),
        steps=(PlanStep(service_name="a"), PlanStep(service_name="b")),
    )
    raised = False
    try:
        ObservationRecorder().record(Goal(metadata={}), plan, [ServiceResult.ok(data={})])
    except ObservationError:
        raised = True
    check(
        raised,
        "record() raises ObservationError when results length does not match plan.steps length",
    )


def scenario_record_empty_plan_is_valid_not_an_error() -> None:
    raised = False
    obs = None
    try:
        obs = ObservationRecorder().record(
            Goal(metadata={}), ExecutionPlan(goal=Goal(metadata={}), steps=()), []
        )
    except ObservationError:
        raised = True
    check(
        not raised and obs is not None and obs.step_count == 0,
        "record() treats an empty plan (steps=(), results=[]) as valid, not an error",
    )


# ---------------------------------------------------------------------------
# Group 5 -- ObservationRecorder itself
# ---------------------------------------------------------------------------
def scenario_recorder_holds_no_collaborator_state() -> None:
    recorder = ObservationRecorder()
    check(
        vars(recorder) == {},
        "ObservationRecorder holds no instance state -- no GoalPlanner/ServiceSkill/Service "
        "reference of any kind",
    )


def scenario_recorder_is_reusable_and_stateless_across_calls() -> None:
    recorder = ObservationRecorder()
    plan = ExecutionPlan(goal=Goal(metadata={}), steps=(PlanStep(service_name="a"),))

    obs1 = recorder.record(Goal(metadata={}), plan, [ServiceResult.ok(data={"x": 1})])
    obs2 = recorder.record(Goal(metadata={}), plan, [ServiceResult.ok(data={"x": 2})])

    check(
        obs1.aggregated_outputs == {"x": 1} and obs2.aggregated_outputs == {"x": 2},
        "the same ObservationRecorder instance produces independent, correct Observations "
        "across repeated calls (no leaked state between calls)",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_observation_error_is_agent_error,
        # Group 2
        scenario_step_observation_is_frozen_value_object,
        # Group 3
        scenario_observation_is_frozen,
        scenario_observation_exposes_no_mutation_api,
        scenario_observation_properties_are_read_only_views,
        scenario_observation_empty_plan_all_succeeded_vacuously_true,
        scenario_observation_recorded_at_is_a_float_timestamp,
        # Group 4
        scenario_record_preserves_execution_order,
        scenario_record_preserves_required_inputs,
        scenario_record_success_and_message_carried_through,
        scenario_record_error_message_is_string_not_exception,
        scenario_record_no_error_message_when_no_error,
        scenario_record_execution_time_carried_through,
        scenario_record_aggregation_later_key_wins,
        scenario_record_aggregation_ignores_failed_and_non_dict,
        scenario_record_data_is_shallow_copied_when_dict,
        scenario_record_non_dict_data_passed_through,
        scenario_record_goal_metadata_is_shallow_copy,
        scenario_record_does_not_mutate_inputs,
        scenario_record_mismatched_length_raises_observation_error,
        scenario_record_empty_plan_is_valid_not_an_error,
        # Group 5
        scenario_recorder_holds_no_collaborator_state,
        scenario_recorder_is_reusable_and_stateless_across_calls,
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
    print(f"STAGE L16 OBSERVATION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())