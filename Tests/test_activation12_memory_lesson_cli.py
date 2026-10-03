"""
Activation 12 Memory (Lessons From Failed Trades) proof suite --
production wiring for the ``lesson`` CLI command.

Scope: this suite proves the REAL user-facing path -- ``main.py``'s
``lesson add|list`` CLI command -- actually stores and retrieves
:class:`~Orchestration.memory.LessonRecord` objects through the
existing, unmodified ``app.memory_store`` (the single ``MemoryStore``
instance ``Core.composition_root.ApplicationGraph`` already builds),
and that nothing else on ``FakeApp``/the financial layer is touched
while doing so.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``Tests/test_activation12_memory_strategy_note_cli.py`` and
``Tests/test_activation12_memory_previous_decision_cli.py``: a global
pass/fail counter, plain fakes, and a ``main()`` runner.

Explicitly NOT tested here (out of scope for this atomic step, see the
Activation 12 Lesson Memory CLI prompt): automatic lesson extraction,
failed-trade classification, rejected-order integration, losing-trade
classification, P/L integration, ``FailureRateEngine`` integration,
``ReflectionRecord``/``LearningLoop`` integration, database or
repository persistence, embeddings/vector memory, or ``lesson
get/remove/edit/search``.
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
    LessonRecord,
    MemoryError,
    MemoryRecord,
    MemoryRecorder,
    MemoryStore,
    PreferenceRecord,
    PreviousDecisionRecord,
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
    the one attribute the lesson command path actually reads:
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
# A. 'lesson add' creates a LessonRecord
# ---------------------------------------------------------------------------


def scenario_lesson_add_stores_a_lesson_record() -> None:
    print("\n[Scenario A1] 'lesson add' stores a LessonRecord in app.memory_store")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        rc = main._run_lesson_command(
            app, ["add", "Avoid", "entering", "before", "confirmation"]
        )

    check(rc == 0, "'lesson add' returns exit code 0 on success")
    check(len(store) == 1, "exactly one record is stored")
    stored = store.list()[0]
    check(isinstance(stored, LessonRecord), "the stored record is a LessonRecord")
    check(
        stored.text == "Avoid entering before confirmation",
        "stored record's text matches the joined CLI arguments",
    )
    check(stored.source == "cli", "the stored LessonRecord's source is exactly 'cli'")
    check(stored.reference_id is None, "the stored LessonRecord's reference_id is None (no auto-generation)")


def scenario_lesson_add_prints_confirmation() -> None:
    print("\n[Scenario A2] 'lesson add' prints a confirmation naming the lesson text")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_lesson_command(app, ["add", "Wait", "for", "volume", "confirmation"])
    output = buf.getvalue()

    check("Wait for volume confirmation" in output, "confirmation output includes the lesson text")


# ---------------------------------------------------------------------------
# B. Multi-word text joins correctly
# ---------------------------------------------------------------------------


def scenario_lesson_add_joins_multiple_words() -> None:
    print("\n[Scenario B1] multi-word 'lesson add' text joins with single spaces")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_lesson_command(
            app,
            ["add", "Do", "not", "chase", "a", "rejected", "setup"],
        )

    stored = store.list()[0]
    check(
        stored.text == "Do not chase a rejected setup",
        "multi-word text is joined into a single space-separated string",
    )


# ---------------------------------------------------------------------------
# C. Empty/whitespace-only text produces clean CLI error (Scenario C in prompt)
# ---------------------------------------------------------------------------


def scenario_lesson_add_missing_text_fails_explicitly() -> None:
    print("\n[Scenario C1/D1] 'lesson add' with no TEXT argument fails explicitly, no traceback")
    store = MemoryStore()
    app = FakeApp(store)

    buf = io.StringIO()
    raised = False
    try:
        with redirect_stdout(buf):
            rc = main._run_lesson_command(app, ["add"])
    except Exception:  # noqa: BLE001
        raised = True
        rc = None
    output = buf.getvalue()

    check(not raised, "a missing TEXT argument does not raise a raw traceback")
    check(rc != 0, "'lesson add' with missing text returns a non-zero exit code")
    check(len(store) == 0, "no record is stored when the command is rejected")
    check("Invalid lesson" in output, "output explicitly names the failure rather than failing silently")


def scenario_lesson_add_whitespace_only_text_fails_explicitly() -> None:
    print("\n[Scenario C2] 'lesson add \"   \"' (whitespace-only text) fails explicitly")
    store = MemoryStore()
    app = FakeApp(store)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_lesson_command(app, ["add", "   ", "  "])
    output = buf.getvalue()

    check(rc != 0, "whitespace-only text returns a non-zero exit code")
    check(len(store) == 0, "no record is stored for whitespace-only text")
    check("Invalid lesson" in output, "output explicitly names the failure")


# ---------------------------------------------------------------------------
# D. Missing arguments ('lesson' with no subcommand)
# ---------------------------------------------------------------------------


def scenario_lesson_command_no_subcommand_fails_explicitly() -> None:
    print("\n[Scenario D2] 'lesson' with no subcommand at all fails explicitly")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_lesson_command(app, [])
    output = buf.getvalue()

    check(rc != 0, "'lesson' with no subcommand returns a non-zero exit code")
    check("Usage: python main.py lesson" in output, "usage message is printed for missing subcommand")


# ---------------------------------------------------------------------------
# E. Unknown subcommand
# ---------------------------------------------------------------------------


def scenario_lesson_command_unknown_subcommand_fails_explicitly() -> None:
    print("\n[Scenario E1] an unknown 'lesson' subcommand fails explicitly")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_lesson_command(app, ["frobnicate"])
    output = buf.getvalue()

    check(rc != 0, "an unknown subcommand returns a non-zero exit code")
    check("Unknown lesson subcommand" in output, "output names the unknown subcommand explicitly")


# ---------------------------------------------------------------------------
# 'lesson list' retrieves lessons
# ---------------------------------------------------------------------------


def scenario_lesson_list_shows_stored_lesson() -> None:
    print("\n[Scenario F1] 'lesson list' shows a lesson 'lesson add' just stored")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_lesson_command(app, ["add", "Respect", "the", "stop", "loss"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_lesson_command(app, ["list"])
    output = buf.getvalue()

    check(rc == 0, "'lesson list' returns exit code 0")
    check("Respect the stop loss" in output, "'lesson list' output includes the stored text")


def scenario_lesson_list_empty_store_reports_zero_lessons() -> None:
    print("\n[Scenario F2] 'lesson list' on an empty store reports zero lessons, does not raise")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    raised = False
    try:
        with redirect_stdout(buf):
            rc = main._run_lesson_command(app, ["list"])
    except Exception:  # noqa: BLE001
        raised = True
        rc = None
    output = buf.getvalue()

    check(not raised, "listing an empty store does not raise")
    check(rc == 0, "'lesson list' on an empty store still returns exit code 0")
    check("Lessons (0)" in output, "output honestly reports there are zero lessons")


def scenario_lesson_list_preserves_insertion_order() -> None:
    print("\n[Scenario F3] multiple lessons are listed in MemoryStore insertion order, not reversed/sorted")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_lesson_command(app, ["add", "First", "lesson"])
        main._run_lesson_command(app, ["add", "Second", "lesson"])
        main._run_lesson_command(app, ["add", "Third", "lesson"])

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_lesson_command(app, ["list"])
    output = buf.getvalue()

    first_pos = output.index("First lesson")
    second_pos = output.index("Second lesson")
    third_pos = output.index("Third lesson")
    check(first_pos < second_pos < third_pos, "lessons appear in the exact order they were added")

    texts = [r.text for r in store.list() if isinstance(r, LessonRecord)]
    check(
        texts == ["First lesson", "Second lesson", "Third lesson"],
        "MemoryStore.list() itself preserves insertion order for lessons",
    )


# ---------------------------------------------------------------------------
# G. Record isolation -- other record kinds do not leak into 'lesson list'
# ---------------------------------------------------------------------------


def scenario_other_record_kinds_are_not_displayed_as_lessons() -> None:
    print("\n[Scenario G1] PreferenceRecord/StrategyNoteRecord/PreviousDecisionRecord/MemoryRecord are not listed by 'lesson list'")
    store = MemoryStore()
    app = FakeApp(store)
    recorder = MemoryRecorder(store=store)

    mr = recorder.record(_observation())
    with redirect_stdout(io.StringIO()):
        main._run_preference_command(app, ["set", "report_verbosity", "concise"])
        main._run_strategy_note_command(app, ["add", "Only", "trade", "the", "trend"])
        main._run_previous_decision_command(app, ["add", "SKIP", "low", "conviction", "setup"])
        main._run_lesson_command(app, ["add", "Wait", "for", "confirmation", "before", "entry"])

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_lesson_command(app, ["list"])
    output = buf.getvalue()

    check("Lessons (1)" in output, "only the one LessonRecord is counted")
    check("report_verbosity" not in output, "the PreferenceRecord's key does not leak into lesson output")
    check("concise" not in output, "the PreferenceRecord's value does not leak into lesson output")
    check("Only trade the trend" not in output, "the StrategyNoteRecord's text does not leak into lesson output")
    check("low conviction setup" not in output, "the PreviousDecisionRecord's rationale does not leak into lesson output")

    listed = store.list()
    check(len(listed) == 5, "all five records coexist in the one shared store")
    check(store.get(mr.record_id) is mr, "the observation MemoryRecord is unaffected by the lesson command")

    lessons_only = [r for r in store.list() if isinstance(r, LessonRecord)]
    check(len(lessons_only) == 1, "isinstance(LessonRecord) filtering yields exactly one record")


# ---------------------------------------------------------------------------
# Store identity -- no second MemoryStore is constructed
# ---------------------------------------------------------------------------


def scenario_lesson_command_reuses_the_passed_in_memory_store_instance() -> None:
    print("\n[Scenario H1] the lesson command path stores into the exact MemoryStore instance it was given")
    store = MemoryStore()
    store_id_before = id(store)
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_lesson_command(app, ["add", "One", "lesson"])

    check(id(app.memory_store) == store_id_before, "app.memory_store is still the same object identity after the command runs")
    check(len(store) == 1, "the record landed in the original store instance, not a second one")


def scenario_two_fake_apps_with_distinct_stores_do_not_leak_into_each_other() -> None:
    print("\n[Scenario H2] two FakeApps with distinct MemoryStores stay fully isolated (no shared/global store)")
    store_a = MemoryStore()
    store_b = MemoryStore()
    app_a = FakeApp(store_a)
    app_b = FakeApp(store_b)

    with redirect_stdout(io.StringIO()):
        main._run_lesson_command(app_a, ["add", "from_a"])

    check(len(store_a) == 1, "store_a received the record added through app_a")
    check(len(store_b) == 0, "store_b is untouched -- no global/shared MemoryStore singleton is used")


def scenario_build_application_wires_exactly_one_memory_store_for_lessons() -> None:
    print("\n[Scenario H3] a real build_application() app stores lessons into its own single memory_store")
    app = build_application()
    store_id_before = id(app.memory_store)

    with redirect_stdout(io.StringIO()):
        rc = main._run_lesson_command(app, ["add", "Confirm", "trend", "before", "entry"])

    check(rc == 0, "'lesson add' succeeds against a real build_application() app")
    check(id(app.memory_store) == store_id_before, "the real app's memory_store identity is unchanged after the command")
    lessons = [r for r in app.memory_store.list() if isinstance(r, LessonRecord)]
    check(len(lessons) == 1, "exactly one LessonRecord landed in the real app's single memory_store")


# ---------------------------------------------------------------------------
# H. Financial state / financial database is never touched
# ---------------------------------------------------------------------------


def scenario_lesson_commands_never_touch_financial_or_execution_attributes() -> None:
    print("\n[Scenario I1] FakeApp has no financial/execution collaborators for the lesson path to reach")
    # FakeApp deliberately exposes only ``memory_store`` -- no
    # PaperTradingEngine, ExecutionService, account/position/order/trade
    # repository, and no FailureRateEngine. If any lesson command path
    # tried to reach one of those, it would raise AttributeError, not
    # silently succeed.
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
        "failure_rate_engine",
    )
    for attr in forbidden_attrs:
        check(not hasattr(app, attr), f"FakeApp has no '{attr}' collaborator for the lesson path to call")

    raised = False
    try:
        with redirect_stdout(io.StringIO()):
            main._run_lesson_command(app, ["add", "Do", "not", "overtrade"])
            main._run_lesson_command(app, ["list"])
    except AttributeError:
        raised = True
    check(not raised, "the full add/list lesson path runs to completion touching only memory_store")


def scenario_lesson_record_source_module_has_no_financial_imports() -> None:
    print("\n[Scenario I2] Orchestration/memory.py still does not import the financial/execution layer")
    import Orchestration.memory as memory_module

    source = Path(memory_module.__file__).read_text()
    for forbidden in ("PaperTradingEngine", "ToolRegistry", "ToolResolver", "ExecutionService", "FailureRateEngine"):
        check(forbidden not in source, f"Orchestration/memory.py does not reference {forbidden}")


def scenario_main_module_lesson_dispatch_does_not_reference_financial_engines() -> None:
    print("\n[Scenario I3] the lesson CLI functions in main.py do not reference financial-outcome machinery")
    import inspect

    for fn in (main._run_lesson_add, main._run_lesson_list, main._run_lesson_command):
        source = inspect.getsource(fn)
        for forbidden in ("FailureRateEngine", "realized_pnl", "OrderStatus.REJECTED", "PositionManager"):
            check(forbidden not in source, f"{fn.__name__} does not reference {forbidden}")


# ---------------------------------------------------------------------------
# Fresh process has no previous lessons (honest process-local behavior)
# ---------------------------------------------------------------------------


def scenario_lessons_do_not_survive_a_fresh_memory_store_representing_a_restart() -> None:
    print("\n[Scenario J1] a fresh MemoryStore (simulating process restart) has no prior lessons")
    store = MemoryStore()
    app = FakeApp(store)
    with redirect_stdout(io.StringIO()):
        main._run_lesson_command(app, ["add", "Lesson", "before", "restart"])
    check(len(store) == 1, "the lesson is present within this process's MemoryStore")

    # A restart means a brand new process, which means a brand new
    # ApplicationGraph/_build_memory_store() call -- there is no
    # database or file backing this store, so a fresh MemoryStore
    # stands in honestly for "after restart" here.
    restarted_store = MemoryStore()
    restarted_app = FakeApp(restarted_store)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_lesson_command(restarted_app, ["list"])
    output = buf.getvalue()

    check(rc == 0, "'lesson list' still succeeds after a simulated restart")
    check("Lessons (0)" in output, "the command is honest that the prior lesson is gone, not silently wrong")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main_() -> int:
    scenarios = [
        # Group A
        scenario_lesson_add_stores_a_lesson_record,
        scenario_lesson_add_prints_confirmation,
        # Group B
        scenario_lesson_add_joins_multiple_words,
        # Group C
        scenario_lesson_add_missing_text_fails_explicitly,
        scenario_lesson_add_whitespace_only_text_fails_explicitly,
        # Group D
        scenario_lesson_command_no_subcommand_fails_explicitly,
        # Group E
        scenario_lesson_command_unknown_subcommand_fails_explicitly,
        # Group F
        scenario_lesson_list_shows_stored_lesson,
        scenario_lesson_list_empty_store_reports_zero_lessons,
        scenario_lesson_list_preserves_insertion_order,
        # Group G
        scenario_other_record_kinds_are_not_displayed_as_lessons,
        # Group H
        scenario_lesson_command_reuses_the_passed_in_memory_store_instance,
        scenario_two_fake_apps_with_distinct_stores_do_not_leak_into_each_other,
        scenario_build_application_wires_exactly_one_memory_store_for_lessons,
        # Group I
        scenario_lesson_commands_never_touch_financial_or_execution_attributes,
        scenario_lesson_record_source_module_has_no_financial_imports,
        scenario_main_module_lesson_dispatch_does_not_reference_financial_engines,
        # Group J
        scenario_lessons_do_not_survive_a_fresh_memory_store_representing_a_restart,
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
    print(f"ACTIVATION 12 MEMORY LESSON CLI RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main_())