"""ToolResult -- the standard return object for every future Tool
(Phase 8, Sprint 86).

Scope note (LOCKED baseline): this module introduces exactly one
value object and nothing more.

  1. ``ToolResultError`` -- the module's own exception type,
     following the same convention as ``SkillResultError``/
     ``TaskError``/``ExecutionContextError``/``WorkflowError``/
     ``SkillRegistryError``/``SkillResolverError`` (subclasses
     ``Core.exceptions.AgentError`` directly, no intermediate layer).
  2. ``ToolResult`` -- a frozen dataclass with exactly four fields:
     ``success: bool``, ``output: Any``, ``error: Any``, and
     ``metadata: Mapping[str, Any]``. That is the entire shape.

This mirrors ``Orchestration.skill_result.SkillResult`` (Sprint 47)
exactly, one layer down the architecture:

    Planner -> Skill -> Tool -> Services / Repository / API

This sprint defines the shape only. It does not wire ``ToolResult``
into ``BaseTool``, any concrete Tool, ``ToolRegistry``,
``ToolResolver``, ``Runtime``, ``Workflow``, ``Executor``, ``Planner``,
``Skill``, or the Composition Root -- ``Orchestration.base_tool.
BaseTool`` (this same sprint) only updates its ``execute()`` contract
to state that it returns ``ToolResult``; no concrete Tool exists yet
and none is created here.

Explicitly NOT part of this milestone: duration, latency,
token_usage, cost, provider, trace, logs, stacktrace, retry,
warnings, events, memory, workflow, executor, scheduler, runtime,
reflection, learning, agent, or host information of any kind.
``ToolResult`` knows about none of those -- it is a pure, minimal
"what did the tool produce" value object, not an execution record or
a diagnostics bundle.

No methods beyond ``__post_init__``/``__hash__`` (LOCKED design
constraint): there is no helper method, no convenience method, no
serialization, and no builder anywhere in this module -- exactly the
same minimal-methods discipline already used by
``Orchestration.skill_result.SkillResult``,
``Orchestration.task.Task``, ``Orchestration.execution_context.
ExecutionContext``, ``Orchestration.workflow.Workflow``,
``Orchestration.workflow_session.WorkflowSession``, and
``Orchestration.event_bus.Event``.

``metadata`` is frozen the same way already used throughout the
project by those classes: a freshly-copied ``dict`` wrapped in
``types.MappingProxyType`` inside ``__post_init__``, via
``object.__setattr__`` (the one sanctioned way to set a field from
inside a frozen dataclass's own ``__post_init__``).

``error`` is deliberately unconstrained (``Any``, unlike
``SkillResult.error``, which is ``Optional[str]``) -- this sprint's
contract validates only ``success`` and ``metadata``. ``output`` is
also unconstrained and never validated, exactly as in ``SkillResult``.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError``, the stdlib ``dataclasses``,
``types.MappingProxyType``, and ``typing`` modules -- nothing else.
It is not imported by, and does not import from,
``Orchestration.base_tool.BaseTool``,
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``,
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
concrete ``BaseTool.execute()`` implementations return it.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from Core.exceptions import AgentError


class ToolResultError(AgentError):
    """Raised when ``ToolResult`` is given invalid inputs at
    construction time.

    Following the same convention as ``SkillResultError``/
    ``TaskError``/``ExecutionContextError``/``WorkflowError``/
    ``SkillRegistryError``/``SkillResolverError`` (all subclass
    ``Core.exceptions.AgentError`` directly). Raised by
    ``ToolResult.__post_init__`` for an invalid ``success`` or
    ``metadata`` field. No other validation exists -- ``output`` and
    ``error`` are deliberately unconstrained (``Any``).
    """


@dataclass(frozen=True)
class ToolResult:
    """The standard, immutable return object every future ``Tool``
    will produce from ``BaseTool.execute(context)``.

    ``ToolResult`` is a pure, passive value object and nothing more:
    it carries whether a tool run succeeded, what it produced, what
    error (if any) it failed with, and arbitrary result metadata --
    and it does nothing with any of that. It is not wired into
    ``BaseTool``, any concrete Tool, ``ToolRegistry``,
    ``ToolResolver``, ``Executor``, ``WorkflowRuntime``, ``Planner``,
    ``Memory``, ``LearningLoop``, ``Reflection``, or the Composition
    Root -- this sprint introduces the shape only. There is no
    execution method, no persistence, no serialization, and no
    eventing anywhere in this module; the only methods this class
    defines at all are ``__post_init__`` and ``__hash__``.

    Instances are frozen (immutable) -- once constructed, none of a
    ``ToolResult``'s fields can be reassigned. ``metadata`` is
    additionally locked down (see ``__post_init__``) so that mutating
    the original mapping passed in -- or attempting to mutate
    ``result.metadata`` itself -- has no effect on this instance
    after construction. This mirrors the same "freeze the mapping
    too" pattern ``Orchestration.skill_result.SkillResult``,
    ``Orchestration.task.Task``, ``Orchestration.execution_context.
    ExecutionContext``, ``Orchestration.workflow.Workflow``,
    ``Orchestration.workflow_session.WorkflowSession``, and
    ``Orchestration.event_bus.Event`` already use for their own
    metadata/payload fields.

    Attributes:
        success: Whether the tool run succeeded. Must be a ``bool``.
        output: Whatever the tool produced. Deliberately
            unconstrained (``Any``) and never validated -- opaque to
            this class.
        error: An error value, if the run failed. Deliberately
            unconstrained (``Any``) and never validated -- opaque to
            this class.
        metadata: Result-specific data. Stored internally as an
            immutable ``MappingProxyType`` snapshot of whatever
            mapping was passed in.
    """

    success: bool
    output: Any
    error: Any
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Validate ``success`` and ``metadata``, and freeze
        ``metadata`` into an immutable snapshot.

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.metadata``) to a different object,
        but it does nothing to stop the *contents* of a mutable
        mapping from being changed out from under this
        ``ToolResult`` after construction. Wrapping a freshly-copied
        ``dict`` in ``MappingProxyType`` closes that gap: the
        ``metadata`` any caller observes is guaranteed to be exactly
        what it was at construction time, for the lifetime of this
        instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        ``output`` and ``error`` are never validated -- both are
        deliberately unconstrained (``Any``).

        Raises:
            ToolResultError: if ``success`` is not a ``bool``; or if
                ``metadata`` is not a ``Mapping``.
        """
        if not isinstance(self.success, bool):
            raise ToolResultError(
                f"ToolResult requires 'success' to be a bool; got "
                f"{self.success!r}"
            )

        if not isinstance(self.metadata, Mapping):
            raise ToolResultError(
                f"ToolResult requires 'metadata' to be a Mapping; "
                f"got {self.metadata!r}"
            )

        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``success`` alone.

        Unlike ``Orchestration.skill_result.SkillResult`` (which
        hashes by ``(success, error)``), ``ToolResult`` hashes by
        ``success`` alone -- ``error`` is unconstrained (``Any``) and
        may itself be unhashable (e.g. a ``list`` or ``dict``), so it
        cannot safely participate in the hash. ``metadata`` is
        excluded because it is an immutable ``MappingProxyType`` over
        a ``dict`` snapshot -- deliberately not hashable (mirroring
        ``Orchestration.event_bus.Event.payload`` and
        ``Orchestration.task.Task.metadata``) -- and ``output`` is
        excluded because it is unconstrained (``Any``) and may itself
        be an unhashable value.

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two ``ToolResult``
        instances are only ``==`` when *all four* fields match. Two
        ``ToolResult`` instances that differ only in ``output``,
        ``error``, or ``metadata`` may therefore share a hash without
        being equal -- which is exactly what Python's hash/eq
        contract permits (it only requires equal objects to share a
        hash, never the reverse).
        """
        return hash(self.success)