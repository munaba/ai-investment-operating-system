"""Capability -- the immutable vocabulary a future Planner will use to
reason about available abilities (Phase 5, Sprint 53).

Scope note (LOCKED baseline): this module introduces exactly two
things and nothing more.

  1. ``CapabilityError`` -- the module's own exception type,
     following the same convention as ``TaskError``/
     ``ExecutionContextError``/``WorkflowError``/``SkillResultError``/
     ``ToolContextError``/``SkillContextError`` (subclasses
     ``Core.exceptions.AgentError`` directly, no intermediate layer).
  2. ``Capability`` -- a frozen dataclass with exactly four fields:
     ``name: str``, ``description: str``,
     ``metadata: Mapping[str, Any]``, and ``tags: Tuple[str, ...]``.
     That is the entire shape.

A ``Capability`` describes *what* can be done -- e.g. (future,
illustrative only) "market_analysis" or "order_execution" -- never
*how* it is done, *who* performs it, or *which* Skill implements it.
This sprint does not create ``SkillRegistry``, ``SkillResolver``,
``Planner`` integration, execution, routing, or a Composition Root. It
only gives every future capability a consistent, minimal shape so the
Planner's vocabulary never needs to change as the number of
capabilities grows to dozens or hundreds.

Explicitly NOT part of this milestone: ``priority``, ``version``,
``cost``, ``provider``, ``executor``, ``runtime``, ``planner``,
``workflow``, ``scheduler``, ``memory``, ``reflection``, ``learning``,
``event_bus``, ``permissions``, ``requirements``, ``dependencies``,
``parent``, ``children``, ``implements``, ``tool``, ``skill``,
``registry``, or ``resolver`` of any kind. ``Capability`` knows about
none of those -- it is a pure, minimal "what can be done" value
object, not a registration record, a routing rule, or an execution
descriptor.

No methods beyond ``__post_init__``/``__hash__`` (LOCKED design
constraint): there is no helper method, no builder, no validator
object, no manager, no serializer, and no async anywhere in this
module -- exactly the same minimal-methods discipline already used by
``Orchestration.task.Task``, ``Orchestration.execution_context.
ExecutionContext``, ``Orchestration.workflow.Workflow``,
``Orchestration.workflow_session.WorkflowSession``,
``Orchestration.skill_result.SkillResult``,
``Orchestration.tool_context.ToolContext``, and
``Orchestration.skill_context.SkillContext``. No inheritance, no
mixins, no Protocol, no interface -- ``Capability`` is a standalone
``@dataclass(frozen=True)``, nothing more.

``metadata`` is frozen the same way already used throughout the
project by those classes: a freshly-copied ``dict`` wrapped in
``types.MappingProxyType`` inside ``__post_init__``, via
``object.__setattr__`` (the one sanctioned way to set a field from
inside a frozen dataclass's own ``__post_init__``). ``tags`` is a
``Tuple[str, ...]`` -- already immutable by construction -- and is
never rewritten, reordered, deduplicated, or otherwise modified; it
is validated and stored exactly as given.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError``, the stdlib ``dataclasses``,
``types.MappingProxyType``, and ``typing`` modules -- nothing else.
It is not imported by, and does not import from,
``Orchestration.base_tool.BaseTool``,
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_registry.SkillRegistry``,
``Orchestration.skill_resolver.SkillResolver``,
``Orchestration.executor.Executor``,
``Orchestration.workflow_runtime.WorkflowRuntime``,
``Orchestration.workflow_engine.WorkflowEngine``,
``Orchestration.workflow_execution_coordinator.
WorkflowExecutionCoordinator``, ``Agents.planner.Planner``,
``Orchestration.task.Task``, ``Orchestration.workflow.Workflow``,
``Orchestration.memory``, ``Orchestration.learning_loop.LearningLoop``,
``Orchestration.reflection``, ``Orchestration.event_bus.EventBus``,
``Services``, ``Repository``, ``Providers``, ``Database``, ``Agents``,
or ``Core.composition_root``. It is additive-only, standing on its own
until a future sprint has a concrete ``SkillRegistry`` or ``Planner``
that consumes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Tuple

from Core.exceptions import AgentError


class CapabilityError(AgentError):
    """Raised when ``Capability`` is given invalid inputs at
    construction time.

    Following the same convention as ``TaskError``/
    ``ExecutionContextError``/``WorkflowError``/``SkillResultError``/
    ``ToolContextError``/``SkillContextError`` (all subclass
    ``Core.exceptions.AgentError`` directly). Raised by
    ``Capability.__post_init__`` for an invalid ``name``,
    ``description``, ``metadata``, or ``tags`` field. No other
    validation exists.
    """


@dataclass(frozen=True)
class Capability:
    """The immutable vocabulary a future Planner will use to reason
    about available abilities.

    ``Capability`` is a pure, passive value object and nothing more:
    it names an ability, describes it, and carries optional
    metadata/tags -- and it does nothing with any of that itself. It
    describes *what* can be done, never *how*, *who* performs it, or
    *which* Skill implements it. It is not wired into ``BaseSkill``,
    ``BaseTool``, ``SkillRegistry``, ``SkillResolver``, ``Executor``,
    ``WorkflowRuntime``, ``WorkflowEngine``,
    ``WorkflowExecutionCoordinator``, ``Planner``, ``Memory``,
    ``LearningLoop``, ``Reflection``, ``EventBus``, ``Services``,
    ``Repository``, ``Providers``, ``Database``, ``Agents``, or the
    Composition Root -- this sprint introduces the shape only. There
    is no execution method, no registration, no discovery, no
    persistence, no serialization, and no eventing anywhere in this
    module; the only methods this class defines at all are
    ``__post_init__`` and ``__hash__``.

    Instances are frozen (immutable) -- once constructed, none of a
    ``Capability``'s fields can be reassigned. ``metadata`` is
    additionally locked down (see ``__post_init__``) so that mutating
    the original mapping passed in -- or attempting to mutate
    ``capability.metadata`` itself -- has no effect on this instance
    after construction. This mirrors the same "freeze the mapping
    too" pattern ``Orchestration.task.Task``,
    ``Orchestration.execution_context.ExecutionContext``,
    ``Orchestration.workflow.Workflow``,
    ``Orchestration.workflow_session.WorkflowSession``,
    ``Orchestration.skill_result.SkillResult``,
    ``Orchestration.tool_context.ToolContext``, and
    ``Orchestration.skill_context.SkillContext`` already use for their
    own metadata/payload fields. ``tags`` is already immutable by
    virtue of being a ``tuple`` and is stored exactly as validated,
    with no copying or transformation.

    Attributes:
        name: The capability's identifying name (e.g., in some future
            sprint, "market_analysis"). Must be a non-empty string
            whose stripped form is also non-empty. Capability names
            must eventually be globally unique, which is why
            ``__hash__`` is defined in terms of ``name`` alone.
        description: A human-readable description of what this
            capability represents. Must be a non-empty string.
        metadata: Optional contextual information about this
            capability. Stored internally as an immutable
            ``MappingProxyType`` snapshot of whatever mapping was
            passed in.
        tags: An immutable tuple of non-empty string tags describing
            or categorizing this capability. Stored exactly as given.
    """

    name: str
    description: str
    metadata: Mapping[str, Any]
    tags: Tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate ``name``, ``description``, ``metadata``, and
        ``tags``, and freeze ``metadata`` into an immutable snapshot.

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.metadata``) to a different object,
        but it does nothing to stop the *contents* of a mutable
        mapping from being changed out from under this ``Capability``
        after construction. Wrapping a freshly-copied ``dict`` in
        ``MappingProxyType`` closes that gap: the ``metadata`` any
        caller observes is guaranteed to be exactly what it was at
        construction time, for the lifetime of this instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        Raises:
            CapabilityError: if ``name`` is not a non-empty string
                (after stripping whitespace); if ``description`` is
                not a non-empty string; if ``metadata`` is not a
                ``Mapping``; if ``tags`` is not a ``tuple``; if any
                element of ``tags`` is not a string; or if any
                element of ``tags`` is an empty string.
        """
        if not isinstance(self.name, str):
            raise CapabilityError(
                f"Capability requires 'name' to be a str; got {self.name!r}"
            )
        if len(self.name.strip()) == 0:
            raise CapabilityError(
                "Capability requires 'name' to be non-empty (after "
                "stripping whitespace)"
            )

        if not isinstance(self.description, str):
            raise CapabilityError(
                f"Capability requires 'description' to be a str; got "
                f"{self.description!r}"
            )
        if len(self.description.strip()) == 0:
            raise CapabilityError(
                "Capability requires 'description' to be non-empty "
                "(after stripping whitespace)"
            )

        if not isinstance(self.metadata, Mapping):
            raise CapabilityError(
                f"Capability requires 'metadata' to be a Mapping; got "
                f"{self.metadata!r}"
            )

        if not isinstance(self.tags, tuple):
            raise CapabilityError(
                f"Capability requires 'tags' to be a tuple; got "
                f"{self.tags!r}"
            )
        for tag in self.tags:
            if not isinstance(tag, str):
                raise CapabilityError(
                    f"Capability requires every 'tags' element to be a "
                    f"str; got {tag!r}"
                )
            if len(tag) == 0:
                raise CapabilityError(
                    "Capability requires every 'tags' element to be "
                    "non-empty"
                )

        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``name`` alone.

        Capability names must eventually be globally unique, so
        ``name`` is the natural identity for hashing (unlike
        ``Orchestration.tool_context.ToolContext``/
        ``Orchestration.skill_context.SkillContext``, which hash by
        ``id(task)`` because ``task`` has no identifying string of
        its own). ``description``, ``metadata``, and ``tags`` are
        deliberately excluded from the hash.

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two ``Capability``
        instances are only ``==`` when *all four* fields match. Two
        ``Capability`` instances sharing the same ``name`` may differ
        in ``description``/``metadata``/``tags`` and thus share a
        hash without being equal -- which is exactly what Python's
        hash/eq contract permits (it only requires equal objects to
        share a hash, never the reverse).
        """
        return hash(self.name)