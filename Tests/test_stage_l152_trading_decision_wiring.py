"""
Sprint 152 proof suite -- MarketState -> TradingDecisionAgent
Production Wiring.

Covers: RuntimeAnalysisPipeline's new optional
``trading_decision_agent`` collaborator / ``AnalysisResult
.trading_decision`` (extended), and composition_root's
``TradingDecisionAgent`` wiring (extended). No real network/HTTP/
filesystem call is made anywhere: a fake, in-memory
``BaseVisionProvider`` stands in for Gemini, and ``TradingDecisionAgent``
is exercised with its six real, unmodified Skills (no Tool wired to
``MarketAnalysisSkill``, so it degrades gracefully -- exactly the
documented, never-raise behavior already proven by
``Tests/test_stage_l126_trading_decision_agent_capital_pipeline.py``).

Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l151_vision_wiring.py``.
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
from Core.composition_root import build_application
from Core.tool_context_builder import ToolContextBuilder
from Orchestration.capital_allocation_skill import CapitalAllocationSkill
from Orchestration.market_analysis_skill import MarketAnalysisSkill
from Orchestration.position_risk_skill import PositionRiskSkill
from Orchestration.position_sizing_skill import PositionSizingSkill
from Orchestration.recommendation_skill import RecommendationSkill
from Orchestration.runtime_analysis_pipeline import AnalysisResult, RuntimeAnalysisPipeline
from Orchestration.trade_plan_skill import TradePlanSkill
from Orchestration.trading_decision_agent import TradingDecisionAgent
from Orchestration.vision_market_state_pipeline import VisionMarketStatePipeline
from Providers.base_vision_provider import BaseVisionProvider
from Providers.gemini_vision_provider import GeminiVisionProvider
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


# Fixtures -------------------------------------------------------------
_SERVICE_NAMES = (
    "stock_service", "technical_indicator_service", "moving_average_service",
    "technical_score_service", "fundamental_service", "pattern_service",
    "chart_service", "news_service", "backtest_service",
    "risk_management_service", "scoring_service",
)

# 8 labeled fields that deterministically drive every reasoning Skill
# to a non-UNKNOWN evidence value -> known, fixed market_state.
_FULL_RAW_RESPONSE = (
    "trend: bullish\nsupport: 100\nresistance: 120\ncandlestick_pattern: hammer\n"
    "volume_signal: increasing\nrsi_signal: oversold\nmacd_signal: bullish\nconfidence: high\n"
)


class _FakeService(BaseService):
    """Minimal BaseService: returns a fixed ServiceResult, no I/O."""

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


class _FakeVisionProvider(BaseVisionProvider):
    """Stands in for GeminiVisionProvider: no network, no filesystem."""

    def __init__(self, raw_response: Optional[str] = None, should_fail: bool = False) -> None:
        self.calls = 0
        self._raw_response = raw_response
        self._should_fail = should_fail

    @property
    def name(self) -> str:
        return "fake-vision"

    @property
    def description(self) -> str:
        return "Fake Vision Provider for Sprint 152 tests"

    def analyze(self, vision_prompt: Any) -> Any:
        self.calls += 1
        if self._should_fail:
            raise RuntimeError("simulated vision provider failure")
        vp = vision_prompt if isinstance(vision_prompt, dict) else {}
        return {
            "symbol": vp.get("symbol"), "timeframe": vp.get("timeframe"),
            "chart_path": vp.get("chart_path"), "status": "READY",
            "analysis_status": "PENDING", "prompt_status": "READY",
            "result_status": "COMPLETED", "result": {"raw_response": self._raw_response},
        }


class _RaisingMarketAnalysisSkill(MarketAnalysisSkill):
    """A MarketAnalysisSkill stand-in that always raises, to prove a
    TradingDecisionAgent-side failure never destroys classic_analysis
    or market_state."""

    def execute(self, context: Any) -> Any:  # noqa: D401
        raise RuntimeError("simulated TradingDecisionAgent failure")


def _real_trading_decision_agent() -> TradingDecisionAgent:
    """Mirrors Tests/test_stage_l126_..._real_agent(), minus Tool
    wiring: MarketAnalysisSkill._resolve_tool is deliberately never
    injected here, exercising the documented never-raise degraded
    path (each symbol's TextAnalysisSkill call raises internally and
    is caught by MarketAnalysisSkill, recording analysis=None)."""
    return TradingDecisionAgent(
        MarketAnalysisSkill(),
        RecommendationSkill(),
        PositionRiskSkill(),
        TradePlanSkill(),
        PositionSizingSkill(),
        CapitalAllocationSkill(),
    )


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
    trading_decision_agent: Optional[TradingDecisionAgent],
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


# 1. No chart, no agent injected -- byte-for-byte pre-Sprint-152 behavior.
def scenario_no_chart_preserves_classic_and_market_state_behavior() -> None:
    fake_provider = _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE)
    pipeline = _fresh_pipeline(fake_provider, _real_trading_decision_agent())

    result = pipeline.run(_context(chart_path=None))

    check(isinstance(result, str), "no-chart result is still a str (backward compatible)")
    check(result.market_state is None, "no-chart market_state is still None")
    check(result.trading_decision is None, "no-chart trading_decision is None")
    check(fake_provider.calls == 0, "no-chart request never calls the Vision Provider")


# 2. No trading_decision_agent injected -- market_state still produced,
#    trading_decision stays None (agent not wired == no-op).
def scenario_no_agent_injected_leaves_trading_decision_none() -> None:
    fake_provider = _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE)
    pipeline = _fresh_pipeline(fake_provider, None)
    context = _context(chart_path="/fake/chart.png")

    result = pipeline.run(context)

    check(result.market_state is not None, "market_state is still produced without an injected agent")
    check(result.trading_decision is None, "trading_decision is None when no TradingDecisionAgent was injected")
    check(isinstance(result, str) and len(str(result)) > 0, "classic_analysis text is still produced")


# 3. Chart + agent -- market_state bridges into a real six-Skill result.
def scenario_chart_and_agent_produce_trading_decision() -> None:
    fake_provider = _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE)
    agent = _real_trading_decision_agent()
    pipeline = _fresh_pipeline(fake_provider, agent)
    context = _context(chart_path="/fake/chart.png", ticker="BBCA.JK")

    result = pipeline.run(context)

    check(isinstance(result, str), "chart result is still a str (classic_analysis preserved)")
    check(len(str(result)) > 0, "classic_analysis text is non-empty for chart request")
    check(result.market_state is not None, "chart request produces a market_state")
    check(result.market_state.get("symbol") == "BBCA.JK", "market_state carries the requested symbol")
    check(result.trading_decision is not None, "chart + injected agent produces a trading_decision")
    check(isinstance(result.trading_decision, dict), "trading_decision is a dict")
    check(
        set(result.trading_decision.keys()) == {
            "market", "recommendation", "risk", "trade_plan",
            "position_size", "capital_allocation",
        },
        "trading_decision has exactly TradingDecisionAgent's fixed six-key schema",
    )
    for key in ("market", "recommendation", "risk", "trade_plan", "position_size", "capital_allocation"):
        value = result.trading_decision[key]
        check(hasattr(value, "success") and hasattr(value, "output"), f"trading_decision[{key!r}] is a real SkillResult-shaped object")


# 4. AnalysisResult identity: constructing it directly still works with all three positional/optional args.
def scenario_analysis_result_carries_all_three_fields() -> None:
    ar = AnalysisResult("classic text", {"symbol": "X"}, {"trading_decision": True})
    check(str(ar) == "classic text", "AnalysisResult.__str__ is still exactly the classic text")
    check(ar.market_state == {"symbol": "X"}, "AnalysisResult.market_state is the exact object passed in")
    check(ar.trading_decision == {"trading_decision": True}, "AnalysisResult.trading_decision is the exact object passed in")
    ar_default = AnalysisResult("classic text only")
    check(ar_default.market_state is None, "AnalysisResult defaults market_state to None")
    check(ar_default.trading_decision is None, "AnalysisResult defaults trading_decision to None")


# 5. Vision-failure UNAVAILABLE mapping (no "symbol" key) still bridges safely.
def scenario_vision_failure_market_state_still_bridges_safely() -> None:
    failing_provider = _FakeVisionProvider(should_fail=True)
    agent = _real_trading_decision_agent()
    pipeline = _fresh_pipeline(failing_provider, agent)
    context = _context(chart_path="/fake/chart.png")

    result = pipeline.run(context)

    check(result.market_state is not None, "a deterministic vision-error market_state is still produced")
    check(result.market_state.get("market_state") == "UNAVAILABLE", "vision failure market_state is UNAVAILABLE")
    check("symbol" not in result.market_state, "UNAVAILABLE market_state carries no symbol field")
    check(result.trading_decision is not None, "TradingDecisionAgent still runs on an UNAVAILABLE market_state (empty symbols, never raises)")
    check(isinstance(result.trading_decision, dict), "trading_decision from an UNAVAILABLE market_state is still a dict")
    check(len(str(result)) > 0, "classic_analysis text is unaffected by the vision failure")


# 6. A TradingDecisionAgent-side failure never destroys classic_analysis or market_state.
def scenario_trading_decision_failure_does_not_destroy_classic_output() -> None:
    fake_provider = _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE)
    raising_agent = TradingDecisionAgent(
        _RaisingMarketAnalysisSkill(),
        RecommendationSkill(),
        PositionRiskSkill(),
        TradePlanSkill(),
        PositionSizingSkill(),
        CapitalAllocationSkill(),
    )
    pipeline = _fresh_pipeline(fake_provider, raising_agent)
    context = _context(chart_path="/fake/chart.png")

    result = pipeline.run(context)

    check(isinstance(result, str), "classic_analysis still returned as str after a TradingDecisionAgent failure")
    check(len(str(result)) > 0, "classic_analysis text is non-empty even when TradingDecisionAgent raises")
    check(result.market_state is not None, "market_state is unaffected by a TradingDecisionAgent-side failure")
    check(result.trading_decision is None, "trading_decision is None (caught, not propagated) when the agent raises")


# 7. Determinism across repeated calls.
def scenario_deterministic_repeated_execution() -> None:
    fake_provider = _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE)
    agent = _real_trading_decision_agent()
    pipeline = _fresh_pipeline(fake_provider, agent)
    context = _context(chart_path="/fake/chart.png")

    result_1 = pipeline.run(context)
    result_2 = pipeline.run(context)

    check(str(result_1) == str(result_2), "repeated run() calls produce identical classic_analysis text")
    check(result_1.market_state == result_2.market_state, "repeated run() calls produce identical market_state")
    check(
        set(result_1.trading_decision.keys()) == set(result_2.trading_decision.keys()),
        "repeated run() calls produce trading_decision dicts with the same fixed schema",
    )


# 8. Task built for TradingDecisionAgent carries symbols from market_state, capital=0.
def scenario_task_metadata_seeded_from_market_state_symbol() -> None:
    fake_provider = _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE)
    agent = _real_trading_decision_agent()
    pipeline = _fresh_pipeline(fake_provider, agent)
    context = _context(chart_path="/fake/chart.png", ticker="TLKM.JK")

    result = pipeline.run(context)

    market_output = result.trading_decision["market"]
    check(hasattr(market_output, "output"), "MarketAnalysisSkill result carries an .output (degraded per-symbol path, no Tool wired)")
    stocks = market_output.output.get("stocks") if isinstance(market_output.output, dict) else None
    check(isinstance(stocks, list) and len(stocks) == 1, "exactly one symbol reached MarketAnalysisSkill")
    check(stocks[0]["symbol"] == "TLKM.JK", "the single symbol is exactly the market_state's own symbol field")


# 9. Composition-root production wiring.
def scenario_composition_root_wiring() -> None:
    graph = build_application(provider_name="gemini-l152-test")

    check(isinstance(graph.trading_decision_agent, TradingDecisionAgent), "graph exposes a real, constructed TradingDecisionAgent")
    check(
        graph.runtime_analysis_pipeline._trading_decision_agent is graph.trading_decision_agent,
        "the exact same TradingDecisionAgent instance is injected into runtime_analysis_pipeline (not rebuilt)",
    )
    check(isinstance(graph.gemini_vision_provider, GeminiVisionProvider), "graph still exposes a real GeminiVisionProvider (Sprint 151 unaffected)")
    check(isinstance(graph.vision_market_state_pipeline, VisionMarketStatePipeline), "graph still exposes a real VisionMarketStatePipeline (Sprint 151 unaffected)")
    check(isinstance(graph.runtime_analysis_pipeline, RuntimeAnalysisPipeline), "graph.runtime_analysis_pipeline is still the correct type")
    check(
        not hasattr(TradingDecisionAgent, "run") and not hasattr(TradingDecisionAgent, "chat"),
        "TradingDecisionAgent itself gained no new public method from this wiring",
    )


def main() -> int:
    scenarios = [
        scenario_no_chart_preserves_classic_and_market_state_behavior,
        scenario_no_agent_injected_leaves_trading_decision_none,
        scenario_chart_and_agent_produce_trading_decision,
        scenario_analysis_result_carries_all_three_fields,
        scenario_vision_failure_market_state_still_bridges_safely,
        scenario_trading_decision_failure_does_not_destroy_classic_output,
        scenario_deterministic_repeated_execution,
        scenario_task_metadata_seeded_from_market_state_symbol,
        scenario_composition_root_wiring,
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
    print(f"STAGE L152 TRADING DECISION WIRING RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())