"""Activation 5.6 wiring proof -- TradeHoldingPeriodEngine /
TradeAttributionEngine / TradeAttributionService into
Core.composition_root.

Mirrors ``Tests/test_stage_sprint5_step3_snapshot_repository_wiring.py``'s
construction-only, no-I/O pattern, applied to the three Activation 5.6
additions.

This suite proves exactly:

  1. ``build_application()`` still builds without raising.
  2. ``graph.trade_holding_period_engine`` is a real
     ``TradeHoldingPeriodEngine`` instance.
  3. ``graph.trade_attribution_engine`` is a real
     ``TradeAttributionEngine`` instance, built over the graph's own
     ``decision_policy`` -- identity check, never a second/new
     risk-mapping component.
  4. ``graph.trade_attribution_service`` is a real
     ``TradeAttributionService`` instance, built over the graph's own
     ``account_repository``/``trade_repository``/``order_repository``/
     ``snapshot_repository``/``trade_attribution_engine``/
     ``trade_holding_period_engine`` -- identity checks throughout,
     never second instances.
  5. Construction remains hermetic: no connection opened, no I/O.
  6. Calling ``build_application()`` twice produces two fully
     independent object graphs (no shared mutable global state).

It deliberately does NOT test any engine's/service's own business
behavior (already covered by
``Tests/test_trade_holding_period_engine.py``,
``Tests/test_trade_attribution_engine.py``, and
``Tests/test_trade_attribution_service.py``) and does NOT apply any
migration or open a connection -- construction-only.

Run directly: ``python Tests/test_activation5_6_wiring.py`` -- no
external test framework required.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.trade_attribution_engine import TradeAttributionEngine  # noqa: E402
from Business.trade_attribution_service import TradeAttributionService  # noqa: E402
from Business.trade_holding_period_engine import TradeHoldingPeriodEngine  # noqa: E402
from Core.composition_root import ApplicationGraph, build_application  # noqa: E402
from Orchestration.decision_policy import DecisionPolicy  # noqa: E402

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


def scenario_graph_builds_without_raising() -> ApplicationGraph:
    graph = build_application(
        provider_name="gemini-activation5-6-test",
        agent_name="activation5-6-test-agent",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    return graph


def scenario_trade_holding_period_engine_present_and_real(graph: ApplicationGraph) -> None:
    check(hasattr(graph, "trade_holding_period_engine"), "ApplicationGraph exposes a trade_holding_period_engine field")
    check(isinstance(graph.trade_holding_period_engine, TradeHoldingPeriodEngine), "graph.trade_holding_period_engine is a real TradeHoldingPeriodEngine instance")


def scenario_trade_attribution_engine_present_and_shares_decision_policy(graph: ApplicationGraph) -> None:
    check(hasattr(graph, "trade_attribution_engine"), "ApplicationGraph exposes a trade_attribution_engine field")
    check(isinstance(graph.trade_attribution_engine, TradeAttributionEngine), "graph.trade_attribution_engine is a real TradeAttributionEngine instance")
    check(hasattr(graph, "decision_policy") and isinstance(graph.decision_policy, DecisionPolicy), "graph.decision_policy is a real, existing DecisionPolicy instance")
    check(
        graph.trade_attribution_engine._decision_policy is graph.decision_policy,
        "graph.trade_attribution_engine reuses the EXACT SAME graph.decision_policy instance (identity check) -- never a second/new risk-mapping component",
    )


def scenario_trade_attribution_service_present_and_shares_collaborators(graph: ApplicationGraph) -> None:
    check(hasattr(graph, "trade_attribution_service"), "ApplicationGraph exposes a trade_attribution_service field")
    check(isinstance(graph.trade_attribution_service, TradeAttributionService), "graph.trade_attribution_service is a real TradeAttributionService instance")

    service = graph.trade_attribution_service
    check(service._account_repository is graph.account_repository, "trade_attribution_service reuses the exact same graph.account_repository instance (identity check)")
    check(service._trade_repository is graph.trade_repository, "trade_attribution_service reuses the exact same graph.trade_repository instance (identity check)")
    check(service._order_repository is graph.order_repository, "trade_attribution_service reuses the exact same graph.order_repository instance (identity check)")
    check(service._snapshot_repository is graph.snapshot_repository, "trade_attribution_service reuses the exact same graph.snapshot_repository instance (identity check)")
    check(service._trade_attribution_engine is graph.trade_attribution_engine, "trade_attribution_service reuses the exact same graph.trade_attribution_engine instance (identity check)")
    check(service._trade_holding_period_engine is graph.trade_holding_period_engine, "trade_attribution_service reuses the exact same graph.trade_holding_period_engine instance (identity check)")


def scenario_no_connection_or_io_at_construction(graph: ApplicationGraph) -> None:
    check(
        graph.database_manager.is_connected is False,
        "database_manager is not connected after build_application() -- construction remains hermetic, no I/O for the 5.6 additions either",
    )


def scenario_build_application_is_idempotent() -> None:
    graph_a = build_application(provider_name="gemini-activation5-6-test", agent_name="activation5-6-test-agent-a")
    graph_b = build_application(provider_name="gemini-activation5-6-test", agent_name="activation5-6-test-agent-b")
    check(graph_a.trade_attribution_service is not graph_b.trade_attribution_service, "two build_application() calls produce two INDEPENDENT trade_attribution_service instances")
    check(graph_a.trade_attribution_engine is not graph_b.trade_attribution_engine, "two build_application() calls produce two INDEPENDENT trade_attribution_engine instances")
    check(graph_a.trade_holding_period_engine is not graph_b.trade_holding_period_engine, "two build_application() calls produce two INDEPENDENT trade_holding_period_engine instances")


def main() -> int:
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

    scenarios_needing_graph = [
        scenario_trade_holding_period_engine_present_and_real,
        scenario_trade_attribution_engine_present_and_shares_decision_policy,
        scenario_trade_attribution_service_present_and_shares_collaborators,
        scenario_no_connection_or_io_at_construction,
    ]
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

    print(f"\n{scenario_build_application_is_idempotent.__name__}")
    try:
        scenario_build_application_is_idempotent()
    except Exception:  # noqa: BLE001
        _FAIL += 1
        _FAILURES.append("scenario_build_application_is_idempotent raised an unexpected exception")
        print("  ERROR - scenario_build_application_is_idempotent raised an unexpected exception:")
        traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 5.6 WIRING TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())