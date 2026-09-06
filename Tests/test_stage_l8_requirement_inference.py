"""
Stage L8 proof suite -- Automatic Requirement Inference.

Scope (per this session's approved diff-level plan):
  - Agents/requirement_inference.py (NEW):
      * infer_requirement(text) -> Optional[ProviderRequirement]. Pure
        function, no Planner/ProviderSelector/ProviderManager import,
        no side effects. Keyword scope limited to need_images,
        local_only, need_reasoning. Returns None (not the empty
        ProviderRequirement()) when nothing matches.
  - Agents/base_agent.py:
      * chat() only. When provider_name is None AND requirement is
        None, attempts infer_requirement(user_input); if it returns a
        requirement, probes it via self._planner.select_by_requirement()
        -- if that succeeds, the inferred requirement is used; if it
        raises PlannerError or ProviderError, the exception is
        swallowed and requirement stays None (opportunistic fallback,
        Option C). run() itself is untouched.
  - Agents/stock_agent.py:
      * chat() override removed -- StockAgent now inherits
        BaseAgent.chat() (which carries the Stage L8 probe).

Untouched by this stage (locked): Agents/planner.py,
Providers/provider_selector.py, Providers/provider_manager.py,
Providers/requirement.py, Providers/capabilities.py,
Core/composition_root.py, Core/runtime.py, Core/approval.py,
Core/startup_validation.py, Agents/market_analysis_agent.py,
Agents/idx_stock_agent.py, Agents/agent_tool_adapter.py,
Providers/gemini.py, Providers/ollama.py, Agents/executor.py.

Cakupan skenario (1-10, disepakati dengan user sebelum coding):
  1. Keyword IMAGE -> need_images=True (other fields False).
  2. Keyword LOCAL -> local_only=True.
  3. Keyword REASONING -> need_reasoning=True.
  4. No keyword -> None (not ProviderRequirement()).
  5. provider_name explicit -> infer_requirement() is never called.
  6. requirement explicit -> infer_requirement() is never called.
  7. Opportunistic fallback: inferred requirement has no matching
     provider -> chat() still succeeds, using the pre-existing
     name/default path, no exception escapes.
  8. Explicit requirement stays fail-closed: an unsatisfiable
     *explicit* requirement still raises ProviderError (Stage L4/L7
     contract unchanged by L8).
  9. StockAgent.chat() (now inherited from BaseAgent) behaves
     identically to the removed override for every pre-existing
     argument combination.
  10. Locked-file guard: none of the locked files contain Stage L8
      vocabulary; the three approved files do.

All checks are hermetic: no network call, no API key, no external
package required.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import Agents.base_agent as base_agent_module
from Agents.base_agent import AgentStateError, BaseAgent
from Agents.executor import Executor
from Agents.memory import ConversationMemory
from Agents.planner import Planner, PlannerError
from Agents.requirement_inference import infer_requirement
from Agents.stock_agent import StockAgent
from Agents.tool_registry import ToolRegistry
from Core.analysis_pipeline import AnalysisPipeline
from Core.exceptions import ProviderError
from Core.tool_context_builder import ToolContextBuilder
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
class _FakeProvider(BaseProvider):
    """Minimal concrete BaseProvider with a configurable capabilities value."""

    def __init__(self, label: str, capabilities: Optional[ProviderCapabilities] = None) -> None:
        super().__init__()
        self._label = label
        self._capabilities = capabilities or ProviderCapabilities()
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
        self.generate_calls.append(list(messages))
        return ProviderResponse(text=f"reply-from-{self._label}")

    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        raise NotImplementedError

    def count_tokens(self, messages: List[Message]) -> int:
        return 0

    def health_check(self) -> bool:
        return True


class SpyPlanner(Planner):
    """Wraps Planner's resolution methods with call counters, pure
    delegation to super() so assertions prove something about the real
    Planner contract."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.select_provider_calls = 0
        self.select_by_requirement_calls = 0

    def select_provider(self, provider_name: Optional[str] = None) -> BaseProvider:
        self.select_provider_calls += 1
        return super().select_provider(provider_name)

    def select_by_requirement(self, requirement: ProviderRequirement) -> BaseProvider:
        self.select_by_requirement_calls += 1
        return super().select_by_requirement(requirement)


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


REMOTE_NAME = "l8_gemini_like"
LOCAL_NAME = "l8_ollama_like"
LOCAL_CAPS = ProviderCapabilities(is_local=True)


def _build_env_with_local_and_remote():
    """Registry has BOTH a remote (default) and a local provider --
    used for scenarios where an inferred/explicit requirement CAN be
    satisfied."""
    manager = ProviderManager()
    remote = _FakeProvider(REMOTE_NAME, ProviderCapabilities())
    local = _FakeProvider(LOCAL_NAME, LOCAL_CAPS)
    manager.register(REMOTE_NAME, remote)
    manager.register(LOCAL_NAME, local)

    tool_registry = ToolRegistry()
    selector = ProviderSelector(manager)
    planner = SpyPlanner(
        provider_manager=manager,
        tool_registry=tool_registry,
        default_provider_name=REMOTE_NAME,
        provider_selector=selector,
    )
    return planner, remote, local, manager


def _build_env_remote_only():
    """Registry has ONLY a remote (non-local, non-image) provider --
    used for the opportunistic-fallback scenario: any inferred
    requirement that needs images or locality cannot be satisfied."""
    manager = ProviderManager()
    remote = _FakeProvider(REMOTE_NAME, ProviderCapabilities())
    manager.register(REMOTE_NAME, remote)

    tool_registry = ToolRegistry()
    selector = ProviderSelector(manager)
    planner = SpyPlanner(
        provider_manager=manager,
        tool_registry=tool_registry,
        default_provider_name=REMOTE_NAME,
        provider_selector=selector,
    )
    return planner, remote, manager


def _build_base_agent(planner: Planner) -> _ConcreteBaseAgent:
    tool_registry = planner._tool_registry  # type: ignore[attr-defined]
    return _ConcreteBaseAgent(
        planner=planner,
        memory=ConversationMemory(),
        executor=Executor(tool_registry=tool_registry),
    )


def _build_stock_agent(planner: Planner) -> StockAgent:
    from Orchestration.instrument_extractor import BaseInstrumentExtractor

    class _StubExtractor(BaseInstrumentExtractor):
        def extract(self, text: str) -> str:
            return "BBCA.JK"

    class _StubPipeline:
        def run(self, context):
            return {"stock_service": "sentinel"}

    class _StubBuilder:
        def build(self, results):
            return "[Stock]\nsentinel"

    tool_registry = planner._tool_registry  # type: ignore[attr-defined]
    return StockAgent(
        planner=planner,
        memory=ConversationMemory(),
        executor=Executor(tool_registry=tool_registry),
        analysis_pipeline=_StubPipeline(),  # duck-typed: only .run(context) used
        tool_context_builder=_StubBuilder(),
        default_provider_name=planner._default_provider_name,  # type: ignore[attr-defined]
        instrument_extractor=_StubExtractor(),
    )


# ---------------------------------------------------------------------------
# 1-4. infer_requirement() keyword mapping
# ---------------------------------------------------------------------------
def scenario_infer_image_keyword() -> None:
    print("\n[1] Keyword IMAGE -> need_images=True")
    for text in ("Generate chart PNG please", "tolong buatkan grafik", "gambar visualisasi harga"):
        req = infer_requirement(text)
        check(req is not None, f"infer_requirement({text!r}) is not None")
        if req is not None:
            check(req.need_images is True, f"infer_requirement({text!r}).need_images is True")
            check(req.local_only is False, f"infer_requirement({text!r}).local_only stays False")
            check(req.need_reasoning is False, f"infer_requirement({text!r}).need_reasoning stays False")


def scenario_infer_local_keyword() -> None:
    print("\n[2] Keyword LOCAL -> local_only=True")
    for text in ("Jalankan lokal saja", "run this offline", "use a local model"):
        req = infer_requirement(text)
        check(req is not None, f"infer_requirement({text!r}) is not None")
        if req is not None:
            check(req.local_only is True, f"infer_requirement({text!r}).local_only is True")
            check(req.need_images is False, f"infer_requirement({text!r}).need_images stays False")


def scenario_infer_reasoning_keyword() -> None:
    print("\n[3] Keyword REASONING -> need_reasoning=True")
    for text in ("Analisa saham BBCA", "tolong analisis prediksi harga", "explain your reasoning"):
        req = infer_requirement(text)
        check(req is not None, f"infer_requirement({text!r}) is not None")
        if req is not None:
            check(req.need_reasoning is True, f"infer_requirement({text!r}).need_reasoning is True")


def scenario_infer_no_keyword() -> None:
    print("\n[4] No keyword -> None (not ProviderRequirement())")
    for text in ("hello there", "what time is it", "terima kasih"):
        req = infer_requirement(text)
        check(req is None, f"infer_requirement({text!r}) is None, got {req!r}")


# ---------------------------------------------------------------------------
# 5-6. Explicit provider_name/requirement bypass inference entirely
# ---------------------------------------------------------------------------
def scenario_explicit_provider_name_bypasses_inference() -> None:
    print("\n[5] provider_name explicit -> infer_requirement() never called")

    calls: List[str] = []
    original = base_agent_module.infer_requirement

    def _spy(text: str):
        calls.append(text)
        return original(text)

    base_agent_module.infer_requirement = _spy
    try:
        _fresh_env()
        planner, remote, local, manager = _build_env_with_local_and_remote()
        agent = _build_base_agent(planner)
        reply = agent.chat("Generate chart PNG please", provider_name=REMOTE_NAME)
        check(calls == [], "infer_requirement() was not invoked when provider_name is explicit")
        check(reply == f"reply-from-{REMOTE_NAME}", "explicit provider_name path still resolves correctly")
    finally:
        base_agent_module.infer_requirement = original


def scenario_explicit_requirement_bypasses_inference() -> None:
    print("\n[6] requirement explicit -> infer_requirement() never called")

    calls: List[str] = []
    original = base_agent_module.infer_requirement

    def _spy(text: str):
        calls.append(text)
        return original(text)

    base_agent_module.infer_requirement = _spy
    try:
        _fresh_env()
        planner, remote, local, manager = _build_env_with_local_and_remote()
        agent = _build_base_agent(planner)
        reply = agent.chat(
            "Generate chart PNG please",
            requirement=ProviderRequirement(local_only=True),
        )
        check(calls == [], "infer_requirement() was not invoked when requirement is explicit")
        check(reply == f"reply-from-{LOCAL_NAME}", "explicit requirement still wins/resolves correctly")
        check(planner.select_by_requirement_calls == 1, "select_by_requirement() called exactly once for the explicit requirement")
    finally:
        base_agent_module.infer_requirement = original


# ---------------------------------------------------------------------------
# 7. Opportunistic fallback -- inferred requirement unmet, no error
# ---------------------------------------------------------------------------
def scenario_opportunistic_fallback() -> None:
    print("\n[7] Opportunistic fallback -- inferred requirement unmet -> silent fallback to default path")

    _fresh_env()
    planner, remote, manager = _build_env_remote_only()
    agent = _build_base_agent(planner)

    raised = False
    reply = None
    try:
        # "lokal" infers local_only=True, but only a non-local provider
        # is registered -> ProviderSelector.select() would raise
        # ProviderError. Opportunistic contract: swallow, fall back.
        reply = agent.chat("Jalankan analisa ini secara lokal")
    except Exception:  # noqa: BLE001
        raised = True

    check(not raised, "chat() does not raise when the inferred requirement has no matching provider")
    check(reply == f"reply-from-{REMOTE_NAME}", "chat() falls back to the default/name-based provider")
    check(planner.select_by_requirement_calls == 1, "the probe call to select_by_requirement() happened exactly once")
    check(planner.select_provider_calls == 1, "select_provider() (name/default path) was used for the actual turn")
    check(len(remote.generate_calls) == 1, "the default provider's generate() was called")


def scenario_opportunistic_success() -> None:
    print("\n[7b] Opportunistic success -- inferred requirement IS met -> requirement path used")

    _fresh_env()
    planner, remote, local, manager = _build_env_with_local_and_remote()
    agent = _build_base_agent(planner)

    # NOTE: deliberately a LOCAL-only keyword phrase, no REASONING
    # keyword overlap (e.g. "analisa") -- LOCAL_CAPS only sets
    # is_local=True, not supports_reasoning, so a phrase matching both
    # groups would correctly fail the local provider's capability check
    # and is not what this scenario is testing.
    reply = agent.chat("Jalankan lokal saja")

    check(reply == f"reply-from-{LOCAL_NAME}", "chat() uses the requirement-satisfying (local) provider when one is registered")
    # Known, documented cost of the Option C probe design (flagged before
    # implementation): chat() probes select_by_requirement() once to
    # decide whether to adopt the inferred requirement, then run() ->
    # Planner.plan(requirement=...) resolves it again for the actual
    # turn. Both calls are read-only (no side effect beyond a debug log
    # line), so this is an accepted cost, not a bug.
    check(planner.select_by_requirement_calls == 2, "select_by_requirement() called twice: one opportunistic probe + one real resolution inside run()")
    check(planner.select_provider_calls == 0, "select_provider() was not needed at all -- the inferred requirement path succeeded")


# ---------------------------------------------------------------------------
# 8. Explicit requirement stays fail-closed (unchanged from L4/L7)
# ---------------------------------------------------------------------------
def scenario_explicit_requirement_fail_closed() -> None:
    print("\n[8] Explicit requirement unmet -> ProviderError still propagates (fail-closed, unchanged)")

    _fresh_env()
    planner, remote, manager = _build_env_remote_only()
    agent = _build_base_agent(planner)

    raised = False
    try:
        agent.chat("just chatting", requirement=ProviderRequirement(local_only=True))
    except ProviderError:
        raised = True
    except Exception:  # noqa: BLE001
        raised = False  # wrong exception type -- treated as failure below

    check(raised, "an explicit, unsatisfiable requirement still raises ProviderError (Stage L4/L7 contract unchanged)")
    check(agent.state.name == "ERROR", "agent transitions to ERROR state on the propagated ProviderError")


# ---------------------------------------------------------------------------
# 9. StockAgent.chat() (inherited) behaves identically to the removed override
# ---------------------------------------------------------------------------
def scenario_stock_agent_inherited_chat_identical() -> None:
    print("\n[9] StockAgent.chat() (inherited from BaseAgent) behaves like the removed override")

    # StockAgent no longer defines chat() at all -- confirm it resolves
    # to BaseAgent.chat via MRO, not silently missing/broken.
    check(
        "chat" not in StockAgent.__dict__,
        "StockAgent no longer defines its own chat() (override removed)",
    )
    check(
        StockAgent.chat is BaseAgent.chat,
        "StockAgent.chat resolves to BaseAgent.chat via inheritance",
    )

    # Backward-compat: provider_name-only call, no requirement, no
    # inference-eligible keywords -- identical to pre-L8 behavior.
    _fresh_env()
    planner, remote, local, manager = _build_env_with_local_and_remote()
    agent = _build_stock_agent(planner)
    reply = agent.chat("BBCA please", provider_name=REMOTE_NAME)
    check(reply == f"reply-from-{REMOTE_NAME}", "StockAgent.chat(provider_name=...) still resolves the named provider")

    # requirement-only call, unchanged from L7.
    _fresh_env()
    planner2, remote2, local2, manager2 = _build_env_with_local_and_remote()
    agent2 = _build_stock_agent(planner2)
    reply2 = agent2.chat("BBCA", requirement=ProviderRequirement(local_only=True))
    check(reply2 == f"reply-from-{LOCAL_NAME}", "StockAgent.chat(requirement=...) still resolves via select_by_requirement")

    # No explicit args, no inference-eligible keyword -- falls to
    # default provider exactly like the pre-L8 override did.
    _fresh_env()
    planner3, remote3, local3, manager3 = _build_env_with_local_and_remote()
    agent3 = _build_stock_agent(planner3)
    reply3 = agent3.chat("BBCA")
    check(reply3 == f"reply-from-{REMOTE_NAME}", "StockAgent.chat() with no args/no keyword still resolves the default provider")


# ---------------------------------------------------------------------------
# 10. Locked-file guard
# ---------------------------------------------------------------------------
def scenario_locked_files_unchanged() -> None:
    print("\n[10] Locked-file guard -- Stage L8 touched only the approved 3 files")

    locked_files = [
        ROOT / "Agents" / "planner.py",
        ROOT / "Providers" / "provider_selector.py",
        ROOT / "Providers" / "provider_manager.py",
        ROOT / "Providers" / "requirement.py",
        ROOT / "Providers" / "capabilities.py",
        ROOT / "Core" / "composition_root.py",
        ROOT / "Core" / "runtime.py",
        ROOT / "Core" / "approval.py",
        ROOT / "Agents" / "market_analysis_agent.py",
        ROOT / "Agents" / "idx_stock_agent.py",
        ROOT / "Agents" / "agent_tool_adapter.py",
        ROOT / "Providers" / "gemini.py",
        ROOT / "Providers" / "ollama.py",
        ROOT / "Agents" / "executor.py",
    ]
    locked_files.extend(ROOT.rglob("startup_validation.py"))

    l8_vocabulary = ("infer_requirement", "requirement_inference")

    for path in locked_files:
        if not path.exists():
            check(False, f"{path.relative_to(ROOT)} expected to exist but was not found")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found = [term for term in l8_vocabulary if term in text]
        check(not found, f"{path.relative_to(ROOT)} contains no Stage L8 vocabulary (untouched); found={found}")

    for path, expect in (
        (ROOT / "Agents" / "requirement_inference.py", "def infer_requirement"),
        (ROOT / "Agents" / "base_agent.py", "infer_requirement"),
    ):
        text = path.read_text(encoding="utf-8", errors="replace")
        check(expect in text, f"{path.relative_to(ROOT)} contains the expected Stage L8 change ('{expect}')")

    stock_agent_text = (ROOT / "Agents" / "stock_agent.py").read_text(encoding="utf-8", errors="replace")
    check(
        "def chat(" not in stock_agent_text,
        "Agents/stock_agent.py no longer defines a chat() override",
    )


def main() -> int:
    scenarios = [
        scenario_infer_image_keyword,
        scenario_infer_local_keyword,
        scenario_infer_reasoning_keyword,
        scenario_infer_no_keyword,
        scenario_explicit_provider_name_bypasses_inference,
        scenario_explicit_requirement_bypasses_inference,
        scenario_opportunistic_fallback,
        scenario_opportunistic_success,
        scenario_explicit_requirement_fail_closed,
        scenario_stock_agent_inherited_chat_identical,
        scenario_locked_files_unchanged,
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
    print(f"STAGE L8 REQUIREMENT INFERENCE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())