"""
Activation 12, Phase 3 proof suite -- production wiring for user
preference storage/retrieval.

Scope: this suite proves the REAL user-facing path -- ``main.py``'s
``preference set|get|list`` CLI command -- actually stores and retrieves
:class:`~Orchestration.memory.PreferenceRecord` objects through the
existing, unmodified ``app.memory_store`` (the single ``MemoryStore``
instance ``Core.composition_root.ApplicationGraph`` already builds), and
that nothing else on ``FakeApp``/the financial layer is touched while
doing so.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``Tests/test_activation12_memory_preference_record.py`` and
``Tests/test_manual_scan_command.py``: a global pass/fail counter, plain
fakes, and a ``main()`` runner.

Explicitly NOT tested here (out of scope for this step, see the
Activation 12 Phase 3 prompt): strategy notes, previous-decision memory,
lessons-from-failed-trades memory, vector/embeddings storage,
GoalPlanner/scheduler/planner integration, or persistence across a
process restart.
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
from Orchestration.memory import (  # noqa: E402
    MemoryError,
    MemoryRecord,
    MemoryRecorder,
    MemoryStore,
    PreferenceRecord,
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
    the one attribute the preference command path actually reads:
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
# A. Real user-facing SET command/path stores a PreferenceRecord
# ---------------------------------------------------------------------------


def scenario_preference_set_stores_a_preference_record() -> None:
    print("\n[Scenario A1] 'preference set' stores a PreferenceRecord in app.memory_store")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        rc = main._run_preference_command(app, ["set", "report_verbosity", "concise"])

    check(rc == 0, "'preference set' returns exit code 0 on success")
    check(len(store) == 1, "exactly one record is stored")
    stored = store.list()[0]
    check(isinstance(stored, PreferenceRecord), "the stored record is a PreferenceRecord")
    check(stored.key == "report_verbosity", "stored record's key matches the CLI argument")
    check(stored.value == "concise", "stored record's value matches the CLI argument")


def scenario_preference_set_prints_confirmation() -> None:
    print("\n[Scenario A2] 'preference set' prints a confirmation naming key and value")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_preference_command(app, ["set", "report_verbosity", "concise"])
    output = buf.getvalue()

    check("report_verbosity" in output, "confirmation output includes the preference key")
    check("concise" in output, "confirmation output includes the preference value")


def scenario_preference_set_missing_value_fails_explicitly() -> None:
    print("\n[Scenario A3] 'preference set' with a missing VALUE argument fails explicitly")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        rc = main._run_preference_command(app, ["set", "report_verbosity"])

    check(rc != 0, "'preference set' with a missing value returns a non-zero exit code")
    check(len(store) == 0, "no record is stored when the command is rejected")


# ---------------------------------------------------------------------------
# B. Real user-facing GET/LIST command/path retrieves the same preference
#    from the existing MemoryStore
# ---------------------------------------------------------------------------


def scenario_preference_get_retrieves_what_set_stored() -> None:
    print("\n[Scenario B1] 'preference get' retrieves the value 'preference set' just stored")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_preference_command(app, ["set", "report_verbosity", "concise"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_preference_command(app, ["get", "report_verbosity"])
    output = buf.getvalue()

    check(rc == 0, "'preference get' returns exit code 0 when the key exists")
    check("concise" in output, "'preference get' output includes the stored value")


def scenario_preference_list_shows_stored_preference() -> None:
    print("\n[Scenario B2] 'preference list' shows a preference 'preference set' just stored")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_preference_command(app, ["set", "notification_style", "digest"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_preference_command(app, ["list"])
    output = buf.getvalue()

    check(rc == 0, "'preference list' returns exit code 0")
    check("notification_style" in output, "'preference list' output includes the stored key")
    check("digest" in output, "'preference list' output includes the stored value")


def scenario_preference_get_unknown_key_fails_explicitly() -> None:
    print("\n[Scenario B3] 'preference get' for a key that was never set fails explicitly")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_preference_command(app, ["get", "does_not_exist"])
    output = buf.getvalue()

    check(rc != 0, "'preference get' on an unset key returns a non-zero exit code")
    check("does_not_exist" in output, "output names the missing key rather than failing silently")


def scenario_preference_list_empty_store_reports_no_preferences() -> None:
    print("\n[Scenario B4] 'preference list' on an empty store reports no preferences, does not raise")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    raised = False
    try:
        with redirect_stdout(buf):
            rc = main._run_preference_command(app, ["list"])
    except Exception:  # noqa: BLE001
        raised = True
        rc = None
    output = buf.getvalue()

    check(not raised, "listing an empty store does not raise")
    check(rc == 0, "'preference list' on an empty store still returns exit code 0")
    check("No preferences" in output, "output honestly reports there are no preferences yet")


# ---------------------------------------------------------------------------
# C. The stored object is actually a PreferenceRecord
# ---------------------------------------------------------------------------


def scenario_stored_object_is_a_real_preference_record_not_a_dict() -> None:
    print("\n[Scenario C1] the object stored by 'preference set' is a real PreferenceRecord")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_preference_command(app, ["set", "k", "v"])

    stored = store.list()[0]
    check(type(stored).__name__ == "PreferenceRecord", "stored object's runtime type is PreferenceRecord")
    check(not isinstance(stored, dict), "stored object is not a plain dict")
    check(hasattr(stored, "record_id") and hasattr(stored, "recorded_at"), "stored object carries PreferenceRecord's identity/timestamp fields")


# ---------------------------------------------------------------------------
# D. Existing MemoryRecord/analysis observation memory still works
# ---------------------------------------------------------------------------


def scenario_existing_observation_memory_flow_unaffected_by_preference_wiring() -> None:
    print("\n[Scenario D1] MemoryRecorder -> MemoryStore observation flow is unaffected")
    store = MemoryStore()
    recorder = MemoryRecorder(store=store)

    mr = recorder.record(_observation())

    check(isinstance(mr, MemoryRecord), "MemoryRecorder still returns a MemoryRecord")
    check(store.get(mr.record_id) is mr, "existing MemoryRecord still round-trips through MemoryStore")


def scenario_preference_and_observation_records_coexist_via_the_command_path() -> None:
    print("\n[Scenario D2] a CLI-set preference and an observation-derived MemoryRecord coexist")
    store = MemoryStore()
    app = FakeApp(store)
    recorder = MemoryRecorder(store=store)

    mr = recorder.record(_observation())
    with redirect_stdout(io.StringIO()):
        main._run_preference_command(app, ["set", "k", "v"])

    listed = store.list()
    check(len(listed) == 2, "both records are present in the one shared store")
    kinds = {type(r).__name__ for r in listed}
    check(kinds == {"MemoryRecord", "PreferenceRecord"}, "store holds both record kinds side by side")
    check(store.get(mr.record_id) is mr, "the observation MemoryRecord is unaffected by the preference command")


# ---------------------------------------------------------------------------
# E. Multiple preference records coexist per actual MemoryStore semantics
# ---------------------------------------------------------------------------


def scenario_multiple_distinct_preference_keys_all_listed() -> None:
    print("\n[Scenario E1] multiple distinct preference keys all coexist and are listed")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_preference_command(app, ["set", "report_verbosity", "concise"])
        main._run_preference_command(app, ["set", "notification_style", "digest"])
        main._run_preference_command(app, ["set", "analysis_style", "detailed"])

    check(len(store) == 3, "three distinct preference keys are all stored")
    keys = {r.key for r in store.list()}
    check(keys == {"report_verbosity", "notification_style", "analysis_style"}, "all three keys are retrievable")


def scenario_setting_same_key_twice_appends_rather_than_silently_overwriting() -> None:
    print("\n[Scenario E2] re-setting the same key follows MemoryStore's actual append-only contract")
    store = MemoryStore()
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_preference_command(app, ["set", "report_verbosity", "concise"])
        main._run_preference_command(app, ["set", "report_verbosity", "detailed"])

    check(len(store) == 2, "MemoryStore.add() is append-only, so re-setting a key adds a second record, not an in-place update")
    matching = [r for r in store.list() if r.key == "report_verbosity"]
    check(len(matching) == 2, "both records for the re-set key are present in the store")

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_preference_command(app, ["get", "report_verbosity"])
    output = buf.getvalue()
    check("detailed" in output, "'preference get' surfaces the most recently set value for a repeated key")


# ---------------------------------------------------------------------------
# F. Invalid preference input fails explicitly
# ---------------------------------------------------------------------------


def scenario_preference_set_rejects_invalid_value_via_preference_record_validation() -> None:
    print("\n[Scenario F1] a non-primitive value cannot be forced through the CLI path")
    # The CLI path only ever constructs PreferenceRecord from plain str
    # argv tokens, so it cannot itself hand PreferenceRecord an invalid
    # (non-primitive) value -- this proves that constraint is real by
    # calling PreferenceRecord's own validation directly, the same
    # validation _run_preference_set relies on.
    try:
        PreferenceRecord(key="k", value={"cash": 100.0})
        check(False, "a dict value is rejected by PreferenceRecord's own validation")
    except MemoryError:
        check(True, "a dict value is rejected by PreferenceRecord's own validation")


def scenario_preference_set_empty_key_fails_explicitly() -> None:
    print("\n[Scenario F2] 'preference set' with an empty KEY fails explicitly, nothing stored")
    store = MemoryStore()
    app = FakeApp(store)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_preference_command(app, ["set", "", "concise"])
    output = buf.getvalue()

    check(rc != 0, "'preference set' with an empty key returns a non-zero exit code")
    check(len(store) == 0, "no record is stored for an empty key")
    check("Invalid preference" in output, "output explicitly names the failure rather than failing silently")


def scenario_preference_command_unknown_subcommand_fails_explicitly() -> None:
    print("\n[Scenario F3] an unknown 'preference' subcommand fails explicitly")
    app = FakeApp(MemoryStore())

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_preference_command(app, ["frobnicate"])
    output = buf.getvalue()

    check(rc != 0, "an unknown subcommand returns a non-zero exit code")
    check("Unknown preference subcommand" in output, "output names the unknown subcommand explicitly")


def scenario_preference_command_no_subcommand_fails_explicitly() -> None:
    print("\n[Scenario F4] 'preference' with no subcommand at all fails explicitly")
    app = FakeApp(MemoryStore())

    with redirect_stdout(io.StringIO()):
        rc = main._run_preference_command(app, [])

    check(rc != 0, "'preference' with no subcommand returns a non-zero exit code")


# ---------------------------------------------------------------------------
# G. No financial mutation occurs / H. No PaperTradingEngine execution occurs
# ---------------------------------------------------------------------------


def scenario_preference_commands_never_touch_financial_or_execution_attributes() -> None:
    print("\n[Scenario G1/H1] FakeApp has no financial/execution collaborators for the preference path to reach")
    # FakeApp deliberately exposes only ``memory_store`` -- no
    # PaperTradingEngine, ExecutionService, account/position/order/trade
    # repository. If any preference command path tried to reach one of
    # those, it would raise AttributeError, not silently succeed.
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
        check(not hasattr(app, attr), f"FakeApp has no '{attr}' collaborator for the preference path to call")

    raised = False
    try:
        with redirect_stdout(io.StringIO()):
            main._run_preference_command(app, ["set", "report_verbosity", "concise"])
            main._run_preference_command(app, ["get", "report_verbosity"])
            main._run_preference_command(app, ["list"])
    except AttributeError:
        raised = True
    check(not raised, "the full set/get/list preference path runs to completion touching only memory_store")


def scenario_preference_record_source_module_has_no_financial_imports() -> None:
    print("\n[Scenario G2/H2] Orchestration/memory.py still does not import the financial/execution layer")
    import Orchestration.memory as memory_module

    source = Path(memory_module.__file__).read_text()
    for forbidden in ("PaperTradingEngine", "ToolRegistry", "ToolResolver", "ExecutionService"):
        check(forbidden not in source, f"Orchestration/memory.py does not reference {forbidden}")


# ---------------------------------------------------------------------------
# I. No second MemoryStore instance is created by the new caller
# ---------------------------------------------------------------------------


def scenario_preference_command_reuses_the_passed_in_memory_store_instance() -> None:
    print("\n[Scenario I1] the preference command path stores into the exact MemoryStore instance it was given")
    store = MemoryStore()
    store_id_before = id(store)
    app = FakeApp(store)

    with redirect_stdout(io.StringIO()):
        main._run_preference_command(app, ["set", "k", "v"])

    check(id(app.memory_store) == store_id_before, "app.memory_store is still the same object identity after the command runs")
    check(len(store) == 1, "the record landed in the original store instance, not a second one")


def scenario_two_fake_apps_with_distinct_stores_do_not_leak_into_each_other() -> None:
    print("\n[Scenario I2] two FakeApps with distinct MemoryStores stay fully isolated (no shared/global store)")
    store_a = MemoryStore()
    store_b = MemoryStore()
    app_a = FakeApp(store_a)
    app_b = FakeApp(store_b)

    with redirect_stdout(io.StringIO()):
        main._run_preference_command(app_a, ["set", "k", "from_a"])

    check(len(store_a) == 1, "store_a received the record set through app_a")
    check(len(store_b) == 0, "store_b is untouched -- no global/shared MemoryStore singleton is used")


# ---------------------------------------------------------------------------
# J. Restart semantics honestly documented/tested
# ---------------------------------------------------------------------------


def scenario_preferences_do_not_survive_a_fresh_memory_store_representing_a_restart() -> None:
    print("\n[Scenario J1] a fresh MemoryStore (simulating process restart) has no prior preferences")
    store = MemoryStore()
    app = FakeApp(store)
    with redirect_stdout(io.StringIO()):
        main._run_preference_command(app, ["set", "report_verbosity", "concise"])
    check(len(store) == 1, "the preference is present within this process's MemoryStore")

    # A restart means a brand new process, which means a brand new
    # ApplicationGraph/_build_memory_store() call -- there is no database
    # or file backing this store, so a fresh MemoryStore stands in
    # honestly for "after restart" here.
    restarted_store = MemoryStore()
    restarted_app = FakeApp(restarted_store)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_preference_command(restarted_app, ["get", "report_verbosity"])
    output = buf.getvalue()

    check(rc != 0, "after a simulated restart, the previously set preference is genuinely gone")
    check("No preference set" in output, "the command is honest that the preference is gone, not silently wrong")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main_() -> int:
    scenarios = [
        # Group A
        scenario_preference_set_stores_a_preference_record,
        scenario_preference_set_prints_confirmation,
        scenario_preference_set_missing_value_fails_explicitly,
        # Group B
        scenario_preference_get_retrieves_what_set_stored,
        scenario_preference_list_shows_stored_preference,
        scenario_preference_get_unknown_key_fails_explicitly,
        scenario_preference_list_empty_store_reports_no_preferences,
        # Group C
        scenario_stored_object_is_a_real_preference_record_not_a_dict,
        # Group D
        scenario_existing_observation_memory_flow_unaffected_by_preference_wiring,
        scenario_preference_and_observation_records_coexist_via_the_command_path,
        # Group E
        scenario_multiple_distinct_preference_keys_all_listed,
        scenario_setting_same_key_twice_appends_rather_than_silently_overwriting,
        # Group F
        scenario_preference_set_rejects_invalid_value_via_preference_record_validation,
        scenario_preference_set_empty_key_fails_explicitly,
        scenario_preference_command_unknown_subcommand_fails_explicitly,
        scenario_preference_command_no_subcommand_fails_explicitly,
        # Group G/H
        scenario_preference_commands_never_touch_financial_or_execution_attributes,
        scenario_preference_record_source_module_has_no_financial_imports,
        # Group I
        scenario_preference_command_reuses_the_passed_in_memory_store_instance,
        scenario_two_fake_apps_with_distinct_stores_do_not_leak_into_each_other,
        # Group J
        scenario_preferences_do_not_survive_a_fresh_memory_store_representing_a_restart,
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
    print(f"ACTIVATION 12 MEMORY PREFERENCE WIRING RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main_())