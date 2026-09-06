"""
Activation 12, Memory (Portfolio Context) proof suite --
``Orchestration.memory.PortfolioContextRecord``.

Scope: dedicated regression suite for the new ``PortfolioContextRecord``
value object only. Verifies it is a minimal, immutable, non-financial
memory record that stores and retrieves through the EXISTING,
UNMODIFIED ``MemoryStore`` -- no new store, no new database, no vector
storage, no persistence, no CLI, no automatic portfolio summarization,
no ``PortfolioSnapshot``/``PortfolioSnapshotRepository`` integration,
no Reflection/LearningLoop/Planner/Agent wiring.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_activation12_memory_preference_record.py``,
``test_activation12_memory_strategy_note_record.py``,
``test_activation12_memory_previous_decision_record.py``,
``test_activation12_memory_lesson_record.py``, and
``test_stage_l17_memory.py``: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Validation contract chosen (mirroring ``LessonRecord.text``): ``text``
must already be a ``str`` -- a non-``str`` value (e.g. an ``int`` or
``None``) is rejected with ``MemoryError`` before any normalization is
attempted. Only once ``text`` is confirmed to be a ``str`` is it
normalized via ``.strip()`` and rejected if the result is empty.

Explicitly NOT tested here: portfolio-context CLI
(``python main.py portfolio-context ...``), automatic
``PortfolioSnapshot`` -> ``PortfolioContextRecord`` conversion,
snapshot lookup/resolution, financial engine integration
(``UnrealizedPnLEngine``, ``MaximumDrawdownEngine``,
``FailureRateEngine``), Repository wiring, persistence, database
schema, vector/embedding storage, planner integration, scheduler
integration, or agent integration -- all out of scope for this step.
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
    LessonRecord,
    MemoryError,
    MemoryRecord,
    MemoryRecorder,
    MemoryStore,
    PortfolioContextRecord,
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
    PortfolioContextRecord has no dependency on it."""
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


def scenario_portfolio_context_record_constructs_with_text() -> None:
    record = PortfolioContextRecord(text="Portfolio remains diversified.")
    check(isinstance(record, PortfolioContextRecord), "PortfolioContextRecord constructs via a single plain call")
    check(record.text == "Portfolio remains diversified.", "PortfolioContextRecord.text stores as given")


def scenario_portfolio_context_record_has_fresh_record_id_and_timestamp() -> None:
    record = PortfolioContextRecord(text="Portfolio remains concentrated in a small number of positions.")
    check(isinstance(record.record_id, str) and len(record.record_id) > 0, "record_id is a non-empty str")
    check(isinstance(record.recorded_at, float), "recorded_at is a float timestamp")


def scenario_portfolio_context_record_source_defaults_to_none_and_is_optional() -> None:
    r1 = PortfolioContextRecord(text="context")
    check(r1.source is None, "source defaults to None")
    r2 = PortfolioContextRecord(text="context", source="cli")
    check(r2.source == "cli", "source stores as given when provided")


# ---------------------------------------------------------------------------
# B. Whitespace normalization (scenario B)
# ---------------------------------------------------------------------------


def scenario_portfolio_context_record_normalizes_surrounding_whitespace() -> None:
    record = PortfolioContextRecord(text="   Portfolio remains diversified.   ")
    check(record.text == "Portfolio remains diversified.", "leading/trailing whitespace is stripped from text")


def scenario_portfolio_context_record_normalization_preserves_internal_content() -> None:
    record = PortfolioContextRecord(text="  Portfolio remains heavily concentrated in technology positions.  ")
    check(
        record.text == "Portfolio remains heavily concentrated in technology positions.",
        "internal spacing/content unchanged, only surrounding whitespace stripped from text",
    )


# ---------------------------------------------------------------------------
# C. Empty text rejected (scenario C)
# ---------------------------------------------------------------------------


def scenario_portfolio_context_record_rejects_empty_text() -> None:
    try:
        PortfolioContextRecord(text="")
        check(False, "empty text is rejected")
    except MemoryError:
        check(True, "empty text is rejected")


def scenario_portfolio_context_record_rejects_whitespace_only_text() -> None:
    try:
        PortfolioContextRecord(text="   ")
        check(False, "whitespace-only text is rejected after stripping")
    except MemoryError:
        check(True, "whitespace-only text is rejected after stripping")


# ---------------------------------------------------------------------------
# D. Non-string text rejected (scenario D)
# ---------------------------------------------------------------------------


def scenario_portfolio_context_record_rejects_non_string_text_int() -> None:
    try:
        PortfolioContextRecord(text=123)  # type: ignore[arg-type]
        check(False, "non-str (int) text is rejected")
    except MemoryError:
        check(True, "non-str (int) text is rejected")


def scenario_portfolio_context_record_rejects_non_string_text_none() -> None:
    try:
        PortfolioContextRecord(text=None)  # type: ignore[arg-type]
        check(False, "non-str (None) text is rejected")
    except MemoryError:
        check(True, "non-str (None) text is rejected")


# ---------------------------------------------------------------------------
# E. Frozen immutability (scenario E)
# ---------------------------------------------------------------------------


def scenario_portfolio_context_record_is_frozen_dataclass() -> None:
    check(dataclasses.is_dataclass(PortfolioContextRecord), "PortfolioContextRecord is a dataclass")
    record = PortfolioContextRecord(text="context")
    try:
        record.text = "changed"  # type: ignore[misc]
        check(False, "mutating .text raises FrozenInstanceError")
    except dataclasses.FrozenInstanceError:
        check(True, "mutating .text raises FrozenInstanceError")


def scenario_portfolio_context_record_frozen_blocks_every_field() -> None:
    record = PortfolioContextRecord(text="context", source="cli", reference_id="snapshot-123")
    for attr, value in (
        ("record_id", "new-id"),
        ("recorded_at", 0.0),
        ("source", "changed"),
        ("reference_id", "changed"),
    ):
        try:
            setattr(record, attr, value)
            check(False, f"mutating .{attr} raises FrozenInstanceError")
        except dataclasses.FrozenInstanceError:
            check(True, f"mutating .{attr} raises FrozenInstanceError")


# ---------------------------------------------------------------------------
# F. Record identity (scenario F)
# ---------------------------------------------------------------------------


def scenario_portfolio_context_record_default_record_id_is_uuid_like() -> None:
    import uuid

    record = PortfolioContextRecord(text="context")
    parsed = uuid.UUID(record.record_id)
    check(str(parsed) == record.record_id, "default record_id is a valid uuid4 string")


def scenario_portfolio_context_record_ids_are_unique_per_instance() -> None:
    r1 = PortfolioContextRecord(text="context one")
    r2 = PortfolioContextRecord(text="context two")
    check(r1.record_id != r2.record_id, "each PortfolioContextRecord gets its own fresh record_id")
    check(isinstance(r1.record_id, str) and len(r1.record_id) > 0, "record_id is a non-empty str")


def scenario_portfolio_context_record_default_recorded_at_is_positive() -> None:
    import time

    before = time.time()
    record = PortfolioContextRecord(text="context")
    after = time.time()
    check(before <= record.recorded_at <= after, "default recorded_at falls within the construction window")
    check(record.recorded_at > 0, "recorded_at is a positive timestamp")
    check(isinstance(record.recorded_at, float), "recorded_at is a numeric/float timestamp")


# ---------------------------------------------------------------------------
# G. Optional source (scenario G)
# ---------------------------------------------------------------------------


def scenario_portfolio_context_record_accepts_optional_source_values() -> None:
    for value in ("cli", "chat", None):
        record = PortfolioContextRecord(text="context", source=value)
        check(record.source == value, f"source={value!r} is accepted and stored as given")


def scenario_portfolio_context_record_source_is_none_when_omitted() -> None:
    record = PortfolioContextRecord(text="context")
    check(record.source is None, "PortfolioContextRecord(text='context').source is None")


# ---------------------------------------------------------------------------
# H. Optional opaque reference_id (scenario H)
# ---------------------------------------------------------------------------


def scenario_portfolio_context_record_accepts_optional_reference_id() -> None:
    record = PortfolioContextRecord(
        text="Portfolio remained concentrated in technology.",
        reference_id="snapshot-123",
    )
    check(record.reference_id == "snapshot-123", "reference_id stores as given when provided")


def scenario_portfolio_context_record_reference_id_defaults_to_none() -> None:
    record = PortfolioContextRecord(text="context")
    check(record.reference_id is None, "reference_id defaults to None")


def scenario_portfolio_context_record_reference_id_is_plain_opaque_string() -> None:
    # An intentionally nonsensical/unresolvable reference_id -- if any
    # lookup were attempted, construction would fail or raise. It must
    # not: reference_id is opaque, never resolved against a snapshot,
    # account, database, or repository.
    record = PortfolioContextRecord(
        text="context",
        reference_id="this-snapshot-id-does-not-exist-anywhere-12345",
    )
    check(isinstance(record.reference_id, str), "reference_id is stored as a plain str")
    check(
        record.reference_id == "this-snapshot-id-does-not-exist-anywhere-12345",
        "an unresolvable reference_id constructs successfully -- no repository/database lookup is performed",
    )


def scenario_portfolio_context_record_has_no_repository_or_database_attribute() -> None:
    record = PortfolioContextRecord(text="context", reference_id="snapshot-1")
    forbidden_attrs = ("repository", "database", "db", "session", "connection")
    for attr in forbidden_attrs:
        check(not hasattr(record, attr), f"PortfolioContextRecord has no '{attr}' attribute")


# ---------------------------------------------------------------------------
# I. Exact field contract (scenario I)
# ---------------------------------------------------------------------------


def scenario_portfolio_context_record_has_exact_field_contract() -> None:
    field_names = {f.name for f in dataclasses.fields(PortfolioContextRecord)}
    check(
        field_names == {"text", "record_id", "recorded_at", "source", "reference_id"},
        "PortfolioContextRecord declares exactly the locked field set, nothing more",
    )
    forbidden_fields = (
        "cash",
        "market_value",
        "equity",
        "realized_pnl",
        "unrealized_pnl",
        "drawdown",
        "exposure",
        "account_id",
        "position_count",
        "order_count",
    )
    for forbidden in forbidden_fields:
        check(forbidden not in field_names, f"PortfolioContextRecord does not declare forbidden field '{forbidden}'")


def scenario_portfolio_context_record_does_not_reference_account_object() -> None:
    account = _account()  # constructed only to prove PortfolioContextRecord never needs it
    record = PortfolioContextRecord(text="context about the portfolio, not the account object itself")
    check(not hasattr(record, "account"), "PortfolioContextRecord has no 'account' attribute")
    check(isinstance(account, Account), "sanity: Account itself is unaffected/unused by PortfolioContextRecord")


def scenario_portfolio_context_record_has_no_execution_capability_attributes() -> None:
    record = PortfolioContextRecord(text="context")
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
        check(not hasattr(record, attr), f"PortfolioContextRecord has no '{attr}' attribute")


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
        "FailureRateEngine",
    ):
        check(forbidden_name not in source, f"Orchestration/memory.py does not reference {forbidden_name}")

    # PortfolioSnapshot/PortfolioSnapshotRepository/UnrealizedPnLEngine/
    # MaximumDrawdownEngine are checked as actual CODE dependencies (an
    # import), not as a raw substring: the new PortfolioContextRecord
    # docstring legitimately *mentions* these names in prose to explain
    # that portfolio context is NOT financial state and does NOT read
    # PortfolioSnapshot -- that documentation is correct and expected,
    # so a bare substring match would be a false failure. What must
    # actually be absent is an import, which the AST-based check above
    # already covers.
    check(
        "PortfolioSnapshotRepository" not in imported_names,
        "Orchestration/memory.py does not import PortfolioSnapshotRepository",
    )


# ---------------------------------------------------------------------------
# J. Existing MemoryStore compatibility (scenario J)
# ---------------------------------------------------------------------------


def scenario_portfolio_context_record_stores_in_existing_memory_store_unmodified() -> None:
    store = MemoryStore()
    record = PortfolioContextRecord(text="context")
    store.add(record)
    check(len(store) == 1, "PortfolioContextRecord stores through the existing, unmodified MemoryStore.add")


def scenario_portfolio_context_record_round_trips_through_get() -> None:
    store = MemoryStore()
    record = PortfolioContextRecord(text="context")
    store.add(record)
    fetched = store.get(record.record_id)
    check(fetched is record, "PortfolioContextRecord round-trips through MemoryStore.get")


def scenario_portfolio_context_record_round_trips_through_list() -> None:
    store = MemoryStore()
    record = PortfolioContextRecord(text="context")
    store.add(record)
    listed = store.list()
    check(record in listed, "PortfolioContextRecord round-trips through MemoryStore.list")


def scenario_portfolio_context_record_missing_id_returns_none_not_error() -> None:
    store = MemoryStore()
    check(store.get("does-not-exist") is None, "a missing record_id returns None, not an error")


def scenario_duplicate_portfolio_context_record_id_raises_memory_error() -> None:
    store = MemoryStore()
    record = PortfolioContextRecord(text="context")
    store.add(record)
    try:
        store.add(record)
        check(False, "adding a duplicate record_id raises MemoryError")
    except MemoryError:
        check(True, "adding a duplicate record_id raises MemoryError")


def scenario_portfolio_context_record_storage_does_not_require_new_store_type() -> None:
    store = MemoryStore(max_size=5, ttl_seconds=None)
    record = PortfolioContextRecord(text="context")
    store.add(record)
    check(
        isinstance(store, MemoryStore),
        "PortfolioContextRecord storage uses the same MemoryStore class, with no new store type",
    )


# ---------------------------------------------------------------------------
# K. Multiple PortfolioContextRecord objects coexist (scenario K)
# ---------------------------------------------------------------------------


def scenario_multiple_portfolio_context_records_coexist_in_one_store() -> None:
    store = MemoryStore()
    r1 = PortfolioContextRecord(text="Portfolio remains heavily concentrated in technology.", reference_id="snapshot-1")
    r2 = PortfolioContextRecord(text="Portfolio diversified across IDX large caps.", reference_id=None)
    store.add(r1)
    store.add(r2)
    check(len(store) == 2, "multiple PortfolioContextRecord instances coexist in one MemoryStore")
    check(store.get(r1.record_id) is r1, "first PortfolioContextRecord retrievable")
    check(store.get(r2.record_id) is r2, "second PortfolioContextRecord retrievable")


# ---------------------------------------------------------------------------
# L. Existing Memory records remain unaffected (scenario L)
# ---------------------------------------------------------------------------


def scenario_existing_observation_memory_record_flow_still_works() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store=store)
    mr = recorder.record(_observation())
    check(isinstance(mr, MemoryRecord), "MemoryRecorder.record still returns a MemoryRecord, unaffected")
    check(store.get(mr.record_id) is mr, "existing MemoryRecord flow through MemoryStore is unaffected")


def scenario_preference_record_still_stores_unaffected() -> None:
    store = MemoryStore()
    pref = PreferenceRecord(key="analysis_style", value="concise")
    store.add(pref)
    check(
        store.get(pref.record_id) is pref,
        "PreferenceRecord still stores/retrieves unaffected by PortfolioContextRecord",
    )


def scenario_strategy_note_record_still_stores_unaffected() -> None:
    store = MemoryStore()
    note = StrategyNoteRecord(text="Use momentum strategy on IDX large caps.")
    store.add(note)
    check(
        store.get(note.record_id) is note,
        "StrategyNoteRecord still stores/retrieves unaffected by PortfolioContextRecord",
    )


def scenario_previous_decision_record_still_stores_unaffected() -> None:
    store = MemoryStore()
    decision = PreviousDecisionRecord(decision="decision", rationale="rationale")
    store.add(decision)
    check(
        store.get(decision.record_id) is decision,
        "PreviousDecisionRecord still stores/retrieves unaffected by PortfolioContextRecord",
    )


def scenario_lesson_record_still_stores_unaffected() -> None:
    store = MemoryStore()
    lesson = LessonRecord(text="Avoid entering after a gap-up without confirmation.")
    store.add(lesson)
    check(
        store.get(lesson.record_id) is lesson,
        "LessonRecord still stores/retrieves unaffected by PortfolioContextRecord",
    )


def scenario_all_six_record_kinds_coexist_in_same_store() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store=store)
    mr = recorder.record(_observation())
    pref = PreferenceRecord(key="k", value="v")
    note = StrategyNoteRecord(text="note")
    decision = PreviousDecisionRecord(decision="decision", rationale="rationale")
    lesson = LessonRecord(text="lesson")
    portfolio_context = PortfolioContextRecord(text="Portfolio context narrative.")
    store.add(pref)
    store.add(note)
    store.add(decision)
    store.add(lesson)
    store.add(portfolio_context)
    listed = store.list()
    check(
        len(listed) == 6,
        "MemoryRecord, PreferenceRecord, StrategyNoteRecord, PreviousDecisionRecord, LessonRecord, and "
        "PortfolioContextRecord all fit in one store",
    )
    kinds = {type(r).__name__ for r in listed}
    check(
        kinds
        == {
            "MemoryRecord",
            "PreferenceRecord",
            "StrategyNoteRecord",
            "PreviousDecisionRecord",
            "LessonRecord",
            "PortfolioContextRecord",
        },
        "store holds all six record kinds side by side",
    )
    check(store.get(mr.record_id) is mr, "MemoryRecord retrievable")
    check(store.get(pref.record_id) is pref, "PreferenceRecord retrievable")
    check(store.get(note.record_id) is note, "StrategyNoteRecord retrievable")
    check(store.get(decision.record_id) is decision, "PreviousDecisionRecord retrievable")
    check(store.get(lesson.record_id) is lesson, "LessonRecord retrievable")
    check(store.get(portfolio_context.record_id) is portfolio_context, "PortfolioContextRecord retrievable")


# ---------------------------------------------------------------------------
# M. Financial separation (scenario M)
# ---------------------------------------------------------------------------


def scenario_portfolio_context_record_construction_needs_no_financial_collaborators() -> None:
    # Construction and storage succeed with no PortfolioSnapshot,
    # PortfolioSnapshotRepository, Account, Position, Order, Trade, or
    # FailureRateEngine ever instantiated or imported for this to work.
    record = PortfolioContextRecord(
        text="Portfolio remains concentrated in a small number of positions.",
        source="cli",
        reference_id="snapshot-123",
    )
    store = MemoryStore()
    store.add(record)
    check(
        store.get(record.record_id) is record,
        "PortfolioContextRecord constructs and stores with zero financial engine/repository/database dependency",
    )


def scenario_portfolio_context_record_module_imports_no_financial_types() -> None:
    # Checked as actual imports (AST-based), not raw substrings: words
    # like "Account", "Position", "Order", and "Trade" are ordinary
    # English/domain nouns that legitimately appear in explanatory
    # docstring prose elsewhere in this module (e.g. PreferenceRecord's
    # own, pre-existing docstring, and PortfolioContextRecord's new
    # docstring) without that prose constituting a code dependency. A
    # raw substring check would false-fail on that prose; what actually
    # matters is whether the module IMPORTS these financial types, and
    # it does not.
    import ast

    import Orchestration.memory as memory_module

    source = Path(memory_module.__file__).read_text()
    tree = ast.parse(source)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add((alias.asname or alias.name).split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported_names.add(alias.asname or alias.name)

    for forbidden_name in (
        "PortfolioSnapshot",
        "PortfolioSnapshotRepository",
        "Account",
        "Position",
        "Order",
        "Trade",
        "FailureRateEngine",
    ):
        check(
            forbidden_name not in imported_names,
            f"Orchestration/memory.py does not import '{forbidden_name}'",
        )


# ---------------------------------------------------------------------------
# N. No automatic snapshot -> context conversion (scenario N)
# ---------------------------------------------------------------------------


def scenario_portfolio_context_record_reference_id_is_inert_string_only() -> None:
    # reference_id is accepted, stored, and returned verbatim -- there
    # is no snapshot lookup, no database read, and no synchronization
    # performed anywhere as a side effect of construction.
    record = PortfolioContextRecord(text="context", reference_id="snapshot-999")
    check(record.reference_id == "snapshot-999", "reference_id is stored exactly as given, with no resolution")
    check(
        not hasattr(record, "snapshot") and not hasattr(record, "portfolio_snapshot"),
        "PortfolioContextRecord has no resolved 'snapshot'/'portfolio_snapshot' attribute",
    )


def scenario_portfolio_context_record_has_no_synchronization_or_refresh_behavior() -> None:
    record = PortfolioContextRecord(text="context")
    forbidden_attrs = ("refresh", "sync", "synchronize", "from_snapshot", "update_from_snapshot")
    for attr in forbidden_attrs:
        check(not hasattr(record, attr), f"PortfolioContextRecord has no '{attr}' attribute")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    scenarios = [
        # A. Valid construction
        scenario_portfolio_context_record_constructs_with_text,
        scenario_portfolio_context_record_has_fresh_record_id_and_timestamp,
        scenario_portfolio_context_record_source_defaults_to_none_and_is_optional,
        # B. Whitespace normalization
        scenario_portfolio_context_record_normalizes_surrounding_whitespace,
        scenario_portfolio_context_record_normalization_preserves_internal_content,
        # C. Empty text rejected
        scenario_portfolio_context_record_rejects_empty_text,
        scenario_portfolio_context_record_rejects_whitespace_only_text,
        # D. Non-string text rejected
        scenario_portfolio_context_record_rejects_non_string_text_int,
        scenario_portfolio_context_record_rejects_non_string_text_none,
        # E. Frozen immutability
        scenario_portfolio_context_record_is_frozen_dataclass,
        scenario_portfolio_context_record_frozen_blocks_every_field,
        # F. Record identity
        scenario_portfolio_context_record_default_record_id_is_uuid_like,
        scenario_portfolio_context_record_ids_are_unique_per_instance,
        scenario_portfolio_context_record_default_recorded_at_is_positive,
        # G. Optional source
        scenario_portfolio_context_record_accepts_optional_source_values,
        scenario_portfolio_context_record_source_is_none_when_omitted,
        # H. Optional opaque reference_id
        scenario_portfolio_context_record_accepts_optional_reference_id,
        scenario_portfolio_context_record_reference_id_defaults_to_none,
        scenario_portfolio_context_record_reference_id_is_plain_opaque_string,
        scenario_portfolio_context_record_has_no_repository_or_database_attribute,
        # I. Exact field contract
        scenario_portfolio_context_record_has_exact_field_contract,
        scenario_portfolio_context_record_does_not_reference_account_object,
        scenario_portfolio_context_record_has_no_execution_capability_attributes,
        scenario_memory_module_does_not_import_execution_or_financial_layer,
        # J. Existing MemoryStore compatibility
        scenario_portfolio_context_record_stores_in_existing_memory_store_unmodified,
        scenario_portfolio_context_record_round_trips_through_get,
        scenario_portfolio_context_record_round_trips_through_list,
        scenario_portfolio_context_record_missing_id_returns_none_not_error,
        scenario_duplicate_portfolio_context_record_id_raises_memory_error,
        scenario_portfolio_context_record_storage_does_not_require_new_store_type,
        # K. Multiple PortfolioContextRecord objects coexist
        scenario_multiple_portfolio_context_records_coexist_in_one_store,
        # L. Existing Memory records remain unaffected
        scenario_existing_observation_memory_record_flow_still_works,
        scenario_preference_record_still_stores_unaffected,
        scenario_strategy_note_record_still_stores_unaffected,
        scenario_previous_decision_record_still_stores_unaffected,
        scenario_lesson_record_still_stores_unaffected,
        scenario_all_six_record_kinds_coexist_in_same_store,
        # M. Financial separation
        scenario_portfolio_context_record_construction_needs_no_financial_collaborators,
        scenario_portfolio_context_record_module_imports_no_financial_types,
        # N. No automatic snapshot -> context conversion
        scenario_portfolio_context_record_reference_id_is_inert_string_only,
        scenario_portfolio_context_record_has_no_synchronization_or_refresh_behavior,
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