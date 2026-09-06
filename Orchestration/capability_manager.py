"""CapabilityManager -- the single facade through which future Skills
and the Planner will access Capabilities (Phase 5, Sprint 67).

Scope note (LOCKED baseline): this module introduces ONLY a very
small orchestration layer. It is not execution, not a runtime, not a
planner, and not autonomous reasoning of any kind. It implements
exactly two things:

  1. ``CapabilityManagerError`` -- the module's own exception type,
     following the same convention as ``CapabilityRegistryError``/
     ``CapabilityResolverError``/``ToolRegistryError``/
     ``ToolManagerError`` (subclasses ``Core.exceptions.AgentError``
     directly, no intermediate layer).
  2. ``CapabilityManager`` -- a thin facade that wraps an
     already-constructed
     ``Orchestration.capability_registry.CapabilityRegistry`` and an
     already-constructed
     ``Orchestration.capability_resolver.CapabilityResolver``, and
     does nothing but delegate to them.

``CapabilityManager`` owns ZERO business logic. Every one of its six
public methods (``register``, ``get``, ``has``, ``list``,
``unregister``, ``resolve``) is a one-line delegation to the
corresponding method on ``CapabilityRegistry`` or
``CapabilityResolver`` -- no caching, no execution, no invocation, no
dispatch, no routing, no planner logic, no runtime logic, no
workflow logic, no event publishing, no memory, no reflection, no
learning, no matching, no metadata lookup, no alias lookup, no
normalization, no lowercasing, no trimming, no fuzzy matching, no
sorting, no filtering, no deduplication, no wrapping of exceptions,
no auto registration, and no singleton.

This sprint upgrades ``CapabilityManager`` from a
``CapabilityRegistry``-only facade (Sprint 64) into the single facade
for capability access -- wiring in ``CapabilityResolver`` (Sprint 66)
alongside it -- so that a future Planner will eventually only need a
``CapabilityManager``, not both a registry and a resolver directly.
This sprint is NOT about Planner integration; it is only about wiring
``CapabilityManager`` to ``CapabilityResolver``.

Explicitly NOT part of this milestone: any execution surface, any
routing or selection logic beyond exact delegation, any coupling to
``Capability``/``Planner``/``SkillRegistry``/``SkillResolver``/
``ToolRegistry``/``ToolResolver``/``ToolManager``/``Workflow*``/
``Runtime*``/``Executor``/``Memory``/``Reflection``/``LearningLoop``/
``EventBus``/``Providers``/``Services``/``Repository``/``Database``/
``Core.composition_root``. This module is not imported by, and does
not import from, any of those. ``CapabilityManager`` never
constructs a ``CapabilityRegistry`` or ``CapabilityResolver`` itself,
never instantiates a ``Capability`` or a Skill, and never accesses
``SkillRegistry``, ``SkillResolver``, ``ToolRegistry``,
``ToolResolver``, ``Planner``, ``Executor``, ``Workflow``,
``Runtime``, ``Memory``, or ``EventBus``.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError``,
``Orchestration.capability_registry.CapabilityRegistry``,
``Orchestration.capability_resolver.CapabilityResolver``, and the
``typing`` standard-library module -- nothing else.

Internal storage (LOCKED design constraint): exactly two private
attributes, ``self._capability_registry`` and
``self._capability_resolver``, holding the exact objects passed to
the constructor by identity -- never copied, never rebuilt. No other
instance state, no module-level state, no singleton, no cache.
"""

from __future__ import annotations

from typing import Any, Tuple

from Core.exceptions import AgentError
from Orchestration.capability_registry import CapabilityRegistry
from Orchestration.capability_resolver import CapabilityResolver


class CapabilityManagerError(AgentError):
    """Raised by :class:`CapabilityManager` for its own facade-level
    failures.

    Following the same convention as ``CapabilityRegistryError``/
    ``CapabilityResolverError``/``ToolRegistryError``/
    ``ToolManagerError`` (all subclass ``Core.exceptions.AgentError``
    directly). Raised only by :class:`CapabilityManager`'s
    constructor for an invalid ``capability_registry`` or
    ``capability_resolver`` argument. Never raised by any of the six
    public methods themselves -- those propagate whatever
    ``CapabilityRegistry``/``CapabilityResolver`` raise, unmodified
    and unwrapped.
    """


class CapabilityManager:
    """The single facade through which future Skills and the Planner
    will access Capabilities.

    ``CapabilityManager`` wraps an already-constructed
    ``CapabilityRegistry`` and an already-constructed
    ``CapabilityResolver`` and does nothing but delegate to them
    (LOCKED scope for Sprint 67). It performs no validation of
    arguments beyond the constructor, no business logic, no caching,
    and no execution of any kind -- every public method is a direct,
    one-line delegation to its collaborator.

    Both collaborators are stored by identity, never copied, and
    never reconstructed. ``CapabilityManager`` never constructs a
    ``CapabilityRegistry`` or ``CapabilityResolver`` itself -- both
    must already exist and are supplied via dependency injection
    only.
    """

    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        capability_resolver: CapabilityResolver,
    ) -> None:
        """Wire up the manager via dependency injection only.

        Args:
            capability_registry: The already-constructed
                ``CapabilityRegistry`` to delegate ``register``/
                ``get``/``has``/``list``/``unregister`` calls to.
                Stored by identity -- never copied.
            capability_resolver: The already-constructed
                ``CapabilityResolver`` to delegate ``resolve`` calls
                to. Stored by identity -- never copied.

        Raises:
            CapabilityManagerError: If ``capability_registry`` is not
                a ``CapabilityRegistry`` instance, or
                ``capability_resolver`` is not a
                ``CapabilityResolver`` instance.
        """
        if capability_registry is None or not isinstance(
            capability_registry, CapabilityRegistry
        ):
            raise CapabilityManagerError(
                f"CapabilityManager() requires 'capability_registry' to be "
                f"a CapabilityRegistry instance; got {capability_registry!r}"
            )

        if capability_resolver is None or not isinstance(
            capability_resolver, CapabilityResolver
        ):
            raise CapabilityManagerError(
                f"CapabilityManager() requires 'capability_resolver' to be "
                f"a CapabilityResolver instance; got {capability_resolver!r}"
            )

        self._capability_registry = capability_registry
        self._capability_resolver = capability_resolver

    def register(self, name: str, capability: Any) -> None:
        """Delegate directly to
        ``CapabilityRegistry.register(name, capability)``.

        Args:
            name: The name to register ``capability`` under.
            capability: The capability object to store.

        Raises:
            CapabilityRegistryError: Propagated unmodified from
                ``CapabilityRegistry.register`` -- never caught or
                wrapped here.
        """
        return self._capability_registry.register(name, capability)

    def get(self, name: str) -> Any:
        """Delegate directly to ``CapabilityRegistry.get(name)``.

        Args:
            name: The name of the capability to look up.

        Returns:
            Whatever ``CapabilityRegistry.get`` returns, unmodified
            and unwrapped.

        Raises:
            CapabilityRegistryError: Propagated unmodified from
                ``CapabilityRegistry.get`` -- never caught or wrapped
                here.
        """
        return self._capability_registry.get(name)

    def has(self, name: str) -> bool:
        """Delegate directly to ``CapabilityRegistry.has(name)``.

        Args:
            name: The name to check.

        Returns:
            Whatever ``CapabilityRegistry.has`` returns, unmodified.
        """
        return self._capability_registry.has(name)

    def list(self) -> Tuple[str, ...]:
        """Delegate directly to ``CapabilityRegistry.list()``.

        Returns:
            Whatever ``CapabilityRegistry.list`` returns, unmodified.
        """
        return self._capability_registry.list()

    def unregister(self, name: str) -> None:
        """Delegate directly to
        ``CapabilityRegistry.unregister(name)``.

        Args:
            name: The name of the capability to remove.

        Raises:
            CapabilityRegistryError: Propagated unmodified from
                ``CapabilityRegistry.unregister`` -- never caught or
                wrapped here.
        """
        return self._capability_registry.unregister(name)

    def resolve(self, capability_name: str) -> Tuple[str, ...]:
        """Delegate directly to
        ``CapabilityResolver.resolve(capability_name)``.

        Args:
            capability_name: The name of the capability to resolve.

        Returns:
            Whatever ``CapabilityResolver.resolve`` returns,
            unmodified and unwrapped.

        Raises:
            CapabilityResolverError: Propagated unmodified from
                ``CapabilityResolver.resolve`` -- never caught or
                wrapped here.
            CapabilitySkillRegistryError: Propagated unmodified from
                ``CapabilityResolver.resolve`` -- never caught or
                wrapped here.
        """
        return self._capability_resolver.resolve(capability_name)