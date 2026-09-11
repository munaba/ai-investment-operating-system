from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from Core.exceptions import AgentError
from Providers import BaseProvider, Message, ProviderManager, ProviderRequirement, ProviderSelector
from Agents.tool_registry import ToolRegistry


class PlannerError(AgentError):
    """Raised when the planner cannot produce a valid plan.

    Additive subclass of ``Core.exceptions.AgentError``.
    """

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
    agent itself using the provider returned from :meth:`select_provider`
    (or, for the Stage L4 capability-based path, :meth:`select_by_requirement`).

    Stage L4 (additive): ``Planner`` now supports two independent,
    parallel provider-selection vocabularies, never mixed internally:

    1. **By name** (pre-existing, unchanged): :meth:`select_provider`,
       driven by ``provider_name`` / ``default_provider_name`` and a
       direct ``ProviderManager.get(name)`` lookup.
    2. **By requirement** (new): :meth:`select_by_requirement`, driven by
       a :class:`~Providers.requirement.ProviderRequirement` and resolved
       via an injected :class:`~Providers.provider_selector.ProviderSelector`
       (Stage L3), which itself never inspects a provider's name or
       class -- only its declared ``capabilities``.

    The two paths do not call each other and neither is preferred over
    the other by default: a caller opts into the requirement-based path
    only by supplying a ``requirement`` (to :meth:`plan`) or calling
    :meth:`select_by_requirement` directly. Every pre-existing caller
    that only ever used ``provider_name``/``select_provider`` observes
    zero behavior change.
    """

    def __init__(
        self,
        provider_manager: ProviderManager,
        tool_registry: ToolRegistry,
        default_provider_name: Optional[str] = None,
        tool_trigger_strategy: Optional[ToolTriggerStrategy] = None,
        provider_selector: Optional[ProviderSelector] = None,
    ) -> None:
        """Initialize the planner.

        Args:
            provider_manager: Registry used by the pre-existing,
                name-based :meth:`select_provider` path.
            tool_registry: Registry of tools consulted by
                :meth:`should_use_tool`.
            default_provider_name: Optional fallback name for
                :meth:`select_provider` when no explicit name is given.
            tool_trigger_strategy: Optional override for tool-trigger
                detection.
            provider_selector: Stage L4 addition (additive, optional).
                A :class:`~Providers.provider_selector.ProviderSelector`
                used exclusively by :meth:`select_by_requirement`. When
                omitted (the default), the requirement-based path is
                simply unavailable -- :meth:`select_by_requirement`
                raises :class:`PlannerError` rather than silently
                falling back to name-based selection. This keeps the two
                paths observably distinct: a caller can never accidentally
                get a name-resolved provider back from a call that asked
                for a requirement-resolved one.
        """
        self._provider_manager = provider_manager
        self._tool_registry = tool_registry
        self._default_provider_name = default_provider_name
        self._tool_trigger_strategy = tool_trigger_strategy or _default_tool_trigger
        self._provider_selector = provider_selector

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

    def select_by_requirement(self, requirement: ProviderRequirement) -> BaseProvider:
        """Select a provider that satisfies ``requirement`` (Stage L4, additive).

        Callers state *what they need* (via ``ProviderRequirement``)
        instead of *which provider they want* (via a name). Resolution
        is delegated entirely to the injected
        :class:`~Providers.provider_selector.ProviderSelector`, which
        reads only each registered provider's ``capabilities`` -- never
        its name or class -- so this method introduces no name-based or
        ``isinstance``-based branching of its own.

        Args:
            requirement: The capability requirement to satisfy.

        Raises:
            PlannerError: If no ``ProviderSelector`` was supplied at
                construction time. This path is opt-in: a ``Planner``
                built without ``provider_selector`` simply cannot serve
                requirement-based requests, and this method says so
                explicitly rather than silently falling back to
                name-based selection (which would defeat the purpose of
                asking for a requirement in the first place).
            Core.exceptions.ProviderError: Propagated unchanged from
                ``ProviderSelector.select()`` if no registered provider
                satisfies ``requirement``.
        """
        if self._provider_selector is None:
            raise PlannerError(
                "Planner was constructed without a ProviderSelector; "
                "select_by_requirement() is unavailable.",
                details={"requirement": requirement},
            )
        return self._provider_selector.select(requirement)

    def plan(
        self,
        message: Message,
        provider_name: Optional[str] = None,
        requirement: Optional[ProviderRequirement] = None,
    ) -> Plan:
        """Produce a :class:`Plan` describing the next step for ``message``.

        Args:
            message: The incoming message being planned for.
            provider_name: Optional explicit provider name -- the
                pre-existing, name-based selection path (see
                :meth:`select_provider`). Ignored when ``requirement``
                is also given (see below).
            requirement: Stage L4 addition (additive, optional). When
                given, provider selection is delegated to
                :meth:`select_by_requirement` instead of
                :meth:`select_provider`, and ``provider_name`` is not
                consulted at all for this call. The two parameters are
                deliberately mutually exclusive in effect -- ``plan()``
                never blends a name filter with a capability filter --
                so which path was used stays unambiguous. Omit this
                argument (the default) to get exactly the pre-existing
                behavior.
        """
        if requirement is not None:
            provider = self.select_by_requirement(requirement)
        else:
            provider = self.select_provider(provider_name)
        tool_name = self.should_use_tool(message)
        return Plan(use_tool=tool_name is not None, provider=provider, tool_name=tool_name)