"""
Sprint 4 STEP 6 proof suite -- ExecutionService wiring into
Core.composition_root.

Mirrors ``Tests/test_stage_sprint4_step5_order_lifecycle_service_wiring.py``
in spirit, adapted for a service with two Repository collaborators
(``OrderRepository``/``TradeRepository``) instead of one: this checks
``ExecutionService`` was built over the graph's own
``order_repository``/``trade_repository`` -- the same shared
instances, never second Repository instances -- and (per the STEP 6
spec's explicit "wiring memakai DatabaseManager yang sama" testing
requirement) that both of those repositories, in turn, share the
graph's one ``database_manager``.

This suite proves exactly six things, no more:

  1. ``build_application()`` still builds without raising.
  2. ``graph.execution_service`` is a real, production
     ``Business.execution_service.ExecutionService`` instance -- never
     a test double.
  3. ``graph.execution_service`` was constructed over the *exact same*
     ``OrderRepository``/``TradeRepository`` instances as
     ``graph.order_repository``/``graph.trade_repository`` -- identity
     check (``is``), not just type/equality.
  4. ``ExecutionService`` depends on ``OrderRepository``/
     ``TradeRepository`` only -- it holds no reference to
     ``account_repository``/``position_repository``.
  5. Both repositories behind ``execution_service`` share the exact
     same ``DatabaseManager`` instance as ``graph.database_manager``
     (identity check).
  6. Construction remains hermetic: no connection opened, no I/O.

It deliberately does NOT test ``ExecutionService``'s own execution
behavior (already covered by ``Tests/test_execution_service.py``), and
does NOT apply ``ORDERS_MIGRATIONS``/``TRADES_MIGRATIONS`` --
construction-only, no connection, no I/O.

Run directly:
``python Tests/test_stage_sprint4_step6_execution_service_wiring.py``
-- no external test framework required.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.execution_service import ExecutionService  # noqa: E402
from Core.composition_root import ApplicationGraph, build_application  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402

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
    """build_application() still builds without raising after this addition."""
    graph = build_application(
        provider_name="gemini-sprint4-step6-test",
        agent_name="sprint4-step6-test-agent",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    return graph


def scenario_execution_service_present_and_real(graph: ApplicationGraph) -> None:
    """graph.execution_service is a real, production ExecutionService."""
    check(
        hasattr(graph, "execution_service"),
        "ApplicationGraph exposes an execution_service field",
    )
    check(
        isinstance(graph.execution_service, ExecutionService),
        "graph.execution_service is a real ExecutionService instance (never a test double)",
    )


def scenario_execution_service_shares_repositories(graph: ApplicationGraph) -> None:
    """graph.execution_service was built over the exact same
    OrderRepository/TradeRepository instances as
    graph.order_repository/graph.trade_repository -- identity, not
    just type/equality.
    """
    check(
        isinstance(graph.order_repository, OrderRepository),
        "graph.order_repository is a real OrderRepository instance",
    )
    check(
        isinstance(graph.trade_repository, TradeRepository),
        "graph.trade_repository is a real TradeRepository instance",
    )
    check(
        graph.execution_service._order_repository is graph.order_repository,
        "graph.execution_service shares the exact same OrderRepository "
        "instance as graph.order_repository (identity check)",
    )
    check(
        graph.execution_service._trade_repository is graph.trade_repository,
        "graph.execution_service shares the exact same TradeRepository "
        "instance as graph.trade_repository (identity check)",
    )


def scenario_execution_service_depends_on_order_and_trade_repository_only(
    graph: ApplicationGraph,
) -> None:
    """ExecutionService holds exactly three collaborator attributes as of
    Activation 3.3 STEP 2: _order_repository/_trade_repository/
    _execution_policy -- still no account/position repository reference
    anywhere on the instance. _execution_policy is the canonical
    Business.execution_policy_config.ExecutionPolicy, read once by
    Core.composition_root and shared with graph.paper_trading_engine.
    """
    attrs = sorted(vars(graph.execution_service).keys())
    check(
        attrs == ["_execution_policy", "_order_repository", "_trade_repository"],
        "graph.execution_service holds exactly three collaborator attributes "
        "(_execution_policy, _order_repository, _trade_repository)",
    )


def scenario_execution_service_repositories_share_database_manager(
    graph: ApplicationGraph,
) -> None:
    """Both repositories behind graph.execution_service share the exact
    same DatabaseManager instance as graph.database_manager --
    identity check, per the STEP 6 spec's explicit wiring test
    requirement.
    """
    check(
        isinstance(graph.database_manager, DatabaseManager),
        "graph.database_manager is a real DatabaseManager instance",
    )
    order_repo_shares_manager = (
        graph.execution_service._order_repository._database_manager is graph.database_manager
    )
    check(
        order_repo_shares_manager,
        "execution_service's OrderRepository shares the exact same "
        "DatabaseManager instance as graph.database_manager (identity check)",
    )
    trade_repo_shares_manager = (
        graph.execution_service._trade_repository._database_manager is graph.database_manager
    )
    check(
        trade_repo_shares_manager,
        "execution_service's TradeRepository shares the exact same "
        "DatabaseManager instance as graph.database_manager (identity check)",
    )


def scenario_build_application_is_idempotent() -> None:
    """Calling build_application() twice does not raise, and each call
    still produces its own execution_service sharing that call's own
    order_repository/trade_repository (never leaking across calls).
    """
    graph_a = build_application(
        provider_name="gemini-sprint4-step6-idempotent-a",
        agent_name="sprint4-step6-idempotent-agent-a",
    )
    graph_b = build_application(
        provider_name="gemini-sprint4-step6-idempotent-b",
        agent_name="sprint4-step6-idempotent-agent-b",
    )
    check(
        graph_a.execution_service is not graph_b.execution_service,
        "two build_application() calls produce two distinct ExecutionService instances",
    )
    check(
        graph_a.execution_service._order_repository is graph_a.order_repository
        and graph_a.execution_service._trade_repository is graph_a.trade_repository,
        "first call's execution_service still shares its own call's repositories",
    )
    check(
        graph_b.execution_service._order_repository is graph_b.order_repository
        and graph_b.execution_service._trade_repository is graph_b.trade_repository,
        "second call's execution_service still shares its own call's repositories",
    )
    check(
        graph_a.execution_service._order_repository is not graph_b.execution_service._order_repository,
        "the two calls' OrderRepository instances are not accidentally shared with each other",
    )


def scenario_no_connection_or_io_at_construction(graph: ApplicationGraph) -> None:
    """Construction is hermetic: no connection was opened."""
    check(
        graph.database_manager.is_connected is False,
        "database_manager (and therefore execution_service's underlying "
        "connections) is not connected after build_application() -- "
        "construction remains hermetic, no I/O",
    )


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
        scenario_execution_service_present_and_real,
        scenario_execution_service_shares_repositories,
        scenario_execution_service_depends_on_order_and_trade_repository_only,
        scenario_execution_service_repositories_share_database_manager,
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
    print(f"SPRINT 4 STEP 6 WIRING TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())