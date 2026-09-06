"""SkillDescriptor -- the immutable metadata layer that describes a
Skill without containing or executing it (Phase 5, Sprint 54).

Scope note (LOCKED baseline): this module introduces exactly two
things and nothing more.

  1. ``SkillDescriptorError`` -- the module's own exception type,
     following the same convention as ``TaskError``/
     ``ExecutionContextError``/``WorkflowError``/``SkillResultError``/
     ``ToolContextError``/``SkillContextError``/``CapabilityError``
     (subclasses ``Core.exceptions.AgentError`` directly, no
     intermediate layer).
  2. ``SkillDescriptor`` -- a frozen dataclass with exactly five
     fields: ``name: str``, ``description: str``,
     ``capabilities: Tuple[Any, ...]``, ``metadata: Mapping[str, Any]``,
     and ``tags: Tuple[str, ...]``. That is the entire shape.

A ``SkillDescriptor`` describes *what a Skill is*, *what capabilities
it provides*, and optional metadata/tags -- nothing more. It sits
between ``Orchestration.capability.Capability`` and a future
``BaseSkill`` in the architecture:

    Capability -> SkillDescriptor -> BaseSkill

but this module deliberately does NOT import ``Capability`` (or
``BaseSkill``/``BaseTool``). The ``capabilities`` field is typed as
``Tuple[Any, ...]`` -- not ``Tuple[Capability, ...]`` -- so that
dependency is intentionally deferred to a future sprint. This sprint
does not create a ``SkillRegistry``, a ``SkillResolver``, ``Planner``
integration, execution, or a Composition Root. It only gives every
future Skill a consistent, minimal descriptor shape.

Explicitly NOT part of this milestone: ``skill``, ``skill_class``,
``executor``, ``planner``, ``provider``, ``runtime``, ``workflow``,
``priority``, ``cost``, ``memory``, ``reflection``, ``learning``,
``scheduler``, ``registry``, ``resolver``, ``tool``, ``service``,
``repository``, ``database``, ``agent``, or ``event_bus`` of any
kind. ``SkillDescriptor`` knows about none of those -- it is a pure,
minimal "what is this Skill, and what does it provide" value object,
not a registration record, an execution handle, or a routing rule.

No methods beyond ``__post_init__``/``__hash__`` (LOCKED design
constraint): there is no helper method, no builder, no validator
object, no manager, no serializer, and no async anywhere in this
module -- exactly the same minimal-methods discipline already used by
``Orchestration.task.Task``, ``Orchestration.execution_context.
ExecutionContext``, ``Orchestration.workflow.Workflow``,
``Orchestration.workflow_session.WorkflowSession``,
``Orchestration.skill_result.SkillResult``,
``Orchestration.tool_context.ToolContext``,
``Orchestration.skill_context.SkillContext``, and
``Orchestration.capability.Capability``. No inheritance, no mixins,
no Protocol, no interface -- ``SkillDescriptor`` is a standalone
``@dataclass(frozen=True)``, nothing more.

``metadata`` is frozen the same way already used throughout the
project by those classes: a freshly-copied ``dict`` wrapped in
``types.MappingProxyType`` inside ``__post_init__``, via
``object.__setattr__`` (the one sanctioned way to set a field from
inside a frozen dataclass's own ``__post_init__``). ``capabilities``
and ``tags`` are both ``Tuple[..., ...]`` -- already immutable by
construction -- and are never copied, reordered, deduplicated, or
otherwise modified; they are validated and stored exactly as given.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError``, the stdlib ``dataclasses``,
``types.MappingProxyType``, and ``typing`` modules -- nothing else.
In particular it does NOT import ``Orchestration.capability.
Capability``, ``Orchestration.base_skill.BaseSkill``, or
``Orchestration.base_tool.BaseTool``. It is not imported by, and does
not import from, ``Orchestration.skill_registry.SkillRegistry``,
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


class SkillDescriptorError(AgentError):
    """Raised when ``SkillDescriptor`` is given invalid inputs at
    construction time.

    Following the same convention as ``TaskError``/
    ``ExecutionContextError``/``WorkflowError``/``SkillResultError``/
    ``ToolContextError``/``SkillContextError``/``CapabilityError``
    (all subclass ``Core.exceptions.AgentError`` directly). Raised by
    ``SkillDescriptor.__post_init__`` for an invalid ``name``,
    ``description``, ``capabilities``, ``metadata``, or ``tags``
    field. No other validation exists.
    """


@dataclass(frozen=True)
class SkillDescriptor:
    """The immutable metadata layer that describes a Skill without
    containing or executing it.

    ``SkillDescriptor`` is a pure, passive value object and nothing
    more: it names a Skill, describes it, lists the capabilities it
    provides, and carries optional metadata/tags -- and it does
    nothing with any of that itself. It does not instantiate or
    execute a Skill, validate a ``BaseSkill`` or ``Capability``, or
    call any registry, resolver, planner, runtime, or workflow. It is
    not wired into ``BaseSkill``, ``BaseTool``, ``Capability``,
    ``SkillRegistry``, ``SkillResolver``, ``Executor``,
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
    ``SkillDescriptor``'s fields can be reassigned. ``metadata`` is
    additionally locked down (see ``__post_init__``) so that mutating
    the original mapping passed in -- or attempting to mutate
    ``descriptor.metadata`` itself -- has no effect on this instance
    after construction. This mirrors the same "freeze the mapping
    too" pattern ``Orchestration.task.Task``,
    ``Orchestration.execution_context.ExecutionContext``,
    ``Orchestration.workflow.Workflow``,
    ``Orchestration.workflow_session.WorkflowSession``,
    ``Orchestration.skill_result.SkillResult``,
    ``Orchestration.tool_context.ToolContext``,
    ``Orchestration.skill_context.SkillContext``, and
    ``Orchestration.capability.Capability`` already use for their own
    metadata/payload fields. ``capabilities`` and ``tags`` are
    already immutable by virtue of being tuples and are stored
    exactly as validated, with no copying, sorting, or
    deduplication.

    Attributes:
        name: The Skill's identifying name. Must be a non-empty
            string whose stripped form is also non-empty.
        description: A human-readable description of what this Skill
            does. Must be a non-empty string.
        capabilities: An immutable tuple describing the capabilities
            this Skill provides. Deliberately typed ``Tuple[Any, ...]``
            (not ``Tuple[Capability, ...]``) -- this module does not
            import or depend on ``Capability`` at all; that wiring is
            intentionally deferred to a future sprint. Stored exactly
            as given, with no copying, validation of element type, or
            reordering.
        metadata: Optional contextual information about this Skill.
            Stored internally as an immutable ``MappingProxyType``
            snapshot of whatever mapping was passed in.
        tags: An immutable tuple of non-empty string tags describing
            or categorizing this Skill. Stored exactly as given.
    """

    name: str
    description: str
    capabilities: Tuple[Any, ...]
    metadata: Mapping[str, Any]
    tags: Tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate ``name``, ``description``, ``capabilities``,
        ``metadata``, and ``tags``, and freeze ``metadata`` into an
        immutable snapshot.

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.metadata``) to a different object,
        but it does nothing to stop the *contents* of a mutable
        mapping from being changed out from under this
        ``SkillDescriptor`` after construction. Wrapping a
        freshly-copied ``dict`` in ``MappingProxyType`` closes that
        gap: the ``metadata`` any caller observes is guaranteed to be
        exactly what it was at construction time, for the lifetime of
        this instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        Raises:
            SkillDescriptorError: if ``name`` is not a non-empty
                string (after stripping whitespace); if
                ``description`` is not a non-empty string; if
                ``capabilities`` is not a ``tuple``; if ``metadata``
                is not a ``Mapping``; if ``tags`` is not a ``tuple``;
                if any element of ``tags`` is not a string; or if any
                element of ``tags`` is an empty string.
        """
        if not isinstance(self.name, str):
            raise SkillDescriptorError(
                f"SkillDescriptor requires 'name' to be a str; got "
                f"{self.name!r}"
            )
        if len(self.name.strip()) == 0:
            raise SkillDescriptorError(
                "SkillDescriptor requires 'name' to be non-empty (after "
                "stripping whitespace)"
            )

        if not isinstance(self.description, str):
            raise SkillDescriptorError(
                f"SkillDescriptor requires 'description' to be a str; "
                f"got {self.description!r}"
            )
        if len(self.description.strip()) == 0:
            raise SkillDescriptorError(
                "SkillDescriptor requires 'description' to be non-empty "
                "(after stripping whitespace)"
            )

        if not isinstance(self.capabilities, tuple):
            raise SkillDescriptorError(
                f"SkillDescriptor requires 'capabilities' to be a "
                f"tuple; got {self.capabilities!r}"
            )

        if not isinstance(self.metadata, Mapping):
            raise SkillDescriptorError(
                f"SkillDescriptor requires 'metadata' to be a Mapping; "
                f"got {self.metadata!r}"
            )

        if not isinstance(self.tags, tuple):
            raise SkillDescriptorError(
                f"SkillDescriptor requires 'tags' to be a tuple; got "
                f"{self.tags!r}"
            )
        for tag in self.tags:
            if not isinstance(tag, str):
                raise SkillDescriptorError(
                    f"SkillDescriptor requires every 'tags' element to "
                    f"be a str; got {tag!r}"
                )
            if len(tag) == 0:
                raise SkillDescriptorError(
                    "SkillDescriptor requires every 'tags' element to "
                    "be non-empty"
                )

        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``name`` alone.

        Skill names are the natural identity for hashing (mirroring
        ``Orchestration.capability.Capability``, which likewise
        hashes by ``name`` alone). ``description``, ``capabilities``,
        ``metadata``, and ``tags`` are deliberately excluded from the
        hash.

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two
        ``SkillDescriptor`` instances are only ``==`` when *all five*
        fields match. Two ``SkillDescriptor`` instances sharing the
        same ``name`` may differ in
        ``description``/``capabilities``/``metadata``/``tags`` and
        thus share a hash without being equal -- which is exactly
        what Python's hash/eq contract permits (it only requires
        equal objects to share a hash, never the reverse).
        """
        return hash(self.name)