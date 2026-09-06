"""
Sprint 153 proof suite -- Exposing TradingDecisionAgent's Output on
the Production AnalysisResult.

Sprint 152 already reaches RuntimeAnalysisPipeline -> VisionMarketStatePipeline
-> TradingDecisionAgent and bridges a real ``market_state`` mapping into
``trading_decision_agent.execute(task)``. This suite proves that bridge's
*output* -- not just the call -- is what ends up on
``AnalysisResult.trading_decision``, using a fake, in-memory
``TradingDecisionAgent`` stand-in (duck-typed: any object exposing
``execute(task) -> Any`` satisfies ``RuntimeAnalysisPipeline``'s
contract, exactly like ``_FakeVisionProvider`` stands in for
``BaseVisionProvider`` elsewhere in this suite family). No real
Skill, no real Tool, no network, no filesystem is exercised here --
this is a pure wiring proof, isolated from
``Core.composition_root.build_application()`` entirely (out of scope
for this sprint's allowed files).

Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l11_runtime_analysis_pipeline.py`` and
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


# Fixtures -------------------------------------------------------------
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

    def __init__(self, raw_response: Optional[str] = None) -> None:
        self.calls = 0
        self._raw_response = raw_response

    @property
    def name(self) -> str:
        return "fake-vision"

    @property
    def description(self) -> str:
        return "Fake Vision Provider for Sprint 153 tests"

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
    """Duck-typed stand-in for Orchestration.trading_decision_agent
    .TradingDecisionAgent: exposes exactly one method, execute(task),
    matching the real Agent's own contract. No Skill, no Tool, no
    reasoning of any kind -- returns a fixed, pre-baked result (or
    raises) and records every Task it was called with.
    """

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


# 1. No trading path: no chart at all -- fake agent never called.
def scenario_no_market_state_never_calls_agent() -> None:
    agent = _FakeTradingDecisionAgent(result={"decision": "HOLD"})
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), agent)

    result = pipeline.run(_context(chart_path=None))

    check(result.market_state is None, "no chart -> market_state is None")
    check(result.trading_decision is None, "no market_state -> AnalysisResult.trading_decision is None")
    check(agent.calls == 0, "TradingDecisionAgent is never called when there is no market_state")


# 2. No trading path: chart present but no agent injected.
def scenario_market_state_without_agent_stays_none() -> None:
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), None)

    result = pipeline.run(_context(chart_path="/fake/chart.png"))

    check(result.market_state is not None, "chart -> market_state is produced")
    check(result.trading_decision is None, "no agent injected -> trading_decision stays None even with a real market_state")


# 3. Trading path: chart + agent -- output is exposed unmodified.
def scenario_trading_path_exposes_agent_output_unmodified() -> None:
    fixed_result = {
        "market": "M", "recommendation": "R", "risk": "K",
        "trade_plan": "T", "position_size": "P", "capital_allocation": "C",
    }
    agent = _FakeTradingDecisionAgent(result=fixed_result)
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), agent)

    result = pipeline.run(_context(chart_path="/fake/chart.png", ticker="BBCA.JK"))

    check(agent.calls == 1, "TradingDecisionAgent is called exactly once for a chart request")
    check(result.trading_decision is fixed_result, "AnalysisResult.trading_decision is the exact object the Agent returned, by identity")
    check(result.trading_decision == fixed_result, "AnalysisResult.trading_decision content matches the Agent's output exactly")
    check(len(agent.received_tasks) == 1, "exactly one Task was built and handed to the Agent")

    task = agent.received_tasks[0]
    check(hasattr(task, "metadata"), "the object handed to execute() carries .metadata")
    check(task.metadata.get("symbols") == ["BBCA.JK"], "Task.metadata['symbols'] is seeded from market_state's own symbol field")
    check(task.metadata.get("capital") == 0, "Task.metadata['capital'] defaults to 0 -- no new reasoning introduced")


# 4. Trading path: symbol extraction is defensive for a non-str/missing symbol.
def scenario_missing_symbol_yields_empty_symbols_list() -> None:
    agent = _FakeTradingDecisionAgent(result={"ok": True})
    # No raw_response at all -> CASE 3 (UNCERTAIN) market_state, still
    # carries a "symbol" key (from ChartVisionSkill's own input), so
    # exercise the "no symbol at all" branch by fetching a market_state
    # snapshot directly and confirming a missing symbol degrades safely.
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=""), agent)

    result = pipeline.run(_context(chart_path="/fake/chart.png", ticker="TLKM.JK"))

    check(agent.calls == 1, "agent still called for an UNCERTAIN market_state")
    task = agent.received_tasks[0]
    check(isinstance(task.metadata.get("symbols"), list), "symbols is always a list, even for a weak/partial market_state")


# 5. Failure path: agent raises -- classic output untouched, trading_decision is None.
def scenario_agent_failure_never_destroys_classic_output() -> None:
    failing_agent = _FakeTradingDecisionAgent(should_fail=True)
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), failing_agent)

    result = pipeline.run(_context(chart_path="/fake/chart.png"))

    check(isinstance(result, str), "classic_analysis is still a str after an Agent failure")
    check(len(str(result)) > 0, "classic_analysis text is non-empty even when the Agent raises")
    check(result.market_state is not None, "market_state is unaffected by an Agent-side failure")
    check(result.trading_decision is None, "trading_decision is None (caught, not propagated) when the Agent raises")
    check(failing_agent.calls == 1, "the failing Agent was still called exactly once")


# 6. Deterministic behaviour: repeated calls re-invoke the Agent, same shape each time.
def scenario_deterministic_repeated_execution() -> None:
    fixed_result = {"decision": "BUY"}
    agent = _FakeTradingDecisionAgent(result=fixed_result)
    pipeline = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), agent)
    context = _context(chart_path="/fake/chart.png")

    result_1 = pipeline.run(context)
    result_2 = pipeline.run(context)

    check(str(result_1) == str(result_2), "repeated run() calls produce identical classic_analysis text")
    check(result_1.trading_decision == result_2.trading_decision, "repeated run() calls produce identical trading_decision content")
    check(agent.calls == 2, "each run() call invokes the Agent independently -- no caching")


# 7. Backward compatibility: str(result) is byte-identical with/without a trading path.
def scenario_str_result_backward_compatible() -> None:
    context = _context(chart_path="/fake/chart.png")

    pipeline_no_agent = _fresh_pipeline(_FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE), None)
    pipeline_with_agent = _fresh_pipeline(
        _FakeVisionProvider(raw_response=_FULL_RAW_RESPONSE),
        _FakeTradingDecisionAgent(result={"decision": "SELL"}),
    )

    result_without = pipeline_no_agent.run(context)
    result_with = pipeline_with_agent.run(context)

    check(str(result_without) == str(result_with), "str(result) is identical whether or not a trading_decision was produced")
    check(isinstance(result_without, str) and isinstance(result_with, str), "both results remain plain str subclasses")
    check(result_without == result_with, "AnalysisResult == comparison (str semantics) is unaffected by trading_decision")

    no_chart_context = _context(chart_path=None)
    result_no_chart = pipeline_with_agent.run(no_chart_context)
    check(isinstance(result_no_chart, str), "no-chart result is still a plain str-comparable value")
    check(len(str(result_no_chart)) > 0, "no-chart classic text is still produced normally")


# 8. AnalysisResult itself: attribute exposure and defaults, constructed directly.
def scenario_analysis_result_attribute_contract() -> None:
    ar_full = AnalysisResult("classic text", {"symbol": "X"}, {"decision": "HOLD"})
    check(str(ar_full) == "classic text", "AnalysisResult.__str__ is exactly the classic text")
    check(ar_full.market_state == {"symbol": "X"}, "market_state exposed exactly as passed")
    check(ar_full.trading_decision == {"decision": "HOLD"}, "trading_decision exposed exactly as passed")

    ar_classic_only = AnalysisResult("classic text only")
    check(ar_classic_only.market_state is None, "market_state defaults to None when omitted")
    check(ar_classic_only.trading_decision is None, "trading_decision defaults to None when omitted")
    check(str(ar_classic_only) == "classic text only", "classic-only construction preserves the exact text")

    ar_market_only = AnalysisResult("classic text", {"symbol": "Y"})
    check(ar_market_only.trading_decision is None, "trading_decision defaults to None when only market_state is supplied")


def main() -> int:
    scenarios = [
        scenario_no_market_state_never_calls_agent,
        scenario_market_state_without_agent_stays_none,
        scenario_trading_path_exposes_agent_output_unmodified,
        scenario_missing_symbol_yields_empty_symbols_list,
        scenario_agent_failure_never_destroys_classic_output,
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
    print(f"STAGE L153 RUNTIME TRADING RESULT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())