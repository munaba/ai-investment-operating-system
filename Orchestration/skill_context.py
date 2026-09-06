"""SkillContext -- the universal input object every future Skill will
receive (Phase 5, Sprint 52).

Phase 9, Sprint 105 update (Architecture Correction, not a feature
sprint): ``task=None`` is now a valid, supported construction,
mirroring the identical Sprint 98 correction already made to this
module's sibling, ``Orchestration.tool_context.ToolContext``.
``Executor.invoke_current_skill()`` has a LOCKED implementation shape
(Sprint 79) that always constructs ``SkillContext(task=None,
parameters={}, metadata={}, tool_context_factory=tool_context_factory)``
-- but this module's own ``__post_init__`` rejected ``task=None``
outright, so every real call to ``invoke_current_skill()`` raised
``SkillContextError`` before the Skill's ``_tool_names``/
``_resolve_tool`` attributes were ever set and before
``skill.execute()`` was ever reached. That was a genuine
contradiction between two LOCKED contracts, not a feature gap:
``task`` was already documented as "deliberately unconstrained" (see
``Any`` below), and the only thing standing in the way of a Skill
invocation that legitimately has no particular task to act on (which
is exactly the Sprint 79 caller's situation) was the single ``is
None`` check. This sprint removes only that one check. ``task``
remains ``Any`` -- unconstrained for every non-``None`` value exactly
as before -- and every other validation (``parameters``/``metadata``
must be ``Mapping``, ``tool_context_factory`` must be ``None`` or
callable, both mapping fields frozen into ``MappingProxyType``
snapshots) is untouched. No constructor change, no new field, no
helper method, no factory, no cache, no logging, no retry, and no
``Runtime``/``Workflow``/``Planner``/``Registry``/``Manager``
reference was introduced.

Scope note (LOCKED baseline): this module introduces exactly two
things and nothing more.

  1. ``SkillContextError`` -- the module's own exception type,
     following the same convention as ``TaskError``/
     ``ExecutionContextError``/``WorkflowError``/``SkillResultError``/
     ``ToolContextError`` (subclasses ``Core.exceptions.AgentError``
     directly, no intermediate layer).
  2. ``SkillContext`` -- a frozen dataclass with exactly four fields:
     ``task: Any``, ``parameters: Mapping[str, Any]``,
     ``metadata: Mapping[str, Any]``, and
     ``tool_context_factory: Optional[Callable[..., Any]] = None``.
     That is the entire shape.

This sprint is a pure contract sprint, one layer above
``Orchestration.tool_context.ToolContext``, in the architecture:

    Planner -> Skill (SkillContext) -> Tool (ToolContext) ->
    Services / Repository / API

This module does NOT build a ``ToolContext``, call a ``Tool``, call a
``Skill``, call a ``Planner``, call a ``Runtime``, create a ``Task``,
or create a ``Workflow``. It only gives every future Skill a
consistent input shape so the Skill contract never needs to change as
the number of Skills grows. ``tool_context_factory`` is stored purely
as an optional callable reference -- it is never invoked, inspected,
or validated beyond "is it callable" here.

Explicitly NOT part of this milestone: ``workflow_id``,
``execution_id``, ``session_id``, a runtime, an executor, a scheduler,
a memory, a reflection, a learning reference, an event bus, a
provider, a database, a repository, a service, an agent, a host, a
planner, a logger, a result, a status, a priority, a retry, or a
timeout of any kind. ``SkillContext`` knows about none of those -- it
is a pure, minimal "what should the skill do, and with what" value
object, not an execution record or a diagnostics bundle.

No methods beyond ``__post_init__``/``__hash__`` (LOCKED design
constraint): there is no helper method, no builder, no validator
object, no manager, no serializer, and no async anywhere in this
module -- exactly the same minimal-methods discipline already used by
``Orchestration.task.Task``, ``Orchestration.execution_context.
ExecutionContext``, ``Orchestration.workflow.Workflow``,
``Orchestration.workflow_session.WorkflowSession``,
``Orchestration.skill_result.SkillResult``, and
``Orchestration.tool_context.ToolContext``. No inheritance, no
mixins, no Protocol, no interface -- ``SkillContext`` is a standalone
``@dataclass(frozen=True)``, nothing more.

Both ``parameters`` and ``metadata`` are frozen the same way already
used throughout the project by those classes: a freshly-copied
``dict`` wrapped in ``types.MappingProxyType`` inside
``__post_init__``, via ``object.__setattr__`` (the one sanctioned way
to set a field from inside a frozen dataclass's own
``__post_init__``).

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
until a future sprint has concrete ``BaseSkill.execute()``
implementations receive it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

from Core.exceptions import AgentError


class SkillContextError(AgentError):
    """Raised when ``SkillContext`` is given invalid inputs at
    construction time.

    Following the same convention as ``TaskError``/
    ``ExecutionContextError``/``WorkflowError``/``SkillResultError``/
    ``ToolContextError`` (all subclass ``Core.exceptions.AgentError``
    directly). Raised by ``SkillContext.__post_init__`` for an invalid
    ``task``, ``parameters``, ``metadata``, or
    ``tool_context_factory`` field. No other validation exists.
    """


@dataclass(frozen=True)
class SkillContext:
    """The single, universal input object every future ``Skill`` will
    receive via ``BaseSkill.execute(context)``.

    ``SkillContext`` is a pure, passive value object and nothing
    more: it carries the task a Skill should act on, the parameters
    that task requires, optional contextual metadata, and an optional
    factory callable a future Skill may use to build a
    ``ToolContext`` -- and it does nothing with any of that itself.
    It is not wired into ``BaseSkill``, ``BaseTool``,
    ``SkillRegistry``, ``SkillResolver``, ``Executor``,
    ``WorkflowRuntime``, ``WorkflowEngine``,
    ``WorkflowExecutionCoordinator``, ``Planner``, ``Memory``,
    ``LearningLoop``, ``Reflection``, ``EventBus``, ``Services``,
    ``Repository``, ``Providers``, ``Database``, ``Agents``, or the
    Composition Root -- this sprint introduces the shape only. There
    is no execution method, no persistence, no serialization, and no
    eventing anywhere in this module; the only methods this class
    defines at all are ``__post_init__`` and ``__hash__``.

    Instances are frozen (immutable) -- once constructed, none of a
    ``SkillContext``'s fields can be reassigned. ``parameters`` and
    ``metadata`` are additionally locked down (see ``__post_init__``)
    so that mutating the original mapping passed in -- or attempting
    to mutate ``context.parameters``/``context.metadata`` themselves
    -- has no effect on this instance after construction. This
    mirrors the same "freeze the mapping too" pattern
    ``Orchestration.task.Task``, ``Orchestration.execution_context.
    ExecutionContext``, ``Orchestration.workflow.Workflow``,
    ``Orchestration.workflow_session.WorkflowSession``,
    ``Orchestration.skill_result.SkillResult``, and
    ``Orchestration.tool_context.ToolContext`` already use for their
    own metadata/payload fields.

    Attributes:
        task: Whatever the Skill should act on, or ``None`` if there
            is no particular task (Phase 9 Sprint 105 -- ``None`` is
            a valid, supported value, not an error). Deliberately
            unconstrained (``Any``) and not validated at all. Never
            copied, transformed, or introspected; this class
            preserves the exact object identity it was constructed
            with.
        parameters: The parameters that ``task`` requires. Stored
            internally as an immutable ``MappingProxyType`` snapshot
            of whatever mapping was passed in.
        metadata: Optional contextual information. Stored internally
            as an immutable ``MappingProxyType`` snapshot of whatever
            mapping was passed in.
        tool_context_factory: Optional callable a future Skill may
            use to construct a ``ToolContext``. Deliberately
            unconstrained beyond "callable or ``None``" -- never
            called, inspected, or validated any further here.
    """

    task: Any
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    tool_context_factory: Optional[Callable[..., Any]] = None

    def __post_init__(self) -> None:
        """Validate ``task``, ``parameters``, ``metadata``, and
        ``tool_context_factory``, and freeze ``parameters``/
        ``metadata`` into immutable snapshots.

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.parameters``/``self.metadata``) to a
        different object, but it does nothing to stop the *contents*
        of a mutable mapping from being changed out from under this
        ``SkillContext`` after construction. Wrapping a
        freshly-copied ``dict`` in ``MappingProxyType`` closes that
        gap: the ``parameters``/``metadata`` any caller observes is
        guaranteed to be exactly what it was at construction time,
        for the lifetime of this instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        Raises:
            SkillContextError: if ``parameters`` is not a
                ``Mapping``; if ``metadata`` is not a ``Mapping``; or
                if ``tool_context_factory`` is neither ``None`` nor
                callable. ``task`` is unconstrained (``Any``,
                including ``None`` -- Sprint 105) and is never
                validated here.
        """
        if not isinstance(self.parameters, Mapping):
            raise SkillContextError(
                f"SkillContext requires 'parameters' to be a Mapping; "
                f"got {self.parameters!r}"
            )

        if not isinstance(self.metadata, Mapping):
            raise SkillContextError(
                f"SkillContext requires 'metadata' to be a Mapping; "
                f"got {self.metadata!r}"
            )

        if self.tool_context_factory is not None and not callable(
            self.tool_context_factory
        ):
            raise SkillContextError(
                f"SkillContext requires 'tool_context_factory' to be "
                f"None or callable; got {self.tool_context_factory!r}"
            )

        object.__setattr__(
            self, "parameters", MappingProxyType(dict(self.parameters))
        )
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``id(task)`` alone.

        ``SkillContext`` has no hashable identifying field of its
        own -- ``task`` is deliberately unconstrained (``Any``) and
        may itself be unhashable (e.g. a ``dict`` or ``list``).
        Hashing by the object identity of ``task`` (``id(task)``)
        sidesteps that entirely: it never calls ``task``'s own
        ``__hash__``, and it deliberately mirrors object identity
        rather than the contents of ``parameters``/``metadata``
        (which are excluded for the same reason ``SkillResult``/
        ``ToolContext`` exclude their own mapping fields -- an
        immutable ``MappingProxyType`` over a ``dict`` snapshot is
        deliberately not hashable) or ``tool_context_factory``
        (excluded for the same reason -- it plays no identifying
        role).

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two ``SkillContext``
        instances are only ``==`` when *all four* fields match. Two
        ``SkillContext`` instances sharing the same ``task``
        reference (and therefore the same ``id(task)``) may differ in
        ``parameters``/``metadata``/``tool_context_factory`` and thus
        share a hash without being equal -- which is exactly what
        Python's hash/eq contract permits (it only requires equal
        objects to share a hash, never the reverse).
        """
        return hash(id(self.task))