from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from Core.exceptions import AgentError
from Core.logger import get_logger
from Core.analysis_pipeline import AnalysisPipeline
from Core.tool_context_builder import ToolContextBuilder
from Core.request_defaults import (
    DEFAULT_INTERVAL,
    DEFAULT_MAX_NEWS,
    DEFAULT_PERIOD,
)
from Agents.base_agent import AgentStateError
from Agents.market_analysis_agent import MarketAnalysisAgent
from Agents.state import AgentState
from Agents.memory import ConversationMemory
from Agents.planner import Planner
from Agents.executor import Executor
from Providers import Message, MessageRole, ProviderResponse
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.metadata_keys import MetadataKeys
from Orchestration.instrument_extractor import BaseInstrumentExtractor, IDXTickerExtractor

logger = get_logger(__name__)


class StockAgentError(AgentError):
    """Raised for StockAgent-specific failures.

    Examples: no ticker could be extracted from the user's input, or the
    provider call itself fails (the only failure allowed to halt the
    pipeline -- individual service failures are absorbed and reported as
    degraded sections of the merged tool message instead).
    """


class StockAgent(MarketAnalysisAgent):
    """Agent that answers stock-analysis questions.

    Runs the fixed 11-step ``AnalysisPipeline`` for a single ticker
    extracted from the user's message, formats the resulting
    ``dict[str, ServiceResult]`` into one TOOL message via
    ``ToolContextBuilder``, then asks the configured provider to produce
    the final natural-language reply.
    """

    def __init__(
        self,
        planner: Planner,
        memory: ConversationMemory,
        executor: Executor,
        analysis_pipeline: AnalysisPipeline,
        tool_context_builder: ToolContextBuilder,
        default_provider_name: str,
        instrument_extractor: Optional[BaseInstrumentExtractor] = None,
    ) -> None:
        """Initialize the agent via dependency injection only.

        No dependency is constructed here -- every collaborator is
        supplied by the caller, per the framework's DI convention (see
        ``Agents.base_agent.BaseAgent``, ``Agents.planner.Planner``, etc.).

        ``planner``, ``memory``, and ``executor`` are delegated to
        ``MarketAnalysisAgent.__init__`` (which forwards them on to
        ``BaseAgent.__init__``), matching the shared constructor contract
        used by other ``MarketAnalysisAgent`` subclasses (e.g.
        ``IDXStockAgent``). ``StockAgent`` does not have (and never used)
        a ``provider_manager`` of its own -- it resolves providers via
        ``Planner.select_provider`` instead -- so ``None`` is passed up for
        it; that attribute is never read anywhere in this class or in
        ``MarketAnalysisAgent`` itself.

        ``instrument_extractor`` is optional for backward compatibility:
        if omitted (``None``), a default ``IDXTickerExtractor`` is
        constructed here so existing callers that only pass the original
        six positional/keyword arguments keep working unchanged. The
        resolved extractor is passed up to ``MarketAnalysisAgent`` (which
        stores it as ``self._instrument_extractor``); ticker extraction is
        performed by calling ``self._instrument_extractor.extract(...)``
        rather than by any logic local to this class.

        ``analysis_pipeline`` is additionally passed up as
        ``service_pipeline`` so the attribute is populated with something
        meaningful, but it is likewise never read via
        ``self._service_pipeline``; the pipeline is only ever invoked via
        ``self.analysis_pipeline``, unchanged from before this refactor.
        """
        resolved_instrument_extractor = instrument_extractor or IDXTickerExtractor()

        super().__init__(
            planner=planner,
            memory=memory,
            executor=executor,
            provider_manager=None,
            tool_context_builder=tool_context_builder,
            instrument_extractor=resolved_instrument_extractor,
            service_pipeline=analysis_pipeline,
            default_provider_name=default_provider_name,
        )

        self.analysis_pipeline = analysis_pipeline
        self.tool_context_builder = tool_context_builder
        self.default_provider_name = default_provider_name

    @property
    def name(self) -> str:
        """Unique, human-readable name identifying this agent."""
        return "StockAgent"

    def chat(self, user_input: str, provider_name: Optional[str] = None) -> str:
        """Run one conversational turn for a plain string and return the reply."""
        return self.run(Message(role=MessageRole.USER, content=user_input), provider_name)

    def run(self, message: Message, provider_name: Optional[str] = None) -> str:
        """Run the full stock-analysis pipeline for an already-built ``Message``.

        Raises:
            AgentStateError: If called while the agent is in ``ERROR`` state.
            StockAgentError: If no ticker can be extracted from the message.
            Exception: Any exception raised while resolving or calling the
                provider propagates unchanged (never wrapped into
                ``StockAgentError``); the agent still transitions to
                ``ERROR`` state before it escapes.
        """
        with self._state_lock:
            if self._state is AgentState.ERROR:
                raise AgentStateError(
                    f"Agent '{self.name}' is in ERROR state; call reset() first.",
                    details={"agent_name": self.name},
                )

        resolved_provider_name = provider_name or self.default_provider_name

        try:
            self._set_state(AgentState.THINKING)
            self._memory.add(message)

            ticker = self._extract_ticker(message.content)

            self._set_state(AgentState.CALLING_TOOL)
            tool_context_text = self._run_service_pipeline(
                ticker=ticker,
                user_input=message.content,
                provider_name=resolved_provider_name,
            )

            self._set_state(AgentState.WAITING_PROVIDER)
            reply_text = self._call_provider(tool_context_text, resolved_provider_name)

            self._set_state(AgentState.RESPONDING)
            self._memory.add(Message(role=MessageRole.ASSISTANT, content=reply_text))

            self._set_state(AgentState.IDLE)
            return reply_text
        except Exception:
           
            self._set_state(AgentState.ERROR)
            raise

    def health_check(self) -> bool:
        """Report whether this agent's configured default provider is healthy.

        Never raises: mirrors the ``bool``-returning contract shared by
        every ``health_check()`` in the framework.
        """
        try:
            provider = self._planner.select_provider(self.default_provider_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"StockAgent health_check could not resolve provider "
                f"'{self.default_provider_name}': {exc}"
            )
            return False
        return provider.health_check()

    def _extract_ticker(self, text: str) -> str:
        """Extract an IDX ticker (e.g. "BBCA" -> "BBCA.JK") from ``text``.

        Delegates to ``self._instrument_extractor.extract()`` (an
        ``IDXTickerExtractor`` by default -- see :meth:`__init__`), which
        is now the sole source of truth for the regex + stopword-filter
        extraction logic. ``BaseInstrumentExtractor.extract`` raises
        ``ValueError`` on failure; that is translated to
        ``StockAgentError`` here, with the message left unchanged, so
        callers of this method see exactly the same exception type and
        text as before this logic moved to ``IDXTickerExtractor``.

        Raises:
            StockAgentError: If no candidate remains after filtering
                stopwords, or if more than one distinct ticker candidate
                remains (ambiguous -- never silently picked).
        """
        try:
            return self._instrument_extractor.extract(text)
        except ValueError as exc:
            raise StockAgentError(str(exc)) from exc

    def _build_context(
        self, provider_name: str, user_input: str, metadata: Dict[str, Any]
    ) -> ServiceContext:
        return ServiceContext(
            agent_name=self.name,
            provider_name=provider_name,
            request_id=str(uuid.uuid4()),
            user_input=user_input,
            conversation_history=[entry.message for entry in self._memory.history()],
            metadata=metadata,
        )

    def _run_service_pipeline(self, ticker: str, user_input: str, provider_name: str) -> str:
        """Run the AnalysisPipeline for ``ticker`` and format the result.

        Builds a single ``ServiceContext`` seeded with ``ticker``, runs the
        fixed 11-step ``AnalysisPipeline`` (accumulating context,
        skip-on-fail -- see docs/analysis_pipeline.md), then hands the
        resulting ``dict[str, ServiceResult]`` to ``ToolContextBuilder``
        for formatting into a single TOOL message body.

        Only a fatal provider failure is allowed to stop the overall
        pipeline; the AnalysisPipeline and its services are best-effort by
        contract (a Service never raises for a business failure -- see
        ``ServiceResult.ok()`` / ``ServiceResult.fail()``).
        """
        context = self._build_context(
            provider_name,
            user_input,
            {
                MetadataKeys.TICKER: ticker,
                MetadataKeys.PERIOD: DEFAULT_PERIOD,
                MetadataKeys.INTERVAL: DEFAULT_INTERVAL,
                MetadataKeys.MAX_NEWS: DEFAULT_MAX_NEWS,
            },
        )
        results: Dict[str, ServiceResult] = self.analysis_pipeline.run(context)
        return self.tool_context_builder.build(results)

    def _call_provider(self, tool_context_text: str, provider_name: str) -> str:
        """Send conversation history plus a single merged TOOL message to
        the configured provider and return the generated reply text.

        Raises:
            Exception: Whatever ``select_provider()`` or ``provider.generate()``
                raise, propagated unchanged (see module Architecture Notes:
                provider failures are never wrapped into ``StockAgentError``).
        """
        
        provider = self._planner.select_provider(provider_name)

        history = [entry.message for entry in self._memory.history()]
        tool_message = Message(role=MessageRole.TOOL, content=tool_context_text)
        messages = history + [tool_message]

        response: ProviderResponse = provider.generate(messages)
        return response.text