"""ToolManager -- a single facade through which future Skills will
access Tools (Phase 5, Sprint 59).

Scope note (LOCKED baseline): this module introduces ONLY a very
small orchestration layer. It is not execution, not a runtime, not a
planner, and not autonomous reasoning of any kind. It implements
exactly two things:

  1. ``ToolManagerError`` -- the module's own exception type,
     following the same convention as ``ToolRegistryError``/
     ``ToolResolverError``/``WorkflowManagerError`` (subclasses
     ``Core.exceptions.AgentError`` directly, no intermediate layer).
  2. ``ToolManager`` -- a thin facade that wraps an already-constructed
     ``Orchestration.tool_registry.ToolRegistry`` and an
     already-constructed ``Orchestration.tool_resolver.ToolResolver``,
     and does nothing but delegate to them.

``ToolManager`` owns ZERO business logic. Every one of its five public
methods (``register``, ``resolve``, ``has``, ``list``, ``unregister``)
is a one-line delegation to the corresponding method on
``ToolRegistry`` or ``ToolResolver`` -- no caching, no execution, no
invocation, no dispatch, no routing, no planner logic, no runtime
logic, no workflow logic, no event publishing, no memory, no
reflection, no learning, no capability matching, no metadata lookup,
no alias lookup, no normalization, no fuzzy matching, no auto
registration, and no singleton.

Explicitly NOT part of this milestone: any execution surface, any
routing or selection logic beyond exact delegation, any coupling to
``BaseTool``/``BaseSkill``/``SkillRegistry``/``SkillResolver``/
``Planner``/``Executor``/``WorkflowRuntime``/``WorkflowEngine``/
``WorkflowExecutionCoordinator``/``Memory``/``Reflection``/
``LearningLoop``/``EventBus``/``Services``/``Repositories``/
``Providers``/``Database``/``Core.composition_root``. This module is
not imported by, and does not import from, any of those.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError``, ``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.tool_resolver.ToolResolver``, and the ``typing``
standard-library module -- nothing else.

Internal storage (LOCKED design constraint): exactly two private
attributes, ``self._tool_registry`` and ``self._tool_resolver``,
holding the exact objects passed to the constructor by identity --
never copied, never wrapped, never rebuilt. No other instance state,
no module-level state, no singleton.
"""

from __future__ import annotations

from typing import Any, Tuple

from Core.exceptions import AgentError
from Orchestration.tool_registry import ToolRegistry
from Orchestration.tool_resolver import ToolResolver


class ToolManagerError(AgentError):
    """Raised by :class:`ToolManager` for its own facade-level
    failures.

    Following the same convention as ``ToolRegistryError``/
    ``ToolResolverError``/``WorkflowManagerError`` (all subclass
    ``Core.exceptions.AgentError`` directly). Raised only by
    :class:`ToolManager`'s constructor for an invalid ``tool_registry``
    or ``tool_resolver`` argument. Never raised by any of the five
    public methods themselves -- those propagate whatever
    ``ToolRegistry``/``ToolResolver`` raise, unmodified and unwrapped.
    """


class ToolManager:
    """A single facade through which future Skills will access Tools.

    ``ToolManager`` wraps an already-constructed ``ToolRegistry`` and
    an already-constructed ``ToolResolver`` and does nothing but
    delegate to them (LOCKED scope for Sprint 59). It performs no
    validation of arguments beyond the constructor, no business
    logic, no caching, and no execution of any kind -- every public
    method is a direct, one-line delegation to its collaborator.

    Both collaborators are stored by identity, never copied, and
    never reconstructed. ``ToolManager`` never constructs a
    ``ToolRegistry`` or ``ToolResolver`` itself -- both must already
    exist and are supplied via dependency injection only.
    """

    def __init__(self, tool_registry: ToolRegistry, tool_resolver: ToolResolver) -> None:
        """Wire up the manager via dependency injection only.

        Args:
            tool_registry: The already-constructed ``ToolRegistry``
                to delegate ``register``/``has``/``list``/
                ``unregister`` calls to. Stored by identity -- never
                copied.
            tool_resolver: The already-constructed ``ToolResolver``
                to delegate ``resolve`` calls to. Stored by identity
                -- never copied.

        Raises:
            ToolManagerError: If ``tool_registry`` is not a
                ``ToolRegistry`` instance, or ``tool_resolver`` is not
                a ``ToolResolver`` instance.
        """
        if tool_registry is None or not isinstance(tool_registry, ToolRegistry):
            raise ToolManagerError(
                f"ToolManager() requires 'tool_registry' to be a "
                f"ToolRegistry instance; got {tool_registry!r}"
            )

        if tool_resolver is None or not isinstance(tool_resolver, ToolResolver):
            raise ToolManagerError(
                f"ToolManager() requires 'tool_resolver' to be a "
                f"ToolResolver instance; got {tool_resolver!r}"
            )

        self._tool_registry = tool_registry
        self._tool_resolver = tool_resolver

    def register(self, name: str, tool: Any) -> None:
        """Delegate directly to ``ToolRegistry.register(name, tool)``.

        Args:
            name: The name to register ``tool`` under.
            tool: The tool object to store.

        Raises:
            ToolRegistryError: Propagated unmodified from
                ``ToolRegistry.register`` -- never caught or wrapped
                here.
        """
        return self._tool_registry.register(name, tool)

    def resolve(self, name: str) -> Any:
        """Delegate directly to ``ToolResolver.resolve(name)``.

        Args:
            name: The name of the tool to resolve.

        Returns:
            Whatever ``ToolResolver.resolve`` returns, unmodified and
            unwrapped.

        Raises:
            ToolResolverError: Propagated unmodified from
                ``ToolResolver.resolve`` -- never caught or wrapped
                here.
            ToolRegistryError: Propagated unmodified from
                ``ToolResolver.resolve`` -- never caught or wrapped
                here.
        """
        return self._tool_resolver.resolve(name)

    def has(self, name: str) -> bool:
        """Delegate directly to ``ToolRegistry.has(name)``.

        Args:
            name: The name to check.

        Returns:
            Whatever ``ToolRegistry.has`` returns, unmodified.
        """
        return self._tool_registry.has(name)

    def list(self) -> Tuple[str, ...]:
        """Delegate directly to ``ToolRegistry.list()``.

        Returns:
            Whatever ``ToolRegistry.list`` returns, unmodified.
        """
        return self._tool_registry.list()

    def unregister(self, name: str) -> None:
        """Delegate directly to ``ToolRegistry.unregister(name)``.

        Args:
            name: The name of the tool to remove.

        Raises:
            ToolRegistryError: Propagated unmodified from
                ``ToolRegistry.unregister`` -- never caught or
                wrapped here.
        """
        return self._tool_registry.unregister(name)