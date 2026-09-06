
"""
Stage L12 proof suite -- Production Runtime Activation (Option A).

Scope (per the LOCKED Stage L12 baseline, approved before coding):
  - Agents/stock_agent.py (additive only):
      * StockAgent.__init__ gains one new, optional constructor argument,
        `runtime_analysis_pipeline: Optional[RuntimeAnalysisPipeline] = None`.
      * `_run_service_pipeline()` branches on it:
          - not None -> routes the ServiceContext through
            `RuntimeAnalysisPipeline.run()` (i.e. through Core.runtime.Runtime
            as the execution kernel) and returns its already-formatted str
            directly -- `self.tool_context_builder.build()` is NOT called a
            second time on this path.
          - None (the default) -> byte-for-byte the pre-Stage-L12 path:
            `self.analysis_pipeline.run(context)` then
            `self.tool_context_builder.build(results)`.
  - Core/composition_root.py (additive only):
      * `build_application()` now passes the already-constructed
        `runtime_analysis_pipeline` into `StockAgent`'s new constructor
        argument -- the one and only place in the production graph that
        activates the Runtime-kernel path for StockAgent.

Explicitly NOT changed by this stage (locked, out of scope):
Orchestration/runtime_analysis_pipeline.py, Orchestration/analysis_pipeline_adapter.py,
Core/analysis_pipeline.py, Core/tool_context_builder.py, Agents/executor.py,
Core/runtime.py, Agents/sandbox.py, Agents/tool_registry.py, Agents/market_analysis_agent.py,
Core/approval_config.py. No existing StockAgent constructor call site across the
test suite is modified by this stage -- none of them pass the new argument, so
all keep exercising the pre-existing (None) fallback path unmodified.

Cakupan skenario:
  1. Fallback path (runtime_analysis_pipeline=None) is byte-for-byte unchanged:
     StockAgent.chat() end-to-end produces the same reply/tool-message shape
     as before this stage.
  2. Runtime path (runtime_analysis_pipeline given) produces output identical
     to the fallback path for the same input -- end-to-end through
     StockAgent.chat(), not just RuntimeAnalysisPipeline in isolation (already
     proven at that level by Stage L11's own suite).
  3. Runtime path leaves no leftover private Tool in ToolRegistry across
     multiple StockAgent.chat() calls (registry hygiene holds through the
     full agent, not just direct RuntimeAnalysisPipeline.run() calls).
  4. Known, accepted difference on the Runtime path: an unexpected exception
     (e.g. from ToolContextBuilder) surfaces as Core.exceptions.ToolExecutionError,
     whereas the fallback path still lets the original exception type through
     unchanged -- proving the two paths do NOT silently converge on the
     unhappy path, exactly as flagged in the Diff-Level Plan.
  5. Composition-root wiring: build_application()'s graph.agent actually
     received the same runtime_analysis_pipeline instance as
     graph.runtime_analysis_pipeline (not a second, separately-built one),
     and graph.agent.analysis_pipeline (the fallback dependency) is still
     the bare AnalysisPipeline, reachable and unwrapped.
  6. Backward compatibility: constructing a StockAgent without the new
     argument at all (positional/keyword call sites exactly as every
     pre-existing test in this suite already does) still works, and
     `agent.runtime_analysis_pipeline` is None.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Agents.executor import Executor, ToolExecutionError
from Agents.memory import ConversationMemory
from Agents.planner import Planner
from Agents.state import AgentState
from Agents.stock_agent import StockAgent
from Agents.tool_registry import ToolRegistry
from Core.analysis_pipeline import AnalysisPipeline
from Core.composition_root import ApplicationGraph, build_application
from Core.tool_context_builder import ToolContextBuilder
from Orchestration.runtime_analysis_pipeline import RuntimeAnalysisPipeline
from Providers import BaseProvider, Message, MessageRole, ProviderManager, ProviderResponse
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
# Fixtures -- lightweight fake services (no yfinance/network), same shape as
# Tests/test_stage_l11_runtime_analysis_pipeline.py's own fixtures.
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


class _RaisingToolContextBuilder(ToolContextBuilder):
    """Stand-in that always raises -- used only to prove the two exception
    taxonomies (raw vs ToolExecutionError) documented in the Diff-Level Plan.
    """

    def build(self, results):  # noqa: ANN001 - matches ToolContextBuilder.build's own signature
        raise RuntimeError("Simulated formatting failure")


class FakeProvider(BaseProvider):
    """Minimal BaseProvider that echoes a fixed reply, no network."""

    def __init__(self, reply_text: str = "Final analysis: BBCA looks bullish.") -> None:
        super().__init__()
        self._reply_text = reply_text
        self.last_messages: Optional[List[Message]] = None

    @property
    def name(self) -> str:
        return "fake_provider_l12"

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def generate(self, messages, **kwargs) -> ProviderResponse:  # noqa: ANN001
        self.last_messages = messages
        return ProviderResponse(text=self._reply_text, finish_reason="stop", model=self.name)

    def stream(self, messages, **kwargs):  # noqa: ANN001
        raise NotImplementedError

    def count_tokens(self, messages) -> int:  # noqa: ANN001
        return sum(len(m.content.split()) for m in messages)

    def health_check(self) -> bool:
        return True


def _fresh_analysis_pipeline() -> AnalysisPipeline:
    services = {name: _FakeService(name) for name in _SERVICE_NAMES}
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


def build_stock_agent(
    *,
    provider: BaseProvider,
    provider_name: str,
    use_runtime: bool,
    tool_context_builder: Optional[ToolContextBuilder] = None,
) -> StockAgent:
    """Construct a fully-wired StockAgent, fresh isolated singletons.

    ``use_runtime=True`` supplies a real, freshly-built
    ``RuntimeAnalysisPipeline`` sharing this call's own ``executor`` and
    ``tool_registry`` (matching the composition_root wiring contract in
    ``Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline``'s
    own docstring: it must share the same registry the executor was
    built with). ``use_runtime=False`` leaves the new argument at its
    default (``None``), exercising the pre-existing fallback path.
    """
    ToolRegistry.reset()
    tool_registry = ToolRegistry()
    provider_manager = ProviderManager()
    if not provider_manager.exists(provider_name):
        provider_manager.register(provider_name, provider)

    planner = Planner(provider_manager=provider_manager, tool_registry=tool_registry)
    memory = ConversationMemory()
    executor = Executor(tool_registry=tool_registry)
    analysis_pipeline = _fresh_analysis_pipeline()
    resolved_tool_context_builder = tool_context_builder or ToolContextBuilder()

    runtime_analysis_pipeline = None
    if use_runtime:
        runtime_analysis_pipeline = RuntimeAnalysisPipeline(
            executor=executor,
            analysis_pipeline=analysis_pipeline,
            tool_context_builder=resolved_tool_context_builder,
            tool_registry=tool_registry,
        )

    return StockAgent(
        planner=planner,
        memory=memory,
        executor=executor,
        analysis_pipeline=analysis_pipeline,
        tool_context_builder=resolved_tool_context_builder,
        default_provider_name=provider_name,
        runtime_analysis_pipeline=runtime_analysis_pipeline,
    )


# ---------------------------------------------------------------------------
# 1. Fallback path (runtime_analysis_pipeline=None) unchanged end-to-end.
# ---------------------------------------------------------------------------
def scenario_fallback_path_unchanged() -> None:
    provider = FakeProvider(reply_text="BBCA analysis via fallback path.")
    agent = build_stock_agent(provider=provider, provider_name="fake_provider_l12_1", use_runtime=False)

    reply = agent.chat("Analisa BBCA")

    check(agent.runtime_analysis_pipeline is None, "fallback agent has runtime_analysis_pipeline=None")
    check(reply == "BBCA analysis via fallback path.", "fallback path returns the provider's exact reply text")
    check(agent.state is AgentState.IDLE, "fallback agent returns to IDLE after success")
    tool_message = provider.last_messages[-1]
    check(tool_message.role == MessageRole.TOOL, "fallback path still sends a TOOL message to the provider")
    check("[Stock]" in tool_message.content, "fallback tool message includes stock section")
    check("[Scoring]" in tool_message.content, "fallback tool message includes scoring section")


# ---------------------------------------------------------------------------
# 2. Runtime path produces identical output to the fallback path.
# ---------------------------------------------------------------------------
def scenario_runtime_path_matches_fallback_output() -> None:
    fallback_provider = FakeProvider(reply_text="irrelevant -- only tool message content compared")
    fallback_agent = build_stock_agent(
        provider=fallback_provider, provider_name="fake_provider_l12_2a", use_runtime=False
    )
    fallback_agent.chat("Analisa BBCA")
    fallback_tool_message = fallback_provider.last_messages[-1].content

    runtime_provider = FakeProvider(reply_text="irrelevant -- only tool message content compared")
    runtime_agent = build_stock_agent(
        provider=runtime_provider, provider_name="fake_provider_l12_2b", use_runtime=True
    )
    runtime_agent.chat("Analisa BBCA")
    runtime_tool_message = runtime_provider.last_messages[-1].content

    check(
        runtime_agent.runtime_analysis_pipeline is not None,
        "runtime-path agent actually has a runtime_analysis_pipeline configured",
    )
    check(
        runtime_tool_message == fallback_tool_message,
        "Runtime-routed StockAgent produces a byte-for-byte identical tool message to the fallback path",
    )
    check(runtime_agent.state is AgentState.IDLE, "runtime-path agent returns to IDLE after success")


# ---------------------------------------------------------------------------
# 3. Registry hygiene holds through the full agent, across repeated calls.
# ---------------------------------------------------------------------------
def scenario_registry_hygiene_through_agent() -> None:
    provider = FakeProvider()
    agent = build_stock_agent(provider=provider, provider_name="fake_provider_l12_3", use_runtime=True)
    registry: ToolRegistry = agent._executor._tool_registry  # noqa: SLF001 -- deliberate white-box check

    before = len(registry.list())
    agent.chat("Analisa BBCA")
    after_one_call = len(registry.list())
    agent.reset()
    agent.chat("Analisa TLKM")
    after_two_calls = len(registry.list())

    check(after_one_call == before, "no leftover private Tool in registry after one StockAgent.chat() call")
    check(after_two_calls == before, "no leftover private Tool in registry after a second StockAgent.chat() call")


# ---------------------------------------------------------------------------
# 4. Exception taxonomy genuinely differs between the two paths (documented,
#    accepted difference from the Diff-Level Plan -- not silently converged).
# ---------------------------------------------------------------------------
def scenario_exception_taxonomy_differs_on_failure() -> None:
    raising_builder = _RaisingToolContextBuilder()

    fallback_provider = FakeProvider()
    fallback_agent = build_stock_agent(
        provider=fallback_provider,
        provider_name="fake_provider_l12_4a",
        use_runtime=False,
        tool_context_builder=raising_builder,
    )
    fallback_raised_type = None
    try:
        fallback_agent.chat("Analisa BBCA")
    except Exception as exc:  # noqa: BLE001
        fallback_raised_type = type(exc)

    runtime_provider = FakeProvider()
    runtime_agent = build_stock_agent(
        provider=runtime_provider,
        provider_name="fake_provider_l12_4b",
        use_runtime=True,
        tool_context_builder=raising_builder,
    )
    runtime_raised_type = None
    try:
        runtime_agent.chat("Analisa BBCA")
    except Exception as exc:  # noqa: BLE001
        runtime_raised_type = type(exc)

    check(fallback_raised_type is RuntimeError, "fallback path lets the original RuntimeError through unchanged")
    check(
        runtime_raised_type is ToolExecutionError,
        "Runtime path wraps the same failure as ToolExecutionError (Executor's existing, unchanged contract)",
    )
    check(
        fallback_agent.state is AgentState.ERROR and runtime_agent.state is AgentState.ERROR,
        "both paths still transition the agent to ERROR state on failure (state-machine contract unchanged)",
    )


# ---------------------------------------------------------------------------
# 5. Composition-root wiring: StockAgent actually receives the shared
#    runtime_analysis_pipeline instance, and the fallback dependency is
#    still reachable, unwrapped.
# ---------------------------------------------------------------------------
def scenario_composition_root_activates_runtime_path() -> None:
    ToolRegistry.reset()
    graph: ApplicationGraph = build_application(
        provider_name="fake-provider-l12-test",
        provider_kind="gemini",
        agent_name="stock_agent_l12_test",
    )

    check(
        graph.agent.runtime_analysis_pipeline is graph.runtime_analysis_pipeline,
        "graph.agent.runtime_analysis_pipeline is the SAME instance as graph.runtime_analysis_pipeline "
        "(one shared object, not a second one built separately)",
    )
    check(
        graph.agent.runtime_analysis_pipeline is not None,
        "production StockAgent now has a non-None runtime_analysis_pipeline (Runtime path is active)",
    )
    check(
        type(graph.agent.analysis_pipeline) is AnalysisPipeline,
        "graph.agent.analysis_pipeline (the fallback dependency) is still the bare AnalysisPipeline, unwrapped",
    )


# ---------------------------------------------------------------------------
# 6. Backward compatibility: constructing StockAgent without the new
#    argument at all (exactly like every pre-existing call site) still works.
# ---------------------------------------------------------------------------
def scenario_constructor_omitting_new_argument_still_works() -> None:
    ToolRegistry.reset()
    tool_registry = ToolRegistry()
    provider_manager = ProviderManager()
    provider = FakeProvider()
    provider_manager.register("fake_provider_l12_6", provider)
    planner = Planner(provider_manager=provider_manager, tool_registry=tool_registry)

    agent = StockAgent(
        planner=planner,
        memory=ConversationMemory(),
        executor=Executor(tool_registry=tool_registry),
        analysis_pipeline=_fresh_analysis_pipeline(),
        tool_context_builder=ToolContextBuilder(),
        default_provider_name="fake_provider_l12_6",
    )

    check(
        agent.runtime_analysis_pipeline is None,
        "StockAgent constructed without runtime_analysis_pipeline defaults it to None",
    )
    reply = agent.chat("Analisa BBCA")
    check(isinstance(reply, str) and len(reply) > 0, "agent still works end-to-end without the new argument")


def main() -> int:
    scenarios = [
        scenario_fallback_path_unchanged,
        scenario_runtime_path_matches_fallback_output,
        scenario_registry_hygiene_through_agent,
        scenario_exception_taxonomy_differs_on_failure,
        scenario_composition_root_activates_runtime_path,
        scenario_constructor_omitting_new_argument_still_works,
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
    print(f"STAGE L12 PRODUCTION RUNTIME ACTIVATION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())