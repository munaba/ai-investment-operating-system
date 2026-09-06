"""
Stage L7 proof suite -- Requirement-based Agent Routing.

Scope (per this session's LOCKED design decisions):
  - Agents/base_agent.py (additive only):
      * chat()/run() gain one new optional parameter, `requirement:
        Optional[ProviderRequirement] = None`, pure pass-through into
        Planner.plan(message, provider_name=provider_name,
        requirement=requirement). No new logic.
  - Agents/market_analysis_agent.py:
      * run() gains `requirement`. Provider resolution is now performed
        exactly once, via the new private helper
        `_resolve_provider_for_request(provider_name, requirement)`,
        BEFORE build_context() (so ServiceContext.provider_name can be
        seeded with the resolved name regardless of which path resolved
        it). When `requirement` is None, the actual BaseProvider
        instance continues to be resolved at the exact same point in
        run() as before this stage (Planner.select_provider(), guarded
        by `if provider is None`) -- byte-for-byte unchanged behavior
        for every pre-existing caller.
  - Agents/stock_agent.py:
      * Same pattern as market_analysis_agent.py (StockAgent overrides
        run() entirely and uses the inherited helper).
      * `_call_provider()`'s signature changed: it now always receives
        an already-resolved `BaseProvider` instance, never a name. It no
        longer calls `Planner.select_provider()` itself -- resolution is
        entirely `run()`'s responsibility now, so there is exactly one
        provider lookup per turn, never two.
  - Tests/test_stage_l4_planner_integration.py:
      * The Stage L4 locked-file static guard (scenario 9) is narrowed:
        `Agents/base_agent.py`, `Agents/stock_agent.py`, and
        `Agents/market_analysis_agent.py` are removed from that tuple,
        with an explanatory comment (same precedent already established
        for `Core/composition_root.py` at Stage L5). This suite's own
        scenario 8 (below) now carries that responsibility for the three
        files removed there.

Untouched by this stage: Agents/planner.py, Providers/provider_selector.py,
Providers/provider_manager.py, Core/composition_root.py, Core/runtime.py,
Agents/executor.py, Core/approval.py, Providers/gemini.py,
Providers/ollama.py, Core/startup_validation.py, Agents/idx_stock_agent.py,
Agents/agent_tool_adapter.py, Services/service_context.py.

Cakupan skenario (1-11, disepakati dengan user sebelum coding):
  1. Backward compatibility -- provider_name-only calls on BaseAgent,
     MarketAnalysisAgent, and StockAgent behave identically to before
     this stage.
  2. Requirement path calls Planner.select_by_requirement(), never
     select_provider(), when `requirement` is given.
  3. Single lookup -- provider is resolved exactly once per turn on
     both paths (spied via a call-counting Planner wrapper).
  4. Reuse instance -- the BaseProvider instance passed to
     provider.generate() is `is` (identity) the same object
     select_by_requirement() returned.
  5. ServiceContext.provider_name is seeded with the resolved
     requirement-path provider's .name.
  6. requirement=None -- the entire flow (state transitions, resolved
     name, provider used) stays identical to the pre-L7 baseline.
  7. IDXStockAgent gets the new behavior automatically, with zero
     modification to Agents/idx_stock_agent.py.
  8. Locked-file guard -- Planner, ProviderSelector, ProviderManager,
     CompositionRoot, Runtime, Executor, Approval, GeminiProvider,
     OllamaProvider, IDXStockAgent, AgentToolAdapter, ServiceContext
     source is unchanged by this stage.
  9. AgentToolAdapter.execute()'s signature still only accepts
     `provider_name` (no `requirement` slot) -- documented limitation,
     not a regression.
  10. Mutual exclusivity -- provider_name + requirement given together:
      requirement wins, provider_name is ignored entirely (no error,
      no merge, no double lookup), matching Planner's own L4 contract.
  11. Pipeline independence -- the service pipeline is invoked with only
      the resolved provider *name* (str) inside ServiceContext; no
      BaseProvider instance is ever passed into build_context()/
      execute_pipeline(), and the provider is only touched at the final
      _call_provider() step.

All checks are hermetic: no network call, no API key, no external
package required.
"""

from __future__ import annotations

import inspect
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Agents.base_agent import AgentStateError, BaseAgent
from Agents.executor import Executor
from Agents.idx_stock_agent import IDXStockAgent
from Agents.market_analysis_agent import MarketAnalysisAgent
from Agents.memory import ConversationMemory
from Agents.planner import Planner
from Agents.state import AgentState
from Agents.stock_agent import StockAgent
from Agents.tool_registry import ToolRegistry
from Providers import (
    BaseProvider,
    Message,
    MessageRole,
    ProviderCapabilities,
    ProviderManager,
    ProviderRequirement,
    ProviderResponse,
    ProviderSelector,
)
from Services.service_context import ServiceContext

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
# Test doubles
# ---------------------------------------------------------------------------
class CallLog:
    def __init__(self) -> None:
        self.events: List[str] = []

    def record(self, event: str) -> None:
        self.events.append(event)


class _FakeProvider(BaseProvider):
    """Minimal concrete BaseProvider with a configurable capabilities value."""

    def __init__(
        self,
        label: str,
        capabilities: Optional[ProviderCapabilities] = None,
        log: Optional[CallLog] = None,
    ) -> None:
        super().__init__()
        self._label = label
        self._capabilities = capabilities or ProviderCapabilities()
        self._log = log
        self.generate_calls: List[List[Message]] = []

    @property
    def name(self) -> str:
        return self._label

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def generate(self, messages: List[Message], **kwargs: Any) -> ProviderResponse:
        if self._log is not None:
            self._log.record(f"provider_generate:{self._label}")
        self.generate_calls.append(list(messages))
        return ProviderResponse(text=f"reply-from-{self._label}")

    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        raise NotImplementedError

    def count_tokens(self, messages: List[Message]) -> int:
        return 0

    def health_check(self) -> bool:
        return True


class SpyPlanner(Planner):
    """Wraps Planner's resolution methods with call counters, without
    changing behavior -- pure delegation to super(), so any assertion
    against this spy proves something about the real Planner contract,
    not a reimplementation of it."""

    def __init__(self, *args: Any, log: Optional[CallLog] = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.select_provider_calls = 0
        self.select_by_requirement_calls = 0
        self._log = log

    def select_provider(self, provider_name: Optional[str] = None) -> BaseProvider:
        self.select_provider_calls += 1
        if self._log is not None:
            self._log.record("select_provider")
        return super().select_provider(provider_name)

    def select_by_requirement(self, requirement: ProviderRequirement) -> BaseProvider:
        self.select_by_requirement_calls += 1
        if self._log is not None:
            self._log.record("select_by_requirement")
        return super().select_by_requirement(requirement)

    def total_lookups(self) -> int:
        return self.select_provider_calls + self.select_by_requirement_calls


class SpyInstrumentExtractor:
    def __init__(self, log: CallLog, ticker: str = "BBCA.JK") -> None:
        self._log = log
        self._ticker = ticker

    def extract(self, text: str) -> str:
        self._log.record("extract")
        return self._ticker


class SpyServicePipeline:
    """Records the *type* of every argument run() receives, to prove
    pipeline independence (scenario 11): it must never see a BaseProvider,
    only a ServiceContext carrying a provider_name string."""

    def __init__(self, log: CallLog, result: Optional[Dict[str, Any]] = None) -> None:
        self._log = log
        self._result = result if result is not None else {"stock_service": "sentinel-result"}
        self.run_calls: List[ServiceContext] = []
        self.saw_base_provider_instance = False

    def run(self, context: ServiceContext) -> Dict[str, Any]:
        self._log.record("pipeline_run")
        self.run_calls.append(context)
        if isinstance(context.provider_name, BaseProvider):
            self.saw_base_provider_instance = True
        for value in vars(context).values():
            if isinstance(value, BaseProvider):
                self.saw_base_provider_instance = True
        return self._result

    def health_check(self) -> bool:
        return True


class SpyToolContextBuilder:
    def __init__(self, log: CallLog, rendered_text: str = "[Stock]\nsentinel-result") -> None:
        self._log = log
        self._rendered_text = rendered_text

    def build(self, results: Dict[str, Any]) -> str:
        self._log.record("render")
        return self._rendered_text


class _ConcreteMarketAnalysisAgent(MarketAnalysisAgent):
    """Minimal concrete subclass -- MarketAnalysisAgent is ABC, needs a
    `name` property to instantiate. No behavior override."""

    @property
    def name(self) -> str:
        return "test_market_analysis_agent"


class _ConcreteBaseAgent(BaseAgent):
    """Minimal concrete BaseAgent -- only implements the abstract `name`."""

    @property
    def name(self) -> str:
        return "test_base_agent"


def _fresh_env() -> None:
    ToolRegistry.reset()
    ProviderManager.reset()


def _msg(text: str = "hello") -> Message:
    return Message(role=MessageRole.USER, content=text)


LOCAL_CAPS = ProviderCapabilities(is_local=True)


def _build_planner_and_providers(log: CallLog) -> "tuple[SpyPlanner, _FakeProvider, _FakeProvider, ProviderManager]":
    """Register two providers -- one remote/default (gemini-like), one
    local (ollama-like, is_local=True) -- and build a SpyPlanner wired
    with a real ProviderSelector, exactly mirroring the production
    Composition Root's Stage L6 wiring (ProviderSelector injected,
    default_provider_name set explicitly)."""
    manager = ProviderManager()
    provider_manager_name = "l7_gemini_like"
    local_name = "l7_ollama_like"

    remote_provider = _FakeProvider(provider_manager_name, ProviderCapabilities(), log=log)
    local_provider = _FakeProvider(local_name, LOCAL_CAPS, log=log)
    manager.register(provider_manager_name, remote_provider)
    manager.register(local_name, local_provider)

    tool_registry = ToolRegistry()
    selector = ProviderSelector(manager)
    planner = SpyPlanner(
        provider_manager=manager,
        tool_registry=tool_registry,
        default_provider_name=provider_manager_name,
        provider_selector=selector,
        log=log,
    )
    return planner, remote_provider, local_provider, manager


def _build_market_analysis_agent(planner: Planner, log: CallLog):
    memory = ConversationMemory()
    executor = Executor(tool_registry=planner._tool_registry)  # type: ignore[attr-defined]
    extractor = SpyInstrumentExtractor(log)
    pipeline = SpyServicePipeline(log)
    builder = SpyToolContextBuilder(log)

    agent = _ConcreteMarketAnalysisAgent(
        planner=planner,
        memory=memory,
        executor=executor,
        provider_manager=None,
        tool_context_builder=builder,
        instrument_extractor=extractor,
        service_pipeline=pipeline,
        default_provider_name=planner._default_provider_name,  # type: ignore[attr-defined]
    )
    return agent, pipeline


def _build_stock_agent(planner: Planner, log: CallLog):
    from Core.analysis_pipeline import AnalysisPipeline
    from Core.tool_context_builder import ToolContextBuilder

    memory = ConversationMemory()
    executor = Executor(tool_registry=planner._tool_registry)  # type: ignore[attr-defined]
    extractor = SpyInstrumentExtractor(log)
    pipeline = SpyServicePipeline(log)
    builder = SpyToolContextBuilder(log)

    agent = StockAgent(
        planner=planner,
        memory=memory,
        executor=executor,
        analysis_pipeline=pipeline,  # duck-typed: only .run(context) is used by run()
        tool_context_builder=builder,
        default_provider_name=planner._default_provider_name,  # type: ignore[attr-defined]
        instrument_extractor=extractor,
    )
    return agent, pipeline


# ---------------------------------------------------------------------------
# 1. Backward compatibility
# ---------------------------------------------------------------------------
def scenario_backward_compatibility() -> None:
    print("\n[1] Backward compatibility -- provider_name-only path unchanged")

    _fresh_env()
    log = CallLog()
    planner, remote, local, manager = _build_planner_and_providers(log)

    ma_agent, ma_pipeline = _build_market_analysis_agent(planner, log)
    reply = ma_agent.run(_msg("analyze BBCA"))
    check(reply == "reply-from-l7_gemini_like", "MarketAnalysisAgent.run() with no requirement resolves the default provider, unchanged")
    check(ma_pipeline.run_calls[0].provider_name == "l7_gemini_like", "ServiceContext.provider_name still seeded with the name-path resolution")

    _fresh_env()
    log2 = CallLog()
    planner2, remote2, local2, manager2 = _build_planner_and_providers(log2)
    sa_agent, sa_pipeline = _build_stock_agent(planner2, log2)
    reply2 = sa_agent.run(_msg("BBCA please"))
    check(reply2 == "reply-from-l7_gemini_like", "StockAgent.run() with no requirement resolves the default provider, unchanged")

    _fresh_env()
    log3 = CallLog()
    planner3, remote3, local3, manager3 = _build_planner_and_providers(log3)
    tool_registry = planner3._tool_registry  # type: ignore[attr-defined]
    base = _ConcreteBaseAgent(
        planner=planner3,
        memory=ConversationMemory(),
        executor=Executor(tool_registry=tool_registry),
    )
    reply3 = base.chat("just chatting")
    check(reply3 == "reply-from-l7_gemini_like", "BaseAgent.chat() with no requirement resolves the default provider, unchanged")


# ---------------------------------------------------------------------------
# 2. Requirement path uses select_by_requirement(), never select_provider()
# ---------------------------------------------------------------------------
def scenario_requirement_path_uses_correct_method() -> None:
    print("\n[2] Requirement path calls select_by_requirement(), not select_provider()")

    _fresh_env()
    log = CallLog()
    planner, remote, local, manager = _build_planner_and_providers(log)
    ma_agent, ma_pipeline = _build_market_analysis_agent(planner, log)

    requirement = ProviderRequirement(local_only=True)
    reply = ma_agent.run(_msg("analyze BBCA"), requirement=requirement)

    check(reply == "reply-from-l7_ollama_like", "requirement=local_only routes to the local provider")
    check(planner.select_by_requirement_calls == 1, "select_by_requirement() was called exactly once")
    check(planner.select_provider_calls == 0, "select_provider() was NOT called on the requirement path")


# ---------------------------------------------------------------------------
# 3. Single lookup (both paths)
# ---------------------------------------------------------------------------
def scenario_single_lookup() -> None:
    print("\n[3] Single lookup -- provider resolved exactly once per turn")

    _fresh_env()
    log = CallLog()
    planner, remote, local, manager = _build_planner_and_providers(log)
    ma_agent, _ = _build_market_analysis_agent(planner, log)
    ma_agent.run(_msg("hi"), requirement=ProviderRequirement(local_only=True))
    check(planner.total_lookups() == 1, "MarketAnalysisAgent requirement path: exactly one total Planner lookup")

    _fresh_env()
    log2 = CallLog()
    planner2, remote2, local2, manager2 = _build_planner_and_providers(log2)
    ma_agent2, _ = _build_market_analysis_agent(planner2, log2)
    ma_agent2.run(_msg("hi"))
    check(planner2.total_lookups() == 1, "MarketAnalysisAgent name path: exactly one total Planner lookup")

    _fresh_env()
    log3 = CallLog()
    planner3, remote3, local3, manager3 = _build_planner_and_providers(log3)
    sa_agent, _ = _build_stock_agent(planner3, log3)
    sa_agent.run(_msg("BBCA"), requirement=ProviderRequirement(local_only=True))
    check(planner3.total_lookups() == 1, "StockAgent requirement path: exactly one total Planner lookup")

    _fresh_env()
    log4 = CallLog()
    planner4, remote4, local4, manager4 = _build_planner_and_providers(log4)
    sa_agent2, _ = _build_stock_agent(planner4, log4)
    sa_agent2.run(_msg("BBCA"))
    check(planner4.total_lookups() == 1, "StockAgent name path: exactly one total Planner lookup")


# ---------------------------------------------------------------------------
# 4. Reuse instance
# ---------------------------------------------------------------------------
def scenario_reuse_instance() -> None:
    print("\n[4] Reuse instance -- generate() called on the exact resolved instance")

    _fresh_env()
    log = CallLog()
    planner, remote, local, manager = _build_planner_and_providers(log)
    ma_agent, _ = _build_market_analysis_agent(planner, log)
    ma_agent.run(_msg("hi"), requirement=ProviderRequirement(local_only=True))
    check(len(local.generate_calls) == 1, "The local provider's generate() was called")
    check(len(remote.generate_calls) == 0, "The remote provider's generate() was NOT called")

    _fresh_env()
    log2 = CallLog()
    planner2, remote2, local2, manager2 = _build_planner_and_providers(log2)
    sa_agent, _ = _build_stock_agent(planner2, log2)
    sa_agent.run(_msg("BBCA"), requirement=ProviderRequirement(local_only=True))
    check(len(local2.generate_calls) == 1, "StockAgent: the local provider's generate() was called")
    check(len(remote2.generate_calls) == 0, "StockAgent: the remote provider's generate() was NOT called")


# ---------------------------------------------------------------------------
# 5. ServiceContext.provider_name reflects the requirement-resolved provider
# ---------------------------------------------------------------------------
def scenario_service_context_provider_name() -> None:
    print("\n[5] ServiceContext.provider_name seeded from requirement-resolved provider.name")

    _fresh_env()
    log = CallLog()
    planner, remote, local, manager = _build_planner_and_providers(log)
    ma_agent, ma_pipeline = _build_market_analysis_agent(planner, log)
    ma_agent.run(_msg("hi"), requirement=ProviderRequirement(local_only=True))
    check(
        ma_pipeline.run_calls[0].provider_name == "l7_ollama_like",
        "ServiceContext.provider_name == the resolved requirement-path provider's .name",
    )
    check(isinstance(ma_pipeline.run_calls[0].provider_name, str), "ServiceContext.provider_name is still a plain str")

    _fresh_env()
    log2 = CallLog()
    planner2, remote2, local2, manager2 = _build_planner_and_providers(log2)
    sa_agent, sa_pipeline = _build_stock_agent(planner2, log2)
    sa_agent.run(_msg("BBCA"), requirement=ProviderRequirement(local_only=True))
    check(
        sa_pipeline.run_calls[0].provider_name == "l7_ollama_like",
        "StockAgent: ServiceContext.provider_name == the resolved requirement-path provider's .name",
    )


# ---------------------------------------------------------------------------
# 6. requirement=None -- flow identical to baseline
# ---------------------------------------------------------------------------
def scenario_requirement_none_identical_flow() -> None:
    print("\n[6] requirement=None -- state transitions and resolution point unchanged")

    _fresh_env()
    log = CallLog()
    planner, remote, local, manager = _build_planner_and_providers(log)
    ma_agent, ma_pipeline = _build_market_analysis_agent(planner, log)
    ma_agent.run(_msg("hi"))

    # Expected order for the name path: extract is not called by
    # MarketAnalysisAgent's own hooks by default (SpyInstrumentExtractor
    # is invoked inside build_context) -> pipeline_run -> render ->
    # select_provider -> provider_generate.
    check(
        log.events == ["extract", "pipeline_run", "render", "select_provider", "provider_generate:l7_gemini_like"],
        f"MarketAnalysisAgent requirement=None call order unchanged, got {log.events}",
    )
    check(ma_agent.state == AgentState.IDLE, "Agent returns to IDLE after a successful turn")

    _fresh_env()
    log2 = CallLog()
    planner2, remote2, local2, manager2 = _build_planner_and_providers(log2)
    sa_agent, sa_pipeline = _build_stock_agent(planner2, log2)
    sa_agent.run(_msg("BBCA"))
    check(
        log2.events == ["extract", "pipeline_run", "render", "select_provider", "provider_generate:l7_gemini_like"],
        f"StockAgent requirement=None: resolution happens at the same relative point as MarketAnalysisAgent, rest of pipeline unchanged; got {log2.events}",
    )


# ---------------------------------------------------------------------------
# 7. IDXStockAgent -- zero modification, automatic new behavior
# ---------------------------------------------------------------------------
def scenario_idx_stock_agent_inherits_automatically() -> None:
    print("\n[7] IDXStockAgent gets requirement routing with zero file changes")

    _fresh_env()
    log = CallLog()
    planner, remote, local, manager = _build_planner_and_providers(log)
    memory = ConversationMemory()
    executor = Executor(tool_registry=planner._tool_registry)  # type: ignore[attr-defined]
    extractor = SpyInstrumentExtractor(log)
    pipeline = SpyServicePipeline(log)
    builder = SpyToolContextBuilder(log)

    idx_agent = IDXStockAgent(
        planner,
        memory,
        executor,
        None,
        builder,
        extractor,
        pipeline,
        planner._default_provider_name,  # type: ignore[attr-defined]
    )

    check("requirement" in inspect.signature(idx_agent.run).parameters, "IDXStockAgent.run() (inherited) exposes requirement param without its own file being touched")

    reply = idx_agent.run(_msg("hi"), requirement=ProviderRequirement(local_only=True))
    check(reply == "reply-from-l7_ollama_like", "IDXStockAgent honors requirement-based routing purely via inheritance")
    check(planner.select_by_requirement_calls == 1, "IDXStockAgent: select_by_requirement() called exactly once")


# ---------------------------------------------------------------------------
# 8. Locked-file guard
# ---------------------------------------------------------------------------
def scenario_locked_files_unchanged() -> None:
    print("\n[8] Locked-file guard -- Stage L7 touched only the approved 3 files")

    # Baseline snapshot taken from disk right now; this suite cannot
    # compare to a pre-L7 git diff, so instead it proves the *absence*
    # of any L7-introduced vocabulary (ProviderRequirement/
    # select_by_requirement/_resolve_provider_for_request) in every file
    # this stage was required to leave untouched.
    locked_files = [
        ROOT / "Agents" / "planner.py",
        ROOT / "Providers" / "provider_selector.py",
        ROOT / "Providers" / "provider_manager.py",
        ROOT / "Core" / "composition_root.py",
        ROOT / "Core" / "runtime.py",
        ROOT / "Agents" / "executor.py",
        ROOT / "Core" / "approval.py",
        ROOT / "Providers" / "gemini.py",
        ROOT / "Providers" / "ollama.py",
        ROOT / "Agents" / "idx_stock_agent.py",
        ROOT / "Agents" / "agent_tool_adapter.py",
        ROOT / "Services" / "service_context.py",
    ]
    startup_validation_candidates = list(ROOT.rglob("startup_validation.py"))
    locked_files.extend(startup_validation_candidates)

    # NOTE: `ProviderRequirement` / `select_by_requirement` are Stage
    # L3/L4 vocabulary and legitimately already appear in
    # Agents/planner.py, Providers/provider_selector.py, and (per L5/L6)
    # Core/composition_root.py -- checking for their *absence* there
    # would be a false positive, not a real guard. The one marker that
    # is unique to Stage L7 (introduced by this stage and nowhere
    # before it) is the new helper name itself.
    l7_vocabulary = ("_resolve_provider_for_request",)

    for path in locked_files:
        if not path.exists():
            check(False, f"{path.relative_to(ROOT)} expected to exist but was not found")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found = [term for term in l7_vocabulary if term in text]
        check(not found, f"{path.relative_to(ROOT)} contains no Stage L7 vocabulary (untouched); found={found}")

    # Positive confirmation: the 3 files that SHOULD have changed do
    # contain the new helper / requirement param -- proves the guard
    # above isn't vacuously trivial.
    for path, expect in (
        (ROOT / "Agents" / "base_agent.py", "ProviderRequirement"),
        (ROOT / "Agents" / "market_analysis_agent.py", "_resolve_provider_for_request"),
        (ROOT / "Agents" / "stock_agent.py", "_resolve_provider_for_request"),
    ):
        text = path.read_text(encoding="utf-8", errors="replace")
        check(expect in text, f"{path.relative_to(ROOT)} contains the expected Stage L7 change ('{expect}')")


# ---------------------------------------------------------------------------
# 9. AgentToolAdapter -- documented limitation, not a regression
# ---------------------------------------------------------------------------
def scenario_agent_tool_adapter_out_of_scope() -> None:
    print("\n[9] AgentToolAdapter.execute() has no requirement slot (documented, out of scope)")

    from Agents.agent_tool_adapter import AgentToolAdapter

    sig = inspect.signature(AgentToolAdapter.execute)
    params = list(sig.parameters.keys())
    check(params == ["self", "user_input", "provider_name"], "AgentToolAdapter.execute() signature is unchanged by Stage L7 (no 'requirement' param)")


# ---------------------------------------------------------------------------
# 10. Mutual exclusivity
# ---------------------------------------------------------------------------
def scenario_mutual_exclusivity() -> None:
    print("\n[10] Mutual exclusivity -- requirement wins, provider_name ignored, no error, no merge")

    _fresh_env()
    log = CallLog()
    planner, remote, local, manager = _build_planner_and_providers(log)
    ma_agent, ma_pipeline = _build_market_analysis_agent(planner, log)

    raised = False
    reply = None
    try:
        reply = ma_agent.run(
            _msg("hi"),
            provider_name="l7_gemini_like",
            requirement=ProviderRequirement(local_only=True),
        )
    except Exception:  # noqa: BLE001
        raised = True

    check(not raised, "Supplying both provider_name and requirement does not raise")
    check(reply == "reply-from-l7_ollama_like", "requirement wins over provider_name (local provider used, not the named 'gemini-like' one)")
    check(len(remote.generate_calls) == 0, "The provider_name-named provider was never called")
    check(planner.select_provider_calls == 0, "select_provider() was never called -- provider_name was not consulted at all")
    check(planner.select_by_requirement_calls == 1, "select_by_requirement() called exactly once")
    check(
        ma_pipeline.run_calls[0].provider_name == "l7_ollama_like",
        "ServiceContext.provider_name reflects the requirement winner, not the ignored provider_name argument",
    )


# ---------------------------------------------------------------------------
# 11. Pipeline independence
# ---------------------------------------------------------------------------
def scenario_pipeline_independence() -> None:
    print("\n[11] Pipeline independence -- pipeline never sees a BaseProvider instance")

    _fresh_env()
    log = CallLog()
    planner, remote, local, manager = _build_planner_and_providers(log)
    ma_agent, ma_pipeline = _build_market_analysis_agent(planner, log)
    ma_agent.run(_msg("hi"), requirement=ProviderRequirement(local_only=True))

    check(not ma_pipeline.saw_base_provider_instance, "ServicePipeline.run()'s ServiceContext never carries a BaseProvider instance in any field")
    check(isinstance(ma_pipeline.run_calls[0].provider_name, str), "ServiceContext.provider_name passed to the pipeline is a str, not a BaseProvider")

    # Call-order proof: pipeline_run must complete BEFORE the provider is
    # ever used (provider_generate), even though resolution now happens
    # earlier than pipeline_run.
    pipeline_idx = log.events.index("pipeline_run")
    generate_idx = log.events.index("provider_generate:l7_ollama_like")
    check(pipeline_idx < generate_idx, "pipeline_run() completes before the provider is used for generate()")

    _fresh_env()
    log2 = CallLog()
    planner2, remote2, local2, manager2 = _build_planner_and_providers(log2)
    sa_agent, sa_pipeline = _build_stock_agent(planner2, log2)
    sa_agent.run(_msg("BBCA"), requirement=ProviderRequirement(local_only=True))
    check(not sa_pipeline.saw_base_provider_instance, "StockAgent: pipeline never sees a BaseProvider instance")


def main() -> int:
    scenarios = [
        scenario_backward_compatibility,
        scenario_requirement_path_uses_correct_method,
        scenario_single_lookup,
        scenario_reuse_instance,
        scenario_service_context_provider_name,
        scenario_requirement_none_identical_flow,
        scenario_idx_stock_agent_inherits_automatically,
        scenario_locked_files_unchanged,
        scenario_agent_tool_adapter_out_of_scope,
        scenario_mutual_exclusivity,
        scenario_pipeline_independence,
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
    print(f"STAGE L7 REQUIREMENT AGENT ROUTING RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())