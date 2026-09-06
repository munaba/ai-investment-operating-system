"""
Sprint 5 STEP 6 proof suite -- ManualScanService wiring into
Core.composition_root.

Mirrors ``Tests/test_stage_sprint4_step9_paper_trading_engine_wiring.py``
in spirit, adapted for ``ManualScanService``: this checks
``ManualScanService`` was built over the graph's own
``watchlist_repository``/``market_analysis_agent``/``snapshot_repository``
-- the same shared instances, never second instances.

This suite proves:

  1. ``build_application()`` still builds without raising.
  2. ``graph.manual_scan_service`` is a real, production
     ``Business.manual_scan_service.ManualScanService`` instance --
     never a test double.
  3. ``graph.manual_scan_service`` was constructed over the *exact
     same* ``SnapshotRepository`` instance as
     ``graph.snapshot_repository`` -- identity check (``is``), not
     just type/equality.
  4. ``graph.manual_scan_service``'s internal ``WatchlistScanner``
     was constructed over the *exact same*
     ``WatchlistRepository``/``MarketAnalysisAgent`` instances as
     ``graph.watchlist_repository``/``graph.market_analysis_agent``
     -- identity check.
  5. ``ManualScanService`` depends on exactly five collaborators --
     no extra attribute, no stray Repository reference.
  6. Construction remains hermetic: no connection opened, no I/O.

It also proves ``build_application()`` remains idempotent (two calls
never leak instances across each other).

It deliberately does NOT test ``ManualScanService.run_scan()``'s own
pipeline behavior (already covered by
``Tests/test_manual_scan_service.py``), and does NOT apply any
migration -- construction-only, no connection, no I/O.

Run directly:
``python Tests/test_stage_sprint5_step6_manual_scan_service_wiring.py``
-- no external test framework required.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.manual_scan_service import ManualScanService  # noqa: E402
from Core.composition_root import ApplicationGraph, build_application  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Orchestration.watchlist_scanner import WatchlistScanner  # noqa: E402
from Repository.persistence.snapshot_repository import SnapshotRepository  # noqa: E402

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
        provider_name="gemini-sprint5-step6-test",
        agent_name="sprint5-step6-test-agent",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    return graph


def scenario_manual_scan_service_present_and_real(graph: ApplicationGraph) -> None:
    """graph.manual_scan_service is a real, production ManualScanService."""
    check(
        hasattr(graph, "manual_scan_service"),
        "ApplicationGraph exposes a manual_scan_service field",
    )
    check(
        isinstance(graph.manual_scan_service, ManualScanService),
        "graph.manual_scan_service is a real ManualScanService instance (never a test double)",
    )


def scenario_manual_scan_service_shares_snapshot_repository(graph: ApplicationGraph) -> None:
    """graph.manual_scan_service was built over the exact same
    SnapshotRepository instance as graph.snapshot_repository --
    identity, not just type/equality.
    """
    check(
        isinstance(graph.snapshot_repository, SnapshotRepository),
        "graph.snapshot_repository is a real SnapshotRepository instance",
    )
    check(
        graph.manual_scan_service._snapshot_repository is graph.snapshot_repository,
        "graph.manual_scan_service shares the exact same SnapshotRepository "
        "instance as graph.snapshot_repository (identity check)",
    )


def scenario_manual_scan_service_watchlist_scanner_shares_collaborators(
    graph: ApplicationGraph,
) -> None:
    """graph.manual_scan_service's internal WatchlistScanner was built over
    the exact same WatchlistRepository/MarketAnalysisAgent instances as
    graph.watchlist_repository/graph.market_analysis_agent -- identity
    check.
    """
    inner_scanner = graph.manual_scan_service._watchlist_scanner
    check(
        isinstance(inner_scanner, WatchlistScanner),
        "graph.manual_scan_service holds a real WatchlistScanner instance",
    )
    check(
        inner_scanner._watchlist_repository is graph.watchlist_repository,
        "manual_scan_service's WatchlistScanner shares the exact same "
        "WatchlistRepository instance as graph.watchlist_repository (identity check)",
    )
    check(
        inner_scanner._market_analysis_agent is graph.market_analysis_agent,
        "manual_scan_service's WatchlistScanner shares the exact same "
        "MarketAnalysisAgent instance as graph.market_analysis_agent (identity check)",
    )


def scenario_manual_scan_service_depends_on_five_collaborators_only(
    graph: ApplicationGraph,
) -> None:
    """ManualScanService holds exactly five collaborator attributes --
    no extra attribute, no stray Repository reference beyond
    SnapshotRepository.
    """
    attrs = sorted(vars(graph.manual_scan_service).keys())
    check(
        attrs
        == [
            "_ranking_engine",
            "_recommendation_service",
            "_report_service",
            "_snapshot_repository",
            "_watchlist_scanner",
        ],
        "graph.manual_scan_service holds exactly five collaborator attributes",
    )


def scenario_underlying_repositories_share_database_manager(
    graph: ApplicationGraph,
) -> None:
    """The Repositories behind graph.manual_scan_service still share the
    exact same DatabaseManager instance as graph.database_manager --
    identity check, mirroring STEP 9's wiring test requirement.
    """
    check(
        isinstance(graph.database_manager, DatabaseManager),
        "graph.database_manager is a real DatabaseManager instance",
    )
    snapshot_repo_shares_manager = (
        graph.manual_scan_service._snapshot_repository._database_manager is graph.database_manager
    )
    check(
        snapshot_repo_shares_manager,
        "manual_scan_service's SnapshotRepository shares the exact same "
        "DatabaseManager instance as graph.database_manager (identity check)",
    )
    watchlist_repo_shares_manager = (
        graph.manual_scan_service._watchlist_scanner._watchlist_repository._database_manager
        is graph.database_manager
    )
    check(
        watchlist_repo_shares_manager,
        "manual_scan_service's WatchlistScanner's WatchlistRepository shares the "
        "exact same DatabaseManager instance as graph.database_manager (identity check)",
    )


def scenario_build_application_is_idempotent() -> None:
    """Calling build_application() twice does not raise, and each call
    still produces its own manual_scan_service sharing that call's own
    watchlist_repository/market_analysis_agent/snapshot_repository
    (never leaking across calls).
    """
    graph_a = build_application(
        provider_name="gemini-sprint5-step6-idempotent-a",
        agent_name="sprint5-step6-idempotent-agent-a",
    )
    graph_b = build_application(
        provider_name="gemini-sprint5-step6-idempotent-b",
        agent_name="sprint5-step6-idempotent-agent-b",
    )
    check(
        graph_a.manual_scan_service is not graph_b.manual_scan_service,
        "two build_application() calls produce two distinct ManualScanService instances",
    )
    check(
        graph_a.manual_scan_service._snapshot_repository is graph_a.snapshot_repository,
        "first call's manual_scan_service still shares its own call's snapshot_repository",
    )
    check(
        graph_b.manual_scan_service._snapshot_repository is graph_b.snapshot_repository,
        "second call's manual_scan_service still shares its own call's snapshot_repository",
    )
    check(
        graph_a.manual_scan_service._snapshot_repository
        is not graph_b.manual_scan_service._snapshot_repository,
        "the two calls' SnapshotRepository instances are not accidentally shared with each other",
    )


def scenario_no_connection_or_io_at_construction(graph: ApplicationGraph) -> None:
    """Construction is hermetic: no connection was opened."""
    check(
        graph.database_manager.is_connected is False,
        "database_manager (and therefore manual_scan_service's underlying "
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
        scenario_manual_scan_service_present_and_real,
        scenario_manual_scan_service_shares_snapshot_repository,
        scenario_manual_scan_service_watchlist_scanner_shares_collaborators,
        scenario_manual_scan_service_depends_on_five_collaborators_only,
        scenario_underlying_repositories_share_database_manager,
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
    print(f"SPRINT 5 STEP 6 WIRING TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())