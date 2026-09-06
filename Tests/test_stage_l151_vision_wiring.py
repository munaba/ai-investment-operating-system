"""
Phase 13, Sprint 151 proof suite -- Vision-to-Market-State Production
Wiring.

Covers: VisionMarketStatePipeline (new), RuntimeAnalysisPipeline's
optional vision_pipeline/AnalysisResult (extended), and
composition_root's GeminiVisionProvider/VisionMarketStatePipeline
wiring (extended). No real network/HTTP call is made anywhere: a
fake, in-memory BaseVisionProvider stands in for Gemini everywhere
the chain is actually run; the real GeminiVisionProvider is only ever
constructed (never .analyze()-called) to prove reachability.
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
from Orchestration.runtime_analysis_pipeline import AnalysisResult, RuntimeAnalysisPipeline
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


# Fixtures
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
    """Stands in for GeminiVisionProvider: no network, no filesystem.

    Records call count (for "called exactly once") and can be told to
    raise, to prove a vision-specific failure never reaches the
    classic analysis result.
    """

    def __init__(self, raw_response: Optional[str] = None, should_fail: bool = False) -> None:
        self.calls = 0
        self._raw_response = raw_response
        self._should_fail = should_fail

    @property
    def name(self) -> str:
        return "fake-vision"

    @property
    def description(self) -> str:
        return "Fake Vision Provider for Sprint 151 tests"

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


def _fresh_pipeline(vision_provider: Optional[BaseVisionProvider]) -> RuntimeAnalysisPipeline:
    ToolRegistry.reset()
    registry = ToolRegistry()
    executor = Executor(registry)
    vision_pipeline = VisionMarketStatePipeline(vision_provider) if vision_provider is not None else None
    return RuntimeAnalysisPipeline(
        executor=executor, analysis_pipeline=_fresh_analysis_pipeline(),
        tool_context_builder=ToolContextBuilder(), tool_registry=registry,
        vision_pipeline=vision_pipeline,
    )


# 1. No-chart request preserves classic behavior exactly.
def scenario_no_chart_preserves_classic_behavior() -> None:
    fake_provider = _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE)
    with_vision = _fresh_pipeline(fake_provider)
    without_vision = _fresh_pipeline(None)

    result_with = with_vision.run(_context(chart_path=None))
    result_without = without_vision.run(_context(chart_path=None))

    check(isinstance(result_with, str), "no-chart result is still a str (backward compatible)")
    check(str(result_with) == str(result_without), "no-chart classic text identical with/without vision_pipeline wired")
    check(result_with.market_state is None, "no-chart market_state is None")
    check(fake_provider.calls == 0, "no-chart request never calls the Vision Provider")


def scenario_missing_or_empty_chart_path_variants() -> None:
    for bad_value in ("", None, 123):
        fake_provider = _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE)
        pipeline = _fresh_pipeline(fake_provider)
        context = _context(chart_path=None)
        if bad_value is not None:
            context = ServiceContext(
                agent_name="test-agent", provider_name="test-provider", request_id="req-1",
                user_input="Analisa BBCA.JK", conversation_history=[],
                metadata={"ticker": "BBCA.JK", "interval": "1D", "chart_path": bad_value},
            )
        result = pipeline.run(context)
        check(result.market_state is None, f"chart_path={bad_value!r} treated as no chart input")
        check(fake_provider.calls == 0, f"chart_path={bad_value!r} never calls the Vision Provider")


# 2. Chart request executes every modern stage in order, provider called once.
def scenario_chart_request_produces_market_state() -> None:
    fake_provider = _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE)
    pipeline = _fresh_pipeline(fake_provider)
    context = _context(chart_path="/fake/chart.png")

    result = pipeline.run(context)

    check(isinstance(result, str), "chart result is still a str (classic_analysis preserved)")
    check(len(str(result)) > 0, "classic_analysis text is non-empty for chart request")
    check(fake_provider.calls == 1, "Vision Provider called exactly once per run()")
    check(result.market_state is not None, "chart request produces a market_state")
    check(isinstance(result.market_state, dict), "market_state is a mapping")


def scenario_full_chain_reaches_correct_market_state() -> None:
    """Parsed vision output reaches all five reasoning Skills,
    EvidenceFusionSkill receives all five, MarketStateSkill's output
    matches the crafted raw_response exactly -- exercised directly
    against VisionMarketStatePipeline for field-level assertions."""
    fake_provider = _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE)
    pipeline = VisionMarketStatePipeline(fake_provider)

    market_state = pipeline.run(symbol="BBCA.JK", timeframe="1D", chart_path="/fake/chart.png")

    check(fake_provider.calls == 1, "VisionMarketStatePipeline calls the provider exactly once")
    check(market_state["symbol"] == "BBCA.JK", "market_state carries the symbol through the whole chain")
    check(market_state["timeframe"] == "1D", "market_state carries the timeframe through the whole chain")
    check(market_state["agreement"] == "FULL", "all five reasoning Skills produced non-UNKNOWN evidence -> FULL agreement")
    check(market_state["confidence"] == "HIGH", "EvidenceFusionSkill resolved HIGH confidence from full agreement")
    check(market_state["market_state"] == "CONFIRMED", "MarketStateSkill resolved CONFIRMED from FULL/HIGH consensus")
    check(
        set(market_state.keys()) == {
            "symbol", "timeframe", "market_state", "state_strength",
            "state_reason", "confidence", "agreement", "summary",
        },
        "market_state has exactly MarketStateSkill's fixed schema (no extra fields invented)",
    )


def scenario_partial_evidence_yields_developing_state() -> None:
    """Partial vision fields flow through every stage without error,
    landing on PARTIAL/DEVELOPING deterministically."""
    partial_response = "trend: bullish\n"
    fake_provider = _FakeVisionProvider(raw_response=partial_response)
    pipeline = VisionMarketStatePipeline(fake_provider)

    market_state = pipeline.run(symbol="TLKM.JK", timeframe="1H", chart_path="/fake/chart2.png")

    check(market_state["agreement"] == "PARTIAL", "partial vision fields yield PARTIAL agreement")
    check(market_state["market_state"] == "DEVELOPING", "partial agreement resolves to DEVELOPING market_state")


# 3. Vision failure never crashes or replaces the classic analysis result.
def scenario_vision_failure_does_not_destroy_classic_output() -> None:
    failing_provider = _FakeVisionProvider(should_fail=True)
    pipeline = _fresh_pipeline(failing_provider)
    context = _context(chart_path="/fake/chart.png")

    result = pipeline.run(context)

    check(isinstance(result, str), "classic_analysis still returned as str after vision failure")
    check(len(str(result)) > 0, "classic_analysis text is non-empty even when vision fails")
    check(failing_provider.calls == 1, "failing Vision Provider was still called exactly once")
    check(result.market_state is not None, "a deterministic vision-error state is returned, not None/silently dropped")
    check(result.market_state.get("market_state") == "UNAVAILABLE", "vision failure surfaces as a deterministic UNAVAILABLE market_state")
    check("error" in result.market_state, "vision failure error is not silently swallowed -- surfaced in market_state")


# 4. Determinism across repeated calls.
def scenario_deterministic_repeated_execution() -> None:
    fake_provider = _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE)
    pipeline = _fresh_pipeline(fake_provider)
    context = _context(chart_path="/fake/chart.png")

    result_1 = pipeline.run(context)
    result_2 = pipeline.run(context)

    check(str(result_1) == str(result_2), "repeated run() calls produce identical classic_analysis text")
    check(result_1.market_state == result_2.market_state, "repeated run() calls produce identical market_state")
    check(fake_provider.calls == 2, "each run() call invokes the Vision Provider independently (no caching)")


# 5. No trading action/recommendation is ever produced by this chain.
def scenario_no_trading_action_triggered() -> None:
    fake_provider = _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE)
    pipeline = VisionMarketStatePipeline(fake_provider)
    market_state = pipeline.run(symbol="BBCA.JK", timeframe="1D", chart_path="/fake/chart.png")

    forbidden_keys = {"recommendation", "action", "order", "position_sizing", "allocation", "trading_decision"}
    check(
        forbidden_keys.isdisjoint(market_state.keys()),
        "market_state contains no recommendation/order/allocation/trading-decision fields",
    )


# 6. Production graph construction: GeminiVisionProvider reachable/injectable,    no real network call performed anywhere in this scenario.
def scenario_composition_root_wiring() -> None:
    graph = build_application(provider_name="gemini-l151-test")

    check(isinstance(graph.gemini_vision_provider, GeminiVisionProvider), "graph exposes a real, constructed GeminiVisionProvider")
    check(isinstance(graph.vision_market_state_pipeline, VisionMarketStatePipeline), "graph exposes a real VisionMarketStatePipeline")
    check(
        graph.runtime_analysis_pipeline._vision_pipeline is graph.vision_market_state_pipeline,
        "the exact same VisionMarketStatePipeline instance is injected into runtime_analysis_pipeline (not rebuilt)",
    )
    check(
        graph.vision_market_state_pipeline._vision_provider is graph.gemini_vision_provider,
        "VisionMarketStatePipeline is wired to the exact same GeminiVisionProvider instance the graph exposes",
    )
    check(isinstance(graph.runtime_analysis_pipeline, RuntimeAnalysisPipeline), "graph.runtime_analysis_pipeline is still the correct type")


def main() -> int:
    scenarios = [
        scenario_no_chart_preserves_classic_behavior,
        scenario_missing_or_empty_chart_path_variants,
        scenario_chart_request_produces_market_state,
        scenario_full_chain_reaches_correct_market_state,
        scenario_partial_evidence_yields_developing_state,
        scenario_vision_failure_does_not_destroy_classic_output,
        scenario_deterministic_repeated_execution,
        scenario_no_trading_action_triggered,
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
    print(f"STAGE L151 VISION WIRING RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())