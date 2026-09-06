from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from Core.exceptions import AgentError


class TaskError(AgentError):
    """Raised when a ``Task`` is given invalid inputs at construction
    time.

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``AutonomousSchedulerError``,
    ``AutonomousHostError``, ``AutonomousAgentError``,
    ``EventBusError``, and others), rather than deriving from the bare
    ``Exception`` class.
    """

    pass


class TaskStatus(Enum):
    """Sprint 24 -- the lifecycle status a ``Task`` value object may
    report.

    This enum only *declares* the five possible states; ``Task`` is a
    pure, immutable value object (see below) and nothing in this
    module ever transitions a ``Task`` from one status to another --
    no run/start/complete/fail/cancel method exists here or anywhere
    else yet. A future sprint may introduce a component that mutates
    (or, since ``Task`` is frozen, more likely *replaces*) a task's
    status over time; this sprint deliberately stops short of that.

    Intentionally separate from ``Orchestration.autonomous_agent.
    AutonomousAgentStatus`` (which models an ``AutonomousAgent``'s own
    run-loop lifecycle) and from ``Agents.state.AgentState`` (which
    models per-turn call state) -- ``TaskStatus`` models the lifecycle
    of a ``Task`` value object specifically, and duplicating/
    overloading either existing enum would conflate three different
    concepts.
    """

    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass(frozen=True)
class Task:
    """Sprint 24 -- ``Task``, the execution unit AIOS will build on
    top of in future sprints.

    ``Task`` is deliberately a *pure value object* and nothing more:
    it carries data describing one unit of work and its current
    lifecycle status, and that is all. This sprint introduces the
    shape only -- it does not wire ``Task`` into
    ``AutonomousScheduler``, ``AutonomousHost``, ``AutonomousAgent``,
    ``RuntimeAnalysisPipeline``, ``GoalPlanner``, ``EventBus``, or the
    Composition Root. There is no execution method (no ``run()``,
    ``start()``, ``cancel()``, etc.), no scheduler/queue integration,
    no workflow, no callbacks, no retry, no timeout, no persistence,
    and no serialization anywhere in this module.

    Instances are frozen (immutable) -- once constructed, none of a
    ``Task``'s fields can be reassigned. ``metadata`` is additionally
    locked down (see ``__post_init__``) so that mutating the original
    mapping passed in -- or attempting to mutate ``task.metadata``
    itself -- has no effect on this instance after construction. This
    mirrors the same "freeze the mapping too" pattern
    ``Orchestration.event_bus.Event`` already uses for its ``payload``
    field, and the same "frozen dataclass, immutable snapshot fields"
    pattern ``Orchestration.autonomous_scheduler.SchedulerJob`` already
    uses for queued work.

    Attributes:
        task_id: A ``uuid4`` string minted automatically at
            construction time (via the field's ``default_factory``)
            if the caller does not supply one -- uniquely identifying
            this specific ``Task`` instance. Two ``Task`` instances
            constructed without an explicit ``task_id`` never collide.
        name: A short, human-readable label for this task. Must be a
            non-empty ``str``.
        description: A longer, human-readable description of what
            this task represents. Must be a ``str`` (may be empty).
        status: This task's current lifecycle status. Defaults to
            ``TaskStatus.PENDING``. Must be a ``TaskStatus`` member.
        metadata: Task-specific data. Stored internally as an
            immutable ``MappingProxyType`` snapshot of whatever
            mapping was passed in (defaults to an empty mapping).
    """

    name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    metadata: Mapping[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate every field and freeze ``metadata`` into an
        immutable snapshot.

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.metadata``) to a different object,
        but it does nothing to stop the *contents* of a mutable
        mapping from being changed out from under this ``Task`` after
        construction. Wrapping a freshly-copied ``dict`` in
        ``MappingProxyType`` closes that gap: the ``metadata`` any
        caller observes is guaranteed to be exactly what it was at
        construction time, for the lifetime of this instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        Raises:
            TaskError: if ``task_id`` is not a non-empty ``str``; if
                ``name`` is not a non-empty ``str``; if ``description``
                is not a ``str``; if ``status`` is not a
                ``TaskStatus`` member; or if ``metadata`` is not a
                ``Mapping``.
        """
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise TaskError(
                f"Task requires a non-empty str 'task_id'; got "
                f"{self.task_id!r}"
            )

        if not isinstance(self.name, str) or not self.name.strip():
            raise TaskError(
                f"Task requires a non-empty str 'name'; got {self.name!r}"
            )

        if not isinstance(self.description, str):
            raise TaskError(
                f"Task requires 'description' to be a str; got "
                f"{self.description!r}"
            )

        if not isinstance(self.status, TaskStatus):
            raise TaskError(
                f"Task requires 'status' to be a TaskStatus member; got "
                f"{self.status!r}"
            )

        if not isinstance(self.metadata, Mapping):
            raise TaskError(
                f"Task requires 'metadata' to be a Mapping; got "
                f"{self.metadata!r}"
            )

        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``task_id`` alone.

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two ``Task`` instances
        are only ``==`` when *all* their fields match, ``task_id``
        included. Hashing by ``task_id`` alone is safe precisely
        because of that: any two equal ``Task`` instances necessarily
        share the same ``task_id``, so they are guaranteed to also
        share the same hash (the only property Python's hash/eq
        contract actually requires). A hash based on every field
        would additionally require every field to itself be hashable,
        which ``metadata`` -- an immutable ``MappingProxyType`` over a
        ``dict`` snapshot -- deliberately is not (mirroring
        ``Orchestration.event_bus.Event.payload``); ``task_id`` (a
        plain ``uuid4`` string) hashes cheaply and uniquely identifies
        this instance regardless.
        """
        return hash(self.task_id)