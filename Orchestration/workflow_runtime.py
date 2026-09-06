from __future__ import annotations

from typing import Any, Mapping, Optional

from Core.exceptions import AgentError
from Orchestration.event_bus import Event, EventBus
from Orchestration.execution_context import ExecutionContext
from Orchestration.executor import Executor
from Orchestration.workflow import Workflow
from Orchestration.workflow_execution_coordinator import (
    WorkflowExecutionCoordinator,
)
from Orchestration.workflow_engine import WorkflowEngine
from Orchestration.workflow_session import WorkflowSession
from Orchestration.workflow_session_manager import WorkflowSessionManager


class WorkflowRuntimeError(AgentError):
    """Raised when ``WorkflowRuntime`` is given invalid inputs at
    construction time.

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``WorkflowSessionManagerError``,
    ``WorkflowSessionError``, ``WorkflowExecutionCoordinatorError``,
    ``WorkflowEngineError``, ``ExecutorError``, ``WorkflowError``,
    ``TaskError``, ``TaskQueueError``, ``TaskManagerError``,
    ``AutonomousSchedulerError``, ``AutonomousHostError``,
    ``AutonomousAgentError``, ``EventBusError``, and others), rather
    than deriving from the bare ``Exception`` class.

    ``run()`` deliberately does *not* wrap failures raised by its
    four collaborators in ``WorkflowRuntimeError`` -- a
    ``WorkflowSessionManagerError`` from ``session_manager``, a
    ``WorkflowEngineError`` from ``workflow_engine``, a
    ``WorkflowExecutionCoordinatorError`` (or whatever the underlying
    execution failure was) from ``coordinator``, all propagate
    unchanged, exactly as the Sprint 37 spec's "re-raise original
    exception" step requires. ``WorkflowRuntimeError`` is reserved for
    this class's own constructor validation only.
    """

    pass


class WorkflowRuntime:
    """Sprint 37 -- the runtime layer that actually drives one
    ``Workflow`` through its full, end-to-end execution lifecycle.

    Every piece this sprint needed already existed: ``WorkflowSession``
    (Sprint 35) is the immutable execution record, ``WorkflowSession
    Manager`` (Sprint 36) owns its lifecycle transitions,
    ``WorkflowEngine`` owns workflow preparation, ``WorkflowExecution
    Coordinator`` owns execution orchestration, and ``Executor`` owns
    task execution -- but nothing tied all five together into one
    call. ``WorkflowRuntime`` is that integration: a thin,
    stateless orchestration-layer component that owns *only* the
    sequence in which its four collaborators are called, and
    delegates every actual unit of work to exactly one of them.

    ``WorkflowRuntime`` performs no lifecycle logic itself (every
    status transition is still decided and performed by
    ``WorkflowSessionManager``), no workflow preparation itself
    (``WorkflowEngine.prepare()`` is only ever reached indirectly, via
    ``coordinator.execute_workflow()`` -- this class calls
    ``workflow_engine.load()`` and nothing else on it directly), no
    execution-orchestration logic itself (``coordinator.
    execute_workflow()`` is called exactly once and its result/
    exception is used as-is, never duplicated or re-implemented), and
    no task execution itself (``Executor.execute()`` is never called
    directly -- only indirectly, via the coordinator). It never
    imports or references ``Orchestration.task_queue.TaskQueue`` or
    ``Orchestration.task_manager.TaskManager`` -- those remain
    ``WorkflowEngine``'s and ``Executor``'s own concern.

    ``run()`` performs exactly this sequence, and nothing more:

        1. ``session_manager.create(workflow, execution_context,
           metadata=metadata)`` -> a ``CREATED`` ``WorkflowSession``.
        2. ``session_manager.prepare(session)`` -> a ``PREPARED``
           ``WorkflowSession``.
        3. ``workflow_engine.load(workflow)``.
        4. ``coordinator.execute_workflow(executor, workflow_engine,
           execution_context, iterations)``.
        5. If step 4 succeeds: ``session_manager.start(session)``,
           then ``session_manager.complete(session)`` -- the
           ``COMPLETED`` session is returned.
        6. If step 4 raises: ``session_manager.start(session)``, then
           ``session_manager.fail(session)`` -- the original exception
           is then re-raised unchanged (nothing is returned).

    This class holds no instance state beyond the four collaborators
    it was constructed with -- it is safe to reuse a single instance
    across any number of ``run()`` calls, against any combination of
    ``Workflow``/``ExecutionContext`` inputs.
    """

    def __init__(
        self,
        session_manager: WorkflowSessionManager,
        workflow_engine: WorkflowEngine,
        coordinator: WorkflowExecutionCoordinator,
        executor: Executor,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        """Construct a ``WorkflowRuntime`` bound to its four
        execution collaborators, plus an ``EventBus`` (Sprint 38) it
        publishes ``run()``'s lifecycle events to.

        Args:
            session_manager: owns ``WorkflowSession`` lifecycle
                transitions. Must not be ``None`` and must be a
                ``WorkflowSessionManager`` instance.
            workflow_engine: owns workflow preparation. Must not be
                ``None`` and must be a ``WorkflowEngine`` instance.
            coordinator: owns execution orchestration. Must not be
                ``None`` and must be a ``WorkflowExecutionCoordinator``
                instance.
            executor: owns task execution. Must not be ``None`` and
                must be an ``Executor`` instance.
            event_bus: the ``EventBus`` ``run()`` publishes
                ``"runtime.started"``/``"runtime.completed"``/
                ``"runtime.failed"`` events to. Defaults to ``None``,
                in which case a brand-new, independent ``EventBus()``
                is created for this instance (never a shared
                singleton). If provided, it must be an ``EventBus``
                instance -- it is used as-is, never wrapped or
                replaced.

        Raises:
            WorkflowRuntimeError: if any of the four collaborator
                arguments is ``None`` or is not an instance of its
                required type, or if ``event_bus`` is provided but is
                not an ``EventBus`` instance.
        """
        if session_manager is None:
            raise WorkflowRuntimeError(
                "WorkflowRuntime requires a non-None 'session_manager'"
            )

        if not isinstance(session_manager, WorkflowSessionManager):
            raise WorkflowRuntimeError(
                f"WorkflowRuntime requires 'session_manager' to be a "
                f"WorkflowSessionManager instance; got {session_manager!r}"
            )

        if workflow_engine is None:
            raise WorkflowRuntimeError(
                "WorkflowRuntime requires a non-None 'workflow_engine'"
            )

        if not isinstance(workflow_engine, WorkflowEngine):
            raise WorkflowRuntimeError(
                f"WorkflowRuntime requires 'workflow_engine' to be a "
                f"WorkflowEngine instance; got {workflow_engine!r}"
            )

        if coordinator is None:
            raise WorkflowRuntimeError(
                "WorkflowRuntime requires a non-None 'coordinator'"
            )

        if not isinstance(coordinator, WorkflowExecutionCoordinator):
            raise WorkflowRuntimeError(
                f"WorkflowRuntime requires 'coordinator' to be a "
                f"WorkflowExecutionCoordinator instance; got "
                f"{coordinator!r}"
            )

        if executor is None:
            raise WorkflowRuntimeError(
                "WorkflowRuntime requires a non-None 'executor'"
            )

        if not isinstance(executor, Executor):
            raise WorkflowRuntimeError(
                f"WorkflowRuntime requires 'executor' to be an Executor "
                f"instance; got {executor!r}"
            )

        if event_bus is not None and not isinstance(event_bus, EventBus):
            raise WorkflowRuntimeError(
                f"WorkflowRuntime requires 'event_bus' to be an EventBus "
                f"instance when provided; got {event_bus!r}"
            )

        self._session_manager: WorkflowSessionManager = session_manager
        self._workflow_engine: WorkflowEngine = workflow_engine
        self._coordinator: WorkflowExecutionCoordinator = coordinator
        self._executor: Executor = executor
        self._event_bus: EventBus = event_bus if event_bus is not None else EventBus()

    def run(
        self,
        workflow: Workflow,
        execution_context: ExecutionContext,
        iterations: int = 1,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> WorkflowSession:
        """Drive ``workflow`` through one full, end-to-end execution
        lifecycle and return the resulting ``WorkflowSession``.

        Args:
            workflow: the ``Workflow`` to run. Passed unchanged to
                ``session_manager.create()`` and
                ``workflow_engine.load()``.
            execution_context: the ``ExecutionContext`` this run
                executes within. Passed unchanged to
                ``session_manager.create()`` and
                ``coordinator.execute_workflow()``.
            iterations: the maximum number of ``Task`` instances to
                execute, forwarded unchanged to
                ``coordinator.execute_workflow()``. Defaults to ``1``.
            metadata: optional session-specific data, forwarded
                unchanged to ``session_manager.create()``. Defaults to
                ``None``.

        Returns:
            The ``WorkflowSession`` produced by this run, with
            ``status == WorkflowSessionStatus.COMPLETED``, once
            ``coordinator.execute_workflow()`` succeeds.

        Raises:
            Whatever ``session_manager.create()`` raises (e.g.
                ``WorkflowSessionManagerError``) if session creation
                fails -- nothing further is attempted.
            Whatever ``session_manager.prepare()`` raises if
                preparation of the session's own status fails --
                nothing further is attempted.
            Whatever ``workflow_engine.load()`` raises if loading the
                workflow fails -- nothing further is attempted.
            The original exception raised by
                ``coordinator.execute_workflow()`` -- re-raised
                unchanged, after this run's session has been moved to
                ``RUNNING`` (via ``session_manager.start()``) and then
                ``FAILED`` (via ``session_manager.fail()``).
        """
        session = self._session_manager.create(
            workflow, execution_context, metadata=metadata
        )
        session = self._session_manager.prepare(session)

        self._workflow_engine.load(workflow)

        identity_payload = {
            "workflow_id": execution_context.workflow_id,
            "session_id": session.session_id,
            "execution_id": execution_context.execution_id,
        }

        self._event_bus.publish(
            Event(
                event_name="runtime.started",
                source="WorkflowRuntime",
                payload=identity_payload,
            )
        )

        try:
            self._coordinator.execute_workflow(
                self._executor,
                self._workflow_engine,
                execution_context,
                iterations,
            )
        except Exception as exc:
            session = self._session_manager.start(session)
            session = self._session_manager.fail(session)
            self._event_bus.publish(
                Event(
                    event_name="runtime.failed",
                    source="WorkflowRuntime",
                    payload={
                        **identity_payload,
                        "exception_type": type(exc).__name__,
                    },
                )
            )
            raise

        session = self._session_manager.start(session)
        session = self._session_manager.complete(session)
        self._event_bus.publish(
            Event(
                event_name="runtime.completed",
                source="WorkflowRuntime",
                payload=identity_payload,
            )
        )
        return session

    def __repr__(self) -> str:
        """Return an unambiguous, informative representation useful
        for debugging/logs, mirroring the terse, no-content-dump
        style already used by ``repr()`` elsewhere in this codebase
        for orchestration objects (e.g.
        ``WorkflowExecutionCoordinator.__repr__``,
        ``WorkflowSessionManager.__repr__``). This class holds no
        state beyond its four collaborators, so there is nothing
        further to report.
        """
        return "WorkflowRuntime()"