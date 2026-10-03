"""
Phase 3 Sprint 28 proof suite -- the ``WorkflowManager`` lifecycle/
storage layer.

Scope: dedicated regression suite for
``Orchestration.workflow_manager.WorkflowManager``/
``WorkflowManagerError`` only. ``Orchestration.workflow.Workflow``
(covered by ``Tests/test_stage_l28_sprint27_workflow.py``) and
``Orchestration.task.Task`` (covered by
``Tests/test_stage_l28_sprint24_task.py``) are unmodified and are not
re-verified beyond what ``WorkflowManager`` itself needs -- real
``Workflow``/``Task`` instances are used throughout here.
``TaskQueue``, ``TaskManager``, ``AutonomousScheduler``,
``AutonomousHost``, ``AutonomousAgent``, ``RuntimeAnalysisPipeline``,
``EventBus``, and the Composition Root are all untouched by this
Sprint and are not exercised by this suite.

``WorkflowManager`` is a pure in-memory, insertion-ordered store: no
threading, no asyncio, no timers, no background execution, no
scheduler/task-execution/queue/WorkflowEngine/EventBus integration, no
persistence, and no serialization exist anywhere in
``Orchestration/workflow_manager.py`` -- this suite proves the
*absence* of that surface area as much as it proves the presence of
the storage/lifecycle behavior itself.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x / Sprint 1x-2x proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    WM1  -- a new WorkflowManager requires no constructor arguments
            and starts empty (count() 0, workflows() == ()).
    WM2  -- add() appends exactly one Workflow, reflected in count()/
            workflows()/contains(), and returns None.
    WM3  -- add() rejects a None workflow, and rejects a non-Workflow
            object -- neither is added.
    WM4  -- add() rejects a Workflow whose workflow_id already exists
            in the manager -- both re-adding the exact same object and
            adding a distinct Workflow that happens to share a
            workflow_id are rejected, and nothing changes on
            rejection.
    WM5  -- insertion order is preserved across many add() calls, as
            observed via workflows().
    WM6  -- remove() removes and returns the matching Workflow by
            identity; count() drops by exactly one; the removed
            Workflow is no longer present.
    WM7  -- remove() for a missing/invalid workflow_id raises
            WorkflowManagerError and leaves state unchanged.
    WM8  -- get() returns the matching Workflow without removing it;
            calling it repeatedly is idempotent; state is unaffected.
    WM9  -- get() for a missing/invalid workflow_id raises
            WorkflowManagerError.
    WM10 -- contains() correctly reports True/False across add()/
            remove()/clear(), and raises WorkflowManagerError for an
            invalid (non-str/empty) workflow_id.
    WM11 -- count() accurately tracks the manager's contents across
            add()/remove()/clear().
    WM12 -- clear() empties a non-empty manager; is idempotent on an
            already-empty manager; and only affects the instance it
            was called on.
    WM13 -- workflows() returns an immutable snapshot: the returned
            tuple cannot be mutated, and mutating a list built from it
            never changes what a later get()/remove() returns; the
            internal list is never the same object returned.
    WM14 -- two independent WorkflowManager instances never share
            state -- adding on one never affects the other's count/
            contents.
    WM15 -- repr() is a stable, informative string reflecting the
            current workflow count.
    WM16 -- WorkflowManager exposes no execution/scheduling/queue/
            WorkflowEngine/persistence/eventing surface (no run/
            start/schedule/tick/execute/save/load/to_dict/publish/
            subscribe/task_queue/scheduler/event_bus members).
    WM17 -- WorkflowManagerError is a subclass of Core.exceptions.
            AgentError.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.workflow import Workflow
from Orchestration.workflow_manager import WorkflowManager, WorkflowManagerError

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


def _make_workflow(
    name: str = "wf", description: str = "d", **kwargs
) -> Workflow:
    return Workflow(name=name, description=description, **kwargs)


# ---------------------------------------------------------------------------
# WM1 -- a new WorkflowManager requires no arguments and starts empty
# ---------------------------------------------------------------------------
def scenario_new_manager_starts_empty() -> None:
    manager = WorkflowManager()

    check(manager.count() == 0, "WM1: a new WorkflowManager reports count() == 0")
    check(
        manager.workflows() == (),
        "WM1: a new WorkflowManager's workflows() is an empty tuple",
    )


# ---------------------------------------------------------------------------
# WM2 -- add() appends exactly one Workflow
# ---------------------------------------------------------------------------
def scenario_add_adds_one_workflow() -> None:
    manager = WorkflowManager()
    workflow = _make_workflow()

    result = manager.add(workflow)

    check(result is None, "WM2: add() returns None")
    check(manager.count() == 1, "WM2: count() is 1 after adding one workflow")
    check(
        manager.workflows() == (workflow,),
        "WM2: workflows() reflects the added workflow",
    )
    check(
        manager.contains(workflow.workflow_id) is True,
        "WM2: contains() reports True for the added workflow's id",
    )


# ---------------------------------------------------------------------------
# WM3 -- add() rejects None and non-Workflow objects
# ---------------------------------------------------------------------------
def scenario_add_rejects_invalid_input() -> None:
    manager = WorkflowManager()

    raised_none = False
    try:
        manager.add(None)
    except WorkflowManagerError:
        raised_none = True

    check(raised_none, "WM3: add(None) raises WorkflowManagerError")

    for bad_value in ("not-a-workflow", 123, {"name": "n"}, ["n", "d"], object()):
        raised_bad = False
        try:
            manager.add(bad_value)
        except WorkflowManagerError:
            raised_bad = True

        check(
            raised_bad,
            f"WM3: add({bad_value!r}) (non-Workflow) raises "
            f"WorkflowManagerError",
        )

    check(
        manager.count() == 0,
        "WM3: none of the rejected add() calls added anything",
    )


# ---------------------------------------------------------------------------
# WM4 -- add() rejects duplicate workflow_id
# ---------------------------------------------------------------------------
def scenario_add_rejects_duplicate_workflow_id() -> None:
    manager = WorkflowManager()
    workflow = _make_workflow(workflow_id="dup-id")
    manager.add(workflow)

    raised_same_object = False
    try:
        manager.add(workflow)
    except WorkflowManagerError:
        raised_same_object = True

    check(
        raised_same_object,
        "WM4: re-adding the exact same Workflow object raises "
        "WorkflowManagerError",
    )

    distinct_workflow_same_id = _make_workflow(
        name="different", workflow_id="dup-id"
    )
    raised_distinct_object = False
    try:
        manager.add(distinct_workflow_same_id)
    except WorkflowManagerError:
        raised_distinct_object = True

    check(
        raised_distinct_object,
        "WM4: adding a distinct Workflow sharing an existing workflow_id "
        "raises WorkflowManagerError",
    )

    check(
        manager.count() == 1,
        "WM4: rejected duplicate add() calls leave the manager unchanged",
    )


# ---------------------------------------------------------------------------
# WM5 -- insertion order preserved
# ---------------------------------------------------------------------------
def scenario_insertion_order_preserved() -> None:
    manager = WorkflowManager()
    workflows = [_make_workflow(name=f"wf-{i}") for i in range(5)]

    for workflow in workflows:
        manager.add(workflow)

    check(
        manager.workflows() == tuple(workflows),
        "WM5: workflows() reflects strict insertion order across many "
        "add() calls",
    )


# ---------------------------------------------------------------------------
# WM6 -- remove() removes and returns the matching Workflow
# ---------------------------------------------------------------------------
def scenario_remove_removes_and_returns_workflow() -> None:
    manager = WorkflowManager()
    workflow_a = _make_workflow(name="a")
    workflow_b = _make_workflow(name="b")
    manager.add(workflow_a)
    manager.add(workflow_b)

    removed = manager.remove(workflow_a.workflow_id)

    check(removed is workflow_a, "WM6: remove() returns the matching workflow by identity")
    check(manager.count() == 1, "WM6: count() drops by exactly one after remove()")
    check(
        removed not in manager.workflows(),
        "WM6: a removed workflow is no longer present in workflows()",
    )
    check(
        manager.contains(workflow_a.workflow_id) is False,
        "WM6: contains() reports False for a removed workflow's id",
    )


# ---------------------------------------------------------------------------
# WM7 -- remove() for a missing/invalid workflow_id raises
# ---------------------------------------------------------------------------
def scenario_remove_missing_raises() -> None:
    manager = WorkflowManager()
    workflow = _make_workflow()
    manager.add(workflow)

    raised_missing = False
    try:
        manager.remove("does-not-exist")
    except WorkflowManagerError:
        raised_missing = True

    check(
        raised_missing,
        "WM7: remove() for a missing workflow_id raises WorkflowManagerError",
    )
    check(
        manager.count() == 1,
        "WM7: a rejected remove() call leaves the manager unchanged",
    )

    for bad_id in ("", "   ", None, 123):
        raised_invalid = False
        try:
            manager.remove(bad_id)
        except WorkflowManagerError:
            raised_invalid = True

        check(
            raised_invalid,
            f"WM7: remove({bad_id!r}) (invalid workflow_id) raises "
            f"WorkflowManagerError",
        )


# ---------------------------------------------------------------------------
# WM8 -- get() returns the matching Workflow without removing it
# ---------------------------------------------------------------------------
def scenario_get_does_not_remove() -> None:
    manager = WorkflowManager()
    workflow = _make_workflow()
    manager.add(workflow)

    fetched_once = manager.get(workflow.workflow_id)
    fetched_twice = manager.get(workflow.workflow_id)

    check(fetched_once is workflow, "WM8: get() returns the matching workflow")
    check(
        fetched_once is fetched_twice,
        "WM8: calling get() repeatedly returns the same workflow each time",
    )
    check(manager.count() == 1, "WM8: get() never changes count()")


# ---------------------------------------------------------------------------
# WM9 -- get() for a missing/invalid workflow_id raises
# ---------------------------------------------------------------------------
def scenario_get_missing_raises() -> None:
    manager = WorkflowManager()

    raised_missing = False
    try:
        manager.get("does-not-exist")
    except WorkflowManagerError:
        raised_missing = True

    check(
        raised_missing,
        "WM9: get() for a missing workflow_id raises WorkflowManagerError",
    )

    for bad_id in ("", "   ", None, 123):
        raised_invalid = False
        try:
            manager.get(bad_id)
        except WorkflowManagerError:
            raised_invalid = True

        check(
            raised_invalid,
            f"WM9: get({bad_id!r}) (invalid workflow_id) raises "
            f"WorkflowManagerError",
        )


# ---------------------------------------------------------------------------
# WM10 -- contains() tracks state, raises on invalid workflow_id
# ---------------------------------------------------------------------------
def scenario_contains_tracks_state_and_validates() -> None:
    manager = WorkflowManager()
    workflow = _make_workflow()

    check(
        manager.contains(workflow.workflow_id) is False,
        "WM10: contains() is False before add()",
    )

    manager.add(workflow)
    check(
        manager.contains(workflow.workflow_id) is True,
        "WM10: contains() is True after add()",
    )

    manager.remove(workflow.workflow_id)
    check(
        manager.contains(workflow.workflow_id) is False,
        "WM10: contains() is False again after remove()",
    )

    manager.add(workflow)
    manager.clear()
    check(
        manager.contains(workflow.workflow_id) is False,
        "WM10: contains() is False after clear()",
    )

    for bad_id in ("", "   ", None, 123):
        raised_invalid = False
        try:
            manager.contains(bad_id)
        except WorkflowManagerError:
            raised_invalid = True

        check(
            raised_invalid,
            f"WM10: contains({bad_id!r}) (invalid workflow_id) raises "
            f"WorkflowManagerError",
        )


# ---------------------------------------------------------------------------
# WM11 -- count() accurately tracks state
# ---------------------------------------------------------------------------
def scenario_count_tracks_operations() -> None:
    manager = WorkflowManager()

    check(manager.count() == 0, "WM11: count() starts at 0")

    manager.add(_make_workflow(name="a"))
    manager.add(_make_workflow(name="b"))
    check(manager.count() == 2, "WM11: count() reflects two add() calls")

    manager.remove(manager.workflows()[0].workflow_id)
    check(manager.count() == 1, "WM11: count() reflects one remove() call")

    manager.clear()
    check(manager.count() == 0, "WM11: count() reflects clear()")


# ---------------------------------------------------------------------------
# WM12 -- clear() behavior
# ---------------------------------------------------------------------------
def scenario_clear_behavior() -> None:
    manager = WorkflowManager()
    manager.add(_make_workflow(name="a"))
    manager.add(_make_workflow(name="b"))

    result = manager.clear()

    check(result is None, "WM12: clear() returns None")
    check(
        manager.count() == 0 and manager.workflows() == (),
        "WM12: clear() empties a non-empty manager",
    )

    manager.clear()
    check(manager.count() == 0, "WM12: clear() is idempotent on an already-empty manager")

    other_manager = WorkflowManager()
    other_manager.add(_make_workflow(name="untouched"))
    manager.clear()
    check(
        other_manager.count() == 1,
        "WM12: clear() only affects the instance it was called on",
    )


# ---------------------------------------------------------------------------
# WM13 -- workflows() returns an immutable, independent snapshot
# ---------------------------------------------------------------------------
def scenario_workflows_snapshot_is_immutable_and_independent() -> None:
    manager = WorkflowManager()
    workflow_a = _make_workflow(name="a")
    workflow_b = _make_workflow(name="b")
    manager.add(workflow_a)
    manager.add(workflow_b)

    snapshot = manager.workflows()

    raised = False
    try:
        snapshot[0] = workflow_b  # type: ignore[index]
    except TypeError:
        raised = True

    check(raised, "WM13: workflows() returns a tuple that rejects item assignment")

    mutable_copy = list(snapshot)
    mutable_copy.append(_make_workflow(name="extra"))
    mutable_copy.pop(0)

    check(
        manager.count() == 2 and manager.workflows() == (workflow_a, workflow_b),
        "WM13: mutating a list built from workflows() never changes the "
        "manager's own state",
    )

    another_snapshot = manager.workflows()
    check(
        another_snapshot is not snapshot,
        "WM13: workflows() returns a fresh tuple object on each call",
    )


# ---------------------------------------------------------------------------
# WM14 -- independent WorkflowManager instances
# ---------------------------------------------------------------------------
def scenario_independent_manager_instances() -> None:
    manager_a = WorkflowManager()
    manager_b = WorkflowManager()

    manager_a.add(_make_workflow(name="a"))
    manager_a.add(_make_workflow(name="a2"))

    check(
        manager_b.count() == 0,
        "WM14: adding on one WorkflowManager never affects a different "
        "instance's count",
    )

    manager_b.add(_make_workflow(name="b"))
    check(
        manager_a.count() == 2,
        "WM14: adding on the second WorkflowManager never affects the "
        "first",
    )


# ---------------------------------------------------------------------------
# WM15 -- repr() is stable and informative
# ---------------------------------------------------------------------------
def scenario_repr_is_stable_and_informative() -> None:
    manager = WorkflowManager()

    check(
        repr(manager) == "WorkflowManager(count=0)",
        "WM15: repr() reflects an empty manager's count",
    )

    workflow = _make_workflow()
    manager.add(workflow)
    check(
        repr(manager) == "WorkflowManager(count=1)",
        "WM15: repr() updates after add()",
    )

    manager.remove(workflow.workflow_id)
    check(
        repr(manager) == "WorkflowManager(count=0)",
        "WM15: repr() updates after remove()",
    )


# ---------------------------------------------------------------------------
# WM16 -- no execution/scheduling/queue/engine/persistence/eventing surface
# ---------------------------------------------------------------------------
def scenario_no_execution_or_forbidden_surface() -> None:
    manager = WorkflowManager()

    forbidden_members = (
        "run",
        "start",
        "stop",
        "cancel",
        "tick",
        "schedule",
        "pause",
        "resume",
        "retry",
        "timeout",
        "execute",
        "save",
        "load",
        "to_dict",
        "from_dict",
        "to_json",
        "from_json",
        "serialize",
        "deserialize",
        "publish",
        "subscribe",
        "unsubscribe",
        "task_queue",
        "task_manager",
        "scheduler",
        "host",
        "agent",
        "workflow_engine",
        "event_bus",
        "pipeline",
        "runtime_analysis_pipeline",
    )

    none_present = all(
        not hasattr(manager, member) for member in forbidden_members
    )
    check(
        none_present,
        "WM16: WorkflowManager exposes none of the forbidden execution/"
        "scheduling/queue/engine/persistence/eventing members",
    )


# ---------------------------------------------------------------------------
# WM17 -- WorkflowManagerError is an AgentError
# ---------------------------------------------------------------------------
def scenario_workflow_manager_error_is_agent_error_subclass() -> None:
    check(
        issubclass(WorkflowManagerError, AgentError),
        "WM17: WorkflowManagerError is a subclass of "
        "Core.exceptions.AgentError",
    )

    raised_as_agent_error = False
    try:
        WorkflowManager().get("missing")
    except AgentError:
        raised_as_agent_error = True

    check(
        raised_as_agent_error,
        "WM17: a WorkflowManagerError from a missing get() can be caught "
        "as AgentError",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_new_manager_starts_empty,
        scenario_add_adds_one_workflow,
        scenario_add_rejects_invalid_input,
        scenario_add_rejects_duplicate_workflow_id,
        scenario_insertion_order_preserved,
        scenario_remove_removes_and_returns_workflow,
        scenario_remove_missing_raises,
        scenario_get_does_not_remove,
        scenario_get_missing_raises,
        scenario_contains_tracks_state_and_validates,
        scenario_count_tracks_operations,
        scenario_clear_behavior,
        scenario_workflows_snapshot_is_immutable_and_independent,
        scenario_independent_manager_instances,
        scenario_repr_is_stable_and_informative,
        scenario_no_execution_or_forbidden_surface,
        scenario_workflow_manager_error_is_agent_error_subclass,
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
    print(f"PHASE 3 SPRINT 28 WORKFLOW MANAGER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())