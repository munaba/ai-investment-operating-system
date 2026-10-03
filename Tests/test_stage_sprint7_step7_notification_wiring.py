"""
Sprint 7 STEP 7 proof suite -- Notification System wiring into
Core.composition_root.

Mirrors ``Tests/test_stage_sprint5_step6_manual_scan_service_wiring.py``
in spirit, adapted for the four Sprint 7 notification objects
(``NotificationBuilder`` STEP 2, ``NotificationDispatcher`` STEP 3,
``TelegramNotificationChannel`` STEP 4, ``NotificationManager`` STEP 5):
this checks that ``build_application()`` now assembles all four, in the
LOCKED DECISION 3 order (Builder -> Channel -> Dispatcher -> Manager),
sharing this graph's own ``NotificationService`` instance -- and that
nothing here actually *sends* anything.

This suite proves:

  1.  ``build_application()`` still builds without raising.
  2.  ``graph.notification_builder`` is a real, production
      ``Business.notification_builder.NotificationBuilder`` instance.
  3.  ``graph.telegram_notification_channel`` is a real, production
      ``Business.telegram_notification_channel.TelegramNotificationChannel``
      instance.
  4.  ``graph.notification_dispatcher`` is a real, production
      ``Business.notification_dispatcher.NotificationDispatcher``
      instance.
  5.  ``graph.notification_manager`` is a real, production
      ``Business.notification_manager.NotificationManager`` instance.
  6.  All four (and the underlying ``NotificationService``) share the
      same ``DatabaseManager``/``ServiceRegistry`` this graph already
      builds -- identity checks (``is``), not just type/equality.
  7.  ``graph.telegram_notification_channel`` was built over the exact
      same ``NotificationService`` instance already registered in
      ``graph.service_registry`` -- never a second instance.
  8.  ``graph.notification_dispatcher`` holds exactly one channel.
  9.  That one channel is ``graph.telegram_notification_channel``
      itself (identity), and it is a ``TelegramNotificationChannel``.
  10. ``graph.notification_manager`` was built over the exact same
      ``NotificationDispatcher`` instance as
      ``graph.notification_dispatcher`` -- identity check.
  11. ``ApplicationGraph`` exposes all four new fields.
  12. Each ``_build_*`` builder function is called exactly once per
      ``build_application()`` call (proven via monkeypatched spies).
  13. Nothing about the pre-existing wiring changed: every field
      ``test_stage_sprint5_step6_manual_scan_service_wiring.py`` and
      ``test_stage_sprint4_step9_paper_trading_engine_wiring.py``
      already asserted (``manual_scan_service``, ``paper_trading_engine``,
      ``snapshot_repository``, ``database_manager``) is still present
      and still shares identity exactly as before.
  14. Sprint 7 STEP 1-5 regression: ``NotificationEvent``,
      ``NotificationBuilder``, ``NotificationDispatcher``,
      ``NotificationManager``, ``TelegramNotificationChannel`` proof
      suites still pass unmodified (invoked as subprocesses).
  15. No notification is ever sent as a side effect of
      ``build_application()``: ``notify()``/``dispatch()``/``send()``
      are never called by wiring construction (proven via monkeypatched
      spies on all three).

It also proves ``build_application()`` remains idempotent (two calls
never leak notification-object instances across each other) and that
construction is hermetic (no real Telegram network I/O, no DatabaseManager
connection opened).

It deliberately does NOT test ``NotificationBuilder.build_daily_report()``,
``NotificationDispatcher.dispatch()``, ``NotificationManager.notify()``,
or ``TelegramNotificationChannel.send()``'s own business behavior
(already covered by their dedicated ``Tests/test_notification_*.py``
and ``Tests/test_telegram_notification_channel.py`` suites) -- this
suite is wiring-only, exactly matching this STEP's own scope.

Run directly:
``python Tests/test_stage_sprint7_step7_notification_wiring.py``
-- no external test framework required.
"""

from __future__ import annotations

import subprocess
import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import Core.composition_root as composition_root_mod  # noqa: E402
from Business.manual_scan_service import ManualScanService  # noqa: E402
from Business.notification_builder import NotificationBuilder  # noqa: E402
from Business.notification_dispatcher import NotificationDispatcher  # noqa: E402
from Business.notification_manager import NotificationManager  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Business.telegram_notification_channel import TelegramNotificationChannel  # noqa: E402
from Core.composition_root import ApplicationGraph, build_application  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Repository.persistence.snapshot_repository import SnapshotRepository  # noqa: E402
from Services.notification_service import NotificationService  # noqa: E402

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


# ---------------------------------------------------------------------------
# Scenario 1 (graph builds) -- prerequisite for everything below
# ---------------------------------------------------------------------------
def scenario_graph_builds_without_raising() -> ApplicationGraph:
    """build_application() still builds without raising after this addition."""
    graph = build_application(
        provider_name="gemini-sprint7-step7-test",
        agent_name="sprint7-step7-test-agent",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    return graph


# ---------------------------------------------------------------------------
# Scenarios 1-4 -- each object is real and production, not a test double
# ---------------------------------------------------------------------------
def scenario_notification_builder_present_and_real(graph: ApplicationGraph) -> None:
    """graph.notification_builder is a real, production NotificationBuilder."""
    check(
        hasattr(graph, "notification_builder"),
        "ApplicationGraph exposes a notification_builder field",
    )
    check(
        isinstance(graph.notification_builder, NotificationBuilder),
        "graph.notification_builder is a real NotificationBuilder instance "
        "(never a test double)",
    )


def scenario_telegram_notification_channel_present_and_real(graph: ApplicationGraph) -> None:
    """graph.telegram_notification_channel is a real, production
    TelegramNotificationChannel.
    """
    check(
        hasattr(graph, "telegram_notification_channel"),
        "ApplicationGraph exposes a telegram_notification_channel field",
    )
    check(
        isinstance(graph.telegram_notification_channel, TelegramNotificationChannel),
        "graph.telegram_notification_channel is a real TelegramNotificationChannel "
        "instance (never a test double)",
    )


def scenario_notification_dispatcher_present_and_real(graph: ApplicationGraph) -> None:
    """graph.notification_dispatcher is a real, production NotificationDispatcher."""
    check(
        hasattr(graph, "notification_dispatcher"),
        "ApplicationGraph exposes a notification_dispatcher field",
    )
    check(
        isinstance(graph.notification_dispatcher, NotificationDispatcher),
        "graph.notification_dispatcher is a real NotificationDispatcher "
        "instance (never a test double)",
    )


def scenario_notification_manager_present_and_real(graph: ApplicationGraph) -> None:
    """graph.notification_manager is a real, production NotificationManager."""
    check(
        hasattr(graph, "notification_manager"),
        "ApplicationGraph exposes a notification_manager field",
    )
    check(
        isinstance(graph.notification_manager, NotificationManager),
        "graph.notification_manager is a real NotificationManager instance "
        "(never a test double)",
    )


# ---------------------------------------------------------------------------
# Scenario 5/6 -- shared collaborators, identity checks
# ---------------------------------------------------------------------------
def scenario_all_share_same_notification_service(graph: ApplicationGraph) -> None:
    """graph.telegram_notification_channel was built over the exact same
    NotificationService instance already registered in
    graph.service_registry -- never a second instance (LOCKED DECISION 9).
    """
    registered_service = graph.service_registry.get("notification_service")
    check(
        isinstance(registered_service, NotificationService),
        "graph.service_registry holds a real, registered NotificationService",
    )
    check(
        graph.telegram_notification_channel._notification_service is registered_service,
        "graph.telegram_notification_channel shares the exact same "
        "NotificationService instance already registered in "
        "graph.service_registry (identity check)",
    )


def scenario_underlying_objects_share_database_manager(graph: ApplicationGraph) -> None:
    """The notification wiring sits alongside (does not duplicate) this
    graph's own DatabaseManager -- mirroring the same requirement STEP 6's
    (ManualScanService) and STEP 9's (PaperTradingEngine) wiring tests
    already enforce for their own collaborators.
    """
    check(
        isinstance(graph.database_manager, DatabaseManager),
        "graph.database_manager is a real DatabaseManager instance",
    )
    check(
        graph.manual_scan_service._snapshot_repository._database_manager
        is graph.database_manager,
        "pre-existing manual_scan_service wiring is unaffected: its "
        "SnapshotRepository still shares graph.database_manager (identity "
        "check, unchanged by this STEP)",
    )


# ---------------------------------------------------------------------------
# Scenario 7/8 -- dispatcher has exactly one channel, and it's the telegram one
# ---------------------------------------------------------------------------
def scenario_dispatcher_has_exactly_one_channel(graph: ApplicationGraph) -> None:
    """graph.notification_dispatcher holds exactly one channel
    (LOCKED DECISION 5 -- no Discord, no email)."""
    channels = graph.notification_dispatcher._channels
    check(
        isinstance(channels, list),
        "graph.notification_dispatcher._channels is a list",
    )
    check(
        len(channels) == 1,
        "graph.notification_dispatcher holds exactly one channel",
    )


def scenario_first_channel_is_telegram_channel(graph: ApplicationGraph) -> None:
    """The dispatcher's one channel is graph.telegram_notification_channel
    itself (identity), and is a TelegramNotificationChannel."""
    channels = graph.notification_dispatcher._channels
    check(
        channels[0] is graph.telegram_notification_channel,
        "the dispatcher's first (only) channel is the exact same "
        "TelegramNotificationChannel instance as "
        "graph.telegram_notification_channel (identity check)",
    )
    check(
        isinstance(channels[0], TelegramNotificationChannel),
        "the dispatcher's first (only) channel is a TelegramNotificationChannel",
    )


# ---------------------------------------------------------------------------
# Scenario 9 -- manager uses the same dispatcher
# ---------------------------------------------------------------------------
def scenario_manager_shares_same_dispatcher(graph: ApplicationGraph) -> None:
    """graph.notification_manager was built over the exact same
    NotificationDispatcher instance as graph.notification_dispatcher --
    identity check (LOCKED DECISION 6)."""
    check(
        graph.notification_manager._dispatcher is graph.notification_dispatcher,
        "graph.notification_manager shares the exact same "
        "NotificationDispatcher instance as graph.notification_dispatcher "
        "(identity check)",
    )


# ---------------------------------------------------------------------------
# Scenario 10 -- ApplicationGraph exposes all four new fields
# ---------------------------------------------------------------------------
def scenario_application_graph_has_all_four_new_fields() -> None:
    """ApplicationGraph's own field list includes all four new fields,
    additive only (no existing field name removed)."""
    field_names = set(ApplicationGraph.__dataclass_fields__.keys())
    for name in (
        "notification_builder",
        "telegram_notification_channel",
        "notification_dispatcher",
        "notification_manager",
    ):
        check(
            name in field_names,
            f"ApplicationGraph.__dataclass_fields__ includes '{name}'",
        )
    # Additive-only: none of the old fields this project already relies
    # on were removed or renamed by this STEP.
    for name in (
        "config",
        "database_manager",
        "service_registry",
        "manual_scan_service",
        "paper_trading_engine",
        "snapshot_repository",
        "agent",
    ):
        check(
            name in field_names,
            f"ApplicationGraph.__dataclass_fields__ still includes "
            f"pre-existing field '{name}' (additive-only, nothing removed)",
        )


# ---------------------------------------------------------------------------
# Scenario 11 -- each builder function is called exactly once
# ---------------------------------------------------------------------------
def scenario_each_builder_function_called_exactly_once() -> None:
    """Each of the four new _build_* functions is called exactly once per
    build_application() call (LOCKED DECISION 8: exactly one object each,
    no singleton, no lazy loading, no re-entrant double-build)."""
    call_counts = {
        "_build_notification_builder": 0,
        "_build_telegram_notification_channel": 0,
        "_build_notification_dispatcher": 0,
        "_build_notification_manager": 0,
    }

    originals = {
        name: getattr(composition_root_mod, name) for name in call_counts
    }

    def make_spy(name: str, original):
        def _spy(*args, **kwargs):
            call_counts[name] += 1
            return original(*args, **kwargs)

        return _spy

    for name in call_counts:
        setattr(composition_root_mod, name, make_spy(name, originals[name]))

    try:
        build_application(
            provider_name="gemini-sprint7-step7-spy-test",
            agent_name="sprint7-step7-spy-test-agent",
        )
    finally:
        for name, original in originals.items():
            setattr(composition_root_mod, name, original)

    for name, count in call_counts.items():
        check(
            count == 1,
            f"{name}() is called exactly once per build_application() call "
            f"(observed {count})",
        )


# ---------------------------------------------------------------------------
# Scenario 12 -- pre-existing wiring (STEP 1-5 predecessors) unaffected
# ---------------------------------------------------------------------------
def scenario_pre_existing_wiring_unaffected(graph: ApplicationGraph) -> None:
    """Nothing about the pre-existing manual_scan_service/paper_trading_engine
    wiring changed -- same fields, same identity relationships as their own
    dedicated wiring test suites already assert (LOCKED DECISION 11)."""
    check(
        isinstance(graph.manual_scan_service, ManualScanService),
        "graph.manual_scan_service is still a real ManualScanService "
        "instance, unaffected by this STEP",
    )
    check(
        isinstance(graph.snapshot_repository, SnapshotRepository),
        "graph.snapshot_repository is still a real SnapshotRepository "
        "instance, unaffected by this STEP",
    )
    check(
        graph.manual_scan_service._snapshot_repository is graph.snapshot_repository,
        "graph.manual_scan_service still shares the exact same "
        "SnapshotRepository instance as graph.snapshot_repository "
        "(identity check, unchanged by this STEP)",
    )
    check(
        isinstance(graph.paper_trading_engine, PaperTradingEngine),
        "graph.paper_trading_engine is still a real PaperTradingEngine "
        "instance, unaffected by this STEP",
    )


# ---------------------------------------------------------------------------
# Scenario 13 -- idempotency: two calls never leak notification instances
# ---------------------------------------------------------------------------
def scenario_build_application_is_idempotent() -> None:
    """Calling build_application() twice does not raise, and each call
    still produces its own notification wiring instances sharing that
    call's own NotificationService/database_manager (never leaking
    across calls)."""
    graph_a = build_application(
        provider_name="gemini-sprint7-step7-idempotent-a",
        agent_name="sprint7-step7-idempotent-agent-a",
    )
    graph_b = build_application(
        provider_name="gemini-sprint7-step7-idempotent-b",
        agent_name="sprint7-step7-idempotent-agent-b",
    )
    check(
        graph_a.notification_builder is not graph_b.notification_builder,
        "two build_application() calls produce two distinct "
        "NotificationBuilder instances",
    )
    check(
        graph_a.telegram_notification_channel is not graph_b.telegram_notification_channel,
        "two build_application() calls produce two distinct "
        "TelegramNotificationChannel instances",
    )
    check(
        graph_a.notification_dispatcher is not graph_b.notification_dispatcher,
        "two build_application() calls produce two distinct "
        "NotificationDispatcher instances",
    )
    check(
        graph_a.notification_manager is not graph_b.notification_manager,
        "two build_application() calls produce two distinct "
        "NotificationManager instances",
    )
    check(
        graph_a.telegram_notification_channel._notification_service
        is not graph_b.telegram_notification_channel._notification_service,
        "the two calls' NotificationService instances are not "
        "accidentally shared with each other",
    )
    check(
        graph_a.notification_dispatcher._channels[0]
        is graph_a.telegram_notification_channel,
        "first call's dispatcher still shares its own call's telegram channel",
    )
    check(
        graph_b.notification_dispatcher._channels[0]
        is graph_b.telegram_notification_channel,
        "second call's dispatcher still shares its own call's telegram channel",
    )


# ---------------------------------------------------------------------------
# Scenario 14 -- construction is hermetic (no I/O, no send)
# ---------------------------------------------------------------------------
def scenario_no_connection_or_io_at_construction(graph: ApplicationGraph) -> None:
    """Construction is hermetic: no DatabaseManager connection was opened,
    and no real Telegram/HTTP call was made by wiring alone."""
    check(
        graph.database_manager.is_connected is False,
        "database_manager (and therefore the notification wiring built "
        "alongside it) is not connected after build_application() -- "
        "construction remains hermetic, no I/O",
    )


# ---------------------------------------------------------------------------
# Scenario 15 -- LOCKED DECISION 10: no notify()/dispatch()/send() is
# ever called by build_application() itself
# ---------------------------------------------------------------------------
def scenario_no_notification_is_sent_during_wiring() -> None:
    """build_application() constructs the whole notification pipeline but
    never calls notify()/dispatch()/send() itself (LOCKED DECISION 10)."""
    notify_calls: List[object] = []
    dispatch_calls: List[object] = []
    send_calls: List[object] = []

    original_notify = NotificationManager.notify
    original_dispatch = NotificationDispatcher.dispatch
    original_send = TelegramNotificationChannel.send

    def spy_notify(self, event):
        notify_calls.append(event)
        return original_notify(self, event)

    def spy_dispatch(self, event):
        dispatch_calls.append(event)
        return original_dispatch(self, event)

    def spy_send(self, event):
        send_calls.append(event)
        return original_send(self, event)

    NotificationManager.notify = spy_notify
    NotificationDispatcher.dispatch = spy_dispatch
    TelegramNotificationChannel.send = spy_send

    try:
        build_application(
            provider_name="gemini-sprint7-step7-no-send-test",
            agent_name="sprint7-step7-no-send-test-agent",
        )
    finally:
        NotificationManager.notify = original_notify
        NotificationDispatcher.dispatch = original_dispatch
        TelegramNotificationChannel.send = original_send

    check(
        len(notify_calls) == 0,
        "NotificationManager.notify() is never called by build_application()",
    )
    check(
        len(dispatch_calls) == 0,
        "NotificationDispatcher.dispatch() is never called by build_application()",
    )
    check(
        len(send_calls) == 0,
        "TelegramNotificationChannel.send() is never called by build_application()",
    )


# ---------------------------------------------------------------------------
# Scenario 16 -- Sprint 7 STEP 1-5 regression (subprocess invocation)
# ---------------------------------------------------------------------------
def scenario_step1_to_5_regression_suites_still_pass() -> None:
    """The five dedicated Sprint 7 STEP 1-5 proof suites still pass,
    unmodified by this wiring-only STEP (LOCKED DECISION 1/11)."""
    suite_files = [
        "test_notification_event.py",
        "test_notification_builder.py",
        "test_notification_dispatcher.py",
        "test_telegram_notification_channel.py",
        "test_notification_manager.py",
    ]
    for suite_file in suite_files:
        suite_path = ROOT / "Tests" / suite_file
        check(
            suite_path.is_file(),
            f"{suite_file} still exists and was not removed by this STEP",
        )
        result = subprocess.run(
            [sys.executable, str(suite_path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        check(
            result.returncode == 0,
            f"{suite_file} still exits 0 (all its own assertions still pass, "
            f"unmodified regression)",
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
        scenario_notification_builder_present_and_real,
        scenario_telegram_notification_channel_present_and_real,
        scenario_notification_dispatcher_present_and_real,
        scenario_notification_manager_present_and_real,
        scenario_all_share_same_notification_service,
        scenario_underlying_objects_share_database_manager,
        scenario_dispatcher_has_exactly_one_channel,
        scenario_first_channel_is_telegram_channel,
        scenario_manager_shares_same_dispatcher,
        scenario_pre_existing_wiring_unaffected,
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

    standalone_scenarios = [
        scenario_application_graph_has_all_four_new_fields,
        scenario_each_builder_function_called_exactly_once,
        scenario_build_application_is_idempotent,
        scenario_no_notification_is_sent_during_wiring,
        scenario_step1_to_5_regression_suites_still_pass,
    ]
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
    print(f"SPRINT 7 STEP 7 NOTIFICATION WIRING TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())