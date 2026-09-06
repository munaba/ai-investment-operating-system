from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Mapping, Optional

from Core.exceptions import AgentError
from Orchestration.execution_context import ExecutionContext
from Orchestration.workflow import Workflow
from Orchestration.workflow_session import (
    WorkflowSession,
    WorkflowSessionError,
    WorkflowSessionStatus,
)


class WorkflowSessionManagerError(AgentError):
    """Raised when ``WorkflowSessionManager`` is given invalid inputs,
    or when a requested lifecycle transition is not permitted from a
    ``WorkflowSession``'s current status.

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``WorkflowSessionError``,
    ``WorkflowExecutionCoordinatorError``, ``WorkflowEngineError``,
    ``WorkflowManagerError``, ``ExecutorError``, ``TaskError``,
    ``TaskQueueError``, ``TaskManagerError``,
    ``AutonomousSchedulerError``, ``AutonomousHostError``,
    ``AutonomousAgentError``, ``EventBusError``, and others), rather
    than deriving from the bare ``Exception`` class.
    """

    pass


class WorkflowSessionManager:
    """Sprint 36 -- the lifecycle-transition layer for
    ``WorkflowSession`` value objects.

    ``WorkflowSession`` (Sprint 35) is an immutable, frozen value
    object that carries a ``status`` field but owns no behavior of
    its own -- nothing transitions that status from one state to
    another. ``WorkflowSessionManager`` is the single component that
    fills that gap: it owns *only* the rules for which
    ``WorkflowSessionStatus`` transitions are legal, and how to
    produce the next ``WorkflowSession`` in that lifecycle.

    ``WorkflowSessionManager`` never executes anything: it never
    prepares a ``Workflow`` (``WorkflowEngine.prepare()``), never runs
    a ``Task`` (``Executor``), never schedules anything
    (``AutonomousScheduler``), and never talks to
    ``Orchestration.event_bus.EventBus``. It does not import
    ``WorkflowEngine``, ``WorkflowExecutionCoordinator``, ``Executor``,
    ``AutonomousScheduler``, ``AutonomousHost``, ``AutonomousAgent``,
    ``RuntimeAnalysisPipeline``, ``EventBus``, the Composition Root,
    ``threading``, or ``asyncio`` anywhere in this module. The words
    "prepare", "start", "complete", "fail", and "cancel" describe
    *status labels* only here -- none of them do any actual
    preparation, execution, scheduling, or eventing.

    ``WorkflowSession`` remains frozen throughout: every lifecycle
    method below returns a **new** ``WorkflowSession`` instance (built
    via ``dataclasses.replace``, changing only ``status``) and never
    mutates the ``session`` passed in. The original ``session`` object
    is always left completely untouched -- callers that hold a
    reference to it will see it report its original status forever;
    only the *returned* object reflects the new status. ``workflow``,
    ``execution_context``, ``session_id``, ``created_at``, and
    ``metadata`` are always carried over unchanged (by identity, for
    ``workflow``/``execution_context``; by value, for the immutable
    ``metadata`` mapping) from the input session to the returned one.

    Allowed transitions (anything not listed here is rejected):

        CREATED   --prepare()--> PREPARED
        PREPARED  --start()-->   RUNNING
        RUNNING   --complete()-> COMPLETED
        CREATED   --fail()-->    FAILED
        PREPARED  --fail()-->    FAILED
        RUNNING   --fail()-->    FAILED
        CREATED   --cancel()-->  CANCELLED
        PREPARED  --cancel()-->  CANCELLED
        RUNNING   --cancel()-->  CANCELLED

    ``COMPLETED``, ``FAILED``, and ``CANCELLED`` are terminal: no
    method on this class accepts a session already in one of those
    three statuses -- every such call raises
    ``WorkflowSessionManagerError`` without constructing anything.

    This class holds no instance state of its own (mirroring
    ``Orchestration.workflow_execution_coordinator.
    WorkflowExecutionCoordinator``) -- it is safe to reuse a single
    instance across any number of calls, against any combination of
    ``WorkflowSession`` instances.
    """

    # Maps each public transition method's name to the set of
    # WorkflowSessionStatus values it may be called from, and the
    # single WorkflowSessionStatus it produces. Consulted by
    # ``_transition`` only -- this is the one and only place transition
    # legality is decided.
    _TRANSITIONS: Dict[str, "tuple[frozenset, WorkflowSessionStatus]"] = {
        "prepare": (
            frozenset({WorkflowSessionStatus.CREATED}),
            WorkflowSessionStatus.PREPARED,
        ),
        "start": (
            frozenset({WorkflowSessionStatus.PREPARED}),
            WorkflowSessionStatus.RUNNING,
        ),
        "complete": (
            frozenset({WorkflowSessionStatus.RUNNING}),
            WorkflowSessionStatus.COMPLETED,
        ),
        "fail": (
            frozenset(
                {
                    WorkflowSessionStatus.CREATED,
                    WorkflowSessionStatus.PREPARED,
                    WorkflowSessionStatus.RUNNING,
                }
            ),
            WorkflowSessionStatus.FAILED,
        ),
        "cancel": (
            frozenset(
                {
                    WorkflowSessionStatus.CREATED,
                    WorkflowSessionStatus.PREPARED,
                    WorkflowSessionStatus.RUNNING,
                }
            ),
            WorkflowSessionStatus.CANCELLED,
        ),
    }

    def create(
        self,
        workflow: Workflow,
        execution_context: ExecutionContext,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> WorkflowSession:
        """Construct a brand-new ``WorkflowSession`` in
        ``WorkflowSessionStatus.CREATED``.

        This is a thin, validating wrapper around the
        ``WorkflowSession`` constructor -- it performs no preparation,
        execution, or scheduling of any kind.

        Args:
            workflow: the ``Workflow`` this session represents a
                single execution of. Must be a ``Workflow`` instance.
            execution_context: the ``ExecutionContext`` this session's
                execution runs within. Must be an ``ExecutionContext``
                instance.
            metadata: optional session-specific data. Must be a
                ``Mapping`` when provided; ``None`` (the default) is
                treated as an empty mapping.

        Returns:
            A new ``WorkflowSession`` with ``status ==
            WorkflowSessionStatus.CREATED``.

        Raises:
            WorkflowSessionManagerError: if ``workflow`` is not a
                ``Workflow`` instance; if ``execution_context`` is not
                an ``ExecutionContext`` instance; if ``metadata`` is
                neither ``None`` nor a ``Mapping``; or if
                ``WorkflowSession`` construction otherwise rejects the
                given inputs.
        """
        try:
            return WorkflowSession(
                workflow=workflow,
                execution_context=execution_context,
                status=WorkflowSessionStatus.CREATED,
                metadata={} if metadata is None else metadata,
            )
        except WorkflowSessionError as error:
            raise WorkflowSessionManagerError(
                f"WorkflowSessionManager.create() could not construct a "
                f"WorkflowSession: {error}"
            ) from error

    def prepare(self, session: WorkflowSession) -> WorkflowSession:
        """Transition ``session`` from ``CREATED`` to ``PREPARED``.

        Args:
            session: the ``WorkflowSession`` to transition. Must be a
                ``WorkflowSession`` instance currently in
                ``WorkflowSessionStatus.CREATED``. Left completely
                untouched by this call.

        Returns:
            A new ``WorkflowSession``, identical to ``session`` except
            ``status == WorkflowSessionStatus.PREPARED``.

        Raises:
            WorkflowSessionManagerError: if ``session`` is not a
                ``WorkflowSession`` instance, or if ``session.status``
                is not ``WorkflowSessionStatus.CREATED``.
        """
        return self._transition("prepare", session)

    def start(self, session: WorkflowSession) -> WorkflowSession:
        """Transition ``session`` from ``PREPARED`` to ``RUNNING``.

        Args:
            session: the ``WorkflowSession`` to transition. Must be a
                ``WorkflowSession`` instance currently in
                ``WorkflowSessionStatus.PREPARED``. Left completely
                untouched by this call.

        Returns:
            A new ``WorkflowSession``, identical to ``session`` except
            ``status == WorkflowSessionStatus.RUNNING``.

        Raises:
            WorkflowSessionManagerError: if ``session`` is not a
                ``WorkflowSession`` instance, or if ``session.status``
                is not ``WorkflowSessionStatus.PREPARED``.
        """
        return self._transition("start", session)

    def complete(self, session: WorkflowSession) -> WorkflowSession:
        """Transition ``session`` from ``RUNNING`` to ``COMPLETED``.

        Args:
            session: the ``WorkflowSession`` to transition. Must be a
                ``WorkflowSession`` instance currently in
                ``WorkflowSessionStatus.RUNNING``. Left completely
                untouched by this call.

        Returns:
            A new ``WorkflowSession``, identical to ``session`` except
            ``status == WorkflowSessionStatus.COMPLETED`` -- a
            terminal status.

        Raises:
            WorkflowSessionManagerError: if ``session`` is not a
                ``WorkflowSession`` instance, or if ``session.status``
                is not ``WorkflowSessionStatus.RUNNING``.
        """
        return self._transition("complete", session)

    def fail(self, session: WorkflowSession) -> WorkflowSession:
        """Transition ``session`` to ``FAILED``.

        Allowed from ``CREATED``, ``PREPARED``, or ``RUNNING`` -- a
        session may fail before, during preparation, or during
        execution.

        Args:
            session: the ``WorkflowSession`` to transition. Must be a
                ``WorkflowSession`` instance currently in
                ``WorkflowSessionStatus.CREATED``,
                ``WorkflowSessionStatus.PREPARED``, or
                ``WorkflowSessionStatus.RUNNING``. Left completely
                untouched by this call.

        Returns:
            A new ``WorkflowSession``, identical to ``session`` except
            ``status == WorkflowSessionStatus.FAILED`` -- a terminal
            status.

        Raises:
            WorkflowSessionManagerError: if ``session`` is not a
                ``WorkflowSession`` instance, or if ``session.status``
                is already one of the terminal statuses (``COMPLETED``,
                ``FAILED``, ``CANCELLED``).
        """
        return self._transition("fail", session)

    def cancel(self, session: WorkflowSession) -> WorkflowSession:
        """Transition ``session`` to ``CANCELLED``.

        Allowed from ``CREATED``, ``PREPARED``, or ``RUNNING`` -- a
        session may be cancelled before, during preparation, or during
        execution.

        Args:
            session: the ``WorkflowSession`` to transition. Must be a
                ``WorkflowSession`` instance currently in
                ``WorkflowSessionStatus.CREATED``,
                ``WorkflowSessionStatus.PREPARED``, or
                ``WorkflowSessionStatus.RUNNING``. Left completely
                untouched by this call.

        Returns:
            A new ``WorkflowSession``, identical to ``session`` except
            ``status == WorkflowSessionStatus.CANCELLED`` -- a
            terminal status.

        Raises:
            WorkflowSessionManagerError: if ``session`` is not a
                ``WorkflowSession`` instance, or if ``session.status``
                is already one of the terminal statuses (``COMPLETED``,
                ``FAILED``, ``CANCELLED``).
        """
        return self._transition("cancel", session)

    def _transition(
        self, method_name: str, session: WorkflowSession
    ) -> WorkflowSession:
        """Validate and perform the single lifecycle transition named
        by ``method_name``, returning a new ``WorkflowSession``.

        This is the one and only place transition legality is decided
        -- every public lifecycle method above delegates here rather
        than duplicating validation logic.

        Args:
            method_name: the key into ``_TRANSITIONS`` identifying
                which transition is being requested (``"prepare"``,
                ``"start"``, ``"complete"``, ``"fail"``, or
                ``"cancel"``).
            session: the ``WorkflowSession`` to transition. Must be a
                ``WorkflowSession`` instance whose current ``status``
                is a member of the allowed "from" set for
                ``method_name``.

        Returns:
            A new ``WorkflowSession``, identical to ``session`` except
            for its ``status``, which is set to the "to" status
            associated with ``method_name``.

        Raises:
            WorkflowSessionManagerError: if ``session`` is ``None`` or
                is not a ``WorkflowSession`` instance; or if
                ``session.status`` is not in the allowed "from" set
                for ``method_name`` (this includes every case where
                ``session.status`` is already a terminal status --
                ``COMPLETED``, ``FAILED``, or ``CANCELLED`` -- none of
                which appear in any "from" set).
        """
        if session is None:
            raise WorkflowSessionManagerError(
                f"WorkflowSessionManager.{method_name}() requires a "
                f"non-None 'session'"
            )

        if not isinstance(session, WorkflowSession):
            raise WorkflowSessionManagerError(
                f"WorkflowSessionManager.{method_name}() requires "
                f"'session' to be a WorkflowSession instance; got "
                f"{session!r}"
            )

        allowed_from, target_status = self._TRANSITIONS[method_name]

        if session.status not in allowed_from:
            raise WorkflowSessionManagerError(
                f"WorkflowSessionManager.{method_name}() rejected: "
                f"cannot transition a WorkflowSession from "
                f"{session.status!r} to {target_status!r} (allowed "
                f"only from {sorted(allowed_from, key=lambda s: s.name)!r})"
            )

        return replace(session, status=target_status)

    def __repr__(self) -> str:
        """Return an unambiguous, informative representation useful
        for debugging/logs, mirroring the terse, no-content-dump
        style already used by ``repr()`` elsewhere in this codebase
        for orchestration objects (e.g.
        ``WorkflowExecutionCoordinator.__repr__``,
        ``WorkflowEngine.__repr__``). This class holds no instance
        state, so there is nothing further to report.
        """
        return "WorkflowSessionManager()"