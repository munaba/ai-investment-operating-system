from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from Core.exceptions import AgentError
from Orchestration.execution_context import ExecutionContext
from Orchestration.workflow import Workflow


class WorkflowSessionError(AgentError):
    """Raised when a ``WorkflowSession`` is given invalid inputs at
    construction time.

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``WorkflowError``, ``ExecutionContextError``,
    ``TaskError``, ``TaskQueueError``, ``TaskManagerError``,
    ``AutonomousSchedulerError``, ``AutonomousHostError``,
    ``AutonomousAgentError``, ``EventBusError``, and others), rather
    than deriving from the bare ``Exception`` class.
    """

    pass


class WorkflowSessionStatus(Enum):
    """Sprint 35 -- the lifecycle status a ``WorkflowSession`` value
    object may report.

    This enum only *declares* the six possible states; ``WorkflowSession``
    is a pure, immutable value object (see below) and nothing in this
    module ever transitions a ``WorkflowSession`` from one status to
    another -- no run/prepare/resume/pause/complete/fail/cancel method
    exists here or anywhere else yet. A future sprint may introduce a
    component that mutates (or, since ``WorkflowSession`` is frozen,
    more likely *replaces*) a session's status over time; this sprint
    deliberately stops short of that.

    Intentionally separate from ``Orchestration.task.TaskStatus``
    (which models an individual ``Task``'s own lifecycle),
    ``Orchestration.workflow.WorkflowStatus`` (which models a
    ``Workflow``'s own lifecycle), ``Orchestration.autonomous_agent.
    AutonomousAgentStatus`` (which models an ``AutonomousAgent``'s own
    run-loop lifecycle), and ``Agents.state.AgentState`` (which models
    per-turn call state) -- ``WorkflowSessionStatus`` models the
    lifecycle of a ``WorkflowSession`` value object specifically, and
    duplicating/overloading any of those would conflate distinct
    concepts.
    """

    CREATED = auto()
    PREPARED = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass(frozen=True)
class WorkflowSession:
    """Sprint 35 -- ``WorkflowSession``, a single immutable object
    representing ONE workflow execution.

    ``WorkflowSession`` is deliberately a *pure value object* and
    nothing more: it carries an identity, a reference to the
    ``Workflow`` being executed, the ``ExecutionContext`` that
    execution runs within, a lifecycle status, a creation timestamp,
    and metadata -- and that is all. This sprint introduces the shape
    only -- it does not wire ``WorkflowSession`` into ``Reflection``,
    ``Learning``, ``Memory``, ``Scheduler``, ``EventBus``,
    ``WorkflowEngine``, ``WorkflowExecutionCoordinator``, ``Executor``,
    ``RuntimeAnalysisPipeline``, or the Composition Root. There is no
    execution method (no ``execute()``, ``prepare()``, ``resume()``,
    ``pause()``, etc.), no scheduler/eventbus integration, no
    persistence, and no serialization anywhere in this module; the
    only methods this class defines at all are ``__post_init__`` and
    ``__hash__``.

    Instances are frozen (immutable) -- once constructed, none of a
    ``WorkflowSession``'s fields can be reassigned. ``metadata`` is
    additionally locked down (see ``__post_init__``) so that mutating
    the original mapping passed in -- or attempting to mutate
    ``session.metadata`` itself -- has no effect on this instance
    after construction. This mirrors the same "freeze the mapping
    too" pattern ``Orchestration.event_bus.Event`` already uses for
    its ``payload`` field, and that ``Orchestration.task.Task``,
    ``Orchestration.workflow.Workflow``, and ``Orchestration.
    execution_context.ExecutionContext`` already use for their own
    ``metadata`` fields.

    Attributes:
        workflow: The ``Workflow`` this session represents a single
            execution of. Must be a ``Workflow`` instance.
        execution_context: The ``ExecutionContext`` this session's
            execution runs within. Must be an ``ExecutionContext``
            instance.
        status: This session's current lifecycle status. Defaults to
            ``WorkflowSessionStatus.CREATED``. Must be a
            ``WorkflowSessionStatus`` member.
        metadata: Session-specific data. Stored internally as an
            immutable ``MappingProxyType`` snapshot of whatever
            mapping was passed in (defaults to an empty mapping).
        session_id: A ``uuid4`` string minted automatically at
            construction time (via the field's ``default_factory``)
            if the caller does not supply one -- uniquely identifying
            this specific ``WorkflowSession`` instance. Two instances
            constructed without an explicit ``session_id`` never
            collide.
        created_at: A timezone-aware UTC ``datetime`` marking when
            this session was constructed, auto-generated via the
            field's ``default_factory`` if the caller does not supply
            one.
    """

    workflow: Workflow
    execution_context: ExecutionContext
    status: WorkflowSessionStatus = WorkflowSessionStatus.CREATED
    metadata: Mapping[str, Any] = field(default_factory=dict)
    session_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        """Validate every field and freeze ``metadata`` into an
        immutable snapshot.

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.metadata``) to a different object,
        but it does nothing to stop the *contents* of a mutable
        mapping from being changed out from under this
        ``WorkflowSession`` after construction. Wrapping a
        freshly-copied ``dict`` in ``MappingProxyType`` closes that
        gap: the ``metadata`` any caller observes is guaranteed to be
        exactly what it was at construction time, for the lifetime of
        this instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        Raises:
            WorkflowSessionError: if ``session_id`` is not a non-empty
                ``str``; if ``workflow`` is not a ``Workflow``
                instance; if ``execution_context`` is not an
                ``ExecutionContext`` instance; if ``status`` is not a
                ``WorkflowSessionStatus`` member; if ``created_at`` is
                not a ``datetime``; or if ``metadata`` is not a
                ``Mapping``.
        """
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise WorkflowSessionError(
                f"WorkflowSession requires a non-empty str 'session_id'; "
                f"got {self.session_id!r}"
            )

        if not isinstance(self.workflow, Workflow):
            raise WorkflowSessionError(
                f"WorkflowSession requires 'workflow' to be a Workflow "
                f"instance; got {self.workflow!r}"
            )

        if not isinstance(self.execution_context, ExecutionContext):
            raise WorkflowSessionError(
                f"WorkflowSession requires 'execution_context' to be an "
                f"ExecutionContext instance; got {self.execution_context!r}"
            )

        if not isinstance(self.status, WorkflowSessionStatus):
            raise WorkflowSessionError(
                f"WorkflowSession requires 'status' to be a "
                f"WorkflowSessionStatus member; got {self.status!r}"
            )

        if not isinstance(self.created_at, datetime):
            raise WorkflowSessionError(
                f"WorkflowSession requires 'created_at' to be a datetime; "
                f"got {self.created_at!r}"
            )

        if not isinstance(self.metadata, Mapping):
            raise WorkflowSessionError(
                f"WorkflowSession requires 'metadata' to be a Mapping; "
                f"got {self.metadata!r}"
            )

        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``session_id`` alone.

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two ``WorkflowSession``
        instances are only ``==`` when *all* their fields match,
        ``session_id`` included. Hashing by ``session_id`` alone is
        safe precisely because of that: any two equal
        ``WorkflowSession`` instances necessarily share the same
        ``session_id``, so they are guaranteed to also share the same
        hash (the only property Python's hash/eq contract actually
        requires). A hash based on every field would additionally
        require every field to itself be hashable, which ``metadata``
        -- an immutable ``MappingProxyType`` over a ``dict`` snapshot
        -- deliberately is not (mirroring ``Orchestration.event_bus.
        Event.payload``, ``Orchestration.task.Task.metadata``,
        ``Orchestration.workflow.Workflow.metadata``, and
        ``Orchestration.execution_context.ExecutionContext.metadata``);
        ``session_id`` (a plain ``uuid4`` string, or a caller-supplied
        one) hashes cheaply and uniquely identifies this instance
        regardless.
        """
        return hash(self.session_id)