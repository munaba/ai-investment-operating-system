"""
Stage L6 proof suite -- Multi-provider Registry.

Scope (per this session's LOCKED design decisions):
  - Core/composition_root.py (additive only):
      * New `_register_all_provider_kinds()`: registers every class in
        `_PROVIDER_CLASSES` under its own canonical name (`"gemini"`,
        `"ollama"`), guarded by the existing `ProviderManager.exists()`
        check -- no `overwrite=True`, no new ProviderManager method.
        Called from `build_application()` right after the existing
        `_build_provider(resolved_provider_name, resolved_provider_kind)`
        call.
      * `ACTIVE_PROVIDER` is re-scoped: it no longer determines *which*
        providers get registered (now unconditional/every kind) -- it
        only determines the *default* provider, i.e.
        `ApplicationGraph.provider_name`/`.provider_kind` and, new in
        this stage, `Planner`'s `default_provider_name`.
      * `Planner(...)` construction gains one additional keyword
        argument: `default_provider_name=resolved_provider_name`. This
        uses a `Planner.__init__` parameter that has existed unchanged
        since Stage L4 -- Agents/planner.py itself is NOT touched.
        Without this, `Planner.select_provider(None)`'s old fallback
        (`registered[0]`, i.e. dict insertion order) would no longer
        reliably mean "the ACTIVE_PROVIDER default" once more than one
        provider is registered -- this line is what keeps that contract
        true.
      * `ApplicationGraph` gains no new field (per this session's
        explicit decision): the full registered set is already
        reachable via `graph.provider_manager.list()`.
  - Tests/test_stage_l5_composition_root_integration.py:
      * scenario_registration_behavior_unchanged (was: "exactly one
        provider registered per call, Option A confirmed") is revised
        to assert what remains true post-L6: both canonical kinds are
        always present, and registration stays idempotent across
        repeated build_application() calls. A before/after set
        difference is no longer valid, because provider_manager is a
        process-wide singleton and "gemini"/"ollama" persist across
        calls once first registered (see note below).
      * scenario_requirement_path_reachable_both_kinds is revised to
        use a discriminating requirement (need_json=True /
        local_only=True) instead of the empty ProviderRequirement() --
        see that scenario's inline comment for why an empty requirement
        is no longer single-candidate under this stage.
  - startup_validation.py: NOT changed. It still validates only the
    active provider kind's env vars -- every provider's connect()
    remains lazy, so a provider that is registered but never selected
    for a real call is never actually used, and therefore never needs
    its credentials validated at startup.

Untouched (proven, not just claimed, below where practical):
  Providers/provider_manager.py, Agents/planner.py,
  Providers/base_provider.py, Providers/gemini.py, Providers/ollama.py,
  Agents/base_agent.py, Agents/stock_agent.py,
  Agents/market_analysis_agent.py, Core/runtime.py, Agents/executor.py,
  Core/approval.py, Core/startup_validation.py.

Important process-lifetime note (documented per this session's decision):
`provider_manager` is a process-wide singleton. Once any test/process
calls `build_application()` a first time, "gemini" and "ollama" remain
registered for the remaining lifetime of that process -- registering
them again is a guarded no-op (`exists()`), not a fresh registration.
Every scenario below therefore asserts *presence* and *idempotency*
(same instance across calls), never a raw `before/after` set difference
on `provider_manager.list()`.

Cakupan skenario:
  1. ACTIVE_PROVIDER="gemini" -> registry contains BOTH "gemini" and
     "ollama"; default (Planner.select_provider() with no name) is
     "gemini".
  2. ACTIVE_PROVIDER="ollama" -> registry still contains BOTH; default
     is now "ollama" -- proving the default follows ACTIVE_PROVIDER,
     not registration order.
  3. ProviderSelector now has two real candidates (not one) reachable
     from the production graph.
  4. Registration is idempotent: calling build_application() twice does
     not duplicate or replace the canonical entries.
  5. No provider-name/isinstance branching was introduced in
     Core/composition_root.py's new lines (targeted regex scan, same
     technique Stage L3/L4/L5 used).
  6. ApplicationGraph.provider_name/.provider_kind still track
     ACTIVE_PROVIDER (the default), and ApplicationGraph gained no new
     field.
  7. Stage 9.0's explicit-provider_name contract still holds: passing
     provider_name="gemini-stage9-0-test" (no provider_kind) still
     builds a GeminiProvider under that exact custom key, unaffected by
     the new unconditional canonical registration.

All checks are hermetic: no network call, no API key, no external
package required.
"""

from __future__ import annotations

import inspect
import os
import re
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from Agents.agent_registry import agent_registry
from Agents.planner import Planner
from Core.composition_root import ApplicationGraph, build_application
import Core.composition_root as composition_root_module
from Providers import GeminiProvider, OllamaProvider, ProviderRequirement, provider_manager
from Core.config import config

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
    for name in names:
        if provider_manager.exists(name):
            provider_manager.unregister(name)


def _clear_agent(name: str) -> None:
    if agent_registry.exists(name):
        agent_registry.unregister(name)


def _with_active_provider(value: str):
    """Context manager: temporarily set/clear ACTIVE_PROVIDER via env,
    restoring whatever was there before on exit. Uses the same
    `Core.config.config`/env-var mechanism `build_application()` itself
    reads (`config.get("ACTIVE_PROVIDER", ...)`), not a private hook.
    """

    class _Ctx:
        def __enter__(self_inner):
            self_inner._had = "ACTIVE_PROVIDER" in os.environ
            self_inner._prev = os.environ.get("ACTIVE_PROVIDER")
            os.environ["ACTIVE_PROVIDER"] = value
            return self_inner

        def __exit__(self_inner, exc_type, exc, tb):
            if self_inner._had:
                os.environ["ACTIVE_PROVIDER"] = self_inner._prev
            else:
                os.environ.pop("ACTIVE_PROVIDER", None)

    return _Ctx()


# ---------------------------------------------------------------------------
# 1. ACTIVE_PROVIDER="gemini" -> both registered, default is gemini.
# ---------------------------------------------------------------------------
def scenario_active_provider_gemini_default() -> None:
    print("\n[1] ACTIVE_PROVIDER='gemini' -- both kinds registered, default follows ACTIVE_PROVIDER")

    _clear_agent("l6_gemini_default_agent")
    try:
        with _with_active_provider("gemini"):
            graph = build_application(agent_name="l6_gemini_default_agent")
        check(
            graph.provider_manager.exists("gemini") and graph.provider_manager.exists("ollama"),
            "registry contains both 'gemini' and 'ollama' when ACTIVE_PROVIDER='gemini'",
        )
        check(
            graph.provider_name == "gemini" and graph.provider_kind == "gemini",
            f"ApplicationGraph.provider_name/.provider_kind == 'gemini' (got provider_name={graph.provider_name!r}, provider_kind={graph.provider_kind!r})",
        )
        check(
            graph.planner.select_provider().name == "gemini",
            f"planner.select_provider() (no explicit name) resolves to the 'gemini' provider (got name={graph.planner.select_provider().name!r})",
        )
        check(
            isinstance(graph.planner.select_provider(), GeminiProvider),
            "planner.select_provider() (no explicit name) is a GeminiProvider instance",
        )
    finally:
        _clear_agent("l6_gemini_default_agent")


# ---------------------------------------------------------------------------
# 2. ACTIVE_PROVIDER="ollama" -> both still registered, default is ollama.
# ---------------------------------------------------------------------------
def scenario_active_provider_ollama_default() -> None:
    print("\n[2] ACTIVE_PROVIDER='ollama' -- both kinds still registered, default follows ACTIVE_PROVIDER")

    _clear_agent("l6_ollama_default_agent")
    try:
        with _with_active_provider("ollama"):
            graph = build_application(agent_name="l6_ollama_default_agent")
        check(
            graph.provider_manager.exists("gemini") and graph.provider_manager.exists("ollama"),
            "registry still contains both 'gemini' and 'ollama' when ACTIVE_PROVIDER='ollama'",
        )
        check(
            graph.provider_name == "ollama" and graph.provider_kind == "ollama",
            f"ApplicationGraph.provider_name/.provider_kind == 'ollama' (got provider_name={graph.provider_name!r}, provider_kind={graph.provider_kind!r})",
        )
        check(
            graph.planner.select_provider().name == "ollama",
            f"planner.select_provider() (no explicit name) resolves to the 'ollama' provider (got name={graph.planner.select_provider().name!r})",
        )
        check(
            isinstance(graph.planner.select_provider(), OllamaProvider),
            "planner.select_provider() (no explicit name) is an OllamaProvider instance",
        )
        check(
            not isinstance(graph.planner.select_provider(), GeminiProvider),
            "the default is NOT GeminiProvider -- proving default follows ACTIVE_PROVIDER, not dict/registration order "
            "(Gemini would otherwise win any capability-based tie-break, and was very likely registered first in this process)",
        )
    finally:
        _clear_agent("l6_ollama_default_agent")


# ---------------------------------------------------------------------------
# 3. ProviderSelector now sees two real candidates.
# ---------------------------------------------------------------------------
def scenario_selector_has_two_real_candidates() -> None:
    print("\n[3] ProviderSelector has two real candidates through the production graph (not one)")

    _clear_agent("l6_two_candidates_agent")
    try:
        with _with_active_provider("gemini"):
            graph = build_application(agent_name="l6_two_candidates_agent")
        selector = graph.planner._provider_selector  # noqa: SLF001 -- white-box proof, test-only
        candidates = selector.candidates(ProviderRequirement())
        candidate_names = sorted(c.name for c in candidates)
        check(
            len(candidates) == 2,
            f"ProviderSelector.candidates(ProviderRequirement()) returns exactly 2 candidates through the production graph (got {len(candidates)}: {candidate_names})",
        )
        check(
            candidate_names == ["gemini", "ollama"],
            f"the two candidates are 'gemini' and 'ollama' (got {candidate_names})",
        )
        gemini_only = selector.candidates(ProviderRequirement(need_json=True))
        check(
            len(gemini_only) == 1 and isinstance(gemini_only[0], GeminiProvider),
            "a discriminating requirement (need_json=True) narrows candidates down to exactly Gemini",
        )
        ollama_only = selector.candidates(ProviderRequirement(local_only=True))
        check(
            len(ollama_only) == 1 and isinstance(ollama_only[0], OllamaProvider),
            "a discriminating requirement (local_only=True) narrows candidates down to exactly Ollama",
        )
    finally:
        _clear_agent("l6_two_candidates_agent")


# ---------------------------------------------------------------------------
# 4. Registration is idempotent across repeated calls.
# ---------------------------------------------------------------------------
def scenario_registration_idempotent() -> None:
    print("\n[4] Registration stays idempotent across repeated build_application() calls")

    _clear_agent("l6_idempotent_agent_1")
    _clear_agent("l6_idempotent_agent_2")
    try:
        graph1 = build_application(agent_name="l6_idempotent_agent_1")
        gemini_instance = graph1.provider_manager.get("gemini")
        ollama_instance = graph1.provider_manager.get("ollama")

        raised = False
        graph2 = None
        try:
            graph2 = build_application(agent_name="l6_idempotent_agent_2")
        except Exception:
            raised = True
        check(raised is False, "calling build_application() again does not raise")
        if graph2 is not None:
            check(
                graph2.provider_manager.get("gemini") is gemini_instance,
                "the second call's 'gemini' entry is the SAME instance as the first call's (no duplicate construction)",
            )
            check(
                graph2.provider_manager.get("ollama") is ollama_instance,
                "the second call's 'ollama' entry is the SAME instance as the first call's (no duplicate construction)",
            )
    finally:
        _clear_agent("l6_idempotent_agent_1")
        _clear_agent("l6_idempotent_agent_2")


# ---------------------------------------------------------------------------
# 5. No provider-name/isinstance branching introduced.
# ---------------------------------------------------------------------------
def scenario_no_name_branching() -> None:
    print("\n[5] No provider-name/isinstance branching introduced by Stage L6's diff")

    new_fn_source = inspect.getsource(composition_root_module._register_all_provider_kinds)  # noqa: SLF001
    build_app_source = inspect.getsource(composition_root_module.build_application)

    forbidden_patterns = [
        r'kind\s*==\s*"',
        r'==\s*"gemini"',
        r'==\s*"ollama"',
        r"isinstance\([^)]*,\s*(GeminiProvider|OllamaProvider)\)",
    ]
    for pattern in forbidden_patterns:
        check(
            re.search(pattern, new_fn_source) is None,
            f"_register_all_provider_kinds() source does not contain forbidden pattern: {pattern}",
        )
    for pattern in forbidden_patterns:
        check(
            re.search(pattern, build_app_source) is None,
            f"build_application() source does not contain forbidden pattern: {pattern}",
        )
    check(
        "_PROVIDER_CLASSES.items()" in new_fn_source,
        "_register_all_provider_kinds() dispatches purely through the existing _PROVIDER_CLASSES dict (polymorphic, no branching)",
    )
    check(
        "default_provider_name=resolved_provider_name" in build_app_source,
        "build_application() passes default_provider_name=resolved_provider_name into Planner(...)",
    )


# ---------------------------------------------------------------------------
# 6. ApplicationGraph tracks ACTIVE_PROVIDER as default; no new field --
#    true as of Stage L6 itself.
#
# Stage L11 addition (additive only, approved explicitly -- same pattern
# used to update Tests/test_stage_l5_composition_root_integration.py's
# equivalent guard, see that file's inline comment): ApplicationGraph now
# also carries `runtime_analysis_pipeline`, added by Stage L11 ("Runtime
# sebagai Execution Kernel"). Updated to include that one new field; what
# this scenario continues to prove is unchanged -- no *other* field was
# added or reordered by any stage between L6 and L11.
#
# Stage L13 addition (additive only, approved Diff-Level Plan FINAL, same
# narrowing pattern as the L11 update immediately above, and the same
# update made to Tests/test_stage_l5_composition_root_integration.py's
# equivalent guard): ApplicationGraph now also carries `service_skills`,
# added by Stage L13 ("Granular Skills") as its last field, right after
# `runtime_analysis_pipeline`.
# ---------------------------------------------------------------------------
def scenario_application_graph_still_default_only() -> None:
    print("\n[6] ApplicationGraph.provider_name/.provider_kind still mean 'default provider'; only Stage L11's and L13's fields added")

    fields = list(ApplicationGraph.__dataclass_fields__.keys())
    check(
        fields
        == [
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
        ],
        f"ApplicationGraph field set is the pre-L6 set + Stage L11's runtime_analysis_pipeline + Stage L13's service_skills + Stage L15's goal_planner + Task 1A's observation_recorder/memory_store/memory_recorder/reflector (got {fields})",
    )

    _clear_agent("l6_graph_field_agent")
    try:
        with _with_active_provider("ollama"):
            graph = build_application(agent_name="l6_graph_field_agent")
        check(
            graph.provider_name == "ollama",
            "graph.provider_name reflects ACTIVE_PROVIDER (the default), not the full registered set",
        )
        check(
            set(graph.provider_manager.list()) >= {"gemini", "ollama"},
            "the full registered set is reachable via graph.provider_manager.list(), not duplicated onto the graph",
        )
    finally:
        _clear_agent("l6_graph_field_agent")


# ---------------------------------------------------------------------------
# 7. Stage 9.0's explicit provider_name contract still holds.
# ---------------------------------------------------------------------------
def scenario_stage9_0_explicit_name_unaffected() -> None:
    print("\n[7] Stage 9.0's explicit provider_name contract unaffected by unconditional canonical registration")

    _clear_registrations("gemini-l6-stage9-0-check")
    _clear_agent("l6_stage9_0_check_agent")
    try:
        graph = build_application(
            provider_name="gemini-l6-stage9-0-check", agent_name="l6_stage9_0_check_agent"
        )
        provider = graph.provider_manager.get(graph.provider_name)
        check(
            isinstance(provider, GeminiProvider),
            "explicit provider_name (no provider_kind) still builds a GeminiProvider under that exact custom key",
        )
        check(
            graph.provider_name == "gemini-l6-stage9-0-check",
            "graph.provider_name is still the exact custom key that was passed in, not overridden by canonical registration",
        )
        check(
            graph.provider_manager.exists("gemini") and graph.provider_manager.exists("ollama"),
            "the canonical 'gemini'/'ollama' entries are ALSO present alongside the custom-named one",
        )
    finally:
        _clear_registrations("gemini-l6-stage9-0-check")
        _clear_agent("l6_stage9_0_check_agent")


def main() -> int:
    scenarios = [
        scenario_active_provider_gemini_default,
        scenario_active_provider_ollama_default,
        scenario_selector_has_two_real_candidates,
        scenario_registration_idempotent,
        scenario_no_name_branching,
        scenario_application_graph_still_default_only,
        scenario_stage9_0_explicit_name_unaffected,
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
    print(f"STAGE L6 MULTI-PROVIDER REGISTRY RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for failure in _FAILURES:
            print(f"  - {failure}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())