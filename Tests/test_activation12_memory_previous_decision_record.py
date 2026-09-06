"""
Activation 12, Memory (Previous Decisions) proof suite --
``Orchestration.memory.PreviousDecisionRecord``.

Scope: dedicated regression suite for the new ``PreviousDecisionRecord``
value object only. Verifies it is a minimal, immutable, non-financial
memory record that stores and retrieves through the EXISTING,
UNMODIFIED ``MemoryStore`` -- no new store, no new database, no vector
storage, no persistence, no CLI, no planner/scheduler/execution wiring,
no decision replay engine.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_activation12_memory_preference_record.py`` and
``test_activation12_memory_strategy_note_record.py``: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Validation contract chosen (mirroring ``StrategyNoteRecord.text``):
``decision`` and ``rationale`` must each already be a ``str`` -- a
non-``str`` value (e.g. an ``int`` or ``None``) is rejected with
``MemoryError`` before any normalization is attempted. Only once a
field is confirmed to be a ``str`` is it normalized via ``.strip()``
and rejected if the result is empty.

Explicitly NOT tested here: previous-decision CLI, ``GoalPlanner``
integration, ``HumanApprovalPort`` integration, decision replay engine,
lessons-from-failed-trades memory, or any persistence-across-restart
behavior -- all out of scope for this step.
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
    PreviousDecisionRecord,
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
    PreviousDecisionRecord has no dependency on it."""
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
# A. Valid construction (scenario A)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_constructs_with_decision_and_rationale() -> None:
    record = PreviousDecisionRecord(
        decision="Reduced BBCA.JK position by half.",
        rationale="Earnings missed consensus and momentum turned negative.",
    )
    check(record.decision == "Reduced BBCA.JK position by half.", "PreviousDecisionRecord.decision stores as given")
    check(
        record.rationale == "Earnings missed consensus and momentum turned negative.",
        "PreviousDecisionRecord.rationale stores as given",
    )


def scenario_previous_decision_record_has_fresh_record_id_and_timestamp() -> None:
    record = PreviousDecisionRecord(decision="Held position.", rationale="No new information.")
    check(isinstance(record.record_id, str) and len(record.record_id) > 0, "record_id is a non-empty str")
    check(isinstance(record.recorded_at, float), "recorded_at is a float timestamp")


def scenario_previous_decision_record_ids_are_unique_per_instance() -> None:
    r1 = PreviousDecisionRecord(decision="decision one", rationale="rationale one")
    r2 = PreviousDecisionRecord(decision="decision two", rationale="rationale two")
    check(r1.record_id != r2.record_id, "each PreviousDecisionRecord gets its own fresh record_id")


def scenario_previous_decision_record_source_defaults_to_none_and_is_optional() -> None:
    r1 = PreviousDecisionRecord(decision="d", rationale="r")
    check(r1.source is None, "source defaults to None")
    r2 = PreviousDecisionRecord(decision="d", rationale="r", source="planner")
    check(r2.source == "planner", "source stores as given when provided")


# ---------------------------------------------------------------------------
# B. Decision normalization (scenario B)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_normalizes_surrounding_whitespace_in_decision() -> None:
    record = PreviousDecisionRecord(decision="   trimmed the position   ", rationale="rationale")
    check(record.decision == "trimmed the position", "leading/trailing whitespace is stripped from decision")


def scenario_previous_decision_record_decision_normalization_preserves_internal_content() -> None:
    record = PreviousDecisionRecord(decision="  cut size by 50% on IDX large caps  ", rationale="rationale")
    check(
        record.decision == "cut size by 50% on IDX large caps",
        "internal spacing/content unchanged, only surrounding whitespace stripped from decision",
    )


# ---------------------------------------------------------------------------
# C. Rationale normalization (scenario C)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_normalizes_surrounding_whitespace_in_rationale() -> None:
    record = PreviousDecisionRecord(decision="decision", rationale="   momentum turned negative   ")
    check(record.rationale == "momentum turned negative", "leading/trailing whitespace is stripped from rationale")


def scenario_previous_decision_record_rationale_normalization_preserves_internal_content() -> None:
    record = PreviousDecisionRecord(decision="decision", rationale="  earnings missed + guidance cut  ")
    check(
        record.rationale == "earnings missed + guidance cut",
        "internal spacing/content unchanged, only surrounding whitespace stripped from rationale",
    )


# ---------------------------------------------------------------------------
# D. Empty decision rejected (scenario D)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_rejects_empty_decision() -> None:
    try:
        PreviousDecisionRecord(decision="", rationale="rationale")
        check(False, "empty decision is rejected")
    except MemoryError:
        check(True, "empty decision is rejected")


def scenario_previous_decision_record_rejects_whitespace_only_decision() -> None:
    try:
        PreviousDecisionRecord(decision="   ", rationale="rationale")
        check(False, "whitespace-only decision is rejected after stripping")
    except MemoryError:
        check(True, "whitespace-only decision is rejected after stripping")


# ---------------------------------------------------------------------------
# E. Empty rationale rejected (scenario E)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_rejects_empty_rationale() -> None:
    try:
        PreviousDecisionRecord(decision="decision", rationale="")
        check(False, "empty rationale is rejected")
    except MemoryError:
        check(True, "empty rationale is rejected")


def scenario_previous_decision_record_rejects_whitespace_only_rationale() -> None:
    try:
        PreviousDecisionRecord(decision="decision", rationale="   ")
        check(False, "whitespace-only rationale is rejected after stripping")
    except MemoryError:
        check(True, "whitespace-only rationale is rejected after stripping")


# ---------------------------------------------------------------------------
# F. Non-string decision rejected (scenario F)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_rejects_non_string_decision_int() -> None:
    try:
        PreviousDecisionRecord(decision=123, rationale="rationale")  # type: ignore[arg-type]
        check(False, "non-str (int) decision is rejected")
    except MemoryError:
        check(True, "non-str (int) decision is rejected")


def scenario_previous_decision_record_rejects_non_string_decision_none() -> None:
    try:
        PreviousDecisionRecord(decision=None, rationale="rationale")  # type: ignore[arg-type]
        check(False, "non-str (None) decision is rejected")
    except MemoryError:
        check(True, "non-str (None) decision is rejected")


# ---------------------------------------------------------------------------
# G. Non-string rationale rejected (scenario G)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_rejects_non_string_rationale_int() -> None:
    try:
        PreviousDecisionRecord(decision="decision", rationale=456)  # type: ignore[arg-type]
        check(False, "non-str (int) rationale is rejected")
    except MemoryError:
        check(True, "non-str (int) rationale is rejected")


def scenario_previous_decision_record_rejects_non_string_rationale_none() -> None:
    try:
        PreviousDecisionRecord(decision="decision", rationale=None)  # type: ignore[arg-type]
        check(False, "non-str (None) rationale is rejected")
    except MemoryError:
        check(True, "non-str (None) rationale is rejected")


# ---------------------------------------------------------------------------
# H. Frozen immutability (scenario H)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_is_frozen_dataclass() -> None:
    check(dataclasses.is_dataclass(PreviousDecisionRecord), "PreviousDecisionRecord is a dataclass")
    record = PreviousDecisionRecord(decision="decision", rationale="rationale")
    try:
        record.decision = "changed"  # type: ignore[misc]
        check(False, "mutating .decision raises FrozenInstanceError")
    except dataclasses.FrozenInstanceError:
        check(True, "mutating .decision raises FrozenInstanceError")
    try:
        record.rationale = "changed"  # type: ignore[misc]
        check(False, "mutating .rationale raises FrozenInstanceError")
    except dataclasses.FrozenInstanceError:
        check(True, "mutating .rationale raises FrozenInstanceError")


def scenario_previous_decision_record_construction_is_single_call() -> None:
    # Construction must remain a single, plain call -- no builder, no
    # separate factory method required.
    record = PreviousDecisionRecord(decision="decision", rationale="rationale")
    check(isinstance(record, PreviousDecisionRecord), "PreviousDecisionRecord constructs via a single plain call")


# ---------------------------------------------------------------------------
# I. Default record_id generated (scenario I)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_default_record_id_is_uuid_like() -> None:
    import uuid

    record = PreviousDecisionRecord(decision="decision", rationale="rationale")
    parsed = uuid.UUID(record.record_id)
    check(str(parsed) == record.record_id, "default record_id is a valid uuid4 string")


# ---------------------------------------------------------------------------
# J. Default recorded_at generated (scenario J)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_default_recorded_at_is_positive() -> None:
    import time

    before = time.time()
    record = PreviousDecisionRecord(decision="decision", rationale="rationale")
    after = time.time()
    check(before <= record.recorded_at <= after, "default recorded_at falls within the construction window")


# ---------------------------------------------------------------------------
# K. Optional source accepted (scenario K)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_accepts_optional_source_values() -> None:
    for value in ("cli", "chat", "planner", None):
        record = PreviousDecisionRecord(decision="decision", rationale="rationale", source=value)
        check(record.source == value, f"source={value!r} is accepted and stored as given")


# ---------------------------------------------------------------------------
# L. Optional reference_id accepted (scenario L)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_accepts_optional_reference_id_values() -> None:
    for value in ("order-123", "trade-456", "decision-key-789", None):
        record = PreviousDecisionRecord(decision="decision", rationale="rationale", reference_id=value)
        check(record.reference_id == value, f"reference_id={value!r} is accepted and stored as given")


def scenario_previous_decision_record_reference_id_defaults_to_none() -> None:
    record = PreviousDecisionRecord(decision="decision", rationale="rationale")
    check(record.reference_id is None, "reference_id defaults to None")


# ---------------------------------------------------------------------------
# M. Stored in existing MemoryStore (scenario M)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_stores_in_existing_memory_store_unmodified() -> None:
    store = MemoryStore()
    record = PreviousDecisionRecord(decision="decision", rationale="rationale")
    store.add(record)
    check(len(store) == 1, "PreviousDecisionRecord stores through the existing, unmodified MemoryStore.add")


def scenario_previous_decision_record_storage_does_not_require_new_store_type() -> None:
    store = MemoryStore(max_size=5, ttl_seconds=None)
    record = PreviousDecisionRecord(decision="decision", rationale="rationale")
    store.add(record)
    check(
        isinstance(store, MemoryStore),
        "PreviousDecisionRecord storage uses the same MemoryStore class, with no new store type",
    )


# ---------------------------------------------------------------------------
# N. Retrieved from existing MemoryStore (scenario N)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_round_trips_through_get() -> None:
    store = MemoryStore()
    record = PreviousDecisionRecord(decision="decision", rationale="rationale")
    store.add(record)
    fetched = store.get(record.record_id)
    check(fetched is record, "PreviousDecisionRecord round-trips through MemoryStore.get")


def scenario_previous_decision_record_round_trips_through_list() -> None:
    store = MemoryStore()
    record = PreviousDecisionRecord(decision="decision", rationale="rationale")
    store.add(record)
    listed = store.list()
    check(record in listed, "PreviousDecisionRecord round-trips through MemoryStore.list")


def scenario_previous_decision_record_missing_id_returns_none_not_error() -> None:
    store = MemoryStore()
    check(store.get("does-not-exist") is None, "a missing record_id returns None, not an error")


def scenario_multiple_previous_decision_records_coexist_in_one_store() -> None:
    store = MemoryStore()
    r1 = PreviousDecisionRecord(decision="d1", rationale="r1")
    r2 = PreviousDecisionRecord(decision="d2", rationale="r2")
    store.add(r1)
    store.add(r2)
    check(len(store) == 2, "multiple PreviousDecisionRecord instances coexist in one MemoryStore")
    check(store.get(r1.record_id) is r1, "first PreviousDecisionRecord retrievable")
    check(store.get(r2.record_id) is r2, "second PreviousDecisionRecord retrievable")


def scenario_duplicate_previous_decision_record_id_raises_memory_error() -> None:
    store = MemoryStore()
    record = PreviousDecisionRecord(decision="decision", rationale="rationale")
    store.add(record)
    try:
        store.add(record)
        check(False, "adding a duplicate record_id raises MemoryError")
    except MemoryError:
        check(True, "adding a duplicate record_id raises MemoryError")


# ---------------------------------------------------------------------------
# O. Coexists with MemoryRecord (scenario O)
# ---------------------------------------------------------------------------


def scenario_previous_decision_and_observation_records_coexist_in_same_store() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store=store)
    mr = recorder.record(_observation())
    decision = PreviousDecisionRecord(decision="decision", rationale="rationale")
    store.add(decision)
    listed = store.list()
    check(len(listed) == 2, "MemoryRecord and PreviousDecisionRecord coexist in one store")
    kinds = {type(r).__name__ for r in listed}
    check(kinds == {"MemoryRecord", "PreviousDecisionRecord"}, "store holds both record kinds side by side")
    check(store.get(mr.record_id) is mr, "MemoryRecord still retrievable after a PreviousDecisionRecord was added")
    check(store.get(decision.record_id) is decision, "PreviousDecisionRecord retrievable alongside a MemoryRecord")


def scenario_existing_observation_memory_record_flow_still_works() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store=store)
    mr = recorder.record(_observation())
    check(isinstance(mr, MemoryRecord), "MemoryRecorder.record still returns a MemoryRecord, unaffected")
    check(store.get(mr.record_id) is mr, "existing MemoryRecord flow through MemoryStore is unaffected")


# ---------------------------------------------------------------------------
# P. Coexists with PreferenceRecord (scenario P)
# ---------------------------------------------------------------------------


def scenario_previous_decision_and_preference_records_coexist_in_same_store() -> None:
    store = MemoryStore()
    pref = PreferenceRecord(key="analysis_style", value="concise")
    decision = PreviousDecisionRecord(decision="decision", rationale="rationale")
    store.add(pref)
    store.add(decision)
    listed = store.list()
    check(len(listed) == 2, "PreferenceRecord and PreviousDecisionRecord coexist in one store")
    kinds = {type(r).__name__ for r in listed}
    check(kinds == {"PreferenceRecord", "PreviousDecisionRecord"}, "store holds both record kinds side by side")
    check(store.get(pref.record_id) is pref, "PreferenceRecord still retrievable after a PreviousDecisionRecord was added")
    check(store.get(decision.record_id) is decision, "PreviousDecisionRecord retrievable alongside a PreferenceRecord")


# ---------------------------------------------------------------------------
# Q. Coexists with StrategyNoteRecord (scenario Q)
# ---------------------------------------------------------------------------


def scenario_previous_decision_and_strategy_note_records_coexist_in_same_store() -> None:
    store = MemoryStore()
    note = StrategyNoteRecord(text="Use momentum strategy on IDX large caps.")
    decision = PreviousDecisionRecord(decision="decision", rationale="rationale")
    store.add(note)
    store.add(decision)
    listed = store.list()
    check(len(listed) == 2, "StrategyNoteRecord and PreviousDecisionRecord coexist in one store")
    kinds = {type(r).__name__ for r in listed}
    check(kinds == {"StrategyNoteRecord", "PreviousDecisionRecord"}, "store holds both record kinds side by side")
    check(store.get(note.record_id) is note, "StrategyNoteRecord still retrievable after a PreviousDecisionRecord was added")
    check(store.get(decision.record_id) is decision, "PreviousDecisionRecord retrievable alongside a StrategyNoteRecord")


def scenario_all_four_record_kinds_coexist_in_same_store() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store=store)
    mr = recorder.record(_observation())
    pref = PreferenceRecord(key="k", value="v")
    note = StrategyNoteRecord(text="note")
    decision = PreviousDecisionRecord(decision="decision", rationale="rationale")
    store.add(pref)
    store.add(note)
    store.add(decision)
    listed = store.list()
    check(len(listed) == 4, "MemoryRecord, PreferenceRecord, StrategyNoteRecord, and PreviousDecisionRecord all fit in one store")
    kinds = {type(r).__name__ for r in listed}
    check(
        kinds == {"MemoryRecord", "PreferenceRecord", "StrategyNoteRecord", "PreviousDecisionRecord"},
        "store holds all four record kinds side by side",
    )
    check(store.get(mr.record_id) is mr, "MemoryRecord retrievable")
    check(store.get(pref.record_id) is pref, "PreferenceRecord retrievable")
    check(store.get(note.record_id) is note, "StrategyNoteRecord retrievable")
    check(store.get(decision.record_id) is decision, "PreviousDecisionRecord retrievable")


# ---------------------------------------------------------------------------
# R. No financial dependency (scenario R)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_has_no_financial_object_field() -> None:
    field_names = {f.name for f in dataclasses.fields(PreviousDecisionRecord)}
    check(
        field_names == {"decision", "rationale", "record_id", "recorded_at", "source", "reference_id"},
        "PreviousDecisionRecord declares exactly the locked field set, nothing more",
    )
    forbidden_fields = (
        "account_id",
        "portfolio_id",
        "order_id",
        "trade_id",
        "symbol",
        "market",
        "position",
        "quantity",
        "price",
    )
    for forbidden in forbidden_fields:
        check(forbidden not in field_names, f"PreviousDecisionRecord does not declare forbidden field '{forbidden}'")


def scenario_previous_decision_record_does_not_reference_account_object() -> None:
    account = _account()  # constructed only to prove PreviousDecisionRecord never needs it
    record = PreviousDecisionRecord(decision="decision about a trade, not the account itself", rationale="rationale")
    check(not hasattr(record, "account"), "PreviousDecisionRecord has no 'account' attribute")
    check(isinstance(account, Account), "sanity: Account itself is unaffected/unused by PreviousDecisionRecord")


# ---------------------------------------------------------------------------
# S. No execution capability (scenario S)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_has_no_execution_capability_attributes() -> None:
    record = PreviousDecisionRecord(decision="decision", rationale="rationale")
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
        check(not hasattr(record, attr), f"PreviousDecisionRecord has no '{attr}' attribute")


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
        "HumanApprovalPort",
    ):
        check(forbidden_name not in source, f"Orchestration/memory.py does not reference {forbidden_name}")


# ---------------------------------------------------------------------------
# T. reference_id remains opaque, no DB/repository access (scenario T)
# ---------------------------------------------------------------------------


def scenario_previous_decision_record_reference_id_is_plain_string_only() -> None:
    record = PreviousDecisionRecord(
        decision="decision",
        rationale="rationale",
        reference_id="order-999",
    )
    check(isinstance(record.reference_id, str), "reference_id is stored as a plain str")
    check(record.reference_id == "order-999", "reference_id is stored verbatim, with no lookup or transformation")


def scenario_previous_decision_record_reference_id_triggers_no_lookup_side_effect() -> None:
    # An intentionally nonsensical/unresolvable reference_id -- if any
    # lookup were attempted, construction would fail or raise. It must
    # not: reference_id is opaque.
    record = PreviousDecisionRecord(
        decision="decision",
        rationale="rationale",
        reference_id="this-id-does-not-exist-anywhere-12345",
    )
    check(
        record.reference_id == "this-id-does-not-exist-anywhere-12345",
        "an unresolvable reference_id constructs successfully -- no repository/database lookup is performed",
    )


def scenario_previous_decision_record_has_no_repository_or_database_attribute() -> None:
    record = PreviousDecisionRecord(decision="decision", rationale="rationale", reference_id="trade-1")
    forbidden_attrs = ("repository", "database", "db", "session", "connection")
    for attr in forbidden_attrs:
        check(not hasattr(record, attr), f"PreviousDecisionRecord has no '{attr}' attribute")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    scenarios = [
        # A. Valid construction
        scenario_previous_decision_record_constructs_with_decision_and_rationale,
        scenario_previous_decision_record_has_fresh_record_id_and_timestamp,
        scenario_previous_decision_record_ids_are_unique_per_instance,
        scenario_previous_decision_record_source_defaults_to_none_and_is_optional,
        # B. Decision normalization
        scenario_previous_decision_record_normalizes_surrounding_whitespace_in_decision,
        scenario_previous_decision_record_decision_normalization_preserves_internal_content,
        # C. Rationale normalization
        scenario_previous_decision_record_normalizes_surrounding_whitespace_in_rationale,
        scenario_previous_decision_record_rationale_normalization_preserves_internal_content,
        # D. Empty decision rejected
        scenario_previous_decision_record_rejects_empty_decision,
        scenario_previous_decision_record_rejects_whitespace_only_decision,
        # E. Empty rationale rejected
        scenario_previous_decision_record_rejects_empty_rationale,
        scenario_previous_decision_record_rejects_whitespace_only_rationale,
        # F. Non-string decision rejected
        scenario_previous_decision_record_rejects_non_string_decision_int,
        scenario_previous_decision_record_rejects_non_string_decision_none,
        # G. Non-string rationale rejected
        scenario_previous_decision_record_rejects_non_string_rationale_int,
        scenario_previous_decision_record_rejects_non_string_rationale_none,
        # H. Frozen immutability
        scenario_previous_decision_record_is_frozen_dataclass,
        scenario_previous_decision_record_construction_is_single_call,
        # I. Default record_id
        scenario_previous_decision_record_default_record_id_is_uuid_like,
        # J. Default recorded_at
        scenario_previous_decision_record_default_recorded_at_is_positive,
        # K. Optional source
        scenario_previous_decision_record_accepts_optional_source_values,
        # L. Optional reference_id
        scenario_previous_decision_record_accepts_optional_reference_id_values,
        scenario_previous_decision_record_reference_id_defaults_to_none,
        # M. Stored in existing MemoryStore
        scenario_previous_decision_record_stores_in_existing_memory_store_unmodified,
        scenario_previous_decision_record_storage_does_not_require_new_store_type,
        # N. Retrieved from existing MemoryStore
        scenario_previous_decision_record_round_trips_through_get,
        scenario_previous_decision_record_round_trips_through_list,
        scenario_previous_decision_record_missing_id_returns_none_not_error,
        scenario_multiple_previous_decision_records_coexist_in_one_store,
        scenario_duplicate_previous_decision_record_id_raises_memory_error,
        # O. Coexists with MemoryRecord
        scenario_previous_decision_and_observation_records_coexist_in_same_store,
        scenario_existing_observation_memory_record_flow_still_works,
        # P. Coexists with PreferenceRecord
        scenario_previous_decision_and_preference_records_coexist_in_same_store,
        # Q. Coexists with StrategyNoteRecord
        scenario_previous_decision_and_strategy_note_records_coexist_in_same_store,
        scenario_all_four_record_kinds_coexist_in_same_store,
        # R. No financial dependency
        scenario_previous_decision_record_has_no_financial_object_field,
        scenario_previous_decision_record_does_not_reference_account_object,
        # S. No execution capability
        scenario_previous_decision_record_has_no_execution_capability_attributes,
        scenario_memory_module_does_not_import_execution_or_financial_layer,
        # T. reference_id opacity
        scenario_previous_decision_record_reference_id_is_plain_string_only,
        scenario_previous_decision_record_reference_id_triggers_no_lookup_side_effect,
        scenario_previous_decision_record_has_no_repository_or_database_attribute,
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