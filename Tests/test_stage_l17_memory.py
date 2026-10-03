"""
Stage L17 proof suite -- Memory (Phase 1-3, milestone: regression suite).

Scope: dedicated regression suite for ``Orchestration.memory.MemoryError``,
``Orchestration.memory.MemoryRecord``, ``Orchestration.memory.MemoryStore``,
and ``Orchestration.memory.MemoryRecorder`` only. Verifies the
implementation completed in previous milestones. No new Memory features,
no retrieval/query API, no persistence, no Runtime/Planner/Composition-Root
wiring -- all explicitly out of scope for L17 (locked).

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l11_runtime_analysis_pipeline.py`` /
``test_stage_l12_production_runtime_activation.py`` /
``test_stage_l13_service_skill.py`` / ``test_stage_l15_planner.py`` /
``test_stage_l16_observation.py``: a global pass/fail counter, plain
``Goal``/``ExecutionPlan``/``PlanStep``/``ServiceResult``/``Observation``
fixtures (no fakes needed here -- ``MemoryRecorder`` has no Service/
Skill/Planner dependency to fake out, only a ``MemoryStore``), and a
``main()`` runner.

Explicitly NOT tested here (belongs to other stages / other milestones):
Runtime, Executor, Sandbox, ToolRegistry, Reflection, StockAgent,
RuntimeAnalysisPipeline, AnalysisPipeline, GoalPlanner's own behavior
(covered by ``test_stage_l15_planner.py``), ObservationRecorder's own
behavior (covered by ``test_stage_l16_observation.py`` -- this file only
checks that Memory consumes an already-built ``Observation`` correctly,
not that ``ObservationRecorder`` builds it correctly). No Memory
persistence beyond the in-process ``MemoryStore``, no Composition Root
wiring, no retrieval/ranking/search API.
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
from Orchestration.memory import (
    MemoryError,
    MemoryRecord,
    MemoryRecorder,
    MemoryStore,
)
from Orchestration.observation import Observation, ObservationRecorder
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


def _empty_observation() -> Observation:
    return ObservationRecorder().record(
        goal=Goal(metadata={}),
        plan=ExecutionPlan(goal=Goal(metadata={}), steps=()),
        results=[],
    )


def _observation_with_steps() -> Observation:
    plan = ExecutionPlan(
        goal=Goal(metadata={"ticker": "BBCA.JK"}),
        steps=(PlanStep(service_name="a"), PlanStep(service_name="b")),
    )
    results = [
        ServiceResult.ok(data={"price": 100}),
        ServiceResult.fail(error=ValueError("nope")),
    ]
    return ObservationRecorder().record(Goal(metadata={"ticker": "BBCA.JK"}), plan, results)


# ---------------------------------------------------------------------------
# Group 1 -- MemoryError
# ---------------------------------------------------------------------------
def scenario_memory_error_is_agent_error() -> None:
    check(
        issubclass(MemoryError, AgentError),
        "MemoryError subclasses Core.exceptions.AgentError, same convention "
        "as GoalPlannerError/ObservationError",
    )

    err = MemoryError("boom", details={"x": 1})
    check(err.message == "boom" and err.details == {"x": 1}, "MemoryError carries message/details")


def scenario_memory_error_details_default_to_empty_dict() -> None:
    err = MemoryError("boom")
    check(err.details == {}, "MemoryError.details defaults to an empty dict when not given")


# ---------------------------------------------------------------------------
# Group 2 -- MemoryRecord (value shape)
# ---------------------------------------------------------------------------
def scenario_memory_record_is_frozen_dataclass() -> None:
    obs = _empty_observation()
    record = MemoryRecord(observation=obs)

    check(dataclasses.is_dataclass(record), "MemoryRecord is a dataclass")

    frozen = False
    try:
        record.record_id = "other"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(frozen, "MemoryRecord is frozen -- field reassignment raises FrozenInstanceError")


def scenario_memory_record_wraps_observation_unmodified() -> None:
    obs = _observation_with_steps()
    record = MemoryRecord(observation=obs)

    check(
        record.observation is obs,
        "MemoryRecord.observation holds the exact Observation instance it was given, "
        "not a copy",
    )


def scenario_memory_record_id_is_fresh_uuid_per_instance() -> None:
    obs = _empty_observation()
    record1 = MemoryRecord(observation=obs)
    record2 = MemoryRecord(observation=obs)

    check(
        isinstance(record1.record_id, str) and len(record1.record_id) > 0,
        "MemoryRecord.record_id is a non-empty string",
    )
    check(
        record1.record_id != record2.record_id,
        "each MemoryRecord constructed gets its own fresh, unique record_id "
        "(default_factory=uuid4)",
    )


def scenario_memory_record_recorded_at_is_float_timestamp() -> None:
    obs = _empty_observation()
    record = MemoryRecord(observation=obs)

    check(
        isinstance(record.recorded_at, float) and record.recorded_at > 0,
        "MemoryRecord.recorded_at is a plain float epoch timestamp",
    )


def scenario_memory_record_recorded_at_distinct_from_observation_recorded_at() -> None:
    obs = _empty_observation()
    record = MemoryRecord(observation=obs)

    check(
        hasattr(record, "recorded_at") and hasattr(record.observation, "recorded_at"),
        "MemoryRecord.recorded_at and Observation.recorded_at are two distinct fields "
        "(when the Observation was built vs. when it was memorized), never conflated "
        "into one",
    )


def scenario_memory_record_construction_is_single_call_no_helper() -> None:
    # LOCKED design constraint: record_id/recorded_at come from the dataclass's
    # own field(default_factory=...), so a plain MemoryRecord(observation=...)
    # call is always enough -- no external id/timestamp helper is required.
    obs = _empty_observation()
    record = MemoryRecord(observation=obs)

    check(
        record.record_id is not None and record.recorded_at is not None,
        "MemoryRecord(observation=...) alone is sufficient to produce a fully "
        "populated record_id and recorded_at, with no extra helper call",
    )


# ---------------------------------------------------------------------------
# Group 3 -- MemoryStore
# ---------------------------------------------------------------------------
def scenario_store_starts_empty() -> None:
    store = MemoryStore()
    check(len(store) == 0, "a fresh MemoryStore starts empty (__len__ == 0)")
    check(store.list() == (), "a fresh MemoryStore.list() returns an empty tuple")


def scenario_store_add_and_get_round_trip() -> None:
    store = MemoryStore()
    record = MemoryRecord(observation=_empty_observation())
    store.add(record)

    check(len(store) == 1, "MemoryStore.add() increments the store's length")
    check(
        store.get(record.record_id) is record,
        "MemoryStore.get(record_id) returns the exact same MemoryRecord instance "
        "that was added",
    )


def scenario_store_get_missing_id_returns_none_not_error() -> None:
    store = MemoryStore()
    result = store.get("does-not-exist")
    check(
        result is None,
        "MemoryStore.get() with an unknown record_id returns None, not an error "
        "(a lookup miss is a normal, expected outcome)",
    )


def scenario_store_add_duplicate_record_id_raises_memory_error() -> None:
    store = MemoryStore()
    obs = _empty_observation()
    record = MemoryRecord(observation=obs)
    store.add(record)

    # Build a second record forced to share the same record_id, to exercise
    # the collision path deterministically (real MemoryRecord ids are unique
    # by construction, so we bypass that only to prove the guard exists).
    duplicate = dataclasses.replace(MemoryRecord(observation=obs), record_id=record.record_id)

    raised = False
    try:
        store.add(duplicate)
    except MemoryError:
        raised = True
    check(
        raised,
        "MemoryStore.add() raises MemoryError when a record with the same "
        "record_id is already stored",
    )
    check(len(store) == 1, "a rejected duplicate add() does not change the store's length")


def scenario_store_list_returns_insertion_order() -> None:
    store = MemoryStore()
    r1 = MemoryRecord(observation=_empty_observation())
    r2 = MemoryRecord(observation=_empty_observation())
    r3 = MemoryRecord(observation=_empty_observation())
    store.add(r1)
    store.add(r2)
    store.add(r3)

    check(
        store.list() == (r1, r2, r3),
        "MemoryStore.list() returns every stored MemoryRecord as a tuple, in the "
        "order they were added",
    )


def scenario_store_list_returns_fresh_snapshot_not_live_reference() -> None:
    store = MemoryStore()
    store.add(MemoryRecord(observation=_empty_observation()))

    snapshot = store.list()
    check(isinstance(snapshot, tuple), "MemoryStore.list() returns a tuple, not a dict/view")

    store.add(MemoryRecord(observation=_empty_observation()))
    check(
        len(snapshot) == 1,
        "a previously taken MemoryStore.list() snapshot is unaffected by a later add() "
        "-- it never shares live state with the store's internal dict",
    )


def scenario_store_clear_empties_the_store() -> None:
    store = MemoryStore()
    store.add(MemoryRecord(observation=_empty_observation()))
    store.add(MemoryRecord(observation=_empty_observation()))
    store.clear()

    check(len(store) == 0, "MemoryStore.clear() empties the store (__len__ == 0)")
    check(store.list() == (), "MemoryStore.clear() leaves list() returning an empty tuple")


def scenario_store_no_dependencies_at_construction() -> None:
    store = MemoryStore()
    check(
        vars(store) == {"_records": {}, "_max_size": None, "_ttl_seconds": None},
        "MemoryStore is constructed with no required arguments and holds only its own "
        "private _records dict plus its (default-disabled) retention config -- no "
        "Service/ServiceSkill/GoalPlanner/Runtime reference",
    )


# ---------------------------------------------------------------------------
# Group 4 -- MemoryRecorder
# ---------------------------------------------------------------------------
def scenario_recorder_holds_only_the_store_it_was_given() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store)

    check(
        vars(recorder) == {"_store": store},
        "MemoryRecorder holds exactly one collaborator, the MemoryStore it was "
        "constructed with -- no other state",
    )


def scenario_recorder_record_wraps_and_returns_memory_record() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store)
    obs = _observation_with_steps()

    result = recorder.record(obs)

    check(isinstance(result, MemoryRecord), "MemoryRecorder.record() returns a MemoryRecord")
    check(
        result.observation is obs,
        "MemoryRecorder.record() wraps the exact Observation instance it was given, "
        "unmodified",
    )


def scenario_recorder_record_inserts_into_the_store() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store)
    obs = _empty_observation()

    record = recorder.record(obs)

    check(len(store) == 1, "MemoryRecorder.record() inserts exactly one record into the store")
    check(
        store.get(record.record_id) is record,
        "the MemoryRecord returned by MemoryRecorder.record() is the same instance "
        "retrievable from the store afterward",
    )


def scenario_recorder_returns_same_instance_that_was_stored() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store)
    obs = _empty_observation()

    record = recorder.record(obs)

    check(
        store.list() == (record,),
        "MemoryRecorder.record() returns the same MemoryRecord instance that ends up "
        "in the store's list(), not a separate copy",
    )


def scenario_recorder_does_not_mutate_observation() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store)
    obs = _observation_with_steps()

    goal_metadata_snapshot = dict(obs.goal_metadata)
    step_count_snapshot = obs.step_count

    recorder.record(obs)

    check(
        obs.goal_metadata == goal_metadata_snapshot,
        "MemoryRecorder.record() never mutates the Observation's goal_metadata",
    )
    check(
        obs.step_count == step_count_snapshot,
        "MemoryRecorder.record() never mutates the Observation's steps",
    )


def scenario_recorder_is_reusable_across_calls() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store)

    record1 = recorder.record(_empty_observation())
    record2 = recorder.record(_empty_observation())

    check(
        record1.record_id != record2.record_id,
        "the same MemoryRecorder instance produces independent MemoryRecords with "
        "distinct record_ids across repeated calls",
    )
    check(len(store) == 2, "both records from repeated MemoryRecorder.record() calls land in the store")


def scenario_recorder_propagates_store_collision_unmodified() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store)
    obs = _empty_observation()

    # Pre-seed the store with a record sharing the id MemoryRecorder would
    # otherwise mint, to force MemoryStore.add()'s collision guard to fire
    # from inside MemoryRecorder.record() -- proving the exception is
    # propagated unmodified, not caught/wrapped/swallowed.
    import uuid
    from unittest.mock import patch

    fixed_id = str(uuid.uuid4())
    with patch("uuid.uuid4", return_value=uuid.UUID(fixed_id)):
        first = MemoryRecord(observation=obs)
    store.add(first)

    raised_type = None
    with patch("uuid.uuid4", return_value=uuid.UUID(fixed_id)):
        try:
            recorder.record(obs)
        except MemoryError:
            raised_type = MemoryError
        except Exception as exc:  # noqa: BLE001
            raised_type = type(exc)

    check(
        raised_type is MemoryError,
        "MemoryRecorder.record() propagates MemoryError from MemoryStore.add() on a "
        "record_id collision, unmodified -- never caught or swallowed here",
    )


# ---------------------------------------------------------------------------
# Group 5 -- Observation -> MemoryRecorder -> MemoryStore integration
# ---------------------------------------------------------------------------
def scenario_end_to_end_observation_to_store() -> None:
    plan = ExecutionPlan(
        goal=Goal(metadata={"ticker": "BBCA.JK"}),
        steps=(PlanStep(service_name="price_service"), PlanStep(service_name="risk_service")),
    )
    results = [
        ServiceResult.ok(data={"price": 9500}),
        ServiceResult.ok(data={"risk": "low"}),
    ]
    obs = ObservationRecorder().record(Goal(metadata={"ticker": "BBCA.JK"}), plan, results)

    store = MemoryStore()
    recorder = MemoryRecorder(store)
    record = recorder.record(obs)

    check(
        record.observation.plan_step_names == ("price_service", "risk_service"),
        "an Observation built by ObservationRecorder retains its plan_step_names once "
        "carried through MemoryRecorder into a MemoryRecord",
    )
    check(
        record.observation.aggregated_outputs == {"price": 9500, "risk": "low"},
        "the Observation's aggregated_outputs survive the Observation -> MemoryRecorder "
        "-> MemoryStore trip unchanged",
    )
    check(
        store.get(record.record_id) is record,
        "the end-to-end record is retrievable from the store by its record_id",
    )


def scenario_end_to_end_multiple_observations_multiple_records() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store)

    obs1 = _observation_with_steps()
    obs2 = _empty_observation()

    record1 = recorder.record(obs1)
    record2 = recorder.record(obs2)

    check(len(store) == 2, "two distinct Observations recorded produce two stored MemoryRecords")
    check(
        {r.record_id for r in store.list()} == {record1.record_id, record2.record_id},
        "MemoryStore.list() reflects exactly the records produced by the two "
        "MemoryRecorder.record() calls, no more and no less",
    )
    check(
        store.get(record1.record_id).observation is obs1
        and store.get(record2.record_id).observation is obs2,
        "each stored MemoryRecord still wraps the exact Observation it was recorded from",
    )


def scenario_end_to_end_failed_step_observation_is_still_memorized() -> None:
    obs = _observation_with_steps()  # contains one failed step ("b")
    check(obs.all_succeeded is False, "sanity check: fixture Observation has a failed step")

    store = MemoryStore()
    recorder = MemoryRecorder(store)
    record = recorder.record(obs)

    check(
        record.observation.all_succeeded is False,
        "an Observation containing a business failure is memorized as-is -- Memory does "
        "not filter out, retry, or reinterpret failed steps",
    )
    check(
        record.observation.failed_service_names == ("b",),
        "the failed step's identity survives the Observation -> Memory round trip",
    )


def scenario_end_to_end_store_isolated_across_recorders() -> None:
    store_a = MemoryStore()
    store_b = MemoryStore()
    recorder_a = MemoryRecorder(store_a)
    recorder_b = MemoryRecorder(store_b)

    recorder_a.record(_empty_observation())
    recorder_b.record(_empty_observation())
    recorder_b.record(_empty_observation())

    check(len(store_a) == 1, "a MemoryRecorder only ever writes into the MemoryStore it was given")
    check(
        len(store_b) == 2,
        "a second MemoryRecorder writing to a different MemoryStore does not affect the first",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_memory_error_is_agent_error,
        scenario_memory_error_details_default_to_empty_dict,
        # Group 2
        scenario_memory_record_is_frozen_dataclass,
        scenario_memory_record_wraps_observation_unmodified,
        scenario_memory_record_id_is_fresh_uuid_per_instance,
        scenario_memory_record_recorded_at_is_float_timestamp,
        scenario_memory_record_recorded_at_distinct_from_observation_recorded_at,
        scenario_memory_record_construction_is_single_call_no_helper,
        # Group 3
        scenario_store_starts_empty,
        scenario_store_add_and_get_round_trip,
        scenario_store_get_missing_id_returns_none_not_error,
        scenario_store_add_duplicate_record_id_raises_memory_error,
        scenario_store_list_returns_insertion_order,
        scenario_store_list_returns_fresh_snapshot_not_live_reference,
        scenario_store_clear_empties_the_store,
        scenario_store_no_dependencies_at_construction,
        # Group 4
        scenario_recorder_holds_only_the_store_it_was_given,
        scenario_recorder_record_wraps_and_returns_memory_record,
        scenario_recorder_record_inserts_into_the_store,
        scenario_recorder_returns_same_instance_that_was_stored,
        scenario_recorder_does_not_mutate_observation,
        scenario_recorder_is_reusable_across_calls,
        scenario_recorder_propagates_store_collision_unmodified,
        # Group 5
        scenario_end_to_end_observation_to_store,
        scenario_end_to_end_multiple_observations_multiple_records,
        scenario_end_to_end_failed_step_observation_is_still_memorized,
        scenario_end_to_end_store_isolated_across_recorders,
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
    print(f"STAGE L17 MEMORY RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())