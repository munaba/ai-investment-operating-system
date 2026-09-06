from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from Core.exceptions import AgentError


class ExecutionContextError(AgentError):
    """Raised when ``ExecutionContext`` is given invalid inputs at
    construction time.

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``ExecutorError``, ``WorkflowEngineError``,
    ``WorkflowManagerError``, ``TaskError``, ``TaskQueueError``,
    ``TaskManagerError``, ``AutonomousSchedulerError``,
    ``AutonomousHostError``, ``AutonomousAgentError``,
    ``EventBusError``, and others), rather than deriving from the
    bare ``Exception`` class.
    """

    pass


@dataclass(frozen=True)
class ExecutionContext:
    """Sprint 31 -- the immutable runtime context shared across a
    single workflow execution.

    ``ExecutionContext`` is a pure, passive value object and nothing
    more: it carries the identifiers and metadata one execution needs
    to reference itself and, optionally, the task/session it is
    currently associated with -- it does not do anything with them.
    It is not wired into ``Executor``, ``WorkflowEngine``,
    ``WorkflowManager``, ``Workflow``, ``TaskManager``, ``TaskQueue``,
    ``Task``, ``AutonomousScheduler``, ``AutonomousHost``,
    ``AutonomousAgent``, ``RuntimeAnalysisPipeline``, ``EventBus``, or
    the Composition Root -- this sprint introduces the shape only.
    There is no execution method, no persistence, no serialization,
    and no eventing anywhere in this module; the only methods this
    class defines at all are ``__post_init__`` and ``__hash__``.

    Instances are frozen (immutable) -- once constructed, none of an
    ``ExecutionContext``'s fields can be reassigned. ``metadata`` is
    additionally locked down (see ``__post_init__``) so that mutating
    the original mapping passed in -- or attempting to mutate
    ``context.metadata`` itself -- has no effect on this instance
    after construction. This mirrors the same "freeze the mapping
    too" pattern ``Orchestration.event_bus.Event`` already uses for
    its ``payload`` field, and ``Orchestration.task.Task`` already
    uses for its ``metadata`` field.

    Attributes:
        workflow_id: The identifier of the workflow this execution
            belongs to. Must be a non-empty ``str``.
        task_id: The identifier of the task currently associated with
            this execution, if any. Must be a ``str`` when provided;
            ``None`` (the default) means no specific task is
            associated.
        session_id: The identifier of the session this execution
            belongs to, if any. Must be a ``str`` when provided;
            ``None`` (the default) means no session is associated.
        metadata: Execution-specific data. Stored internally as an
            immutable ``MappingProxyType`` snapshot of whatever
            mapping was passed in (defaults to an empty mapping).
        execution_id: A ``uuid4`` string minted automatically at
            construction time (via the field's ``default_factory``)
            if the caller does not supply one -- uniquely identifying
            this specific ``ExecutionContext`` instance. Two
            instances constructed without an explicit ``execution_id``
            never collide.
        created_at: A timezone-aware UTC ``datetime`` marking when
            this context was constructed, auto-generated via the
            field's ``default_factory`` if the caller does not supply
            one.
    """

    workflow_id: str
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    execution_id: str = field(default_factory=lambda: str(uuid4()))
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
        ``ExecutionContext`` after construction. Wrapping a
        freshly-copied ``dict`` in ``MappingProxyType`` closes that
        gap: the ``metadata`` any caller observes is guaranteed to be
        exactly what it was at construction time, for the lifetime of
        this instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        Raises:
            ExecutionContextError: if ``execution_id`` is not a
                non-empty ``str``; if ``workflow_id`` is not a
                non-empty ``str``; if ``task_id`` is neither ``None``
                nor a ``str``; if ``session_id`` is neither ``None``
                nor a ``str``; if ``metadata`` is not a ``Mapping``;
                or if ``created_at`` is not a ``datetime``.
        """
        if (
            not isinstance(self.execution_id, str)
            or not self.execution_id.strip()
        ):
            raise ExecutionContextError(
                f"ExecutionContext requires a non-empty str "
                f"'execution_id'; got {self.execution_id!r}"
            )

        if not isinstance(self.workflow_id, str) or not self.workflow_id.strip():
            raise ExecutionContextError(
                f"ExecutionContext requires a non-empty str "
                f"'workflow_id'; got {self.workflow_id!r}"
            )

        if self.task_id is not None and not isinstance(self.task_id, str):
            raise ExecutionContextError(
                f"ExecutionContext requires 'task_id' to be a str or "
                f"None; got {self.task_id!r}"
            )

        if self.session_id is not None and not isinstance(
            self.session_id, str
        ):
            raise ExecutionContextError(
                f"ExecutionContext requires 'session_id' to be a str "
                f"or None; got {self.session_id!r}"
            )

        if not isinstance(self.metadata, Mapping):
            raise ExecutionContextError(
                f"ExecutionContext requires 'metadata' to be a "
                f"Mapping; got {self.metadata!r}"
            )

        if not isinstance(self.created_at, datetime):
            raise ExecutionContextError(
                f"ExecutionContext requires 'created_at' to be a "
                f"datetime; got {self.created_at!r}"
            )

        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``execution_id`` alone.

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two ``ExecutionContext``
        instances are only ``==`` when *all* their fields match,
        ``execution_id`` included. Hashing by ``execution_id`` alone
        is safe precisely because of that: any two equal
        ``ExecutionContext`` instances necessarily share the same
        ``execution_id``, so they are guaranteed to also share the
        same hash (the only property Python's hash/eq contract
        actually requires). A hash based on every field would
        additionally require every field to itself be hashable, which
        ``metadata`` -- an immutable ``MappingProxyType`` over a
        ``dict`` snapshot -- deliberately is not (mirroring
        ``Orchestration.event_bus.Event.payload`` and
        ``Orchestration.task.Task.metadata``); ``execution_id`` (a
        plain ``uuid4`` string, or a caller-supplied one) hashes
        cheaply and uniquely identifies this instance regardless.
        """
        return hash(self.execution_id)