"""
Sprint 4 STEP 7 proof suite -- AccountBalanceService wiring into
Core.composition_root.

Mirrors ``Tests/test_stage_sprint4_step6_execution_service_wiring.py``
in spirit, adapted for a service with one Repository collaborator
(``AccountRepository``) instead of two: this checks
``AccountBalanceService`` was built over the graph's own
``account_repository`` -- the same shared instance (from Sprint 4
STEP 1), never a second instance -- and that that repository, in
turn, shares the graph's one ``database_manager``.

This suite proves exactly five things, no more:

  1. ``build_application()`` still builds without raising.
  2. ``graph.account_balance_service`` is a real, production
     ``Business.account_balance_service.AccountBalanceService``
     instance -- never a test double.
  3. ``graph.account_balance_service`` was constructed over the
     *exact same* ``AccountRepository`` instance as
     ``graph.account_repository`` -- identity check (``is``), not
     just type/equality.
  4. ``AccountBalanceService`` depends on ``AccountRepository`` only
     -- it holds no reference to
     ``position_repository``/``order_repository``/``trade_repository``.
  5. ``account_balance_service``'s repository shares the exact same
     ``DatabaseManager`` instance as ``graph.database_manager``
     (identity check).

It also proves ``build_application()`` remains idempotent (two calls
never leak instances across each other) and that construction stays
hermetic (no connection opened, no I/O).

It deliberately does NOT test ``AccountBalanceService``'s own
``apply_trade()`` behavior (already covered by
``Tests/test_account_balance_service.py``), and does NOT apply
``ACCOUNTS_MIGRATIONS`` -- construction-only, no connection, no I/O.

Run directly:
``python Tests/test_stage_sprint4_step7_account_balance_service_wiring.py``
-- no external test framework required.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.account_balance_service import AccountBalanceService  # noqa: E402
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
        provider_name="gemini-sprint4-step7-test",
        agent_name="sprint4-step7-test-agent",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    return graph


def scenario_account_balance_service_present_and_real(graph: ApplicationGraph) -> None:
    """graph.account_balance_service is a real, production AccountBalanceService."""
    check(
        hasattr(graph, "account_balance_service"),
        "ApplicationGraph exposes an account_balance_service field",
    )
    check(
        isinstance(graph.account_balance_service, AccountBalanceService),
        "graph.account_balance_service is a real AccountBalanceService instance "
        "(never a test double)",
    )


def scenario_account_balance_service_shares_repository(graph: ApplicationGraph) -> None:
    """graph.account_balance_service was built over the exact same
    AccountRepository instance as graph.account_repository -- identity,
    not just type/equality.
    """
    check(
        isinstance(graph.account_repository, AccountRepository),
        "graph.account_repository is a real AccountRepository instance",
    )
    check(
        graph.account_balance_service._account_repository is graph.account_repository,
        "graph.account_balance_service shares the exact same AccountRepository "
        "instance as graph.account_repository (identity check)",
    )


def scenario_account_balance_service_depends_on_account_repository_only(
    graph: ApplicationGraph,
) -> None:
    """AccountBalanceService holds exactly one collaborator attribute:
    _account_repository -- no position/order/trade repository
    reference anywhere on the instance.
    """
    attrs = sorted(vars(graph.account_balance_service).keys())
    check(
        attrs == ["_account_repository"],
        "graph.account_balance_service holds exactly one collaborator attribute "
        "(_account_repository)",
    )


def scenario_account_balance_service_repository_shares_database_manager(
    graph: ApplicationGraph,
) -> None:
    """account_balance_service's AccountRepository shares the exact same
    DatabaseManager instance as graph.database_manager -- identity
    check, mirroring the STEP 6 wiring test's explicit requirement.
    """
    check(
        isinstance(graph.database_manager, DatabaseManager),
        "graph.database_manager is a real DatabaseManager instance",
    )
    repo_shares_manager = (
        graph.account_balance_service._account_repository._database_manager
        is graph.database_manager
    )
    check(
        repo_shares_manager,
        "account_balance_service's AccountRepository shares the exact same "
        "DatabaseManager instance as graph.database_manager (identity check)",
    )


def scenario_build_application_is_idempotent() -> None:
    """Calling build_application() twice does not raise, and each call
    still produces its own account_balance_service sharing that call's
    own account_repository (never leaking across calls).
    """
    graph_a = build_application(
        provider_name="gemini-sprint4-step7-idempotent-a",
        agent_name="sprint4-step7-idempotent-agent-a",
    )
    graph_b = build_application(
        provider_name="gemini-sprint4-step7-idempotent-b",
        agent_name="sprint4-step7-idempotent-agent-b",
    )
    check(
        graph_a.account_balance_service is not graph_b.account_balance_service,
        "two build_application() calls produce two distinct AccountBalanceService instances",
    )
    check(
        graph_a.account_balance_service._account_repository is graph_a.account_repository,
        "first call's account_balance_service still shares its own call's repository",
    )
    check(
        graph_b.account_balance_service._account_repository is graph_b.account_repository,
        "second call's account_balance_service still shares its own call's repository",
    )
    check(
        graph_a.account_balance_service._account_repository
        is not graph_b.account_balance_service._account_repository,
        "the two calls' AccountRepository instances are not accidentally shared with each other",
    )
    check(
        graph_a.database_manager is not graph_b.database_manager,
        "the two calls do not accidentally share one DatabaseManager either",
    )


def scenario_no_connection_or_io_at_construction(graph: ApplicationGraph) -> None:
    """Construction is hermetic: no connection was opened."""
    check(
        graph.database_manager.is_connected is False,
        "database_manager (and therefore account_balance_service's underlying "
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
        scenario_account_balance_service_present_and_real,
        scenario_account_balance_service_shares_repository,
        scenario_account_balance_service_depends_on_account_repository_only,
        scenario_account_balance_service_repository_shares_database_manager,
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
    print(f"SPRINT 4 STEP 7 WIRING TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())