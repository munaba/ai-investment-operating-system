from __future__ import annotations

from abc import ABC
from typing import Optional

from Agents.base_agent import BaseAgent
from Agents.executor import Executor
from Agents.memory import ConversationMemory
from Agents.planner import Planner


class MarketAnalysisAgent(BaseAgent, ABC):
    """Abstract base for agents that analyze market instruments via a pipeline.

    ``MarketAnalysisAgent`` is the shared foundation for concrete agents
    that analyze a specific class of market instrument -- for example a
    future ``StockAgent``, ``CryptoAgent``, ``ForexAgent``, or
    ``CommodityAgent`` -- each of which runs its own fixed pipeline of
    services over an extracted instrument identifier (a ticker, a symbol
    pair, a commodity code, and so on).

    This class holds the dependencies that are common across every such
    agent -- a provider manager for resolving providers, a tool-context
    builder for turning pipeline results into a provider-facing message,
    an instrument extractor for pulling the instrument identifier out of
    a message, and a service pipeline that performs the actual analysis
    -- so that concrete agents do not each need to wire these themselves.

    All behavior -- pipeline execution order, instrument extraction
    logic, context building, and how results are merged into the
    provider call -- remains the responsibility of concrete subclasses.
    This class implements no pipeline, overrides none of
    :class:`~Agents.base_agent.BaseAgent`'s methods, and defines no
    abstract methods of its own; it is purely a shared constructor and
    dependency-storage layer.

    Attributes:
        _provider_manager: Shared provider manager used to resolve
            providers by name.
        _tool_context_builder: Builder that turns pipeline results into
            a single provider-facing message.
        _instrument_extractor: Extracts an instrument identifier (e.g. a
            ticker or symbol) from an incoming message.
        _service_pipeline: The pipeline of services that performs the
            instrument analysis.
        _default_provider_name: Optional default provider name to use
            when none is specified for a given call.
    """

    def __init__(
        self,
        planner: Planner,
        memory: ConversationMemory,
        executor: Executor,
        provider_manager: object,
        tool_context_builder: object,
        instrument_extractor: object,
        service_pipeline: object,
        default_provider_name: Optional[str] = None,
    ) -> None:
        """Store shared dependencies for market-analysis agents.

        Args:
            planner: Planner used for provider selection and (in the
                generic engine) tool planning.
            memory: Conversation memory shared with the base agent
                engine.
            executor: Executor used to run registered tools.
            provider_manager: Shared provider manager used to resolve
                providers by name.
            tool_context_builder: Builder that turns pipeline results
                into a single provider-facing message.
            instrument_extractor: Extracts an instrument identifier
                (e.g. a ticker or symbol) from an incoming message.
            service_pipeline: The pipeline of services that performs the
                instrument analysis.
            default_provider_name: Optional default provider name to use
                when none is specified for a given call.
        """
        super().__init__(planner, memory, executor)
        self._provider_manager = provider_manager
        self._tool_context_builder = tool_context_builder
        self._instrument_extractor = instrument_extractor
        self._service_pipeline = service_pipeline
        self._default_provider_name = default_provider_name