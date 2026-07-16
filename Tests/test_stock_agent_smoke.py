from __future__ import annotations
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sys
import traceback
from typing import Any, Iterator, List, Optional
import pandas as pd
from Providers import BaseProvider, Message, MessageRole, ProviderManager, ProviderResponse
from Agents.state import AgentState
from Agents.memory import ConversationMemory
from Agents.planner import Planner
from Agents.executor import Executor
from Agents.tool_registry import ToolRegistry
from Agents.base_agent import AgentStateError
from Agents.stock_agent import StockAgent, StockAgentError
from Services.stock_service import StockService
from Services.chart_service import ChartService
from Services.news_service import NewsService
from Services.backtest_service import BacktestService


# ----------------------------------------------------------------------
# Fakes / test doubles
# ----------------------------------------------------------------------


class FakeProvider(BaseProvider):
    """Minimal BaseProvider implementation that echoes a fixed analysis."""

    def __init__(self, reply_text: str = "Final analysis: BBCA looks bullish.", fail: bool = False) -> None:
        super().__init__()
        self._reply_text = reply_text
        self._fail = fail
        self.last_messages: Optional[List[Message]] = None

    @property
    def name(self) -> str:
        return "fake_provider"

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def generate(self, messages: List[Message], **kwargs: Any) -> ProviderResponse:
        self.last_messages = messages
        if self._fail:
            raise RuntimeError("Simulated provider failure")
        return ProviderResponse(text=self._reply_text, finish_reason="stop", model=self.name)

    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        raise NotImplementedError

    def count_tokens(self, messages: List[Message]) -> int:
        return sum(len(m.content.split()) for m in messages)

    def health_check(self) -> bool:
        return True


class FakeYFinanceTicker:
    """Fake yfinance.Ticker returning canned OHLCV/news/info data."""

    def __init__(self, symbol: str, *, empty_history: bool = False, raise_on_history: bool = False) -> None:
        self.symbol = symbol
        self._empty_history = empty_history
        self._raise_on_history = raise_on_history
        self.info = {"longName": f"{symbol} Test Company"}
        self.news = [
            {
                "title": f"{symbol} posts strong quarterly earnings",
                "publisher": "Test Wire",
                "link": "https://example.test/news/1",
                "providerPublishTime": 1700000000,
                "summary": "Earnings beat expectations.",
                "relatedTickers": [symbol],
            },
            {
                "title": f"{symbol} announces new product line",
                "publisher": "Test Daily",
                "link": "https://example.test/news/2",
                "providerPublishTime": 1700086400,
            },
        ]

    def history(self, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        if self._raise_on_history:
            raise RuntimeError("Simulated yfinance network failure")
        if self._empty_history:
            return pd.DataFrame()

        dates = pd.date_range("2024-01-01", periods=80, freq="D")
        base = 9000.0
        closes = [base + (i % 10) * 15 - (i % 7) * 10 for i in range(len(dates))]
        opens = [c - 5 for c in closes]
        highs = [c + 10 for c in closes]
        lows = [c - 10 for c in closes]
        volumes = [1_000_000 + i * 500 for i in range(len(dates))]
        df = pd.DataFrame(
            {"Date": dates, "Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes}
        )
        return df.set_index("Date")


class FakeYFinanceModule:
    """Fake yfinance module: `.Ticker(symbol)` -> FakeYFinanceTicker."""

    def __init__(self, *, empty_history: bool = False, raise_on_history: bool = False) -> None:
        self._empty_history = empty_history
        self._raise_on_history = raise_on_history

    def Ticker(self, symbol: str) -> FakeYFinanceTicker:
        return FakeYFinanceTicker(
            symbol, empty_history=self._empty_history, raise_on_history=self._raise_on_history
        )


class FakeGo:
    """Fake plotly.graph_objects: records trace calls, no real rendering."""

    class _Trace:
        def __init__(self, kind: str, **kwargs: Any) -> None:
            self.kind = kind
            self.kwargs = kwargs

    def Candlestick(self, **kwargs: Any) -> "FakeGo._Trace":
        return FakeGo._Trace("candlestick", **kwargs)

    def Scatter(self, **kwargs: Any) -> "FakeGo._Trace":
        return FakeGo._Trace("scatter", **kwargs)

    def Bar(self, **kwargs: Any) -> "FakeGo._Trace":
        return FakeGo._Trace("bar", **kwargs)


class FakeFigure:
    def __init__(self) -> None:
        self.traces: List[Any] = []
        self.layout: Any = None

    def add_trace(self, trace: Any, row: int = 1, col: int = 1) -> None:
        self.traces.append((trace, row, col))

    def update_layout(self, **kwargs: Any) -> None:
        self.layout = kwargs

    def write_image(self, path: str) -> None:
        raise RuntimeError("kaleido not available in test environment")


def fake_make_subplots(**kwargs: Any) -> FakeFigure:
    return FakeFigure()


# ----------------------------------------------------------------------
# Test harness
# ----------------------------------------------------------------------

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


def build_agent(
    *,
    yfinance_module: Any,
    provider: BaseProvider,
    provider_name: str = "fake_provider",
) -> StockAgent:
    """Construct a fully wired StockAgent using fresh, isolated instances
    of every mutable dependency.

    Note: ``ToolRegistry`` is a process-wide singleton (see Architecture
    Notes in ``Agents/stock_agent.py``) whose tool names are registered
    idempotently -- once bound, a tool name's handler stays bound to
    whichever ``StockAgent`` instance registered it first, for the
    lifetime of the process. That is the correct, intended behaviour for
    production (one long-lived ``StockAgent``), but it means this test
    file -- which intentionally builds a *fresh* ``StockAgent`` (with
    fresh, per-scenario fake services) for every scenario -- must reset
    the registry first, or every scenario after the first would silently
    keep calling the *first* scenario's services. ``ToolRegistry.reset()``
    is explicitly documented as "intended for tests only", which is
    exactly this situation.
    """
    ToolRegistry.reset()
    tool_registry = ToolRegistry()
    provider_manager = ProviderManager()
    if not provider_manager.exists(provider_name):
        provider_manager.register(provider_name, provider)

    planner = Planner(provider_manager=provider_manager, tool_registry=tool_registry)
    memory = ConversationMemory()
    executor = Executor(tool_registry=tool_registry)

    stock_service = StockService(yfinance_module=yfinance_module)
    chart_service = ChartService(go_module=FakeGo(), make_subplots_func=fake_make_subplots)
    news_service = NewsService(yfinance_module=yfinance_module)
    backtest_service = BacktestService()

    return StockAgent(
        planner=planner,
        memory=memory,
        executor=executor,
        tool_registry=tool_registry,
        stock_service=stock_service,
        chart_service=chart_service,
        news_service=news_service,
        backtest_service=backtest_service,
        default_provider_name=provider_name,
    )


# ----------------------------------------------------------------------
# Scenarios
# ----------------------------------------------------------------------


def scenario_success_full_pipeline() -> None:
    print("\n[Scenario 1] Full successful pipeline: 'Analisa BBCA'")
    provider = FakeProvider(reply_text="BBCA analysis: uptrend, moderate volatility.")
    agent = build_agent(yfinance_module=FakeYFinanceModule(), provider=provider, provider_name="fake_provider_1")

    reply = agent.chat("Analisa BBCA")

    check(isinstance(reply, str) and len(reply) > 0, "returns non-empty final analysis text")
    check(reply == "BBCA analysis: uptrend, moderate volatility.", "returns the provider's exact reply text")
    check(agent.state is AgentState.IDLE, "agent state returns to IDLE after success")
    check(len(agent._memory.history()) == 2, "memory holds exactly [user, assistant] after one turn")
    check(provider.last_messages is not None and len(provider.last_messages) >= 2, "provider received conversation + tool context")
    tool_message = provider.last_messages[-1]
    check(tool_message.role == MessageRole.TOOL, "last message sent to provider is a TOOL message")
    check("BBCA.JK" in tool_message.content, "combined tool context mentions the normalized ticker")
    check("[Stock Data]" in tool_message.content, "combined tool context includes stock data section")
    check("[Chart]" in tool_message.content, "combined tool context includes chart section")
    check("[News]" in tool_message.content, "combined tool context includes news section")
    check("[Backtest]" in tool_message.content, "combined tool context includes backtest section")
    check("FAILED" not in tool_message.content, "no section reports failure in the happy path")


def scenario_already_suffixed_ticker() -> None:
    print("\n[Scenario 2] Ticker already has exchange suffix: 'Analisa ANTM.JK sekarang'")
    provider = FakeProvider(reply_text="ANTM analysis done.")
    agent = build_agent(yfinance_module=FakeYFinanceModule(), provider=provider, provider_name="fake_provider_2")

    reply = agent.chat("Analisa ANTM.JK sekarang")

    check(reply == "ANTM analysis done.", "pipeline completes for an already-suffixed ticker")
    tool_message = provider.last_messages[-1]
    check("ANTM.JK" in tool_message.content and "ANTM.JK.JK" not in tool_message.content, "does not double-append the market suffix")


def scenario_no_ticker_found() -> None:
    print("\n[Scenario 3] Failure path: input with no extractable ticker")
    provider = FakeProvider()
    agent = build_agent(yfinance_module=FakeYFinanceModule(), provider=provider, provider_name="fake_provider_3")

    raised = False
    try:
        agent.chat("tolong analisa dong")
    except StockAgentError:
        raised = True
    except Exception as exc:  # noqa: BLE001
        check(False, f"expected StockAgentError, got {type(exc).__name__}: {exc}")

    check(raised, "raises StockAgentError when no ticker can be extracted")
    check(agent.state is AgentState.ERROR, "agent transitions to ERROR state on unparseable input")

    reset_raised = False
    try:
        agent.chat("Analisa BBCA")
    except AgentStateError:
        reset_raised = True
    check(reset_raised, "agent refuses further runs while in ERROR state (AgentStateError)")

    agent.reset()
    check(agent.state is AgentState.IDLE, "reset() clears ERROR state back to IDLE")
    recovered_reply = agent.chat("Analisa BBCA")
    check(isinstance(recovered_reply, str) and len(recovered_reply) > 0, "agent works normally again after reset()")


def scenario_empty_input() -> None:
    print("\n[Scenario 4] Failure path: empty user input")
    provider = FakeProvider()
    agent = build_agent(yfinance_module=FakeYFinanceModule(), provider=provider, provider_name="fake_provider_4")

    raised = False
    try:
        agent.chat("   ")
    except StockAgentError:
        raised = True
    check(raised, "raises StockAgentError for blank/whitespace-only input")


def scenario_stock_data_failure_degrades_gracefully() -> None:
    print("\n[Scenario 5] Stock data source fails (empty history) -> pipeline degrades, does not crash")
    provider = FakeProvider(reply_text="Limited analysis due to missing data.")
    agent = build_agent(
        yfinance_module=FakeYFinanceModule(empty_history=True), provider=provider, provider_name="fake_provider_5"
    )

    reply = agent.chat("Analisa XXXX")

    check(reply == "Limited analysis due to missing data.", "pipeline still returns a final analysis when stock data is missing")
    check(agent.state is AgentState.IDLE, "agent state returns to IDLE even when stock data failed (business failure, not exception)")
    tool_message = provider.last_messages[-1]
    check("[Stock Data] FAILED" in tool_message.content, "combined context reports the stock data failure")
    check("[Chart] Not generated" in tool_message.content, "chart is skipped (not attempted) when there is no history")
    check("[Backtest] Not run" in tool_message.content, "backtest is skipped (not attempted) when there is no history")
    check("[News]" in tool_message.content and "FAILED" not in tool_message.content.split("[News]")[1].split("[Backtest]")[0], "news is still fetched independently of the stock data failure")


def scenario_stock_service_raises_network_error() -> None:
    print("\n[Scenario 6] Stock data source raises an exception (simulated network failure)")
    provider = FakeProvider(reply_text="Analysis with degraded data.")
    agent = build_agent(
        yfinance_module=FakeYFinanceModule(raise_on_history=True), provider=provider, provider_name="fake_provider_6"
    )

    reply = agent.chat("Analisa BBCA")

    check(reply == "Analysis with degraded data.", "pipeline survives a raised exception inside StockService (caught internally, reported as failed ServiceResult)")
    tool_message = provider.last_messages[-1]
    check("[Stock Data] FAILED" in tool_message.content, "network failure surfaces as a reported failure, not a crash")


def scenario_provider_failure_propagates() -> None:
    print("\n[Scenario 7] Provider itself fails -> exception propagates, agent goes to ERROR")
    provider = FakeProvider(fail=True)
    agent = build_agent(yfinance_module=FakeYFinanceModule(), provider=provider, provider_name="fake_provider_7")

    raised = False
    try:
        agent.chat("Analisa BBCA")
    except RuntimeError:
        raised = True
    check(raised, "provider failure propagates as an exception (not silently swallowed)")
    check(agent.state is AgentState.ERROR, "agent state is ERROR after a provider failure")


def scenario_idempotent_tool_registration() -> None:
    print("\n[Scenario 8] Constructing a second StockAgent against the SAME (unreset) ToolRegistry does not raise ToolAlreadyRegisteredError")
    # Deliberately bypass build_agent's ToolRegistry.reset() here: this
    # scenario specifically checks the _register_tools() exists-check
    # guard, which only matters when the singleton registry is *not*
    # reset between constructions (i.e. two StockAgents sharing one
    # process, the realistic production concern).
    ToolRegistry.reset()
    tool_registry = ToolRegistry()
    provider_manager = ProviderManager()
    provider_manager.register("fake_provider_8a", FakeProvider())
    provider_manager.register("fake_provider_8b", FakeProvider())

    raised = False
    try:
        StockAgent(
            planner=Planner(provider_manager=provider_manager, tool_registry=tool_registry),
            memory=ConversationMemory(),
            executor=Executor(tool_registry=tool_registry),
            tool_registry=tool_registry,
            stock_service=StockService(yfinance_module=FakeYFinanceModule()),
            chart_service=ChartService(go_module=FakeGo(), make_subplots_func=fake_make_subplots),
            news_service=NewsService(yfinance_module=FakeYFinanceModule()),
            backtest_service=BacktestService(),
            default_provider_name="fake_provider_8a",
        )
        StockAgent(
            planner=Planner(provider_manager=provider_manager, tool_registry=tool_registry),
            memory=ConversationMemory(),
            executor=Executor(tool_registry=tool_registry),
            tool_registry=tool_registry,
            stock_service=StockService(yfinance_module=FakeYFinanceModule()),
            chart_service=ChartService(go_module=FakeGo(), make_subplots_func=fake_make_subplots),
            news_service=NewsService(yfinance_module=FakeYFinanceModule()),
            backtest_service=BacktestService(),
            default_provider_name="fake_provider_8b",
        )
    except Exception as exc:  # noqa: BLE001
        raised = True
        check(False, f"second StockAgent construction raised unexpectedly: {type(exc).__name__}: {exc}")
    check(not raised, "tool registration is idempotent (exists-check) across multiple StockAgent instances sharing one registry")
    ToolRegistry.reset()


def scenario_health_check_reuses_base_agent() -> None:
    print("\n[Scenario 9] health_check() is inherited unchanged from BaseAgent")
    provider = FakeProvider()
    agent = build_agent(yfinance_module=FakeYFinanceModule(), provider=provider, provider_name="fake_provider_9")
    check(agent.health_check() is True, "health_check() delegates to the resolved provider's health_check()")


def scenario_run_accepts_message_directly() -> None:
    print("\n[Scenario 10] run() accepts a pre-built Message (not just chat())")
    provider = FakeProvider(reply_text="Direct run() analysis.")
    agent = build_agent(yfinance_module=FakeYFinanceModule(), provider=provider, provider_name="fake_provider_10")

    reply = agent.run(Message(role=MessageRole.USER, content="Analisa BBCA"))
    check(reply == "Direct run() analysis.", "run() works directly with a Message, matching BaseAgent.run()'s signature")


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------


def main() -> int:
    scenarios = [
        scenario_success_full_pipeline,
        scenario_already_suffixed_ticker,
        scenario_no_ticker_found,
        scenario_empty_input,
        scenario_stock_data_failure_degrades_gracefully,
        scenario_stock_service_raises_network_error,
        scenario_provider_failure_propagates,
        scenario_idempotent_tool_registration,
        scenario_health_check_reuses_base_agent,
        scenario_run_accepts_message_directly,
    ]

    for scenario in scenarios:
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"SMOKE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())