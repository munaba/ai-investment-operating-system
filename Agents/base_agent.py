"""Generic agent engine.

This module purposefully does NOT define StockAgent, ChatAgent, or any
other concrete agent. Concrete agents live in higher-level packages and
inherit from :class:`BaseAgent`, which implements the full, reusable
pipeline:

    User -> Message -> Planner -> Memory -> Tool Registry -> Provider -> Response

Architecture Notes:
    ``Providers.BaseProvider.health_check()`` returns a plain ``bool`` (not
    a rich result object) -- richer diagnostics are available separately
    via ``provider.last_health_check`` if ever needed. ``BaseAgent.health_check()``
    mirrors that and returns ``bool`` too, to stay consistent with the
    (finished) ``Providers`` layer rather than inventing a different shape.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Optional

from Core.exceptions import AgentError
from Core.logger import get_logger
from Providers import BaseProvider, Message, MessageRole, ProviderResponse
from Agents.state import AgentState
from Agents.memory import ConversationMemory
from Agents.planner import Planner
from Agents.executor import Executor

logger = get_logger(__name__)


class AgentStateError(AgentError):
    """Raised when an agent operation is invalid for the current state.

    Additive subclass of ``Core.exceptions.AgentError``.
    """


class BaseAgent(ABC):
    """Abstract base class implementing the generic agent engine.

    Concrete agents (e.g. a future ``StockAgent`` or ``ChatAgent``) only
    need to supply a :attr:`name` and, optionally, override the hook
    methods to customize behaviour. They must never need to touch a
    concrete provider implementation directly -- only :class:`BaseProvider`.
    """

    def __init__(
        self,
        planner: Planner,
        memory: ConversationMemory,
        executor: Executor,
    ) -> None:
        self._planner = planner
        self._memory = memory
        self._executor = executor
        self._state = AgentState.IDLE
        self._state_lock = threading.RLock()

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique, human-readable name identifying this agent."""
        raise NotImplementedError

    @property
    def state(self) -> AgentState:
        """Current lifecycle state of the agent."""
        with self._state_lock:
            return self._state

    def _set_state(self, new_state: AgentState) -> None:
        with self._state_lock:
            logger.debug(f"Agent '{self.name}' state: {self._state} -> {new_state}")
            self._state = new_state

    def chat(self, user_input: str, provider_name: Optional[str] = None) -> str:
        """Run a single conversational turn and return the reply text.

        This is the generic engine pipeline:
        Message -> Planner -> (optional) Tool -> Provider -> Response.
        """
        return self.run(Message(role=MessageRole.USER, content=user_input), provider_name)

    def run(self, message: Message, provider_name: Optional[str] = None) -> str:
        """Run the full pipeline for an already-constructed :class:`Message`.

        Raises:
            AgentStateError: If called while the agent is in ``ERROR`` state.
        """
        with self._state_lock:
            if self._state is AgentState.ERROR:
                raise AgentStateError(
                    f"Agent '{self.name}' is in ERROR state; call reset() first.",
                    details={"agent_name": self.name},
                )

        try:
            self._set_state(AgentState.THINKING)
            self._memory.add(message)

            plan = self._planner.plan(message, provider_name=provider_name)

            tool_result = None
            if plan.use_tool and plan.tool_name is not None:
                self._set_state(AgentState.CALLING_TOOL)
                tool_result = self._executor.execute(plan.tool_name, message.content)

            self._set_state(AgentState.WAITING_PROVIDER)
            reply = self._call_provider(plan.provider, tool_result)

            self._set_state(AgentState.RESPONDING)
            response_message = Message(role=MessageRole.ASSISTANT, content=reply.text)
            self._memory.add(response_message)

            self._set_state(AgentState.IDLE)
            return reply.text
        except Exception:
            self._set_state(AgentState.ERROR)
            raise

    def _call_provider(
        self,
        provider: BaseProvider,
        tool_result: Optional[object],
    ) -> ProviderResponse:
        """Build the conversation context and call the provider.

        Subclasses may override this hook to customize how tool results are
        merged into the provider call, without touching the rest of the
        pipeline.
        """
        history = [entry.message for entry in self._memory.history()]
        if tool_result is not None:
            history = history + [Message(role=MessageRole.TOOL, content=str(tool_result))]
        return provider.generate(history)

    def reset(self) -> None:
        """Clear conversation memory and return the agent to IDLE state."""
        self._memory.clear()
        self._set_state(AgentState.IDLE)

    def health_check(self) -> bool:
        """Report whether the agent's default provider is currently healthy.

        Never raises: any failure resolving a provider is caught, logged,
        and reported as ``False``, mirroring
        ``Providers.BaseProvider.health_check()``'s own contract.
        """
        try:
            provider = self._planner.select_provider()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Agent '{self.name}' health_check could not resolve a provider: {exc}")
            return False
        return provider.health_check()
