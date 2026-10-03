"""SkillResolver -- maps a ``Task`` to a registered skill by exact
name match (Phase 5, Sprint 44).

Scope note (LOCKED baseline): this module is the missing link between
``Task`` and ``Orchestration.skill_registry.SkillRegistry`` -- and
nothing more. It implements exactly two things:

  1. ``SkillResolverError`` -- the module's own exception type,
     following the same convention as ``GoalPlannerError``/
     ``SkillRegistryError``/``MemoryError`` (subclasses
     ``Core.exceptions.AgentError`` directly, no intermediate layer).
  2. ``SkillResolver`` -- one class, constructed with a
     ``SkillRegistry`` and exposing a single public method,
     :meth:`resolve`, which looks up ``task.name`` in that registry
     via exact string match and returns whatever skill object is
     registered under it.

Explicitly NOT part of this milestone: any execution (no ``call``/
``execute``/``run``/``invoke``/``dispatch`` method anywhere on this
class, and this class never calls one on anything it resolves), any
routing engine, any fuzzy/alias/metadata-based/scored/embedding-based
matching, any Planner integration, any AI, and any wiring into
``Executor``, ``WorkflowRuntime``, ``WorkflowEngine``,
``WorkflowExecutionCoordinator``, ``GoalPlanner``, ``Memory``,
``Reflection``, ``LearningLoop``, ``AutonomousScheduler``,
``AutonomousHost``, ``AutonomousAgent``, ``EventBus``, or
``Core.composition_root``. This module is not imported by, and does
not import from, any of those. It is additive-only, standing on its
own until a future sprint wires it up.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError``, ``Orchestration.task.Task``,
``Orchestration.skill_registry.SkillRegistry``, and the stdlib
``typing`` module -- nothing else.

Resolution rule (LOCKED, intentionally simple): ``task.name`` is used
verbatim as the lookup key into the ``SkillRegistry`` --
``registry.get(task.name)``. No transformation, normalization,
aliasing, or fallback of any kind is applied to the name before the
lookup; ``task.description`` and ``task.metadata`` are never read by
this module at all.
"""

from __future__ import annotations

from typing import Any

from Core.exceptions import AgentError
from Orchestration.skill_registry import SkillRegistry
from Orchestration.task import Task


class SkillResolverError(AgentError):
    """Raised by :class:`SkillResolver` for its own resolution-level
    failures.

    Following the same convention as ``GoalPlannerError``/
    ``SkillRegistryError``/``MemoryError`` (all subclass
    ``Core.exceptions.AgentError`` directly). Raised by
    :class:`SkillResolver`'s constructor for an invalid
    ``skill_registry`` argument, and by :meth:`SkillResolver.resolve`
    for a ``None`` or non-``Task`` ``task`` argument. Never raised for
    a registry lookup miss -- that case propagates the registry's own
    ``SkillRegistryError`` unchanged (see :meth:`SkillResolver.resolve`).
    """


class SkillResolver:
    """Resolves a ``Task`` to a registered skill by exact
    ``task.name`` match against a :class:`SkillRegistry`.

    Purely a lookup (LOCKED scope for Sprint 44): this class never
    executes, calls, or invokes anything it resolves, never registers
    or unregisters anything on the ``SkillRegistry`` it is given, and
    never applies any matching logic beyond
    ``skill_registry.get(task.name)``. It holds exactly one
    collaborator, ``self._skill_registry`` -- no other state.
    """

    def __init__(self, skill_registry: SkillRegistry) -> None:
        """Wire up the resolver via dependency injection only.

        Args:
            skill_registry: The already-constructed ``SkillRegistry``
                to resolve against. Never constructed here, and no
                ``SkillRegistry`` is ever instantiated a second time
                by this class.

        Raises:
            SkillResolverError: If ``skill_registry`` is ``None`` or
                not a ``SkillRegistry`` instance.
        """
        if skill_registry is None or not isinstance(skill_registry, SkillRegistry):
            raise SkillResolverError(
                f"SkillResolver() requires 'skill_registry' to be a "
                f"SkillRegistry instance; got {skill_registry!r}"
            )

        self._skill_registry = skill_registry

    def resolve(self, task: Task) -> Any:
        """Resolve ``task`` to a registered skill by exact
        ``task.name`` match.

        Reads only ``task.name`` -- ``task.description`` and
        ``task.metadata`` are never inspected. The order skills were
        registered in is irrelevant: this is a direct key lookup, not
        a scan.

        Args:
            task: The ``Task`` to resolve. Must be a ``Task``
                instance.

        Returns:
            The exact object registered in the ``SkillRegistry``
            under ``task.name`` -- unmodified, unwrapped, never
            called or executed.

        Raises:
            SkillResolverError: If ``task`` is ``None`` or not a
                ``Task`` instance.
            SkillRegistryError: Propagated unmodified from
                ``SkillRegistry.get(task.name)`` when no skill is
                registered under that name -- never caught or
                wrapped here.
        """
        if task is None or not isinstance(task, Task):
            raise SkillResolverError(
                f"SkillResolver.resolve requires 'task' to be a Task "
                f"instance; got {task!r}"
            )

        return self._skill_registry.get(task.name)