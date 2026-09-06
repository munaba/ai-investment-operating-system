"""CapabilityResolver -- resolves a capability name to the tuple of
skill names that implement it (Phase 5, Sprint 66).

Scope note (LOCKED baseline): this module implements exactly two
things:

  1. ``CapabilityResolverError`` -- the module's own exception type,
     following the same convention as ``ToolResolverError``/
     ``SkillResolverError``/``CapabilitySkillRegistryError``
     (subclasses ``Core.exceptions.AgentError`` directly, no
     intermediate layer).
  2. ``CapabilityResolver`` -- a single-method class that resolves a
     plain ``capability_name: str`` to the ``Tuple[str, ...]`` of
     skill names registered for it, via exact
     ``CapabilitySkillRegistry`` key match.

This module is the missing bridge answering the planner's future
question "I need capability X" with "capability X is implemented by
these skill names" -- and nothing more. It never resolves a skill
name to an actual skill object, never executes anything, never plans,
and never re-validates anything the ``CapabilitySkillRegistry`` itself
already validates. A "registry miss" is not this class's concern to
interpret -- it simply lets whatever ``CapabilitySkillRegistry.get``
raises propagate unchanged.

Explicitly NOT part of this milestone: any execution surface, any
routing or selection logic beyond exact delegation, any fuzzy/alias/
case-insensitive/whitespace-trimmed matching, any coupling to
``SkillRegistry``, ``SkillResolver``, ``ToolRegistry``,
``ToolResolver``, ``Executor``, ``Planner``, ``Workflow*``,
``Memory``, ``Reflection``, ``LearningLoop``, ``CapabilityRegistry``,
``CapabilityManager``, ``Capability``, ``BaseSkill``, ``BaseTool``,
``Core.composition_root``, ``Services``, ``Repository``,
``Providers``, ``Database``, or ``Agents``. This module is not
imported by, and does not import from, any of those.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError``,
``Orchestration.capability_skill_registry.CapabilitySkillRegistry``,
and the ``typing`` standard-library module -- nothing else.

Internal storage (LOCKED design constraint): exactly one private
attribute, ``self._capability_skill_registry``, holding the exact
object passed to the constructor by identity -- never copied, never
rebuilt. No other instance state, no module-level state, no
singleton.
"""

from __future__ import annotations

from typing import Tuple

from Core.exceptions import AgentError
from Orchestration.capability_skill_registry import CapabilitySkillRegistry


class CapabilityResolverError(AgentError):
    """Raised by :class:`CapabilityResolver` for its own
    resolution-level failures.

    Following the same convention as ``ToolResolverError``/
    ``SkillResolverError``/``CapabilitySkillRegistryError`` (all
    subclass ``Core.exceptions.AgentError`` directly). Raised by
    :class:`CapabilityResolver`'s constructor for an invalid
    ``capability_skill_registry`` argument, and by
    :meth:`CapabilityResolver.resolve` for an invalid
    ``capability_name`` argument. Never raised for a registry lookup
    miss -- that case propagates the registry's own
    ``CapabilitySkillRegistryError`` unchanged (see
    :meth:`CapabilityResolver.resolve`).
    """


class CapabilityResolver:
    """Resolves a capability name to the tuple of skill names
    registered for it, by exact ``capability_name`` match against a
    :class:`CapabilitySkillRegistry`.

    Purely a lookup (LOCKED scope for Sprint 66): this class never
    executes, calls, or invokes anything, never resolves a skill name
    to an actual skill object, never registers or unregisters
    anything on the ``CapabilitySkillRegistry`` it is given, and never
    applies any matching logic beyond
    ``capability_skill_registry.get(capability_name)``. It holds
    exactly one collaborator, ``self._capability_skill_registry`` --
    no other state.
    """

    def __init__(self, capability_skill_registry: CapabilitySkillRegistry) -> None:
        """Wire up the resolver via dependency injection only.

        Args:
            capability_skill_registry: The already-constructed
                ``CapabilitySkillRegistry`` to resolve against. Never
                constructed here, and no ``CapabilitySkillRegistry``
                is ever instantiated a second time by this class.
                Stored by identity -- never copied.

        Raises:
            CapabilityResolverError: If ``capability_skill_registry``
                is ``None`` or not a ``CapabilitySkillRegistry``
                instance.
        """
        if capability_skill_registry is None or not isinstance(
            capability_skill_registry, CapabilitySkillRegistry
        ):
            raise CapabilityResolverError(
                f"CapabilityResolver() requires "
                f"'capability_skill_registry' to be a "
                f"CapabilitySkillRegistry instance; got "
                f"{capability_skill_registry!r}"
            )

        self._capability_skill_registry = capability_skill_registry

    def resolve(self, capability_name: str) -> Tuple[str, ...]:
        """Resolve ``capability_name`` to the tuple of skill names
        registered for it, by exact match.

        Args:
            capability_name: The name of the capability to resolve.
                Must be a non-empty ``str`` (whitespace-only is
                rejected).

        Returns:
            The exact ``Tuple[str, ...]`` registered in the
            ``CapabilitySkillRegistry`` under ``capability_name`` --
            unmodified, unwrapped, never copied, never filtered,
            never sorted, never deduplicated. Equivalent to
            ``capability_skill_registry.get(capability_name)``,
            exactly.

        Raises:
            CapabilityResolverError: If ``capability_name`` is not a
                non-empty ``str``.
            CapabilitySkillRegistryError: Propagated unmodified from
                ``CapabilitySkillRegistry.get(capability_name)`` when
                no skill names are registered under that name --
                never caught or wrapped here.
        """
        if not isinstance(capability_name, str) or not capability_name.strip():
            raise CapabilityResolverError(
                f"CapabilityResolver.resolve requires 'capability_name' "
                f"to be a non-empty str; got {capability_name!r}"
            )

        return self._capability_skill_registry.get(capability_name)