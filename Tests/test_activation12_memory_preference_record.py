"""
Activation 12, Phase 2 proof suite -- ``Orchestration.memory.PreferenceRecord``.

Scope: dedicated regression suite for the new ``PreferenceRecord`` value
object only. Verifies it is a minimal, immutable, non-financial memory
record that stores and retrieves through the EXISTING, UNMODIFIED
``MemoryStore`` -- no new store, no new database, no vector storage, no
persistence, no planner/scheduler/execution wiring.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l17_memory.py``: a global pass/fail counter, plain fixtures,
and a ``main()`` runner.

Explicitly NOT tested here: strategy notes, previous-decision memory,
lessons-from-failed-trades memory, ``GoalPlanner`` integration, or any
persistence-across-restart behavior -- all out of scope for this step.
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
from Database.models import Account
from Orchestration.memory import (
    MemoryError,
    MemoryRecord,
    MemoryRecorder,
    MemoryStore,
    PreferenceRecord,
)
from Orchestration.observation import ObservationRecorder
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


def _observation():
    """A minimal, real ``Observation`` -- used only to prove existing
    observation-based ``MemoryRecord`` behavior is unaffected."""
    goal = Goal(metadata={"ticker": "BBCA.JK"})
    plan = ExecutionPlan(goal=goal, steps=(PlanStep(service_name="svc"),))
    results = [ServiceResult.ok(data={"price": 100})]
    return ObservationRecorder().record(goal=goal, plan=plan, results=results)


def _account() -> Account:
    """A real financial domain object -- used only to prove it is
    rejected as a preference value."""
    return Account(
        account_id="a1",
        account_name="n",
        mode="paper",
        currency="USD",
        asset_class="equity",
        cash=100.0,
        equity=100.0,
        buying_power=100.0,
        created_at="t",
        updated_at="t",
    )


# ---------------------------------------------------------------------------
# A. Construction
# ---------------------------------------------------------------------------


def scenario_preference_record_constructs_with_key_and_value() -> None:
    record = PreferenceRecord(key="analysis_style", value="concise")
    check(record.key == "analysis_style", "PreferenceRecord.key stores as given")
    check(record.value == "concise", "PreferenceRecord.value stores as given")


def scenario_preference_record_has_fresh_record_id_and_timestamp() -> None:
    record = PreferenceRecord(key="k", value="v")
    check(isinstance(record.record_id, str) and len(record.record_id) > 0, "record_id is a non-empty str")
    check(isinstance(record.recorded_at, float), "recorded_at is a float timestamp")


def scenario_preference_record_ids_are_unique_per_instance() -> None:
    a = PreferenceRecord(key="k", value="v")
    b = PreferenceRecord(key="k", value="v")
    check(a.record_id != b.record_id, "two PreferenceRecords get distinct record_ids")


def scenario_preference_record_source_defaults_to_none_and_is_optional() -> None:
    no_source = PreferenceRecord(key="k", value="v")
    with_source = PreferenceRecord(key="k", value="v", source="chat")
    check(no_source.source is None, "source defaults to None")
    check(with_source.source == "chat", "source stores as given when provided")


def scenario_preference_record_rejects_empty_key() -> None:
    try:
        PreferenceRecord(key="", value="v")
        check(False, "empty key raises MemoryError")
    except MemoryError:
        check(True, "empty key raises MemoryError")


def scenario_preference_record_rejects_non_string_key() -> None:
    try:
        PreferenceRecord(key=123, value="v")  # type: ignore[arg-type]
        check(False, "non-str key raises MemoryError")
    except MemoryError:
        check(True, "non-str key raises MemoryError")


def scenario_preference_record_accepts_none_value() -> None:
    record = PreferenceRecord(key="k", value=None)
    check(record.value is None, "None is a valid preference value")


def scenario_preference_record_accepts_primitive_value_types() -> None:
    str_rec = PreferenceRecord(key="k1", value="concise")
    int_rec = PreferenceRecord(key="k2", value=3)
    float_rec = PreferenceRecord(key="k3", value=0.5)
    bool_rec = PreferenceRecord(key="k4", value=True)
    check(str_rec.value == "concise", "str value accepted")
    check(int_rec.value == 3, "int value accepted")
    check(float_rec.value == 0.5, "float value accepted")
    check(bool_rec.value is True, "bool value accepted")


# ---------------------------------------------------------------------------
# B. Immutability
# ---------------------------------------------------------------------------


def scenario_preference_record_is_frozen_dataclass() -> None:
    check(dataclasses.is_dataclass(PreferenceRecord), "PreferenceRecord is a dataclass")
    record = PreferenceRecord(key="k", value="v")
    try:
        record.value = "changed"  # type: ignore[misc]
        check(False, "mutating .value raises FrozenInstanceError")
    except dataclasses.FrozenInstanceError:
        check(True, "mutating .value raises FrozenInstanceError")


def scenario_preference_record_construction_is_single_call() -> None:
    # No helper/factory required -- a plain PreferenceRecord(key=..., value=...)
    # call is sufficient, exactly like MemoryRecord(observation=...).
    record = PreferenceRecord(key="k", value="v")
    check(isinstance(record, PreferenceRecord), "single-call construction succeeds")


# ---------------------------------------------------------------------------
# C. Valid preference storage using the EXISTING MemoryStore contract
# ---------------------------------------------------------------------------


def scenario_preference_record_stores_in_existing_memory_store_unmodified() -> None:
    store = MemoryStore()
    record = PreferenceRecord(key="analysis_style", value="concise")
    store.add(record)  # MemoryStore.add is not modified for this step
    check(len(store) == 1, "MemoryStore.add accepts a PreferenceRecord")


def scenario_preference_record_storage_does_not_require_new_store_type() -> None:
    store = MemoryStore()
    check(isinstance(store, MemoryStore), "storage uses the existing MemoryStore class, nothing new")
    store.add(PreferenceRecord(key="k", value="v"))
    check(len(store) == 1, "record stored without any new store subtype")


# ---------------------------------------------------------------------------
# D. Retrieval from MemoryStore
# ---------------------------------------------------------------------------


def scenario_preference_record_round_trips_through_get() -> None:
    store = MemoryStore()
    record = PreferenceRecord(key="notification_style", value="digest")
    store.add(record)
    fetched = store.get(record.record_id)
    check(fetched is record, "store.get returns the same PreferenceRecord instance")


def scenario_preference_record_round_trips_through_list() -> None:
    store = MemoryStore()
    record = PreferenceRecord(key="k", value="v")
    store.add(record)
    listed = store.list()
    check(isinstance(listed, tuple), "store.list() still returns a tuple")
    check(record in listed, "store.list() includes the stored PreferenceRecord")


def scenario_preference_record_missing_id_returns_none_not_error() -> None:
    store = MemoryStore()
    check(store.get("does-not-exist") is None, "unknown record_id returns None, not an error")


# ---------------------------------------------------------------------------
# E. Multiple preferences coexist
# ---------------------------------------------------------------------------


def scenario_multiple_preferences_coexist_in_one_store() -> None:
    store = MemoryStore()
    p1 = PreferenceRecord(key="analysis_style", value="concise")
    p2 = PreferenceRecord(key="notification_style", value="digest")
    p3 = PreferenceRecord(key="report_verbosity", value="detailed")
    store.add(p1)
    store.add(p2)
    store.add(p3)
    listed = store.list()
    check(len(listed) == 3, "three distinct preferences all stored")
    check({r.key for r in listed} == {"analysis_style", "notification_style", "report_verbosity"}, "all three keys retrievable")


def scenario_duplicate_preference_record_id_raises_memory_error() -> None:
    store = MemoryStore()
    record = PreferenceRecord(key="k", value="v")
    store.add(record)
    try:
        store.add(record)
        check(False, "re-adding the same record_id raises MemoryError")
    except MemoryError:
        check(True, "re-adding the same record_id raises MemoryError")


# ---------------------------------------------------------------------------
# F. Existing MemoryStore observation behavior remains unchanged
# ---------------------------------------------------------------------------


def scenario_existing_observation_memory_record_flow_still_works() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store=store)
    obs = _observation()
    mr = recorder.record(obs)
    check(isinstance(mr, MemoryRecord), "MemoryRecorder still returns a MemoryRecord")
    check(store.get(mr.record_id) is mr, "existing MemoryRecord still round-trips through MemoryStore")


def scenario_preference_and_observation_records_coexist_in_same_store() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store=store)
    mr = recorder.record(_observation())
    pref = PreferenceRecord(key="k", value="v")
    store.add(pref)
    listed = store.list()
    check(len(listed) == 2, "both an observation-based MemoryRecord and a PreferenceRecord fit in one store")
    kinds = {type(r).__name__ for r in listed}
    check(kinds == {"MemoryRecord", "PreferenceRecord"}, "store holds both record kinds side by side")
    check(store.get(mr.record_id) is mr, "MemoryRecord still retrievable after a PreferenceRecord was added")
    check(store.get(pref.record_id) is pref, "PreferenceRecord retrievable alongside a MemoryRecord")


# ---------------------------------------------------------------------------
# G. Financial objects cannot be stored as preference values
# ---------------------------------------------------------------------------


def scenario_financial_account_object_rejected_as_preference_value() -> None:
    try:
        PreferenceRecord(key="account", value=_account())
        check(False, "an Account object is rejected as a preference value")
    except MemoryError:
        check(True, "an Account object is rejected as a preference value")


def scenario_arbitrary_non_primitive_object_rejected_as_preference_value() -> None:
    try:
        PreferenceRecord(key="k", value={"cash": 100.0})
        check(False, "a dict/object value is rejected as a preference value")
    except MemoryError:
        check(True, "a dict/object value is rejected as a preference value")


# ---------------------------------------------------------------------------
# H. No execution/business-layer dependency introduced
# ---------------------------------------------------------------------------


def scenario_preference_record_has_no_execution_capability_attributes() -> None:
    record = PreferenceRecord(key="k", value="v")
    forbidden_attrs = (
        "execute",
        "run",
        "submit_order",
        "place_order",
        "cancel",
        "tool_registry",
        "tool_resolver",
    )
    for attr in forbidden_attrs:
        check(not hasattr(record, attr), f"PreferenceRecord has no '{attr}' attribute")


def scenario_preference_record_fields_are_only_declared_data_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(PreferenceRecord)}
    check(
        field_names == {"key", "value", "record_id", "recorded_at", "source"},
        "PreferenceRecord declares exactly the justified fields, nothing more",
    )


def scenario_memory_module_does_not_import_execution_layer() -> None:
    import Orchestration.memory as memory_module

    source = Path(memory_module.__file__).read_text()
    for forbidden in ("PaperTradingEngine", "ToolRegistry", "ToolResolver", "ExecutionService"):
        check(forbidden not in source, f"Orchestration/memory.py does not reference {forbidden}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    scenarios = [
        # Group A
        scenario_preference_record_constructs_with_key_and_value,
        scenario_preference_record_has_fresh_record_id_and_timestamp,
        scenario_preference_record_ids_are_unique_per_instance,
        scenario_preference_record_source_defaults_to_none_and_is_optional,
        scenario_preference_record_rejects_empty_key,
        scenario_preference_record_rejects_non_string_key,
        scenario_preference_record_accepts_none_value,
        scenario_preference_record_accepts_primitive_value_types,
        # Group B
        scenario_preference_record_is_frozen_dataclass,
        scenario_preference_record_construction_is_single_call,
        # Group C
        scenario_preference_record_stores_in_existing_memory_store_unmodified,
        scenario_preference_record_storage_does_not_require_new_store_type,
        # Group D
        scenario_preference_record_round_trips_through_get,
        scenario_preference_record_round_trips_through_list,
        scenario_preference_record_missing_id_returns_none_not_error,
        # Group E
        scenario_multiple_preferences_coexist_in_one_store,
        scenario_duplicate_preference_record_id_raises_memory_error,
        # Group F
        scenario_existing_observation_memory_record_flow_still_works,
        scenario_preference_and_observation_records_coexist_in_same_store,
        # Group G
        scenario_financial_account_object_rejected_as_preference_value,
        scenario_arbitrary_non_primitive_object_rejected_as_preference_value,
        # Group H
        scenario_preference_record_has_no_execution_capability_attributes,
        scenario_preference_record_fields_are_only_declared_data_fields,
        scenario_memory_module_does_not_import_execution_layer,
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
    print(f"ACTIVATION 12 MEMORY PREFERENCE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())