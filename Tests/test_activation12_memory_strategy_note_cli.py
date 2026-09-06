"""
Activation 12 Memory (Strategy Notes) proof suite -- production wiring
for the ``strategy-note`` CLI command.

Scope: this suite proves the REAL user-facing path -- ``main.py``'s
``strategy-note add|list`` CLI command -- actually stores and retrieves
:class:`~Orchestration.memory.StrategyNoteRecord` objects through the
existing, unmodified ``app.memory_store`` (the single ``MemoryStore``
instance ``Core.composition_root.ApplicationGraph`` already builds), and
that nothing else on ``FakeApp``/the financial layer is touched while
doing so.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``Tests/test_activation12_memory_preference_wiring.py`` and
``Tests/test_activation12_memory_strategy_note_record.py``: a global
pass/fail counter, plain fakes, and a ``main()`` runner.

Explicitly NOT tested here (out of scope for this step, see the
Activation 12 Memory Strategy Note CLI prompt): previous-decision
memory, lessons-from-failed-trades memory, portfolio memory, vector/
embeddings storage, GoalPlanner/scheduler/planner integration,
persistence across a process restart, or ``strategy-note get/remove/
edit/search``.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import List

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import main  # noqa: E402
from Core.composition_root import build_application  # noqa: E402
from Orchestration.memory import (  # noqa: E402
    MemoryError,
    MemoryRecord,
    MemoryRecorder,
    MemoryStore,
    PreferenceRecord,
    StrategyNoteRecord,
)
from Orchestration.observation import ObservationRecorder  # noqa: E402
from Orchestration.planner import ExecutionPlan, Goal, PlanStep  # noqa: E402
from Services.service_result import ServiceResult  # noqa: E402

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


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeApp:
    """Stands in for ``Core.composition_root.ApplicationGraph`` -- only
    the one attribute the strategy-note command path actually reads:
    ``memory_store``. No financial collaborators (``PaperTradingEngine``,
    ``ExecutionService``, account/position/order/trade repositories) are
    present on this fake at all -- if a code path under test ever tried
    to reach one, it would fail with ``AttributeError``, not silently
    succeed against a stub.
    """

    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory_store = memory_store


def _observation():
    """A minimal, real ``Observation`` -- used only to prove existing
    observation-based ``MemoryRecord`` flow is unaffected by this wiring."""
    goal = Goal(metadata={"ticker": "BBCA.JK"})
    plan = ExecutionPlan(goal=goal, steps=(PlanStep(service_name="svc"),))
    results = [ServiceResult.ok(data={"price": 100})]
    return ObservationRecorder().record(goal=goal, plan=plan, results=results)


# ---------------------------------------------------------------------------
# A. 'strategy-note add' creates a StrategyNoteRecord
# ---------------------------------------------------------------------------


def scenario_strategy_note_add_stores_a_strategy_note_record() -> None:
    print("\n[Scenario A1] 'strategy-note add' stores a StrategyNoteRecord in app.memory_store")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        rc = main._run_strategy_note_command(
            app, ["add", "Use", "momentum", "confirmation", "before", "entering"]
        )

    check(rc == 0, "'strategy-note add' returns exit code 0 on success")
    check(len(store) == 1, "exactly one record is stored")
    stored = store.list()[0]
    check(isinstance(stored, StrategyNoteRecord), "the stored record is a StrategyNoteRecord")
    check(
        stored.text == "Use momentum confirmation before entering",
        "stored record's text matches the joined CLI arguments",
    )


def scenario_strategy_note_add_prints_confirmation() -> None:
    print("\n[Scenario A2] 'strategy-note add' prints a confirmation naming the note text")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_strategy_note_command(app, ["add", "Avoid", "overtrading", "on", "Fridays"])
    output = buf.getvalue()

    check("Avoid overtrading on Fridays" in output, "confirmation output includes the strategy note text")


# ---------------------------------------------------------------------------
# B. Multi-word text joins correctly
# ---------------------------------------------------------------------------


def scenario_strategy_note_add_joins_multiple_words() -> None:
    print("\n[Scenario B1] multi-word 'strategy-note add' text joins with single spaces")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_strategy_note_command(
            app,
            ["add", "Avoid", "trading", "immediately", "after", "major", "earnings"],
        )

    stored = store.list()[0]
    check(
        stored.text == "Avoid trading immediately after major earnings",
        "multi-word text is joined into a single space-separated string",
    )


# ---------------------------------------------------------------------------
# C. Leading/trailing whitespace normalized by StrategyNoteRecord, not CLI
# ---------------------------------------------------------------------------


def scenario_strategy_note_text_normalization_comes_from_the_record_not_the_cli() -> None:
    print("\n[Scenario C1] whitespace normalization is StrategyNoteRecord's job, CLI just joins+strips the whole string")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_strategy_note_command(app, ["add", "  Trim", "the", "edges  "])

    stored = store.list()[0]
    check(not stored.text.startswith(" "), "no leading whitespace survives in the stored text")
    check(not stored.text.endswith(" "), "no trailing whitespace survives in the stored text")


# ---------------------------------------------------------------------------
# D. Empty/missing text produces clean CLI error
# ---------------------------------------------------------------------------


def scenario_strategy_note_add_missing_text_fails_explicitly() -> None:
    print("\n[Scenario D1] 'strategy-note add' with no TEXT argument fails explicitly, no traceback")
    store = MemoryStore()
    app = FakeApp(store)

    buf = io.StringIO()
    raised = False
    try:
        with redirect_stdout(buf):
            rc = main._run_strategy_note_command(app, ["add"])
    except Exception:  # noqa: BLE001
        raised = True
        rc = None
    output = buf.getvalue()

    check(not raised, "a missing TEXT argument does not raise a raw traceback")
    check(rc != 0, "'strategy-note add' with missing text returns a non-zero exit code")
    check(len(store) == 0, "no record is stored when the command is rejected")
    check("Invalid strategy note" in output, "output explicitly names the failure rather than failing silently")


def scenario_strategy_note_add_whitespace_only_text_fails_explicitly() -> None:
    print("\n[Scenario D2] 'strategy-note add' with only whitespace tokens fails explicitly")
    store = MemoryStore()
    app = FakeApp(store)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_strategy_note_command(app, ["add", "   ", "  "])
    output = buf.getvalue()

    check(rc != 0, "whitespace-only text returns a non-zero exit code")
    check(len(store) == 0, "no record is stored for whitespace-only text")
    check("Invalid strategy note" in output, "output explicitly names the failure")


# ---------------------------------------------------------------------------
# E. 'strategy-note list' retrieves notes
# ---------------------------------------------------------------------------


def scenario_strategy_note_list_shows_stored_note() -> None:
    print("\n[Scenario E1] 'strategy-note list' shows a note 'strategy-note add' just stored")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_strategy_note_command(app, ["add", "Wait", "for", "confirmation", "candle"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_strategy_note_command(app, ["list"])
    output = buf.getvalue()

    check(rc == 0, "'strategy-note list' returns exit code 0")
    check("Wait for confirmation candle" in output, "'strategy-note list' output includes the stored text")


def scenario_strategy_note_list_empty_store_reports_zero_notes() -> None:
    print("\n[Scenario E2] 'strategy-note list' on an empty store reports zero notes, does not raise")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    raised = False
    try:
        with redirect_stdout(buf):
            rc = main._run_strategy_note_command(app, ["list"])
    except Exception:  # noqa: BLE001
        raised = True
        rc = None
    output = buf.getvalue()

    check(not raised, "listing an empty store does not raise")
    check(rc == 0, "'strategy-note list' on an empty store still returns exit code 0")
    check("Strategy Notes (0)" in output, "output honestly reports there are zero notes")


# ---------------------------------------------------------------------------
# F. Multiple notes preserve MemoryStore insertion order
# ---------------------------------------------------------------------------


def scenario_strategy_note_list_preserves_insertion_order() -> None:
    print("\n[Scenario F1] multiple strategy notes are listed in MemoryStore insertion order, not reversed/sorted")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_strategy_note_command(app, ["add", "First", "note"])
        main._run_strategy_note_command(app, ["add", "Second", "note"])
        main._run_strategy_note_command(app, ["add", "Third", "note"])

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_strategy_note_command(app, ["list"])
    output = buf.getvalue()

    first_pos = output.index("First note")
    second_pos = output.index("Second note")
    third_pos = output.index("Third note")
    check(first_pos < second_pos < third_pos, "notes appear in the exact order they were added")

    texts = [r.text for r in store.list() if isinstance(r, StrategyNoteRecord)]
    check(
        texts == ["First note", "Second note", "Third note"],
        "MemoryStore.list() itself preserves insertion order for strategy notes",
    )


# ---------------------------------------------------------------------------
# G. Preference records are not displayed as strategy notes
# ---------------------------------------------------------------------------


def scenario_preference_records_are_not_displayed_as_strategy_notes() -> None:
    print("\n[Scenario G1] a PreferenceRecord in the same store is not listed by 'strategy-note list'")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_preference_command(app, ["set", "report_verbosity", "concise"])
        main._run_strategy_note_command(app, ["add", "Only", "trade", "the", "trend"])

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_strategy_note_command(app, ["list"])
    output = buf.getvalue()

    check("Strategy Notes (1)" in output, "only the one StrategyNoteRecord is counted")
    check("report_verbosity" not in output, "the PreferenceRecord's key does not leak into strategy-note output")
    check("concise" not in output, "the PreferenceRecord's value does not leak into strategy-note output")


# ---------------------------------------------------------------------------
# H. Existing analysis MemoryRecord objects are not displayed as strategy notes
# ---------------------------------------------------------------------------


def scenario_observation_memory_records_are_not_displayed_as_strategy_notes() -> None:
    print("\n[Scenario H1] an observation-derived MemoryRecord in the same store is not listed by 'strategy-note list'")
    store = MemoryStore()
    app = FakeApp(store)
    recorder = MemoryRecorder(store=store)

    mr = recorder.record(_observation())
    with redirect_stdout(io.StringIO()):
        main._run_strategy_note_command(app, ["add", "Respect", "the", "stop", "loss"])

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_strategy_note_command(app, ["list"])
    output = buf.getvalue()

    check("Strategy Notes (1)" in output, "only the one StrategyNoteRecord is counted, not the MemoryRecord too")
    listed = store.list()
    check(len(listed) == 2, "both records coexist in the one shared store")
    check(store.get(mr.record_id) is mr, "the observation MemoryRecord is unaffected by the strategy-note command")


# ---------------------------------------------------------------------------
# I. Source is "cli"
# ---------------------------------------------------------------------------


def scenario_strategy_note_add_sets_source_cli() -> None:
    print("\n[Scenario I1] a note stored via 'strategy-note add' has source='cli'")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_strategy_note_command(app, ["add", "Size", "positions", "conservatively"])

    stored = store.list()[0]
    check(stored.source == "cli", "the stored StrategyNoteRecord's source is exactly 'cli'")


# ---------------------------------------------------------------------------
# J. No second MemoryStore is constructed
# ---------------------------------------------------------------------------


def scenario_strategy_note_command_reuses_the_passed_in_memory_store_instance() -> None:
    print("\n[Scenario J1] the strategy-note command path stores into the exact MemoryStore instance it was given")
    store = MemoryStore()
    store_id_before = id(store)
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_strategy_note_command(app, ["add", "One", "note"])

    check(id(app.memory_store) == store_id_before, "app.memory_store is still the same object identity after the command runs")
    check(len(store) == 1, "the record landed in the original store instance, not a second one")


def scenario_two_fake_apps_with_distinct_stores_do_not_leak_into_each_other() -> None:
    print("\n[Scenario J2] two FakeApps with distinct MemoryStores stay fully isolated (no shared/global store)")
    store_a = MemoryStore()
    store_b = MemoryStore()
    app_a = FakeApp(store_a)
    app_b = FakeApp(store_b)

    with redirect_stdout(io.StringIO()):
        main._run_strategy_note_command(app_a, ["add", "from_a"])

    check(len(store_a) == 1, "store_a received the record added through app_a")
    check(len(store_b) == 0, "store_b is untouched -- no global/shared MemoryStore singleton is used")


def scenario_build_application_wires_exactly_one_memory_store_for_strategy_notes() -> None:
    print("\n[Scenario J3] a real build_application() app stores strategy notes into its own single memory_store")
    app = build_application()
    store_id_before = id(app.memory_store)

    with redirect_stdout(io.StringIO()):
        rc = main._run_strategy_note_command(app, ["add", "Confirm", "trend", "with", "volume"])

    check(rc == 0, "'strategy-note add' succeeds against a real build_application() app")
    check(id(app.memory_store) == store_id_before, "the real app's memory_store identity is unchanged after the command")
    notes = [r for r in app.memory_store.list() if isinstance(r, StrategyNoteRecord)]
    check(len(notes) == 1, "exactly one StrategyNoteRecord landed in the real app's single memory_store")


# ---------------------------------------------------------------------------
# K. Financial state is untouched / L. PaperTradingEngine is untouched
# ---------------------------------------------------------------------------


def scenario_strategy_note_commands_never_touch_financial_or_execution_attributes() -> None:
    print("\n[Scenario K1/L1] FakeApp has no financial/execution collaborators for the strategy-note path to reach")
    # FakeApp deliberately exposes only ``memory_store`` -- no
    # PaperTradingEngine, ExecutionService, account/position/order/trade
    # repository. If any strategy-note command path tried to reach one
    # of those, it would raise AttributeError, not silently succeed.
    store = MemoryStore()
    app = FakeApp(store)
    forbidden_attrs = (
        "paper_trading_engine",
        "execution_coordinator",
        "execution_planner",
        "account_repository",
        "position_repository",
        "order_repository",
        "trade_repository",
    )
    for attr in forbidden_attrs:
        check(not hasattr(app, attr), f"FakeApp has no '{attr}' collaborator for the strategy-note path to call")

    raised = False
    try:
        with redirect_stdout(io.StringIO()):
            main._run_strategy_note_command(app, ["add", "Do", "not", "overtrade"])
            main._run_strategy_note_command(app, ["list"])
    except AttributeError:
        raised = True
    check(not raised, "the full add/list strategy-note path runs to completion touching only memory_store")


def scenario_strategy_note_record_source_module_has_no_financial_imports() -> None:
    print("\n[Scenario K2/L2] Orchestration/memory.py still does not import the financial/execution layer")
    import Orchestration.memory as memory_module

    source = Path(memory_module.__file__).read_text()
    for forbidden in ("PaperTradingEngine", "ToolRegistry", "ToolResolver", "ExecutionService"):
        check(forbidden not in source, f"Orchestration/memory.py does not reference {forbidden}")


# ---------------------------------------------------------------------------
# Additional: unknown subcommand / no subcommand fail explicitly
# ---------------------------------------------------------------------------


def scenario_strategy_note_command_unknown_subcommand_fails_explicitly() -> None:
    print("\n[Scenario Extra1] an unknown 'strategy-note' subcommand fails explicitly")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_strategy_note_command(app, ["frobnicate"])
    output = buf.getvalue()

    check(rc != 0, "an unknown subcommand returns a non-zero exit code")
    check("Unknown strategy-note subcommand" in output, "output names the unknown subcommand explicitly")


def scenario_strategy_note_command_no_subcommand_fails_explicitly() -> None:
    print("\n[Scenario Extra2] 'strategy-note' with no subcommand at all fails explicitly")
    app = FakeApp(MemoryStore())

    with redirect_stdout(io.StringIO()):
        rc = main._run_strategy_note_command(app, [])

    check(rc != 0, "'strategy-note' with no subcommand returns a non-zero exit code")


# ---------------------------------------------------------------------------
# M. A fresh process has no previous strategy notes (honest process-local behavior)
# ---------------------------------------------------------------------------


def scenario_strategy_notes_do_not_survive_a_fresh_memory_store_representing_a_restart() -> None:
    print("\n[Scenario M1] a fresh MemoryStore (simulating process restart) has no prior strategy notes")
    store = MemoryStore()
    app = FakeApp(store)
    with redirect_stdout(io.StringIO()):
        main._run_strategy_note_command(app, ["add", "Note", "before", "restart"])
    check(len(store) == 1, "the strategy note is present within this process's MemoryStore")

    # A restart means a brand new process, which means a brand new
    # ApplicationGraph/_build_memory_store() call -- there is no
    # database or file backing this store, so a fresh MemoryStore
    # stands in honestly for "after restart" here.
    restarted_store = MemoryStore()
    restarted_app = FakeApp(restarted_store)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_strategy_note_command(restarted_app, ["list"])
    output = buf.getvalue()

    check(rc == 0, "'strategy-note list' still succeeds after a simulated restart")
    check("Strategy Notes (0)" in output, "the command is honest that the prior note is gone, not silently wrong")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main_() -> int:
    scenarios = [
        # Group A
        scenario_strategy_note_add_stores_a_strategy_note_record,
        scenario_strategy_note_add_prints_confirmation,
        # Group B
        scenario_strategy_note_add_joins_multiple_words,
        # Group C
        scenario_strategy_note_text_normalization_comes_from_the_record_not_the_cli,
        # Group D
        scenario_strategy_note_add_missing_text_fails_explicitly,
        scenario_strategy_note_add_whitespace_only_text_fails_explicitly,
        # Group E
        scenario_strategy_note_list_shows_stored_note,
        scenario_strategy_note_list_empty_store_reports_zero_notes,
        # Group F
        scenario_strategy_note_list_preserves_insertion_order,
        # Group G
        scenario_preference_records_are_not_displayed_as_strategy_notes,
        # Group H
        scenario_observation_memory_records_are_not_displayed_as_strategy_notes,
        # Group I
        scenario_strategy_note_add_sets_source_cli,
        # Group J
        scenario_strategy_note_command_reuses_the_passed_in_memory_store_instance,
        scenario_two_fake_apps_with_distinct_stores_do_not_leak_into_each_other,
        scenario_build_application_wires_exactly_one_memory_store_for_strategy_notes,
        # Group K/L
        scenario_strategy_note_commands_never_touch_financial_or_execution_attributes,
        scenario_strategy_note_record_source_module_has_no_financial_imports,
        # Extra dispatch coverage
        scenario_strategy_note_command_unknown_subcommand_fails_explicitly,
        scenario_strategy_note_command_no_subcommand_fails_explicitly,
        # Group M
        scenario_strategy_notes_do_not_survive_a_fresh_memory_store_representing_a_restart,
    ]

    for scenario in scenarios:
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 12 MEMORY STRATEGY NOTE CLI RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main_())