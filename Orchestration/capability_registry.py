"""CapabilityRegistry -- a simple capability catalog (Phase 5,
Sprint 63).

Scope note (LOCKED baseline): this module is a pure catalog and
nothing more. It implements exactly two things:

  1. ``CapabilityRegistryError`` -- the module's own exception type,
     following the same convention as ``ToolRegistryError``/
     ``SkillRegistryError``/``GoalPlannerError``/``ObservationError``
     (subclasses ``Core.exceptions.AgentError`` directly, no
     intermediate layer).
  2. ``CapabilityRegistry`` -- an in-memory catalog mapping a name
     (``str``) to a capability object. It stores and returns
     capabilities; it never executes, invokes, dispatches, resolves,
     validates the *shape* of, or otherwise interprets a capability in
     any way. A "capability" here is any Python object at all -- this
     module does not require, define, or import any base class or
     interface for it (no ``Capability``), and it does not import
     ``Skill``, ``SkillDescriptor``, ``ToolDescriptor``, ``BaseSkill``,
     or ``BaseTool`` either.

This module is intentionally the mirror of
``Orchestration.tool_registry.ToolRegistry`` and
``Orchestration.skill_registry.SkillRegistry`` -- same shape, same
discipline, standing entirely on its own as a catalog for capability
objects.

Explicitly NOT part of this milestone: any execution surface (no
``run``/``execute``/``invoke``/``dispatch`` method anywhere on this
class), any routing or selection logic, any
manager/resolver/executor/runtime built on top of this catalog, any
singleton or module-level global registry instance, any service
locator, any auto-registration or auto-discovery, any coupling to
``Capability``, ``SkillDescriptor``, ``ToolDescriptor``, ``BaseSkill``,
or ``BaseTool``, and any wiring into ``Planner``, ``Skill``,
``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.tool_resolver.ToolResolver``,
``Orchestration.skill_registry.SkillRegistry``,
``Orchestration.skill_resolver.SkillResolver``,
``Orchestration.executor.Executor``,
``Orchestration.workflow_runtime.WorkflowRuntime``,
``Orchestration.workflow_engine.WorkflowEngine``,
``Orchestration.workflow_execution_coordinator.
WorkflowExecutionCoordinator``, ``Orchestration.event_bus.EventBus``,
``Memory``, ``Orchestration.learning_loop.LearningLoop``,
``Orchestration.reflection``, or ``Core.composition_root``. This
module is not imported by, and does not import from, any of those. It
is additive-only, standing on its own as a catalog.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError`` and the ``typing`` standard-library
module -- nothing else, not even ``Core.logger``.

Internal storage (LOCKED design constraint): a single, private, plain
``Dict[str, Any]`` -- no singleton, no module-level state, no
thread-safety machinery. Every ``CapabilityRegistry()`` instance owns
its own independent dictionary; two instances never share state.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from Core.exceptions import AgentError


class CapabilityRegistryError(AgentError):
    """Raised by :class:`CapabilityRegistry` for its own catalog-level
    failures.

    Following the same convention as ``ToolRegistryError``/
    ``SkillRegistryError``/``GoalPlannerError``/``ObservationError``
    (all subclass ``Core.exceptions.AgentError`` directly). Raised by
    :meth:`CapabilityRegistry.register` for an invalid ``name``, a
    ``None`` ``capability``, or a duplicate ``name``; by
    :meth:`CapabilityRegistry.unregister` and
    :meth:`CapabilityRegistry.get` when ``name`` is not registered.
    Never raised by :meth:`CapabilityRegistry.has` or
    :meth:`CapabilityRegistry.list` -- a missing name is a normal,
    expected outcome for those two (see their own docstrings).
    """


class CapabilityRegistry:
    """A simple in-memory catalog of capability objects, keyed by
    name.

    Purely a catalog (LOCKED scope for Sprint 63): stores and returns
    whatever object it is given under a name, and nothing more. It
    never calls, inspects the shape of, executes, or dispatches to any
    capability it holds -- a capability is opaque to this class. No
    method here has any execution semantics.

    Holds one private, mutable collection internally (a
    ``Dict[str, Any]``) but never exposes it, its ``.values()`` view,
    or any other live reference to it -- :meth:`list` always returns a
    fresh, independent ``tuple`` snapshot.
    """

    def __init__(self) -> None:
        """Start empty. No dependencies -- ``CapabilityRegistry`` does
        not call a Service, ``Capability``, ``SkillDescriptor``,
        ``ToolDescriptor``, Planner, Runtime, Executor, or Provider, so
        it has nothing to be constructed with. No singleton, no
        module-level global: each instance owns its own independent
        dictionary."""
        self._capabilities: Dict[str, Any] = {}

    def register(self, name: str, capability: Any) -> None:
        """Register ``capability`` under ``name``.

        Args:
            name: The name to register ``capability`` under. Must be
                a non-empty ``str`` (whitespace-only is rejected).
            capability: The capability object to store. Must not be
                ``None``. Never inspected, validated for shape, or
                executed -- any non-``None`` Python object is accepted
                as-is (no ``Capability`` requirement, no
                ``isinstance`` check).

        Raises:
            CapabilityRegistryError: If ``name`` is not a non-empty
                ``str``; if ``capability`` is ``None``; or if ``name``
                is already registered (duplicate registration is
                rejected, not silently overwritten).
        """
        if not isinstance(name, str) or not name.strip():
            raise CapabilityRegistryError(
                f"CapabilityRegistry.register requires a non-empty str "
                f"'name'; got {name!r}"
            )

        if capability is None:
            raise CapabilityRegistryError(
                "CapabilityRegistry.register requires 'capability' to "
                "be not None."
            )

        if name in self._capabilities:
            raise CapabilityRegistryError(
                f"CapabilityRegistry.register: a capability is already "
                f"registered under name={name!r} -- duplicate "
                f"registration is not allowed.",
                details={"name": name},
            )

        self._capabilities[name] = capability

    def unregister(self, name: str) -> None:
        """Remove the capability registered under ``name``.

        Args:
            name: The name of the capability to remove.

        Raises:
            CapabilityRegistryError: If no capability is registered
                under ``name``.
        """
        if name not in self._capabilities:
            raise CapabilityRegistryError(
                f"CapabilityRegistry.unregister: no capability "
                f"registered under name={name!r}.",
                details={"name": name},
            )

        del self._capabilities[name]

    def get(self, name: str) -> Any:
        """Return the capability registered under ``name``.

        Args:
            name: The name of the capability to look up.

        Returns:
            The exact object previously passed to :meth:`register` --
            unmodified, unwrapped.

        Raises:
            CapabilityRegistryError: If no capability is registered
                under ``name``. A missing capability here is treated
                as a genuine misuse -- callers ask for a capability
                they expect to exist.
        """
        if name not in self._capabilities:
            raise CapabilityRegistryError(
                f"CapabilityRegistry.get: no capability registered "
                f"under name={name!r}.",
                details={"name": name},
            )

        return self._capabilities[name]

    def has(self, name: str) -> bool:
        """Return whether a capability is registered under ``name``.

        Args:
            name: The name to check.

        Returns:
            ``True`` if a capability is registered under ``name``,
            else ``False``. Never raises for a missing name -- an
            ordinary, expected query.
        """
        return name in self._capabilities

    def list(self) -> Tuple[str, ...]:
        """Return every registered capability name, in insertion
        order.

        Returns:
            A ``Tuple[str, ...]`` of every registered name, in the
            order each was first registered. Always a fresh ``tuple``
            snapshot -- never the internal ``dict``, its keys view, or
            any other object sharing live state with this registry.
            Mutating (or attempting to mutate) the returned tuple
            never affects the registry.
        """
        return tuple(self._capabilities.keys())