from __future__ import annotations

from typing import List, Tuple

from Core.exceptions import AgentError
from Orchestration.task import Task


class TaskQueueError(AgentError):
    """Raised when ``TaskQueue`` is given invalid inputs, or when an
    operation cannot be satisfied given the queue's current state
    (e.g. ``dequeue()``/``peek()`` on an empty queue).

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``AutonomousSchedulerError``,
    ``AutonomousHostError``, ``AutonomousAgentError``,
    ``EventBusError``, ``TaskError``, and others), rather than
    deriving from the bare ``Exception`` class.
    """

    pass


class TaskQueue:
    """Sprint 25 -- the storage layer for ``Task`` value objects.

    ``TaskQueue`` owns exactly one thing: a FIFO list of ``Task``
    instances. It holds no other state, and performs no execution,
    scheduling, workflow, persistence, or eventing of any kind --
    it never imports, references, or calls
    ``Orchestration.autonomous_scheduler.AutonomousScheduler``,
    ``Orchestration.autonomous_host.AutonomousHost``,
    ``Orchestration.autonomous_agent.AutonomousAgent``,
    ``Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline``,
    or ``Orchestration.event_bus.EventBus``. Nothing is written to
    disk/DB -- the queue lives only in this instance's own process
    memory and is lost the moment the instance is garbage collected.

    This is a plain in-memory FIFO: there is no threading, no
    asyncio, no timers, no background execution, and no priority
    ordering of any kind -- ``enqueue()`` always appends to the back,
    and ``dequeue()`` always removes from the front, strictly in the
    order tasks were enqueued. Duplicate tasks (by value, by
    ``task_id``, or the exact same ``Task`` instance enqueued more
    than once) are all allowed -- ``TaskQueue`` never deduplicates.

    Storage is private: the underlying list is never handed out
    directly. ``tasks()`` returns a fresh ``tuple`` snapshot each
    call, so nothing the caller does with the returned structure can
    affect this queue's own state.
    """

    def __init__(self) -> None:
        self._tasks: List[Task] = []

    def enqueue(self, task: Task) -> None:
        """Append ``task`` to the back of the FIFO queue.

        Args:
            task: the ``Task`` to enqueue. Must not be ``None`` and
                must be a ``Task`` instance. Duplicate tasks (equal
                by value, sharing a ``task_id``, or literally the
                same object already enqueued) are all accepted --
                ``enqueue()`` never rejects on the grounds of
                duplication.

        Returns:
            ``None``.

        Raises:
            TaskQueueError: if ``task`` is ``None`` or is not a
                ``Task`` instance.
        """
        if task is None:
            raise TaskQueueError(
                "TaskQueue.enqueue() requires a non-None 'task'"
            )

        if not isinstance(task, Task):
            raise TaskQueueError(
                f"TaskQueue.enqueue() requires 'task' to be a Task "
                f"instance; got {task!r}"
            )

        self._tasks.append(task)
        return None

    def dequeue(self) -> Task:
        """Remove and return the ``Task`` at the front of the FIFO
        queue.

        Returns:
            The ``Task`` that has been waiting longest (i.e. the one
            least-recently ``enqueue()``'d that has not already been
            dequeued).

        Raises:
            TaskQueueError: if the queue is currently empty.
        """
        if not self._tasks:
            raise TaskQueueError(
                "TaskQueue.dequeue() cannot be called on an empty queue"
            )

        return self._tasks.pop(0)

    def peek(self) -> Task:
        """Return (without removing) the ``Task`` at the front of the
        FIFO queue.

        Calling ``peek()`` any number of times has no effect on the
        queue's contents or on what a subsequent ``dequeue()`` will
        return.

        Returns:
            The ``Task`` currently at the front of the queue.

        Raises:
            TaskQueueError: if the queue is currently empty.
        """
        if not self._tasks:
            raise TaskQueueError(
                "TaskQueue.peek() cannot be called on an empty queue"
            )

        return self._tasks[0]

    def clear(self) -> None:
        """Remove every ``Task`` currently waiting in the FIFO queue.

        Safe to call on an already-empty queue, and safe to call
        repeatedly (each call after the first is a no-op). Only this
        queue's own storage is affected; other ``TaskQueue``
        instances are unaffected.

        Returns:
            ``None``.
        """
        self._tasks.clear()
        return None

    def size(self) -> int:
        """Return the number of ``Task`` instances currently waiting
        in the queue.

        Returns:
            A non-negative ``int`` count. ``0`` for an empty queue.
        """
        return len(self._tasks)

    def is_empty(self) -> bool:
        """Return whether the queue currently holds no tasks.

        Returns:
            ``True`` if ``size()`` is ``0``, ``False`` otherwise.
        """
        return len(self._tasks) == 0

    def tasks(self) -> Tuple[Task, ...]:
        """Return an immutable snapshot of every task currently
        waiting in the FIFO queue, in queue order (front first).

        This is read-only inspection: it performs no removal or
        reordering, and mutating (or attempting to mutate) the
        returned ``tuple`` -- or anything the caller does with it --
        cannot affect this queue's own state. The internal list is
        never handed out directly; a new ``tuple`` is built from it
        each call.

        Returns:
            A ``tuple`` of ``Task`` instances, oldest (next to
            dequeue) first. Empty queue returns an empty tuple.
        """
        return tuple(self._tasks)

    def __repr__(self) -> str:
        """Return an unambiguous, informative representation useful
        for debugging/logs -- the class name plus the current task
        count, mirroring the terse, no-content-dump style already
        used by ``repr()`` elsewhere in this codebase for container-
        like objects."""
        return f"TaskQueue(size={len(self._tasks)})"