"""
Sprint 4 STEP 5 proof suite -- OrderLifecycleService wiring into
Core.composition_root.

Mirrors ``Tests/test_stage_sprint4_step4_trade_repository_wiring.py``
in spirit, adapted for a business-layer component rather than a
Repository: instead of checking a shared ``DatabaseManager``, this
checks ``OrderLifecycleService`` was built over the graph's own
``order_repository`` -- the same shared instance, never a second
``OrderRepository``.

This suite proves exactly five things, no more:

  1. ``build_application()`` still builds without raising.
  2. ``graph.order_lifecycle_service`` is a real, production
     ``Business.order_lifecycle_service.OrderLifecycleService``
     instance -- never a test double.
  3. ``graph.order_lifecycle_service`` was constructed over the
     *exact same* ``OrderRepository`` instance as
     ``graph.order_repository`` -- identity check (``is``), not just
     type/equality.
  4. ``OrderLifecycleService`` depends on ``OrderRepository`` only --
     it holds no reference to ``account_repository``,
     ``position_repository``, or ``trade_repository``.
  5. Construction remains hermetic: no connection opened, no I/O.

It deliberately does NOT test ``OrderLifecycleService``'s own
lifecycle behavior (already covered by
``Tests/test_order_lifecycle_service.py``), and does NOT apply
``ORDERS_MIGRATIONS`` -- construction-only, no connection, no I/O.

Run directly:
``python Tests/test_stage_sprint4_step5_order_lifecycle_service_wiring.py``
-- no external test framework required.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Core.composition_root import ApplicationGraph, build_application  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402

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
        provider_name="gemini-sprint4-step5-test",
        agent_name="sprint4-step5-test-agent",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    return graph


def scenario_order_lifecycle_service_present_and_real(graph: ApplicationGraph) -> None:
    """graph.order_lifecycle_service is a real, production OrderLifecycleService."""
    check(
        hasattr(graph, "order_lifecycle_service"),
        "ApplicationGraph exposes an order_lifecycle_service field",
    )
    check(
        isinstance(graph.order_lifecycle_service, OrderLifecycleService),
        "graph.order_lifecycle_service is a real OrderLifecycleService instance (never a test double)",
    )


def scenario_order_lifecycle_service_shares_order_repository(graph: ApplicationGraph) -> None:
    """graph.order_lifecycle_service was built over the exact same
    OrderRepository instance as graph.order_repository -- identity,
    not just type/equality.
    """
    check(
        isinstance(graph.order_repository, OrderRepository),
        "graph.order_repository is a real OrderRepository instance",
    )
    same_as_order_repository = (
        graph.order_lifecycle_service._order_repository is graph.order_repository
    )
    check(
        same_as_order_repository,
        "graph.order_lifecycle_service shares the exact same OrderRepository "
        "instance as graph.order_repository (identity check)",
    )


def scenario_order_lifecycle_service_depends_on_order_repository_only(
    graph: ApplicationGraph,
) -> None:
    """OrderLifecycleService holds exactly one collaborator attribute:
    _order_repository -- no account/position/trade repository
    reference anywhere on the instance.
    """
    attrs = vars(graph.order_lifecycle_service)
    check(
        list(attrs.keys()) == ["_order_repository"],
        "graph.order_lifecycle_service holds exactly one collaborator attribute (_order_repository)",
    )


def scenario_build_application_is_idempotent() -> None:
    """Calling build_application() twice does not raise, and each call
    still produces its own order_lifecycle_service sharing that call's
    own order_repository (never leaking across calls).
    """
    graph_a = build_application(
        provider_name="gemini-sprint4-step5-idempotent-a",
        agent_name="sprint4-step5-idempotent-agent-a",
    )
    graph_b = build_application(
        provider_name="gemini-sprint4-step5-idempotent-b",
        agent_name="sprint4-step5-idempotent-agent-b",
    )
    check(
        graph_a.order_lifecycle_service is not graph_b.order_lifecycle_service,
        "two build_application() calls produce two distinct OrderLifecycleService instances",
    )
    check(
        graph_a.order_lifecycle_service._order_repository is graph_a.order_repository,
        "first call's order_lifecycle_service still shares its own call's order_repository",
    )
    check(
        graph_b.order_lifecycle_service._order_repository is graph_b.order_repository,
        "second call's order_lifecycle_service still shares its own call's order_repository",
    )
    check(
        graph_a.order_lifecycle_service._order_repository
        is not graph_b.order_lifecycle_service._order_repository,
        "the two calls' order_repository instances are not accidentally shared with each other",
    )


def scenario_no_connection_or_io_at_construction(graph: ApplicationGraph) -> None:
    """Construction is hermetic: no connection was opened."""
    check(
        graph.database_manager.is_connected is False,
        "database_manager (and therefore order_lifecycle_service's underlying "
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
        scenario_order_lifecycle_service_present_and_real,
        scenario_order_lifecycle_service_shares_order_repository,
        scenario_order_lifecycle_service_depends_on_order_repository_only,
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
    print(f"SPRINT 4 STEP 5 WIRING TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())