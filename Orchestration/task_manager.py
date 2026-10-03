from __future__ import annotations

from Core.exceptions import AgentError
from Orchestration.task import Task
from Orchestration.task_queue import TaskQueue


class TaskManagerError(AgentError):
    """Raised when ``TaskManager`` is given invalid inputs at
    construction time.

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``TaskQueueError``, ``TaskError``,
    ``AutonomousSchedulerError``, ``AutonomousHostError``,
    ``AutonomousAgentError``, ``EventBusError``, and others), rather
    than deriving from the bare ``Exception`` class.
    """

    pass


class TaskManager:
    """Sprint 26 -- the orchestration layer that owns a ``Task``'s
    lifecycle at the API level, sitting directly on top of a
    ``TaskQueue``.

    ``TaskManager`` owns orchestration only; ``TaskQueue`` owns
    storage only. Every public method on this class does nothing but
    delegate, unmodified, to the single corresponding ``TaskQueue``
    method it wraps -- ``submit()`` calls ``TaskQueue.enqueue()``,
    ``next_task()`` calls ``TaskQueue.dequeue()``, ``peek_task()``
    calls ``TaskQueue.peek()``, ``clear()`` calls ``TaskQueue.clear()``,
    ``task_count()`` calls ``TaskQueue.size()``, and ``has_tasks()``
    calls ``TaskQueue.is_empty()`` (inverted). No method reimplements,
    duplicates, or shortcuts any of that storage logic -- there is no
    second, parallel list of tasks anywhere in this class, and
    ``TaskManager`` never reaches past the ``TaskQueue`` instance it
    was constructed with into that queue's own private internals.

    ``TaskManager`` never changes a ``Task``'s ``status`` and never
    executes a ``Task`` in any sense -- there is no ``run()``,
    ``start()``, or similar method here, and nothing in this module
    imports, references, calls, or even mentions
    ``Orchestration.autonomous_scheduler.AutonomousScheduler``,
    ``Orchestration.autonomous_host.AutonomousHost``,
    ``Orchestration.autonomous_agent.AutonomousAgent``,
    ``Orchestration.planner`` (or any other Workflow component),
    ``Orchestration.event_bus.EventBus``, or
    ``Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline``.
    This sprint deliberately stops at plain, synchronous delegation:
    no retries, no priority, no persistence, no threading, and no
    asyncio exist anywhere in this module.
    """

    def __init__(self, task_queue: TaskQueue) -> None:
        """Construct a ``TaskManager`` bound to a single ``TaskQueue``.

        Args:
            task_queue: the ``TaskQueue`` instance this manager will
                delegate every operation to. Must not be ``None`` and
                must be a ``TaskQueue`` instance.

        Raises:
            TaskManagerError: if ``task_queue`` is ``None`` or is not
                a ``TaskQueue`` instance.
        """
        if task_queue is None:
            raise TaskManagerError(
                "TaskManager requires a non-None 'task_queue'"
            )

        if not isinstance(task_queue, TaskQueue):
            raise TaskManagerError(
                f"TaskManager requires 'task_queue' to be a TaskQueue "
                f"instance; got {task_queue!r}"
            )

        self._task_queue: TaskQueue = task_queue

    def submit(self, task: Task) -> None:
        """Submit ``task`` for later processing.

        Delegates directly to ``TaskQueue.enqueue()`` -- see that
        method's docstring for the exact validation and behavior
        (including the ``TaskQueueError`` this raises on invalid
        input, which propagates unchanged).

        Args:
            task: the ``Task`` to submit.

        Returns:
            ``None``.
        """
        return self._task_queue.enqueue(task)

    def next_task(self) -> Task:
        """Remove and return the next ``Task`` to be processed.

        Delegates directly to ``TaskQueue.dequeue()`` -- see that
        method's docstring for the exact FIFO ordering and behavior
        (including the ``TaskQueueError`` this raises on an empty
        queue, which propagates unchanged).

        Returns:
            The ``Task`` that has been waiting longest.
        """
        return self._task_queue.dequeue()

    def peek_task(self) -> Task:
        """Return (without removing) the next ``Task`` to be
        processed.

        Delegates directly to ``TaskQueue.peek()`` -- see that
        method's docstring for the exact behavior (including the
        ``TaskQueueError`` this raises on an empty queue, which
        propagates unchanged).

        Returns:
            The ``Task`` currently at the front of the queue.
        """
        return self._task_queue.peek()

    def clear(self) -> None:
        """Remove every currently-submitted ``Task``.

        Delegates directly to ``TaskQueue.clear()``.

        Returns:
            ``None``.
        """
        return self._task_queue.clear()

    def task_count(self) -> int:
        """Return the number of ``Task`` instances currently
        submitted and not yet taken via ``next_task()``.

        Delegates directly to ``TaskQueue.size()``.

        Returns:
            A non-negative ``int`` count. ``0`` when nothing is
            submitted.
        """
        return self._task_queue.size()

    def has_tasks(self) -> bool:
        """Return whether at least one ``Task`` is currently
        submitted and not yet taken via ``next_task()``.

        Delegates directly to ``TaskQueue.is_empty()``, inverting the
        result -- ``has_tasks()`` is ``True`` precisely when
        ``is_empty()`` is ``False``.

        Returns:
            ``True`` if at least one task is waiting, ``False``
            otherwise.
        """
        return not self._task_queue.is_empty()

    def __repr__(self) -> str:
        """Return an unambiguous, informative representation useful
        for debugging/logs -- the class name plus the current task
        count, mirroring the terse, no-content-dump style already
        used by ``repr()`` elsewhere in this codebase for container-
        like/orchestration objects (e.g. ``TaskQueue.__repr__``)."""
        return f"TaskManager(task_count={self._task_queue.size()})"