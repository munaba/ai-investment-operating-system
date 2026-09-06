"""
Activation 12, Memory (Strategy Notes) proof suite --
``Orchestration.memory.StrategyNoteRecord``.

Scope: dedicated regression suite for the new ``StrategyNoteRecord``
value object only. Verifies it is a minimal, immutable, non-financial
memory record that stores and retrieves through the EXISTING,
UNMODIFIED ``MemoryStore`` -- no new store, no new database, no vector
storage, no persistence, no CLI, no planner/scheduler/execution wiring.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_activation12_memory_preference_record.py`` and
``test_stage_l17_memory.py``: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Validation contract chosen (per the Activation 12 Memory Strategy Note
Record atomic-implementation instructions, scenario D): ``text`` must
already be a ``str`` -- a non-``str`` value (e.g. an ``int`` or
``None``) is rejected with ``MemoryError`` before any normalization is
attempted, exactly mirroring ``PreferenceRecord.key``'s own
``isinstance`` check. Only once ``text`` is confirmed to be a ``str``
is it normalized via ``.strip()`` and rejected if the result is empty.

Explicitly NOT tested here: strategy-note CLI, ``GoalPlanner``
integration, previous-decision memory, lessons-from-failed-trades
memory, or any persistence-across-restart behavior -- all out of scope
for this step.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Database.models import Account
from Orchestration.memory import (
    MemoryError,
    MemoryRecord,
    MemoryRecorder,
    MemoryStore,
    PreferenceRecord,
    StrategyNoteRecord,
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
    """A real financial domain object -- used only to prove
    StrategyNoteRecord has no dependency on it."""
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
# A. Valid construction
# ---------------------------------------------------------------------------


def scenario_strategy_note_record_constructs_with_text() -> None:
    record = StrategyNoteRecord(text="Use momentum strategy on IDX large caps.")
    check(record.text == "Use momentum strategy on IDX large caps.", "StrategyNoteRecord.text stores as given")


def scenario_strategy_note_record_has_fresh_record_id_and_timestamp() -> None:
    record = StrategyNoteRecord(text="Avoid banking names during this experiment.")
    check(isinstance(record.record_id, str) and len(record.record_id) > 0, "record_id is a non-empty str")
    check(isinstance(record.recorded_at, float), "recorded_at is a float timestamp")


def scenario_strategy_note_record_ids_are_unique_per_instance() -> None:
    r1 = StrategyNoteRecord(text="note one")
    r2 = StrategyNoteRecord(text="note two")
    check(r1.record_id != r2.record_id, "each StrategyNoteRecord gets its own fresh record_id")


def scenario_strategy_note_record_source_defaults_to_none_and_is_optional() -> None:
    r1 = StrategyNoteRecord(text="note")
    check(r1.source is None, "source defaults to None")
    r2 = StrategyNoteRecord(text="note", source="cli")
    check(r2.source == "cli", "source stores as given when provided")


# ---------------------------------------------------------------------------
# B. Text normalization (scenario B)
# ---------------------------------------------------------------------------


def scenario_strategy_note_record_normalizes_surrounding_whitespace() -> None:
    record = StrategyNoteRecord(text="   swing trades only   ")
    check(record.text == "swing trades only", "leading/trailing whitespace is stripped from text")


def scenario_strategy_note_record_normalization_preserves_internal_content() -> None:
    record = StrategyNoteRecord(text="  prefer confirmation from price + volume  ")
    check(record.text == "prefer confirmation from price + volume", "internal spacing/content unchanged, only surrounding whitespace stripped")


# ---------------------------------------------------------------------------
# C. Empty text rejected (scenario C)
# ---------------------------------------------------------------------------


def scenario_strategy_note_record_rejects_empty_text() -> None:
    try:
        StrategyNoteRecord(text="")
        check(False, "empty text is rejected")
    except MemoryError:
        check(True, "empty text is rejected")


def scenario_strategy_note_record_rejects_whitespace_only_text() -> None:
    try:
        StrategyNoteRecord(text="   ")
        check(False, "whitespace-only text is rejected after stripping")
    except MemoryError:
        check(True, "whitespace-only text is rejected after stripping")


# ---------------------------------------------------------------------------
# D. Non-string text behavior matches chosen validation contract (scenario D)
# ---------------------------------------------------------------------------


def scenario_strategy_note_record_rejects_non_string_text_int() -> None:
    try:
        StrategyNoteRecord(text=123)  # type: ignore[arg-type]
        check(False, "non-str (int) text is rejected, per the chosen validation contract")
    except MemoryError:
        check(True, "non-str (int) text is rejected, per the chosen validation contract")


def scenario_strategy_note_record_rejects_non_string_text_none() -> None:
    try:
        StrategyNoteRecord(text=None)  # type: ignore[arg-type]
        check(False, "non-str (None) text is rejected, per the chosen validation contract")
    except MemoryError:
        check(True, "non-str (None) text is rejected, per the chosen validation contract")


# ---------------------------------------------------------------------------
# E. Immutability
# ---------------------------------------------------------------------------


def scenario_strategy_note_record_is_frozen_dataclass() -> None:
    check(dataclasses.is_dataclass(StrategyNoteRecord), "StrategyNoteRecord is a dataclass")
    record = StrategyNoteRecord(text="note")
    try:
        record.text = "changed"  # type: ignore[misc]
        check(False, "mutating .text raises FrozenInstanceError")
    except dataclasses.FrozenInstanceError:
        check(True, "mutating .text raises FrozenInstanceError")


def scenario_strategy_note_record_construction_is_single_call() -> None:
    record = StrategyNoteRecord(text="note")
    check(isinstance(record, StrategyNoteRecord), "single-call construction succeeds")


# ---------------------------------------------------------------------------
# F. Default record_id created (scenario F)
# ---------------------------------------------------------------------------


def scenario_strategy_note_record_default_record_id_is_uuid_like() -> None:
    record = StrategyNoteRecord(text="note")
    check(len(record.record_id.split("-")) == 5, "default record_id looks like a uuid4 string")


# ---------------------------------------------------------------------------
# G. Default recorded_at created (scenario G)
# ---------------------------------------------------------------------------


def scenario_strategy_note_record_default_recorded_at_is_positive() -> None:
    record = StrategyNoteRecord(text="note")
    check(record.recorded_at > 0, "default recorded_at is a positive epoch timestamp")


# ---------------------------------------------------------------------------
# H. Optional source accepted (scenario H)
# ---------------------------------------------------------------------------


def scenario_strategy_note_record_accepts_optional_source_values() -> None:
    for source_value in (None, "cli", "chat"):
        record = StrategyNoteRecord(text="note", source=source_value)
        check(record.source == source_value, f"source={source_value!r} accepted")


# ---------------------------------------------------------------------------
# I. Stored in existing MemoryStore (scenario I)
# ---------------------------------------------------------------------------


def scenario_strategy_note_record_stores_in_existing_memory_store_unmodified() -> None:
    store = MemoryStore()
    record = StrategyNoteRecord(text="Use momentum strategy on IDX large caps.")
    store.add(record)  # MemoryStore.add is not modified for this step
    check(len(store) == 1, "MemoryStore.add accepts a StrategyNoteRecord")


def scenario_strategy_note_record_storage_does_not_require_new_store_type() -> None:
    store = MemoryStore()
    check(isinstance(store, MemoryStore), "storage uses the existing MemoryStore class, nothing new")
    store.add(StrategyNoteRecord(text="note"))
    check(len(store) == 1, "record stored without any new store subtype")


# ---------------------------------------------------------------------------
# J. Retrieved from existing MemoryStore (scenario J)
# ---------------------------------------------------------------------------


def scenario_strategy_note_record_round_trips_through_get() -> None:
    store = MemoryStore()
    record = StrategyNoteRecord(text="This strategy is intended for swing trades.")
    store.add(record)
    fetched = store.get(record.record_id)
    check(fetched is record, "store.get returns the same StrategyNoteRecord instance")


def scenario_strategy_note_record_round_trips_through_list() -> None:
    store = MemoryStore()
    record = StrategyNoteRecord(text="note")
    store.add(record)
    listed = store.list()
    check(isinstance(listed, tuple), "store.list() still returns a tuple")
    check(record in listed, "store.list() includes the stored StrategyNoteRecord")


def scenario_strategy_note_record_missing_id_returns_none_not_error() -> None:
    store = MemoryStore()
    check(store.get("does-not-exist") is None, "unknown record_id returns None, not an error")


def scenario_multiple_strategy_notes_coexist_in_one_store() -> None:
    store = MemoryStore()
    n1 = StrategyNoteRecord(text="Use momentum strategy on IDX large caps.")
    n2 = StrategyNoteRecord(text="Avoid banking names during this strategy experiment.")
    n3 = StrategyNoteRecord(text="Prefer confirmation from price + volume.")
    store.add(n1)
    store.add(n2)
    store.add(n3)
    listed = store.list()
    check(len(listed) == 3, "three distinct strategy notes all stored")
    check({r.text for r in listed} == {n1.text, n2.text, n3.text}, "all three note texts retrievable")


def scenario_duplicate_strategy_note_record_id_raises_memory_error() -> None:
    store = MemoryStore()
    record = StrategyNoteRecord(text="note")
    store.add(record)
    try:
        store.add(record)
        check(False, "re-adding the same record_id raises MemoryError")
    except MemoryError:
        check(True, "re-adding the same record_id raises MemoryError")


# ---------------------------------------------------------------------------
# K. Coexistence with MemoryRecord (scenario K)
# ---------------------------------------------------------------------------


def scenario_strategy_note_and_observation_records_coexist_in_same_store() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store=store)
    mr = recorder.record(_observation())
    note = StrategyNoteRecord(text="note")
    store.add(note)
    listed = store.list()
    check(len(listed) == 2, "both an observation-based MemoryRecord and a StrategyNoteRecord fit in one store")
    kinds = {type(r).__name__ for r in listed}
    check(kinds == {"MemoryRecord", "StrategyNoteRecord"}, "store holds both record kinds side by side")
    check(store.get(mr.record_id) is mr, "MemoryRecord still retrievable after a StrategyNoteRecord was added")
    check(store.get(note.record_id) is note, "StrategyNoteRecord retrievable alongside a MemoryRecord")


def scenario_existing_observation_memory_record_flow_still_works() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store=store)
    obs = _observation()
    mr = recorder.record(obs)
    check(isinstance(mr, MemoryRecord), "MemoryRecorder still returns a MemoryRecord")
    check(store.get(mr.record_id) is mr, "existing MemoryRecord still round-trips through MemoryStore")


# ---------------------------------------------------------------------------
# L. Coexistence with PreferenceRecord (scenario L)
# ---------------------------------------------------------------------------


def scenario_strategy_note_and_preference_records_coexist_in_same_store() -> None:
    store = MemoryStore()
    pref = PreferenceRecord(key="analysis_style", value="concise")
    note = StrategyNoteRecord(text="note")
    store.add(pref)
    store.add(note)
    listed = store.list()
    check(len(listed) == 2, "both a PreferenceRecord and a StrategyNoteRecord fit in one store")
    kinds = {type(r).__name__ for r in listed}
    check(kinds == {"PreferenceRecord", "StrategyNoteRecord"}, "store holds both record kinds side by side")
    check(store.get(pref.record_id) is pref, "PreferenceRecord still retrievable after a StrategyNoteRecord was added")
    check(store.get(note.record_id) is note, "StrategyNoteRecord retrievable alongside a PreferenceRecord")


def scenario_all_three_record_kinds_coexist_in_same_store() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store=store)
    mr = recorder.record(_observation())
    pref = PreferenceRecord(key="k", value="v")
    note = StrategyNoteRecord(text="note")
    store.add(pref)
    store.add(note)
    listed = store.list()
    check(len(listed) == 3, "MemoryRecord, PreferenceRecord, and StrategyNoteRecord all fit in one store")
    kinds = {type(r).__name__ for r in listed}
    check(
        kinds == {"MemoryRecord", "PreferenceRecord", "StrategyNoteRecord"},
        "store holds all three record kinds side by side",
    )
    check(store.get(mr.record_id) is mr, "MemoryRecord retrievable")
    check(store.get(pref.record_id) is pref, "PreferenceRecord retrievable")
    check(store.get(note.record_id) is note, "StrategyNoteRecord retrievable")


# ---------------------------------------------------------------------------
# M. No financial object dependency (scenario M)
# ---------------------------------------------------------------------------


def scenario_strategy_note_record_has_no_financial_object_field() -> None:
    field_names = {f.name for f in dataclasses.fields(StrategyNoteRecord)}
    check(
        field_names == {"text", "record_id", "recorded_at", "source"},
        "StrategyNoteRecord declares exactly the locked field set, nothing more",
    )
    forbidden_fields = (
        "strategy_name",
        "strategy_version",
        "symbol",
        "market",
        "account_id",
        "portfolio_id",
        "risk",
        "target_price",
        "stop_loss",
        "performance",
        "trade_id",
    )
    for forbidden in forbidden_fields:
        check(forbidden not in field_names, f"StrategyNoteRecord does not declare forbidden field '{forbidden}'")


def scenario_strategy_note_record_does_not_reference_account_object() -> None:
    account = _account()  # constructed only to prove StrategyNoteRecord never needs it
    record = StrategyNoteRecord(text="note about a strategy, not about this account")
    check(not hasattr(record, "account"), "StrategyNoteRecord has no 'account' attribute")
    check(isinstance(account, Account), "sanity: Account itself is unaffected/unused by StrategyNoteRecord")


# ---------------------------------------------------------------------------
# N. No execution dependency (scenario N)
# ---------------------------------------------------------------------------


def scenario_strategy_note_record_has_no_execution_capability_attributes() -> None:
    record = StrategyNoteRecord(text="note")
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
        check(not hasattr(record, attr), f"StrategyNoteRecord has no '{attr}' attribute")


def scenario_memory_module_does_not_import_execution_or_financial_layer() -> None:
    import ast

    import Orchestration.memory as memory_module

    source = Path(memory_module.__file__).read_text()
    tree = ast.parse(source)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])

    # AST-level check (not a substring scan): forbidden modules must not
    # be imported. Prose mentions of "Account"/"Position"/"Order"/"Trade"
    # already exist legitimately in PreferenceRecord's own docstring
    # (explaining what kinds of objects it rejects as a preference
    # value), so a plain substring scan would false-positive on those --
    # actual imports are what matter for a real dependency.
    for forbidden_module in ("Database", "Repository"):
        check(forbidden_module not in imported_names, f"Orchestration/memory.py does not import {forbidden_module}")

    for forbidden_name in (
        "PaperTradingEngine",
        "ToolRegistry",
        "ToolResolver",
        "ExecutionService",
        "PermissionContext",
        "PaperExecutionTool",
    ):
        check(forbidden_name not in source, f"Orchestration/memory.py does not reference {forbidden_name}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    scenarios = [
        # A. Valid construction
        scenario_strategy_note_record_constructs_with_text,
        scenario_strategy_note_record_has_fresh_record_id_and_timestamp,
        scenario_strategy_note_record_ids_are_unique_per_instance,
        scenario_strategy_note_record_source_defaults_to_none_and_is_optional,
        # B. Text normalization
        scenario_strategy_note_record_normalizes_surrounding_whitespace,
        scenario_strategy_note_record_normalization_preserves_internal_content,
        # C. Empty text rejected
        scenario_strategy_note_record_rejects_empty_text,
        scenario_strategy_note_record_rejects_whitespace_only_text,
        # D. Non-string text
        scenario_strategy_note_record_rejects_non_string_text_int,
        scenario_strategy_note_record_rejects_non_string_text_none,
        # E. Immutability
        scenario_strategy_note_record_is_frozen_dataclass,
        scenario_strategy_note_record_construction_is_single_call,
        # F. Default record_id
        scenario_strategy_note_record_default_record_id_is_uuid_like,
        # G. Default recorded_at
        scenario_strategy_note_record_default_recorded_at_is_positive,
        # H. Optional source
        scenario_strategy_note_record_accepts_optional_source_values,
        # I. Stored in existing MemoryStore
        scenario_strategy_note_record_stores_in_existing_memory_store_unmodified,
        scenario_strategy_note_record_storage_does_not_require_new_store_type,
        # J. Retrieved from existing MemoryStore
        scenario_strategy_note_record_round_trips_through_get,
        scenario_strategy_note_record_round_trips_through_list,
        scenario_strategy_note_record_missing_id_returns_none_not_error,
        scenario_multiple_strategy_notes_coexist_in_one_store,
        scenario_duplicate_strategy_note_record_id_raises_memory_error,
        # K. Coexistence with MemoryRecord
        scenario_strategy_note_and_observation_records_coexist_in_same_store,
        scenario_existing_observation_memory_record_flow_still_works,
        # L. Coexistence with PreferenceRecord
        scenario_strategy_note_and_preference_records_coexist_in_same_store,
        scenario_all_three_record_kinds_coexist_in_same_store,
        # M. No financial object dependency
        scenario_strategy_note_record_has_no_financial_object_field,
        scenario_strategy_note_record_does_not_reference_account_object,
        # N. No execution dependency
        scenario_strategy_note_record_has_no_execution_capability_attributes,
        scenario_memory_module_does_not_import_execution_or_financial_layer,
    ]

    print(f"Running {len(scenarios)} scenarios...\n")
    for scenario in scenarios:
        print(f"[{scenario.__name__}]")
        try:
            scenario()
        except Exception as exc:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised unexpectedly: {exc!r}")
            print(f"  FAIL - {scenario.__name__} raised unexpectedly: {exc!r}")
        print()

    print(f"\n{_PASS} passed, {_FAIL} failed out of {_PASS + _FAIL}")
    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())