"""
Stage L4 proof suite -- Planner Integration (requirement-based selection).

Scope (per this session's LOCKED design decision):
  - Agents/planner.py (additive only):
      * Planner.__init__ gained one new optional parameter,
        `provider_selector: Optional[ProviderSelector] = None`.
      * Planner.select_by_requirement(requirement) -- new method,
        delegates entirely to the injected ProviderSelector.
      * Planner.plan(message, provider_name=None, requirement=None) --
        gained one new optional parameter, `requirement`. When given,
        selection goes through select_by_requirement() instead of
        select_provider(); provider_name is not consulted for that call.

Untouched by this stage (proven, not just claimed, below where
practical): Agents/base_agent.py, Agents/stock_agent.py,
Agents/market_analysis_agent.py, Providers/provider_manager.py,
Core/runtime.py, Agents/executor.py, Core/approval.py,
Core/composition_root.py.

Cakupan skenario:
  1. Backward compatibility -- every pre-existing Planner call shape
     (positional/keyword, with/without default_provider_name, with/without
     an explicit provider_name, the "no name at all -> first registered"
     fallback, the "no provider registered -> PlannerError" failure)
     behaves identically to before this stage, whether or not a
     provider_selector was supplied at construction.
  2. select_by_requirement() with no selector injected -> PlannerError,
     not a silent fallback to name-based selection and not an
     AttributeError/crash.
  3. select_by_requirement() with a selector injected -> delegates
     correctly, filtering/scoring purely via capabilities (proven via a
     custom BaseProvider subclass this suite defines, mirroring Stage
     L3's own polymorphism proof).
  4. select_by_requirement() propagates ProviderError unchanged when no
     registered provider satisfies the requirement.
  5. plan(requirement=...) uses the requirement path and ignores
     provider_name when both are given; plan() with neither given keeps
     using the pre-existing provider_name/default fallback chain.
  6. The two paths coexist on the same Planner instance without
     interfering with each other's state.
  7. No provider-name/isinstance branching was introduced in
     Agents/planner.py -- proven via inspect.getsource() + regex, same
     technique Stage L3 used on provider_selector.py.
  8. Public surface of Planner.select_provider() and Planner.plan()'s
     pre-existing parameters (name, order, defaults) is unchanged --
     regression guard specific to this stage's "0 behavior change on
     the old path" requirement.
  9. Locked-file regression guard: Agents/base_agent.py,
     Agents/stock_agent.py, Agents/market_analysis_agent.py,
     Providers/provider_manager.py source is unchanged from a
     re-import's perspective (their call sites into Planner still work
     with the exact same call shapes they used before).

All checks are hermetic: no network call, no API key, no external
package required.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path
from typing import Any, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Providers import (
    BaseProvider,
    GeminiProvider,
    Message,
    MessageRole,
    OllamaProvider,
    ProviderCapabilities,
    ProviderManager,
    ProviderRequirement,
    ProviderResponse,
    ProviderSelector,
)
from Agents.planner import Planner, PlannerError, Plan
from Agents.tool_registry import ToolRegistry
import Agents.planner as planner_module
from Core.exceptions import ProviderError

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
# Test doubles. Defined only here -- production code (Planner,
# ProviderSelector) has never seen these classes, proving the
# requirement-based path works purely via .capabilities.
# ---------------------------------------------------------------------------
class _FakeProvider(BaseProvider):
    """Minimal concrete BaseProvider with a configurable capabilities value."""

    def __init__(self, label: str, capabilities: Optional[ProviderCapabilities] = None) -> None:
        super().__init__()
        self._label = label
        self._capabilities = capabilities or ProviderCapabilities()

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
        return ProviderResponse(text="ok", finish_reason="stop", model=self._label)

    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        yield "ok"

    def count_tokens(self, messages: List[Message]) -> int:
        return len(messages)

    def health_check(self) -> bool:
        return True


def _fresh_provider_manager(*named_providers: "tuple[str, BaseProvider]") -> ProviderManager:
    """Register the given (name, provider) pairs on a clean ProviderManager
    singleton, unregistering anything already sitting under those names
    first (defensive against leftover state from a prior scenario/run).
    """
    manager = ProviderManager()
    for name, _ in named_providers:
        if manager.exists(name):
            manager.unregister(name)
    for name, provider in named_providers:
        manager.register(name, provider)
    return manager


def _cleanup(manager: ProviderManager, *names: str) -> None:
    for name in names:
        if manager.exists(name):
            manager.unregister(name)


def _msg(text: str = "hello") -> Message:
    return Message(role=MessageRole.USER, content=text)


# ---------------------------------------------------------------------------
# 1. Backward compatibility of the pre-existing, name-based path.
# ---------------------------------------------------------------------------
def scenario_backward_compatibility_name_path() -> None:
    print("\n[1] Backward compatibility -- provider_name path unchanged")

    manager = _fresh_provider_manager(
        ("l4_prov_a", _FakeProvider("l4_prov_a")),
        ("l4_prov_b", _FakeProvider("l4_prov_b")),
    )
    tool_registry = ToolRegistry()

    try:
        # (a) No provider_selector supplied at all -- exactly the old
        # constructor call shape.
        planner = Planner(provider_manager=manager, tool_registry=tool_registry)
        provider = planner.select_provider("l4_prov_a")
        check(provider.name == "l4_prov_a", "select_provider(explicit name) still returns the named provider")

        # (b) default_provider_name fallback still works.
        planner_default = Planner(
            provider_manager=manager,
            tool_registry=tool_registry,
            default_provider_name="l4_prov_b",
        )
        check(
            planner_default.select_provider().name == "l4_prov_b",
            "select_provider() with no arg still falls back to default_provider_name",
        )

        # (c) No name and no default -- first registered provider wins.
        planner_no_default = Planner(provider_manager=manager, tool_registry=tool_registry)
        check(
            planner_no_default.select_provider().name in ("l4_prov_a", "l4_prov_b"),
            "select_provider() with nothing configured falls back to first-registered provider",
        )

        # (d) plan() without requirement behaves exactly as before.
        plan = planner.plan(_msg("just chatting"), provider_name="l4_prov_b")
        check(isinstance(plan, Plan), "plan() still returns a Plan instance")
        check(plan.provider.name == "l4_prov_b", "plan(provider_name=...) still resolves by name when requirement is omitted")

        # (e) Supplying a provider_selector at construction does NOT
        # change select_provider()/plan(provider_name=...) behavior.
        selector = ProviderSelector(manager)
        planner_with_selector = Planner(
            provider_manager=manager, tool_registry=tool_registry, provider_selector=selector
        )
        check(
            planner_with_selector.select_provider("l4_prov_a").name == "l4_prov_a",
            "select_provider() unaffected by presence of an injected provider_selector",
        )
        plan2 = planner_with_selector.plan(_msg(), provider_name="l4_prov_a")
        check(
            plan2.provider.name == "l4_prov_a",
            "plan(provider_name=...) unaffected by presence of an injected provider_selector",
        )
    finally:
        _cleanup(manager, "l4_prov_a", "l4_prov_b")


def scenario_backward_compatibility_no_provider_registered() -> None:
    print("\n[1b] Backward compatibility -- empty registry still raises PlannerError")

    manager = ProviderManager()
    # Ensure the singleton is actually empty for this check.
    for name in list(manager.list()):
        manager.unregister(name)
    tool_registry = ToolRegistry()
    planner = Planner(provider_manager=manager, tool_registry=tool_registry)

    raised = False
    try:
        planner.select_provider()
    except PlannerError:
        raised = True
    check(raised, "select_provider() with an empty registry still raises PlannerError, unchanged")


# ---------------------------------------------------------------------------
# 2. select_by_requirement() with no selector injected.
# ---------------------------------------------------------------------------
def scenario_no_selector_injected() -> None:
    print("\n[2] select_by_requirement() without an injected ProviderSelector")

    manager = _fresh_provider_manager(("l4_prov_c", _FakeProvider("l4_prov_c")))
    tool_registry = ToolRegistry()
    planner = Planner(provider_manager=manager, tool_registry=tool_registry)  # no provider_selector

    try:
        raised_planner_error = False
        try:
            planner.select_by_requirement(ProviderRequirement())
        except PlannerError:
            raised_planner_error = True
        except Exception:
            raised_planner_error = False
        check(
            raised_planner_error,
            "select_by_requirement() without a selector raises PlannerError (not a silent name-based fallback)",
        )

        raised_via_plan = False
        try:
            planner.plan(_msg(), requirement=ProviderRequirement())
        except PlannerError:
            raised_via_plan = True
        check(
            raised_via_plan,
            "plan(requirement=...) without a selector raises PlannerError through the same path",
        )
    finally:
        _cleanup(manager, "l4_prov_c")


# ---------------------------------------------------------------------------
# 3. select_by_requirement() with a selector injected -- correct delegation.
# ---------------------------------------------------------------------------
def scenario_requirement_path_delegates_correctly() -> None:
    print("\n[3] select_by_requirement() with an injected ProviderSelector")

    weak = _FakeProvider("l4_weak", ProviderCapabilities(supports_json=True))
    strong = _FakeProvider(
        "l4_strong",
        ProviderCapabilities(
            supports_json=True,
            supports_images=True,
            supports_reasoning=True,
            max_context_tokens=500_000,
        ),
    )
    manager = _fresh_provider_manager(("l4_weak", weak), ("l4_strong", strong))
    tool_registry = ToolRegistry()
    selector = ProviderSelector(manager)
    planner = Planner(provider_manager=manager, tool_registry=tool_registry, provider_selector=selector)

    try:
        chosen = planner.select_by_requirement(ProviderRequirement(need_json=True, need_images=True))
        check(chosen.name == "l4_strong", "select_by_requirement() picks the provider whose capabilities satisfy the requirement")

        chosen_any = planner.select_by_requirement(ProviderRequirement(need_json=True))
        check(
            chosen_any.name == "l4_strong",
            "select_by_requirement() scoring prefers the provider with more matching optional capabilities",
        )

        plan = planner.plan(_msg(), requirement=ProviderRequirement(need_reasoning=True))
        check(plan.provider.name == "l4_strong", "plan(requirement=...) delegates to select_by_requirement()")
    finally:
        _cleanup(manager, "l4_weak", "l4_strong")


# ---------------------------------------------------------------------------
# 4. select_by_requirement() propagates ProviderError when nothing matches.
# ---------------------------------------------------------------------------
def scenario_no_match_propagates_provider_error() -> None:
    print("\n[4] select_by_requirement() with no satisfying provider")

    plain = _FakeProvider("l4_plain", ProviderCapabilities())
    manager = _fresh_provider_manager(("l4_plain", plain))
    tool_registry = ToolRegistry()
    selector = ProviderSelector(manager)
    planner = Planner(provider_manager=manager, tool_registry=tool_registry, provider_selector=selector)

    try:
        raised = False
        try:
            planner.select_by_requirement(ProviderRequirement(need_images=True, minimum_context_tokens=1_000_000))
        except ProviderError:
            raised = True
        check(raised, "select_by_requirement() propagates ProviderError, unchanged, when no provider satisfies the requirement")
    finally:
        _cleanup(manager, "l4_plain")


# ---------------------------------------------------------------------------
# 5 & 6. plan() argument precedence + coexistence on one Planner instance.
# ---------------------------------------------------------------------------
def scenario_plan_precedence_and_coexistence() -> None:
    print("\n[5-6] plan() precedence between provider_name and requirement; both paths coexist")

    named = _FakeProvider("l4_named", ProviderCapabilities(supports_json=True))
    capable = _FakeProvider("l4_capable", ProviderCapabilities(supports_stream=True, supports_json=True))
    manager = _fresh_provider_manager(("l4_named", named), ("l4_capable", capable))
    tool_registry = ToolRegistry()
    selector = ProviderSelector(manager)
    planner = Planner(
        provider_manager=manager,
        tool_registry=tool_registry,
        default_provider_name="l4_named",
        provider_selector=selector,
    )

    try:
        # requirement given alongside provider_name -> requirement wins,
        # provider_name is not consulted for that call.
        plan_both = planner.plan(_msg(), provider_name="l4_named", requirement=ProviderRequirement(need_stream=True))
        check(
            plan_both.provider.name == "l4_capable",
            "plan() prefers the requirement path over provider_name when both are supplied",
        )

        # Neither given -> pre-existing default_provider_name fallback,
        # completely unaffected by the requirement path existing.
        plan_neither = planner.plan(_msg())
        check(
            plan_neither.provider.name == "l4_named",
            "plan() with neither argument still falls back to default_provider_name",
        )

        # Interleave both paths on the SAME Planner instance repeatedly,
        # confirming neither call mutates shared state the other reads.
        for _ in range(3):
            r1 = planner.select_provider("l4_named")
            r2 = planner.select_by_requirement(ProviderRequirement(need_stream=True))
            check(r1.name == "l4_named" and r2.name == "l4_capable", "repeated interleaved calls on both paths remain independent and correct")
    finally:
        _cleanup(manager, "l4_named", "l4_capable")


# ---------------------------------------------------------------------------
# 7. No provider-name / isinstance branching introduced.
# ---------------------------------------------------------------------------
def scenario_no_name_branching() -> None:
    print("\n[7] No provider-name/isinstance branching in Agents/planner.py")

    source = inspect.getsource(planner_module)

    forbidden_patterns = [
        r'==\s*"gemini"',
        r'==\s*"ollama"',
        r'provider_name\s*==\s*"',
        r'\.name\s*==\s*"',
        r"isinstance\([^)]*GeminiProvider",
        r"isinstance\([^)]*OllamaProvider",
    ]
    for pattern in forbidden_patterns:
        check(
            re.search(pattern, source) is None,
            f"Agents/planner.py source does not contain forbidden pattern: {pattern}",
        )

    # select_by_requirement() itself must not reference provider_manager
    # at all -- it should delegate purely to provider_selector.
    method_source = inspect.getsource(Planner.select_by_requirement)
    check(
        "_provider_manager" not in method_source,
        "select_by_requirement() does not touch _provider_manager directly -- pure delegation to ProviderSelector",
    )


# ---------------------------------------------------------------------------
# 8. Public surface of the pre-existing path is unchanged.
# ---------------------------------------------------------------------------
def scenario_locked_surfaces_unchanged() -> None:
    print("\n[8] Pre-existing public surface unchanged")

    sig = inspect.signature(Planner.select_provider)
    params = list(sig.parameters.keys())
    check(params == ["self", "provider_name"], "select_provider()'s signature (name, order) is unchanged")
    check(
        sig.parameters["provider_name"].default is None,
        "select_provider()'s provider_name default is still None",
    )

    plan_sig = inspect.signature(Planner.plan)
    plan_params = list(plan_sig.parameters.keys())
    check(
        plan_params[:3] == ["self", "message", "provider_name"],
        "plan()'s pre-existing parameters (self, message, provider_name) keep their original order",
    )
    check(
        "requirement" in plan_params and plan_params.index("requirement") == 3,
        "plan()'s new 'requirement' parameter was appended after provider_name, not inserted before it",
    )
    check(
        plan_sig.parameters["requirement"].default is None,
        "plan()'s new 'requirement' parameter defaults to None (opt-in only)",
    )

    init_sig = inspect.signature(Planner.__init__)
    init_params = list(init_sig.parameters.keys())
    check(
        init_params[:4] == ["self", "provider_manager", "tool_registry", "default_provider_name"],
        "Planner.__init__'s pre-existing first four parameters keep their original order",
    )
    check(
        init_params[-1] == "provider_selector" and init_sig.parameters["provider_selector"].default is None,
        "Planner.__init__'s new 'provider_selector' parameter is appended last and defaults to None",
    )

    # Plan dataclass itself untouched.
    plan_fields = list(Plan.__dataclass_fields__.keys())
    check(plan_fields == ["use_tool", "provider", "tool_name"], "Plan dataclass fields/order unchanged")


# ---------------------------------------------------------------------------
# 9. Locked-file call-site regression guard.
# ---------------------------------------------------------------------------
def scenario_locked_call_sites_still_work() -> None:
    print("\n[9] Locked-file call shapes into Planner still work unchanged")

    provider = _FakeProvider("l4_locked_check")
    manager = _fresh_provider_manager(("l4_locked_check", provider))
    tool_registry = ToolRegistry()

    try:
        # Exact call shape BaseAgent.run() uses: plan(message, provider_name=provider_name)
        planner = Planner(provider_manager=manager, tool_registry=tool_registry)
        plan = planner.plan(_msg("hi"), provider_name=None)
        check(plan.provider.name == "l4_locked_check", "BaseAgent.run()'s call shape -- plan(message, provider_name=provider_name) -- still works")

        # Exact call shape BaseAgent.health_check() uses: select_provider()
        p = planner.select_provider()
        check(p.name == "l4_locked_check", "BaseAgent.health_check()'s call shape -- select_provider() -- still works")

        # Exact call shape StockAgent/MarketAnalysisAgent use:
        # select_provider(resolved_provider_name)
        p2 = planner.select_provider("l4_locked_check")
        check(p2.name == "l4_locked_check", "StockAgent/MarketAnalysisAgent's call shape -- select_provider(name) -- still works")

        # Composition Root's exact construction call shape (positional-free, two kwargs).
        cr_style_planner = Planner(provider_manager=manager, tool_registry=tool_registry)
        check(isinstance(cr_style_planner, Planner), "Core.composition_root's Planner(...) construction call shape still works unchanged")
    finally:
        _cleanup(manager, "l4_locked_check")

    # Confirm the locked files' source was never touched by this stage
    # (best-effort static guard: they must not import anything L4-new).
    #
    # Stage L5 scope note: `Core/composition_root.py` was intentionally
    # removed from this tuple. At Stage L4 it was correctly LOCKED (this
    # check proved L4 never touched it). Stage L5's entire, approved
    # purpose is to wire `ProviderSelector`/`provider_selector` INTO
    # `Core/composition_root.py` -- so asserting its absence there would
    # now be a false-positive failure, not a real regression. The guard
    # is narrowed to the files still LOCKED as of L5; it is not weakened
    # for any of them.
    #
    # Stage L7 scope note (same precedent as L5, above): `Agents/base_agent.py`,
    # `Agents/stock_agent.py`, and `Agents/market_analysis_agent.py` are
    # intentionally removed from this tuple. They were correctly LOCKED
    # through L4-L6 (this check proved so). Stage L7's entire, approved
    # purpose is Requirement-based Agent Routing: `BaseAgent.run()`/`chat()`
    # gain a pass-through `requirement` param into `Planner.plan()`, and
    # `MarketAnalysisAgent`/`StockAgent` gain calls to
    # `Planner.select_by_requirement()` via the new
    # `MarketAnalysisAgent._resolve_provider_for_request()` helper -- so
    # asserting the absence of `select_by_requirement`/`provider_selector`
    # references in these three files would now be a false-positive
    # failure, not a real regression. See
    # `Tests/test_stage_l7_requirement_agent_routing.py` for this stage's
    # own locked-file guard (Planner, ProviderSelector, ProviderManager,
    # CompositionRoot, Runtime, Executor, Approval, Gemini/OllamaProvider,
    # IDXStockAgent, AgentToolAdapter, ServiceContext), which now carries
    # this responsibility for the three files removed here.
    for locked_path in (
        ROOT / "Providers" / "provider_manager.py",
        ROOT / "Core" / "runtime.py",
        ROOT / "Agents" / "executor.py",
        ROOT / "Core" / "approval.py",
    ):
        text = locked_path.read_text(encoding="utf-8", errors="replace")
        check(
            "select_by_requirement" not in text and "provider_selector" not in text,
            f"{locked_path.relative_to(ROOT)} contains no reference to Stage L4's new Planner API (untouched)",
        )


def main() -> int:
    scenarios = [
        scenario_backward_compatibility_name_path,
        scenario_backward_compatibility_no_provider_registered,
        scenario_no_selector_injected,
        scenario_requirement_path_delegates_correctly,
        scenario_no_match_propagates_provider_error,
        scenario_plan_precedence_and_coexistence,
        scenario_no_name_branching,
        scenario_locked_surfaces_unchanged,
        scenario_locked_call_sites_still_work,
    ]

    import traceback

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
    print(f"STAGE L4 PLANNER INTEGRATION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())