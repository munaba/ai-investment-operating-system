from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from Core.exceptions import AgentError
from Core.logger import get_logger
from Agents.base_agent import BaseAgent, AgentStateError
from Agents.state import AgentState
from Agents.memory import ConversationMemory
from Agents.planner import Planner
from Agents.executor import Executor, ToolExecutionError
from Agents.tool_registry import (
    ToolRegistry,
    Tool,
    ToolAlreadyRegisteredError,
)
from Providers import Message, MessageRole, ProviderResponse
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.stock_service import StockService
from Services.chart_service import ChartService
from Services.news_service import NewsService
from Services.backtest_service import BacktestService

import re

logger = get_logger(__name__)


class StockAgentError(AgentError):
    """Raised for StockAgent-specific failures.

    Examples: no ticker could be extracted from the user's input, or the
    provider call itself fails (the only failure allowed to halt the
    pipeline -- individual service failures are absorbed and reported as
    degraded sections of the merged tool message instead).
    """


class StockAgent(BaseAgent):
    """Agent that answers stock-analysis questions.

    Combines OHLCV data, a technical chart, recent news, and a moving
    average crossover backtest for a single ticker extracted from the
    user's message into one TOOL message, then asks the configured
    provider to produce the final natural-language reply.
    """

    TOOL_STOCK_DATA: str = "stock_data"
    TOOL_CHART: str = "chart"
    TOOL_NEWS: str = "news"
    TOOL_BACKTEST: str = "backtest"

    _TICKER_PATTERN = re.compile(r"\b([A-Z]{4})(\.JK)?\b")

    _TICKER_STOPWORDS = frozenset({"BELI", "JUAL", "SAYA", "YANG", "ATAU"})

    def __init__(
        self,
        planner: Planner,
        memory: ConversationMemory,
        executor: Executor,
        tool_registry: ToolRegistry,
        stock_service: StockService,
        chart_service: ChartService,
        news_service: NewsService,
        backtest_service: BacktestService,
        default_provider_name: str,
    ) -> None:
        """Initialize the agent via dependency injection only.

        No dependency is constructed here -- every collaborator is
        supplied by the caller, per the framework's DI convention (see
        ``Agents.base_agent.BaseAgent``, ``Agents.planner.Planner``, etc.).
        """
        super().__init__(planner=planner, memory=memory, executor=executor)

        self.tool_registry = tool_registry
        self.stock_service = stock_service
        self.chart_service = chart_service
        self.news_service = news_service
        self.backtest_service = backtest_service
        self.default_provider_name = default_provider_name

        self._register_tools()

    @property
    def name(self) -> str:
        """Unique, human-readable name identifying this agent."""
        return "StockAgent"

    def _register_tools(self) -> None:
        tools = (
            Tool(
                name=self.TOOL_STOCK_DATA,
                description="Fetches OHLCV price history and company info for a stock ticker.",
                handler=self._tool_stock_data,
            ),
            Tool(
                name=self.TOOL_CHART,
                description="Builds a technical-analysis chart from OHLC data.",
                handler=self._tool_chart,
            ),
            Tool(
                name=self.TOOL_NEWS,
                description="Fetches recent news articles for a stock ticker.",
                handler=self._tool_news,
            ),
            Tool(
                name=self.TOOL_BACKTEST,
                description="Runs a moving-average crossover backtest against historical price data.",
                handler=self._tool_backtest,
            ),
        )
        for tool in tools:
            self._register_tool_idempotent(tool)

    def _register_tool_idempotent(self, tool: Tool) -> None:
        if self.tool_registry.exists(tool.name):
            return
        try:
            self.tool_registry.register(tool)
        except ToolAlreadyRegisteredError:
           
            pass

    def _tool_stock_data(self, context: ServiceContext) -> ServiceResult:
        return self.stock_service.execute(context)

    def _tool_chart(self, context: ServiceContext) -> ServiceResult:
        return self.chart_service.execute(context)

    def _tool_news(self, context: ServiceContext) -> ServiceResult:
        return self.news_service.execute(context)

    def _tool_backtest(self, context: ServiceContext) -> ServiceResult:
        return self.backtest_service.execute(context)

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

        Looks for a 4-uppercase-letter token, optionally already suffixed
        with ``.JK``. Tokens in :attr:`_TICKER_STOPWORDS` (common Indonesian
        command/pronoun words such as "BELI", "JUAL", "SAYA") are ignored
        before determining the candidate(s).

        Raises:
            StockAgentError: If no candidate remains after filtering
                stopwords, or if more than one distinct ticker candidate
                remains (ambiguous -- never silently picked).
        """
        matches = self._TICKER_PATTERN.findall(text or "")
        candidates = [
            (base, suffix) for base, suffix in matches if base not in self._TICKER_STOPWORDS
        ]

        if not candidates:
            raise StockAgentError(f"Ticker tidak ditemukan pada input: {text!r}")

        unique_bases = {base for base, _ in candidates}
        if len(unique_bases) > 1:
            raise StockAgentError(
                f"Ditemukan lebih dari satu kandidat ticker yang ambigu "
                f"{sorted(unique_bases)!r} pada input: {text!r}"
            )

        base = candidates[0][0]
        return f"{base}.JK"

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

    def _safe_execute_tool(self, tool_name: str, context: ServiceContext) -> ServiceResult:
        """Run a registered tool via the injected Executor, never raising.

        A service (or the executor) failing must not crash the pipeline --
        it is converted into a failed ``ServiceResult`` and the pipeline
        continues with whatever context is available.
        """
        try:
            result = self._executor.execute(tool_name, context)
        except ToolExecutionError as exc:
            logger.warning(f"Tool '{tool_name}' failed: {exc}")
            return ServiceResult.fail(exc, message=str(exc))
        except Exception as exc: 
            logger.warning(f"Tool '{tool_name}' raised an unexpected error: {exc}")
            return ServiceResult.fail(exc, message=str(exc))

        if isinstance(result, ServiceResult):
            return result
        
        return ServiceResult.ok(data=result)

    def _run_service_pipeline(self, ticker: str, user_input: str, provider_name: str) -> str:
        """Run StockService -> ChartService -> NewsService -> BacktestService
        and merge every outcome into a single TOOL message body.

        Only a fatal provider failure is allowed to stop the overall
        pipeline; every service call here is best-effort.
        """
        stock_result = self._safe_execute_tool(
            self.TOOL_STOCK_DATA,
            self._build_context(provider_name, user_input, {"ticker": ticker}),
        )

        history: Optional[List[Dict[str, Any]]] = None
        if stock_result.success and isinstance(stock_result.data, dict):
            history = stock_result.data.get("history") or None

        if history:
            chart_result = self._safe_execute_tool(
                self.TOOL_CHART,
                self._build_context(
                    provider_name, user_input, {"ticker": ticker, "history": history}
                ),
            )
        else:
            chart_result = ServiceResult.fail(
                StockAgentError("No stock history available; chart generation skipped."),
                message="No stock history available; chart generation skipped.",
            )

        news_result = self._safe_execute_tool(
            self.TOOL_NEWS,
            self._build_context(provider_name, user_input, {"ticker": ticker}),
        )

        if history:
            backtest_result = self._safe_execute_tool(
                self.TOOL_BACKTEST,
                self._build_context(provider_name, user_input, {"history": history}),
            )
        else:
            backtest_result = ServiceResult.fail(
                StockAgentError("No stock history available; backtest skipped."),
                message="No stock history available; backtest skipped.",
            )

        return self._merge_tool_context(
            ticker=ticker,
            stock_result=stock_result,
            chart_result=chart_result,
            news_result=news_result,
            backtest_result=backtest_result,
        )

    @staticmethod
    def _format_stock_section(result: ServiceResult) -> str:
        if not result.success or not isinstance(result.data, dict):
            return "FAILED"

        data = result.data
        history = data.get("history") or []
        info = data.get("info") or {}
        lines = [f"Ticker: {data.get('ticker')}", f"Data points: {len(history)}"]

        company_name = info.get("longName") or info.get("shortName")
        if company_name:
            lines.append(f"Company: {company_name}")
        currency = info.get("currency")
        if currency:
            lines.append(f"Currency: {currency}")

        last_row = history[-1] if history else None
        if isinstance(last_row, dict) and "Close" in last_row:
            lines.append(f"Last Close: {last_row['Close']}")

        return "\n".join(lines)

    @staticmethod
    def _format_chart_section(result: ServiceResult) -> str:
        if not result.success or not isinstance(result.data, dict):
            return "Not generated"

        data = result.data
        meta = data.get("metadata") or {}
        lines = [f"Rows plotted: {meta.get('rows', 0)}"]

        included = meta.get("indicators_included") or []
        if included:
            lines.append(f"Indicators: {', '.join(included)}")
        skipped = meta.get("indicators_skipped") or []
        if skipped:
            lines.append(f"Skipped indicators: {', '.join(skipped)}")
        if data.get("image_path"):
            lines.append(f"Image saved: {data['image_path']}")

        return "\n".join(lines)

    @staticmethod
    def _format_news_section(result: ServiceResult) -> str:
        if not result.success or not isinstance(result.data, dict):
            return "Not available"

        items = result.data.get("news") or []
        if not items:
            return "No recent news found."

        lines = []
        for item in items[:5]:
            title = item.get("title") or "(untitled)"
            publisher = item.get("publisher") or ""
            lines.append(f"- {title} ({publisher})" if publisher else f"- {title}")
        return "\n".join(lines)

    @staticmethod
    def _format_backtest_section(result: ServiceResult) -> str:
        if not result.success or not isinstance(result.data, dict):
            return "Not run"

        data = result.data
        total_return = data.get("total_return", 0.0) or 0.0
        final_capital = data.get("final_capital", 0.0) or 0.0
        win_rate = data.get("win_rate", 0.0) or 0.0

        lines = [
            f"Strategy: {data.get('strategy')}",
            f"Total Return: {total_return:.2f}%",
            f"Final Capital: {final_capital:,.2f}",
            f"Total Trades: {data.get('total_trade', 0)}",
            f"Win Rate: {win_rate:.2f}%",
        ]
        return "\n".join(lines)

    def _merge_tool_context(
        self,
        ticker: str,
        stock_result: ServiceResult,
        chart_result: ServiceResult,
        news_result: ServiceResult,
        backtest_result: ServiceResult,
    ) -> str:
        return "\n\n".join(
            [
                self._render_section("Ticker", ticker),
                self._render_section("Stock Data", self._format_stock_section(stock_result)),
                self._render_section("Chart", self._format_chart_section(chart_result)),
                self._render_section("News", self._format_news_section(news_result)),
                self._render_section("Backtest", self._format_backtest_section(backtest_result)),
            ]
        )

    _INLINE_STATUS_MARKERS = frozenset({"FAILED", "Not generated", "Not run"})

    def _render_section(self, header: str, content: str) -> str:
        """Render one ``[Header] ...`` tool-context section.

        Fixed one-word failure markers (e.g. ``"FAILED"``) are rendered on
        the same line as the header (``"[Stock Data] FAILED"``); any other
        (possibly multi-line) content is rendered on the following line(s).
        """
        if content in self._INLINE_STATUS_MARKERS:
            return f"[{header}] {content}"
        return f"[{header}]\n{content}"

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