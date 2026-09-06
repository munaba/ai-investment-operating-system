"""
Sprint 4 STEP 1 proof suite -- AccountRepository wiring into
Core.composition_root.

Scope (per Sprint 4 Pre-Implementation Review, approved): this is the
first Sprint 4 STEP. It only makes ``ApplicationGraph.account_repository``
reachable from the production object graph, over the graph's own
``database_manager`` -- the same shared instance every later Sprint 4
Repository (Position/Order/Trade, none built yet) must also share, so
that ``BasePersistenceRepository._session()``'s transaction nesting
(SAVEPOINT-based) actually spans all of them once they exist.

This suite proves exactly three things, no more:

  1. ``build_application()`` still builds without raising (no existing
     signature/behavior broken by this addition).
  2. ``graph.account_repository`` is a real, production
     ``Repository.persistence.account_repository.AccountRepository``
     instance -- never a test double.
  3. ``graph.account_repository`` was constructed over the *exact same*
     ``DatabaseManager`` instance as ``graph.database_manager`` --
     identity check (``is``), not just type/equality -- since this is
     the one property every later Sprint 4 atomicity guarantee depends
     on.

It deliberately does NOT test AccountRepository's own CRUD behavior
(already covered by ``Tests/test_account_repository.py``, unchanged and
still the source of truth for that), and does NOT apply
``ACCOUNTS_MIGRATIONS`` -- construction-only, no connection, no I/O,
matching every other component this module already builds hermetically
(see ``Tests/test_stage9_0_composition_root.py`` Level 1).

Run directly: ``python Tests/test_stage_sprint4_step1_account_repository_wiring.py``
-- no external test framework required, matching every other
``Tests/test_stage_*.py`` file in this project.
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
        provider_name="gemini-sprint4-step1-test",
        agent_name="sprint4-step1-test-agent",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    return graph


def scenario_account_repository_present_and_real(graph: ApplicationGraph) -> None:
    """graph.account_repository is a real, production AccountRepository."""
    check(
        hasattr(graph, "account_repository"),
        "ApplicationGraph exposes an account_repository field",
    )
    check(
        isinstance(graph.account_repository, AccountRepository),
        "graph.account_repository is a real AccountRepository instance (never a test double)",
    )


def scenario_account_repository_shares_database_manager(graph: ApplicationGraph) -> None:
    """graph.account_repository was built over the exact same DatabaseManager
    as graph.database_manager -- identity, not just type/equality.

    This is the property later Sprint 4 STEPs (PositionRepository,
    OrderRepository, TradeRepository, PaperTradingEngine's single
    _session() call) depend on for atomicity. If this ever regresses to
    two separate DatabaseManager instances, transactions opened via one
    Repository would silently NOT cover writes made via another --
    exactly the failure mode flagged in the Sprint 4 Pre-Implementation
    Review (R2).
    """
    check(
        isinstance(graph.database_manager, DatabaseManager),
        "graph.database_manager is a real DatabaseManager instance",
    )
    same_instance = graph.account_repository._database_manager is graph.database_manager
    check(
        same_instance,
        "graph.account_repository shares the exact same DatabaseManager "
        "instance as graph.database_manager (identity check)",
    )


def scenario_build_application_is_idempotent() -> None:
    """Calling build_application() twice does not raise, and each call
    still produces its own account_repository sharing that call's own
    database_manager (never leaking across calls).
    """
    graph_a = build_application(
        provider_name="gemini-sprint4-step1-idempotent-a",
        agent_name="sprint4-step1-idempotent-agent-a",
    )
    graph_b = build_application(
        provider_name="gemini-sprint4-step1-idempotent-b",
        agent_name="sprint4-step1-idempotent-agent-b",
    )
    check(
        graph_a.account_repository is not graph_b.account_repository,
        "two build_application() calls produce two distinct AccountRepository instances",
    )
    check(
        graph_a.account_repository._database_manager is graph_a.database_manager,
        "first call's account_repository still shares its own call's database_manager",
    )
    check(
        graph_b.account_repository._database_manager is graph_b.database_manager,
        "second call's account_repository still shares its own call's database_manager",
    )
    check(
        graph_a.account_repository._database_manager is not graph_b.account_repository._database_manager,
        "the two calls' database_manager instances are not accidentally shared with each other",
    )


def scenario_no_connection_or_io_at_construction(graph: ApplicationGraph) -> None:
    """Construction is hermetic: no connection was opened, matching every
    other component this module builds construct-only.
    """
    check(
        graph.database_manager.is_connected is False,
        "database_manager (and therefore account_repository's backing "
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
        scenario_account_repository_present_and_real,
        scenario_account_repository_shares_database_manager,
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
    print(f"SPRINT 4 STEP 1 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())