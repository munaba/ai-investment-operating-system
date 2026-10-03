from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from types import MappingProxyType
from typing import Any, Mapping, Tuple
from uuid import uuid4

from Core.exceptions import AgentError
from Orchestration.task import Task


class WorkflowError(AgentError):
    """Raised when a ``Workflow`` is given invalid inputs at
    construction time.

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``TaskError``, ``TaskQueueError``,
    ``TaskManagerError``, ``AutonomousSchedulerError``,
    ``AutonomousHostError``, ``AutonomousAgentError``,
    ``EventBusError``, and others), rather than deriving from the
    bare ``Exception`` class.
    """

    pass


class WorkflowStatus(Enum):
    """Sprint 27 -- the lifecycle status a ``Workflow`` value object
    may report.

    This enum only *declares* the five possible states; ``Workflow``
    is a pure, immutable value object (see below) and nothing in this
    module ever transitions a ``Workflow`` from one status to another
    -- no run/start/complete/fail method exists here or anywhere else
    yet. A future sprint may introduce a component that mutates (or,
    since ``Workflow`` is frozen, more likely *replaces*) a workflow's
    status over time; this sprint deliberately stops short of that.

    Intentionally separate from ``Orchestration.task.TaskStatus``
    (which models an individual ``Task``'s own lifecycle),
    ``Orchestration.autonomous_agent.AutonomousAgentStatus`` (which
    models an ``AutonomousAgent``'s own run-loop lifecycle), and
    ``Agents.state.AgentState`` (which models per-turn call state) --
    ``WorkflowStatus`` models the lifecycle of a ``Workflow`` value
    object specifically, and duplicating/overloading any of those
    would conflate distinct concepts.
    """

    CREATED = auto()
    READY = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass(frozen=True)
class Workflow:
    """Sprint 27 -- ``Workflow``, the immutable description of how a
    group of ``Task`` instances is organized, that later sprints will
    build execution on top of.

    ``Workflow`` is deliberately a *pure value object* and nothing
    more: it carries a name, description, an ordered group of
    ``Task`` instances, a lifecycle status, and metadata -- and that
    is all. This sprint introduces the shape only -- it does not wire
    ``Workflow`` into ``TaskManager``, ``TaskQueue``,
    ``AutonomousScheduler``, ``AutonomousHost``, ``AutonomousAgent``,
    ``RuntimeAnalysisPipeline``, ``EventBus``, or the Composition
    Root. There is no execution method (no ``run()``, ``start()``,
    etc.), no scheduler/queue/manager integration, no dependency
    graph or task ordering logic beyond preserving whatever order the
    caller supplied, no callbacks, no retry, no timeout, no
    persistence, and no serialization anywhere in this module.

    Instances are frozen (immutable) -- once constructed, none of a
    ``Workflow``'s fields can be reassigned. ``tasks`` is stored as a
    ``tuple`` (already immutable) and ``metadata`` is additionally
    locked down (see ``__post_init__``) so that mutating the original
    mapping/sequence passed in -- or attempting to mutate
    ``workflow.metadata`` itself -- has no effect on this instance
    after construction. This mirrors the same "freeze the mapping
    too" pattern ``Orchestration.task.Task`` already uses for its own
    ``metadata`` field (and that ``Orchestration.event_bus.Event``
    uses for ``payload``).

    Duplicate tasks (by value, by ``task_id``, or the exact same
    ``Task`` instance appearing more than once) are all allowed --
    construction never deduplicates, and insertion order is always
    preserved exactly as supplied.

    Attributes:
        workflow_id: A ``uuid4`` string minted automatically at
            construction time (via the field's ``default_factory``)
            if the caller does not supply one -- uniquely identifying
            this specific ``Workflow`` instance. Two ``Workflow``
            instances constructed without an explicit ``workflow_id``
            never collide.
        name: A short, human-readable label for this workflow. Must
            be a non-empty ``str``.
        description: A longer, human-readable description of what
            this workflow represents. Must be a ``str`` (may be
            empty).
        tasks: The ordered group of ``Task`` instances this workflow
            describes. Stored internally as an immutable ``tuple``,
            in exactly the order supplied. Defaults to an empty
            tuple. Duplicates are allowed and never removed.
        status: This workflow's current lifecycle status. Defaults to
            ``WorkflowStatus.CREATED``. Must be a ``WorkflowStatus``
            member.
        metadata: Workflow-specific data. Stored internally as an
            immutable ``MappingProxyType`` snapshot of whatever
            mapping was passed in (defaults to an empty mapping).
    """

    name: str
    description: str
    tasks: Tuple[Task, ...] = field(default_factory=tuple)
    status: WorkflowStatus = WorkflowStatus.CREATED
    metadata: Mapping[str, Any] = field(default_factory=dict)
    workflow_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """Validate every field and freeze ``tasks``/``metadata`` into
        immutable snapshots.

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.tasks``/``self.metadata``) to a
        different object, but it does nothing on its own to stop a
        mutable sequence/mapping passed by the caller from being
        changed out from under this ``Workflow`` after construction,
        or to reject a non-tuple/non-``Mapping`` value outright.
        Converting ``tasks`` to a fresh ``tuple`` and wrapping a
        freshly-copied ``dict`` in ``MappingProxyType`` closes that
        gap: what any caller observes via ``workflow.tasks``/
        ``workflow.metadata`` is guaranteed to be exactly what it was
        at construction time, for the lifetime of this instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        Raises:
            WorkflowError: if ``workflow_id`` is not a non-empty
                ``str``; if ``name`` is not a non-empty ``str``; if
                ``description`` is not a ``str``; if ``tasks`` is not
                an iterable of ``Task`` instances only; if ``status``
                is not a ``WorkflowStatus`` member; or if ``metadata``
                is not a ``Mapping``.
        """
        if not isinstance(self.workflow_id, str) or not self.workflow_id.strip():
            raise WorkflowError(
                f"Workflow requires a non-empty str 'workflow_id'; got "
                f"{self.workflow_id!r}"
            )

        if not isinstance(self.name, str) or not self.name.strip():
            raise WorkflowError(
                f"Workflow requires a non-empty str 'name'; got {self.name!r}"
            )

        if not isinstance(self.description, str):
            raise WorkflowError(
                f"Workflow requires 'description' to be a str; got "
                f"{self.description!r}"
            )

        if isinstance(self.tasks, (str, bytes)) or not hasattr(self.tasks, "__iter__"):
            raise WorkflowError(
                f"Workflow requires 'tasks' to be an iterable of Task "
                f"instances; got {self.tasks!r}"
            )

        materialized_tasks = tuple(self.tasks)
        for item in materialized_tasks:
            if not isinstance(item, Task):
                raise WorkflowError(
                    f"Workflow requires every item in 'tasks' to be a Task "
                    f"instance; got {item!r}"
                )

        if not isinstance(self.status, WorkflowStatus):
            raise WorkflowError(
                f"Workflow requires 'status' to be a WorkflowStatus "
                f"member; got {self.status!r}"
            )

        if not isinstance(self.metadata, Mapping):
            raise WorkflowError(
                f"Workflow requires 'metadata' to be a Mapping; got "
                f"{self.metadata!r}"
            )

        object.__setattr__(self, "tasks", materialized_tasks)
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``workflow_id`` alone.

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two ``Workflow``
        instances are only ``==`` when *all* their fields match,
        ``workflow_id`` included. Hashing by ``workflow_id`` alone is
        safe precisely because of that: any two equal ``Workflow``
        instances necessarily share the same ``workflow_id``, so they
        are guaranteed to also share the same hash (the only property
        Python's hash/eq contract actually requires). A hash based on
        every field would additionally require every field to itself
        be hashable, which ``metadata`` -- an immutable
        ``MappingProxyType`` over a ``dict`` snapshot -- deliberately
        is not (mirroring ``Orchestration.task.Task.__hash__`` and
        ``Orchestration.event_bus.Event.payload``); ``workflow_id``
        (a plain ``uuid4`` string) hashes cheaply and uniquely
        identifies this instance regardless.
        """
        return hash(self.workflow_id)