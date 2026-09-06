"""ToolContext -- the universal input object every future Tool will
receive (Phase 5, Sprint 51).

Phase 8, Sprint 98 update (Architecture Correction, not a feature
sprint): ``task=None`` is now a valid, supported construction.
Sprint 97 gave ``Executor.execute_current_tool()`` a LOCKED
implementation shape that always constructs
``ToolContext(task=None, parameters={}, metadata={})`` -- but this
module's own ``__post_init__`` rejected ``task=None`` outright,
so every real call to ``execute_current_tool()`` failed before
``Tool.execute()`` was ever reached. That was a genuine contradiction
between two LOCKED contracts, not a feature gap: ``task`` was already
documented as "deliberately unconstrained" (see ``Any`` below), and
the only thing standing in the way of a Tool that legitimately has no
particular task to act on (which is exactly the Sprint 97 caller's
situation) was the single ``is None`` check. This sprint removes only
that one check. ``task`` remains ``Any`` -- unconstrained for every
non-``None`` value exactly as before -- and every other validation
(``parameters``/``metadata`` must be ``Mapping``, both frozen into
``MappingProxyType`` snapshots) is untouched. No constructor change,
no new field, no helper method, no factory, no cache, no logging, no
retry, and no ``Runtime``/``Workflow``/``Planner``/``Registry``/
``Manager`` reference was introduced.

Scope note (LOCKED baseline): this module introduces exactly two
things and nothing more.

  1. ``ToolContextError`` -- the module's own exception type,
     following the same convention as ``TaskError``/
     ``ExecutionContextError``/``WorkflowError``/``SkillResultError``/
     ``SkillContextError`` (subclasses ``Core.exceptions.AgentError``
     directly, no intermediate layer).
  2. ``ToolContext`` -- a frozen dataclass with exactly three fields:
     ``task: Any``, ``parameters: Mapping[str, Any]``, and
     ``metadata: Mapping[str, Any]``. That is the entire shape.

This sprint is a pure contract sprint, one layer below
``Orchestration.skill_context.SkillContext``, in the architecture:

    Planner -> Skill (SkillContext) -> Tool (ToolContext) ->
    Services / Repository / API

This module does NOT create a ``BrowserTool``, ``MarketTool``,
``TradingTool``, ``NewsTool``, or any other concrete Tool. It only
gives every future Tool a consistent input shape so the Tool contract
never needs to change as the number of Tools grows to dozens or
hundreds.

Explicitly NOT part of this milestone: ``tool_id``, ``tool_name``,
``execution_id``, ``workflow_id``, ``session_id``, a timestamp, a
logger, memory, a runtime, a planner, an executor, a scheduler, a
provider, a service, a repository, a database, an agent, an event, a
reflection, or a learning reference of any kind. ``ToolContext`` knows
about none of those -- it is a pure, minimal "what should the tool do,
and with what" value object, not an execution record or a diagnostics
bundle.

No methods beyond ``__post_init__``/``__hash__`` (LOCKED design
constraint): there is no helper method, no builder, no validator
object, no manager, no serializer, and no async anywhere in this
module -- exactly the same minimal-methods discipline already used by
``Orchestration.task.Task``, ``Orchestration.execution_context.
ExecutionContext``, ``Orchestration.workflow.Workflow``,
``Orchestration.workflow_session.WorkflowSession``,
``Orchestration.skill_result.SkillResult``, and
``Orchestration.skill_context.SkillContext``. No inheritance, no
mixins, no Protocol, no interface -- ``ToolContext`` is a standalone
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
until a future sprint has concrete ``BaseTool.execute()``
implementations receive it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from Core.exceptions import AgentError


class ToolContextError(AgentError):
    """Raised when ``ToolContext`` is given invalid inputs at
    construction time.

    Following the same convention as ``TaskError``/
    ``ExecutionContextError``/``WorkflowError``/``SkillResultError``/
    ``SkillContextError`` (all subclass ``Core.exceptions.AgentError``
    directly). Raised by ``ToolContext.__post_init__`` for an invalid
    ``parameters`` or ``metadata`` field. No other validation exists
    -- as of Phase 8 Sprint 98, ``task`` has no validation of its own
    at all (``None`` and every other value are equally accepted).
    """


@dataclass(frozen=True)
class ToolContext:
    """The single, universal input object every future ``Tool`` will
    receive via ``BaseTool.execute(context)``.

    ``ToolContext`` is a pure, passive value object and nothing more:
    it carries the task a Tool should act on, the parameters that
    task requires, and optional contextual metadata -- and it does
    nothing with any of that. It is not wired into ``BaseTool``,
    ``BaseSkill``, ``SkillRegistry``, ``SkillResolver``, ``Executor``,
    ``WorkflowRuntime``, ``WorkflowEngine``,
    ``WorkflowExecutionCoordinator``, ``Planner``, ``Memory``,
    ``LearningLoop``, ``Reflection``, ``EventBus``, ``Services``,
    ``Repository``, ``Providers``, ``Database``, ``Agents``, or the
    Composition Root -- this sprint introduces the shape only. There
    is no execution method, no persistence, no serialization, and no
    eventing anywhere in this module; the only methods this class
    defines at all are ``__post_init__`` and ``__hash__``.

    Instances are frozen (immutable) -- once constructed, none of a
    ``ToolContext``'s fields can be reassigned. ``parameters`` and
    ``metadata`` are additionally locked down (see ``__post_init__``)
    so that mutating the original mapping passed in -- or attempting
    to mutate ``context.parameters``/``context.metadata`` themselves
    -- has no effect on this instance after construction. This
    mirrors the same "freeze the mapping too" pattern
    ``Orchestration.task.Task``, ``Orchestration.execution_context.
    ExecutionContext``, ``Orchestration.workflow.Workflow``,
    ``Orchestration.workflow_session.WorkflowSession``,
    ``Orchestration.skill_result.SkillResult``, and
    ``Orchestration.skill_context.SkillContext`` already use for
    their own metadata/payload fields.

    Attributes:
        task: Whatever the Tool should act on, or ``None`` if there
            is no particular task (Phase 8 Sprint 98 -- ``None`` is
            now a valid, supported value, not an error). Deliberately
            unconstrained (``Any``) -- no validation is performed on
            this field at all. Never copied, transformed, or
            introspected; this class preserves the exact object
            identity it was constructed with.
        parameters: The parameters that ``task`` requires. Stored
            internally as an immutable ``MappingProxyType`` snapshot
            of whatever mapping was passed in.
        metadata: Optional contextual information. Stored internally
            as an immutable ``MappingProxyType`` snapshot of whatever
            mapping was passed in.
    """

    task: Any
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate ``parameters`` and ``metadata``, and freeze them
        into immutable snapshots. ``task`` is not validated at all
        (Phase 8 Sprint 98 -- ``None`` is now accepted alongside every
        other value; ``task`` was already documented as
        unconstrained ``Any``, so removing the sole ``is None`` check
        widens its accepted domain rather than narrowing it).

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.parameters``/``self.metadata``) to a
        different object, but it does nothing to stop the *contents*
        of a mutable mapping from being changed out from under this
        ``ToolContext`` after construction. Wrapping a freshly-copied
        ``dict`` in ``MappingProxyType`` closes that gap: the
        ``parameters``/``metadata`` any caller observes is guaranteed
        to be exactly what it was at construction time, for the
        lifetime of this instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        Raises:
            ToolContextError: if ``parameters`` is not a ``Mapping``;
                or if ``metadata`` is not a ``Mapping``. ``task`` can
                never cause this method to raise.
        """
        if not isinstance(self.parameters, Mapping):
            raise ToolContextError(
                f"ToolContext requires 'parameters' to be a Mapping; "
                f"got {self.parameters!r}"
            )

        if not isinstance(self.metadata, Mapping):
            raise ToolContextError(
                f"ToolContext requires 'metadata' to be a Mapping; "
                f"got {self.metadata!r}"
            )

        object.__setattr__(
            self, "parameters", MappingProxyType(dict(self.parameters))
        )
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``id(task)`` alone.

        Unlike ``Orchestration.skill_context.SkillContext`` (which
        hashes by its own ``action`` string), ``ToolContext`` has no
        hashable identifying field of its own -- ``task`` is
        deliberately unconstrained (``Any``) and may itself be
        unhashable (e.g. a ``dict`` or ``list``). Hashing by the
        object identity of ``task`` (``id(task)``) sidesteps that
        entirely: it never calls ``task``'s own ``__hash__``, and it
        deliberately mirrors object identity rather than the contents
        of ``parameters``/``metadata`` (which are excluded for the
        same reason ``SkillResult``/``SkillContext`` exclude their own
        mapping fields -- an immutable ``MappingProxyType`` over a
        ``dict`` snapshot is deliberately not hashable).

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two ``ToolContext``
        instances are only ``==`` when *all three* fields match. Two
        ``ToolContext`` instances sharing the same ``task`` reference
        (and therefore the same ``id(task)``) may differ in
        ``parameters``/``metadata`` and thus share a hash without
        being equal -- which is exactly what Python's hash/eq contract
        permits (it only requires equal objects to share a hash, never
        the reverse).
        """
        return hash(id(self.task))