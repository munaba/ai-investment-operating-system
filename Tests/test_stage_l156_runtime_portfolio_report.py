"""Sprint 156 proof suite -- Exposing the Final PortfolioReport on the
Production AnalysisResult.

TradingDecisionAgent (Sprint 154) returns a fourteen-key dict whose last
entry, keyed "portfolio_report", is the identity-forwarded
PortfolioReportSkill result. RuntimeAnalysisPipeline (152/153) already
exposes that whole dict as AnalysisResult.trading_decision. This suite
proves the new AnalysisResult.portfolio_report surface: a pure, derived,
identity-forwarded read of trading_decision["portfolio_report"] -- no
copy/transform/merge -- that changes nothing about classic str output.

Uses a fake, duck-typed TradingDecisionAgent stand-in, exactly like
Tests/test_stage_l153_runtime_trading_result.py. No real Skill, Tool,
network, or filesystem is exercised.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Agents.executor import Executor
from Agents.tool_registry import ToolRegistry
from Core.analysis_pipeline import AnalysisPipeline
from Core.tool_context_builder import ToolContextBuilder
from Orchestration.runtime_analysis_pipeline import AnalysisResult, RuntimeAnalysisPipeline
from Orchestration.vision_market_state_pipeline import VisionMarketStatePipeline
from Providers.base_vision_provider import BaseVisionProvider
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult

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

_SERVICE_NAMES = (
    "stock_service", "technical_indicator_service", "moving_average_service",
    "technical_score_service", "fundamental_service", "pattern_service",
    "chart_service", "news_service", "backtest_service",
    "risk_management_service", "scoring_service",
)

_FULL_RAW_RESPONSE = (
    "trend: bullish\nsupport: 100\nresistance: 120\ncandlestick_pattern: hammer\n"
    "volume_signal: increasing\nrsi_signal: oversold\nmacd_signal: bullish\nconfidence: high\n"
)

class _FakeService(BaseService):  # Minimal BaseService: fixed ServiceResult, no I/O.
    def __init__(self, name: str) -> None:
        self._name = name
    @property
    def name(self) -> str:
        return self._name
    @property
    def description(self) -> str:
        return f"fake {self._name}"
    @property
    def category(self) -> str:
        return "test"
    def execute(self, context: ServiceContext) -> ServiceResult:
        ticker = context.get_metadata("ticker", "UNKNOWN")
        return ServiceResult.ok(data={"ticker": ticker, "value": f"{self._name}-ok"})
    def health_check(self) -> bool:
        return True

class _FakeVisionProvider(BaseVisionProvider):  # stands in for GeminiVisionProvider
    def __init__(self, raw_response: Optional[str] = None) -> None:
        self.calls = 0
        self._raw_response = raw_response
    @property
    def name(self) -> str:
        return "fake-vision"
    @property
    def description(self) -> str:
        return "Fake Vision Provider for Sprint 156 tests"
    def analyze(self, vision_prompt: Any) -> Any:
        self.calls += 1
        vp = vision_prompt if isinstance(vision_prompt, dict) else {}
        return {
            "symbol": vp.get("symbol"), "timeframe": vp.get("timeframe"),
            "chart_path": vp.get("chart_path"), "status": "READY",
            "analysis_status": "PENDING", "prompt_status": "READY",
            "result_status": "COMPLETED", "result": {"raw_response": self._raw_response},
        }

class _FakeTradingDecisionAgent:
    """Duck-typed stand-in: execute(task) returns a fixed result (or raises), recording every Task received."""
    def __init__(self, result: Any = None, should_fail: bool = False) -> None:
        self.calls = 0
        self.received_tasks: List[Any] = []
        self._result = result
        self._should_fail = should_fail
    def execute(self, task: Any) -> Any:
        self.calls += 1
        self.received_tasks.append(task)
        if self._should_fail:
            raise RuntimeError("simulated TradingDecisionAgent failure")
        return self._result

def _fresh_analysis_pipeline() -> AnalysisPipeline:
    services = {name: _FakeService(name) for name in _SERVICE_NAMES}
    return AnalysisPipeline(
        stock_service=services["stock_service"],
        technical_indicator_service=services["technical_indicator_service"],
        moving_average_service=services["moving_average_service"],
        technical_score_service=services["technical_score_service"],
        fundamental_service=services["fundamental_service"],
        pattern_service=services["pattern_service"],
        chart_service=services["chart_service"],
        news_service=services["news_service"],
        backtest_service=services["backtest_service"],
        risk_management_service=services["risk_management_service"],
        scoring_service=services["scoring_service"],
    )

def _context(*, chart_path: Optional[str], ticker: str = "BBCA.JK") -> ServiceContext:
    metadata = {"ticker": ticker, "interval": "1D"}
    if chart_path is not None:
        metadata["chart_path"] = chart_path
    return ServiceContext(
        agent_name="test-agent", provider_name="test-provider", request_id="req-1",
        user_input=f"Analisa {ticker}", conversation_history=[], metadata=metadata,
    )

def _fresh_pipeline(
    vision_provider: Optional[BaseVisionProvider],
    trading_decision_agent: Optional[Any],
) -> RuntimeAnalysisPipeline:
    ToolRegistry.reset()
    registry = ToolRegistry()
    executor = Executor(registry)
    vision_pipeline = VisionMarketStatePipeline(vision_provider) if vision_provider is not None else None
    return RuntimeAnalysisPipeline(
        executor=executor, analysis_pipeline=_fresh_analysis_pipeline(),
        tool_context_builder=ToolContextBuilder(), tool_registry=registry,
        vision_pipeline=vision_pipeline,
        trading_decision_agent=trading_decision_agent,
    )

# Sentinel stand-in for a real PortfolioReportSkill SkillResult -- enough
# to prove identity forwarding; its exact type is never inspected.
class _FakePortfolioReportResult:
    def __init__(self, label: str) -> None:
        self.label = label

def _fourteen_key_trading_decision(portfolio_report: Any) -> dict:
    """Shaped exactly like the real TradingDecisionAgent.execute() return
    value: fourteen keys, the last one "portfolio_report"."""
    return {
        "market": "M", "recommendation": "R", "risk": "K",
        "trade_plan": "T", "position_size": "P", "capital_allocation": "C",
        "order_validation": "OV", "paper_trading": "PT", "trade_history": "TH",
        "portfolio_update": "PU", "portfolio_monitor": "PM",
        "portfolio_performance": "PP", "portfolio_alert": "PA",
        "portfolio_report": portfolio_report,
    }

def scenario_success_path_exposes_portfolio_report_by_identity() -> None:
    report = _FakePortfolioReportResult("final-report")
    trading_decision = _fourteen_key_trading_decision(report)
    agent = _FakeTradingDecisionAgent(result=trading_decision)
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), agent)
    result = pipeline.run(_context(chart_path="/fake/chart.png"))
    check(agent.calls == 1, "TradingDecisionAgent is called exactly once for a chart request")
    check(result.trading_decision is trading_decision, "trading_decision is the exact fourteen-key dict returned by the Agent")
    check(result.portfolio_report is report, "portfolio_report is the exact same object as trading_decision['portfolio_report'] (identity)")
    check(result.portfolio_report is trading_decision["portfolio_report"], "portfolio_report matches trading_decision['portfolio_report'] by identity, not equality")
    check(result.portfolio_report.label == "final-report", "the forwarded object's own state is untouched -- no copy/transform")

def scenario_identity_forwarding_not_value_equality() -> None:
    report_a = _FakePortfolioReportResult("same-label")
    report_b = _FakePortfolioReportResult("same-label")
    trading_decision = _fourteen_key_trading_decision(report_a)
    agent = _FakeTradingDecisionAgent(result=trading_decision)
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), agent)
    result = pipeline.run(_context(chart_path="/fake/chart.png"))
    check(result.portfolio_report is report_a, "portfolio_report is report_a by identity")
    check(result.portfolio_report is not report_b, "portfolio_report is not a distinct-but-equal object -- true identity forwarding")

def scenario_no_trading_decision_yields_none_portfolio_report() -> None:
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), None)
    result = pipeline.run(_context(chart_path="/fake/chart.png"))
    check(result.market_state is not None, "chart -> market_state is still produced")
    check(result.trading_decision is None, "no agent injected -> trading_decision stays None")
    check(result.portfolio_report is None, "no trading_decision -> portfolio_report is None")

def scenario_no_chart_yields_none_portfolio_report() -> None:
    agent = _FakeTradingDecisionAgent(result=_fourteen_key_trading_decision(_FakePortfolioReportResult("unused")))
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), agent)
    result = pipeline.run(_context(chart_path=None))
    check(result.trading_decision is None, "no chart -> trading_decision is None")
    check(result.portfolio_report is None, "no chart -> portfolio_report is None")
    check(agent.calls == 0, "TradingDecisionAgent is never called when there is no market_state")

def scenario_trading_decision_missing_key_yields_none() -> None:
    partial = {"market": "M", "recommendation": "R"}
    agent = _FakeTradingDecisionAgent(result=partial)
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), agent)
    result = pipeline.run(_context(chart_path="/fake/chart.png"))
    check(result.trading_decision == partial, "trading_decision holds the Agent's dict, even without a portfolio_report key")
    check(result.portfolio_report is None, "trading_decision without a 'portfolio_report' key -> portfolio_report is None, no KeyError")

def scenario_non_mapping_trading_decision_yields_none() -> None:
    agent = _FakeTradingDecisionAgent(result="not-a-mapping")
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), agent)
    result = pipeline.run(_context(chart_path="/fake/chart.png"))
    check(result.trading_decision == "not-a-mapping", "trading_decision holds whatever the Agent returned, unmodified")
    check(result.portfolio_report is None, "a non-Mapping trading_decision -> portfolio_report is None, never raises")

def scenario_agent_failure_yields_none_portfolio_report() -> None:
    failing_agent = _FakeTradingDecisionAgent(should_fail=True)
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), failing_agent)
    result = pipeline.run(_context(chart_path="/fake/chart.png"))
    check(isinstance(result, str), "classic_analysis is still a str after an Agent failure")
    check(len(str(result)) > 0, "classic_analysis text is non-empty even when the Agent raises")
    check(result.trading_decision is None, "trading_decision is None (caught, not propagated) when the Agent raises")
    check(result.portfolio_report is None, "portfolio_report is None when the Agent raises")
    check(failing_agent.calls == 1, "the failing Agent was still called exactly once")

def scenario_deterministic_repeated_execution() -> None:
    report = _FakePortfolioReportResult("stable-report")
    trading_decision = _fourteen_key_trading_decision(report)
    agent = _FakeTradingDecisionAgent(result=trading_decision)
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), agent)
    context = _context(chart_path="/fake/chart.png")
    result_1 = pipeline.run(context)
    result_2 = pipeline.run(context)
    check(str(result_1) == str(result_2), "repeated run() calls produce identical classic_analysis text")
    check(result_1.portfolio_report is report, "first run's portfolio_report is the same object by identity")
    check(result_2.portfolio_report is report, "second run's portfolio_report is the same object by identity")
    check(result_1.portfolio_report is result_2.portfolio_report, "portfolio_report identity is stable across repeated run() calls")
    check(agent.calls == 2, "each run() call invokes the Agent independently -- no caching")

def scenario_str_result_backward_compatible() -> None:
    context = _context(chart_path="/fake/chart.png")
    pipeline_no_agent = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), None)
    pipeline_with_agent = _fresh_pipeline(
        _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE),
        _FakeTradingDecisionAgent(result=_fourteen_key_trading_decision(_FakePortfolioReportResult("r"))),
    )
    result_without = pipeline_no_agent.run(context)
    result_with = pipeline_with_agent.run(context)
    check(str(result_without) == str(result_with), "str(result) is identical whether or not a portfolio_report was produced")
    check(isinstance(result_without, str) and isinstance(result_with, str), "both results remain plain str subclasses")
    check(result_without == result_with, "AnalysisResult == comparison (str semantics) is unaffected by portfolio_report")
    no_chart_context = _context(chart_path=None)
    result_no_chart = pipeline_with_agent.run(no_chart_context)
    check(isinstance(result_no_chart, str), "no-chart result is still a plain str-comparable value")
    check(len(str(result_no_chart)) > 0, "no-chart classic text is still produced normally")
    check(str(result_no_chart) == str(result_without), "classic text is unaffected by whether portfolio_report ends up populated")

def scenario_analysis_result_attribute_contract() -> None:
    report = _FakePortfolioReportResult("direct-construction")
    trading_decision = _fourteen_key_trading_decision(report)
    ar_full = AnalysisResult("classic text", {"symbol": "X"}, trading_decision)
    check(str(ar_full) == "classic text", "AnalysisResult.__str__ is exactly the classic text")
    check(ar_full.trading_decision is trading_decision, "trading_decision exposed exactly as passed, by identity")
    check(ar_full.portfolio_report is report, "portfolio_report derives from the passed-in trading_decision, by identity")
    ar_classic_only = AnalysisResult("classic text only")
    check(ar_classic_only.trading_decision is None, "trading_decision defaults to None when omitted")
    check(ar_classic_only.portfolio_report is None, "portfolio_report defaults to None when trading_decision is omitted (None)")
    check(str(ar_classic_only) == "classic text only", "classic-only construction preserves the exact text")
    ar_market_only = AnalysisResult("classic text", {"symbol": "Y"})
    check(ar_market_only.trading_decision is None, "trading_decision defaults to None when only market_state is supplied")
    check(ar_market_only.portfolio_report is None, "portfolio_report is None when trading_decision is None")
    ar_no_report_key = AnalysisResult("classic text", None, {"market": "M"})
    check(ar_no_report_key.portfolio_report is None, "portfolio_report is None when trading_decision lacks the key, constructed directly")
    ar_none_trading_decision_explicit = AnalysisResult("classic text", None, None)
    check(ar_none_trading_decision_explicit.portfolio_report is None, "explicit None trading_decision -> portfolio_report is None")

def main() -> int:
    scenarios = [
        scenario_success_path_exposes_portfolio_report_by_identity,
        scenario_identity_forwarding_not_value_equality,
        scenario_no_trading_decision_yields_none_portfolio_report,
        scenario_no_chart_yields_none_portfolio_report,
        scenario_trading_decision_missing_key_yields_none,
        scenario_non_mapping_trading_decision_yields_none,
        scenario_agent_failure_yields_none_portfolio_report,
        scenario_deterministic_repeated_execution,
        scenario_str_result_backward_compatible,
        scenario_analysis_result_attribute_contract,
    ]
    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()
    print("\n" + "=" * 60)
    print(f"STAGE L156 RUNTIME PORTFOLIO REPORT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())