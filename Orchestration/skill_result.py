"""SkillResult -- the standard return object for every future Skill
(Phase 5, Sprint 47).

Scope note (LOCKED baseline): this module introduces exactly one
value object and nothing more.

  1. ``SkillResultError`` -- the module's own exception type,
     following the same convention as ``TaskError``/
     ``ExecutionContextError``/``WorkflowError``/``SkillRegistryError``/
     ``SkillResolverError`` (subclasses ``Core.exceptions.AgentError``
     directly, no intermediate layer).
  2. ``SkillResult`` -- a frozen dataclass with exactly four fields:
     ``success: bool``, ``output: Any = None``,
     ``error: Optional[str] = None``, and
     ``metadata: Mapping[str, Any] = {}``. That is the entire shape.

Explicitly NOT part of this milestone: duration, latency,
token_usage, cost, provider, trace, logs, stacktrace, retry,
warnings, events, memory, workflow, executor, scheduler, runtime,
reflection, learning, agent, or host information of any kind.
``SkillResult`` knows about none of those -- it is a pure, minimal
"what did the skill produce" value object, not an execution record or
a diagnostics bundle.

No methods beyond ``__post_init__``/``__hash__`` (LOCKED design
constraint): there is no helper method, no convenience method, no
serialization, and no builder anywhere in this module -- exactly the
same minimal-methods discipline already used by
``Orchestration.task.Task``, ``Orchestration.execution_context.
ExecutionContext``, ``Orchestration.workflow.Workflow``,
``Orchestration.workflow_session.WorkflowSession``, and
``Orchestration.event_bus.Event``.

``metadata`` is frozen the same way already used throughout the
project by those five classes: a freshly-copied ``dict`` wrapped in
``types.MappingProxyType`` inside ``__post_init__``, via
``object.__setattr__`` (the one sanctioned way to set a field from
inside a frozen dataclass's own ``__post_init__``).

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError``, the stdlib ``dataclasses``,
``types.MappingProxyType``, and ``typing`` modules -- nothing else.
It is not imported by, and does not import from,
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_registry.SkillRegistry``,
``Orchestration.skill_resolver.SkillResolver``,
``Orchestration.executor.Executor``,
``Orchestration.workflow_execution_coordinator.
WorkflowExecutionCoordinator``, ``Orchestration.workflow_runtime.
WorkflowRuntime``, ``Agents.planner.Planner``, ``Orchestration.memory``,
``Orchestration.learning_loop.LearningLoop``,
``Orchestration.reflection``, ``Orchestration.autonomous_scheduler.
AutonomousScheduler``, ``Orchestration.autonomous_host.
AutonomousHost``, ``Orchestration.autonomous_agent.AutonomousAgent``,
``Orchestration.event_bus.EventBus``, or ``Core.composition_root``.
It is additive-only, standing on its own until a future sprint has
concrete ``BaseSkill.execute()`` implementations return it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional

from Core.exceptions import AgentError


class SkillResultError(AgentError):
    """Raised when ``SkillResult`` is given invalid inputs at
    construction time.

    Following the same convention as ``TaskError``/
    ``ExecutionContextError``/``WorkflowError``/``SkillRegistryError``/
    ``SkillResolverError`` (all subclass ``Core.exceptions.AgentError``
    directly). Raised by ``SkillResult.__post_init__`` for an invalid
    ``success``, ``error``, or ``metadata`` field. No other validation
    exists -- ``output`` is deliberately unconstrained (``Any``).
    """


@dataclass(frozen=True)
class SkillResult:
    """The standard, immutable return object every future ``Skill``
    will produce from ``BaseSkill.execute(context)``.

    ``SkillResult`` is a pure, passive value object and nothing more:
    it carries whether a skill run succeeded, what it produced, what
    error (if any) it failed with, and arbitrary result metadata --
    and it does nothing with any of that. It is not wired into
    ``BaseSkill``, ``SkillRegistry``, ``SkillResolver``, ``Executor``,
    ``WorkflowRuntime``, ``Planner``, ``Memory``, ``LearningLoop``,
    ``Reflection``, or the Composition Root -- this sprint introduces
    the shape only. There is no execution method, no persistence, no
    serialization, and no eventing anywhere in this module; the only
    methods this class defines at all are ``__post_init__`` and
    ``__hash__``.

    Instances are frozen (immutable) -- once constructed, none of a
    ``SkillResult``'s fields can be reassigned. ``metadata`` is
    additionally locked down (see ``__post_init__``) so that mutating
    the original mapping passed in -- or attempting to mutate
    ``result.metadata`` itself -- has no effect on this instance
    after construction. This mirrors the same "freeze the mapping
    too" pattern ``Orchestration.task.Task``,
    ``Orchestration.execution_context.ExecutionContext``,
    ``Orchestration.workflow.Workflow``,
    ``Orchestration.workflow_session.WorkflowSession``, and
    ``Orchestration.event_bus.Event`` already use for their own
    metadata/payload fields.

    Attributes:
        success: Whether the skill run succeeded. Must be a ``bool``.
        output: Whatever the skill produced. Defaults to ``None``.
            Deliberately unconstrained (``Any``) and never validated
            -- opaque to this class.
        error: An error message, if the run failed. Must be ``None``
            or a ``str``. Defaults to ``None``.
        metadata: Result-specific data. Stored internally as an
            immutable ``MappingProxyType`` snapshot of whatever
            mapping was passed in (defaults to an empty mapping).
    """

    success: bool
    output: Any = None
    error: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate ``success``, ``error``, and ``metadata``, and
        freeze ``metadata`` into an immutable snapshot.

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.metadata``) to a different object,
        but it does nothing to stop the *contents* of a mutable
        mapping from being changed out from under this
        ``SkillResult`` after construction. Wrapping a freshly-copied
        ``dict`` in ``MappingProxyType`` closes that gap: the
        ``metadata`` any caller observes is guaranteed to be exactly
        what it was at construction time, for the lifetime of this
        instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        ``output`` is never validated -- it is deliberately
        unconstrained (``Any``).

        Raises:
            SkillResultError: if ``success`` is not a ``bool``; if
                ``error`` is neither ``None`` nor a ``str``; or if
                ``metadata`` is not a ``Mapping``.
        """
        if not isinstance(self.success, bool):
            raise SkillResultError(
                f"SkillResult requires 'success' to be a bool; got "
                f"{self.success!r}"
            )

        if self.error is not None and not isinstance(self.error, str):
            raise SkillResultError(
                f"SkillResult requires 'error' to be a str or None; "
                f"got {self.error!r}"
            )

        if not isinstance(self.metadata, Mapping):
            raise SkillResultError(
                f"SkillResult requires 'metadata' to be a Mapping; "
                f"got {self.metadata!r}"
            )

        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``(success, error)`` alone.

        Unlike ``Orchestration.task.Task``/``Orchestration.
        execution_context.ExecutionContext``/``Orchestration.workflow.
        Workflow``/``Orchestration.workflow_session.WorkflowSession``
        (each of which hashes by its own unique ``*_id`` field),
        ``SkillResult`` deliberately has no identifier field at all --
        its shape is locked to exactly ``success``/``output``/
        ``error``/``metadata``. Hashing therefore falls back to the
        two fields guaranteed to be hashable: ``success`` (a ``bool``)
        and ``error`` (``None`` or a ``str``). ``metadata`` is
        excluded because it is an immutable ``MappingProxyType`` over
        a ``dict`` snapshot -- deliberately not hashable (mirroring
        ``Orchestration.event_bus.Event.payload`` and
        ``Orchestration.task.Task.metadata``) -- and ``output`` is
        excluded because it is unconstrained (``Any``) and may itself
        be an unhashable value (e.g. a ``list`` or ``dict``).

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two ``SkillResult``
        instances are only ``==`` when *all four* fields match. Two
        ``SkillResult`` instances that differ only in ``output`` or
        ``metadata`` may therefore share a hash without being equal --
        which is exactly what Python's hash/eq contract permits (it
        only requires equal objects to share a hash, never the
        reverse).
        """
        return hash((self.success, self.error))