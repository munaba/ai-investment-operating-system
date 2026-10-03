

from __future__ import annotations

from typing import Any

from Core.exceptions import AgentError
from Orchestration.tool_registry import ToolRegistry


class ToolResolverError(AgentError):
    """Raised by :class:`ToolResolver` for its own resolution-level
    failures.

    Following the same convention as ``ToolRegistryError``/
    ``SkillResolverError``/``SkillRegistryError`` (all subclass
    ``Core.exceptions.AgentError`` directly). Raised by
    :class:`ToolResolver`'s constructor for an invalid
    ``tool_registry`` argument, and by :meth:`ToolResolver.resolve`
    for an invalid ``tool_name`` argument. Never raised for a
    registry lookup miss -- that case propagates the registry's own
    ``ToolRegistryError`` unchanged (see :meth:`ToolResolver.resolve`).
    """


class ToolResolver:
    """Resolves a tool name to a registered tool by exact
    ``tool_name`` match against a :class:`ToolRegistry`.

    Purely a lookup (LOCKED scope for Sprint 57): this class never
    executes, calls, or invokes anything it resolves, never registers
    or unregisters anything on the ``ToolRegistry`` it is given, and
    never applies any matching logic beyond
    ``tool_registry.get(tool_name)``. It holds exactly one
    collaborator, ``self._tool_registry`` -- no other state.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        """Wire up the resolver via dependency injection only.

        Args:
            tool_registry: The already-constructed ``ToolRegistry``
                to resolve against. Never constructed here, and no
                ``ToolRegistry`` is ever instantiated a second time by
                this class. Stored by identity -- never copied.

        Raises:
            ToolResolverError: If ``tool_registry`` is ``None`` or
                not a ``ToolRegistry`` instance.
        """
        if tool_registry is None or not isinstance(tool_registry, ToolRegistry):
            raise ToolResolverError(
                f"ToolResolver() requires 'tool_registry' to be a "
                f"ToolRegistry instance; got {tool_registry!r}"
            )

        self._tool_registry = tool_registry

    def resolve(self, tool_name: str) -> Any:
        """Resolve ``tool_name`` to a registered tool by exact match.

        Args:
            tool_name: The name of the tool to resolve. Must be a
                non-empty ``str`` (whitespace-only is rejected).

        Returns:
            The exact object registered in the ``ToolRegistry`` under
            ``tool_name`` -- unmodified, unwrapped, never called or
            executed. Equivalent to
            ``tool_registry.get(tool_name)``, exactly.

        Raises:
            ToolResolverError: If ``tool_name`` is not a non-empty
                ``str``.
            ToolRegistryError: Propagated unmodified from
                ``ToolRegistry.get(tool_name)`` when no tool is
                registered under that name -- never caught or wrapped
                here.
        """
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ToolResolverError(
                f"ToolResolver.resolve requires 'tool_name' to be a "
                f"non-empty str; got {tool_name!r}"
            )

        return self._tool_registry.get(tool_name)