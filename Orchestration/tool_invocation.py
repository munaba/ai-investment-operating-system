"""ToolInvocation -- the immutable boundary contract between Skill and
Tool execution (Phase 8, Sprint 93).

Scope note (LOCKED baseline): this module introduces exactly one
value object and nothing more.

  1. ``ToolInvocationError`` -- the module's own exception type,
     following the same convention as ``ToolResultError``/
     ``SkillResultError``/``TaskError``/``ExecutionContextError``/
     ``WorkflowError``/``SkillRegistryError``/``SkillResolverError``
     (subclasses ``Core.exceptions.AgentError`` directly, no
     intermediate layer).
  2. ``ToolInvocation`` -- a frozen dataclass with exactly three
     fields: ``tool_name: str``, ``context: Any``, and
     ``metadata: Mapping[str, Any]``. That is the entire shape.

This sits one step ahead of ``Orchestration.tool_result.ToolResult``
(Sprint 86) in the same layer of the architecture:

    Planner -> Skill -> Tool -> Services / Repository / API

Where ``ToolResult`` is the immutable record of what a Tool
*produced*, ``ToolInvocation`` is the immutable record of what a
Skill is *asking* a Tool to do -- the request side of the same
boundary.

This sprint defines the shape only. It does not wire
``ToolInvocation`` into ``BaseSkill``, ``BaseTool``, any concrete
Skill or Tool, ``ToolRegistry``, ``ToolResolver``, ``ToolManager``,
``Executor``, ``Planner``, ``WorkflowRuntime``, or the Composition
Root, and it does not execute anything.

Explicitly NOT part of this milestone: duration, latency, timeout,
retry, priority, caching, logging, tracing, events, memory, workflow,
executor, scheduler, runtime, reflection, learning, agent, host, or
any execution semantics of any kind. ``ToolInvocation`` knows about
none of those -- it is a pure, minimal "what is being asked for"
value object, not an execution record, a dispatcher, or a
diagnostics bundle.

No methods beyond ``__post_init__``/``__hash__`` (LOCKED design
constraint): there is no helper method, no convenience method, no
serialization, and no builder anywhere in this module -- exactly the
same minimal-methods discipline already used by
``Orchestration.tool_result.ToolResult``,
``Orchestration.skill_result.SkillResult``, ``Orchestration.task.
Task``, ``Orchestration.execution_context.ExecutionContext``,
``Orchestration.workflow.Workflow``, ``Orchestration.workflow_session.
WorkflowSession``, and ``Orchestration.event_bus.Event``.

``metadata`` is frozen the same way already used throughout the
project by those classes: a freshly-copied ``dict`` wrapped in
``types.MappingProxyType`` inside ``__post_init__``, via
``object.__setattr__`` (the one sanctioned way to set a field from
inside a frozen dataclass's own ``__post_init__``).

``context`` is deliberately unconstrained (``Any``) and its identity
is preserved exactly as passed in -- this sprint's contract validates
only ``tool_name`` and ``metadata``. ``context`` is never validated
and never copied.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError``, the stdlib ``dataclasses``,
``types.MappingProxyType``, and ``typing`` modules -- nothing else.
It is not imported by, and does not import from,
``Orchestration.base_tool.BaseTool``,
``Orchestration.base_skill.BaseSkill``,
``Orchestration.tool_result.ToolResult``,
``Orchestration.skill_result.SkillResult``,
``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.tool_resolver.ToolResolver``,
``Orchestration.tool_manager.ToolManager``,
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
It is additive-only, standing on its own until a future sprint wires
it into Skill/Tool execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from Core.exceptions import AgentError


class ToolInvocationError(AgentError):
    """Raised when ``ToolInvocation`` is given invalid inputs at
    construction time.

    Following the same convention as ``ToolResultError``/
    ``SkillResultError``/``TaskError``/``ExecutionContextError``/
    ``WorkflowError``/``SkillRegistryError``/``SkillResolverError``
    (all subclass ``Core.exceptions.AgentError`` directly). Raised by
    ``ToolInvocation.__post_init__`` for an invalid ``tool_name`` or
    ``metadata`` field. No other validation exists -- ``context`` is
    deliberately unconstrained (``Any``).
    """


@dataclass(frozen=True)
class ToolInvocation:
    """The immutable boundary contract every future Skill will use to
    ask a Tool to run.

    ``ToolInvocation`` is a pure, passive value object and nothing
    more: it carries which tool is being invoked, the context to
    invoke it with, and arbitrary invocation metadata -- and it does
    nothing with any of that. It is not wired into ``BaseSkill``,
    ``BaseTool``, any concrete Skill or Tool, ``ToolRegistry``,
    ``ToolResolver``, ``ToolManager``, ``Executor``,
    ``WorkflowRuntime``, ``Planner``, ``Memory``, ``LearningLoop``,
    ``Reflection``, or the Composition Root -- this sprint introduces
    the shape only. There is no execution method, no dispatch, no
    persistence, no serialization, and no eventing anywhere in this
    module; the only methods this class defines at all are
    ``__post_init__`` and ``__hash__``.

    Instances are frozen (immutable) -- once constructed, none of a
    ``ToolInvocation``'s fields can be reassigned. ``metadata`` is
    additionally locked down (see ``__post_init__``) so that mutating
    the original mapping passed in -- or attempting to mutate
    ``invocation.metadata`` itself -- has no effect on this instance
    after construction. This mirrors the same "freeze the mapping
    too" pattern ``Orchestration.tool_result.ToolResult``,
    ``Orchestration.skill_result.SkillResult``, ``Orchestration.task.
    Task``, ``Orchestration.execution_context.ExecutionContext``,
    ``Orchestration.workflow.Workflow``, ``Orchestration.
    workflow_session.WorkflowSession``, and ``Orchestration.
    event_bus.Event`` already use for their own metadata/payload
    fields.

    Attributes:
        tool_name: Which tool is being invoked. Must be a non-empty,
            non-whitespace-only ``str``.
        context: Whatever the tool should be invoked with.
            Deliberately unconstrained (``Any``), never validated,
            and never copied -- identity is preserved exactly as
            passed in.
        metadata: Invocation-specific data. Stored internally as an
            immutable ``MappingProxyType`` snapshot of whatever
            mapping was passed in.
    """

    tool_name: str
    context: Any
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Validate ``tool_name`` and ``metadata``, and freeze
        ``metadata`` into an immutable snapshot.

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.metadata``) to a different object,
        but it does nothing to stop the *contents* of a mutable
        mapping from being changed out from under this
        ``ToolInvocation`` after construction. Wrapping a
        freshly-copied ``dict`` in ``MappingProxyType`` closes that
        gap: the ``metadata`` any caller observes is guaranteed to be
        exactly what it was at construction time, for the lifetime of
        this instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        ``context`` is never validated and never copied -- it is
        deliberately unconstrained (``Any``) and its identity is
        preserved exactly as passed in.

        Raises:
            ToolInvocationError: if ``tool_name`` is not a ``str``,
                is empty, or is whitespace-only; or if ``metadata``
                is not a ``Mapping``.
        """
        if not isinstance(self.tool_name, str):
            raise ToolInvocationError(
                f"ToolInvocation requires 'tool_name' to be a str; got "
                f"{self.tool_name!r}"
            )

        if not self.tool_name.strip():
            raise ToolInvocationError(
                "ToolInvocation requires 'tool_name' to be non-empty and "
                "not whitespace-only"
            )

        if not isinstance(self.metadata, Mapping):
            raise ToolInvocationError(
                f"ToolInvocation requires 'metadata' to be a Mapping; "
                f"got {self.metadata!r}"
            )

        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``tool_name`` alone.

        ``context`` is excluded because it is unconstrained (``Any``)
        and may itself be an unhashable value (e.g. a ``list`` or
        ``dict``). ``metadata`` is excluded because it is an
        immutable ``MappingProxyType`` over a ``dict`` snapshot --
        deliberately not hashable (mirroring
        ``Orchestration.tool_result.ToolResult.metadata`` and
        ``Orchestration.task.Task.metadata``) -- so neither can
        safely participate in the hash.

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two ``ToolInvocation``
        instances are only ``==`` when *all three* fields match. Two
        ``ToolInvocation`` instances that differ only in ``context``
        or ``metadata`` may therefore share a hash without being
        equal -- which is exactly what Python's hash/eq contract
        permits (it only requires equal objects to share a hash,
        never the reverse).
        """
        return hash(self.tool_name)