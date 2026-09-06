"""
Phase 3 Sprint 29 proof suite -- the ``WorkflowEngine`` preparation
layer.

Scope: dedicated regression suite for
``Orchestration.workflow_engine.WorkflowEngine``/
``WorkflowEngineError`` only. ``Orchestration.workflow.Workflow``
(covered by ``Tests/test_stage_l28_sprint27_workflow.py``),
``Orchestration.workflow_manager.WorkflowManager`` (covered by
``Tests/test_stage_l28_sprint28_workflow_manager.py``),
``Orchestration.task_manager.TaskManager`` (covered by
``Tests/test_stage_l28_sprint26_task_manager.py``),
``Orchestration.task_queue.TaskQueue``, and ``Orchestration.task.
Task`` are all unmodified and are not re-verified beyond what
``WorkflowEngine`` itself needs -- real instances of each are used
throughout here. ``AutonomousScheduler``, ``AutonomousHost``,
``AutonomousAgent``, ``RuntimeAnalysisPipeline``, ``EventBus``, and
the Composition Root are all untouched by this Sprint and are not
exercised by this suite.

``WorkflowEngine`` is a pure preparation layer: no ``Task`` is ever
run, no ``Task.status``/``Workflow.status`` is ever mutated, and no
scheduler/host/agent/pipeline/EventBus knowledge, retries, dependency
graph, branching, persistence, threading, or asyncio exist anywhere in
``Orchestration/workflow_engine.py`` -- this suite proves the
*absence* of that surface area as much as it proves the presence of
the load/prepare/unload behavior itself.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x / Sprint 1x-2x proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    E1  -- the constructor rejects a None task_manager, and rejects a
           non-TaskManager object.
    E2  -- constructing a WorkflowEngine with a valid TaskManager
           succeeds, and current_workflow() starts as None.
    E3  -- load() validates its input: it rejects a None workflow and
           a non-Workflow object, leaving whatever was previously
           loaded (if anything) unchanged.
    E4  -- load() with a valid Workflow succeeds, is reflected via
           current_workflow(), and returns None.
    E5  -- load() called a second time replaces the previously loaded
           workflow -- current_workflow() reflects only the newest
           one.
    E6  -- unload() removes the currently-loaded workflow --
           current_workflow() becomes None -- and is safe (a no-op)
           when nothing is loaded.
    E7  -- current_workflow() returns exactly the Workflow instance
           passed to the most recent load() (by identity), or None.
    E8  -- prepare() with no workflow loaded raises
           WorkflowEngineError, and does not touch the bound
           TaskManager.
    E9  -- prepare() clears the bound TaskManager first, then submits
           every Task from the loaded Workflow.tasks, in order --
           verified both via the TaskManager's own task_count()/
           has_tasks() and by draining it with next_task() and
           comparing against Workflow.tasks.
    E10 -- prepare() returns exactly len(workflow.tasks) -- the count
           of tasks submitted.
    E11 -- prepare() on a Workflow with an empty tasks tuple submits
           nothing, still clears the TaskManager, and returns 0.
    E12 -- task ordering: Workflow.tasks order is preserved exactly
           in the order Tasks come back out of the TaskManager via
           next_task().
    E13 -- TaskManager delegation: prepare() only calls the
           TaskManager's own public clear()/submit() -- verified by
           constructing the TaskManager around a real TaskQueue and
           confirming that queue ends up in the exact state directly
           calling clear()/enqueue() in the same order would produce.
    E14 -- calling prepare() twice in a row (same workflow still
           loaded) is safe and repeatable -- both calls succeed,
           return the same count, and leave the TaskManager in the
           same final state.
    E15 -- unload() after prepare() clears current_workflow() to None
           but does not touch tasks a prior prepare() already
           submitted to the TaskManager.
    E16 -- WorkflowEngine never mutates Task.status or Workflow.status
           -- loading and preparing a workflow leaves every task's
           status, and the workflow's own status, exactly as
           constructed.
    E17 -- WorkflowEngine exposes no execution/scheduling/persistence/
           eventing/component-knowledge surface (no run/start/stop/
           cancel/tick/schedule/execute/retry members, and no
           scheduler/host/agent/event_bus/runtime_analysis_pipeline
           attributes).
    E18 -- WorkflowEngineError is a subclass of Core.exceptions.
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
from Orchestration.task import Task, TaskStatus
from Orchestration.task_manager import TaskManager
from Orchestration.task_queue import TaskQueue
from Orchestration.workflow import Workflow, WorkflowStatus
from Orchestration.workflow_engine import WorkflowEngine, WorkflowEngineError

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


def _make_task(name: str = "n", description: str = "d", **kwargs) -> Task:
    return Task(name=name, description=description, **kwargs)


def _make_workflow(
    name: str = "wf", description: str = "d", **kwargs
) -> Workflow:
    return Workflow(name=name, description=description, **kwargs)


def _drain(task_manager: TaskManager) -> List[Task]:
    drained: List[Task] = []
    while task_manager.has_tasks():
        drained.append(task_manager.next_task())
    return drained


# ---------------------------------------------------------------------------
# E1 -- constructor rejects None / non-TaskManager
# ---------------------------------------------------------------------------
def scenario_constructor_rejects_invalid_task_manager() -> None:
    raised_none = False
    try:
        WorkflowEngine(None)
    except WorkflowEngineError:
        raised_none = True

    check(raised_none, "E1: WorkflowEngine(None) raises WorkflowEngineError")

    for bad_value in ("not-a-manager", 123, TaskQueue(), [], {}, object()):
        raised_bad = False
        try:
            WorkflowEngine(bad_value)
        except WorkflowEngineError:
            raised_bad = True

        check(
            raised_bad,
            f"E1: WorkflowEngine({bad_value!r}) (non-TaskManager) raises "
            f"WorkflowEngineError",
        )


# ---------------------------------------------------------------------------
# E2 -- valid construction succeeds; current_workflow() starts None
# ---------------------------------------------------------------------------
def scenario_construction_succeeds_and_starts_unloaded() -> None:
    engine = WorkflowEngine(TaskManager(TaskQueue()))

    check(
        engine.current_workflow() is None,
        "E2: a freshly constructed WorkflowEngine's current_workflow() is None",
    )


# ---------------------------------------------------------------------------
# E3 -- load() validates input
# ---------------------------------------------------------------------------
def scenario_load_rejects_invalid_input() -> None:
    engine = WorkflowEngine(TaskManager(TaskQueue()))
    original = _make_workflow(name="original")
    engine.load(original)

    raised_none = False
    try:
        engine.load(None)
    except WorkflowEngineError:
        raised_none = True

    check(raised_none, "E3: load(None) raises WorkflowEngineError")

    for bad_value in ("not-a-workflow", 123, [], {}, object()):
        raised_bad = False
        try:
            engine.load(bad_value)
        except WorkflowEngineError:
            raised_bad = True

        check(
            raised_bad,
            f"E3: load({bad_value!r}) (non-Workflow) raises "
            f"WorkflowEngineError",
        )

    check(
        engine.current_workflow() is original,
        "E3: a rejected load() call leaves the previously loaded workflow "
        "unchanged",
    )


# ---------------------------------------------------------------------------
# E4 -- load() with a valid Workflow succeeds
# ---------------------------------------------------------------------------
def scenario_load_succeeds() -> None:
    engine = WorkflowEngine(TaskManager(TaskQueue()))
    workflow = _make_workflow()

    result = engine.load(workflow)

    check(result is None, "E4: load() returns None")
    check(
        engine.current_workflow() is workflow,
        "E4: load() is reflected via current_workflow()",
    )


# ---------------------------------------------------------------------------
# E5 -- load() replaces the previously loaded workflow
# ---------------------------------------------------------------------------
def scenario_load_replaces_previous_workflow() -> None:
    engine = WorkflowEngine(TaskManager(TaskQueue()))
    first = _make_workflow(name="first")
    second = _make_workflow(name="second")

    engine.load(first)
    check(
        engine.current_workflow() is first,
        "E5: current_workflow() reflects the first load()",
    )

    engine.load(second)
    check(
        engine.current_workflow() is second,
        "E5: a second load() replaces the first -- current_workflow() "
        "reflects only the newest workflow",
    )


# ---------------------------------------------------------------------------
# E6 -- unload() removes the current workflow, no-op when unloaded
# ---------------------------------------------------------------------------
def scenario_unload_removes_current_workflow() -> None:
    engine = WorkflowEngine(TaskManager(TaskQueue()))
    engine.load(_make_workflow())

    result = engine.unload()

    check(result is None, "E6: unload() returns None")
    check(
        engine.current_workflow() is None,
        "E6: unload() clears current_workflow() to None",
    )

    # calling unload() again when nothing is loaded is a safe no-op
    result_again = engine.unload()
    check(
        result_again is None and engine.current_workflow() is None,
        "E6: unload() is a safe no-op when nothing is currently loaded",
    )


# ---------------------------------------------------------------------------
# E7 -- current_workflow() returns exactly what was loaded, or None
# ---------------------------------------------------------------------------
def scenario_current_workflow_identity() -> None:
    engine = WorkflowEngine(TaskManager(TaskQueue()))
    check(
        engine.current_workflow() is None,
        "E7: current_workflow() is None before any load()",
    )

    workflow = _make_workflow()
    engine.load(workflow)
    check(
        engine.current_workflow() is workflow,
        "E7: current_workflow() returns exactly the loaded Workflow by "
        "identity",
    )


# ---------------------------------------------------------------------------
# E8 -- prepare() with nothing loaded raises, doesn't touch TaskManager
# ---------------------------------------------------------------------------
def scenario_prepare_without_loaded_workflow_raises() -> None:
    task_manager = TaskManager(TaskQueue())
    task_manager.submit(_make_task(name="pre-existing"))
    engine = WorkflowEngine(task_manager)

    raised = False
    try:
        engine.prepare()
    except WorkflowEngineError:
        raised = True

    check(
        raised,
        "E8: prepare() with no workflow loaded raises WorkflowEngineError",
    )
    check(
        task_manager.task_count() == 1,
        "E8: a rejected prepare() call does not touch the bound "
        "TaskManager",
    )


# ---------------------------------------------------------------------------
# E9 -- prepare() clears then submits every task from the workflow
# ---------------------------------------------------------------------------
def scenario_prepare_clears_and_submits_tasks() -> None:
    task_manager = TaskManager(TaskQueue())
    task_manager.submit(_make_task(name="stale"))
    engine = WorkflowEngine(task_manager)

    tasks = [_make_task(name=f"task-{i}") for i in range(3)]
    workflow = _make_workflow(tasks=tasks)
    engine.load(workflow)

    engine.prepare()

    check(
        task_manager.task_count() == 3,
        "E9: prepare() clears stale tasks and submits every task from the "
        "loaded workflow",
    )
    check(
        task_manager.has_tasks() is True,
        "E9: has_tasks() is True after prepare() with a non-empty workflow",
    )

    drained = _drain(task_manager)
    check(
        drained == tasks,
        "E9: draining the TaskManager after prepare() returns exactly the "
        "workflow's tasks, in order",
    )


# ---------------------------------------------------------------------------
# E10 -- prepare() returns the number of tasks submitted
# ---------------------------------------------------------------------------
def scenario_prepare_returns_submitted_count() -> None:
    engine = WorkflowEngine(TaskManager(TaskQueue()))
    tasks = [_make_task(name=f"task-{i}") for i in range(4)]
    engine.load(_make_workflow(tasks=tasks))

    result = engine.prepare()

    check(result == 4, "E10: prepare() returns len(workflow.tasks)")


# ---------------------------------------------------------------------------
# E11 -- empty workflow: prepare() submits nothing, still clears, returns 0
# ---------------------------------------------------------------------------
def scenario_prepare_with_empty_workflow() -> None:
    task_manager = TaskManager(TaskQueue())
    task_manager.submit(_make_task(name="stale"))
    engine = WorkflowEngine(task_manager)
    engine.load(_make_workflow(tasks=()))

    result = engine.prepare()

    check(result == 0, "E11: prepare() on an empty workflow returns 0")
    check(
        task_manager.task_count() == 0 and task_manager.has_tasks() is False,
        "E11: prepare() on an empty workflow still clears the "
        "TaskManager, leaving it empty",
    )


# ---------------------------------------------------------------------------
# E12 -- task ordering preserved
# ---------------------------------------------------------------------------
def scenario_task_ordering_preserved() -> None:
    task_manager = TaskManager(TaskQueue())
    engine = WorkflowEngine(task_manager)
    tasks = [_make_task(name=f"ordered-{i}") for i in range(6)]
    engine.load(_make_workflow(tasks=tasks))

    engine.prepare()
    drained = _drain(task_manager)

    check(
        drained == tasks,
        "E12: Workflow.tasks order is preserved exactly in the order "
        "Tasks come back out of the TaskManager",
    )


# ---------------------------------------------------------------------------
# E13 -- TaskManager delegation matches direct clear()/enqueue() use
# ---------------------------------------------------------------------------
def scenario_delegation_matches_direct_task_manager_use() -> None:
    via_engine_queue = TaskQueue()
    via_engine_manager = TaskManager(via_engine_queue)
    engine = WorkflowEngine(via_engine_manager)

    direct_queue = TaskQueue()
    direct_manager = TaskManager(direct_queue)

    pre_existing = _make_task(name="pre-existing")
    via_engine_manager.submit(pre_existing)
    direct_manager.submit(pre_existing)

    tasks = [_make_task(name=f"t-{i}") for i in range(3)]
    engine.load(_make_workflow(tasks=tasks))

    engine.prepare()

    direct_manager.clear()
    for task in tasks:
        direct_manager.submit(task)

    check(
        via_engine_queue.tasks() == direct_queue.tasks(),
        "E13: prepare() only calls the TaskManager's own public clear()/"
        "submit() -- the resulting TaskQueue state exactly matches doing "
        "the same operations directly",
    )


# ---------------------------------------------------------------------------
# E14 -- prepare() twice in a row is safe and repeatable
# ---------------------------------------------------------------------------
def scenario_prepare_twice_is_safe() -> None:
    task_manager = TaskManager(TaskQueue())
    engine = WorkflowEngine(task_manager)
    tasks = [_make_task(name=f"t-{i}") for i in range(3)]
    engine.load(_make_workflow(tasks=tasks))

    first_result = engine.prepare()
    first_state = task_manager.task_count()

    second_result = engine.prepare()
    second_state = task_manager.task_count()

    check(
        first_result == second_result == 3,
        "E14: calling prepare() twice returns the same count both times",
    )
    check(
        first_state == second_state == 3,
        "E14: calling prepare() twice leaves the TaskManager in the same "
        "final state both times",
    )


# ---------------------------------------------------------------------------
# E15 -- unload() after prepare() doesn't touch already-submitted tasks
# ---------------------------------------------------------------------------
def scenario_unload_after_prepare_preserves_submitted_tasks() -> None:
    task_manager = TaskManager(TaskQueue())
    engine = WorkflowEngine(task_manager)
    tasks = [_make_task(name=f"t-{i}") for i in range(2)]
    engine.load(_make_workflow(tasks=tasks))

    engine.prepare()
    engine.unload()

    check(
        engine.current_workflow() is None,
        "E15: unload() after prepare() clears current_workflow() to None",
    )
    check(
        task_manager.task_count() == 2,
        "E15: unload() after prepare() does not touch tasks already "
        "submitted to the TaskManager",
    )


# ---------------------------------------------------------------------------
# E16 -- no Task.status or Workflow.status mutation
# ---------------------------------------------------------------------------
def scenario_no_status_mutation() -> None:
    tasks = [_make_task(name=f"t-{i}") for i in range(3)]
    original_statuses = [task.status for task in tasks]
    workflow = _make_workflow(tasks=tasks)
    original_workflow_status = workflow.status

    task_manager = TaskManager(TaskQueue())
    engine = WorkflowEngine(task_manager)
    engine.load(workflow)
    engine.prepare()
    drained = _drain(task_manager)

    check(
        [t.status for t in drained] == original_statuses,
        "E16: preparing and draining a workflow's tasks leaves every "
        "Task.status exactly as constructed",
    )
    check(
        workflow.status == original_workflow_status
        and workflow.status == WorkflowStatus.CREATED,
        "E16: loading/preparing a Workflow never changes its own status",
    )
    check(
        all(t.status == TaskStatus.PENDING for t in drained),
        "E16: no Task in the drained workflow was transitioned out of "
        "PENDING",
    )


# ---------------------------------------------------------------------------
# E17 -- no execution/scheduling/persistence/eventing/component surface
# ---------------------------------------------------------------------------
def scenario_no_execution_or_forbidden_surface() -> None:
    engine = WorkflowEngine(TaskManager(TaskQueue()))

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
        "load_from_disk",
        "to_dict",
        "from_dict",
        "to_json",
        "from_json",
        "serialize",
        "deserialize",
        "publish",
        "subscribe",
        "unsubscribe",
        "scheduler",
        "host",
        "agent",
        "event_bus",
        "pipeline",
        "runtime_analysis_pipeline",
        "add_dependency",
        "dependencies",
        "traverse",
        "graph",
    )

    none_present = all(
        not hasattr(engine, member) for member in forbidden_members
    )
    check(
        none_present,
        "E17: WorkflowEngine exposes none of the forbidden execution/"
        "scheduling/persistence/eventing/component-knowledge members",
    )


# ---------------------------------------------------------------------------
# E18 -- WorkflowEngineError is an AgentError
# ---------------------------------------------------------------------------
def scenario_workflow_engine_error_is_agent_error_subclass() -> None:
    check(
        issubclass(WorkflowEngineError, AgentError),
        "E18: WorkflowEngineError is a subclass of "
        "Core.exceptions.AgentError",
    )

    raised_as_agent_error = False
    try:
        WorkflowEngine(None)
    except AgentError:
        raised_as_agent_error = True

    check(
        raised_as_agent_error,
        "E18: a WorkflowEngineError from an invalid constructor call can "
        "be caught as AgentError",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_rejects_invalid_task_manager,
        scenario_construction_succeeds_and_starts_unloaded,
        scenario_load_rejects_invalid_input,
        scenario_load_succeeds,
        scenario_load_replaces_previous_workflow,
        scenario_unload_removes_current_workflow,
        scenario_current_workflow_identity,
        scenario_prepare_without_loaded_workflow_raises,
        scenario_prepare_clears_and_submits_tasks,
        scenario_prepare_returns_submitted_count,
        scenario_prepare_with_empty_workflow,
        scenario_task_ordering_preserved,
        scenario_delegation_matches_direct_task_manager_use,
        scenario_prepare_twice_is_safe,
        scenario_unload_after_prepare_preserves_submitted_tasks,
        scenario_no_status_mutation,
        scenario_no_execution_or_forbidden_surface,
        scenario_workflow_engine_error_is_agent_error_subclass,
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
    print(f"PHASE 3 SPRINT 29 WORKFLOW ENGINE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())