from __future__ import annotations

from typing import Optional

from Core.exceptions import AgentError
from Orchestration.task_manager import TaskManager
from Orchestration.workflow import Workflow


class WorkflowEngineError(AgentError):
    """Raised when ``WorkflowEngine`` is given invalid inputs, or when
    an operation cannot be satisfied given the engine's current state
    (e.g. ``prepare()`` with no ``Workflow`` currently loaded).

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``WorkflowError``,
    ``WorkflowManagerError``, ``TaskError``, ``TaskQueueError``,
    ``TaskManagerError``, ``AutonomousSchedulerError``,
    ``AutonomousHostError``, ``AutonomousAgentError``,
    ``EventBusError``, and others), rather than deriving from the
    bare ``Exception`` class.
    """

    pass


class WorkflowEngine:
    """Sprint 29 -- the first *executable* piece of the Workflow
    stack, and deliberately still a pure preparation layer: it loads
    one ``Workflow`` at a time and, on request, hands that workflow's
    ``Task`` instances to a ``TaskManager`` in order -- nothing more.

    ``WorkflowEngine`` owns exactly two things: a reference to the
    single ``TaskManager`` it was constructed with, and (at most) one
    currently-loaded ``Workflow``. It performs no execution of any
    kind -- no ``Task`` is ever run, no ``Task.status`` or
    ``Workflow.status`` is ever changed by anything in this module --
    and it never imports, references, or calls
    ``Orchestration.autonomous_scheduler.AutonomousScheduler``,
    ``Orchestration.autonomous_host.AutonomousHost``,
    ``Orchestration.autonomous_agent.AutonomousAgent``,
    ``Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline``,
    or ``Orchestration.event_bus.EventBus``. There is no retry logic,
    no dependency graph or dependency resolution, no branching, no
    persistence, no threading, and no asyncio anywhere in this
    module.

    ``prepare()`` is the one method that does something beyond plain
    bookkeeping, and even that is simple, synchronous delegation:
    clear whatever the bound ``TaskManager`` currently holds, then
    ``submit()`` each ``Task`` from the loaded ``Workflow.tasks`` to
    it, strictly in the order they appear in ``Workflow.tasks``. It
    performs no graph traversal, dependency resolution, or reordering
    of any kind.
    """

    def __init__(self, task_manager: TaskManager) -> None:
        """Construct a ``WorkflowEngine`` bound to a single
        ``TaskManager``.

        Args:
            task_manager: the ``TaskManager`` this engine will submit
                tasks to on ``prepare()``. Must not be ``None`` and
                must be a ``TaskManager`` instance.

        Raises:
            WorkflowEngineError: if ``task_manager`` is ``None`` or is
                not a ``TaskManager`` instance.
        """
        if task_manager is None:
            raise WorkflowEngineError(
                "WorkflowEngine requires a non-None 'task_manager'"
            )

        if not isinstance(task_manager, TaskManager):
            raise WorkflowEngineError(
                f"WorkflowEngine requires 'task_manager' to be a "
                f"TaskManager instance; got {task_manager!r}"
            )

        self._task_manager: TaskManager = task_manager
        self._current_workflow: Optional[Workflow] = None

    def load(self, workflow: Workflow) -> None:
        """Load ``workflow`` as this engine's current workflow,
        replacing whatever was previously loaded (if anything).

        Args:
            workflow: the ``Workflow`` to load. Must not be ``None``
                and must be a ``Workflow`` instance.

        Returns:
            ``None``.

        Raises:
            WorkflowEngineError: if ``workflow`` is ``None`` or is not
                a ``Workflow`` instance. On rejection, whatever was
                previously loaded (if anything) remains loaded,
                unchanged.
        """
        if workflow is None:
            raise WorkflowEngineError(
                "WorkflowEngine.load() requires a non-None 'workflow'"
            )

        if not isinstance(workflow, Workflow):
            raise WorkflowEngineError(
                f"WorkflowEngine.load() requires 'workflow' to be a "
                f"Workflow instance; got {workflow!r}"
            )

        self._current_workflow = workflow
        return None

    def current_workflow(self) -> Optional[Workflow]:
        """Return the currently-loaded ``Workflow``, or ``None`` if
        nothing is loaded.

        Returns:
            The ``Workflow`` passed to the most recent successful
            ``load()`` call, or ``None`` if no workflow is currently
            loaded (either because ``load()`` was never called, or
            ``unload()`` was called since).
        """
        return self._current_workflow

    def unload(self) -> None:
        """Remove the currently-loaded ``Workflow``, if any.

        Safe to call when nothing is loaded (a no-op). Only affects
        which ``Workflow`` this engine considers "current" -- it does
        not touch this engine's bound ``TaskManager`` in any way, so
        any tasks a prior ``prepare()`` call already submitted are
        left exactly as they were.

        Returns:
            ``None``.
        """
        self._current_workflow = None
        return None

    def prepare(self) -> int:
        """Submit every ``Task`` from the currently-loaded
        ``Workflow`` to this engine's bound ``TaskManager``, in
        order.

        First clears the bound ``TaskManager`` (via ``clear()``), then
        calls ``submit()`` once per ``Task`` in ``Workflow.tasks``,
        strictly in the order they appear there -- no execution,
        reordering, deduplication, or dependency resolution of any
        kind. Calling ``prepare()`` again (with the same or a
        different workflow loaded) simply repeats this: clear, then
        resubmit, from scratch.

        Returns:
            The number of ``Task`` instances submitted -- exactly
            ``len(workflow.tasks)`` for the currently-loaded
            ``workflow``. ``0`` for a workflow with no tasks.

        Raises:
            WorkflowEngineError: if no ``Workflow`` is currently
                loaded.
        """
        if self._current_workflow is None:
            raise WorkflowEngineError(
                "WorkflowEngine.prepare() requires a loaded Workflow; "
                "call load() first"
            )

        self._task_manager.clear()

        submitted = 0
        for task in self._current_workflow.tasks:
            self._task_manager.submit(task)
            submitted += 1

        return submitted

    def __repr__(self) -> str:
        """Return an unambiguous, informative representation useful
        for debugging/logs -- the class name plus whether a workflow
        is currently loaded (and its ``workflow_id`` if so), mirroring
        the terse, no-content-dump style already used by ``repr()``
        elsewhere in this codebase for orchestration objects (e.g.
        ``TaskQueue.__repr__``, ``TaskManager.__repr__``,
        ``WorkflowManager.__repr__``)."""
        loaded = (
            self._current_workflow.workflow_id
            if self._current_workflow is not None
            else None
        )
        return f"WorkflowEngine(loaded_workflow_id={loaded!r})"