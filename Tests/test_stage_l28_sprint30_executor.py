"""
Phase 3 Sprint 30 proof suite -- the ``Executor`` foundation.

Scope: dedicated regression suite for ``Orchestration.executor.
Executor``/``ExecutorError`` only. ``Orchestration.task_manager.
TaskManager`` (covered by ``Tests/test_stage_l28_sprint26_task_manager.
py``), ``Orchestration.task_queue.TaskQueue``, ``Orchestration.task.
Task``, and ``Orchestration.autonomous_host.AutonomousHost`` (covered
by ``Tests/test_stage_l28_sprint12_host.py`` and
``Tests/test_stage_l28_sprint15_multi_host.py``) are all unmodified
and are not re-verified beyond what ``Executor`` itself needs -- real
``TaskManager``/``TaskQueue`` instances are used throughout, and
``AutonomousHost`` is exercised through a thin recording subclass that
overrides only ``start()`` so delegation can be observed without
constructing a real ``AutonomousAgent``/``RuntimeAnalysisPipeline``
graph (out of scope for this sprint). ``WorkflowEngine``,
``WorkflowManager``, ``Workflow``, ``AutonomousScheduler``,
``AutonomousAgent``, ``RuntimeAnalysisPipeline``, ``EventBus``, and
the Composition Root are all untouched by this Sprint and are not
exercised by this suite.

``Executor`` is a pure, synchronous consume-and-delegate layer: no
``Task``/``Workflow`` status is ever mutated, no retry, no dependency
graph, no branching, no persistence, no threading, and no asyncio
exist anywhere in ``Orchestration/executor.py`` -- this suite proves
the *absence* of that surface area as much as it proves the presence
of the execute()/has_pending_tasks() behavior itself.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x / Sprint 1x-30 proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    E1  -- the constructor rejects a None task_manager, and rejects a
           non-TaskManager object (while a valid host is given).
    E2  -- the constructor rejects a None host, and rejects a
           non-AutonomousHost object (while a valid task_manager is
           given).
    E3  -- constructing an Executor with a valid TaskManager and a
           valid AutonomousHost succeeds, and has_pending_tasks() is
           False for an empty TaskManager.
    E4  -- execute() rejects a None context, without dequeuing any
           Task or calling host.start().
    E5  -- execute() rejects an invalid 'iterations' (zero, negative,
           non-int, and bool -- including True/False even though bool
           is technically an int subclass), without dequeuing any
           Task or calling host.start().
    E6  -- execute() with a single pending Task and the default
           iterations=1 executes exactly that Task, returns 1, and
           leaves the TaskManager empty afterward.
    E7  -- FIFO order: with several Tasks submitted in order, execute()
           with iterations equal to the task count delegates them to
           the host in exactly the order they were submitted.
    E8  -- iteration limit: with more pending Tasks than the requested
           iterations, execute() stops after exactly 'iterations'
           Tasks, returns that count, and leaves the remaining Tasks
           (in their original order) still pending in the TaskManager.
    E9  -- empty queue: execute() on an Executor with no pending Tasks
           makes no host.start() calls, returns 0, and does not raise.
    E10 -- empty queue mid-run: execute() with iterations greater than
           the number of pending Tasks stops early once the queue is
           exhausted, returning the number actually executed (fewer
           than iterations requested), rather than raising.
    E11 -- host delegation: execute() calls host.start() with the
           dequeued Task and the exact context object passed to
           execute(), by identity.
    E12 -- exactly one host.start() call per Task -- verified by an
           explicit call count assertion across several Tasks in one
           execute() call.
    E13 -- has_pending_tasks() delegates to (and matches)
           TaskManager.has_tasks() at every point: before any tasks
           are submitted, after tasks are submitted, and after they
           are fully drained via execute().
    E14 -- repeated execute() calls: calling execute() again after a
           previous call (queue not yet drained) continues consuming
           Tasks from where the previous call left off, still in FIFO
           order, and the sum of the two calls' return values equals
           the total number of Tasks originally submitted.
    E15 -- duplicate Tasks: submitting the exact same Task instance
           more than once is handled like any other Task -- both
           copies are dequeued and delegated to the host in order,
           with a separate host.start() call for each occurrence.
    E16 -- Executor never mutates Task.status or Workflow.status --
           every Task's status is exactly as constructed both before
           and after execute() runs it (Workflow.status is not
           applicable here since Executor never references Workflow
           at all -- see E17).
    E17 -- Executor exposes no forbidden execution/knowledge surface:
           no TaskQueue/WorkflowEngine/WorkflowManager/Workflow/
           AutonomousScheduler/AutonomousAgent/
           RuntimeAnalysisPipeline/EventBus/Composition-Root
           attributes or imports, and no run/tick/schedule/retry
           members beyond the documented execute()/has_pending_tasks().
    E18 -- ExecutorError is a subclass of Core.exceptions.AgentError,
           and can be caught as such from both constructor and
           execute() validation failures.
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
from Orchestration.executor import Executor, ExecutorError
from Orchestration.task import Task, TaskStatus
from Orchestration.task_manager import TaskManager
from Orchestration.task_queue import TaskQueue

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


class RecordingHost(AutonomousHost):
    """A thin ``AutonomousHost`` subclass that overrides only
    ``start()`` to record every call it receives, instead of
    delegating to a real ``AutonomousAgent``.

    This sprint is explicitly scoped to *not* touch
    ``AutonomousHost``/``AutonomousAgent`` internals, and constructing
    a real ``AutonomousAgent`` requires a full
    ``RuntimeAnalysisPipeline`` collaborator graph that is out of
    scope here. Subclassing (rather than a bare stand-in object) keeps
    ``isinstance(host, AutonomousHost)`` true, exactly matching what a
    real ``AutonomousHost`` passed to ``Executor`` would satisfy.
    """

    def __init__(self) -> None:
        self.calls: List[Tuple[object, object, object]] = []

    def start(self, agent, context, iterations):  # type: ignore[override]
        self.calls.append((agent, context, iterations))
        return ()


def _make_executor() -> Tuple[Executor, TaskManager, RecordingHost]:
    task_manager = TaskManager(TaskQueue())
    host = RecordingHost()
    return Executor(task_manager, host), task_manager, host


def _drain_task_manager(task_manager: TaskManager) -> List[Task]:
    drained: List[Task] = []
    while task_manager.has_tasks():
        drained.append(task_manager.next_task())
    return drained


# ---------------------------------------------------------------------------
# E1 -- constructor rejects None / non-TaskManager task_manager
# ---------------------------------------------------------------------------
def scenario_constructor_rejects_invalid_task_manager() -> None:
    host = RecordingHost()

    raised_none = False
    try:
        Executor(None, host)
    except ExecutorError:
        raised_none = True

    check(raised_none, "E1: Executor(None, host) raises ExecutorError")

    for bad_value in ("not-a-manager", 123, TaskQueue(), [], {}, object()):
        raised_bad = False
        try:
            Executor(bad_value, host)
        except ExecutorError:
            raised_bad = True

        check(
            raised_bad,
            f"E1: Executor({bad_value!r}, host) (non-TaskManager) raises "
            f"ExecutorError",
        )


# ---------------------------------------------------------------------------
# E2 -- constructor rejects None / non-AutonomousHost host
# ---------------------------------------------------------------------------
def scenario_constructor_rejects_invalid_host() -> None:
    task_manager = TaskManager(TaskQueue())

    raised_none = False
    try:
        Executor(task_manager, None)
    except ExecutorError:
        raised_none = True

    check(raised_none, "E2: Executor(task_manager, None) raises ExecutorError")

    for bad_value in ("not-a-host", 123, TaskManager(TaskQueue()), [], {}, object()):
        raised_bad = False
        try:
            Executor(task_manager, bad_value)
        except ExecutorError:
            raised_bad = True

        check(
            raised_bad,
            f"E2: Executor(task_manager, {bad_value!r}) (non-AutonomousHost) "
            f"raises ExecutorError",
        )


# ---------------------------------------------------------------------------
# E3 -- valid construction succeeds; has_pending_tasks() starts False
# ---------------------------------------------------------------------------
def scenario_construction_succeeds_and_starts_with_no_pending_tasks() -> None:
    executor, _task_manager, _host = _make_executor()

    check(
        executor.has_pending_tasks() is False,
        "E3: a freshly constructed Executor over an empty TaskManager "
        "reports has_pending_tasks() as False",
    )


# ---------------------------------------------------------------------------
# E4 -- execute() rejects a None context
# ---------------------------------------------------------------------------
def scenario_execute_rejects_none_context() -> None:
    executor, task_manager, host = _make_executor()
    task_manager.submit(_make_task(name="only"))

    raised = False
    try:
        executor.execute(None)
    except ExecutorError:
        raised = True

    check(raised, "E4: execute(None) raises ExecutorError")
    check(
        task_manager.task_count() == 1,
        "E4: a rejected execute(None) call does not dequeue any Task",
    )
    check(
        len(host.calls) == 0,
        "E4: a rejected execute(None) call never calls host.start()",
    )


# ---------------------------------------------------------------------------
# E5 -- execute() rejects invalid 'iterations'
# ---------------------------------------------------------------------------
def scenario_execute_rejects_invalid_iterations() -> None:
    for bad_iterations in (0, -1, -5, "1", 1.5, None, True, False, [], {}):
        executor, task_manager, host = _make_executor()
        task_manager.submit(_make_task(name="only"))

        raised = False
        try:
            executor.execute("ctx", iterations=bad_iterations)
        except ExecutorError:
            raised = True

        check(
            raised,
            f"E5: execute('ctx', iterations={bad_iterations!r}) raises "
            f"ExecutorError",
        )
        check(
            task_manager.task_count() == 1,
            f"E5: a rejected execute() call with iterations="
            f"{bad_iterations!r} does not dequeue any Task",
        )
        check(
            len(host.calls) == 0,
            f"E5: a rejected execute() call with iterations="
            f"{bad_iterations!r} never calls host.start()",
        )


# ---------------------------------------------------------------------------
# E6 -- single Task, default iterations=1
# ---------------------------------------------------------------------------
def scenario_execute_single_task_default_iterations() -> None:
    executor, task_manager, host = _make_executor()
    task = _make_task(name="solo")
    task_manager.submit(task)

    result = executor.execute("ctx")

    check(result == 1, "E6: execute() with one pending Task returns 1")
    check(
        len(host.calls) == 1 and host.calls[0][0] is task,
        "E6: execute() delegates the single Task to host.start()",
    )
    check(
        task_manager.has_tasks() is False,
        "E6: execute() leaves the TaskManager empty after consuming the "
        "only pending Task",
    )


# ---------------------------------------------------------------------------
# E7 -- FIFO order preserved across a full execute() call
# ---------------------------------------------------------------------------
def scenario_fifo_order_preserved() -> None:
    executor, task_manager, host = _make_executor()
    tasks = [_make_task(name=f"task-{i}") for i in range(5)]
    for task in tasks:
        task_manager.submit(task)

    result = executor.execute("ctx", iterations=5)

    check(result == 5, "E7: execute() returns the number of Tasks executed")
    delegated = [call[0] for call in host.calls]
    check(
        delegated == tasks,
        "E7: Tasks are delegated to host.start() in exactly the order "
        "they were submitted",
    )


# ---------------------------------------------------------------------------
# E8 -- iteration limit stops execute() early, remainder stays pending
# ---------------------------------------------------------------------------
def scenario_iteration_limit_stops_execution() -> None:
    executor, task_manager, host = _make_executor()
    tasks = [_make_task(name=f"task-{i}") for i in range(5)]
    for task in tasks:
        task_manager.submit(task)

    result = executor.execute("ctx", iterations=2)

    check(result == 2, "E8: execute() returns exactly the requested iterations")
    check(
        len(host.calls) == 2,
        "E8: execute() makes exactly 'iterations' host.start() calls",
    )
    delegated = [call[0] for call in host.calls]
    check(
        delegated == tasks[:2],
        "E8: execute() executes the first 'iterations' Tasks, in order",
    )

    remaining = _drain_task_manager(task_manager)
    check(
        remaining == tasks[2:],
        "E8: the remaining Tasks are left pending, in their original "
        "order, after the iteration limit is reached",
    )


# ---------------------------------------------------------------------------
# E9 -- empty queue: execute() is a safe no-op, returns 0
# ---------------------------------------------------------------------------
def scenario_execute_with_empty_queue() -> None:
    executor, _task_manager, host = _make_executor()

    result = executor.execute("ctx", iterations=3)

    check(result == 0, "E9: execute() on an empty TaskManager returns 0")
    check(
        len(host.calls) == 0,
        "E9: execute() on an empty TaskManager never calls host.start()",
    )


# ---------------------------------------------------------------------------
# E10 -- queue exhausted mid-run: execute() stops early, doesn't raise
# ---------------------------------------------------------------------------
def scenario_execute_stops_when_queue_exhausted_mid_run() -> None:
    executor, task_manager, host = _make_executor()
    tasks = [_make_task(name=f"task-{i}") for i in range(3)]
    for task in tasks:
        task_manager.submit(task)

    result = executor.execute("ctx", iterations=10)

    check(
        result == 3,
        "E10: execute() with iterations greater than the pending count "
        "returns the number actually executed",
    )
    check(
        len(host.calls) == 3,
        "E10: execute() stops making host.start() calls once the queue "
        "is exhausted, rather than raising",
    )
    check(
        task_manager.has_tasks() is False,
        "E10: the TaskManager is left empty once the queue is exhausted",
    )


# ---------------------------------------------------------------------------
# E11 -- host delegation carries the exact Task and context, by identity
# ---------------------------------------------------------------------------
def scenario_host_receives_exact_task_and_context() -> None:
    executor, task_manager, host = _make_executor()
    task = _make_task(name="carried")
    task_manager.submit(task)
    context = {"marker": object()}

    executor.execute(context)

    check(
        len(host.calls) == 1,
        "E11: exactly one host.start() call is made for the single Task",
    )
    delegated_task, delegated_context, _iterations = host.calls[0]
    check(
        delegated_task is task,
        "E11: host.start() receives the exact dequeued Task, by identity",
    )
    check(
        delegated_context is context,
        "E11: host.start() receives the exact context object passed to "
        "execute(), by identity",
    )


# ---------------------------------------------------------------------------
# E12 -- exactly one host.start() call per Task
# ---------------------------------------------------------------------------
def scenario_one_host_start_call_per_task() -> None:
    executor, task_manager, host = _make_executor()
    tasks = [_make_task(name=f"task-{i}") for i in range(4)]
    for task in tasks:
        task_manager.submit(task)

    executor.execute("ctx", iterations=4)

    check(
        len(host.calls) == 4,
        "E12: execute() makes exactly one host.start() call per Task -- "
        "four Tasks in, four calls out",
    )
    check(
        len({id(call[0]) for call in host.calls}) == 4,
        "E12: each host.start() call corresponds to a distinct Task",
    )


# ---------------------------------------------------------------------------
# E13 -- has_pending_tasks() delegates to (and matches) TaskManager.has_tasks()
# ---------------------------------------------------------------------------
def scenario_has_pending_tasks_matches_task_manager() -> None:
    executor, task_manager, _host = _make_executor()

    check(
        executor.has_pending_tasks() == task_manager.has_tasks() is False,
        "E13: has_pending_tasks() matches TaskManager.has_tasks() before "
        "any Tasks are submitted (both False)",
    )

    task_manager.submit(_make_task(name="a"))
    task_manager.submit(_make_task(name="b"))

    check(
        executor.has_pending_tasks() == task_manager.has_tasks() is True,
        "E13: has_pending_tasks() matches TaskManager.has_tasks() after "
        "Tasks are submitted (both True)",
    )

    executor.execute("ctx", iterations=2)

    check(
        executor.has_pending_tasks() == task_manager.has_tasks() is False,
        "E13: has_pending_tasks() matches TaskManager.has_tasks() after "
        "every Task has been drained via execute() (both False)",
    )


# ---------------------------------------------------------------------------
# E14 -- repeated execute() calls continue where the previous call left off
# ---------------------------------------------------------------------------
def scenario_repeated_execute_calls_continue_fifo() -> None:
    executor, task_manager, host = _make_executor()
    tasks = [_make_task(name=f"task-{i}") for i in range(5)]
    for task in tasks:
        task_manager.submit(task)

    first_result = executor.execute("ctx", iterations=2)
    second_result = executor.execute("ctx", iterations=10)

    check(
        first_result == 2,
        "E14: the first execute() call returns the number of Tasks it "
        "executed",
    )
    check(
        second_result == 3,
        "E14: a subsequent execute() call picks up exactly where the "
        "previous one left off",
    )
    check(
        first_result + second_result == len(tasks),
        "E14: the sum across repeated execute() calls equals the total "
        "number of Tasks originally submitted",
    )
    delegated = [call[0] for call in host.calls]
    check(
        delegated == tasks,
        "E14: Tasks remain delegated in strict FIFO order across "
        "repeated execute() calls",
    )


# ---------------------------------------------------------------------------
# E15 -- duplicate Tasks are each dequeued and delegated separately
# ---------------------------------------------------------------------------
def scenario_duplicate_tasks_each_delegated_separately() -> None:
    executor, task_manager, host = _make_executor()
    task = _make_task(name="dup")
    task_manager.submit(task)
    task_manager.submit(task)

    result = executor.execute("ctx", iterations=2)

    check(result == 2, "E15: execute() executes both submissions of the "
          "same Task instance")
    check(
        len(host.calls) == 2,
        "E15: a duplicate Task produces a separate host.start() call for "
        "each occurrence",
    )
    check(
        host.calls[0][0] is task and host.calls[1][0] is task,
        "E15: both host.start() calls carry the same duplicated Task, by "
        "identity",
    )


# ---------------------------------------------------------------------------
# E16 -- no Task.status mutation
# ---------------------------------------------------------------------------
def scenario_no_task_status_mutation() -> None:
    executor, task_manager, _host = _make_executor()
    tasks = [_make_task(name=f"task-{i}") for i in range(3)]
    original_statuses = [task.status for task in tasks]
    for task in tasks:
        task_manager.submit(task)

    executor.execute("ctx", iterations=3)

    check(
        all(
            task.status == original for task, original in zip(
                tasks, original_statuses
            )
        ),
        "E16: Executor never mutates Task.status -- every Task's status "
        "is exactly as constructed, both before and after execute()",
    )
    check(
        all(task.status == TaskStatus.PENDING for task in tasks),
        "E16: every Task remains in TaskStatus.PENDING (Executor performs "
        "no lifecycle transitions of its own)",
    )


# ---------------------------------------------------------------------------
# E17 -- no forbidden execution/knowledge surface
# ---------------------------------------------------------------------------
def scenario_no_forbidden_surface() -> None:
    import ast

    import Orchestration.executor as executor_module

    source = Path(executor_module.__file__).read_text()
    tree = ast.parse(source)

    imported_names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.append(node.module)
            for alias in node.names:
                imported_names.append(alias.name)

    forbidden_symbols = (
        "TaskQueue",
        "WorkflowEngine",
        "WorkflowManager",
        "Workflow",
        "AutonomousScheduler",
        "AutonomousAgent",
        "RuntimeAnalysisPipeline",
        "EventBus",
        "composition_root",
        "CompositionRoot",
    )
    for symbol in forbidden_symbols:
        check(
            not any(symbol in name for name in imported_names),
            f"E17: Orchestration/executor.py never imports anything "
            f"referencing {symbol!r}",
        )

    executor, _task_manager, _host = _make_executor()
    forbidden_members = (
        "run",
        "tick",
        "schedule",
        "retry",
        "cancel",
        "pause",
        "resume",
        "workflow",
        "task_queue",
        "event_bus",
        "scheduler",
        "runtime_analysis_pipeline",
    )
    for member in forbidden_members:
        check(
            not hasattr(executor, member),
            f"E17: Executor exposes no {member!r} member",
        )

    check(
        hasattr(executor, "execute") and callable(executor.execute),
        "E17: Executor exposes a callable execute()",
    )
    check(
        hasattr(executor, "has_pending_tasks")
        and callable(executor.has_pending_tasks),
        "E17: Executor exposes a callable has_pending_tasks()",
    )


# ---------------------------------------------------------------------------
# E18 -- ExecutorError is an AgentError subclass
# ---------------------------------------------------------------------------
def scenario_executor_error_is_agent_error_subclass() -> None:
    check(
        issubclass(ExecutorError, AgentError),
        "E18: ExecutorError is a subclass of Core.exceptions.AgentError",
    )

    raised_as_agent_error_ctor = False
    try:
        Executor(None, RecordingHost())
    except AgentError:
        raised_as_agent_error_ctor = True

    check(
        raised_as_agent_error_ctor,
        "E18: an ExecutorError from an invalid constructor call can be "
        "caught as AgentError",
    )

    executor, _task_manager, _host = _make_executor()
    raised_as_agent_error_execute = False
    try:
        executor.execute("ctx", iterations=0)
    except AgentError:
        raised_as_agent_error_execute = True

    check(
        raised_as_agent_error_execute,
        "E18: an ExecutorError from an invalid execute() call can be "
        "caught as AgentError",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_rejects_invalid_task_manager,
        scenario_constructor_rejects_invalid_host,
        scenario_construction_succeeds_and_starts_with_no_pending_tasks,
        scenario_execute_rejects_none_context,
        scenario_execute_rejects_invalid_iterations,
        scenario_execute_single_task_default_iterations,
        scenario_fifo_order_preserved,
        scenario_iteration_limit_stops_execution,
        scenario_execute_with_empty_queue,
        scenario_execute_stops_when_queue_exhausted_mid_run,
        scenario_host_receives_exact_task_and_context,
        scenario_one_host_start_call_per_task,
        scenario_has_pending_tasks_matches_task_manager,
        scenario_repeated_execute_calls_continue_fifo,
        scenario_duplicate_tasks_each_delegated_separately,
        scenario_no_task_status_mutation,
        scenario_no_forbidden_surface,
        scenario_executor_error_is_agent_error_subclass,
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
    print(f"PHASE 3 SPRINT 30 EXECUTOR RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())