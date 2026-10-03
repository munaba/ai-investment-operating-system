"""
Phase 3 Sprint 25 proof suite -- the ``TaskQueue`` storage layer.

Scope: dedicated regression suite for
``Orchestration.task_queue.TaskQueue``/``TaskQueueError`` only.
``Orchestration.task.Task`` is unmodified and already covered by its
own dedicated suite (``Tests/test_stage_l28_sprint24_task.py``) --
real ``Task`` instances are used throughout here, but ``Task``'s own
value-object behavior is not re-verified beyond what ``TaskQueue``
itself needs. ``AutonomousScheduler``, ``AutonomousHost``,
``AutonomousAgent``, ``RuntimeAnalysisPipeline``, ``EventBus``, and
the Composition Root are all untouched by this Sprint and are not
exercised by this suite.

``TaskQueue`` is a pure in-memory FIFO: no threading, no asyncio, no
timers, no background execution, no priority ordering, no scheduler/
manager/workflow integration, no execution, no persistence, and no
eventing exist anywhere in ``Orchestration/task_queue.py`` -- this
suite proves the *absence* of that surface area as much as it proves
the presence of the queue behavior itself.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x / Sprint 1x-2x proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    Q1  -- a new TaskQueue starts empty (size 0, is_empty() True,
           tasks() == ()).
    Q2  -- enqueue() adds exactly one task, reflected in size()/
           is_empty()/tasks().
    Q3  -- enqueue() rejects a None task, and rejects a non-Task
           object -- neither is added to the queue.
    Q4  -- FIFO ordering: dequeue() always returns the
           least-recently-enqueued remaining task, across many
           enqueue()/dequeue() calls in sequence.
    Q5  -- dequeue() removes the returned task from the queue (size
           drops by exactly one; the same task is not returned twice).
    Q6  -- dequeue() on an empty queue raises TaskQueueError, and
           does not change queue state.
    Q7  -- peek() returns the front task without removing it -- size
           is unchanged, and a following dequeue() returns the exact
           same task peek() reported.
    Q8  -- peek() on an empty queue raises TaskQueueError.
    Q9  -- size() accurately tracks the queue's contents across
           enqueue()/dequeue()/clear() calls.
    Q10 -- clear() empties a non-empty queue; is idempotent on an
           already-empty queue; and only affects the instance it was
           called on.
    Q11 -- duplicate tasks (the exact same Task object enqueued
           twice, and two distinct Task instances with identical
           field values) are both accepted without error and both
           counted separately.
    Q12 -- tasks() returns an immutable snapshot: mutating the
           returned tuple is impossible (tuples are already
           immutable), and mutating a list passed earlier or calling
           tasks() repeatedly never changes what a later dequeue()
           returns; the internal list is never the same object
           returned.
    Q13 -- multiple sequential dequeue() calls drain the queue in
           order down to empty, and a dequeue() after the last item
           raises TaskQueueError.
    Q14 -- two independent TaskQueue instances never share state --
           enqueuing on one never affects the other's size/contents.
    Q15 -- repr() is a stable, informative string reflecting the
           current size.
    Q16 -- TaskQueue exposes no execution/scheduling/persistence/
           eventing surface (no run/start/schedule/tick/save/load/
           to_dict/publish/subscribe members).
    Q17 -- TaskQueueError is a subclass of Core.exceptions.AgentError.
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
# Q1 -- a new TaskQueue starts empty
# ---------------------------------------------------------------------------
def scenario_new_queue_starts_empty() -> None:
    queue = TaskQueue()

    check(queue.size() == 0, "Q1: a new TaskQueue reports size() == 0")
    check(queue.is_empty() is True, "Q1: a new TaskQueue reports is_empty() True")
    check(queue.tasks() == (), "Q1: a new TaskQueue's tasks() is an empty tuple")


# ---------------------------------------------------------------------------
# Q2 -- enqueue() adds exactly one task
# ---------------------------------------------------------------------------
def scenario_enqueue_adds_one_task() -> None:
    queue = TaskQueue()
    task = _make_task()

    result = queue.enqueue(task)

    check(result is None, "Q2: enqueue() returns None")
    check(queue.size() == 1, "Q2: size() is 1 after enqueuing one task")
    check(queue.is_empty() is False, "Q2: is_empty() is False after enqueuing")
    check(queue.tasks() == (task,), "Q2: tasks() reflects the enqueued task")


# ---------------------------------------------------------------------------
# Q3 -- enqueue() rejects None and non-Task objects
# ---------------------------------------------------------------------------
def scenario_enqueue_rejects_invalid_input() -> None:
    queue = TaskQueue()

    raised_none = False
    try:
        queue.enqueue(None)
    except TaskQueueError:
        raised_none = True

    check(raised_none, "Q3: enqueue(None) raises TaskQueueError")

    for bad_value in ("not-a-task", 123, {"name": "n"}, ["n", "d"], object()):
        raised_bad = False
        try:
            queue.enqueue(bad_value)
        except TaskQueueError:
            raised_bad = True

        check(
            raised_bad,
            f"Q3: enqueue({bad_value!r}) (non-Task) raises TaskQueueError",
        )

    check(
        queue.is_empty(),
        "Q3: none of the rejected enqueue() calls added anything to the queue",
    )


# ---------------------------------------------------------------------------
# Q4 -- FIFO ordering across many enqueue()/dequeue() calls
# ---------------------------------------------------------------------------
def scenario_fifo_ordering_preserved() -> None:
    queue = TaskQueue()
    tasks = [_make_task(name=f"task-{i}") for i in range(5)]

    for task in tasks:
        queue.enqueue(task)

    dequeued_order = [queue.dequeue() for _ in range(5)]

    check(
        dequeued_order == tasks,
        "Q4: dequeue() returns tasks in strict FIFO (enqueue) order",
    )


# ---------------------------------------------------------------------------
# Q5 -- dequeue() removes the returned task from the queue
# ---------------------------------------------------------------------------
def scenario_dequeue_removes_task() -> None:
    queue = TaskQueue()
    task_a = _make_task(name="a")
    task_b = _make_task(name="b")
    queue.enqueue(task_a)
    queue.enqueue(task_b)

    first = queue.dequeue()

    check(first is task_a, "Q5: dequeue() returns the front task by identity")
    check(queue.size() == 1, "Q5: size() drops by exactly one after dequeue()")
    check(
        first not in queue.tasks(),
        "Q5: a dequeued task is no longer present in the queue",
    )

    second = queue.dequeue()
    check(
        second is task_b and second is not first,
        "Q5: the same task is never returned twice",
    )


# ---------------------------------------------------------------------------
# Q6 -- dequeue() on an empty queue raises and leaves state unchanged
# ---------------------------------------------------------------------------
def scenario_dequeue_on_empty_queue_raises() -> None:
    queue = TaskQueue()

    raised = False
    try:
        queue.dequeue()
    except TaskQueueError:
        raised = True

    check(raised, "Q6: dequeue() on an empty queue raises TaskQueueError")
    check(
        queue.size() == 0 and queue.is_empty(),
        "Q6: a rejected dequeue() call leaves the empty queue unchanged",
    )


# ---------------------------------------------------------------------------
# Q7 -- peek() returns the front task without removing it
# ---------------------------------------------------------------------------
def scenario_peek_does_not_remove() -> None:
    queue = TaskQueue()
    task_a = _make_task(name="a")
    task_b = _make_task(name="b")
    queue.enqueue(task_a)
    queue.enqueue(task_b)

    peeked_once = queue.peek()
    peeked_twice = queue.peek()

    check(peeked_once is task_a, "Q7: peek() returns the front task")
    check(
        peeked_once is peeked_twice,
        "Q7: calling peek() repeatedly returns the same task each time",
    )
    check(queue.size() == 2, "Q7: peek() never changes the queue's size")

    dequeued = queue.dequeue()
    check(
        dequeued is peeked_once,
        "Q7: the following dequeue() returns exactly what peek() reported",
    )


# ---------------------------------------------------------------------------
# Q8 -- peek() on an empty queue raises
# ---------------------------------------------------------------------------
def scenario_peek_on_empty_queue_raises() -> None:
    queue = TaskQueue()

    raised = False
    try:
        queue.peek()
    except TaskQueueError:
        raised = True

    check(raised, "Q8: peek() on an empty queue raises TaskQueueError")


# ---------------------------------------------------------------------------
# Q9 -- size() accurately tracks the queue across operations
# ---------------------------------------------------------------------------
def scenario_size_tracks_operations() -> None:
    queue = TaskQueue()
    check(queue.size() == 0, "Q9: size() starts at 0")

    queue.enqueue(_make_task(name="a"))
    check(queue.size() == 1, "Q9: size() is 1 after one enqueue()")

    queue.enqueue(_make_task(name="b"))
    queue.enqueue(_make_task(name="c"))
    check(queue.size() == 3, "Q9: size() is 3 after three enqueue() calls")

    queue.dequeue()
    check(queue.size() == 2, "Q9: size() drops by one after dequeue()")

    queue.clear()
    check(queue.size() == 0, "Q9: size() is 0 after clear()")


# ---------------------------------------------------------------------------
# Q10 -- clear() behavior
# ---------------------------------------------------------------------------
def scenario_clear_behavior() -> None:
    queue = TaskQueue()
    queue.enqueue(_make_task(name="a"))
    queue.enqueue(_make_task(name="b"))

    result = queue.clear()

    check(result is None, "Q10: clear() returns None")
    check(
        queue.size() == 0 and queue.is_empty() and queue.tasks() == (),
        "Q10: clear() empties a non-empty queue",
    )

    # idempotent on an already-empty queue
    queue.clear()
    check(queue.is_empty(), "Q10: clear() on an already-empty queue is a no-op")

    other_queue = TaskQueue()
    other_queue.enqueue(_make_task(name="untouched"))
    queue.clear()
    check(
        other_queue.size() == 1,
        "Q10: clear() on one queue never affects a different instance",
    )


# ---------------------------------------------------------------------------
# Q11 -- duplicate tasks are allowed
# ---------------------------------------------------------------------------
def scenario_duplicate_tasks_allowed() -> None:
    queue = TaskQueue()
    same_task = _make_task(name="dup")

    queue.enqueue(same_task)
    queue.enqueue(same_task)  # the exact same object, twice

    check(
        queue.size() == 2,
        "Q11: enqueuing the exact same Task object twice is accepted and "
        "counted separately",
    )

    twin_a = _make_task(name="twin", description="d", task_id="shared-id")
    twin_b = _make_task(name="twin", description="d", task_id="shared-id")
    check(twin_a == twin_b, "Q11: sanity -- the two twin Tasks are equal by value")

    queue2 = TaskQueue()
    queue2.enqueue(twin_a)
    queue2.enqueue(twin_b)
    check(
        queue2.size() == 2,
        "Q11: two distinct Task instances with identical field values are "
        "both accepted and both counted separately",
    )


# ---------------------------------------------------------------------------
# Q12 -- tasks() returns an immutable, independent snapshot
# ---------------------------------------------------------------------------
def scenario_tasks_snapshot_is_immutable_and_independent() -> None:
    queue = TaskQueue()
    task_a = _make_task(name="a")
    queue.enqueue(task_a)

    snapshot = queue.tasks()

    check(isinstance(snapshot, tuple), "Q12: tasks() returns a tuple")

    raised = False
    try:
        snapshot[0] = _make_task(name="mutated")  # type: ignore[index]
    except TypeError:
        raised = True

    check(raised, "Q12: item assignment on the returned tuple raises TypeError")

    task_b = _make_task(name="b")
    queue.enqueue(task_b)  # mutate the queue after taking the earlier snapshot

    check(
        snapshot == (task_a,),
        "Q12: an earlier tasks() snapshot is unaffected by a later enqueue()",
    )
    check(
        queue.tasks() == (task_a, task_b),
        "Q12: a fresh tasks() call reflects the queue's current contents",
    )

    another_snapshot = queue.tasks()
    check(
        another_snapshot is not queue._tasks,
        "Q12: tasks() never hands out the internal list object itself",
    )


# ---------------------------------------------------------------------------
# Q13 -- multiple sequential dequeue() calls drain to empty
# ---------------------------------------------------------------------------
def scenario_multiple_dequeue_drains_to_empty() -> None:
    queue = TaskQueue()
    tasks = [_make_task(name=f"t{i}") for i in range(3)]
    for task in tasks:
        queue.enqueue(task)

    check(queue.dequeue() is tasks[0], "Q13: first dequeue() returns tasks[0]")
    check(queue.dequeue() is tasks[1], "Q13: second dequeue() returns tasks[1]")
    check(queue.dequeue() is tasks[2], "Q13: third dequeue() returns tasks[2]")
    check(queue.is_empty(), "Q13: the queue is empty after draining every task")

    raised = False
    try:
        queue.dequeue()
    except TaskQueueError:
        raised = True

    check(
        raised,
        "Q13: a dequeue() call after the last item raises TaskQueueError",
    )


# ---------------------------------------------------------------------------
# Q14 -- independent TaskQueue instances never share state
# ---------------------------------------------------------------------------
def scenario_independent_queue_instances() -> None:
    queue_a = TaskQueue()
    queue_b = TaskQueue()

    queue_a.enqueue(_make_task(name="only-in-a"))
    queue_a.enqueue(_make_task(name="also-only-in-a"))

    check(
        queue_b.size() == 0 and queue_b.is_empty(),
        "Q14: enqueuing on queue_a never affects queue_b's size/emptiness",
    )
    check(
        queue_b.tasks() == (),
        "Q14: queue_b's tasks() sees none of queue_a's enqueued work",
    )

    queue_b.enqueue(_make_task(name="only-in-b"))
    check(
        queue_a.size() == 2,
        "Q14: enqueuing on queue_b never affects queue_a's size",
    )


# ---------------------------------------------------------------------------
# Q15 -- repr() is stable and informative
# ---------------------------------------------------------------------------
def scenario_repr_is_stable_and_informative() -> None:
    queue = TaskQueue()
    check(
        repr(queue) == "TaskQueue(size=0)",
        "Q15: repr() of an empty queue reports size=0",
    )

    queue.enqueue(_make_task(name="a"))
    queue.enqueue(_make_task(name="b"))
    check(
        repr(queue) == "TaskQueue(size=2)",
        "Q15: repr() reflects the current size after enqueuing",
    )

    queue.dequeue()
    check(
        repr(queue) == "TaskQueue(size=1)",
        "Q15: repr() updates after dequeue()",
    )


# ---------------------------------------------------------------------------
# Q16 -- no execution/scheduling/persistence/eventing surface
# ---------------------------------------------------------------------------
def scenario_no_execution_or_persistence_surface() -> None:
    queue = TaskQueue()

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
        "event_bus",
    )

    none_present = all(
        not hasattr(queue, member) for member in forbidden_members
    )
    check(
        none_present,
        "Q16: TaskQueue exposes none of the forbidden execution/scheduling/"
        "persistence/eventing members",
    )


# ---------------------------------------------------------------------------
# Q17 -- TaskQueueError is an AgentError
# ---------------------------------------------------------------------------
def scenario_task_queue_error_is_agent_error_subclass() -> None:
    check(
        issubclass(TaskQueueError, AgentError),
        "Q17: TaskQueueError is a subclass of Core.exceptions.AgentError",
    )

    raised_as_agent_error = False
    try:
        TaskQueue().dequeue()
    except AgentError:
        raised_as_agent_error = True

    check(
        raised_as_agent_error,
        "Q17: a TaskQueueError from an empty dequeue() can be caught as "
        "AgentError",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_new_queue_starts_empty,
        scenario_enqueue_adds_one_task,
        scenario_enqueue_rejects_invalid_input,
        scenario_fifo_ordering_preserved,
        scenario_dequeue_removes_task,
        scenario_dequeue_on_empty_queue_raises,
        scenario_peek_does_not_remove,
        scenario_peek_on_empty_queue_raises,
        scenario_size_tracks_operations,
        scenario_clear_behavior,
        scenario_duplicate_tasks_allowed,
        scenario_tasks_snapshot_is_immutable_and_independent,
        scenario_multiple_dequeue_drains_to_empty,
        scenario_independent_queue_instances,
        scenario_repr_is_stable_and_informative,
        scenario_no_execution_or_persistence_surface,
        scenario_task_queue_error_is_agent_error_subclass,
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
    print(f"PHASE 3 SPRINT 25 TASK QUEUE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())