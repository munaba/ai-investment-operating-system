"""SkillRegistry -- a simple capability catalog (Phase 5, Sprint 43).

Scope note (LOCKED baseline): this module is a pure catalog and
nothing more. It implements exactly two things:

  1. ``SkillRegistryError`` -- the module's own exception type,
     following the same convention as ``GoalPlannerError``/
     ``MemoryError``/``ObservationError`` (subclasses
     ``Core.exceptions.AgentError`` directly, no intermediate layer).
  2. ``SkillRegistry`` -- an in-memory catalog mapping a name (``str``)
     to a skill object. It stores and returns skills; it never
     executes, routes, selects, validates the *shape* of, or otherwise
     interprets a skill in any way. A "skill" here is any Python
     object at all -- this module does not require, define, or import
     any base class or interface for it (no ``BaseSkill``).

Explicitly NOT part of this milestone: any execution surface (no
``run``/``execute``/``call`` method anywhere on this class), any
routing or selection logic, any manager/executor/resolver/runtime
built on top of this catalog, any singleton or module-level global
registry instance, and any wiring into ``Executor``, ``WorkflowEngine``,
``WorkflowRuntime``, ``WorkflowExecutionCoordinator``, ``GoalPlanner``,
``Memory``, ``LearningLoop``, ``Reflection``, ``AutonomousScheduler``,
``AutonomousHost``, ``AutonomousAgent``, or ``Core.composition_root``.
This module is not imported by, and does not import from, any of
those. It is additive-only, standing on its own until a future sprint
builds a resolver/executor on top of it.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError`` and the ``typing`` standard-library
module -- nothing else, not even ``Core.logger``.

Internal storage (LOCKED design constraint): a single, private, plain
``Dict[str, Any]`` -- no singleton, no module-level state, no
thread-safety machinery. Every ``SkillRegistry()`` instance owns its
own independent dictionary; two instances never share state.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from Core.exceptions import AgentError


class SkillRegistryError(AgentError):
    """Raised by :class:`SkillRegistry` for its own catalog-level
    failures.

    Following the same convention as ``GoalPlannerError``/
    ``MemoryError``/``ObservationError`` (all subclass
    ``Core.exceptions.AgentError`` directly). Raised by
    :meth:`SkillRegistry.register` for an invalid ``name``, a ``None``
    ``skill``, or a duplicate ``name``; by :meth:`SkillRegistry.unregister`
    and :meth:`SkillRegistry.get` when ``name`` is not registered.
    Never raised by :meth:`SkillRegistry.has` or
    :meth:`SkillRegistry.list` -- a missing name is a normal, expected
    outcome for those two (see their own docstrings).
    """


class SkillRegistry:
    """A simple in-memory catalog of capability objects, keyed by name.

    Purely a catalog (LOCKED scope for Sprint 43): stores and returns
    whatever object it is given under a name, and nothing more. It
    never calls, inspects the shape of, executes, or routes to any
    skill it holds -- a skill is opaque to this class, exactly as a
    ``ServiceSkill`` registry dict is opaque to whatever constructs
    it. No method here has any execution semantics.

    Holds one private, mutable collection internally (a
    ``Dict[str, Any]``) but never exposes it, its ``.values()`` view,
    or any other live reference to it -- :meth:`list` always returns a
    fresh, independent ``tuple`` snapshot.
    """

    def __init__(self) -> None:
        """Start empty. No dependencies -- ``SkillRegistry`` does not
        call a Service, ``ServiceSkill``, ``GoalPlanner``, Runtime,
        Executor, or Provider, so it has nothing to be constructed
        with. No singleton, no module-level global: each instance
        owns its own independent dictionary."""
        self._skills: Dict[str, Any] = {}

    def register(self, name: str, skill: Any) -> None:
        """Register ``skill`` under ``name``.

        Args:
            name: The name to register ``skill`` under. Must be a
                non-empty ``str`` (whitespace-only is rejected).
            skill: The skill object to store. Must not be ``None``.
                Never inspected, validated for shape, or executed --
                any non-``None`` Python object is accepted as-is.

        Raises:
            SkillRegistryError: If ``name`` is not a non-empty ``str``;
                if ``skill`` is ``None``; or if ``name`` is already
                registered (duplicate registration is rejected, not
                silently overwritten).
        """
        if not isinstance(name, str) or not name.strip():
            raise SkillRegistryError(
                f"SkillRegistry.register requires a non-empty str "
                f"'name'; got {name!r}"
            )

        if skill is None:
            raise SkillRegistryError(
                "SkillRegistry.register requires 'skill' to be not "
                "None."
            )

        if name in self._skills:
            raise SkillRegistryError(
                f"SkillRegistry.register: a skill is already "
                f"registered under name={name!r} -- duplicate "
                f"registration is not allowed.",
                details={"name": name},
            )

        self._skills[name] = skill

    def unregister(self, name: str) -> None:
        """Remove the skill registered under ``name``.

        Args:
            name: The name of the skill to remove.

        Raises:
            SkillRegistryError: If no skill is registered under
                ``name``.
        """
        if name not in self._skills:
            raise SkillRegistryError(
                f"SkillRegistry.unregister: no skill registered "
                f"under name={name!r}.",
                details={"name": name},
            )

        del self._skills[name]

    def get(self, name: str) -> Any:
        """Return the skill registered under ``name``.

        Args:
            name: The name of the skill to look up.

        Returns:
            The exact object previously passed to :meth:`register` --
            unmodified, unwrapped.

        Raises:
            SkillRegistryError: If no skill is registered under
                ``name``. Unlike ``MemoryStore.get`` (which returns
                ``None`` on a miss), a missing skill here is treated
                as a genuine misuse -- callers ask for a skill they
                expect to exist.
        """
        if name not in self._skills:
            raise SkillRegistryError(
                f"SkillRegistry.get: no skill registered under "
                f"name={name!r}.",
                details={"name": name},
            )

        return self._skills[name]

    def has(self, name: str) -> bool:
        """Return whether a skill is registered under ``name``.

        Args:
            name: The name to check.

        Returns:
            ``True`` if a skill is registered under ``name``, else
            ``False``. Never raises for a missing name -- an ordinary,
            expected query.
        """
        return name in self._skills

    def list(self) -> Tuple[str, ...]:
        """Return every registered skill name, in insertion order.

        Returns:
            A ``Tuple[str, ...]`` of every registered name, in the
            order each was first registered. Always a fresh ``tuple``
            snapshot -- never the internal ``dict``, its keys view, or
            any other object sharing live state with this registry.
            Mutating (or attempting to mutate) the returned tuple
            never affects the registry.
        """
        return tuple(self._skills.keys())