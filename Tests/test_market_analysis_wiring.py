"""Regression tests for Stage 2: MarketAnalysisAgent Template Method wiring.

These tests exist because ``test_idx_foundation_parity.py`` only verifies
*construction-time wiring* (that dependencies are stored on the right
attributes) -- it never calls ``chat()``/``run()``, so it could not have
caught the Stage 2 bug where ``IDXStockAgent.chat(...)`` silently skipped
``InstrumentExtractor``, ``ServicePipeline``, and ``ToolContextBuilder``
entirely and fell through to ``BaseAgent``'s generic tool-triggered engine.

This file closes that gap: every test here actually calls ``chat()`` (or
``run()``) and asserts, via spies, that the four collaborators are invoked
-- and invoked in the correct order:

    InstrumentExtractor.extract()
        -> ServicePipeline.run()
        -> ToolContextBuilder.build()
        -> Provider.generate()

Written in the same dependency-free, hand-rolled style as
``test_stock_agent_smoke.py`` / ``integration_test.py`` / ``E2e_test.py``
(no pytest, no unittest.TestCase) so it can be run the same way as every
other test file in this repository.
"""

from __future__ import annotations

import sys
import traceback
from typing import Any, Dict, List, Optional
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Agents.base_agent import AgentStateError
from Agents.executor import Executor
from Agents.idx_stock_agent import IDXStockAgent
from Agents.market_analysis_agent import MarketAnalysisAgent
from Agents.memory import ConversationMemory
from Agents.planner import Planner
from Agents.state import AgentState
from Agents.tool_registry import ToolRegistry
from Providers.base_provider import BaseProvider
from Providers.message import Message, MessageRole
from Providers.provider_manager import ProviderManager
from Providers.response import ProviderResponse
from Services.metadata_keys import MetadataKeys
from Services.service_context import ServiceContext


# ---------------------------------------------------------------------------
# Spies -- each records its own call plus a shared, ordered call log so call
# ORDER (not just call presence) can be asserted.
# ---------------------------------------------------------------------------


class CallLog:
    def __init__(self) -> None:
        self.events: List[str] = []

    def record(self, event: str) -> None:
        self.events.append(event)


class SpyInstrumentExtractor:
    def __init__(self, log: CallLog, ticker: str = "BBCA.JK") -> None:
        self._log = log
        self._ticker = ticker
        self.calls: List[str] = []

    def extract(self, text: str) -> str:
        self._log.record("extract")
        self.calls.append(text)
        return self._ticker


class SpyServicePipeline:
    def __init__(self, log: CallLog, result: Optional[Dict[str, Any]] = None) -> None:
        self._log = log
        self._result = result if result is not None else {"stock_service": "sentinel-result"}
        self.run_calls: List[ServiceContext] = []

    def run(self, context: ServiceContext) -> Dict[str, Any]:
        self._log.record("pipeline_run")
        self.run_calls.append(context)
        return self._result

    def health_check(self) -> bool:
        return True


class SpyToolContextBuilder:
    def __init__(self, log: CallLog, rendered_text: str = "[Stock]\nsentinel-result") -> None:
        self._log = log
        self._rendered_text = rendered_text
        self.build_calls: List[Dict[str, Any]] = []

    def build(self, results: Dict[str, Any]) -> str:
        self._log.record("render")
        self.build_calls.append(results)
        return self._rendered_text


class SpyProvider(BaseProvider):
    def __init__(self, log: CallLog, reply_text: str = "final reply text") -> None:
        super().__init__()
        self._log = log
        self._reply_text = reply_text
        self.generate_calls: List[List[Message]] = []

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def generate(self, messages: List[Message], **kwargs: Any) -> ProviderResponse:
        self._log.record("provider_generate")
        self.generate_calls.append(list(messages))
        return ProviderResponse(text=self._reply_text)

    def stream(self, messages: List[Message], **kwargs: Any):
        raise NotImplementedError

    def count_tokens(self, messages: List[Message]) -> int:
        return 0

    def health_check(self) -> bool:
        return True


class RaisingInstrumentExtractor:
    def extract(self, text: str) -> str:
        raise ValueError(f"no instrument found in: {text!r}")


class RaisingServicePipeline:
    def run(self, context: ServiceContext) -> Dict[str, Any]:
        raise RuntimeError("pipeline exploded")

    def health_check(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

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
    log: CallLog,
    instrument_extractor: Any = None,
    service_pipeline: Any = None,
    tool_context_builder: Any = None,
    provider: Any = None,
    provider_name: str = "fake",
) -> Any:
    """Build a fresh IDXStockAgent wired to fresh spies, with fresh
    process-wide registries (ToolRegistry/ProviderManager are singletons
    elsewhere in this codebase; reset them so tests don't leak state)."""
    ToolRegistry.reset()
    ProviderManager.reset()

    tool_registry = ToolRegistry()
    provider_manager = ProviderManager()

    spy_provider = provider or SpyProvider(log)
    provider_manager.register(provider_name, spy_provider)

    planner = Planner(
        provider_manager=provider_manager,
        tool_registry=tool_registry,
        default_provider_name=provider_name,
    )
    memory = ConversationMemory()
    executor = Executor(tool_registry=tool_registry)

    spy_extractor = instrument_extractor or SpyInstrumentExtractor(log)
    spy_pipeline = service_pipeline or SpyServicePipeline(log)
    spy_renderer = tool_context_builder or SpyToolContextBuilder(log)

    agent = IDXStockAgent(
        planner,
        memory,
        executor,
        provider_manager=provider_manager,
        tool_context_builder=spy_renderer,
        instrument_extractor=spy_extractor,
        service_pipeline=spy_pipeline,
        default_provider_name=provider_name,
    )
    return agent, spy_provider, spy_extractor, spy_pipeline, spy_renderer


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def scenario_pipeline_actually_runs_in_correct_order() -> None:
    print("\n[Scenario 1] IDXStockAgent.chat(...) drives extractor -> pipeline -> renderer -> provider, in order")
    log = CallLog()
    agent, spy_provider, spy_extractor, spy_pipeline, spy_renderer = build_agent(log)

    reply = agent.chat("Analisa BBCA sekarang")

    check(reply == "final reply text", "chat() returns the provider's reply text")
    check(len(spy_extractor.calls) == 1, "InstrumentExtractor.extract() was called exactly once")
    check(len(spy_pipeline.run_calls) == 1, "ServicePipeline.run() was called exactly once")
    check(len(spy_renderer.build_calls) == 1, "ToolContextBuilder.build() was called exactly once")
    check(len(spy_provider.generate_calls) == 1, "Provider.generate() was called exactly once")

    check(
        log.events == ["extract", "pipeline_run", "render", "provider_generate"],
        f"call order is extract -> pipeline_run -> render -> provider_generate (got {log.events})",
    )

    check(
        spy_extractor.calls[0] == "Analisa BBCA sekarang",
        "InstrumentExtractor received the raw user message text",
    )
    check(
        spy_pipeline.run_calls[0].metadata.get(MetadataKeys.TICKER) == "BBCA.JK",
        "ServiceContext handed to the pipeline is seeded with the extracted ticker",
    )
    check(
        spy_renderer.build_calls[0] == spy_pipeline._result,
        "ToolContextBuilder received exactly the pipeline's result dict, unmodified",
    )

    last_message = spy_provider.generate_calls[0][-1]
    check(
        last_message.role == MessageRole.TOOL and last_message.content == "[Stock]\nsentinel-result",
        "the last message sent to the provider is a TOOL message containing the rendered pipeline output",
    )


def scenario_run_accepts_a_prebuilt_message() -> None:
    print("\n[Scenario 2] run() works with a pre-built Message, not just chat()")
    log = CallLog()
    agent, spy_provider, spy_extractor, spy_pipeline, spy_renderer = build_agent(log)

    reply = agent.run(Message(role=MessageRole.USER, content="Analisa ANTM sekarang"), "fake")

    check(reply == "final reply text", "run() returns the provider's reply text")
    check(
        log.events == ["extract", "pipeline_run", "render", "provider_generate"],
        "run() drives the same extract -> pipeline_run -> render -> provider_generate order as chat()",
    )


def scenario_extractor_failure_propagates_and_sets_error_state() -> None:
    print("\n[Scenario 3] InstrumentExtractor failure propagates; pipeline/renderer/provider never run")
    log = CallLog()
    agent, spy_provider, _extractor, spy_pipeline, spy_renderer = build_agent(
        log, instrument_extractor=RaisingInstrumentExtractor()
    )

    raised = None
    try:
        agent.chat("no ticker in here")
    except ValueError as exc:
        raised = exc

    check(raised is not None, "ValueError from the extractor propagates out of chat()")
    check(len(spy_pipeline.run_calls) == 0, "ServicePipeline.run() was never called after extractor failure")
    check(len(spy_renderer.build_calls) == 0, "ToolContextBuilder.build() was never called after extractor failure")
    check(len(spy_provider.generate_calls) == 0, "Provider.generate() was never called after extractor failure")
    check(agent.state is AgentState.ERROR, "agent state is ERROR after extractor failure")


def scenario_pipeline_failure_propagates_and_skips_renderer_and_provider() -> None:
    print("\n[Scenario 4] ServicePipeline failure propagates; renderer/provider never run")
    log = CallLog()
    agent, spy_provider, spy_extractor, _pipeline, spy_renderer = build_agent(
        log, service_pipeline=RaisingServicePipeline()
    )

    raised = None
    try:
        agent.chat("Analisa BBCA sekarang")
    except RuntimeError as exc:
        raised = exc

    check(raised is not None, "RuntimeError from the pipeline propagates out of chat()")
    check(len(spy_extractor.calls) == 1, "InstrumentExtractor still ran before the pipeline failed")
    check(len(spy_renderer.build_calls) == 0, "ToolContextBuilder.build() was never called after pipeline failure")
    check(len(spy_provider.generate_calls) == 0, "Provider.generate() was never called after pipeline failure")
    check(agent.state is AgentState.ERROR, "agent state is ERROR after pipeline failure")


def scenario_error_state_blocks_further_calls_until_reset() -> None:
    print("\n[Scenario 5] AgentStateError is raised while stuck in ERROR, cleared by reset()")
    log = CallLog()
    agent, *_ = build_agent(log, service_pipeline=RaisingServicePipeline())

    try:
        agent.chat("Analisa BBCA sekarang")
    except RuntimeError:
        pass

    raised = None
    try:
        agent.chat("Analisa BBCA sekarang lagi")
    except AgentStateError as exc:
        raised = exc

    check(raised is not None, "a second call while in ERROR state raises AgentStateError")

    agent.reset()
    check(agent.state is AgentState.IDLE, "reset() clears ERROR state back to IDLE")


def scenario_default_build_context_uses_market_analysis_agent_hook() -> None:
    print("\n[Scenario 6] Default build_context()/execute_pipeline()/render_context() hooks are the ones actually used")
    log = CallLog()
    agent, *_ = build_agent(log)

    # These are inherited, unoverridden, from MarketAnalysisAgent -- confirm
    # IDXStockAgent did not silently reintroduce its own overrides.
    check(
        type(agent).build_context is MarketAnalysisAgent.build_context,
        "IDXStockAgent does not override build_context() (default hook is used)",
    )
    check(
        type(agent).execute_pipeline is MarketAnalysisAgent.execute_pipeline,
        "IDXStockAgent does not override execute_pipeline() (default hook is used)",
    )
    check(
        type(agent).render_context is MarketAnalysisAgent.render_context,
        "IDXStockAgent does not override render_context() (default hook is used)",
    )
    check(
        type(agent).create_pipeline is MarketAnalysisAgent.create_pipeline,
        "IDXStockAgent does not override create_pipeline() (default hook is used)",
    )
    check(
        type(agent).run is MarketAnalysisAgent.run,
        "IDXStockAgent does not override run() -- Template Method stays final",
    )


def scenario_backward_compatible_construction_still_works() -> None:
    print("\n[Scenario 7] Existing IDXStockAgent constructor signature is unchanged")
    log = CallLog()
    # Mirrors test_idx_foundation_parity.py's construction call exactly,
    # positionally, to prove the public constructor contract did not change.
    ToolRegistry.reset()
    ProviderManager.reset()
    tool_registry = ToolRegistry()
    provider_manager = ProviderManager()
    provider_manager.register("gemini", SpyProvider(log))
    planner = Planner(provider_manager=provider_manager, tool_registry=tool_registry)
    memory = ConversationMemory()
    executor = Executor(tool_registry=tool_registry)

    agent = IDXStockAgent(
        planner,
        memory,
        executor,
        provider_manager=provider_manager,
        tool_context_builder=SpyToolContextBuilder(log),
        instrument_extractor=SpyInstrumentExtractor(log),
        service_pipeline=SpyServicePipeline(log),
        default_provider_name="gemini",
    )

    check(agent.name == "idx_stock_agent", "IDXStockAgent.name is unchanged")
    check(
        agent._service_pipeline is not None
        and agent._instrument_extractor is not None
        and agent._tool_context_builder is not None,
        "all four constructor-injected collaborators are still stored, unchanged",
    )


def main() -> int:
    scenarios = [
        scenario_pipeline_actually_runs_in_correct_order,
        scenario_run_accepts_a_prebuilt_message,
        scenario_extractor_failure_propagates_and_sets_error_state,
        scenario_pipeline_failure_propagates_and_skips_renderer_and_provider,
        scenario_error_state_blocks_further_calls_until_reset,
        scenario_default_build_context_uses_market_analysis_agent_hook,
        scenario_backward_compatible_construction_still_works,
    ]

    global _FAIL
    for scenario in scenarios:
        try:
            scenario()
        except Exception:  # noqa: BLE001
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"MARKET ANALYSIS PIPELINE WIRING RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())