"""ExecutionSession -- the immutable value object that wraps a
``SkillExecutionPlan`` together with a lifecycle ``state`` and
``metadata`` snapshot (Phase 6, Sprint 73: Executor stores an
ExecutionSession, not a raw SkillExecutionPlan; Phase 6, Sprint 74:
controlled session state transitions via ``with_state`` -- execution
remains disabled throughout).

Scope note (LOCKED baseline): this module introduces exactly two
things and nothing more.

  1. ``ExecutionSessionError`` -- the module's own exception type,
     following the same convention as ``SkillExecutionPlanError``/
     ``SkillDescriptorError``/``CapabilityError``/``SkillResultError``/
     ``ToolContextError``/``SkillContextError`` (subclasses
     ``Core.exceptions.AgentError`` directly, no intermediate layer).
  2. ``ExecutionSession`` -- a frozen dataclass with exactly three
     fields: ``plan: SkillExecutionPlan``, ``state: str``, and
     ``metadata: Mapping[str, Any]``. That is the entire shape.

An ``ExecutionSession`` is a pure, passive wrapper around a
``SkillExecutionPlan`` that has been handed to the ``Executor`` -- it
introduces a boundary between "the Executor knows a plan exists" and
"the Executor knows how to run it". It does not execute a Skill or a
Tool, does not instantiate ``Runtime``, ``Workflow``, or ``EventBus``,
does not inspect ``plan.skills`` or ``plan.tools``, and does not
inspect its own ``metadata``. This sprint (Phase 6, Sprint 73)
deliberately keeps ``Executor`` one layer further away from
``SkillExecutionPlan``'s concrete shape -- but this module is purely
the value-object boundary; the ``SkillExecutionPlan`` introduced in
Sprint 71 and the ``Executor.execute_plan`` addition from Sprint 72
are both frozen and untouched except for the one storage-line change
described below.

No methods beyond ``__post_init__``/``__hash__``/``with_state``
(LOCKED design constraint as of Sprint 74): there is no builder, no
validator object, no manager, no serializer, and no async anywhere in
this module. ``with_state`` (added in Sprint 74) is the single
sanctioned state-transition method -- it returns a new instance
rather than mutating ``self``, preserving the same frozen-value-
object discipline already used by ``Orchestration.skill_execution_plan.
SkillExecutionPlan``, ``Orchestration.tool_context.ToolContext``,
``Orchestration.skill_context.SkillContext``,
``Orchestration.skill_result.SkillResult``,
``Orchestration.capability.Capability``, and
``Orchestration.skill_descriptor.SkillDescriptor``. No inheritance, no
mixins, no Protocol, no interface -- ``ExecutionSession`` is a
standalone ``@dataclass(frozen=True)``, nothing more.

``metadata`` is frozen the same way already used throughout the
project by those classes: a freshly-copied ``dict`` wrapped in
``types.MappingProxyType`` inside ``__post_init__``, via
``object.__setattr__`` (the one sanctioned way to set a field from
inside a frozen dataclass's own ``__post_init__``). ``plan`` is stored
exactly as given (never copied or cloned), and ``state`` is stored
exactly as given once validated to be a non-empty ``str``.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError``,
``Orchestration.skill_execution_plan.SkillExecutionPlan``, the stdlib
``dataclasses``, ``types.MappingProxyType``, and ``typing`` modules --
nothing else. It does not import from and is not imported by
``Orchestration.executor.Executor`` circularly (only ``Executor``
imports this module, never the reverse), ``Orchestration.runtime``,
``Orchestration.workflow``, ``Orchestration.workflow_engine``,
``Orchestration.workflow_execution_coordinator``,
``Orchestration.event_bus``, ``Orchestration.base_skill``, or
``Orchestration.base_tool``.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from Core.exceptions import AgentError
from Orchestration.skill_execution_plan import SkillExecutionPlan


class ExecutionSessionError(AgentError):
    """Raised when ``ExecutionSession`` is given invalid inputs at
    construction time.

    Following the same convention as ``SkillExecutionPlanError``/
    ``SkillDescriptorError``/``CapabilityError``/``SkillResultError``/
    ``ToolContextError``/``SkillContextError`` (all subclass
    ``Core.exceptions.AgentError`` directly). Raised by
    ``ExecutionSession.__post_init__`` for an invalid ``plan``,
    ``state``, or ``metadata`` field. No other validation exists.
    """


@dataclass(frozen=True)
class ExecutionSession:
    """The immutable value object wrapping a ``SkillExecutionPlan``
    together with a lifecycle ``state`` and ``metadata`` snapshot.

    ``ExecutionSession`` is a pure, passive value object and does
    almost nothing with the data it holds: it does not execute a
    skill or a tool, does not call any Executor, Runtime, Workflow, or
    EventBus, and does not inspect ``plan.skills`` or ``plan.tools``.
    There is no execution method, no registration, no persistence, no
    serialization, and no eventing anywhere in this module. The one
    exception is ``with_state`` (Sprint 74) -- the single sanctioned
    state-transition method, which returns a brand-new
    ``ExecutionSession`` rather than mutating ``self``. The only
    methods this class defines at all are ``__post_init__``,
    ``__hash__``, and ``with_state``.

    Instances are frozen (immutable) -- once constructed, none of an
    ``ExecutionSession``'s fields can be reassigned. ``metadata`` is
    additionally locked down (see ``__post_init__``) so that mutating
    the original mapping passed in -- or attempting to mutate
    ``session.metadata`` itself -- has no effect on this instance
    after construction. This mirrors the same "freeze the mapping
    too" pattern ``Orchestration.skill_execution_plan.
    SkillExecutionPlan`` and its siblings already use for their own
    metadata/payload fields. ``plan`` is stored exactly as validated,
    with no copying or cloning.

    Attributes:
        plan: The ``SkillExecutionPlan`` this session wraps. Stored
            exactly as given -- never copied, cloned, or inspected.
        state: The lifecycle label for this session (e.g.
            ``"pending"``). Must be a non-empty ``str``.
        metadata: Optional contextual information about this session.
            Stored internally as an immutable ``MappingProxyType``
            snapshot of whatever mapping was passed in.
    """

    plan: SkillExecutionPlan
    state: str
    metadata: Mapping[str, Any]
    current_skill_index: int = 0

    def __post_init__(self) -> None:
        """Validate ``plan``, ``state``, and ``metadata``, and freeze
        ``metadata`` into an immutable snapshot.

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.metadata``) to a different object,
        but it does nothing to stop the *contents* of a mutable
        mapping from being changed out from under this
        ``ExecutionSession`` after construction. Wrapping a
        freshly-copied ``dict`` in ``MappingProxyType`` closes that
        gap: the ``metadata`` any caller observes is guaranteed to be
        exactly what it was at construction time, for the lifetime of
        this instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        Raises:
            ExecutionSessionError: if ``plan`` is not a
                ``SkillExecutionPlan`` instance; if ``state`` is not a
                ``str`` or is an empty string; or if ``metadata`` is
                not a ``Mapping``.
        """
        if not isinstance(self.plan, SkillExecutionPlan):
            raise ExecutionSessionError(
                f"ExecutionSession requires 'plan' to be a "
                f"SkillExecutionPlan instance; got {self.plan!r}"
            )

        if not isinstance(self.state, str) or not self.state:
            raise ExecutionSessionError(
                f"ExecutionSession requires 'state' to be a non-empty "
                f"str; got {self.state!r}"
            )

        if not isinstance(self.metadata, Mapping):
            raise ExecutionSessionError(
                f"ExecutionSession requires 'metadata' to be a "
                f"Mapping; got {self.metadata!r}"
            )

        if (
            not isinstance(self.current_skill_index, int)
            or isinstance(self.current_skill_index, bool)
            or self.current_skill_index < 0
        ):
            raise ExecutionSessionError(
                f"ExecutionSession requires 'current_skill_index' to "
                f"be an int >= 0; got {self.current_skill_index!r}"
            )

        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``id(self.plan)`` alone.

        ``plan`` is the natural identity for hashing this value
        object (mirroring ``Orchestration.skill_execution_plan.
        SkillExecutionPlan``, which likewise hashes by the object
        identity of one of its own fields rather than its contents).
        ``state`` and ``metadata`` are deliberately excluded from the
        hash -- ``metadata`` in particular is stored as a
        ``MappingProxyType`` snapshot, which is itself unhashable.

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two
        ``ExecutionSession`` instances are only ``==`` when *all
        three* fields match. Two ``ExecutionSession`` instances
        sharing the same ``plan`` object (and therefore the same
        ``id(plan)``) may differ in ``state``/``metadata`` and thus
        share a hash without being equal -- which is exactly what
        Python's hash/eq contract permits (it only requires equal
        objects to share a hash, never the reverse).
        """
        return hash(id(self.plan))

    def with_state(self, state: str) -> "ExecutionSession":
        """Return a new ``ExecutionSession`` with ``state`` replaced,
        leaving this instance completely unchanged (Phase 6 Sprint 74
        -- controlled session state transitions; execution remains
        disabled).

        This is the one sanctioned way to move a session along its
        lifecycle (e.g. ``pending`` -> ``ready``): rather than
        mutating ``state`` in place -- impossible anyway, since
        ``ExecutionSession`` is a frozen dataclass -- ``with_state``
        builds and returns a brand-new ``ExecutionSession`` instance
        carrying the requested ``state``, while ``plan`` and
        ``metadata`` are carried over from ``self`` **by identity**:
        the returned instance's ``plan`` is ``self.plan`` (the exact
        same object, never re-validated or cloned) and its
        ``metadata`` is ``self.metadata`` (the exact same
        already-frozen ``MappingProxyType`` snapshot, never rewrapped
        or re-copied). ``self`` itself is never touched -- no field
        of ``self`` is reassigned, and no method is called on
        ``self.plan`` or ``self.metadata``.

        Construction deliberately bypasses ``ExecutionSession.
        __init__``/``__post_init__`` (via ``object.__new__`` plus
        ``object.__setattr__`` -- the same sanctioned frozen-dataclass
        technique already used by ``__post_init__`` itself) precisely
        so that ``plan`` and ``metadata`` are not re-validated or
        re-copied a second time; only the new ``state`` argument is
        validated here, using the identical rule already enforced by
        ``__post_init__`` (must be a non-empty ``str``).

        Args:
            state: The new lifecycle label for the returned session.
                Must be a non-empty ``str``.

        Returns:
            A new ``ExecutionSession`` instance with the given
            ``state``, and with ``plan``/``metadata`` carried over
            from ``self`` by identity.

        Raises:
            ExecutionSessionError: if ``state`` is not a ``str`` or
                is an empty string. ``self`` is left completely
                unchanged, and no new instance is returned, when
                validation fails.
        """
        if not isinstance(state, str) or not state:
            raise ExecutionSessionError(
                f"ExecutionSession.with_state() requires 'state' to "
                f"be a non-empty str; got {state!r}"
            )

        new_session = object.__new__(ExecutionSession)
        object.__setattr__(new_session, "plan", self.plan)
        object.__setattr__(new_session, "state", state)
        object.__setattr__(new_session, "metadata", self.metadata)
        object.__setattr__(
            new_session, "current_skill_index", self.current_skill_index
        )
        return new_session

    def start(self) -> "ExecutionSession":
        """Return a new ``ExecutionSession`` transitioned from
        ``ready`` to ``running`` (Phase 7 Sprint 75 -- execution
        lifecycle: ``pending`` -> ``ready`` -> ``running``; execution
        of the wrapped plan itself remains disabled).

        This is the second sanctioned state-transition method
        (alongside ``with_state``, added in Sprint 74), specialized to
        the single ``ready`` -> ``running`` step: it requires
        ``self.state`` to already be ``"ready"`` -- any other current
        state raises ``ExecutionSessionError`` -- and otherwise builds
        and returns a brand-new ``ExecutionSession`` instance carrying
        the fixed ``state`` value ``"running"``, while ``plan`` and
        ``metadata`` are carried over from ``self`` **by identity**:
        the returned instance's ``plan`` is ``self.plan`` (the exact
        same object, never re-validated or cloned) and its
        ``metadata`` is ``self.metadata`` (the exact same
        already-frozen ``MappingProxyType`` snapshot, never rewrapped
        or re-copied). ``self`` itself is never touched -- no field of
        ``self`` is reassigned, and no method is called on
        ``self.plan`` or ``self.metadata``.

        Construction deliberately bypasses ``ExecutionSession.
        __init__``/``__post_init__`` (via ``object.__new__`` plus
        ``object.__setattr__`` -- the same sanctioned frozen-dataclass
        technique already used by ``__post_init__`` and ``with_state``)
        precisely so that ``plan`` and ``metadata`` are not
        re-validated or re-copied a second time.

        Returns:
            A new ``ExecutionSession`` instance with ``state``
            ``"running"``, and with ``plan``/``metadata`` carried over
            from ``self`` by identity.

        Raises:
            ExecutionSessionError: if ``self.state`` is not
                ``"ready"``. ``self`` is left completely unchanged,
                and no new instance is returned, when this check
                fails.
        """
        if self.state != "ready":
            raise ExecutionSessionError(
                f"ExecutionSession.start() requires current state to "
                f"be 'ready'; got {self.state!r}"
            )

        new_session = object.__new__(ExecutionSession)
        object.__setattr__(new_session, "plan", self.plan)
        object.__setattr__(new_session, "state", "running")
        object.__setattr__(new_session, "metadata", self.metadata)
        object.__setattr__(
            new_session, "current_skill_index", self.current_skill_index
        )
        return new_session

    def advance(self) -> "ExecutionSession":
        """Return a new ``ExecutionSession`` with ``current_skill_index``
        incremented by exactly one (Phase 7 Sprint 76 -- the execution
        cursor; still no Skill is executed and ``plan.skills`` is
        never read).

        This is the third sanctioned transition method (alongside
        ``with_state`` from Sprint 74 and ``start`` from Sprint 75),
        specialized to moving the session's execution cursor forward
        by one position: it requires ``self.state`` to already be
        ``"running"`` -- any other current state raises
        ``ExecutionSessionError`` -- and otherwise builds and returns
        a brand-new ``ExecutionSession`` instance carrying
        ``current_skill_index`` equal to ``self.current_skill_index +
        1``, while ``plan``, ``state``, and ``metadata`` are carried
        over from ``self`` **by identity/value**: the returned
        instance's ``plan`` is ``self.plan`` (the exact same object,
        never re-validated or cloned), its ``state`` is ``self.state``
        (the same string value, ``"running"``), and its ``metadata``
        is ``self.metadata`` (the exact same already-frozen
        ``MappingProxyType`` snapshot, never rewrapped or re-copied).
        ``self`` itself is never touched -- no field of ``self`` is
        reassigned, and no method is called on ``self.plan`` or
        ``self.metadata``. There is no bounds check against
        ``plan.skills`` (indeed ``plan.skills`` is never read at all)
        -- the cursor is simply incremented without regard to how many
        skills the wrapped plan actually holds.

        Construction deliberately bypasses ``ExecutionSession.
        __init__``/``__post_init__`` (via ``object.__new__`` plus
        ``object.__setattr__`` -- the same sanctioned frozen-dataclass
        technique already used by ``__post_init__``, ``with_state``,
        and ``start``) precisely so that ``plan`` and ``metadata`` are
        not re-validated or re-copied a second time.

        Returns:
            A new ``ExecutionSession`` instance with
            ``current_skill_index`` incremented by one, and with
            ``plan``/``state``/``metadata`` carried over from ``self``
            by identity/value.

        Raises:
            ExecutionSessionError: if ``self.state`` is not
                ``"running"``. ``self`` is left completely unchanged,
                and no new instance is returned, when this check
                fails.
        """
        if self.state != "running":
            raise ExecutionSessionError(
                f"ExecutionSession.advance() requires current state "
                f"to be 'running'; got {self.state!r}"
            )

        new_session = object.__new__(ExecutionSession)
        object.__setattr__(new_session, "plan", self.plan)
        object.__setattr__(new_session, "state", self.state)
        object.__setattr__(new_session, "metadata", self.metadata)
        object.__setattr__(
            new_session, "current_skill_index", self.current_skill_index + 1
        )
        return new_session