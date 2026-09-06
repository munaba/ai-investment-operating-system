"""
Sprint 4 STEP 8 proof suite -- PositionManager wiring into
Core.composition_root.

Mirrors ``Tests/test_stage_sprint4_step7_account_balance_service_wiring.py``
in spirit, adapted for ``PositionManager``: this checks
``PositionManager`` was built over the graph's own
``position_repository`` (from Sprint 4 STEP 2) -- the same shared
instance, never a second instance -- and that that repository, in
turn, shares the graph's one ``database_manager``.

This suite proves exactly five things, no more:

  1. ``build_application()`` still builds without raising.
  2. ``graph.position_manager`` is a real, production
     ``Business.position_manager.PositionManager`` instance -- never a
     test double.
  3. ``graph.position_manager`` was constructed over the *exact same*
     ``PositionRepository`` instance as ``graph.position_repository``
     -- identity check (``is``), not just type/equality.
  4. ``PositionManager`` depends on ``PositionRepository`` only -- it
     holds no reference to
     ``account_repository``/``order_repository``/``trade_repository``.
  5. ``position_manager``'s repository shares the exact same
     ``DatabaseManager`` instance as ``graph.database_manager``
     (identity check).

It also proves ``build_application()`` remains idempotent (two calls
never leak instances across each other) and that construction stays
hermetic (no connection opened, no I/O).

It deliberately does NOT test ``PositionManager``'s own
``apply_trade()`` behavior (already covered by
``Tests/test_position_manager.py``), and does NOT apply
``POSITIONS_MIGRATIONS`` -- construction-only, no connection, no I/O.

Run directly:
``python Tests/test_stage_sprint4_step8_position_manager_wiring.py``
-- no external test framework required.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.position_manager import PositionManager  # noqa: E402
from Core.composition_root import ApplicationGraph, build_application  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402

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
        provider_name="gemini-sprint4-step8-test",
        agent_name="sprint4-step8-test-agent",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    return graph


def scenario_position_manager_present_and_real(graph: ApplicationGraph) -> None:
    """graph.position_manager is a real, production PositionManager."""
    check(
        hasattr(graph, "position_manager"),
        "ApplicationGraph exposes a position_manager field",
    )
    check(
        isinstance(graph.position_manager, PositionManager),
        "graph.position_manager is a real PositionManager instance (never a test double)",
    )


def scenario_position_manager_shares_repository(graph: ApplicationGraph) -> None:
    """graph.position_manager was built over the exact same
    PositionRepository instance as graph.position_repository --
    identity, not just type/equality.
    """
    check(
        isinstance(graph.position_repository, PositionRepository),
        "graph.position_repository is a real PositionRepository instance",
    )
    check(
        graph.position_manager._position_repository is graph.position_repository,
        "graph.position_manager shares the exact same PositionRepository "
        "instance as graph.position_repository (identity check)",
    )


def scenario_position_manager_depends_on_position_repository_only(
    graph: ApplicationGraph,
) -> None:
    """PositionManager holds exactly one collaborator attribute wired
    to something by the composition root: _position_repository -- no
    order/trade repository reference anywhere on the instance.

    Activation 11.12 added a SECOND, OPTIONAL collaborator attribute
    (_account_repository) to the PositionManager class itself, but
    Core.composition_root._build_position_manager() (Core/*, out of
    scope for Activation 11.12 -- see its HARD SCOPE LIMIT) still
    calls ``PositionManager(position_repository)`` with a single
    positional argument, exactly as before. So graph.position_manager
    ends up with two attributes, and the second
    (_account_repository) is None -- the composition root has not
    (yet) been taught to wire a real AccountRepository into
    PositionManager. That wiring is explicitly out of scope for this
    Activation and is deferred to whichever future STEP actually
    creates a Forex account/CLI/PaperTradingEngine integration.
    """
    attrs = sorted(vars(graph.position_manager).keys())
    check(
        attrs == ["_account_repository", "_position_repository"],
        "graph.position_manager holds exactly two collaborator attributes "
        "(_account_repository, _position_repository)",
    )
    check(
        graph.position_manager._account_repository is None,
        "graph.position_manager._account_repository is None -- the composition root "
        "does not wire an AccountRepository into PositionManager as of Activation 11.12 "
        "(Core/composition_root.py is out of this Activation's scope)",
    )


def scenario_position_manager_repository_shares_database_manager(
    graph: ApplicationGraph,
) -> None:
    """position_manager's PositionRepository shares the exact same
    DatabaseManager instance as graph.database_manager -- identity
    check, mirroring STEP 6/STEP 7's wiring test requirement.
    """
    check(
        isinstance(graph.database_manager, DatabaseManager),
        "graph.database_manager is a real DatabaseManager instance",
    )
    repo_shares_manager = (
        graph.position_manager._position_repository._database_manager is graph.database_manager
    )
    check(
        repo_shares_manager,
        "position_manager's PositionRepository shares the exact same "
        "DatabaseManager instance as graph.database_manager (identity check)",
    )


def scenario_build_application_is_idempotent() -> None:
    """Calling build_application() twice does not raise, and each call
    still produces its own position_manager sharing that call's own
    position_repository (never leaking across calls).
    """
    graph_a = build_application(
        provider_name="gemini-sprint4-step8-idempotent-a",
        agent_name="sprint4-step8-idempotent-agent-a",
    )
    graph_b = build_application(
        provider_name="gemini-sprint4-step8-idempotent-b",
        agent_name="sprint4-step8-idempotent-agent-b",
    )
    check(
        graph_a.position_manager is not graph_b.position_manager,
        "two build_application() calls produce two distinct PositionManager instances",
    )
    check(
        graph_a.position_manager._position_repository is graph_a.position_repository,
        "first call's position_manager still shares its own call's repository",
    )
    check(
        graph_b.position_manager._position_repository is graph_b.position_repository,
        "second call's position_manager still shares its own call's repository",
    )
    check(
        graph_a.position_manager._position_repository
        is not graph_b.position_manager._position_repository,
        "the two calls' PositionRepository instances are not accidentally shared with each other",
    )
    check(
        graph_a.database_manager is not graph_b.database_manager,
        "the two calls do not accidentally share one DatabaseManager either",
    )


def scenario_no_connection_or_io_at_construction(graph: ApplicationGraph) -> None:
    """Construction is hermetic: no connection was opened."""
    check(
        graph.database_manager.is_connected is False,
        "database_manager (and therefore position_manager's underlying "
        "connection) is not connected after build_application() -- construction "
        "remains hermetic, no I/O",
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
        scenario_position_manager_present_and_real,
        scenario_position_manager_shares_repository,
        scenario_position_manager_depends_on_position_repository_only,
        scenario_position_manager_repository_shares_database_manager,
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
    print(f"SPRINT 4 STEP 8 WIRING TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())