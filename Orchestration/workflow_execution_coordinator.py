from __future__ import annotations

from Core.exceptions import AgentError
from Orchestration.execution_context import ExecutionContext
from Orchestration.executor import Executor
from Orchestration.workflow_engine import WorkflowEngine


class WorkflowExecutionCoordinatorError(AgentError):
    """Raised when ``WorkflowExecutionCoordinator`` is given invalid
    inputs, either directly or via the ``WorkflowEngine``/``Executor``
    it is asked to coordinate.

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``WorkflowEngineError``,
    ``WorkflowManagerError``, ``ExecutorError``, ``TaskError``,
    ``TaskQueueError``, ``TaskManagerError``,
    ``AutonomousSchedulerError``, ``AutonomousHostError``,
    ``AutonomousAgentError``, ``EventBusError``, and others), rather
    than deriving from the bare ``Exception`` class.
    """

    pass


class WorkflowExecutionCoordinator:
    """Sprint 33 -- Executor Decoupling (Architecture Cleanup).

    Sprint 32 bridged the Workflow/TaskManager/Executor stack
    (Subsystem B) and the Scheduler/Host/Agent stack (Subsystem A) by
    giving ``Executor`` a single ``execute_workflow()`` method that
    imported ``WorkflowEngine`` and ``ExecutionContext`` directly.
    That made ``Executor`` -- which should remain a generic,
    task-in/task-out execution component -- depend on the Workflow
    stack's preparation concerns, and created an undesired dependency
    cycle (``WorkflowEngine`` -> ``Executor`` -> ``WorkflowEngine``).

    ``WorkflowExecutionCoordinator`` restores the clean, one-way
    dependency direction:

        WorkflowEngine -> WorkflowExecutionCoordinator -> Executor

    It is a thin, stateless orchestration-layer component: the *only*
    place in the codebase that is allowed to know about both
    ``WorkflowEngine`` (workflow preparation) and ``Executor``
    (task execution) at once. Neither of those two classes knows
    about this one, or about each other -- ``Executor`` no longer
    imports ``WorkflowEngine``/``Workflow``/``ExecutionContext`` at
    all, and ``WorkflowEngine`` still never imports ``Executor`` or
    ``AutonomousHost``, exactly as Sprint 29/30 originally locked
    down.

    ``execute_workflow()`` introduces no second execution engine and
    duplicates none of ``Executor.execute()``'s loop logic -- it is
    purely: validate inputs, require a loaded workflow, call
    ``workflow_engine.prepare()`` exactly once, then delegate to
    ``executor.execute(context, iterations)`` and return that result
    unchanged. ``WorkflowEngine`` remains the sole owner of workflow
    preparation (loading/clearing/submitting ``Task`` instances);
    ``Executor`` remains the sole owner of execution (dequeuing and
    delegating to ``AutonomousHost``). This method never reaches
    inside ``TaskQueue`` directly, and never mutates
    ``Workflow.status``, ``Task.status``, or any field of the
    ``ExecutionContext`` passed in.

    This class holds no instance state of its own -- it is safe to
    reuse a single instance across any number of ``execute_workflow()``
    calls, against any combination of ``Executor``/``WorkflowEngine``
    pairs.
    """

    def execute_workflow(
        self,
        executor: Executor,
        workflow_engine: WorkflowEngine,
        context: ExecutionContext,
        iterations: int = 1,
    ) -> int:
        """Prepare the ``Workflow`` currently loaded on
        ``workflow_engine`` and execute it via ``executor``.

        Args:
            executor: the ``Executor`` that will consume the prepared
                ``Task`` instances and delegate their execution. Must
                not be ``None`` and must be an ``Executor`` instance.
            workflow_engine: the ``WorkflowEngine`` to prepare and
                whose prepared tasks will then be executed. Must not
                be ``None`` and must be a ``WorkflowEngine`` instance,
                with a ``Workflow`` currently loaded (i.e.
                ``workflow_engine.current_workflow()`` must not be
                ``None``).
            context: the ``ExecutionContext`` passed unchanged to the
                delegated ``executor.execute()`` call (and, from
                there, to every ``AutonomousHost.start()`` call it
                makes). Must not be ``None`` and must be an
                ``ExecutionContext`` instance.
            iterations: the maximum number of ``Task`` instances to
                execute, passed unchanged to the delegated
                ``executor.execute()`` call. Must be an ``int`` >= 1
                (``bool`` is rejected even though it is technically
                an ``int`` subclass). Defaults to ``1``.

        Returns:
            The number of ``Task`` instances actually executed --
            exactly what the delegated
            ``executor.execute(context, iterations)`` call returns.

        Raises:
            WorkflowExecutionCoordinatorError: if ``executor`` is
                ``None`` or is not an ``Executor`` instance; if
                ``workflow_engine`` is ``None`` or is not a
                ``WorkflowEngine`` instance; if ``context`` is
                ``None`` or is not an ``ExecutionContext`` instance;
                if ``iterations`` is not an ``int`` >= 1 (including
                when it is a ``bool``); or if ``workflow_engine`` has
                no ``Workflow`` currently loaded. None of these
                validation failures call ``workflow_engine.prepare()``
                or dequeue any ``Task``.
        """
        if executor is None:
            raise WorkflowExecutionCoordinatorError(
                "WorkflowExecutionCoordinator.execute_workflow() "
                "requires a non-None 'executor'"
            )

        if not isinstance(executor, Executor):
            raise WorkflowExecutionCoordinatorError(
                f"WorkflowExecutionCoordinator.execute_workflow() "
                f"requires 'executor' to be an Executor instance; got "
                f"{executor!r}"
            )

        if workflow_engine is None:
            raise WorkflowExecutionCoordinatorError(
                "WorkflowExecutionCoordinator.execute_workflow() "
                "requires a non-None 'workflow_engine'"
            )

        if not isinstance(workflow_engine, WorkflowEngine):
            raise WorkflowExecutionCoordinatorError(
                f"WorkflowExecutionCoordinator.execute_workflow() "
                f"requires 'workflow_engine' to be a WorkflowEngine "
                f"instance; got {workflow_engine!r}"
            )

        if context is None:
            raise WorkflowExecutionCoordinatorError(
                "WorkflowExecutionCoordinator.execute_workflow() "
                "requires a non-None 'context'"
            )

        if not isinstance(context, ExecutionContext):
            raise WorkflowExecutionCoordinatorError(
                f"WorkflowExecutionCoordinator.execute_workflow() "
                f"requires 'context' to be an ExecutionContext "
                f"instance; got {context!r}"
            )

        if (
            not isinstance(iterations, int)
            or isinstance(iterations, bool)
            or iterations < 1
        ):
            raise WorkflowExecutionCoordinatorError(
                "WorkflowExecutionCoordinator.execute_workflow() "
                f"requires 'iterations' to be an int >= 1; got "
                f"{iterations!r}"
            )

        if workflow_engine.current_workflow() is None:
            raise WorkflowExecutionCoordinatorError(
                "WorkflowExecutionCoordinator.execute_workflow() "
                "requires 'workflow_engine' to have a Workflow "
                "currently loaded; call workflow_engine.load() first"
            )

        workflow_engine.prepare()

        return executor.execute(context, iterations)

    def __repr__(self) -> str:
        """Return an unambiguous, informative representation useful
        for debugging/logs, mirroring the terse, no-content-dump
        style already used by ``repr()`` elsewhere in this codebase
        for orchestration objects (e.g. ``Executor.__repr__``,
        ``WorkflowEngine.__repr__``). This class holds no instance
        state, so there is nothing further to report.
        """
        return "WorkflowExecutionCoordinator()"