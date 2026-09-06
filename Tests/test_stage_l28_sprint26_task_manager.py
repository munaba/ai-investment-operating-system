"""
Phase 3 Sprint 26 proof suite -- the ``TaskManager`` orchestration
layer.

Scope: dedicated regression suite for
``Orchestration.task_manager.TaskManager``/``TaskManagerError`` only.
``Orchestration.task.Task`` (covered by
``Tests/test_stage_l28_sprint24_task.py``) and
``Orchestration.task_queue.TaskQueue`` (covered by
``Tests/test_stage_l28_sprint25_task_queue.py``) are unmodified and
are not re-verified beyond what ``TaskManager`` itself needs -- real
``Task``/``TaskQueue`` instances are used throughout here.
``AutonomousScheduler``, ``AutonomousHost``, ``AutonomousAgent``,
``RuntimeAnalysisPipeline``, ``EventBus``, and the Composition Root
are all untouched by this Sprint and are not exercised by this suite.

``TaskManager`` is a pure delegation layer: every public method does
nothing but forward, unmodified, to the single ``TaskQueue`` method it
wraps. No method reimplements or shortcuts any storage logic, no
``Task.status`` is ever mutated, and no execution/scheduling/workflow/
eventing surface exists anywhere in ``Orchestration/task_manager.py``
-- this suite proves the *absence* of that surface area as much as it
proves the presence of the delegation behavior itself.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x / Sprint 1x-2x proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    M1  -- constructing a TaskManager with a valid TaskQueue succeeds
           and starts with an empty, independent queue.
    M2  -- the constructor rejects a None task_queue, and rejects a
           non-TaskQueue object.
    M3  -- submit() delegates to TaskQueue.enqueue(): it adds exactly
           one task, is reflected via the queue's own size()/tasks(),
           and returns None.
    M4  -- submit() propagates TaskQueueError, unchanged, for invalid
           input (None / non-Task), and adds nothing on rejection.
    M5  -- next_task() delegates to TaskQueue.dequeue(): FIFO order is
           preserved across many submit()/next_task() calls, the
           returned task is removed from the queue, and the same task
           is never returned twice.
    M6  -- next_task() on an empty manager propagates TaskQueueError
           and leaves state unchanged.
    M7  -- peek_task() delegates to TaskQueue.peek(): returns the
           front task without removing it, is idempotent across
           repeated calls, and a following next_task() returns
           exactly what peek_task() reported.
    M8  -- peek_task() on an empty manager propagates TaskQueueError.
    M9  -- task_count() delegates to TaskQueue.size(), tracking
           accurately across submit()/next_task()/clear() calls.
    M10 -- has_tasks() delegates to (the inverse of)
           TaskQueue.is_empty(), staying correct across the same
           sequence of operations.
    M11 -- clear() delegates to TaskQueue.clear(): empties a
           non-empty manager, is idempotent on an already-empty one,
           and only affects the TaskQueue instance it was constructed
           with.
    M12 -- duplicate tasks (the exact same Task object submitted
           twice, and two distinct Task instances with identical
           field values) are both accepted without error and both
           counted separately.
    M13 -- empty-manager behavior is consistent across every read
           method (task_count() == 0, has_tasks() is False) both for
           a freshly constructed manager and after clear().
    M14 -- queue independence: two TaskManager instances wrapping two
           different TaskQueue instances never share state, and a
           TaskManager never bypasses the specific TaskQueue instance
           it was constructed with.
    M15 -- delegation is exact and non-duplicated: driving state
           through the TaskManager and driving the same operations
           directly on its underlying TaskQueue leave both queues in
           an identical, verifiably-equal final state.
    M16 -- TaskManager never mutates Task.status -- submitting and
           then retrieving a task leaves its status (and every other
           field) exactly as constructed.
    M17 -- TaskManager exposes no execution surface (no run/start/
           stop/cancel/tick/schedule/pause/resume/retry/timeout
           members) and no forbidden knowledge of Scheduler/Host/
           Agent/Workflow/EventBus/RuntimePipeline (no scheduler/host/
           agent/workflow/event_bus/pipeline/runtime_analysis_pipeline
           attributes).
    M18 -- TaskManagerError is a subclass of Core.exceptions.
           AgentError, and is distinct from TaskQueueError even
           though a TaskQueueError raised deep inside a delegated
           call still propagates (uncaught, unwrapped) through
           TaskManager.
    M19 -- repr() is a stable, informative string reflecting the
           current task count.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.task import Task
from Orchestration.task_queue import TaskQueue, TaskQueueError
from Orchestration.task_manager import TaskManager, TaskManagerError

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


# ---------------------------------------------------------------------------
# M1 -- constructing a TaskManager with a valid TaskQueue succeeds
# ---------------------------------------------------------------------------
def scenario_construction_succeeds_with_valid_queue() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)

    check(
        manager.task_count() == 0,
        "M1: a freshly constructed TaskManager reports task_count() == 0",
    )
    check(
        manager.has_tasks() is False,
        "M1: a freshly constructed TaskManager reports has_tasks() False",
    )


# ---------------------------------------------------------------------------
# M2 -- constructor rejects None and non-TaskQueue objects
# ---------------------------------------------------------------------------
def scenario_constructor_rejects_invalid_queue() -> None:
    raised_none = False
    try:
        TaskManager(None)
    except TaskManagerError:
        raised_none = True

    check(raised_none, "M2: TaskManager(None) raises TaskManagerError")

    for bad_value in ("not-a-queue", 123, [], {}, object(), Task(name="n", description="d")):
        raised_bad = False
        try:
            TaskManager(bad_value)
        except TaskManagerError:
            raised_bad = True

        check(
            raised_bad,
            f"M2: TaskManager({bad_value!r}) (non-TaskQueue) raises "
            f"TaskManagerError",
        )


# ---------------------------------------------------------------------------
# M3 -- submit() delegates to TaskQueue.enqueue()
# ---------------------------------------------------------------------------
def scenario_submit_delegates_to_enqueue() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)
    task = _make_task()

    result = manager.submit(task)

    check(result is None, "M3: submit() returns None")
    check(queue.size() == 1, "M3: submit() is reflected in the queue's size()")
    check(
        queue.tasks() == (task,),
        "M3: submit() is reflected in the queue's tasks()",
    )
    check(
        manager.task_count() == 1,
        "M3: submit() is reflected via the manager's own task_count()",
    )


# ---------------------------------------------------------------------------
# M4 -- submit() propagates TaskQueueError for invalid input
# ---------------------------------------------------------------------------
def scenario_submit_propagates_queue_error_for_invalid_input() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)

    raised_none = False
    try:
        manager.submit(None)
    except TaskQueueError:
        raised_none = True

    check(raised_none, "M4: submit(None) propagates TaskQueueError")

    for bad_value in ("not-a-task", 123, {"name": "n"}, ["n", "d"], object()):
        raised_bad = False
        try:
            manager.submit(bad_value)
        except TaskQueueError:
            raised_bad = True

        check(
            raised_bad,
            f"M4: submit({bad_value!r}) (non-Task) propagates TaskQueueError",
        )

    check(
        manager.task_count() == 0 and manager.has_tasks() is False,
        "M4: none of the rejected submit() calls added anything",
    )


# ---------------------------------------------------------------------------
# M5 -- next_task() delegates to TaskQueue.dequeue(); FIFO preserved
# ---------------------------------------------------------------------------
def scenario_next_task_fifo_and_removes() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)
    tasks = [_make_task(name=f"task-{i}") for i in range(5)]

    for task in tasks:
        manager.submit(task)

    retrieved_order = [manager.next_task() for _ in range(5)]

    check(
        retrieved_order == tasks,
        "M5: next_task() returns tasks in strict FIFO (submit) order",
    )
    check(
        manager.task_count() == 0,
        "M5: next_task() removes each task from the manager's queue",
    )
    check(
        len(set(id(t) for t in retrieved_order)) == 5,
        "M5: the same task is never returned twice",
    )


# ---------------------------------------------------------------------------
# M6 -- next_task() on an empty manager propagates TaskQueueError
# ---------------------------------------------------------------------------
def scenario_next_task_on_empty_manager_raises() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)

    raised = False
    try:
        manager.next_task()
    except TaskQueueError:
        raised = True

    check(raised, "M6: next_task() on an empty manager propagates TaskQueueError")
    check(
        manager.task_count() == 0 and manager.has_tasks() is False,
        "M6: a rejected next_task() call leaves the empty manager unchanged",
    )


# ---------------------------------------------------------------------------
# M7 -- peek_task() delegates to TaskQueue.peek()
# ---------------------------------------------------------------------------
def scenario_peek_task_does_not_remove() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)
    task_a = _make_task(name="a")
    task_b = _make_task(name="b")
    manager.submit(task_a)
    manager.submit(task_b)

    peeked_once = manager.peek_task()
    peeked_twice = manager.peek_task()

    check(peeked_once is task_a, "M7: peek_task() returns the front task")
    check(
        peeked_once is peeked_twice,
        "M7: calling peek_task() repeatedly returns the same task each time",
    )
    check(manager.task_count() == 2, "M7: peek_task() never changes task_count()")

    retrieved = manager.next_task()
    check(
        retrieved is peeked_once,
        "M7: the following next_task() returns exactly what peek_task() reported",
    )


# ---------------------------------------------------------------------------
# M8 -- peek_task() on an empty manager propagates TaskQueueError
# ---------------------------------------------------------------------------
def scenario_peek_task_on_empty_manager_raises() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)

    raised = False
    try:
        manager.peek_task()
    except TaskQueueError:
        raised = True

    check(raised, "M8: peek_task() on an empty manager propagates TaskQueueError")


# ---------------------------------------------------------------------------
# M9 -- task_count() delegates to TaskQueue.size()
# ---------------------------------------------------------------------------
def scenario_task_count_tracks_operations() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)

    check(manager.task_count() == 0, "M9: task_count() starts at 0")

    manager.submit(_make_task(name="a"))
    manager.submit(_make_task(name="b"))
    check(manager.task_count() == 2, "M9: task_count() reflects two submits")

    manager.next_task()
    check(manager.task_count() == 1, "M9: task_count() reflects one next_task()")

    manager.clear()
    check(manager.task_count() == 0, "M9: task_count() reflects clear()")


# ---------------------------------------------------------------------------
# M10 -- has_tasks() delegates to the inverse of TaskQueue.is_empty()
# ---------------------------------------------------------------------------
def scenario_has_tasks_tracks_operations() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)

    check(manager.has_tasks() is False, "M10: has_tasks() starts False")

    manager.submit(_make_task())
    check(manager.has_tasks() is True, "M10: has_tasks() is True after submit()")

    manager.next_task()
    check(
        manager.has_tasks() is False,
        "M10: has_tasks() is False again after draining the only task",
    )

    manager.submit(_make_task())
    manager.clear()
    check(manager.has_tasks() is False, "M10: has_tasks() is False after clear()")


# ---------------------------------------------------------------------------
# M11 -- clear() delegates to TaskQueue.clear()
# ---------------------------------------------------------------------------
def scenario_clear_behavior() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)
    manager.submit(_make_task(name="a"))
    manager.submit(_make_task(name="b"))

    result = manager.clear()

    check(result is None, "M11: clear() returns None")
    check(
        manager.task_count() == 0 and manager.has_tasks() is False,
        "M11: clear() empties a non-empty manager",
    )
    check(queue.size() == 0, "M11: clear() empties the underlying TaskQueue")

    # idempotent on an already-empty manager
    manager.clear()
    check(
        manager.task_count() == 0,
        "M11: clear() is idempotent on an already-empty manager",
    )

    # only affects the TaskQueue instance this manager was constructed with
    other_queue = TaskQueue()
    other_queue.enqueue(_make_task(name="untouched"))
    other_manager = TaskManager(other_queue)
    manager.clear()
    check(
        other_queue.size() == 1,
        "M11: clear() only affects this manager's own TaskQueue instance",
    )


# ---------------------------------------------------------------------------
# M12 -- duplicate tasks are accepted and counted separately
# ---------------------------------------------------------------------------
def scenario_duplicate_tasks_allowed() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)
    task = _make_task(name="dup")

    manager.submit(task)
    manager.submit(task)

    check(
        manager.task_count() == 2,
        "M12: submitting the exact same Task object twice is accepted and "
        "counted twice",
    )

    twin_a = _make_task(name="twin")
    twin_b = _make_task(name="twin")
    manager.clear()
    manager.submit(twin_a)
    manager.submit(twin_b)

    check(
        manager.task_count() == 2,
        "M12: two distinct Task instances with identical field values are "
        "both accepted and counted separately",
    )


# ---------------------------------------------------------------------------
# M13 -- empty-manager behavior is consistent across read methods
# ---------------------------------------------------------------------------
def scenario_empty_manager_consistency() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)

    check(
        manager.task_count() == 0 and manager.has_tasks() is False,
        "M13: a freshly constructed manager is consistently empty across "
        "task_count()/has_tasks()",
    )

    manager.submit(_make_task())
    manager.clear()

    check(
        manager.task_count() == 0 and manager.has_tasks() is False,
        "M13: a manager drained via clear() is consistently empty across "
        "task_count()/has_tasks()",
    )


# ---------------------------------------------------------------------------
# M14 -- queue independence across TaskManager instances
# ---------------------------------------------------------------------------
def scenario_independent_manager_instances() -> None:
    queue_a = TaskQueue()
    queue_b = TaskQueue()
    manager_a = TaskManager(queue_a)
    manager_b = TaskManager(queue_b)

    manager_a.submit(_make_task(name="a"))
    manager_a.submit(_make_task(name="a2"))

    check(
        manager_b.task_count() == 0,
        "M14: submitting on one TaskManager never affects a different "
        "TaskManager's own queue",
    )
    check(
        queue_b.size() == 0,
        "M14: submitting on one TaskManager never affects a different "
        "underlying TaskQueue instance",
    )

    manager_b.submit(_make_task(name="b"))
    check(
        manager_a.task_count() == 2,
        "M14: submitting on the second TaskManager never affects the "
        "first",
    )

    # two managers sharing the SAME underlying queue do observe each
    # other's changes, via that shared TaskQueue instance
    shared_queue = TaskQueue()
    shared_manager_1 = TaskManager(shared_queue)
    shared_manager_2 = TaskManager(shared_queue)
    shared_manager_1.submit(_make_task(name="shared"))
    check(
        shared_manager_2.task_count() == 1,
        "M14: two TaskManagers constructed around the SAME TaskQueue "
        "instance correctly observe each other's changes through it",
    )


# ---------------------------------------------------------------------------
# M15 -- delegation is exact: TaskManager vs. driving TaskQueue directly
# ---------------------------------------------------------------------------
def scenario_delegation_matches_direct_queue_use() -> None:
    via_manager_queue = TaskQueue()
    manager = TaskManager(via_manager_queue)

    direct_queue = TaskQueue()

    tasks = [_make_task(name=f"t-{i}") for i in range(4)]

    for task in tasks:
        manager.submit(task)
        direct_queue.enqueue(task)

    manager.next_task()
    direct_queue.dequeue()

    check(
        via_manager_queue.tasks() == direct_queue.tasks(),
        "M15: driving state through TaskManager leaves its TaskQueue in "
        "an identical state to driving the same operations directly on "
        "an equivalent TaskQueue",
    )
    check(
        manager.task_count() == direct_queue.size(),
        "M15: TaskManager.task_count() exactly matches TaskQueue.size() "
        "after the same operations",
    )
    check(
        manager.has_tasks() == (not direct_queue.is_empty()),
        "M15: TaskManager.has_tasks() exactly matches the inverse of "
        "TaskQueue.is_empty() after the same operations",
    )


# ---------------------------------------------------------------------------
# M16 -- TaskManager never mutates Task.status or any other field
# ---------------------------------------------------------------------------
def scenario_task_status_never_mutated() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)
    task = _make_task(name="status-check")
    original_status = task.status

    manager.submit(task)
    peeked = manager.peek_task()
    retrieved = manager.next_task()

    check(
        peeked.status == original_status and retrieved.status == original_status,
        "M16: submitting/peeking/retrieving a Task never changes its status",
    )
    check(
        retrieved == task,
        "M16: the retrieved Task is field-for-field identical to what was "
        "submitted",
    )


# ---------------------------------------------------------------------------
# M17 -- no execution surface, no forbidden component knowledge
# ---------------------------------------------------------------------------
def scenario_no_execution_or_forbidden_knowledge_surface() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)

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
        "scheduler",
        "host",
        "agent",
        "workflow",
        "event_bus",
        "pipeline",
        "runtime_analysis_pipeline",
    )

    none_present = all(
        not hasattr(manager, member) for member in forbidden_members
    )
    check(
        none_present,
        "M17: TaskManager exposes none of the forbidden execution/"
        "scheduling/persistence/eventing/component-knowledge members",
    )


# ---------------------------------------------------------------------------
# M18 -- TaskManagerError vs. propagated TaskQueueError
# ---------------------------------------------------------------------------
def scenario_error_hierarchy() -> None:
    check(
        issubclass(TaskManagerError, AgentError),
        "M18: TaskManagerError is a subclass of Core.exceptions.AgentError",
    )
    check(
        not issubclass(TaskManagerError, TaskQueueError)
        and not issubclass(TaskQueueError, TaskManagerError),
        "M18: TaskManagerError and TaskQueueError are distinct, neither "
        "a subclass of the other",
    )

    raised_manager_error_as_agent_error = False
    try:
        TaskManager(None)
    except AgentError:
        raised_manager_error_as_agent_error = True

    check(
        raised_manager_error_as_agent_error,
        "M18: a TaskManagerError from an invalid constructor call can be "
        "caught as AgentError",
    )

    manager = TaskManager(TaskQueue())
    raised_queue_error_unwrapped = False
    try:
        manager.next_task()
    except TaskQueueError:
        raised_queue_error_unwrapped = True
    except TaskManagerError:
        raised_queue_error_unwrapped = False

    check(
        raised_queue_error_unwrapped,
        "M18: a TaskQueueError raised inside a delegated call propagates "
        "through TaskManager unchanged, not wrapped as TaskManagerError",
    )


# ---------------------------------------------------------------------------
# M19 -- repr() is stable and informative
# ---------------------------------------------------------------------------
def scenario_repr_is_stable_and_informative() -> None:
    queue = TaskQueue()
    manager = TaskManager(queue)

    check(
        repr(manager) == "TaskManager(task_count=0)",
        "M19: repr() reflects an empty manager's task count",
    )

    manager.submit(_make_task())
    check(
        repr(manager) == "TaskManager(task_count=1)",
        "M19: repr() updates after submit()",
    )

    manager.next_task()
    check(
        repr(manager) == "TaskManager(task_count=0)",
        "M19: repr() updates after next_task()",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_construction_succeeds_with_valid_queue,
        scenario_constructor_rejects_invalid_queue,
        scenario_submit_delegates_to_enqueue,
        scenario_submit_propagates_queue_error_for_invalid_input,
        scenario_next_task_fifo_and_removes,
        scenario_next_task_on_empty_manager_raises,
        scenario_peek_task_does_not_remove,
        scenario_peek_task_on_empty_manager_raises,
        scenario_task_count_tracks_operations,
        scenario_has_tasks_tracks_operations,
        scenario_clear_behavior,
        scenario_duplicate_tasks_allowed,
        scenario_empty_manager_consistency,
        scenario_independent_manager_instances,
        scenario_delegation_matches_direct_queue_use,
        scenario_task_status_never_mutated,
        scenario_no_execution_or_forbidden_knowledge_surface,
        scenario_error_hierarchy,
        scenario_repr_is_stable_and_informative,
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
    print(f"PHASE 3 SPRINT 26 TASK MANAGER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())