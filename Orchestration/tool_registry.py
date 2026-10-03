"""ToolRegistry -- a simple tool catalog (Phase 5, Sprint 56).

Scope note (LOCKED baseline): this module is a pure catalog and
nothing more. It implements exactly two things:

  1. ``ToolRegistryError`` -- the module's own exception type,
     following the same convention as ``SkillRegistryError``/
     ``GoalPlannerError``/``ObservationError`` (subclasses
     ``Core.exceptions.AgentError`` directly, no intermediate layer).
  2. ``ToolRegistry`` -- an in-memory catalog mapping a name (``str``)
     to a tool object. It stores and returns tools; it never
     executes, invokes, dispatches, resolves, validates the *shape*
     of, or otherwise interprets a tool in any way. A "tool" here is
     any Python object at all -- this module does not require,
     define, or import any base class or interface for it (no
     ``BaseTool``), and it does not import ``ToolDescriptor`` either.

This module is intentionally the mirror of
``Orchestration.skill_registry.SkillRegistry`` -- same shape, same
discipline, one layer down the stack (tools instead of skills).

Explicitly NOT part of this milestone: any execution surface (no
``run``/``execute``/``invoke``/``dispatch`` method anywhere on this
class), any routing or selection logic, any
manager/resolver/executor/runtime built on top of this catalog, any
singleton or module-level global registry instance, any service
locator, any auto-registration or auto-discovery, any coupling to
``ToolDescriptor``, and any wiring into ``BaseTool``,
``Orchestration.skill_registry.SkillRegistry``,
``Orchestration.skill_resolver.SkillResolver``,
``Agents.planner.Planner``, ``Orchestration.executor.Executor``,
``Orchestration.workflow_runtime.WorkflowRuntime``,
``Orchestration.workflow_engine.WorkflowEngine``,
``Orchestration.workflow_execution_coordinator.
WorkflowExecutionCoordinator``, ``Orchestration.event_bus.EventBus``,
``Orchestration.autonomous_scheduler.AutonomousScheduler``, ``Memory``,
``Orchestration.learning_loop.LearningLoop``,
``Orchestration.reflection``, or ``Core.composition_root``. This
module is not imported by, and does not import from, any of those. It
is additive-only, standing on its own until a future sprint builds a
resolver/executor on top of it.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError`` and the ``typing`` standard-library
module -- nothing else, not even ``Core.logger``.

Internal storage (LOCKED design constraint): a single, private, plain
``Dict[str, Any]`` -- no singleton, no module-level state, no
thread-safety machinery. Every ``ToolRegistry()`` instance owns its
own independent dictionary; two instances never share state.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from Core.exceptions import AgentError


class ToolRegistryError(AgentError):
    """Raised by :class:`ToolRegistry` for its own catalog-level
    failures.

    Following the same convention as ``SkillRegistryError``/
    ``GoalPlannerError``/``ObservationError`` (all subclass
    ``Core.exceptions.AgentError`` directly). Raised by
    :meth:`ToolRegistry.register` for an invalid ``name``, a ``None``
    ``tool``, or a duplicate ``name``; by :meth:`ToolRegistry.unregister`
    and :meth:`ToolRegistry.get` when ``name`` is not registered.
    Never raised by :meth:`ToolRegistry.has` or
    :meth:`ToolRegistry.list` -- a missing name is a normal, expected
    outcome for those two (see their own docstrings).
    """


class ToolRegistry:
    """A simple in-memory catalog of tool objects, keyed by name.

    Purely a catalog (LOCKED scope for Sprint 56): stores and returns
    whatever object it is given under a name, and nothing more. It
    never calls, inspects the shape of, executes, or dispatches to
    any tool it holds -- a tool is opaque to this class. No method
    here has any execution semantics.

    Holds one private, mutable collection internally (a
    ``Dict[str, Any]``) but never exposes it, its ``.values()`` view,
    or any other live reference to it -- :meth:`list` always returns a
    fresh, independent ``tuple`` snapshot.
    """

    def __init__(self) -> None:
        """Start empty. No dependencies -- ``ToolRegistry`` does not
        call a Service, ``BaseTool``, ``ToolDescriptor``, Planner,
        Runtime, Executor, or Provider, so it has nothing to be
        constructed with. No singleton, no module-level global: each
        instance owns its own independent dictionary."""
        self._tools: Dict[str, Any] = {}

    def register(self, name: str, tool: Any) -> None:
        """Register ``tool`` under ``name``.

        Args:
            name: The name to register ``tool`` under. Must be a
                non-empty ``str`` (whitespace-only is rejected).
            tool: The tool object to store. Must not be ``None``.
                Never inspected, validated for shape, or executed --
                any non-``None`` Python object is accepted as-is (no
                ``BaseTool`` requirement, no ``isinstance`` check).

        Raises:
            ToolRegistryError: If ``name`` is not a non-empty ``str``;
                if ``tool`` is ``None``; or if ``name`` is already
                registered (duplicate registration is rejected, not
                silently overwritten).
        """
        if not isinstance(name, str) or not name.strip():
            raise ToolRegistryError(
                f"ToolRegistry.register requires a non-empty str "
                f"'name'; got {name!r}"
            )

        if tool is None:
            raise ToolRegistryError(
                "ToolRegistry.register requires 'tool' to be not "
                "None."
            )

        if name in self._tools:
            raise ToolRegistryError(
                f"ToolRegistry.register: a tool is already "
                f"registered under name={name!r} -- duplicate "
                f"registration is not allowed.",
                details={"name": name},
            )

        self._tools[name] = tool

    def unregister(self, name: str) -> None:
        """Remove the tool registered under ``name``.

        Args:
            name: The name of the tool to remove.

        Raises:
            ToolRegistryError: If no tool is registered under
                ``name``.
        """
        if name not in self._tools:
            raise ToolRegistryError(
                f"ToolRegistry.unregister: no tool registered "
                f"under name={name!r}.",
                details={"name": name},
            )

        del self._tools[name]

    def get(self, name: str) -> Any:
        """Return the tool registered under ``name``.

        Args:
            name: The name of the tool to look up.

        Returns:
            The exact object previously passed to :meth:`register` --
            unmodified, unwrapped.

        Raises:
            ToolRegistryError: If no tool is registered under
                ``name``. A missing tool here is treated as a genuine
                misuse -- callers ask for a tool they expect to
                exist.
        """
        if name not in self._tools:
            raise ToolRegistryError(
                f"ToolRegistry.get: no tool registered under "
                f"name={name!r}.",
                details={"name": name},
            )

        return self._tools[name]

    def has(self, name: str) -> bool:
        """Return whether a tool is registered under ``name``.

        Args:
            name: The name to check.

        Returns:
            ``True`` if a tool is registered under ``name``, else
            ``False``. Never raises for a missing name -- an ordinary,
            expected query.
        """
        return name in self._tools

    def list(self) -> Tuple[str, ...]:
        """Return every registered tool name, in insertion order.

        Returns:
            A ``Tuple[str, ...]`` of every registered name, in the
            order each was first registered. Always a fresh ``tuple``
            snapshot -- never the internal ``dict``, its keys view, or
            any other object sharing live state with this registry.
            Mutating (or attempting to mutate) the returned tuple
            never affects the registry.
        """
        return tuple(self._tools.keys())