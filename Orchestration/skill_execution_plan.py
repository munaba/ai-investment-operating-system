"""SkillExecutionPlan -- the immutable value object that packages a
discovery result into a single, execution-ready plan shape (Phase 6,
Sprint 71: Skill Execution Pipeline, Discovery -> Execution Boundary).

Scope note (LOCKED baseline): this module introduces exactly two
things and nothing more.

  1. ``SkillExecutionPlanError`` -- the module's own exception type,
     following the same convention as ``SkillDescriptorError``/
     ``CapabilityError``/``SkillResultError``/``ToolContextError``/
     ``SkillContextError`` (subclasses ``Core.exceptions.AgentError``
     directly, no intermediate layer).
  2. ``SkillExecutionPlan`` -- a frozen dataclass with exactly three
     fields: ``skills: Tuple[Any, ...]``, ``tools: Tuple[str, ...]``,
     and ``metadata: Mapping[str, Any]``. That is the entire shape.

A ``SkillExecutionPlan`` is a pure, passive snapshot of what
``GoalPlanner.resolve_skills(goal)`` and ``GoalPlanner.discover_tools
(goal)`` already produced -- nothing more. It does not execute a
Skill or a Tool, does not instantiate ``Executor``, ``Runtime``,
``Workflow``, or ``EventBus``, does not inspect ``BaseSkill`` or
``BaseTool``, and does not normalize, cache, rank, reorder, or
deduplicate anything it is given. This sprint (Phase 6, Sprint 71)
begins connecting the Discovery Layer to the Execution Layer -- but
this module is purely the value-object boundary between them; the
Registry/Resolver/Manager architecture built during Sprints 43-70 is
frozen and untouched by this addition.

No methods beyond ``__post_init__``/``__hash__`` (LOCKED design
constraint): there is no helper method, no builder, no validator
object, no manager, no serializer, and no async anywhere in this
module -- exactly the same minimal-methods discipline already used by
``Orchestration.tool_context.ToolContext``,
``Orchestration.skill_context.SkillContext``,
``Orchestration.skill_result.SkillResult``,
``Orchestration.capability.Capability``, and
``Orchestration.skill_descriptor.SkillDescriptor``. No inheritance, no
mixins, no Protocol, no interface -- ``SkillExecutionPlan`` is a
standalone ``@dataclass(frozen=True)``, nothing more.

``metadata`` is frozen the same way already used throughout the
project by those classes: a freshly-copied ``dict`` wrapped in
``types.MappingProxyType`` inside ``__post_init__``, via
``object.__setattr__`` (the one sanctioned way to set a field from
inside a frozen dataclass's own ``__post_init__``). ``skills`` and
``tools`` are both ``Tuple[..., ...]`` -- already immutable by
construction -- and are never copied, reordered, deduplicated, or
otherwise modified; they are validated and stored exactly as given.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError``, the stdlib ``dataclasses``,
``types.MappingProxyType``, and ``typing`` modules -- nothing else. It
is not imported by, and does not import from,
``Orchestration.executor.Executor``,
``Orchestration.workflow_runtime.WorkflowRuntime``,
``Orchestration.workflow_engine.WorkflowEngine``,
``Orchestration.workflow_execution_coordinator.
WorkflowExecutionCoordinator``, ``Orchestration.event_bus.EventBus``,
``Orchestration.base_skill.BaseSkill``, or
``Orchestration.base_tool.BaseTool``. It is additive-only, standing on
its own until a future sprint has a concrete Executor that consumes
it.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Tuple

from Core.exceptions import AgentError


class SkillExecutionPlanError(AgentError):
    """Raised when ``SkillExecutionPlan`` is given invalid inputs at
    construction time.

    Following the same convention as ``SkillDescriptorError``/
    ``CapabilityError``/``SkillResultError``/``ToolContextError``/
    ``SkillContextError`` (all subclass ``Core.exceptions.AgentError``
    directly). Raised by ``SkillExecutionPlan.__post_init__`` for an
    invalid ``skills``, ``tools``, or ``metadata`` field. No other
    validation exists.
    """


@dataclass(frozen=True)
class SkillExecutionPlan:
    """The immutable value object packaging a discovery result into a
    single, execution-ready plan shape.

    ``SkillExecutionPlan`` is a pure, passive value object and nothing
    more: it holds the resolved skills, the discovered tool names, and
    optional metadata -- and it does nothing with any of that itself.
    It does not execute a skill or a tool, does not call any
    Executor, Runtime, Workflow, or EventBus, and does not inspect
    ``BaseSkill`` or ``BaseTool``. There is no execution method, no
    registration, no discovery, no persistence, no serialization, and
    no eventing anywhere in this module; the only methods this class
    defines at all are ``__post_init__`` and ``__hash__``.

    Instances are frozen (immutable) -- once constructed, none of a
    ``SkillExecutionPlan``'s fields can be reassigned. ``metadata`` is
    additionally locked down (see ``__post_init__``) so that mutating
    the original mapping passed in -- or attempting to mutate
    ``plan.metadata`` itself -- has no effect on this instance after
    construction. This mirrors the same "freeze the mapping too"
    pattern ``Orchestration.tool_context.ToolContext``,
    ``Orchestration.skill_context.SkillContext``,
    ``Orchestration.skill_result.SkillResult``,
    ``Orchestration.capability.Capability``, and
    ``Orchestration.skill_descriptor.SkillDescriptor`` already use for
    their own metadata/payload fields. ``skills`` and ``tools`` are
    already immutable by virtue of being tuples and are stored exactly
    as validated, with no copying, sorting, or deduplication.

    Attributes:
        skills: An immutable tuple of the resolved skill objects this
            plan packages. Deliberately typed ``Tuple[Any, ...]`` --
            this module does not import or depend on any concrete
            skill type. Stored exactly as given, with no copying,
            validation of element type, reordering, or deduplication.
        tools: An immutable tuple of the discovered tool names this
            plan packages. Stored exactly as given, with no copying,
            validation of element type, reordering, or deduplication.
        metadata: Optional contextual information about this plan.
            Stored internally as an immutable ``MappingProxyType``
            snapshot of whatever mapping was passed in.
    """

    skills: Tuple[Any, ...]
    tools: Tuple[str, ...]
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Validate ``skills``, ``tools``, and ``metadata``, and
        freeze ``metadata`` into an immutable snapshot.

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.metadata``) to a different object,
        but it does nothing to stop the *contents* of a mutable
        mapping from being changed out from under this
        ``SkillExecutionPlan`` after construction. Wrapping a
        freshly-copied ``dict`` in ``MappingProxyType`` closes that
        gap: the ``metadata`` any caller observes is guaranteed to be
        exactly what it was at construction time, for the lifetime of
        this instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        Raises:
            SkillExecutionPlanError: if ``skills`` is not a ``tuple``;
                if ``tools`` is not a ``tuple``; or if ``metadata`` is
                not a ``Mapping``.
        """
        if not isinstance(self.skills, tuple):
            raise SkillExecutionPlanError(
                f"SkillExecutionPlan requires 'skills' to be a tuple; "
                f"got {self.skills!r}"
            )

        if not isinstance(self.tools, tuple):
            raise SkillExecutionPlanError(
                f"SkillExecutionPlan requires 'tools' to be a tuple; "
                f"got {self.tools!r}"
            )

        if not isinstance(self.metadata, Mapping):
            raise SkillExecutionPlanError(
                f"SkillExecutionPlan requires 'metadata' to be a "
                f"Mapping; got {self.metadata!r}"
            )

        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``id(self.skills)`` alone.

        ``skills`` is the natural identity for hashing this value
        object (mirroring ``Orchestration.skill_context.SkillContext``,
        which likewise hashes by the object identity of one of its
        own fields rather than its contents). ``tools`` and
        ``metadata`` are deliberately excluded from the hash --
        ``metadata`` in particular is stored as a ``MappingProxyType``
        snapshot, which is itself unhashable.

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two
        ``SkillExecutionPlan`` instances are only ``==`` when *all
        three* fields match. Two ``SkillExecutionPlan`` instances
        sharing the same ``skills`` tuple object (and therefore the
        same ``id(skills)``) may differ in ``tools``/``metadata`` and
        thus share a hash without being equal -- which is exactly
        what Python's hash/eq contract permits (it only requires
        equal objects to share a hash, never the reverse).
        """
        return hash(id(self.skills))