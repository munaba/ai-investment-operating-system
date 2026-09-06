"""
Sprint 4 STEP 9 proof suite -- PaperTradingEngine wiring into
Core.composition_root.

Mirrors ``Tests/test_stage_sprint4_step6_execution_service_wiring.py``
in spirit, adapted for ``PaperTradingEngine``: this checks
``PaperTradingEngine`` was built over the graph's own
``order_lifecycle_service``/``execution_service`` -- the same shared
instances, never second instances.

This suite proves exactly five things, no more:

  1. ``build_application()`` still builds without raising.
  2. ``graph.paper_trading_engine`` is a real, production
     ``Business.paper_trading_engine.PaperTradingEngine`` instance --
     never a test double.
  3. ``graph.paper_trading_engine`` was constructed over the *exact
     same* ``OrderLifecycleService``/``ExecutionService`` instances as
     ``graph.order_lifecycle_service``/``graph.execution_service`` --
     identity check (``is``), not just type/equality.
  4. ``PaperTradingEngine`` depends on ``OrderLifecycleService``/
     ``ExecutionService`` only -- it holds no reference to any
     ``Repository``, ``AccountBalanceService``, or ``PositionManager``.
  5. Construction remains hermetic: no connection opened, no I/O.

It also proves ``build_application()`` remains idempotent (two calls
never leak instances across each other).

It deliberately does NOT test ``PaperTradingEngine``'s own
``submit_order()`` behavior (already covered by
``Tests/test_paper_trading_engine.py``), and does NOT apply
``ORDERS_MIGRATIONS``/``TRADES_MIGRATIONS`` -- construction-only, no
connection, no I/O.

Run directly:
``python Tests/test_stage_sprint4_step9_paper_trading_engine_wiring.py``
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
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Core.composition_root import ApplicationGraph, build_application  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402

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
        provider_name="gemini-sprint4-step9-test",
        agent_name="sprint4-step9-test-agent",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    return graph


def scenario_paper_trading_engine_present_and_real(graph: ApplicationGraph) -> None:
    """graph.paper_trading_engine is a real, production PaperTradingEngine."""
    check(
        hasattr(graph, "paper_trading_engine"),
        "ApplicationGraph exposes a paper_trading_engine field",
    )
    check(
        isinstance(graph.paper_trading_engine, PaperTradingEngine),
        "graph.paper_trading_engine is a real PaperTradingEngine instance (never a test double)",
    )


def scenario_paper_trading_engine_shares_services(graph: ApplicationGraph) -> None:
    """graph.paper_trading_engine was built over the exact same
    OrderLifecycleService/ExecutionService instances as
    graph.order_lifecycle_service/graph.execution_service -- identity,
    not just type/equality.
    """
    check(
        isinstance(graph.order_lifecycle_service, OrderLifecycleService),
        "graph.order_lifecycle_service is a real OrderLifecycleService instance",
    )
    check(
        isinstance(graph.execution_service, ExecutionService),
        "graph.execution_service is a real ExecutionService instance",
    )
    check(
        graph.paper_trading_engine._order_lifecycle_service is graph.order_lifecycle_service,
        "graph.paper_trading_engine shares the exact same OrderLifecycleService "
        "instance as graph.order_lifecycle_service (identity check)",
    )
    check(
        graph.paper_trading_engine._execution_service is graph.execution_service,
        "graph.paper_trading_engine shares the exact same ExecutionService "
        "instance as graph.execution_service (identity check)",
    )


def scenario_paper_trading_engine_depends_on_the_two_services_only(
    graph: ApplicationGraph,
) -> None:
    """Sprint 4 STEP 9 originally wired PaperTradingEngine to exactly two
    collaborators (_order_lifecycle_service/_execution_service). Activation
    3.2 deliberately extended the constructor (see
    Business.paper_trading_engine module docstring, "Constructor
    dependency (LOCKED for this Activation)") to five collaborators --
    adding AccountRepository/PositionRepository/OrderIdempotencyRepository
    for the 12 pre-trade gates -- plus two plain config values
    (kill_switch_engaged/max_order_value). Activation 3.3 STEP 2 added one
    further collaborator, _execution_policy (the canonical
    Business.execution_policy_config.ExecutionPolicy), read once by
    Core.composition_root and shared with graph.execution_service.
    Activation 3.5 STEP 1 added one further collaborator,
    _account_balance_service (the canonical
    Business.account_balance_service.AccountBalanceService, Sprint 4
    STEP 7), read once by Core.composition_root and shared with
    graph.account_balance_service -- this engine now calls
    apply_trade() on it after a successful execute_order(). Activation
    3.5 STEP 2 added one further collaborator, _position_manager (the
    canonical Business.position_manager.PositionManager, Sprint 4
    STEP 8), read once by Core.composition_root and shared with
    graph.position_manager -- this engine now also calls apply_trade()
    on it, immediately after _account_balance_service.apply_trade().
    Activation 6.3 (VERIFY ONLY) added two further collaborators,
    _notification_builder/_notification_manager: Core.composition_root.
    _build_paper_trading_engine now passes the graph's own
    notification_builder/notification_manager instances through (see
    that function's docstring, "notification_manager/notification_builder
    (Activation 6.3)"), so graph.paper_trading_engine notifies over the
    same real Telegram-backed chain every other graph.notification_*
    reference already shares, instead of falling back to its own inert
    defaults. This scenario is updated to assert that current contract;
    Tests/test_paper_trading_engine.py's own
    scenario_engine_holds_only_its_collaborators independently proves the
    same thing directly against a standalone engine instance.
    """
    # Activation 7 Blocker #4 ("persist user_approval so it is
    # auditable from the database") adds exactly one further
    # attribute, _order_approval_repository -- see
    # Tests/test_paper_trading_engine.py's own
    # scenario_engine_holds_only_its_collaborators for the full
    # rationale. No other Repository/Service was added, and gate 3/
    # execution order/transaction boundary are unchanged.
    # Activation 8.4 ("kill switch") adds four further plain
    # config-value attributes -- _halted_markets/_halted_symbols/
    # _max_daily_loss/_max_position_value, backing pre-trade gates
    # 13-16 -- read once at graph-build time by
    # Core.composition_root._halted_markets()/_halted_symbols()/
    # _max_daily_loss()/_max_position_value(), identical
    # construct-once pattern to _kill_switch_engaged/_max_order_value
    # above. No new Repository/Service collaborator: gates 15/16 reuse
    # the already-held _position_repository.
    attrs = sorted(vars(graph.paper_trading_engine).keys())
    check(
        attrs == sorted([
            "_order_lifecycle_service",
            "_execution_service",
            "_account_repository",
            "_position_repository",
            "_order_idempotency_repository",
            "_kill_switch_engaged",
            "_max_order_value",
            "_execution_policy",
            "_account_balance_service",
            "_position_manager",
            "_notification_builder",
            "_notification_manager",
            "_order_approval_repository",
            "_halted_markets",
            "_halted_symbols",
            "_max_daily_loss",
            "_max_position_value",
        ]),
        "graph.paper_trading_engine holds exactly its Activation 7 "
        "collaborator set (_order_lifecycle_service, _execution_service, "
        "_account_repository, _position_repository, "
        "_order_idempotency_repository, _kill_switch_engaged, "
        "_max_order_value, _execution_policy, _account_balance_service, "
        "_position_manager, _notification_builder, _notification_manager, "
        "_order_approval_repository) plus Activation 8.4's four kill-switch "
        "config values (_halted_markets, _halted_symbols, _max_daily_loss, "
        "_max_position_value) "
        "-- no other Repository/Service reference",
    )


def scenario_underlying_repositories_share_database_manager(
    graph: ApplicationGraph,
) -> None:
    """The Repositories behind graph.paper_trading_engine's two Services
    still share the exact same DatabaseManager instance as
    graph.database_manager -- identity check, mirroring STEP 6's
    wiring test requirement (transitively, since this STEP adds no new
    Repository of its own).
    """
    check(
        isinstance(graph.database_manager, DatabaseManager),
        "graph.database_manager is a real DatabaseManager instance",
    )
    order_repo_shares_manager = (
        graph.paper_trading_engine._order_lifecycle_service._order_repository._database_manager
        is graph.database_manager
    )
    check(
        order_repo_shares_manager,
        "paper_trading_engine's OrderLifecycleService's OrderRepository shares "
        "the exact same DatabaseManager instance as graph.database_manager "
        "(identity check)",
    )
    execution_order_repo_shares_manager = (
        graph.paper_trading_engine._execution_service._order_repository._database_manager
        is graph.database_manager
    )
    execution_trade_repo_shares_manager = (
        graph.paper_trading_engine._execution_service._trade_repository._database_manager
        is graph.database_manager
    )
    check(
        execution_order_repo_shares_manager and execution_trade_repo_shares_manager,
        "paper_trading_engine's ExecutionService's OrderRepository/TradeRepository "
        "share the exact same DatabaseManager instance as graph.database_manager "
        "(identity check)",
    )


def scenario_build_application_is_idempotent() -> None:
    """Calling build_application() twice does not raise, and each call
    still produces its own paper_trading_engine sharing that call's own
    order_lifecycle_service/execution_service (never leaking across
    calls).
    """
    graph_a = build_application(
        provider_name="gemini-sprint4-step9-idempotent-a",
        agent_name="sprint4-step9-idempotent-agent-a",
    )
    graph_b = build_application(
        provider_name="gemini-sprint4-step9-idempotent-b",
        agent_name="sprint4-step9-idempotent-agent-b",
    )
    check(
        graph_a.paper_trading_engine is not graph_b.paper_trading_engine,
        "two build_application() calls produce two distinct PaperTradingEngine instances",
    )
    check(
        graph_a.paper_trading_engine._order_lifecycle_service is graph_a.order_lifecycle_service
        and graph_a.paper_trading_engine._execution_service is graph_a.execution_service,
        "first call's paper_trading_engine still shares its own call's services",
    )
    check(
        graph_b.paper_trading_engine._order_lifecycle_service is graph_b.order_lifecycle_service
        and graph_b.paper_trading_engine._execution_service is graph_b.execution_service,
        "second call's paper_trading_engine still shares its own call's services",
    )
    check(
        graph_a.paper_trading_engine._order_lifecycle_service
        is not graph_b.paper_trading_engine._order_lifecycle_service,
        "the two calls' OrderLifecycleService instances are not accidentally shared with each other",
    )


def scenario_no_connection_or_io_at_construction(graph: ApplicationGraph) -> None:
    """Construction is hermetic: no connection was opened."""
    check(
        graph.database_manager.is_connected is False,
        "database_manager (and therefore paper_trading_engine's underlying "
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
        scenario_paper_trading_engine_present_and_real,
        scenario_paper_trading_engine_shares_services,
        scenario_paper_trading_engine_depends_on_the_two_services_only,
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
    print(f"SPRINT 4 STEP 9 WIRING TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())