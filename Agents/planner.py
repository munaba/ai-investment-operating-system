"""Planner: decides the next step an agent should take.

Architecture Notes:
    ``Providers.ProviderManager`` (finished layer) does not expose a
    "default provider" concept -- only ``register(name, provider)``,
    ``get(name)``, ``list()``, ``exists(name)`` and ``unregister(name)``.
    To let an agent be created without forcing every call site to name a
    provider explicitly, ``Planner`` accepts an optional
    ``default_provider_name`` and, failing that, falls back to the first
    name returned by ``provider_manager.list()``. This is purely additive
    behaviour built on top of the existing public API; ``ProviderManager``
    itself is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from Core.exceptions import AgentError
from Providers import BaseProvider, Message, ProviderManager
from Agents.tool_registry import ToolRegistry


class PlannerError(AgentError):
    """Raised when the planner cannot produce a valid plan.

    Additive subclass of ``Core.exceptions.AgentError``.
    """


#: A strategy that decides whether a given message should trigger tool use.
#: Defaults to a simple keyword-based heuristic (see ``_default_tool_trigger``)
#: but can be swapped for a smarter (e.g. LLM-based) implementation without
#: touching the ``Planner`` public interface.
ToolTriggerStrategy = Callable[[Message, ToolRegistry], Optional[str]]


@dataclass(frozen=True)
class Plan:
    """The outcome of :meth:`Planner.plan`.

    Attributes:
        use_tool: Whether a tool should be called before hitting the
            provider.
        provider: The provider selected to fulfil this turn.
        tool_name: Name of the tool to call, when ``use_tool`` is ``True``.
    """

    use_tool: bool
    provider: BaseProvider
    tool_name: Optional[str] = None


def _default_tool_trigger(message: Message, tool_registry: ToolRegistry) -> Optional[str]:
    """Default heuristic: trigger a tool if its name literally appears
    (case-insensitively) inside the message content.
    """
    content = message.content.lower()
    for tool in tool_registry.list():
        if tool.name.lower() in content:
            return tool.name
    return None


class Planner:
    """Decides what an agent should do next for a given message.

    The planner never talks to a provider or a tool directly; it only
    decides *what* should happen. Execution is delegated to
    :class:`Agents.executor.Executor` and provider calls are made by the
    agent itself using the provider returned from :meth:`select_provider`.
    """

    def __init__(
        self,
        provider_manager: ProviderManager,
        tool_registry: ToolRegistry,
        default_provider_name: Optional[str] = None,
        tool_trigger_strategy: Optional[ToolTriggerStrategy] = None,
    ) -> None:
        self._provider_manager = provider_manager
        self._tool_registry = tool_registry
        self._default_provider_name = default_provider_name
        self._tool_trigger_strategy = tool_trigger_strategy or _default_tool_trigger

    def should_use_tool(self, message: Message) -> Optional[str]:
        """Return the tool name to use for ``message``, or ``None``."""
        return self._tool_trigger_strategy(message, self._tool_registry)

    def select_provider(self, provider_name: Optional[str] = None) -> BaseProvider:
        """Select which provider should handle the current turn.

        Args:
            provider_name: Optional explicit provider name. When omitted,
                ``default_provider_name`` (set at construction time) is
                used; if that is also unset, the first provider registered
                in ``ProviderManager`` is used.

        Raises:
            PlannerError: If no provider name can be resolved (i.e. no
                provider is registered at all).
        """
        name = provider_name or self._default_provider_name
        if name is None:
            registered = self._provider_manager.list()
            if not registered:
                raise PlannerError("No providers are registered in ProviderManager.")
            name = registered[0]
        return self._provider_manager.get(name)

    def plan(self, message: Message, provider_name: Optional[str] = None) -> Plan:
        """Produce a :class:`Plan` describing the next step for ``message``."""
        provider = self.select_provider(provider_name)
        tool_name = self.should_use_tool(message)
        return Plan(use_tool=tool_name is not None, provider=provider, tool_name=tool_name)
