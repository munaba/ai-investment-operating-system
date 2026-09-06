

from Agents.idx_stock_agent import IDXStockAgent
from Orchestration.instrument_extractor import IDXTickerExtractor
from Agents.memory import ConversationMemory
from Agents.planner import Planner
from Agents.executor import Executor
from Agents.tool_registry import ToolRegistry
from Core.analysis_pipeline import AnalysisPipeline
from Orchestration.analysis_pipeline_adapter import AnalysisPipelineAdapter
from Core.tool_context_builder import ToolContextBuilder
from Providers import ProviderManager
from Services.stock_service import StockService
from Services.technical_indicator_service import TechnicalIndicatorService
from Services.moving_average_service import MovingAverageService
from Services.technical_score_service import TechnicalScoreService
from Services.fundamental_service import FundamentalService
from Services.pattern_service import PatternService
from Services.chart_service import ChartService
from Services.news_service import NewsService
from Services.backtest_service import BacktestService
from Services.risk_management_service import RiskManagementService
from Services.scoring_service import ScoringService


class FakeYFinanceTicker:
    """Minimal fake yfinance.Ticker -- never actually invoked in this test."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.info = {}
        self.news = []

    def history(self, period: str = "6mo", interval: str = "1d"):
        raise AssertionError(
            "FakeYFinanceTicker.history() should never be called by a "
            "wiring-only test."
        )


class FakeYFinanceModule:
    """Minimal fake yfinance module, passed only so StockService/NewsService
    can be constructed without importing the real network-calling library.
    Never exercised -- this test never runs the pipeline.
    """

    def Ticker(self, symbol: str) -> FakeYFinanceTicker:
        return FakeYFinanceTicker(symbol)


class FakeGo:
    """Minimal fake plotly.graph_objects, passed only so ChartService can
    be constructed. Never exercised -- this test never runs the pipeline.
    """

    def Candlestick(self, **kwargs):
        raise AssertionError("FakeGo.Candlestick() should never be called.")

    def Scatter(self, **kwargs):
        raise AssertionError("FakeGo.Scatter() should never be called.")

    def Bar(self, **kwargs):
        raise AssertionError("FakeGo.Bar() should never be called.")


def _fake_make_subplots(**kwargs):
    raise AssertionError("fake_make_subplots() should never be called.")


class RecordingPipeline:
    """Local test double standing in for a service pipeline, used only to
    verify that ``AnalysisPipelineAdapter`` genuinely delegates rather than
    performing any logic of its own. Not the real ``AnalysisPipeline`` --
    that is exercised separately below purely for construction/wiring.
    """

    def __init__(self) -> None:
        self.run_calls = []
        self.health_check_calls = 0

    def run(self, context):
        self.run_calls.append(context)
        return {"sentinel": context}

    def health_check(self) -> bool:
        self.health_check_calls += 1
        return True


def _build_real_analysis_pipeline() -> AnalysisPipeline:
    """Construct a real ``AnalysisPipeline`` the same way
    ``test_stock_agent_smoke.py`` does, using fake I/O boundaries
    (yfinance, plotly) so no network call can occur. This is used only to
    prove the real ``AnalysisPipeline`` can be wrapped by the adapter --
    it is never run.
    """
    return AnalysisPipeline(
        stock_service=StockService(yfinance_module=FakeYFinanceModule()),
        technical_indicator_service=TechnicalIndicatorService(),
        moving_average_service=MovingAverageService(),
        technical_score_service=TechnicalScoreService(),
        fundamental_service=FundamentalService(),
        pattern_service=PatternService(),
        chart_service=ChartService(go_module=FakeGo(), make_subplots_func=_fake_make_subplots),
        news_service=NewsService(yfinance_module=FakeYFinanceModule()),
        backtest_service=BacktestService(),
        risk_management_service=RiskManagementService(),
        scoring_service=ScoringService(),
    )


def test_real_analysis_pipeline_can_be_wrapped_by_adapter():
    """Step 1 + 2: the existing AnalysisPipeline can be instantiated and
    wrapped by AnalysisPipelineAdapter with no modification to either
    class, and the adapter stores it unchanged."""
    pipeline = _build_real_analysis_pipeline()
    adapter = AnalysisPipelineAdapter(pipeline)

    assert adapter._analysis_pipeline is pipeline


def test_adapter_delegates_run_and_health_check():
    """Adapter delegation is verified functionally against a recording
    stub, so this test does not depend on -- or execute -- the real
    AnalysisPipeline's 11-step business logic."""
    recording_pipeline = RecordingPipeline()
    adapter = AnalysisPipelineAdapter(recording_pipeline)

    sentinel_context = object()
    result = adapter.run(sentinel_context)

    assert recording_pipeline.run_calls == [sentinel_context]
    assert result == {"sentinel": sentinel_context}

    health_result = adapter.health_check()

    assert recording_pipeline.health_check_calls == 1
    assert health_result is True


def test_idx_stock_agent_composition_wiring():
    """Steps 3-5: IDXTickerExtractor and IDXStockAgent can be composed
    from the existing pieces via DI only. Verifies wiring only -- no
    run()/chat()/provider/yfinance call anywhere in this test."""
    pipeline = _build_real_analysis_pipeline()
    adapter = AnalysisPipelineAdapter(pipeline)
    extractor = IDXTickerExtractor()

    planner = Planner(provider_manager=ProviderManager(), tool_registry=ToolRegistry())
    memory = ConversationMemory()
    executor = Executor(tool_registry=ToolRegistry())
    tool_context_builder = ToolContextBuilder()

    agent = IDXStockAgent(
        planner,
        memory,
        executor,
        provider_manager=ProviderManager(),
        tool_context_builder=tool_context_builder,
        instrument_extractor=extractor,
        service_pipeline=adapter,
        default_provider_name="gemini",
    )

    assert agent._service_pipeline is adapter
    assert agent._instrument_extractor is extractor
    assert agent._service_pipeline._analysis_pipeline is pipeline