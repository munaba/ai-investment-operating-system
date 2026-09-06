"""
Phase 3 Sprint 32/33 proof suite -- the Workflow-to-Executor bridge,
now living on ``WorkflowExecutionCoordinator.execute_workflow()``.

Scope: Sprint 32 originally added this bridge as ``Orchestration.
executor.Executor.execute_workflow()``. Sprint 33 (Executor
Decoupling) removed that method from ``Executor`` -- along with
``Executor``'s direct imports of ``WorkflowEngine`` and
``ExecutionContext`` -- and moved the exact same behavior to a new,
dedicated orchestration-layer component, ``Orchestration.
workflow_execution_coordinator.WorkflowExecutionCoordinator``. This
suite is updated accordingly: every scenario that used to call
``executor.execute_workflow(...)`` now calls ``coordinator.
execute_workflow(executor, ...)`` on a shared, stateless
``WorkflowExecutionCoordinator`` instance, and validation-failure
checks now expect ``WorkflowExecutionCoordinatorError`` instead of
``ExecutorError``. All of the originally-locked invariants (W1-W22)
are otherwise unchanged -- this is a routing update, not a behavior
change. ``Orchestration.workflow_engine.WorkflowEngine`` (covered by
``Tests/test_stage_l28_sprint29_workflow_engine.py``),
``Orchestration.workflow.Workflow`` (Sprint 27),
``Orchestration.task_manager.TaskManager`` (Sprint 26),
``Orchestration.task_queue.TaskQueue`` (Sprint 25),
``Orchestration.task.Task`` (Sprint 24), and
``Orchestration.execution_context.ExecutionContext`` (Sprint 31) are
all unmodified by Sprint 33 and are not re-verified beyond what
``execute_workflow()`` itself needs -- real instances of each are used
throughout. ``WorkflowManager``, ``AutonomousScheduler``,
``AutonomousAgent``, ``RuntimeAnalysisPipeline``, ``EventBus``, and
the Composition Root are all untouched by this sprint and are not
exercised by this suite. ``AutonomousHost`` is exercised only through
the same recording-subclass technique Sprint 30's suite uses, since
constructing a real ``AutonomousAgent`` requires a full
``RuntimeAnalysisPipeline`` collaborator graph that remains out of
scope.

``execute_workflow()`` introduces no second execution engine: this
suite proves it is nothing more than input validation, a loaded-
workflow check, exactly one ``workflow_engine.prepare()`` call, and a
straight delegation to the already-existing, unmodified ``Executor.
execute()`` -- with ``WorkflowEngine`` remaining the sole owner of
preparation and ``Executor`` remaining the sole owner of execution, no
direct ``TaskQueue`` access anywhere, and no mutation of
``Workflow.status``, ``Task.status``, or ``ExecutionContext``. As of
Sprint 33, ``Executor`` itself no longer imports or references
``WorkflowEngine``/``Workflow``/``ExecutionContext`` at all --
``WorkflowExecutionCoordinator`` is the sole component that depends on
both ``WorkflowEngine`` and ``Executor``.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x / Sprint 1x-33 proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    W1  -- Executor's Sprint 30 constructor validation is unchanged:
           it still rejects a None/non-TaskManager task_manager and a
           None/non-AutonomousHost host.
    W2  -- execute_workflow() rejects a None workflow_engine, and a
           non-WorkflowEngine object, without calling prepare() or
           execute() or touching the TaskManager.
    W3  -- execute_workflow() rejects a None context, and a
           non-ExecutionContext object, without calling prepare() or
           execute() or touching the TaskManager.
    W4  -- execute_workflow() rejects an invalid 'iterations' (zero,
           negative, non-int, and bool), without calling prepare() or
           execute() or touching the TaskManager.
    W5  -- execute_workflow() with no Workflow loaded on
           workflow_engine raises WorkflowExecutionCoordinatorError,
           and never calls
           prepare() or touches the TaskManager.
    W6  -- prepare() is called exactly once per execute_workflow()
           call -- verified via a call-counting WorkflowEngine
           subclass.
    W7  -- the underlying execute() logic is exercised exactly once
           per execute_workflow() call (no duplicate/parallel
           execution loop) -- verified via host.start() call counts
           matching the workflow's task count.
    W8  -- the int execute_workflow() returns is forwarded unchanged
           from the delegated execute() call.
    W9  -- an empty Workflow (no tasks) still calls prepare() exactly
           once, makes no host.start() calls, and returns 0.
    W10 -- a Workflow with many tasks: execute_workflow() with
           iterations >= task count executes every task exactly once.
    W11 -- iteration limit: execute_workflow() with iterations less
           than the task count stops after exactly that many tasks,
           leaving the remainder pending in the TaskManager.
    W12 -- task order preserved: Workflow.tasks order is preserved
           exactly in the order tasks are delegated to host.start().
    W13 -- WorkflowEngine remains responsible for preparation --
           prepare()'s own clear-then-submit behavior (already locked
           by Sprint 29) is exercised unchanged; Executor never
           submits/clears tasks itself.
    W14 -- Executor remains responsible for execution -- every
           delegated Task reaches AutonomousHost.start() through the
           exact same code path execute() already uses (same call
           shape: (task, context, 1)).
    W15 -- TaskQueue is never accessed directly by execute_workflow()
           -- verified via AST inspection of the (still-unmodified,
           beyond the one new method) executor.py module surface, and
           via a real TaskQueue behaving identically whether reached
           through execute_workflow() or through direct
           TaskManager/TaskQueue calls.
    W16 -- TaskManager delegation is unchanged: execute_workflow()'s
           dequeuing goes through the exact same TaskManager.
           next_task()/has_tasks() calls execute() already used.
    W17 -- Workflow.status is never mutated by execute_workflow().
    W18 -- Task.status is never mutated by execute_workflow().
    W19 -- the ExecutionContext instance passed to execute_workflow()
           is unchanged (by identity and by field values) after the
           call returns, and is exactly the object passed to
           host.start().
    W20 -- exception propagation: an exception raised by
           workflow_engine.prepare() propagates unchanged out of
           execute_workflow(), and one raised by the delegated
           execute()/host.start() propagates unchanged too.
    W21 -- multiple execute_workflow() calls: calling it twice in a
           row (workflow reloaded/re-prepared) is safe and repeatable,
           and calling it again against an engine whose workflow was
           already fully drained re-prepares (via prepare()'s own
           clear+resubmit) and executes it again from scratch.
    W22 -- no hidden state: two Executor instances constructed
           identically behave identically, and execute_workflow()
           leaves no new instance attributes on the Executor beyond
           what the Sprint 30 constructor already set.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.autonomous_host import AutonomousHost
from Orchestration.execution_context import ExecutionContext
from Orchestration.executor import Executor, ExecutorError
from Orchestration.workflow_execution_coordinator import (
    WorkflowExecutionCoordinator,
    WorkflowExecutionCoordinatorError,
)
from Orchestration.task import Task, TaskStatus
from Orchestration.task_manager import TaskManager
from Orchestration.task_queue import TaskQueue
from Orchestration.workflow import Workflow, WorkflowStatus
from Orchestration.workflow_engine import WorkflowEngine

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []

# ``WorkflowExecutionCoordinator`` is stateless (Sprint 33), so a single
# module-level instance is safe to reuse across every scenario below --
# mirroring how a single ``Executor``/``WorkflowEngine`` pair is reused
# within a scenario via ``_make_stack()``.
coordinator = WorkflowExecutionCoordinator()


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


def _make_context(workflow_id: str = "wf-1", **kwargs) -> ExecutionContext:
    return ExecutionContext(workflow_id=workflow_id, **kwargs)


class RecordingHost(AutonomousHost):
    """See Tests/test_stage_l28_sprint30_executor.py -- identical
    technique: a thin ``AutonomousHost`` subclass overriding only
    ``start()`` to record every call, keeping ``isinstance(host,
    AutonomousHost)`` true without requiring a real ``AutonomousAgent``
    /``RuntimeAnalysisPipeline`` graph.
    """

    def __init__(self) -> None:
        self.calls: List[Tuple[object, object, object]] = []

    def start(self, agent, context, iterations):  # type: ignore[override]
        self.calls.append((agent, context, iterations))
        return ()


class CountingWorkflowEngine(WorkflowEngine):
    """A ``WorkflowEngine`` subclass that counts ``prepare()`` calls
    without changing its behavior at all -- ``prepare()`` still calls
    ``super().prepare()`` and returns exactly what that returns.

    Used to prove ``execute_workflow()`` calls ``prepare()`` exactly
    once per call (W6), while still exercising the real, unmodified
    Sprint 29 ``prepare()``/``load()``/``current_workflow()``
    behavior underneath.
    """

    def __init__(self, task_manager: TaskManager) -> None:
        super().__init__(task_manager)
        self.prepare_call_count = 0

    def prepare(self) -> int:
        self.prepare_call_count += 1
        return super().prepare()


def _make_stack(
    tasks: List[Task] = None,
) -> Tuple[Executor, CountingWorkflowEngine, TaskManager, RecordingHost]:
    task_manager = TaskManager(TaskQueue())
    host = RecordingHost()
    executor = Executor(task_manager, host)
    workflow_engine = CountingWorkflowEngine(task_manager)
    if tasks is not None:
        workflow_engine.load(_make_workflow(tasks=tasks))
    return executor, workflow_engine, task_manager, host


def _drain(task_manager: TaskManager) -> List[Task]:
    drained: List[Task] = []
    while task_manager.has_tasks():
        drained.append(task_manager.next_task())
    return drained


# ---------------------------------------------------------------------------
# W1 -- Sprint 30 constructor validation unchanged
# ---------------------------------------------------------------------------
def scenario_constructor_validation_unchanged() -> None:
    host = RecordingHost()

    raised_none_manager = False
    try:
        Executor(None, host)
    except ExecutorError:
        raised_none_manager = True
    check(
        raised_none_manager,
        "W1: Executor(None, host) still raises ExecutorError",
    )

    for bad_value in ("not-a-manager", 123, TaskQueue(), [], {}, object()):
        raised = False
        try:
            Executor(bad_value, host)
        except ExecutorError:
            raised = True
        check(
            raised,
            f"W1: Executor({bad_value!r}, host) (non-TaskManager) still "
            f"raises ExecutorError",
        )

    task_manager = TaskManager(TaskQueue())
    raised_none_host = False
    try:
        Executor(task_manager, None)
    except ExecutorError:
        raised_none_host = True
    check(
        raised_none_host,
        "W1: Executor(task_manager, None) still raises ExecutorError",
    )

    for bad_value in ("not-a-host", 123, TaskManager(TaskQueue()), [], {}, object()):
        raised = False
        try:
            Executor(task_manager, bad_value)
        except ExecutorError:
            raised = True
        check(
            raised,
            f"W1: Executor(task_manager, {bad_value!r}) (non-AutonomousHost) "
            f"still raises ExecutorError",
        )


# ---------------------------------------------------------------------------
# W2 -- execute_workflow() rejects an invalid workflow_engine
# ---------------------------------------------------------------------------
def scenario_execute_workflow_rejects_invalid_workflow_engine() -> None:
    task_manager = TaskManager(TaskQueue())
    host = RecordingHost()
    executor = Executor(task_manager, host)
    context = _make_context()

    raised_none = False
    try:
        coordinator.execute_workflow(executor, None, context)
    except WorkflowExecutionCoordinatorError:
        raised_none = True
    check(
        raised_none,
        "W2: execute_workflow(None, context) raises WorkflowExecutionCoordinatorError",
    )

    for bad_value in ("not-an-engine", 123, [], {}, object(), task_manager):
        raised = False
        try:
            coordinator.execute_workflow(executor, bad_value, context)
        except WorkflowExecutionCoordinatorError:
            raised = True
        check(
            raised,
            f"W2: execute_workflow({bad_value!r}, context) "
            f"(non-WorkflowEngine) raises WorkflowExecutionCoordinatorError",
        )

    check(
        len(host.calls) == 0 and task_manager.task_count() == 0,
        "W2: rejected workflow_engine values never call host.start() or "
        "touch the TaskManager",
    )


# ---------------------------------------------------------------------------
# W3 -- execute_workflow() rejects an invalid context
# ---------------------------------------------------------------------------
def scenario_execute_workflow_rejects_invalid_context() -> None:
    executor, workflow_engine, task_manager, host = _make_stack(
        tasks=[_make_task(name="only")]
    )

    raised_none = False
    try:
        coordinator.execute_workflow(executor, workflow_engine, None)
    except WorkflowExecutionCoordinatorError:
        raised_none = True
    check(
        raised_none,
        "W3: execute_workflow(workflow_engine, None) raises WorkflowExecutionCoordinatorError",
    )

    for bad_value in ("not-a-context", 123, [], {}, object(), {"workflow_id": "x"}):
        raised = False
        try:
            coordinator.execute_workflow(executor, workflow_engine, bad_value)
        except WorkflowExecutionCoordinatorError:
            raised = True
        check(
            raised,
            f"W3: execute_workflow(workflow_engine, {bad_value!r}) "
            f"(non-ExecutionContext) raises WorkflowExecutionCoordinatorError",
        )

    check(
        workflow_engine.prepare_call_count == 0,
        "W3: rejected context values never call workflow_engine.prepare()",
    )
    check(
        len(host.calls) == 0 and task_manager.task_count() == 0,
        "W3: rejected context values never call host.start() or touch "
        "the TaskManager",
    )


# ---------------------------------------------------------------------------
# W4 -- execute_workflow() rejects invalid iterations
# ---------------------------------------------------------------------------
def scenario_execute_workflow_rejects_invalid_iterations() -> None:
    for bad_iterations in (0, -1, -5, "1", 1.5, None, True, False, [], {}):
        executor, workflow_engine, task_manager, host = _make_stack(
            tasks=[_make_task(name="only")]
        )
        context = _make_context()

        raised = False
        try:
            coordinator.execute_workflow(
                executor, workflow_engine, context, iterations=bad_iterations
            )
        except WorkflowExecutionCoordinatorError:
            raised = True

        check(
            raised,
            f"W4: execute_workflow(..., iterations={bad_iterations!r}) "
            f"raises WorkflowExecutionCoordinatorError",
        )
        check(
            workflow_engine.prepare_call_count == 0,
            f"W4: iterations={bad_iterations!r} never calls "
            f"workflow_engine.prepare()",
        )
        check(
            len(host.calls) == 0 and task_manager.task_count() == 0,
            f"W4: iterations={bad_iterations!r} never calls host.start() "
            f"or touches the TaskManager",
        )


# ---------------------------------------------------------------------------
# W5 -- no workflow loaded raises, never calls prepare()
# ---------------------------------------------------------------------------
def scenario_execute_workflow_requires_loaded_workflow() -> None:
    executor, workflow_engine, task_manager, host = _make_stack()
    context = _make_context()

    check(
        workflow_engine.current_workflow() is None,
        "W5: precondition -- nothing is loaded on the WorkflowEngine",
    )

    raised = False
    try:
        coordinator.execute_workflow(executor, workflow_engine, context)
    except WorkflowExecutionCoordinatorError:
        raised = True

    check(
        raised,
        "W5: execute_workflow() with no Workflow loaded raises "
        "WorkflowExecutionCoordinatorError",
    )
    check(
        workflow_engine.prepare_call_count == 0,
        "W5: execute_workflow() with no Workflow loaded never calls "
        "prepare()",
    )
    check(
        len(host.calls) == 0 and task_manager.task_count() == 0,
        "W5: execute_workflow() with no Workflow loaded never touches "
        "host.start() or the TaskManager",
    )


# ---------------------------------------------------------------------------
# W6 -- prepare() called exactly once per execute_workflow() call
# ---------------------------------------------------------------------------
def scenario_prepare_called_exactly_once() -> None:
    tasks = [_make_task(name=f"task-{i}") for i in range(3)]
    executor, workflow_engine, _task_manager, _host = _make_stack(tasks=tasks)
    context = _make_context()

    coordinator.execute_workflow(executor, workflow_engine, context, iterations=3)

    check(
        workflow_engine.prepare_call_count == 1,
        "W6: a single execute_workflow() call triggers exactly one "
        "workflow_engine.prepare() call",
    )


# ---------------------------------------------------------------------------
# W7 -- underlying execute() logic runs exactly once per call
# ---------------------------------------------------------------------------
def scenario_execute_runs_exactly_once() -> None:
    tasks = [_make_task(name=f"task-{i}") for i in range(4)]
    executor, workflow_engine, _task_manager, host = _make_stack(tasks=tasks)
    context = _make_context()

    coordinator.execute_workflow(executor, workflow_engine, context, iterations=4)

    check(
        len(host.calls) == 4,
        "W7: exactly one host.start() call is made per Task -- no "
        "duplicate/parallel execution loop",
    )


# ---------------------------------------------------------------------------
# W8 -- returned count forwarded unchanged from execute()
# ---------------------------------------------------------------------------
def scenario_returned_count_forwarded() -> None:
    tasks = [_make_task(name=f"task-{i}") for i in range(3)]
    executor, workflow_engine, task_manager, _host = _make_stack(tasks=tasks)
    context = _make_context()

    workflow_engine.prepare()
    direct_result = executor.execute(context, iterations=3)
    check(
        direct_result == 3,
        "W8: precondition -- direct execute() returns the executed count",
    )

    # Fresh stack for the actual execute_workflow() comparison.
    executor2, workflow_engine2, _tm2, _host2 = _make_stack(tasks=tasks)
    context2 = _make_context()
    result = coordinator.execute_workflow(executor2, workflow_engine2, context2, iterations=3)

    check(
        result == 3,
        "W8: execute_workflow() returns exactly the count execute() "
        "itself would have returned",
    )


# ---------------------------------------------------------------------------
# W9 -- empty workflow: prepare() still called once, 0 host calls, returns 0
# ---------------------------------------------------------------------------
def scenario_empty_workflow() -> None:
    executor, workflow_engine, task_manager, host = _make_stack(tasks=[])
    context = _make_context()

    result = coordinator.execute_workflow(executor, workflow_engine, context, iterations=5)

    check(result == 0, "W9: execute_workflow() on an empty Workflow returns 0")
    check(
        workflow_engine.prepare_call_count == 1,
        "W9: execute_workflow() on an empty Workflow still calls "
        "prepare() exactly once",
    )
    check(
        len(host.calls) == 0,
        "W9: execute_workflow() on an empty Workflow makes no "
        "host.start() calls",
    )
    check(
        task_manager.has_tasks() is False,
        "W9: the TaskManager is left empty after an empty Workflow's "
        "execute_workflow() call",
    )


# ---------------------------------------------------------------------------
# W10 -- many tasks: every task executed exactly once
# ---------------------------------------------------------------------------
def scenario_workflow_with_many_tasks() -> None:
    tasks = [_make_task(name=f"task-{i}") for i in range(10)]
    executor, workflow_engine, task_manager, host = _make_stack(tasks=tasks)
    context = _make_context()

    result = coordinator.execute_workflow(executor, workflow_engine, context, iterations=10)

    check(
        result == 10,
        "W10: execute_workflow() with iterations >= task count executes "
        "every task",
    )
    check(
        len(host.calls) == 10,
        "W10: every one of the 10 tasks produces exactly one "
        "host.start() call",
    )
    check(
        task_manager.has_tasks() is False,
        "W10: the TaskManager is fully drained after all tasks execute",
    )


# ---------------------------------------------------------------------------
# W11 -- iteration limit respected, remainder stays pending
# ---------------------------------------------------------------------------
def scenario_iteration_limit_respected() -> None:
    tasks = [_make_task(name=f"task-{i}") for i in range(6)]
    executor, workflow_engine, task_manager, host = _make_stack(tasks=tasks)
    context = _make_context()

    result = coordinator.execute_workflow(executor, workflow_engine, context, iterations=4)

    check(
        result == 4,
        "W11: execute_workflow() with iterations < task count returns "
        "exactly 'iterations'",
    )
    check(
        len(host.calls) == 4,
        "W11: exactly 'iterations' host.start() calls are made",
    )

    remaining = _drain(task_manager)
    check(
        remaining == tasks[4:],
        "W11: the remaining tasks stay pending in the TaskManager, in "
        "their original order",
    )


# ---------------------------------------------------------------------------
# W12 -- task order preserved
# ---------------------------------------------------------------------------
def scenario_task_order_preserved() -> None:
    tasks = [_make_task(name=f"ordered-{i}") for i in range(7)]
    executor, workflow_engine, _task_manager, host = _make_stack(tasks=tasks)
    context = _make_context()

    coordinator.execute_workflow(executor, workflow_engine, context, iterations=7)

    delegated = [call[0] for call in host.calls]
    check(
        delegated == tasks,
        "W12: Workflow.tasks order is preserved exactly in the order "
        "tasks are delegated to host.start()",
    )


# ---------------------------------------------------------------------------
# W13 -- WorkflowEngine remains responsible for preparation
# ---------------------------------------------------------------------------
def scenario_workflow_engine_owns_preparation() -> None:
    stale_task_manager = TaskManager(TaskQueue())
    stale_task_manager.submit(_make_task(name="stale"))
    workflow_engine = CountingWorkflowEngine(stale_task_manager)
    fresh_tasks = [_make_task(name=f"fresh-{i}") for i in range(2)]
    workflow_engine.load(_make_workflow(tasks=fresh_tasks))

    host = RecordingHost()
    executor = Executor(stale_task_manager, host)
    context = _make_context()

    coordinator.execute_workflow(executor, workflow_engine, context, iterations=2)

    check(
        [call[0] for call in host.calls] == fresh_tasks,
        "W13: prepare()'s clear-then-submit behavior (owned entirely by "
        "WorkflowEngine) removes the stale task and submits only the "
        "freshly-loaded Workflow's tasks",
    )


# ---------------------------------------------------------------------------
# W14 -- Executor remains responsible for execution (same call shape)
# ---------------------------------------------------------------------------
def scenario_executor_owns_execution_same_call_shape() -> None:
    tasks = [_make_task(name="only")]
    executor, workflow_engine, _task_manager, host = _make_stack(tasks=tasks)
    context = _make_context()

    coordinator.execute_workflow(executor, workflow_engine, context, iterations=1)

    check(
        len(host.calls) == 1,
        "W14: exactly one host.start() call is made",
    )
    delegated_task, delegated_context, delegated_iterations = host.calls[0]
    check(
        delegated_task is tasks[0],
        "W14: host.start() receives the exact Task, by identity, same "
        "as a direct execute() call would",
    )
    check(
        delegated_context is context,
        "W14: host.start() receives the exact ExecutionContext, by "
        "identity, same as a direct execute() call would",
    )
    check(
        delegated_iterations == 1,
        "W14: host.start() is called with the same fixed per-task "
        "iterations value (1) that execute() itself always uses",
    )


# ---------------------------------------------------------------------------
# W15 -- TaskQueue never accessed directly
# ---------------------------------------------------------------------------
def scenario_task_queue_never_accessed_directly() -> None:
    import ast

    import Orchestration.executor as executor_module

    tree = ast.parse(Path(executor_module.__file__).read_text())
    imported_names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.append(node.module)
            imported_names.extend(alias.name for alias in node.names)

    check(
        not any("TaskQueue" in name for name in imported_names),
        "W15: Orchestration/executor.py never imports anything "
        "referencing TaskQueue",
    )

    # Behavioral confirmation: draining the TaskManager after
    # execute_workflow() partially consumes it yields the exact same
    # sequence direct TaskQueue enqueue/dequeue calls would produce --
    # i.e. execute_workflow() never bypassed TaskManager to touch the
    # queue in some other way.
    tasks = [_make_task(name=f"task-{i}") for i in range(3)]
    executor, workflow_engine, task_manager, _host = _make_stack(tasks=tasks)
    context = _make_context()
    coordinator.execute_workflow(executor, workflow_engine, context, iterations=1)

    reference_queue = TaskQueue()
    for task in tasks:
        reference_queue.enqueue(task)
    reference_queue.dequeue()

    check(
        _drain(task_manager) == [
            reference_queue.dequeue(),
            reference_queue.dequeue(),
        ],
        "W15: the TaskManager's remaining state after execute_workflow() "
        "matches exactly what direct TaskQueue enqueue/dequeue calls "
        "would produce",
    )


# ---------------------------------------------------------------------------
# W16 -- TaskManager delegation unchanged
# ---------------------------------------------------------------------------
def scenario_task_manager_delegation_unchanged() -> None:
    tasks = [_make_task(name=f"task-{i}") for i in range(3)]
    executor, workflow_engine, task_manager, host = _make_stack(tasks=tasks)
    context = _make_context()

    check(
        executor.has_pending_tasks() is False,
        "W16: has_pending_tasks() reflects the TaskManager before "
        "preparation (nothing submitted yet)",
    )

    coordinator.execute_workflow(executor, workflow_engine, context, iterations=1)

    check(
        executor.has_pending_tasks() == task_manager.has_tasks() is True,
        "W16: has_pending_tasks() still matches TaskManager.has_tasks() "
        "after a partial execute_workflow() call",
    )

    executor.execute("ctx-direct", iterations=2)
    check(
        executor.has_pending_tasks() == task_manager.has_tasks() is False,
        "W16: the same TaskManager can still be drained via a direct "
        "execute() call afterward, exactly as Sprint 30 already proved",
    )


# ---------------------------------------------------------------------------
# W17 -- Workflow.status never mutated
# ---------------------------------------------------------------------------
def scenario_workflow_status_unchanged() -> None:
    tasks = [_make_task(name=f"task-{i}") for i in range(2)]
    task_manager = TaskManager(TaskQueue())
    host = RecordingHost()
    executor = Executor(task_manager, host)
    workflow_engine = CountingWorkflowEngine(task_manager)
    workflow = _make_workflow(tasks=tasks)
    original_status = workflow.status
    workflow_engine.load(workflow)
    context = _make_context()

    coordinator.execute_workflow(executor, workflow_engine, context, iterations=2)

    check(
        workflow.status == original_status,
        "W17: execute_workflow() never mutates Workflow.status",
    )
    check(
        workflow.status == WorkflowStatus.CREATED,
        "W17: the Workflow remains in its constructed status "
        "(CREATED) -- Executor performs no lifecycle transitions",
    )


# ---------------------------------------------------------------------------
# W18 -- Task.status never mutated
# ---------------------------------------------------------------------------
def scenario_task_status_unchanged() -> None:
    tasks = [_make_task(name=f"task-{i}") for i in range(3)]
    original_statuses = [task.status for task in tasks]
    executor, workflow_engine, _task_manager, _host = _make_stack(tasks=tasks)
    context = _make_context()

    coordinator.execute_workflow(executor, workflow_engine, context, iterations=3)

    check(
        all(
            task.status == original
            for task, original in zip(tasks, original_statuses)
        ),
        "W18: execute_workflow() never mutates any Task's status",
    )
    check(
        all(task.status == TaskStatus.PENDING for task in tasks),
        "W18: every Task remains in TaskStatus.PENDING",
    )


# ---------------------------------------------------------------------------
# W19 -- ExecutionContext unchanged
# ---------------------------------------------------------------------------
def scenario_execution_context_unchanged() -> None:
    tasks = [_make_task(name="only")]
    executor, workflow_engine, _task_manager, host = _make_stack(tasks=tasks)
    context = _make_context(
        workflow_id="wf-ctx", task_id="t-ctx", session_id="s-ctx"
    )
    snapshot = (
        context.execution_id,
        context.workflow_id,
        context.task_id,
        context.session_id,
        dict(context.metadata),
        context.created_at,
    )

    coordinator.execute_workflow(executor, workflow_engine, context, iterations=1)

    after_snapshot = (
        context.execution_id,
        context.workflow_id,
        context.task_id,
        context.session_id,
        dict(context.metadata),
        context.created_at,
    )
    check(
        snapshot == after_snapshot,
        "W19: every field of the ExecutionContext is unchanged after "
        "execute_workflow() returns",
    )
    check(
        host.calls[0][1] is context,
        "W19: the exact ExecutionContext instance passed to "
        "execute_workflow() is the one delivered to host.start(), by "
        "identity",
    )


# ---------------------------------------------------------------------------
# W20 -- exception propagation
# ---------------------------------------------------------------------------
class _ExplodingWorkflowEngine(WorkflowEngine):
    def prepare(self) -> int:
        raise RuntimeError("boom-from-prepare")


class _ExplodingHost(AutonomousHost):
    def start(self, agent, context, iterations):  # type: ignore[override]
        raise RuntimeError("boom-from-host-start")


def scenario_exception_propagation() -> None:
    task_manager = TaskManager(TaskQueue())
    host = RecordingHost()
    executor = Executor(task_manager, host)
    exploding_engine = _ExplodingWorkflowEngine(task_manager)
    exploding_engine.load(_make_workflow(tasks=[_make_task(name="x")]))
    context = _make_context()

    raised_from_prepare = False
    try:
        coordinator.execute_workflow(executor, exploding_engine, context)
    except RuntimeError as exc:
        raised_from_prepare = str(exc) == "boom-from-prepare"

    check(
        raised_from_prepare,
        "W20: an exception raised by workflow_engine.prepare() "
        "propagates out of execute_workflow() unchanged",
    )

    task_manager2 = TaskManager(TaskQueue())
    exploding_host = _ExplodingHost()
    executor2 = Executor(task_manager2, exploding_host)
    workflow_engine2 = CountingWorkflowEngine(task_manager2)
    workflow_engine2.load(_make_workflow(tasks=[_make_task(name="y")]))

    raised_from_host = False
    try:
        coordinator.execute_workflow(executor2, workflow_engine2, context)
    except RuntimeError as exc:
        raised_from_host = str(exc) == "boom-from-host-start"

    check(
        raised_from_host,
        "W20: an exception raised by the delegated execute()/"
        "AutonomousHost.start() propagates out of execute_workflow() "
        "unchanged",
    )
    check(
        workflow_engine2.prepare_call_count == 1,
        "W20: prepare() had already succeeded (and was not retried) "
        "before the host-side exception propagated",
    )


# ---------------------------------------------------------------------------
# W21 -- multiple execute_workflow() calls
# ---------------------------------------------------------------------------
def scenario_multiple_execute_workflow_calls() -> None:
    tasks = [_make_task(name=f"task-{i}") for i in range(3)]
    executor, workflow_engine, task_manager, host = _make_stack(tasks=tasks)
    context = _make_context()

    first_result = coordinator.execute_workflow(
        executor, workflow_engine, context, iterations=3
    )
    check(
        first_result == 3 and workflow_engine.prepare_call_count == 1,
        "W21: the first execute_workflow() call executes every task and "
        "calls prepare() once",
    )

    # Second call against the same (already-drained) engine: prepare()
    # clears (a no-op, already empty) and resubmits the same Workflow's
    # tasks from scratch, then executes them again.
    second_result = coordinator.execute_workflow(
        executor, workflow_engine, context, iterations=3
    )
    check(
        second_result == 3,
        "W21: a second execute_workflow() call against the same engine "
        "re-prepares and re-executes the Workflow from scratch",
    )
    check(
        workflow_engine.prepare_call_count == 2,
        "W21: prepare() is called exactly once per execute_workflow() "
        "call -- two calls total across two execute_workflow() calls",
    )
    check(
        len(host.calls) == 6,
        "W21: host.start() is called once per task per "
        "execute_workflow() call -- 3 + 3 = 6 total",
    )
    check(
        [call[0] for call in host.calls] == tasks + tasks,
        "W21: both rounds delegate the same Workflow's tasks, in order",
    )


# ---------------------------------------------------------------------------
# W22 -- no hidden state
# ---------------------------------------------------------------------------
def scenario_no_hidden_state() -> None:
    task_manager_a = TaskManager(TaskQueue())
    host_a = RecordingHost()
    executor_a = Executor(task_manager_a, host_a)
    attrs_before = set(vars(executor_a).keys())

    workflow_engine_a = CountingWorkflowEngine(task_manager_a)
    workflow_engine_a.load(_make_workflow(tasks=[_make_task(name="x")]))
    coordinator.execute_workflow(executor_a, workflow_engine_a, _make_context())

    attrs_after = set(vars(executor_a).keys())
    check(
        attrs_before == attrs_after,
        "W22: execute_workflow() introduces no new instance attributes "
        "on Executor beyond what the Sprint 30 constructor already set",
    )

    task_manager_b = TaskManager(TaskQueue())
    host_b = RecordingHost()
    executor_b = Executor(task_manager_b, host_b)
    check(
        set(vars(executor_b).keys()) == attrs_before,
        "W22: two independently constructed Executors expose the same "
        "attribute shape",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_validation_unchanged,
        scenario_execute_workflow_rejects_invalid_workflow_engine,
        scenario_execute_workflow_rejects_invalid_context,
        scenario_execute_workflow_rejects_invalid_iterations,
        scenario_execute_workflow_requires_loaded_workflow,
        scenario_prepare_called_exactly_once,
        scenario_execute_runs_exactly_once,
        scenario_returned_count_forwarded,
        scenario_empty_workflow,
        scenario_workflow_with_many_tasks,
        scenario_iteration_limit_respected,
        scenario_task_order_preserved,
        scenario_workflow_engine_owns_preparation,
        scenario_executor_owns_execution_same_call_shape,
        scenario_task_queue_never_accessed_directly,
        scenario_task_manager_delegation_unchanged,
        scenario_workflow_status_unchanged,
        scenario_task_status_unchanged,
        scenario_execution_context_unchanged,
        scenario_exception_propagation,
        scenario_multiple_execute_workflow_calls,
        scenario_no_hidden_state,
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
    print(f"PHASE 3 SPRINT 32 EXECUTOR-WORKFLOW RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())