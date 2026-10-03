"""
Activation 12 Memory (Previous Decisions) proof suite -- production
wiring for the ``previous-decision`` CLI command.

Scope: this suite proves the REAL user-facing path -- ``main.py``'s
``previous-decision add|list`` CLI command -- actually stores and
retrieves :class:`~Orchestration.memory.PreviousDecisionRecord` objects
through the existing, unmodified ``app.memory_store`` (the single
``MemoryStore`` instance ``Core.composition_root.ApplicationGraph``
already builds), and that nothing else on ``FakeApp``/the financial
layer is touched while doing so.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``Tests/test_activation12_memory_strategy_note_cli.py`` and
``Tests/test_activation12_memory_previous_decision_record.py``: a
global pass/fail counter, plain fakes, and a ``main()`` runner.

Explicitly NOT tested here (out of scope for this step, see the
Activation 12 Memory Previous Decision CLI prompt): planner
integration, HumanApprovalPort integration, order/trade lookup from
``reference_id``, automatic outcome classification, lessons from
failed trades, persistence across a process restart, or
``previous-decision get/remove/edit/search``.
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
    the one attribute the previous-decision command path actually
    reads: ``memory_store``. No financial collaborators
    (``PaperTradingEngine``, ``ExecutionService``, account/position/
    order/trade repositories) are present on this fake at all -- if a
    code path under test ever tried to reach one, it would fail with
    ``AttributeError``, not silently succeed against a stub.
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
# A. 'previous-decision add' creates a PreviousDecisionRecord
# ---------------------------------------------------------------------------


def scenario_previous_decision_add_stores_a_previous_decision_record() -> None:
    print("\n[Scenario A1] 'previous-decision add' stores a PreviousDecisionRecord in app.memory_store")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        rc = main._run_previous_decision_command(
            app, ["add", "WAIT", "Momentum", "had", "not", "confirmed", "yet"]
        )

    check(rc == 0, "'previous-decision add' returns exit code 0 on success")
    check(len(store) == 1, "exactly one record is stored")
    stored = store.list()[0]
    check(isinstance(stored, PreviousDecisionRecord), "the stored record is a PreviousDecisionRecord")
    check(stored.decision == "WAIT", "stored record's decision matches the first CLI argument")
    check(
        stored.rationale == "Momentum had not confirmed yet",
        "stored record's rationale matches the joined remaining CLI arguments",
    )


def scenario_previous_decision_add_prints_confirmation() -> None:
    print("\n[Scenario A2] 'previous-decision add' prints a confirmation naming decision and rationale")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_previous_decision_command(
            app, ["add", "REJECTED", "Risk", "limit", "would", "be", "breached"]
        )
    output = buf.getvalue()

    check("REJECTED" in output, "confirmation output includes the decision")
    check("Risk limit would be breached" in output, "confirmation output includes the rationale")


# ---------------------------------------------------------------------------
# B. Decision normalization works through the record contract
# ---------------------------------------------------------------------------


def scenario_previous_decision_normalization_comes_from_the_record_not_the_cli() -> None:
    print("\n[Scenario B1] whitespace normalization is PreviousDecisionRecord's job, CLI just passes the tokens through")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_previous_decision_command(app, ["add", "BUY", "  Trim", "the", "edges  "])

    stored = store.list()[0]
    check(stored.decision == "BUY", "the decision is stored as given (already a single token)")
    check(not stored.rationale.startswith(" "), "no leading whitespace survives in the stored rationale")
    check(not stored.rationale.endswith(" "), "no trailing whitespace survives in the stored rationale")


# ---------------------------------------------------------------------------
# C. Multi-word rationale joins correctly
# ---------------------------------------------------------------------------


def scenario_previous_decision_add_joins_multiple_rationale_words() -> None:
    print("\n[Scenario C1] multi-word 'previous-decision add' rationale joins with single spaces")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_previous_decision_command(
            app,
            ["add", "REDUCED", "Earnings", "missed", "consensus", "and", "momentum", "turned", "negative"],
        )

    stored = store.list()[0]
    check(stored.decision == "REDUCED", "the decision is the first argv token")
    check(
        stored.rationale == "Earnings missed consensus and momentum turned negative",
        "multi-word rationale is joined into a single space-separated string",
    )


# ---------------------------------------------------------------------------
# D. Missing decision/rationale produces a clean CLI error
# ---------------------------------------------------------------------------


def scenario_previous_decision_add_missing_all_arguments_fails_explicitly() -> None:
    print("\n[Scenario D1] 'previous-decision add' with no arguments fails explicitly, no traceback")
    store = MemoryStore()
    app = FakeApp(store)

    buf = io.StringIO()
    raised = False
    try:
        with redirect_stdout(buf):
            rc = main._run_previous_decision_command(app, ["add"])
    except Exception:  # noqa: BLE001
        raised = True
        rc = None
    output = buf.getvalue()

    check(not raised, "missing arguments do not raise a raw traceback")
    check(rc != 0, "'previous-decision add' with no arguments returns a non-zero exit code")
    check(len(store) == 0, "no record is stored when the command is rejected")
    check("Usage" in output, "output explicitly names the usage rather than failing silently")


def scenario_previous_decision_add_missing_rationale_fails_explicitly() -> None:
    print("\n[Scenario D2] 'previous-decision add BUY' (no rationale) fails explicitly")
    store = MemoryStore()
    app = FakeApp(store)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_previous_decision_command(app, ["add", "BUY"])
    output = buf.getvalue()

    check(rc != 0, "a decision with no rationale returns a non-zero exit code")
    check(len(store) == 0, "no record is stored when rationale is missing")
    check("Usage" in output, "output explicitly names the usage failure")


def scenario_previous_decision_add_whitespace_only_rationale_fails_explicitly() -> None:
    print("\n[Scenario D3] 'previous-decision add' with only whitespace rationale tokens fails explicitly")
    store = MemoryStore()
    app = FakeApp(store)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_previous_decision_command(app, ["add", "WAIT", "   ", "  "])
    output = buf.getvalue()

    check(rc != 0, "whitespace-only rationale returns a non-zero exit code")
    check(len(store) == 0, "no record is stored for whitespace-only rationale")
    check("Invalid previous decision" in output, "output explicitly names the failure")


# ---------------------------------------------------------------------------
# E. 'previous-decision list' retrieves records
# ---------------------------------------------------------------------------


def scenario_previous_decision_list_shows_stored_record() -> None:
    print("\n[Scenario E1] 'previous-decision list' shows a record 'previous-decision add' just stored")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_previous_decision_command(app, ["add", "WAIT", "For", "confirmation", "candle"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_previous_decision_command(app, ["list"])
    output = buf.getvalue()

    check(rc == 0, "'previous-decision list' returns exit code 0")
    check("WAIT" in output, "'previous-decision list' output includes the stored decision")
    check("For confirmation candle" in output, "'previous-decision list' output includes the stored rationale")


def scenario_previous_decision_list_empty_store_reports_zero_records() -> None:
    print("\n[Scenario E2] 'previous-decision list' on an empty store reports zero records, does not raise")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    raised = False
    try:
        with redirect_stdout(buf):
            rc = main._run_previous_decision_command(app, ["list"])
    except Exception:  # noqa: BLE001
        raised = True
        rc = None
    output = buf.getvalue()

    check(not raised, "listing an empty store does not raise")
    check(rc == 0, "'previous-decision list' on an empty store still returns exit code 0")
    check("Previous Decisions (0)" in output, "output honestly reports there are zero records")


# ---------------------------------------------------------------------------
# F. Insertion order is preserved
# ---------------------------------------------------------------------------


def scenario_previous_decision_list_preserves_insertion_order() -> None:
    print("\n[Scenario F1] multiple decisions are listed in MemoryStore insertion order, not reversed/sorted")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_previous_decision_command(app, ["add", "WAIT", "First", "decision"])
        main._run_previous_decision_command(app, ["add", "BUY", "Second", "decision"])
        main._run_previous_decision_command(app, ["add", "SELL", "Third", "decision"])

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_previous_decision_command(app, ["list"])
    output = buf.getvalue()

    first_pos = output.index("First decision")
    second_pos = output.index("Second decision")
    third_pos = output.index("Third decision")
    check(first_pos < second_pos < third_pos, "records appear in the exact order they were added")

    decisions = [r.decision for r in store.list() if isinstance(r, PreviousDecisionRecord)]
    check(
        decisions == ["WAIT", "BUY", "SELL"],
        "MemoryStore.list() itself preserves insertion order for previous decisions",
    )


# ---------------------------------------------------------------------------
# G. PreferenceRecord is not displayed
# ---------------------------------------------------------------------------


def scenario_preference_records_are_not_displayed_as_previous_decisions() -> None:
    print("\n[Scenario G1] a PreferenceRecord in the same store is not listed by 'previous-decision list'")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_preference_command(app, ["set", "report_verbosity", "concise"])
        main._run_previous_decision_command(app, ["add", "WAIT", "Only", "trade", "the", "trend"])

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_previous_decision_command(app, ["list"])
    output = buf.getvalue()

    check("Previous Decisions (1)" in output, "only the one PreviousDecisionRecord is counted")
    check("report_verbosity" not in output, "the PreferenceRecord's key does not leak into previous-decision output")
    check("concise" not in output, "the PreferenceRecord's value does not leak into previous-decision output")


# ---------------------------------------------------------------------------
# H. StrategyNoteRecord is not displayed
# ---------------------------------------------------------------------------


def scenario_strategy_notes_are_not_displayed_as_previous_decisions() -> None:
    print("\n[Scenario H1] a StrategyNoteRecord in the same store is not listed by 'previous-decision list'")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_strategy_note_command(app, ["add", "Respect", "the", "stop", "loss"])
        main._run_previous_decision_command(app, ["add", "SELL", "Stop", "hit"])

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_previous_decision_command(app, ["list"])
    output = buf.getvalue()

    check("Previous Decisions (1)" in output, "only the one PreviousDecisionRecord is counted, not the StrategyNoteRecord too")
    check("Respect the stop loss" not in output, "the StrategyNoteRecord's text does not leak into previous-decision output")


# ---------------------------------------------------------------------------
# I. MemoryRecord is not displayed
# ---------------------------------------------------------------------------


def scenario_observation_memory_records_are_not_displayed_as_previous_decisions() -> None:
    print("\n[Scenario I1] an observation-derived MemoryRecord in the same store is not listed by 'previous-decision list'")
    store = MemoryStore()
    app = FakeApp(store)
    recorder = MemoryRecorder(store=store)

    mr = recorder.record(_observation())
    with redirect_stdout(io.StringIO()):
        main._run_previous_decision_command(app, ["add", "HOLD", "No", "new", "signal"])

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_previous_decision_command(app, ["list"])
    output = buf.getvalue()

    check("Previous Decisions (1)" in output, "only the one PreviousDecisionRecord is counted, not the MemoryRecord too")
    listed = store.list()
    check(len(listed) == 2, "both records coexist in the one shared store")
    check(store.get(mr.record_id) is mr, "the observation MemoryRecord is unaffected by the previous-decision command")


# ---------------------------------------------------------------------------
# J. source == "cli"
# ---------------------------------------------------------------------------


def scenario_previous_decision_add_sets_source_cli() -> None:
    print("\n[Scenario J1] a decision stored via 'previous-decision add' has source='cli'")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_previous_decision_command(app, ["add", "HOLD", "Size", "positions", "conservatively"])

    stored = store.list()[0]
    check(stored.source == "cli", "the stored PreviousDecisionRecord's source is exactly 'cli'")


# ---------------------------------------------------------------------------
# K. reference_id remains None for CLI-created decisions
# ---------------------------------------------------------------------------


def scenario_previous_decision_add_leaves_reference_id_none() -> None:
    print("\n[Scenario K1] a decision stored via 'previous-decision add' has reference_id=None")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_previous_decision_command(app, ["add", "HOLD", "No", "reference", "yet"])

    stored = store.list()[0]
    check(stored.reference_id is None, "the stored PreviousDecisionRecord's reference_id is exactly None")


# ---------------------------------------------------------------------------
# L. Only one existing ApplicationGraph.memory_store is used /
# N. No second MemoryStore is created
# ---------------------------------------------------------------------------


def scenario_previous_decision_command_reuses_the_passed_in_memory_store_instance() -> None:
    print("\n[Scenario L1] the previous-decision command path stores into the exact MemoryStore instance it was given")
    store = MemoryStore()
    store_id_before = id(store)
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_previous_decision_command(app, ["add", "HOLD", "One", "decision"])

    check(id(app.memory_store) == store_id_before, "app.memory_store is still the same object identity after the command runs")
    check(len(store) == 1, "the record landed in the original store instance, not a second one")


def scenario_two_fake_apps_with_distinct_stores_do_not_leak_into_each_other() -> None:
    print("\n[Scenario L2] two FakeApps with distinct MemoryStores stay fully isolated (no shared/global store)")
    store_a = MemoryStore()
    store_b = MemoryStore()
    app_a = FakeApp(store_a)
    app_b = FakeApp(store_b)

    with redirect_stdout(io.StringIO()):
        main._run_previous_decision_command(app_a, ["add", "WAIT", "from_a"])

    check(len(store_a) == 1, "store_a received the record added through app_a")
    check(len(store_b) == 0, "store_b is untouched -- no global/shared MemoryStore singleton is used")


def scenario_build_application_wires_exactly_one_memory_store_for_previous_decisions() -> None:
    print("\n[Scenario L3] a real build_application() app stores previous decisions into its own single memory_store")
    app = build_application()
    store_id_before = id(app.memory_store)

    with redirect_stdout(io.StringIO()):
        rc = main._run_previous_decision_command(app, ["add", "HOLD", "Confirm", "trend", "with", "volume"])

    check(rc == 0, "'previous-decision add' succeeds against a real build_application() app")
    check(id(app.memory_store) == store_id_before, "the real app's memory_store identity is unchanged after the command")
    decisions = [r for r in app.memory_store.list() if isinstance(r, PreviousDecisionRecord)]
    check(len(decisions) == 1, "exactly one PreviousDecisionRecord landed in the real app's single memory_store")


# ---------------------------------------------------------------------------
# M. Financial state remains untouched / N. PaperTradingEngine remains untouched
# ---------------------------------------------------------------------------


def scenario_previous_decision_commands_never_touch_financial_or_execution_attributes() -> None:
    print("\n[Scenario M1/N1] FakeApp has no financial/execution collaborators for the previous-decision path to reach")
    # FakeApp deliberately exposes only ``memory_store`` -- no
    # PaperTradingEngine, ExecutionService, account/position/order/trade
    # repository. If any previous-decision command path tried to reach
    # one of those, it would raise AttributeError, not silently succeed.
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
        check(not hasattr(app, attr), f"FakeApp has no '{attr}' collaborator for the previous-decision path to call")

    raised = False
    try:
        with redirect_stdout(io.StringIO()):
            main._run_previous_decision_command(app, ["add", "HOLD", "Do", "not", "overtrade"])
            main._run_previous_decision_command(app, ["list"])
    except AttributeError:
        raised = True
    check(not raised, "the full add/list previous-decision path runs to completion touching only memory_store")


def scenario_previous_decision_record_source_module_has_no_financial_imports() -> None:
    print("\n[Scenario M2/N2] Orchestration/memory.py still does not import the financial/execution layer")
    import Orchestration.memory as memory_module

    source = Path(memory_module.__file__).read_text()
    for forbidden in ("PaperTradingEngine", "ToolRegistry", "ToolResolver", "ExecutionService"):
        check(forbidden not in source, f"Orchestration/memory.py does not reference {forbidden}")


# ---------------------------------------------------------------------------
# Additional: unknown subcommand / no subcommand fail explicitly
# ---------------------------------------------------------------------------


def scenario_previous_decision_command_unknown_subcommand_fails_explicitly() -> None:
    print("\n[Scenario Extra1] an unknown 'previous-decision' subcommand fails explicitly")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_previous_decision_command(app, ["frobnicate"])
    output = buf.getvalue()

    check(rc != 0, "an unknown subcommand returns a non-zero exit code")
    check("Unknown previous-decision subcommand" in output, "output names the unknown subcommand explicitly")


def scenario_previous_decision_command_no_subcommand_fails_explicitly() -> None:
    print("\n[Scenario Extra2] 'previous-decision' with no subcommand at all fails explicitly")
    app = FakeApp(MemoryStore())

    with redirect_stdout(io.StringIO()):
        rc = main._run_previous_decision_command(app, [])

    check(rc != 0, "'previous-decision' with no subcommand returns a non-zero exit code")


def scenario_previous_decision_command_no_get_subcommand() -> None:
    print("\n[Scenario Extra3] 'previous-decision get' is not a supported subcommand (chronological memory, not a keyed setting)")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_previous_decision_command(app, ["get", "some-id"])
    output = buf.getvalue()

    check(rc != 0, "'previous-decision get' returns a non-zero exit code")
    check("Unknown previous-decision subcommand" in output, "'get' is rejected as an unknown subcommand")


# ---------------------------------------------------------------------------
# O. Process-local semantics are honest (no persistence across a restart)
# ---------------------------------------------------------------------------


def scenario_previous_decisions_do_not_survive_a_fresh_memory_store_representing_a_restart() -> None:
    print("\n[Scenario O1] a fresh MemoryStore (simulating process restart) has no prior previous decisions")
    store = MemoryStore()
    app = FakeApp(store)
    with redirect_stdout(io.StringIO()):
        main._run_previous_decision_command(app, ["add", "WAIT", "Decision", "before", "restart"])
    check(len(store) == 1, "the previous decision is present within this process's MemoryStore")

    # A restart means a brand new process, which means a brand new
    # ApplicationGraph/_build_memory_store() call -- there is no
    # database or file backing this store, so a fresh MemoryStore
    # stands in honestly for "after restart" here.
    restarted_store = MemoryStore()
    restarted_app = FakeApp(restarted_store)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_previous_decision_command(restarted_app, ["list"])
    output = buf.getvalue()

    check(rc == 0, "'previous-decision list' still succeeds after a simulated restart")
    check("Previous Decisions (0)" in output, "the command is honest that the prior decision is gone, not silently wrong")


# ---------------------------------------------------------------------------
# P. No second MemoryStore is created (module-level sanity: main.py imports
# PreviousDecisionRecord from the same Orchestration.memory module, no
# alternate memory module is introduced)
# ---------------------------------------------------------------------------


def scenario_main_imports_previous_decision_record_from_the_single_memory_module() -> None:
    print("\n[Scenario P1] main.py's PreviousDecisionRecord is the exact same class as Orchestration.memory.PreviousDecisionRecord")
    check(
        main.PreviousDecisionRecord is PreviousDecisionRecord,
        "no second/alternate PreviousDecisionRecord or memory module is introduced",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main_() -> int:
    scenarios = [
        # Group A
        scenario_previous_decision_add_stores_a_previous_decision_record,
        scenario_previous_decision_add_prints_confirmation,
        # Group B
        scenario_previous_decision_normalization_comes_from_the_record_not_the_cli,
        # Group C
        scenario_previous_decision_add_joins_multiple_rationale_words,
        # Group D
        scenario_previous_decision_add_missing_all_arguments_fails_explicitly,
        scenario_previous_decision_add_missing_rationale_fails_explicitly,
        scenario_previous_decision_add_whitespace_only_rationale_fails_explicitly,
        # Group E
        scenario_previous_decision_list_shows_stored_record,
        scenario_previous_decision_list_empty_store_reports_zero_records,
        # Group F
        scenario_previous_decision_list_preserves_insertion_order,
        # Group G
        scenario_preference_records_are_not_displayed_as_previous_decisions,
        # Group H
        scenario_strategy_notes_are_not_displayed_as_previous_decisions,
        # Group I
        scenario_observation_memory_records_are_not_displayed_as_previous_decisions,
        # Group J
        scenario_previous_decision_add_sets_source_cli,
        # Group K
        scenario_previous_decision_add_leaves_reference_id_none,
        # Group L / N
        scenario_previous_decision_command_reuses_the_passed_in_memory_store_instance,
        scenario_two_fake_apps_with_distinct_stores_do_not_leak_into_each_other,
        scenario_build_application_wires_exactly_one_memory_store_for_previous_decisions,
        # Group M / N
        scenario_previous_decision_commands_never_touch_financial_or_execution_attributes,
        scenario_previous_decision_record_source_module_has_no_financial_imports,
        # Extra dispatch coverage
        scenario_previous_decision_command_unknown_subcommand_fails_explicitly,
        scenario_previous_decision_command_no_subcommand_fails_explicitly,
        scenario_previous_decision_command_no_get_subcommand,
        # Group O
        scenario_previous_decisions_do_not_survive_a_fresh_memory_store_representing_a_restart,
        # Group P
        scenario_main_imports_previous_decision_record_from_the_single_memory_module,
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
    print(f"ACTIVATION 12 MEMORY PREVIOUS DECISION CLI RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main_())