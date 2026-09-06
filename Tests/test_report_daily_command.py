"""Standalone regression checks for Activation 7 FIX blocker #2:

    ``python main.py report daily`` no longer lets a Telegram
    credential/network failure escape as a raw, unhandled traceback.
    ``main._run_report_daily()`` now catches any exception
    ``DailyReportOrchestrator.run_daily_report()`` raises -- reusing
    the exact catch-log-print-non-zero pattern Activation 7 already
    established in ``main._run_post_trade_snapshot_and_reconciliation()``
    -- reports it to the caller as a clean, labelled failure message
    (never a traceback), logs it (never silently), returns a non-zero
    exit code, and never attempts to roll back any state a prior step
    (``ManualScanService.run_scan()``) already committed.

Drives the REAL notification pipeline end to end wherever the blocker
actually lives: real ``NotificationBuilder``, real
``NotificationManager``, real ``NotificationDispatcher``, real
``TelegramNotificationChannel``, real ``NotificationService`` (Sprint
7/Activation 6.1/6.2, all LOCKED and unmodified here) -- a genuine
missing-credential failure and a genuine network-failure double both
propagate a real ``NotificationServiceError``/exception up through the
real, untouched ``DailyReportOrchestrator`` (its own documented "no
try/except" contract is left exactly as-is) into
``main._run_report_daily()``, which is the one and only place this fix
touches.

``ManualScanService``/``PerformanceSummaryProductionService`` are
faked (small doubles returning a real ``Report``/a duck-typed
performance object) -- they are the two upstream, unrelated-to-this-
blocker business steps and are not under test here; faking them keeps
this file focused on the notification-failure boundary, mirroring how
``Tests/test_activation7_fix_blockers.py`` fakes only I/O boundaries
(price tool, channel) and never re-implements business logic itself.

Run directly with ``python Tests/test_report_daily_command.py`` -- no
external test framework required, matching every other standalone
test file in this repository.
"""

from __future__ import annotations

import io
import logging
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import main  # noqa: E402
from Business.notification_builder import NotificationBuilder  # noqa: E402
from Business.notification_dispatcher import NotificationDispatcher  # noqa: E402
from Business.notification_manager import NotificationManager  # noqa: E402
from Business.daily_report_orchestrator import DailyReportOrchestrator  # noqa: E402
from Business.report_service import Report  # noqa: E402
from Business.telegram_notification_channel import TelegramNotificationChannel  # noqa: E402
from Services.metadata_keys import MetadataKeys  # noqa: E402
from Services.notification_service import NotificationService  # noqa: E402
from Services.service_context import ServiceContext  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES = []


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
# Test doubles for the two upstream, unrelated-to-this-blocker business
# steps only. Everything from NotificationBuilder onward is real.
# ---------------------------------------------------------------------------


class _FakeManualScanService:
    """Stands in for ``ManualScanService`` -- returns a real ``Report``
    without running an actual scan pipeline. Records whether it ran,
    so a test can prove this "already-committed" step is never undone
    after a later notification failure."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_scan(self, generated_at: str) -> Report:
        self.calls.append(generated_at)
        return Report(generated_at=generated_at, recommendations=[], total_symbols=0)


class _FakePerformanceSummaryProductionService:
    """Stands in for ``PerformanceSummaryProductionService`` -- returns a
    duck-typed object exposing only the two attributes
    ``NotificationBuilder.build_daily_report()`` actually reads
    (``win_rate`` and ``maximum_drawdown.maximum_drawdown``)."""

    def get_performance_summary(self, account_id: str):
        return SimpleNamespace(
            win_rate=0.5,
            maximum_drawdown=SimpleNamespace(maximum_drawdown=0.1),
        )


class _RaisingHttpClient:
    """Injected as ``NotificationService``'s ``http_client`` -- simulates
    a real network failure (connection refused/timeout) at the exact
    point ``requests.post`` would be called."""

    def post(self, *args, **kwargs):
        raise ConnectionError("simulated Telegram network outage")


class _ListLogHandler(logging.Handler):
    """Captures log records emitted by a real logger, so a test can
    prove the failure is actually logged (not just \"doesn't crash\")."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _no_credentials_context_factory(metadata):
    """A ``service_context_factory`` that supplies no
    ``telegram_bot_token``/``telegram_chat_id`` -- simulates the real
    "Telegram credentials not configured" production failure path
    (mirrors ``Core.composition_root._notification_service_context_
    factory`` leaving those keys out when the env vars are unset)."""
    return ServiceContext(
        agent_name="daily_report",
        provider_name="",
        request_id="test-request-id",
        user_input="",
        metadata=dict(metadata),
    )


def _with_credentials_context_factory(metadata):
    """A ``service_context_factory`` that supplies real-shaped (fake)
    credentials, so the request reaches the injected HTTP client --
    used for the network-failure and happy-path scenarios."""
    resolved = dict(metadata)
    resolved[MetadataKeys.TELEGRAM_BOT_TOKEN] = "fake-bot-token"
    resolved[MetadataKeys.TELEGRAM_CHAT_ID] = "fake-chat-id"
    return ServiceContext(
        agent_name="daily_report",
        provider_name="",
        request_id="test-request-id",
        user_input="",
        metadata=resolved,
    )


class _RecordingHttpClient:
    """Injected as ``NotificationService``'s ``http_client`` for the
    happy-path scenario -- returns a minimal successful-shaped
    response instead of ever touching the network."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def post(self, url, *args, **kwargs):
        self.calls.append((url, args, kwargs))
        return SimpleNamespace(status_code=200, text="ok", json=lambda: {"ok": True})


def _build_app(*, http_client, context_factory) -> tuple[SimpleNamespace, _FakeManualScanService]:
    """Wires a real ``DailyReportOrchestrator`` (Activation 6.4, LOCKED,
    unmodified) over the real notification pipeline, with the two
    upstream business steps faked (see module docstring)."""
    scan_service = _FakeManualScanService()
    performance_service = _FakePerformanceSummaryProductionService()
    notification_builder = NotificationBuilder()

    notification_service = NotificationService(http_client=http_client)
    telegram_channel = TelegramNotificationChannel(
        notification_service=notification_service,
        service_context_factory=context_factory,
    )
    dispatcher = NotificationDispatcher(channels=[telegram_channel])
    notification_manager = NotificationManager(dispatcher)

    orchestrator = DailyReportOrchestrator(
        manual_scan_service=scan_service,
        performance_summary_production_service=performance_service,
        notification_builder=notification_builder,
        notification_manager=notification_manager,
    )

    app = SimpleNamespace(daily_report_orchestrator=orchestrator)
    return app, scan_service


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def scenario_1_missing_credentials_clean_failure() -> None:
    print("\n[Scenario 1] Telegram credentials missing -> clean failure, no raw traceback")
    app, scan_service = _build_app(
        http_client=_RecordingHttpClient(),
        context_factory=_no_credentials_context_factory,
    )

    handler = _ListLogHandler()
    main.logger.addHandler(handler)
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main._run_report_daily(app, "paper-id")
        output = buf.getvalue()
    finally:
        main.logger.removeHandler(handler)

    check(rc == 1, f"_run_report_daily returns non-zero on a credential failure, got {rc}")
    check("DAILY REPORT FAILED" in output, "a clean, labelled failure message is printed")
    check("Traceback" not in output, "no raw traceback text is printed to the caller")
    check(
        any("NotificationServiceError" in str(r.getMessage()) or r.exc_info for r in handler.records),
        "the failure is actually logged (with exc_info), not silently dropped",
    )
    check(scan_service.calls == [scan_service.calls[0]] if scan_service.calls else False,
          "the upstream scan step ran exactly once before the notification failed")


def scenario_2_network_failure_clean_failure() -> None:
    print("\n[Scenario 2] Telegram network failure -> clean failure, no raw traceback")
    app, scan_service = _build_app(
        http_client=_RaisingHttpClient(),
        context_factory=_with_credentials_context_factory,
    )

    handler = _ListLogHandler()
    main.logger.addHandler(handler)
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main._run_report_daily(app, "paper-id")
        output = buf.getvalue()
    finally:
        main.logger.removeHandler(handler)

    check(rc == 1, f"_run_report_daily returns non-zero on a network failure, got {rc}")
    check("DAILY REPORT FAILED" in output, "a clean, labelled failure message is printed")
    check("Traceback" not in output, "no raw traceback text is printed to the caller")
    check(len(handler.records) >= 1, "the network failure is actually logged")
    check(
        any(r.exc_info for r in handler.records),
        "the logged record carries exc_info (full failure detail preserved in logs, not on stdout)",
    )
    check(len(scan_service.calls) == 1, "the upstream scan step already ran/committed before the failure")


def scenario_3_happy_path_unaffected() -> None:
    print("\n[Scenario 3] Happy path: working Telegram send is unaffected by the fix")
    app, scan_service = _build_app(
        http_client=_RecordingHttpClient(),
        context_factory=_with_credentials_context_factory,
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main._run_report_daily(app, "paper-id")
    output = buf.getvalue()

    check(rc == 0, f"_run_report_daily returns 0 on a successful send, got {rc}")
    check("Daily Report Sent" in output, "the normal success output is printed")
    check("DAILY REPORT FAILED" not in output, "no failure message is printed on the happy path")
    check(len(scan_service.calls) == 1, "the scan step ran exactly once")


def scenario_4_no_rollback_of_committed_state() -> None:
    print("\n[Scenario 4] A notification failure never rolls back already-committed state")
    app, scan_service = _build_app(
        http_client=_RaisingHttpClient(),
        context_factory=_with_credentials_context_factory,
    )

    rc = main._run_report_daily(app, "paper-id")

    check(rc == 1, "the call still fails as expected")
    check(
        scan_service.calls == [scan_service.calls[0]],
        "the already-committed scan step's own record is untouched -- called once, never retried/undone here",
    )


def main_test_runner() -> int:
    scenario_1_missing_credentials_clean_failure()
    scenario_2_network_failure_clean_failure()
    scenario_3_happy_path_unaffected()
    scenario_4_no_rollback_of_committed_state()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 7 FIX BLOCKER #2 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for description in _FAILURES:
            print(f"  - {description}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main_test_runner())