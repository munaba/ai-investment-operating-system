"""
Stage L11 proof suite -- Runtime as Execution Kernel (Phase 1).

Scope (per the LOCKED Stage L11 baseline, approved before coding):
  - Orchestration/runtime_analysis_pipeline.py (NEW):
      * RuntimeAnalysisPipeline -- a new facade class (not an evolution of
        AnalysisPipelineAdapter) that runs the existing 11-step
        AnalysisPipeline through the Runtime execution kernel (via
        Executor) as a single Tool call per RuntimeAnalysisPipeline.run()
        invocation.
      * The Tool handler is a private implementation detail: registered
        under a unique name for the duration of one run() call, then
        unregistered, so RuntimeAnalysisPipeline itself stays stateless.
      * ToolContextBuilder.build() runs inside the Tool handler -- only
        the final str crosses the Runtime/Executor JSON boundary.
  - Core/composition_root.py (additive only):
      * ApplicationGraph gains one new field, `runtime_analysis_pipeline`.
      * New `_build_runtime_analysis_pipeline()` factory, called from
        `build_application()`.
      * Nothing about `agent`'s own construction/call path changes --
        StockAgent still runs `analysis_pipeline` directly, unchanged.

Explicitly NOT changed by this stage (locked):
Orchestration/analysis_pipeline_adapter.py, Core/analysis_pipeline.py,
Core/tool_context_builder.py, Agents/executor.py, Core/runtime.py,
Agents/sandbox.py, Agents/tool_registry.py, Agents/stock_agent.py,
Core/approval_config.py.

Cakupan skenario:
  1. RuntimeAnalysisPipeline.run() produces the exact same formatted
     string as calling AnalysisPipeline.run() + ToolContextBuilder.build()
     directly, for the same ServiceContext (behavioral parity with the
     pre-existing non-Runtime call path).
  2. The private Tool is gone from ToolRegistry after run() returns
     (registry does not grow across repeated calls).
  3. The private Tool is still unregistered even when the pipeline
     raises inside the handler -- and the exception surfaces as
     Core.exceptions.ToolExecutionError (Runtime's existing error-as-data
     contract), not a silent failure or a registry leak.
  4. RuntimeAnalysisPipeline is stateless across calls: two run() calls
     with two different ServiceContexts in sequence both succeed and
     produce independently-correct output (no leaked state between
     calls).
  5. health_check() delegates to the wrapped AnalysisPipeline's own
     health_check().
  6. build_application() constructs a real
     ApplicationGraph.runtime_analysis_pipeline of the correct type,
     sharing the same tool_registry/executor/analysis_pipeline the rest
     of the graph uses -- and graph.agent.analysis_pipeline is still the
     bare AnalysisPipeline instance (not wrapped), proving the existing
     StockAgent call path is untouched.
  7. AnalysisPipelineAdapter (locked, out of scope) still behaves as pure
     delegation -- re-proven functionally, not just left alone by
     inspection.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Agents.executor import Executor, ToolExecutionError
from Agents.tool_registry import ToolRegistry
from Core.analysis_pipeline import AnalysisPipeline
from Core.composition_root import ApplicationGraph, build_application
from Core.tool_context_builder import ToolContextBuilder
from Orchestration.analysis_pipeline_adapter import AnalysisPipelineAdapter
from Orchestration.runtime_analysis_pipeline import RuntimeAnalysisPipeline
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


# ---------------------------------------------------------------------------
# Fixtures -- lightweight fake services (no yfinance/network), matching the
# 11 `.name` values ToolContextBuilder._SECTION_ORDER expects.
# ---------------------------------------------------------------------------
_SERVICE_NAMES = (
    "stock_service",
    "technical_indicator_service",
    "moving_average_service",
    "technical_score_service",
    "fundamental_service",
    "pattern_service",
    "chart_service",
    "news_service",
    "backtest_service",
    "risk_management_service",
    "scoring_service",
)


class _FakeService(BaseService):
    """Minimal BaseService: returns a fixed ServiceResult, no I/O."""

    def __init__(self, name: str, *, fail: bool = False) -> None:
        self._name = name
        self._fail = fail

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
        if self._fail:
            raise RuntimeError(f"Simulated failure in {self._name}")
        ticker = context.get_metadata("ticker", "UNKNOWN")
        return ServiceResult.ok(data={"ticker": ticker, "value": f"{self._name}-ok"})

    def health_check(self) -> bool:
        return True


def _fresh_analysis_pipeline(*, fail_service: str | None = None) -> AnalysisPipeline:
    services = {name: _FakeService(name, fail=(name == fail_service)) for name in _SERVICE_NAMES}
    return AnalysisPipeline(
        stock_service=services["stock_service"],
        technical_indicator_service=services["technical_indicator_service"],
        moving_average_service=services["moving_average_service"],
        technical_score_service=services["technical_score_service"],
        fundamental_service=services["fundamental_service"],
        backtest_service=services["backtest_service"],
        pattern_service=services["pattern_service"],
        chart_service=services["chart_service"],
        news_service=services["news_service"],
        risk_management_service=services["risk_management_service"],
        scoring_service=services["scoring_service"],
    )


def _fresh_context(ticker: str = "BBCA.JK") -> ServiceContext:
    return ServiceContext(
        agent_name="test-agent",
        provider_name="test-provider",
        request_id="test-request-id",
        user_input=f"Analisa {ticker}",
        conversation_history=[],
        metadata={"ticker": ticker},
    )


def _fresh_registry() -> ToolRegistry:
    """A fresh, isolated ToolRegistry -- same reasoning as
    Tests/test_stage9_1_executor.py::_fresh_registry_with_echo_tool: it is
    a process-wide singleton, so each scenario needs a clean slate.
    """
    ToolRegistry.reset()
    return ToolRegistry()


def _fresh_runtime_pipeline(
    *, fail_service: str | None = None
) -> tuple[RuntimeAnalysisPipeline, ToolRegistry, AnalysisPipeline, ToolContextBuilder]:
    registry = _fresh_registry()
    executor = Executor(registry)
    analysis_pipeline = _fresh_analysis_pipeline(fail_service=fail_service)
    tool_context_builder = ToolContextBuilder()
    runtime_pipeline = RuntimeAnalysisPipeline(
        executor=executor,
        analysis_pipeline=analysis_pipeline,
        tool_context_builder=tool_context_builder,
        tool_registry=registry,
    )
    return runtime_pipeline, registry, analysis_pipeline, tool_context_builder


# ---------------------------------------------------------------------------
# 1. Behavioral parity with the direct (non-Runtime) call path.
# ---------------------------------------------------------------------------
def scenario_output_parity_with_direct_call() -> None:
    runtime_pipeline, _registry, analysis_pipeline, tool_context_builder = _fresh_runtime_pipeline()
    context = _fresh_context("BBCA.JK")

    via_runtime = runtime_pipeline.run(context)

    direct_results = analysis_pipeline.run(context)
    via_direct = tool_context_builder.build(direct_results)

    check(
        via_runtime == via_direct,
        "RuntimeAnalysisPipeline.run() output is byte-for-byte identical to "
        "AnalysisPipeline.run() + ToolContextBuilder.build() called directly",
    )
    check(isinstance(via_runtime, str) and len(via_runtime) > 0, "run() returns a non-empty str")


# ---------------------------------------------------------------------------
# 2. Private Tool does not leak into the registry after a successful call.
# ---------------------------------------------------------------------------
def scenario_tool_unregistered_after_success() -> None:
    runtime_pipeline, registry, _ap, _tcb = _fresh_runtime_pipeline()

    before = len(registry.list())
    runtime_pipeline.run(_fresh_context("BBCA.JK"))
    after_one_call = len(registry.list())
    runtime_pipeline.run(_fresh_context("TLKM.JK"))
    after_two_calls = len(registry.list())

    check(before == 0, "registry starts empty")
    check(after_one_call == before, "registry has no leftover Tool after one run() call")
    check(after_two_calls == before, "registry has no leftover Tool after a second run() call (no growth)")


# ---------------------------------------------------------------------------
# 3. Private Tool is unregistered even when the handler raises; exception
#    surfaces as ToolExecutionError (Runtime's existing error-as-data path).
# ---------------------------------------------------------------------------
def scenario_tool_unregistered_after_failure() -> None:
    runtime_pipeline, registry, _ap, _tcb = _fresh_runtime_pipeline(fail_service="stock_service")

    raised = None
    try:
        runtime_pipeline.run(_fresh_context("BBCA.JK"))
    except ToolExecutionError as exc:
        raised = exc

    check(raised is not None, "a failing service inside the Tool handler surfaces as ToolExecutionError")
    check(len(registry.list()) == 0, "registry has no leftover Tool after a failed run() call")


# ---------------------------------------------------------------------------
# 4. Stateless across calls -- two different contexts, independently correct.
# ---------------------------------------------------------------------------
def scenario_stateless_across_calls() -> None:
    runtime_pipeline, _registry, _ap, _tcb = _fresh_runtime_pipeline()

    result_a = runtime_pipeline.run(_fresh_context("BBCA.JK"))
    result_b = runtime_pipeline.run(_fresh_context("TLKM.JK"))

    check("BBCA.JK" in result_a, "first call's output reflects its own ticker (BBCA.JK)")
    check("TLKM.JK" in result_b, "second call's output reflects its own ticker (TLKM.JK), not leaked from the first")
    check(result_a != result_b, "two different contexts produce two different outputs (no cross-call state)")


# ---------------------------------------------------------------------------
# 5. health_check() delegation.
# ---------------------------------------------------------------------------
def scenario_health_check_delegates() -> None:
    runtime_pipeline, _registry, analysis_pipeline, _tcb = _fresh_runtime_pipeline()
    check(
        runtime_pipeline.health_check() == analysis_pipeline.health_check(),
        "RuntimeAnalysisPipeline.health_check() delegates to the wrapped AnalysisPipeline",
    )


# ---------------------------------------------------------------------------
# 6. Composition-root wiring: additive, StockAgent's own path untouched.
# ---------------------------------------------------------------------------
def scenario_composition_root_wiring() -> None:
    ToolRegistry.reset()
    graph: ApplicationGraph = build_application(
        provider_name="fake-provider-l11-test",
        provider_kind="gemini",
        agent_name="stock_agent_l11_test",
    )

    check(
        isinstance(graph.runtime_analysis_pipeline, RuntimeAnalysisPipeline),
        "graph.runtime_analysis_pipeline is a real RuntimeAnalysisPipeline",
    )
    check(
        graph.runtime_analysis_pipeline._tool_registry is graph.tool_registry,  # noqa: SLF001 -- deliberate white-box check
        "graph.runtime_analysis_pipeline shares the graph's own tool_registry singleton",
    )
    check(
        graph.runtime_analysis_pipeline._executor is graph.executor,  # noqa: SLF001
        "graph.runtime_analysis_pipeline shares the graph's own executor",
    )
    check(
        type(graph.agent.analysis_pipeline) is AnalysisPipeline,
        "graph.agent.analysis_pipeline is still the bare AnalysisPipeline (StockAgent's own path is untouched)",
    )
    check(
        graph.agent.analysis_pipeline is not graph.runtime_analysis_pipeline,
        "StockAgent does not run through RuntimeAnalysisPipeline in Phase 1 (additive-only, no swap)",
    )


# ---------------------------------------------------------------------------
# 7. AnalysisPipelineAdapter (locked) still pure delegation -- functional
#    re-proof, this stage touches nothing in that file.
# ---------------------------------------------------------------------------
def scenario_adapter_still_pure_delegation() -> None:
    analysis_pipeline = _fresh_analysis_pipeline()
    adapter = AnalysisPipelineAdapter(analysis_pipeline)
    context = _fresh_context("BBCA.JK")

    check(
        adapter.health_check() == analysis_pipeline.health_check(),
        "AnalysisPipelineAdapter.health_check() still pure delegation (Stage L11 did not touch this file)",
    )
    adapter_result = adapter.run(context)
    direct_result = analysis_pipeline.run(_fresh_context("BBCA.JK"))
    check(
        {k: v.data for k, v in adapter_result.items()} == {k: v.data for k, v in direct_result.items()},
        "AnalysisPipelineAdapter.run() still pure delegation (Stage L11 did not touch this file)",
    )


def main() -> int:
    scenarios = [
        scenario_output_parity_with_direct_call,
        scenario_tool_unregistered_after_success,
        scenario_tool_unregistered_after_failure,
        scenario_stateless_across_calls,
        scenario_health_check_delegates,
        scenario_composition_root_wiring,
        scenario_adapter_still_pure_delegation,
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
    print(f"STAGE L11 RUNTIME ANALYSIS PIPELINE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())