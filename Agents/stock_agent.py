from __future__ import annotations

import tempfile
import uuid
from typing import Any, Dict, Optional

from Core.exceptions import AgentError, ApprovalDenied, ApprovalPending
from Core.logger import get_logger
from Core.runtime import ActorTerminatedError
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
from Providers import BaseProvider, Message, MessageRole, ProviderRequirement, ProviderResponse
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.metadata_keys import MetadataKeys
from Orchestration.instrument_extractor import BaseInstrumentExtractor, IDXTickerExtractor
from Orchestration.runtime_analysis_pipeline import (
    AnalysisResult,
    RuntimeAnalysisPipeline,
    VISION_CHART_PATH_METADATA_KEY,
)

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

    Stage L12 addition (additive, optional): if a
    ``runtime_analysis_pipeline`` (an
    ``Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline``)
    is supplied at construction time, :meth:`_run_service_pipeline` routes
    the analysis call through it instead -- i.e. through
    ``Core.runtime.Runtime`` as the execution kernel -- and uses its
    already-formatted ``str`` return value directly, without a second
    call to ``ToolContextBuilder.build()``. When omitted (``None``, the
    default), behavior is byte-for-byte identical to before this stage:
    ``self.analysis_pipeline.run(context)`` followed by
    ``self.tool_context_builder.build(results)``, the pre-existing,
    non-Runtime path. See :meth:`_run_service_pipeline` for the exact
    branch.
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
        runtime_analysis_pipeline: Optional[RuntimeAnalysisPipeline] = None,
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

        ``runtime_analysis_pipeline`` is a Stage L12 addition (additive,
        optional): when supplied (never constructed here -- passed in by
        the caller, e.g. ``Core.composition_root.build_application``),
        :meth:`_run_service_pipeline` routes through it instead of calling
        ``self.analysis_pipeline`` / ``self.tool_context_builder``
        directly. Omitting it (``None``, the default) keeps every
        pre-Stage-L12 caller's behavior byte-for-byte unchanged -- this is
        why every existing constructor call site across the test suite,
        none of which passes this argument, keeps working without
        modification.
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
        # Stage L12 (additive): None preserves the pre-existing,
        # non-Runtime call path exactly -- see _run_service_pipeline().
        self.runtime_analysis_pipeline = runtime_analysis_pipeline

    @property
    def name(self) -> str:
        """Unique, human-readable name identifying this agent."""
        return "StockAgent"

    # Stage L8: the ``chat()`` override that used to live here was
    # byte-for-byte identical to ``Agents.base_agent.BaseAgent.chat()`` --
    # both just wrapped ``user_input`` in a ``Message`` and delegated to
    # ``run()``. It has been removed so ``StockAgent`` inherits
    # ``BaseAgent.chat()`` directly, which now also carries the Stage L8
    # opportunistic requirement-inference probe. This is not a behavior
    # change for any pre-existing caller: for every input where inference
    # previously played no role (Stage L7 and earlier), the inherited
    # method produces the exact same call to ``run()`` the removed
    # override did.

    def run(
        self,
        message: Message,
        provider_name: Optional[str] = None,
        requirement: Optional[ProviderRequirement] = None,
    ) -> str:
        """Run the full stock-analysis pipeline for an already-built ``Message``.

        Args:
            message: The incoming message to run the pipeline for.
            provider_name: Optional explicit provider name -- the
                pre-existing, name-based selection path. Ignored when
                ``requirement`` is also given (Planner's L4 contract).
            requirement: Stage L7 addition (additive, optional). When
                given, the provider for this turn is resolved by
                capability instead of by name, exactly once, via the
                inherited :meth:`MarketAnalysisAgent._resolve_provider_for_request`.

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

        provider, resolved_provider_name = self._resolve_provider_for_request(
            provider_name, requirement
        )

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
            if provider is None:
                provider = self._planner.select_provider(resolved_provider_name)
            reply_text = self._call_provider(tool_context_text, provider)

            self._set_state(AgentState.RESPONDING)
            self._memory.add(Message(role=MessageRole.ASSISTANT, content=reply_text))

            self._set_state(AgentState.IDLE)
            return reply_text
        except ApprovalDenied:
            self._set_state(AgentState.ERROR)
            raise
        except ApprovalPending:
            self._set_state(AgentState.ERROR)
            raise
        except ActorTerminatedError:
            self._set_state(AgentState.ERROR)
            raise
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

        Builds a single ``ServiceContext`` seeded with ``ticker``, then
        produces the final TOOL message body one of two ways:

        - Stage L12 path (``self.runtime_analysis_pipeline`` is not
          ``None``): the context is handed to
          ``RuntimeAnalysisPipeline.run()``, which runs the 11-step
          ``AnalysisPipeline`` through ``Core.runtime.Runtime`` as the
          execution kernel and already returns the final formatted
          ``str`` (``ToolContextBuilder.build()`` already ran *inside*
          that call -- see ``Orchestration.runtime_analysis_pipeline``
          decision #5). ``self.tool_context_builder`` is deliberately
          NOT called a second time on this path: its input is a
          ``Dict[str, ServiceResult]``, not the ``str``
          ``RuntimeAnalysisPipeline.run()`` returns.
        - Pre-existing path (``self.runtime_analysis_pipeline`` is
          ``None``, the default): unchanged from before Stage L12 --
          ``self.analysis_pipeline.run(context)`` (accumulating context,
          skip-on-fail -- see docs/analysis_pipeline.md) then
          ``self.tool_context_builder.build(results)``.

        Only a fatal provider failure is allowed to stop the overall
        pipeline; the AnalysisPipeline and its services are best-effort by
        contract (a Service never raises for a business failure -- see
        ``ServiceResult.ok()`` / ``ServiceResult.fail()``). On the Stage
        L12 path, an unexpected exception instead surfaces as
        ``Core.exceptions.ToolExecutionError`` (Runtime's existing
        error-as-data contract, unchanged here) rather than its original
        type -- a known, documented difference from the pre-existing
        path, not something this method papers over.
        """
        metadata: Dict[str, Any] = {
            MetadataKeys.TICKER: ticker,
            MetadataKeys.PERIOD: DEFAULT_PERIOD,
            MetadataKeys.INTERVAL: DEFAULT_INTERVAL,
            MetadataKeys.MAX_NEWS: DEFAULT_MAX_NEWS,
        }
        if self.runtime_analysis_pipeline is not None:
            # Stage L12 production bridge: seed one shared temp file path
            # into both MetadataKeys.IMAGE_PATH (so ChartService, the 8th
            # step of AnalysisPipeline, persists a chart there) and
            # VISION_CHART_PATH_METADATA_KEY (so
            # RuntimeAnalysisPipeline._maybe_run_vision finds it on the
            # same context afterwards). ServiceContext is immutable and
            # AnalysisPipeline.run()'s internal replace() calls never
            # mutate the original object RuntimeAnalysisPipeline.run()
            # holds, so this single context instance carries chart_path
            # through unchanged.
            chart_path = tempfile.NamedTemporaryFile(
                prefix="chart_", suffix=".png", delete=False
            ).name
            metadata[MetadataKeys.IMAGE_PATH] = chart_path
            metadata[VISION_CHART_PATH_METADATA_KEY] = chart_path

        context = self._build_context(provider_name, user_input, metadata)

        if self.runtime_analysis_pipeline is not None:
            return self.runtime_analysis_pipeline.run(context)
        results: Dict[str, ServiceResult] = self.analysis_pipeline.run(context)
        return self.tool_context_builder.build(results)

    def _call_provider(self, tool_context_text: str, provider: BaseProvider) -> str:
        """Send conversation history plus a single merged TOOL message to
        ``provider`` and return the generated reply text.

        Stage L7: this method now always receives an already-resolved
        ``BaseProvider`` instance -- resolution (by name or by
        requirement) is entirely ``run()``'s responsibility (via
        :meth:`~Agents.market_analysis_agent.MarketAnalysisAgent._resolve_provider_for_request`).
        This method's only job is to use the provider, never to find one
        -- it no longer calls ``Planner.select_provider()`` itself, so
        there is exactly one provider lookup per turn, not two.

        Sprint 159 (additive): when ``tool_context_text`` is an
        ``AnalysisResult`` (the Stage L12 runtime path -- see
        :meth:`_run_service_pipeline`), its ``market_state``,
        ``trading_decision``, and ``portfolio_report`` fields are
        appended, verbatim, to the TOOL message content sent below --
        this is the only place those fields ever reach the Provider,
        since ``BaseProvider`` implementations read ``Message.content``
        only. ``AnalysisResult`` is a ``str`` subclass, so when none of
        these three fields are populated (or ``tool_context_text`` is a
        plain ``str``, the pre-existing non-Runtime path), the content
        sent is byte-for-byte identical to before this sprint.

        Raises:
            Exception: Whatever ``provider.generate()`` raises, propagated
                unchanged (see module Architecture Notes: provider
                failures are never wrapped into ``StockAgentError``).
        """
        history = [entry.message for entry in self._memory.history()]
        content = str(tool_context_text)
        if isinstance(tool_context_text, AnalysisResult):
            extra_lines = []
            if tool_context_text.market_state is not None:
                extra_lines.append(f"market_state: {tool_context_text.market_state}")
            if tool_context_text.trading_decision is not None:
                extra_lines.append(f"trading_decision: {tool_context_text.trading_decision}")
            if tool_context_text.portfolio_report is not None:
                extra_lines.append(f"portfolio_report: {tool_context_text.portfolio_report}")
            if extra_lines:
                content = content + "\n\n" + "\n".join(extra_lines)
        tool_message = Message(role=MessageRole.TOOL, content=content)
        messages = history + [tool_message]

        response: ProviderResponse = provider.generate(messages)
        return response.text