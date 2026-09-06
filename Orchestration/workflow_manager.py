from __future__ import annotations

from typing import List, Tuple

from Core.exceptions import AgentError
from Orchestration.workflow import Workflow


class WorkflowManagerError(AgentError):
    """Raised when ``WorkflowManager`` is given invalid inputs, or
    when an operation cannot be satisfied given the manager's current
    state (e.g. ``get()``/``remove()`` for a ``workflow_id`` that is
    not present, or ``add()`` of a ``workflow_id`` that already is).

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``WorkflowError``, ``TaskError``,
    ``TaskQueueError``, ``TaskManagerError``,
    ``AutonomousSchedulerError``, ``AutonomousHostError``,
    ``AutonomousAgentError``, ``EventBusError``, and others), rather
    than deriving from the bare ``Exception`` class.
    """

    pass


class WorkflowManager:
    """Sprint 28 -- the storage/lifecycle layer for ``Workflow``
    value objects.

    ``WorkflowManager`` owns exactly one thing: an ordered collection
    of ``Workflow`` instances, keyed by their ``workflow_id``. It
    holds no other state, and performs no execution, scheduling, task
    execution, queue integration, workflow engine, persistence, or
    eventing of any kind -- it never imports, references, or calls
    ``Orchestration.task_queue.TaskQueue``,
    ``Orchestration.task_manager.TaskManager``,
    ``Orchestration.autonomous_scheduler.AutonomousScheduler``,
    ``Orchestration.autonomous_host.AutonomousHost``,
    ``Orchestration.autonomous_agent.AutonomousAgent``,
    ``Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline``,
    or ``Orchestration.event_bus.EventBus``. Nothing is written to
    disk/DB -- the collection lives only in this instance's own
    process memory and is lost the moment the instance is garbage
    collected.

    This is a plain in-memory, insertion-ordered store: there is no
    threading, no asyncio, no timers, no background execution, and no
    reordering of any kind -- ``add()`` always appends to the end, and
    iteration order (as seen via ``workflows()``) always reflects the
    order ``Workflow`` instances were added in, with removed entries
    simply gone. Two distinct ``Workflow`` instances that happen to
    share a ``workflow_id`` are treated as a duplicate and rejected by
    ``add()`` -- as is re-adding the exact same ``Workflow`` object a
    second time (which necessarily shares its own ``workflow_id`` with
    itself).

    Storage is private: the underlying list is never handed out
    directly. ``workflows()`` returns a fresh ``tuple`` snapshot each
    call, so nothing the caller does with the returned structure can
    affect this manager's own state.
    """

    def __init__(self) -> None:
        """Construct an empty ``WorkflowManager``.

        Requires no dependencies/arguments -- the manager owns its
        storage entirely on its own.
        """
        self._workflows: List[Workflow] = []

    def _find_index(self, workflow_id: str) -> int:
        """Return the index of the stored ``Workflow`` whose
        ``workflow_id`` equals ``workflow_id``, or ``-1`` if none is
        stored.

        Args:
            workflow_id: the ``workflow_id`` to look up. Must be a
                non-empty ``str``.

        Raises:
            WorkflowManagerError: if ``workflow_id`` is not a
                non-empty ``str``.
        """
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise WorkflowManagerError(
                f"WorkflowManager requires 'workflow_id' to be a non-empty "
                f"str; got {workflow_id!r}"
            )

        for index, existing in enumerate(self._workflows):
            if existing.workflow_id == workflow_id:
                return index

        return -1

    def add(self, workflow: Workflow) -> None:
        """Add ``workflow`` to the end of this manager's collection.

        Args:
            workflow: the ``Workflow`` to add. Must not be ``None``
                and must be a ``Workflow`` instance. Its
                ``workflow_id`` must not already be present in this
                manager.

        Returns:
            ``None``.

        Raises:
            WorkflowManagerError: if ``workflow`` is ``None``; if it
                is not a ``Workflow`` instance; or if a ``Workflow``
                with the same ``workflow_id`` (including the exact
                same object) is already stored in this manager.
        """
        if workflow is None:
            raise WorkflowManagerError(
                "WorkflowManager.add() requires a non-None 'workflow'"
            )

        if not isinstance(workflow, Workflow):
            raise WorkflowManagerError(
                f"WorkflowManager.add() requires 'workflow' to be a "
                f"Workflow instance; got {workflow!r}"
            )

        for existing in self._workflows:
            if existing.workflow_id == workflow.workflow_id:
                raise WorkflowManagerError(
                    f"WorkflowManager.add() rejected: a Workflow with "
                    f"workflow_id {workflow.workflow_id!r} is already "
                    f"present"
                )

        self._workflows.append(workflow)
        return None

    def remove(self, workflow_id: str) -> Workflow:
        """Remove and return the ``Workflow`` stored under
        ``workflow_id``.

        Args:
            workflow_id: the ``workflow_id`` of the ``Workflow`` to
                remove.

        Returns:
            The removed ``Workflow`` instance.

        Raises:
            WorkflowManagerError: if ``workflow_id`` is not a
                non-empty ``str``, or if no ``Workflow`` with that
                ``workflow_id`` is currently stored.
        """
        index = self._find_index(workflow_id)

        if index == -1:
            raise WorkflowManagerError(
                f"WorkflowManager.remove() found no Workflow with "
                f"workflow_id {workflow_id!r}"
            )

        return self._workflows.pop(index)

    def get(self, workflow_id: str) -> Workflow:
        """Return (without removing) the ``Workflow`` stored under
        ``workflow_id``.

        Args:
            workflow_id: the ``workflow_id`` of the ``Workflow`` to
                retrieve.

        Returns:
            The matching ``Workflow`` instance.

        Raises:
            WorkflowManagerError: if ``workflow_id`` is not a
                non-empty ``str``, or if no ``Workflow`` with that
                ``workflow_id`` is currently stored.
        """
        index = self._find_index(workflow_id)

        if index == -1:
            raise WorkflowManagerError(
                f"WorkflowManager.get() found no Workflow with "
                f"workflow_id {workflow_id!r}"
            )

        return self._workflows[index]

    def contains(self, workflow_id: str) -> bool:
        """Return whether a ``Workflow`` with ``workflow_id`` is
        currently stored.

        Args:
            workflow_id: the ``workflow_id`` to check for.

        Returns:
            ``True`` if a matching ``Workflow`` is stored, ``False``
            otherwise.

        Raises:
            WorkflowManagerError: if ``workflow_id`` is not a
                non-empty ``str``.
        """
        return self._find_index(workflow_id) != -1

    def workflows(self) -> Tuple[Workflow, ...]:
        """Return an immutable snapshot of every ``Workflow``
        currently stored, in insertion order.

        This is read-only inspection: it performs no removal or
        reordering, and mutating (or attempting to mutate) the
        returned ``tuple`` -- or anything the caller does with it --
        cannot affect this manager's own state. The internal list is
        never handed out directly; a new ``tuple`` is built from it
        each call.

        Returns:
            A ``tuple`` of ``Workflow`` instances, oldest-added
            first. Empty manager returns an empty tuple.
        """
        return tuple(self._workflows)

    def clear(self) -> None:
        """Remove every ``Workflow`` currently stored.

        Safe to call on an already-empty manager, and safe to call
        repeatedly (each call after the first is a no-op). Only this
        manager's own storage is affected; other ``WorkflowManager``
        instances are unaffected.

        Returns:
            ``None``.
        """
        self._workflows.clear()
        return None

    def count(self) -> int:
        """Return the number of ``Workflow`` instances currently
        stored.

        Returns:
            A non-negative ``int`` count. ``0`` for an empty manager.
        """
        return len(self._workflows)

    def __repr__(self) -> str:
        """Return an unambiguous, informative representation useful
        for debugging/logs -- the class name plus the current
        workflow count, mirroring the terse, no-content-dump style
        already used by ``repr()`` elsewhere in this codebase for
        container-like/orchestration objects (e.g.
        ``TaskQueue.__repr__``, ``TaskManager.__repr__``)."""
        return f"WorkflowManager(count={len(self._workflows)})"