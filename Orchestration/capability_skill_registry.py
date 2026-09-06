"""CapabilitySkillRegistry -- a simple mapping catalog declaring which
Skill names belong to a given Capability (Phase 5, Sprint 65).

Scope note (LOCKED baseline): this module is a pure metadata catalog
and nothing more. It implements exactly two things:

  1. ``CapabilitySkillRegistryError`` -- the module's own exception
     type, following the same convention as
     ``CapabilityRegistryError``/``SkillToolRegistryError``/
     ``ToolRegistryError``/``SkillRegistryError`` (subclasses
     ``Core.exceptions.AgentError`` directly, no intermediate layer).
  2. ``CapabilitySkillRegistry`` -- an in-memory catalog mapping a
     capability name (``str``) to a tuple of skill names
     (``Tuple[str, ...]``). It stores and returns the declared
     relationship; it never resolves, instantiates, executes, or
     validates the existence of any Capability or Skill. Both sides
     are plain, opaque strings -- this module does not require,
     define, or import ``Capability``, ``CapabilityRegistry``,
     ``CapabilityManager``, ``SkillRegistry``, ``SkillResolver``,
     ``SkillDescriptor``, or ``BaseSkill`` at all.

This sprint introduces exactly the structural relationship

    Capability
        |
        v
    Skill

the same way ``SkillToolRegistry`` declares the ``Skill -> Tool``
relationship without resolving or wiring either side --
``CapabilitySkillRegistry`` is a third, independent catalog that
merely *declares* which skill names a capability name is associated
with. It does not look either name up anywhere, does not check that a
capability or skill by that name actually exists, and does not wire
any other registry together.

Explicitly NOT part of this milestone: any execution surface (no
``run``/``execute``/``call``/``invoke``/``dispatch`` method anywhere
on this class), any routing or selection logic, any
resolver/executor/manager/runtime built on top of this catalog, any
singleton or module-level global registry instance, and any wiring
into ``Capability``, ``CapabilityRegistry``, ``CapabilityManager``,
``SkillRegistry``, ``SkillResolver``, ``SkillDescriptor``,
``BaseSkill``, ``ToolRegistry``, ``ToolResolver``, ``ToolManager``,
``Planner``, ``Workflow*``, ``Runtime*``, ``Executor``, ``Memory``,
``Reflection``, ``LearningLoop``, ``EventBus``, ``Repository``,
``Services``, ``Providers``, ``Database``, or
``Core.composition_root``. This module is not imported by, and does
not import from, any of those. It is additive-only, standing on its
own until a future sprint builds something that consumes this
declared relationship.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError`` and the ``typing`` standard-library
module -- nothing else, not even ``Core.logger``.

Internal storage (LOCKED design constraint): a single, private, plain
``Dict[str, Tuple[str, ...]]`` -- no singleton, no module-level
state, no thread-safety machinery. Every ``CapabilitySkillRegistry()``
instance owns its own independent dictionary; two instances never
share state.
"""

from __future__ import annotations

from typing import Dict, Tuple

from Core.exceptions import AgentError


class CapabilitySkillRegistryError(AgentError):
    """Raised by :class:`CapabilitySkillRegistry` for its own
    catalog-level failures.

    Following the same convention as ``CapabilityRegistryError``/
    ``SkillToolRegistryError``/``ToolRegistryError``/
    ``SkillRegistryError`` (all subclass ``Core.exceptions.AgentError``
    directly). Raised by :meth:`CapabilitySkillRegistry.register` for
    an invalid ``capability_name``, an invalid ``skill_names`` tuple,
    or a duplicate ``capability_name``; by
    :meth:`CapabilitySkillRegistry.unregister` and
    :meth:`CapabilitySkillRegistry.get` when ``capability_name`` is not
    registered. Never raised by :meth:`CapabilitySkillRegistry.has` or
    :meth:`CapabilitySkillRegistry.list` -- a missing name is a
    normal, expected outcome for those two (see their own
    docstrings).
    """


class CapabilitySkillRegistry:
    """A simple in-memory catalog declaring which skill names belong
    to a given capability name.

    Purely a catalog (LOCKED scope for Sprint 65): stores and returns
    the ``Tuple[str, ...]`` of skill names it is given under a
    capability name, and nothing more. It never resolves a capability
    name or a skill name against any other registry, never
    instantiates a Capability or a Skill, and never validates that
    either actually exists -- both ``capability_name`` and every entry
    of ``skill_names`` are opaque strings to this class.

    Holds one private, mutable collection internally (a
    ``Dict[str, Tuple[str, ...]]``) but never exposes it or any live
    reference to it -- :meth:`get` and :meth:`list` always return
    values (a ``tuple`` and its elements) that are independent of the
    registry's internal mutable state going forward.
    """

    def __init__(self) -> None:
        """Start empty. No dependencies -- ``CapabilitySkillRegistry``
        does not call ``CapabilityRegistry``, ``CapabilityManager``,
        ``SkillRegistry``, ``BaseSkill``, or any resolver, so it has
        nothing to be constructed with. No singleton, no module-level
        global: each instance owns its own independent dictionary."""
        self._mapping: Dict[str, Tuple[str, ...]] = {}

    def register(self, capability_name: str, skill_names: Tuple[str, ...]) -> None:
        """Declare that ``capability_name`` is associated with
        ``skill_names``.

        Args:
            capability_name: The capability name to register the
                skill names under. Must be a non-empty ``str``
                (whitespace-only is rejected).
            skill_names: The tuple of skill names associated with
                ``capability_name``. Must be a ``tuple`` whose every
                element is a non-empty ``str``, with no duplicate
                entries. Never inspected further, never resolved
                against any registry, and never checked for
                real-world existence.

        Raises:
            CapabilitySkillRegistryError: If ``capability_name`` is
                not a non-empty ``str``; if ``skill_names`` is not a
                ``tuple``; if any element of ``skill_names`` is not a
                non-empty ``str``; if ``skill_names`` contains
                duplicate entries; or if ``capability_name`` is
                already registered (duplicate registration is
                rejected, not silently overwritten).
        """
        if not isinstance(capability_name, str) or not capability_name.strip():
            raise CapabilitySkillRegistryError(
                f"CapabilitySkillRegistry.register requires a non-empty "
                f"str 'capability_name'; got {capability_name!r}"
            )

        if not isinstance(skill_names, tuple):
            raise CapabilitySkillRegistryError(
                f"CapabilitySkillRegistry.register requires "
                f"'skill_names' to be a tuple; got {skill_names!r}"
            )

        for skill_name in skill_names:
            if not isinstance(skill_name, str) or not skill_name.strip():
                raise CapabilitySkillRegistryError(
                    f"CapabilitySkillRegistry.register requires every "
                    f"'skill_names' element to be a non-empty str; got "
                    f"{skill_name!r}"
                )

        if len(set(skill_names)) != len(skill_names):
            raise CapabilitySkillRegistryError(
                f"CapabilitySkillRegistry.register requires "
                f"'skill_names' to contain no duplicate entries; got "
                f"{skill_names!r}"
            )

        if capability_name in self._mapping:
            raise CapabilitySkillRegistryError(
                f"CapabilitySkillRegistry.register: skill names are "
                f"already registered under "
                f"capability_name={capability_name!r} -- duplicate "
                f"registration is not allowed.",
                details={"capability_name": capability_name},
            )

        self._mapping[capability_name] = skill_names

    def unregister(self, capability_name: str) -> None:
        """Remove the skill-name tuple registered under
        ``capability_name``.

        Args:
            capability_name: The capability name whose mapping should
                be removed.

        Raises:
            CapabilitySkillRegistryError: If no skill names are
                registered under ``capability_name``.
        """
        if capability_name not in self._mapping:
            raise CapabilitySkillRegistryError(
                f"CapabilitySkillRegistry.unregister: no skill names "
                f"registered under capability_name={capability_name!r}.",
                details={"capability_name": capability_name},
            )

        del self._mapping[capability_name]

    def get(self, capability_name: str) -> Tuple[str, ...]:
        """Return the tuple of skill names registered under
        ``capability_name``.

        Args:
            capability_name: The capability name to look up.

        Returns:
            The exact ``Tuple[str, ...]`` previously passed to
            :meth:`register` -- unmodified, unwrapped.

        Raises:
            CapabilitySkillRegistryError: If no skill names are
                registered under ``capability_name``. A missing
                capability name here is treated as a genuine misuse
                -- callers ask for a mapping they expect to exist.
        """
        if capability_name not in self._mapping:
            raise CapabilitySkillRegistryError(
                f"CapabilitySkillRegistry.get: no skill names "
                f"registered under capability_name={capability_name!r}.",
                details={"capability_name": capability_name},
            )

        return self._mapping[capability_name]

    def has(self, capability_name: str) -> bool:
        """Return whether skill names are registered under
        ``capability_name``.

        Args:
            capability_name: The capability name to check.

        Returns:
            ``True`` if skill names are registered under
            ``capability_name``, else ``False``. Never raises for a
            missing name -- an ordinary, expected query.
        """
        return capability_name in self._mapping

    def list(self) -> Tuple[str, ...]:
        """Return every registered capability name, in insertion
        order.

        Returns:
            A ``Tuple[str, ...]`` of every registered capability
            name, in the order each was first registered. Always a
            fresh ``tuple`` snapshot -- never the internal ``dict``,
            its keys view, or any other object sharing live state
            with this registry. Mutating (or attempting to mutate)
            the returned tuple never affects the registry.
        """
        return tuple(self._mapping.keys())