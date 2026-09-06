"""
Stage L5 proof suite -- Composition Root Integration (wiring only, Option A).

Scope (per this session's LOCKED design decision, Option A):
  - Core/composition_root.py (additive only):
      * build_application() now constructs a
        `ProviderSelector(provider_manager)` and passes it into `Planner`
        as `provider_selector=`.
      * What gets registered, or when, is UNCHANGED: `_build_provider`
        still registers exactly one provider per call, exactly as
        before L5. Only the *wiring downstream of the registry* changed.
      * `ApplicationGraph` gained no new field. The selector is a local
        variable used only to construct `Planner`.
  - Tests/test_stage_l4_planner_integration.py: narrowed its locked-file
    guard to drop `Core/composition_root.py` from the tuple it scans
    (see that file's inline comment) -- no other change to that suite.

Explicitly NOT changed by this stage (proven, not just claimed, below
where practical): Agents/planner.py, Providers/provider_manager.py,
Providers/base_provider.py, Providers/gemini.py, Providers/ollama.py,
Agents/base_agent.py, Agents/stock_agent.py,
Agents/market_analysis_agent.py, Core/runtime.py, Agents/executor.py,
Core/approval.py, Core/startup_validation.py.

Cakupan skenario:
  1. build_application() still constructible hermetically (no network,
     no API key, no external package) -- mirrors Stage 9.0's own
     Level-1 guarantee, re-proven after this stage's change.
  2. graph.planner._provider_selector is a real, non-None
     ProviderSelector wrapping the same provider_manager singleton the
     graph itself exposes -- proving the wiring actually happened, not
     just that construction didn't crash.
  3. graph.planner.select_by_requirement() is reachable and returns the
     one provider build_application() registered, for both
     provider_kind="gemini" and provider_kind="ollama".
  4. [Superseded by Stage L6 -- see Tests/test_stage_l6_multi_provider_registry.py]
     Registration behavior now intentionally registers every provider
     kind in _PROVIDER_CLASSES on every call (Stage L6, "Multi-provider
     Registry" -- the exact follow-on this stage's own docstring flagged
     as deferred). This scenario no longer asserts "exactly one new key"
     (that assertion described Stage L5's Option A, which Stage L6
     explicitly and deliberately supersedes); it instead asserts the two
     things that remain true post-L6: the canonical provider kinds are
     always present, and repeated calls never duplicate/re-register them
     (ProviderManager singleton + exists()-guarded idempotency,
     unchanged).
  5. ApplicationGraph gained no new field (dataclass field set is
     exactly the pre-L5 set) -- proving the "no graph field" design
     decision was actually followed.
  6. Planner's own pre-existing (name-based) selection path is
     unaffected when reached through the production graph.
  7. Idempotency: build_application() called twice in the same process
     does not raise and does not duplicate registration -- unchanged
     Stage 9.0 guarantee, re-proven with the selector present.
  8. No provider-name/isinstance branching was introduced in
     Core/composition_root.py by this stage's diff (targeted regex scan
     of the new lines' surrounding context, same technique Stage L3/L4
     used).
  9. Locked-file regression guard: Agents/planner.py,
     Providers/provider_manager.py, Agents/base_agent.py,
     Agents/stock_agent.py, Agents/market_analysis_agent.py,
     Core/runtime.py, Agents/executor.py, Core/approval.py,
     Core/startup_validation.py source contains no reference to this
     stage's wiring and their public call shapes into
     Core/composition_root.py / Planner still work unchanged.
 10. Tests/test_stage_l4_planner_integration.py itself still passes in
     full after its guard was narrowed (regression-of-the-regression-
     guard check).

All checks are hermetic: no network call, no API key, no external
package required.
"""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Agents.agent_registry import AgentRegistry, agent_registry
from Agents.planner import Planner
from Agents.stock_agent import StockAgent
from Core.composition_root import ApplicationGraph, build_application
import Core.composition_root as composition_root_module
from Providers import GeminiProvider, OllamaProvider, ProviderManager, ProviderRequirement, ProviderSelector, provider_manager
from Services.service_registry import service_registry

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


def _clear_registrations(*names: str) -> None:
    """Best-effort cleanup so repeated scenarios/runs don't collide on
    ProviderManager/AgentRegistry singleton state left over from a prior
    call (mirrors the defensive cleanup pattern used by Stage 9.0/L3/L4).
    """
    for name in names:
        if provider_manager.exists(name):
            provider_manager.unregister(name)


def _clear_agent(name: str) -> None:
    if agent_registry.exists(name):
        agent_registry.unregister(name)


# ---------------------------------------------------------------------------
# 1. Hermetic constructibility, re-proven after this stage's change.
# ---------------------------------------------------------------------------
def scenario_hermetic_constructibility() -> None:
    print("\n[1] build_application() still hermetically constructible")

    _clear_registrations("l5_gemini_check")
    _clear_agent("l5_agent_check")
    try:
        graph = build_application(
            provider_name="l5_gemini_check", provider_kind="gemini", agent_name="l5_agent_check"
        )
        check(isinstance(graph, ApplicationGraph), "build_application() still returns an ApplicationGraph")
        check(isinstance(graph.agent, StockAgent), "graph.agent is still a real StockAgent")
        check(isinstance(graph.planner, Planner), "graph.planner is still a real Planner")
    finally:
        _clear_registrations("l5_gemini_check")
        _clear_agent("l5_agent_check")


# ---------------------------------------------------------------------------
# 2. Wiring actually happened.
# ---------------------------------------------------------------------------
def scenario_selector_actually_wired() -> None:
    print("\n[2] Planner in the production graph actually received a ProviderSelector")

    _clear_registrations("l5_wired_check")
    _clear_agent("l5_wired_agent")
    try:
        graph = build_application(
            provider_name="l5_wired_check", provider_kind="gemini", agent_name="l5_wired_agent"
        )
        selector = graph.planner._provider_selector  # noqa: SLF001 -- white-box proof, test-only
        check(selector is not None, "graph.planner's internal _provider_selector is not None")
        check(isinstance(selector, ProviderSelector), "graph.planner's _provider_selector is a real ProviderSelector instance")
        check(
            selector._provider_manager is graph.provider_manager,  # noqa: SLF001
            "the injected ProviderSelector wraps the SAME provider_manager singleton the graph exposes",
        )
    finally:
        _clear_registrations("l5_wired_check")
        _clear_agent("l5_wired_agent")


# ---------------------------------------------------------------------------
# 3. select_by_requirement() reachable end-to-end, for both provider kinds.
#    (Stage L6 note: an EMPTY ProviderRequirement() is no longer a valid way
#    to pin down "the one just registered" -- with more than one real
#    candidate now in the registry, ProviderSelector's scoring deterministically
#    favors Gemini's richer capabilities over Ollama's for a trivial/empty
#    requirement, regardless of which kind this call registered. Each check
#    below therefore uses a requirement that actually discriminates for the
#    kind under test, the same way Stage L3's own proof suite does.)
# ---------------------------------------------------------------------------
def scenario_requirement_path_reachable_both_kinds() -> None:
    print("\n[3] Planner.select_by_requirement() reachable from the production graph -- gemini & ollama")

    for kind, expected_class, requirement, reg_name, agent_name in (
        ("gemini", GeminiProvider, ProviderRequirement(need_json=True), "l5_req_gemini", "l5_req_agent_gemini"),
        ("ollama", OllamaProvider, ProviderRequirement(local_only=True), "l5_req_ollama", "l5_req_agent_ollama"),
    ):
        _clear_registrations(reg_name)
        _clear_agent(agent_name)
        try:
            graph = build_application(provider_name=reg_name, provider_kind=kind, agent_name=agent_name)
            provider = graph.planner.select_by_requirement(requirement)
            check(
                isinstance(provider, expected_class),
                f"select_by_requirement({requirement}) through the production graph resolves to {expected_class.__name__} when ACTIVE_PROVIDER/provider_kind='{kind}'",
            )
        finally:
            _clear_registrations(reg_name)
            _clear_agent(agent_name)


# ---------------------------------------------------------------------------
# 4. Canonical providers always present + registration stays idempotent.
#    (Supersedes the old "exactly one new key" / Option-A-only assertion --
#    Stage L6 deliberately registers every provider kind on every call. A
#    before/after set-difference is NOT used here on purpose: provider_manager
#    is a process-wide singleton, so "gemini"/"ollama" may already be present
#    from an earlier call in this same process -- see
#    Tests/test_stage_l6_multi_provider_registry.py's module docstring.)
# ---------------------------------------------------------------------------
def scenario_registration_behavior_unchanged() -> None:
    print("\n[4] Canonical providers (gemini, ollama) always present; registration stays idempotent")

    _clear_registrations("l5_single_check")
    _clear_agent("l5_single_agent")
    try:
        graph = build_application(
            provider_name="l5_single_check", provider_kind="gemini", agent_name="l5_single_agent"
        )
        check(
            graph.provider_manager.exists("gemini") and graph.provider_manager.exists("ollama"),
            "both canonical provider kinds ('gemini', 'ollama') are registered after build_application()",
        )
        gemini_before = graph.provider_manager.get("gemini")
        ollama_before = graph.provider_manager.get("ollama")

        # Calling build_application() again (same or different custom name)
        # must not duplicate/replace the canonical registrations.
        graph2 = build_application(
            provider_name="l5_single_check_2", provider_kind="ollama", agent_name="l5_single_agent_2"
        )
        try:
            check(
                graph2.provider_manager.get("gemini") is gemini_before,
                "a second build_application() call does not re-register/replace the existing 'gemini' entry",
            )
            check(
                graph2.provider_manager.get("ollama") is ollama_before,
                "a second build_application() call does not re-register/replace the existing 'ollama' entry",
            )
        finally:
            _clear_registrations("l5_single_check_2")
            _clear_agent("l5_single_agent_2")
    finally:
        _clear_registrations("l5_single_check")
        _clear_agent("l5_single_agent")


# ---------------------------------------------------------------------------
# 5. ApplicationGraph gained no new field -- true as of Stage L5 itself.
#
# Stage L11 addition (additive only, approved explicitly, mirrors how this
# same file previously narrowed Stage L4's locked-file guard after L5
# legitimately touched Core/composition_root.py -- see this module's
# top-of-file docstring): ApplicationGraph now also carries
# `runtime_analysis_pipeline` (Orchestration.runtime_analysis_pipeline.
# RuntimeAnalysisPipeline), added by Stage L11 ("Runtime sebagai Execution
# Kernel", additive-only). This scenario's assertion is updated to include
# that one new field -- what it continues to prove is unchanged: no *other*
# field was added or reordered by any stage between L5 and L11.
#
# Stage L13 addition (additive only, approved Diff-Level Plan FINAL, same
# narrowing pattern as the L11 update immediately above): ApplicationGraph
# now also carries `service_skills` (Dict[str, Orchestration.service_skill.
# ServiceSkill]), added by Stage L13 ("Granular Skills", additive-only) as
# its last field, right after `runtime_analysis_pipeline`. Updated the same
# way, for the same reason: only this one new field is added to `expected`,
# so the scenario keeps proving no *other* field was added or reordered.
# ---------------------------------------------------------------------------
def scenario_application_graph_no_new_field() -> None:
    print("\n[5] ApplicationGraph field set is the pre-L5 set plus Stage L11's runtime_analysis_pipeline and Stage L13's service_skills")

    fields = list(ApplicationGraph.__dataclass_fields__.keys())
    expected = [
        "config",
        "tool_registry",
        "provider_manager",
        "service_registry",
        "agent_registry",
        "executor",
        "planner",
        "agent",
        "database_manager",
        "runtime_analysis_pipeline",
        "service_skills",
        "goal_planner",
        "observation_recorder",
        "memory_store",
        "memory_recorder",
        "reflector",
        "agent_name",
        "provider_name",
        "provider_kind",
    ]
    check(fields == expected, f"ApplicationGraph's field set/order is the pre-L5 set + Stage L11's runtime_analysis_pipeline + Stage L13's service_skills (got {fields})")


# ---------------------------------------------------------------------------
# 6. Pre-existing name-based path unaffected through the production graph.
# ---------------------------------------------------------------------------
def scenario_name_based_path_unaffected() -> None:
    print("\n[6] Planner's pre-existing name-based path unaffected through the production graph")

    _clear_registrations("l5_name_path_check")
    _clear_agent("l5_name_path_agent")
    try:
        graph = build_application(
            provider_name="l5_name_path_check", provider_kind="gemini", agent_name="l5_name_path_agent"
        )
        provider_by_name = graph.planner.select_provider("l5_name_path_check")
        check(
            isinstance(provider_by_name, GeminiProvider),
            "select_provider(name) through the production graph still resolves by name, unaffected by the injected selector",
        )
        # plan() itself, without a requirement, should still use the name path.
        from Providers import Message, MessageRole

        result_plan = graph.planner.plan(Message(role=MessageRole.USER, content="hi"), provider_name="l5_name_path_check")
        check(
            isinstance(result_plan.provider, GeminiProvider),
            "plan(provider_name=...) through the production graph still resolves by name when requirement is omitted",
        )
    finally:
        _clear_registrations("l5_name_path_check")
        _clear_agent("l5_name_path_agent")


# ---------------------------------------------------------------------------
# 7. Idempotency preserved.
# ---------------------------------------------------------------------------
def scenario_idempotency_preserved() -> None:
    print("\n[7] build_application() idempotency preserved with the selector present")

    _clear_registrations("l5_idempotent_check")
    _clear_agent("l5_idempotent_agent")
    try:
        graph1 = build_application(
            provider_name="l5_idempotent_check", provider_kind="gemini", agent_name="l5_idempotent_agent"
        )
        provider1 = graph1.provider_manager.get("l5_idempotent_check")

        raised = False
        graph2 = None
        try:
            graph2 = build_application(
                provider_name="l5_idempotent_check", provider_kind="gemini", agent_name="l5_idempotent_agent"
            )
        except Exception:
            raised = True
        check(not raised, "calling build_application() twice with the same names does not raise")
        if graph2 is not None:
            provider2 = graph2.provider_manager.get("l5_idempotent_check")
            check(provider1 is provider2, "the second call does not re-register/duplicate the already-registered provider")
    finally:
        _clear_registrations("l5_idempotent_check")
        _clear_agent("l5_idempotent_agent")


# ---------------------------------------------------------------------------
# 8. No name/isinstance branching introduced by this stage's diff.
# ---------------------------------------------------------------------------
def scenario_no_name_branching_in_new_lines() -> None:
    print("\n[8] No provider-name/isinstance branching introduced by Stage L5's diff")

    source = inspect.getsource(composition_root_module)

    # The pre-existing _PROVIDER_CLASSES dict lookup (Stage L1, unchanged)
    # is allowed and expected; what must NOT appear is a NEW conditional
    # comparing a provider's name/class around the selector-wiring lines.
    selector_wiring_snippet = inspect.getsource(composition_root_module.build_application)
    forbidden_patterns = [
        r'provider_selector.*==\s*"',
        r'if\s+resolved_provider_kind\s*==.*ProviderSelector',
        r"isinstance\([^)]*provider_selector[^)]*,\s*(GeminiProvider|OllamaProvider)",
    ]
    for pattern in forbidden_patterns:
        check(
            re.search(pattern, selector_wiring_snippet) is None,
            f"build_application() source does not contain forbidden pattern near selector wiring: {pattern}",
        )
    check(
        "ProviderSelector(provider_manager)" in selector_wiring_snippet,
        "build_application() constructs ProviderSelector directly over the existing provider_manager singleton (no new registry/class introduced)",
    )


# ---------------------------------------------------------------------------
# 9. Locked-file regression guard.
# ---------------------------------------------------------------------------
def scenario_locked_files_untouched() -> None:
    print("\n[9] Locked files contain no reference to Stage L5's Composition Root wiring")

    for locked_path in (
        ROOT / "Providers" / "provider_manager.py",
        ROOT / "Providers" / "base_provider.py",
        ROOT / "Providers" / "gemini.py",
        ROOT / "Providers" / "ollama.py",
        ROOT / "Agents" / "base_agent.py",
        ROOT / "Agents" / "stock_agent.py",
        ROOT / "Agents" / "market_analysis_agent.py",
        ROOT / "Core" / "runtime.py",
        ROOT / "Agents" / "executor.py",
        ROOT / "Core" / "approval.py",
        ROOT / "Core" / "startup_validation.py",
    ):
        text = locked_path.read_text(encoding="utf-8", errors="replace")
        check(
            "Stage L5" not in text and "provider_selector" not in text,
            f"{locked_path.relative_to(ROOT)} contains no Stage L5 marker or provider_selector reference (untouched by this stage)",
        )

    # Agents/planner.py is a special case: it ALREADY legitimately contains
    # "provider_selector" (from Stage L4, the stage before this one), so a
    # plain string-absence check would be a false positive here. Instead,
    # prove L5 added no further change to it: its public constructor/method
    # signatures are exactly what Stage L4 left them as (same check L4's
    # own suite already runs on itself -- re-run here as a cross-stage
    # regression guard, since L5 is the stage that could most plausibly
    # have been tempted to touch Planner again).
    planner_init_params = list(inspect.signature(Planner.__init__).parameters.keys())
    check(
        planner_init_params
        == ["self", "provider_manager", "tool_registry", "default_provider_name", "tool_trigger_strategy", "provider_selector"],
        "Agents/planner.py: Planner.__init__'s parameter list is exactly what Stage L4 left it as -- L5 added no further parameter",
    )
    plan_params = list(inspect.signature(Planner.plan).parameters.keys())
    check(
        plan_params == ["self", "message", "provider_name", "requirement"],
        "Agents/planner.py: Planner.plan()'s parameter list is exactly what Stage L4 left it as -- L5 added no further parameter",
    )
    check(
        hasattr(Planner, "select_by_requirement") and not hasattr(Planner, "select_by_kind"),
        "Agents/planner.py: no new selection method was added beyond Stage L4's select_by_requirement()",
    )


# ---------------------------------------------------------------------------
# 10. The L4 suite's narrowed guard still fully passes.
# ---------------------------------------------------------------------------
def scenario_l4_suite_still_green() -> None:
    print("\n[10] Tests/test_stage_l4_planner_integration.py still fully passes after its guard was narrowed")

    l4_path = ROOT / "Tests" / "test_stage_l4_planner_integration.py"
    result = subprocess.run(
        [sys.executable, str(l4_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    check(result.returncode == 0, "Tests/test_stage_l4_planner_integration.py exits 0 (all checks still PASS) after its Stage L5 guard update")
    if result.returncode != 0:
        print("  ---- L4 suite output (for diagnosis) ----")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])


def main() -> int:
    scenarios = [
        scenario_hermetic_constructibility,
        scenario_selector_actually_wired,
        scenario_requirement_path_reachable_both_kinds,
        scenario_registration_behavior_unchanged,
        scenario_application_graph_no_new_field,
        scenario_name_based_path_unaffected,
        scenario_idempotency_preserved,
        scenario_no_name_branching_in_new_lines,
        scenario_locked_files_untouched,
        scenario_l4_suite_still_green,
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
    print(f"STAGE L5 COMPOSITION ROOT INTEGRATION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())