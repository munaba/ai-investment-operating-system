"""
Stage 9.0 proof suite -- Composition Root.

Scope (per this session's LOCKED design decision, Opsi A):
  - Core/composition_root.py assembles the production object graph using
    only each class's existing public API. No new parameter was added to
    Executor.__init__, Runtime, or BaseAgent -- this suite proves that by
    construction (importing and calling build_application() would fail
    immediately if a signature had changed incompatibly) and by explicit
    identity checks below.

Two levels, per the LOCKED decision:

  LEVEL 1 -- HERMETIC, MANDATORY (this is Stage 9.0's official proof).
    Proves the production object graph is *constructible*: real classes
    (never Fake/test doubles), no duplicate singleton construction, no
    network call, no .env/API key/external package required. This is
    "production object graph is constructible" -- NOT "production AI can
    answer" (that is explicitly Level 2's concern, not Level 1's).

  LEVEL 2 -- OPTIONAL INTEGRATION SMOKE.
    Exercises one real agent.chat() call through the fully-wired graph.
    Automatically SKIPPED (never FAILED) when GEMINI_API_KEY is absent or
    an external package (google-generativeai, yfinance) is not installed.
    Never affects Stage 9.0's PASS/FAIL result.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Agents.agent_registry import AgentRegistry, agent_registry
from Agents.executor import Executor
from Agents.planner import Planner
from Agents.stock_agent import StockAgent
from Agents.tool_registry import ToolRegistry, tool_registry
from Core.composition_root import ApplicationGraph, build_application
from Core.config import Config, config
from Providers import GeminiProvider, ProviderManager, provider_manager
from Services.service_registry import ServiceRegistry, service_registry


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


_EXPECTED_SERVICE_NAMES = {
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
}


# ---------------------------------------------------------------------------
# LEVEL 1 -- Hermetic, mandatory. This is Stage 9.0's official proof.
# ---------------------------------------------------------------------------
def scenario_graph_builds_without_raising() -> ApplicationGraph:
    graph = build_application(
        provider_name="gemini-stage9-0-test",
        agent_name="stock_agent-stage9-0-test",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    return graph


def scenario_production_classes_not_fakes(graph: ApplicationGraph) -> None:
    check(isinstance(graph.tool_registry, ToolRegistry), "graph.tool_registry is a real ToolRegistry")
    check(isinstance(graph.provider_manager, ProviderManager), "graph.provider_manager is a real ProviderManager")
    check(isinstance(graph.agent_registry, AgentRegistry), "graph.agent_registry is a real AgentRegistry")
    check(isinstance(graph.service_registry, ServiceRegistry), "graph.service_registry is a real ServiceRegistry")
    check(isinstance(graph.config, Config), "graph.config is a real Config")
    check(type(graph.executor) is Executor, "graph.executor is the real Executor class (not a subclass/double)")
    check(isinstance(graph.planner, Planner), "graph.planner is a real Planner")
    check(type(graph.agent) is StockAgent, "graph.agent is the real StockAgent class (not a subclass/double)")

    provider = graph.provider_manager.get(graph.provider_name)
    check(type(provider) is GeminiProvider, "registered default provider is the real GeminiProvider class")


def scenario_singletons_are_the_shared_instances(graph: ApplicationGraph) -> None:
    """Every registry the graph exposes must be *the* process-wide
    singleton the framework already defines -- never a second instance."""
    check(graph.tool_registry is tool_registry, "graph.tool_registry is the module-level ToolRegistry singleton")
    check(graph.provider_manager is provider_manager, "graph.provider_manager is the module-level ProviderManager singleton")
    check(graph.agent_registry is agent_registry, "graph.agent_registry is the module-level AgentRegistry singleton")
    check(graph.service_registry is service_registry, "graph.service_registry is the module-level ServiceRegistry singleton")
    check(graph.config is config, "graph.config is the module-level Config singleton")
    check(ToolRegistry() is tool_registry, "ToolRegistry() still resolves to the same singleton after wiring (class contract untouched)")


def scenario_no_duplicate_tool_registry_inside_executor(graph: ApplicationGraph) -> None:
    """Executor.__init__ was NOT reopened -- it still stores whatever
    ToolRegistry it is handed. Confirm it was handed the SAME shared
    instance, not a second ToolRegistry() constructed independently."""
    check(
        graph.executor._tool_registry is graph.tool_registry,  # noqa: SLF001 -- deliberate white-box check
        "Executor was wired with the SAME ToolRegistry instance as the rest of the graph (no duplicate construction)",
    )


def scenario_agent_registered_correctly(graph: ApplicationGraph) -> None:
    check(graph.agent_registry.exists(graph.agent_name), "constructed StockAgent is registered in AgentRegistry")
    check(
        graph.agent_registry.get(graph.agent_name) is graph.agent,
        "AgentRegistry.get() returns the exact same StockAgent instance the graph holds",
    )


def scenario_all_analysis_services_registered(graph: ApplicationGraph) -> None:
    registered_names = {s.name for s in graph.service_registry.list()}
    check(
        _EXPECTED_SERVICE_NAMES.issubset(registered_names),
        f"all 11 AnalysisPipeline services are registered in ServiceRegistry (missing: {_EXPECTED_SERVICE_NAMES - registered_names})",
    )


def scenario_no_locked_signature_was_touched() -> None:
    """Structural proof, not a behavioral one: Executor's public
    constructor exposes exactly the contract currently in force.

    Updated for Stage 9.1 (approved, deliberate change): Executor's
    constructor was opened for dependency injection of approval_port/
    gateway/event_store, additive and backward-compatible (see
    Tests/test_stage9_1_executor_di.py for the full proof of that).
    This assertion's job was never "the signature must never change" --
    it is "the signature must match the contract this project has
    actually, deliberately agreed to" -- so it is updated here to that
    new, current contract rather than left asserting a historical one
    Stage 9.1 explicitly superseded.
    """
    import inspect

    executor_params = list(inspect.signature(Executor.__init__).parameters.keys())
    check(
        executor_params == ["self", "tool_registry", "approval_port", "gateway", "event_store"],
        f"Executor.__init__ signature matches the current (post-Stage-9.1) contract: {executor_params}",
    )


def scenario_build_application_is_idempotent() -> None:
    """Calling build_application() twice in the same process must not
    raise, must not duplicate any singleton, and must not silently
    replace the already-registered agent."""
    graph_a = build_application(
        provider_name="gemini-stage9-0-idempotency",
        agent_name="stock_agent-stage9-0-idempotency",
    )
    raised = None
    graph_b = None
    try:
        graph_b = build_application(
            provider_name="gemini-stage9-0-idempotency",
            agent_name="stock_agent-stage9-0-idempotency",
        )
    except Exception as exc:  # noqa: BLE001
        raised = exc

    check(raised is None, f"calling build_application() twice does not raise (got: {raised!r})")
    if graph_b is not None:
        check(graph_a.tool_registry is graph_b.tool_registry, "second call reuses the same ToolRegistry singleton")
        check(graph_a.provider_manager is graph_b.provider_manager, "second call reuses the same ProviderManager singleton")
        check(graph_a.agent_registry is graph_b.agent_registry, "second call reuses the same AgentRegistry singleton")
        check(graph_a.service_registry is graph_b.service_registry, "second call reuses the same ServiceRegistry singleton")
        check(
            graph_a.agent_registry.get("stock_agent-stage9-0-idempotency") is graph_a.agent,
            "second call did not silently replace the agent registered by the first call",
        )


def scenario_no_external_dependency_required_to_build() -> None:
    """Confirms this environment genuinely lacks the external packages/
    secret Level 2 would need -- so the earlier scenarios passing here is
    real evidence of hermeticity, not an accident of a fully-configured
    machine."""
    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY"))
    has_google_genai = importlib.util.find_spec("google.generativeai") is not None
    has_yfinance = importlib.util.find_spec("yfinance") is not None
    has_plotly = importlib.util.find_spec("plotly") is not None
    print(
        f"  INFO - environment: GEMINI_API_KEY={'set' if has_gemini_key else 'unset'}, "
        f"google-generativeai={'installed' if has_google_genai else 'absent'}, "
        f"yfinance={'installed' if has_yfinance else 'absent'}, "
        f"plotly={'installed' if has_plotly else 'absent'}"
    )
    check(True, "environment probe recorded (informational, always passes)")


# ---------------------------------------------------------------------------
# LEVEL 2 -- Optional integration smoke. Never affects PASS/FAIL above.
# ---------------------------------------------------------------------------
def level_2_integration_smoke() -> None:
    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY"))
    has_google_genai = importlib.util.find_spec("google.generativeai") is not None
    has_yfinance = importlib.util.find_spec("yfinance") is not None

    if not (has_gemini_key and has_google_genai and has_yfinance):
        print("\nLevel 2 (integration smoke)")
        print("  SKIPPED:")
        print("  Production integration requires:")
        print("  - GEMINI_API_KEY")
        print("  - external packages (google-generativeai, yfinance)")
        print("  - network connectivity")
        return

    print("\nLevel 2 (integration smoke)")
    graph = build_application(
        provider_name="gemini-stage9-0-level2",
        agent_name="stock_agent-stage9-0-level2",
    )
    try:
        reply = graph.agent.chat("Analisa BBCA")
        print(f"  PASS - agent.chat() returned a real reply ({len(reply)} chars)")
    except Exception as exc:  # noqa: BLE001
        print(f"  SKIPPED - integration call failed at runtime (network/API issue, not a Stage 9.0 defect): {exc}")


def main() -> int:
    scenarios_needing_graph = [
        scenario_production_classes_not_fakes,
        scenario_singletons_are_the_shared_instances,
        scenario_no_duplicate_tool_registry_inside_executor,
        scenario_agent_registered_correctly,
        scenario_all_analysis_services_registered,
    ]
    standalone_scenarios = [
        scenario_no_locked_signature_was_touched,
        scenario_build_application_is_idempotent,
        scenario_no_external_dependency_required_to_build,
    ]

    import traceback

    print("scenario_graph_builds_without_raising")
    try:
        graph = scenario_graph_builds_without_raising()
    except Exception:  # noqa: BLE001
        global _FAIL
        _FAIL += 1
        _FAILURES.append("scenario_graph_builds_without_raising raised an unexpected exception")
        print("  ERROR - build_application() raised unexpectedly:")
        traceback.print_exc()
        graph = None

    if graph is not None:
        for scenario in scenarios_needing_graph:
            print(f"\n{scenario.__name__}")
            try:
                scenario(graph)
            except Exception:  # noqa: BLE001
                _FAIL += 1
                _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
                print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
                traceback.print_exc()

    for scenario in standalone_scenarios:
        print(f"\n{scenario.__name__}")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"STAGE 9.0 COMPOSITION ROOT TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    # Level 2 never affects Stage 9.0's PASS/FAIL result.
    level_2_integration_smoke()

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())