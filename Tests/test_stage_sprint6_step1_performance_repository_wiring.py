"""
Sprint 6 STEP 1 proof suite -- PerformanceRepository wiring into
Core.composition_root.

Mirrors ``Tests/test_stage_sprint5_step3_snapshot_repository_wiring.py``
exactly, for ``performance_repository`` instead of
``snapshot_repository``. Scope: this only makes
``ApplicationGraph.performance_repository`` reachable from the
production object graph, over the graph's own ``database_manager`` --
the exact same shared instance as ``account_repository``/
``position_repository``/``order_repository``/``trade_repository``/
``snapshot_repository``, so that
``BasePersistenceRepository._session()``'s transaction nesting
(SAVEPOINT-based) spans all six once a later STEP needs it.

This suite proves exactly five things, no more:

  1. ``build_application()`` still builds without raising.
  2. ``graph.performance_repository`` is a real, production
     ``Repository.persistence.performance_repository.PerformanceRepository``
     instance -- never a test double.
  3. ``graph.performance_repository`` was constructed over the *exact
     same* ``DatabaseManager`` instance as ``graph.database_manager``,
     ``graph.account_repository``, ``graph.position_repository``,
     ``graph.order_repository``, ``graph.trade_repository``, AND
     ``graph.snapshot_repository`` -- identity check (``is``), not
     just type/equality.
  4. Construction remains hermetic: no connection opened, no I/O.
  5. None of the pre-existing repositories (account/position/order/
     trade/snapshot) changed shape as a result of this addition.

It deliberately does NOT test PerformanceRepository's own query
behavior (already covered by
``Tests/test_performance_repository.py``), and does NOT apply any
migration -- construction-only, no connection, no I/O.

Run directly:
``python Tests/test_stage_sprint6_step1_performance_repository_wiring.py``
-- no external test framework required.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.composition_root import ApplicationGraph, build_application  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.performance_repository import PerformanceRepository  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.snapshot_repository import SnapshotRepository  # noqa: E402
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
        provider_name="gemini-sprint6-step1-test",
        agent_name="sprint6-step1-test-agent",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    return graph


def scenario_performance_repository_present_and_real(graph: ApplicationGraph) -> None:
    """graph.performance_repository is a real, production PerformanceRepository."""
    check(
        hasattr(graph, "performance_repository"),
        "ApplicationGraph exposes a performance_repository field",
    )
    check(
        isinstance(graph.performance_repository, PerformanceRepository),
        "graph.performance_repository is a real PerformanceRepository instance (never a test double)",
    )


def scenario_performance_repository_shares_database_manager(graph: ApplicationGraph) -> None:
    """graph.performance_repository was built over the exact same DatabaseManager
    as graph.database_manager, graph.account_repository,
    graph.position_repository, graph.order_repository,
    graph.trade_repository, AND graph.snapshot_repository -- identity,
    not just type/equality.
    """
    check(
        isinstance(graph.database_manager, DatabaseManager),
        "graph.database_manager is a real DatabaseManager instance",
    )
    same_as_manager = graph.performance_repository._database_manager is graph.database_manager
    check(
        same_as_manager,
        "graph.performance_repository shares the exact same DatabaseManager "
        "instance as graph.database_manager (identity check)",
    )
    same_as_account_repository = (
        graph.performance_repository._database_manager is graph.account_repository._database_manager
    )
    check(
        same_as_account_repository,
        "graph.performance_repository shares the exact same DatabaseManager "
        "instance as graph.account_repository (identity check)",
    )
    same_as_position_repository = (
        graph.performance_repository._database_manager is graph.position_repository._database_manager
    )
    check(
        same_as_position_repository,
        "graph.performance_repository shares the exact same DatabaseManager "
        "instance as graph.position_repository (identity check)",
    )
    same_as_order_repository = (
        graph.performance_repository._database_manager is graph.order_repository._database_manager
    )
    check(
        same_as_order_repository,
        "graph.performance_repository shares the exact same DatabaseManager "
        "instance as graph.order_repository (identity check)",
    )
    same_as_trade_repository = (
        graph.performance_repository._database_manager is graph.trade_repository._database_manager
    )
    check(
        same_as_trade_repository,
        "graph.performance_repository shares the exact same DatabaseManager "
        "instance as graph.trade_repository (identity check)",
    )
    same_as_snapshot_repository = (
        graph.performance_repository._database_manager is graph.snapshot_repository._database_manager
    )
    check(
        same_as_snapshot_repository,
        "graph.performance_repository shares the exact same DatabaseManager "
        "instance as graph.snapshot_repository (identity check)",
    )


def scenario_pre_existing_repositories_unchanged(graph: ApplicationGraph) -> None:
    """The five pre-existing repositories are still present, still real,
    and still their own concrete types -- this STEP did not touch or
    replace any of them.
    """
    check(
        isinstance(graph.account_repository, AccountRepository),
        "graph.account_repository is still a real AccountRepository (unchanged)",
    )
    check(
        isinstance(graph.position_repository, PositionRepository),
        "graph.position_repository is still a real PositionRepository (unchanged)",
    )
    check(
        isinstance(graph.order_repository, OrderRepository),
        "graph.order_repository is still a real OrderRepository (unchanged)",
    )
    check(
        isinstance(graph.trade_repository, TradeRepository),
        "graph.trade_repository is still a real TradeRepository (unchanged)",
    )
    check(
        isinstance(graph.snapshot_repository, SnapshotRepository),
        "graph.snapshot_repository is still a real SnapshotRepository (unchanged)",
    )


def scenario_build_application_is_idempotent() -> None:
    """Calling build_application() twice does not raise, and each call
    still produces its own performance_repository sharing that call's
    own database_manager (never leaking across calls).
    """
    graph_a = build_application(
        provider_name="gemini-sprint6-step1-idempotent-a",
        agent_name="sprint6-step1-idempotent-agent-a",
    )
    graph_b = build_application(
        provider_name="gemini-sprint6-step1-idempotent-b",
        agent_name="sprint6-step1-idempotent-agent-b",
    )
    check(
        graph_a.performance_repository is not graph_b.performance_repository,
        "two build_application() calls produce two distinct PerformanceRepository instances",
    )
    check(
        graph_a.performance_repository._database_manager is graph_a.database_manager,
        "first call's performance_repository still shares its own call's database_manager",
    )
    check(
        graph_b.performance_repository._database_manager is graph_b.database_manager,
        "second call's performance_repository still shares its own call's database_manager",
    )
    check(
        graph_a.performance_repository._database_manager
        is not graph_b.performance_repository._database_manager,
        "the two calls' database_manager instances are not accidentally shared with each other",
    )


def scenario_no_connection_or_io_at_construction(graph: ApplicationGraph) -> None:
    """Construction is hermetic: no connection was opened."""
    check(
        graph.database_manager.is_connected is False,
        "database_manager (and therefore performance_repository's backing "
        "connection) is not connected after build_application() -- "
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
        scenario_performance_repository_present_and_real,
        scenario_performance_repository_shares_database_manager,
        scenario_pre_existing_repositories_unchanged,
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
    print(f"SPRINT 6 STEP 1 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())