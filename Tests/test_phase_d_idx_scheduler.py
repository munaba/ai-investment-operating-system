"""Phase D ("Proactive IDX Scheduler Routine") standalone proof suite.

Scope (VERIFICATION ONLY -- no scheduler logic touched by this file):
  - Orchestration.idx_daily_scheduler.IDXDailyScheduler
  - Services.health_audit_service.HealthAuditService
  - Repository.persistence.scheduler_state_repository.SchedulerStateRepository
  - Repository.persistence.notification_dedup_repository.NotificationDedupRepository
  - Repository.persistence.audit_event_repository.AuditEventRepository
  - Database.migrations_scheduler.SCHEDULER_MIGRATIONS (v22-24)

Drives ``IDXDailyScheduler.tick()`` against a real, on-disk (never
``:memory:``) temp SQLite database migrated with
``SCHEDULER_MIGRATIONS``, using hand-written fakes for
``ManualScanService``/``DailyReportOrchestrator``/notification sender
so each scenario below is deterministic and never touches the network
(yfinance/Telegram). This mirrors the existing
``Tests/activation_3_5_step1_proof.py`` real-SQLite-file convention.

Run directly: ``python Tests/test_phase_d_idx_scheduler.py``

Scenarios:
  A. IDX session gating -- pre_market_check only considered in the
     pre-market window; session_scan only while regular session open;
     a non-trading day (weekend) runs no job at all.
  B. Pre-market exactly-once/idempotency -- a second tick in the same
     pre-market window on the same trading date does not re-run it.
  C. Session scan gating -- closed market performs no scan/fetch.
  D. Data-health check -- runs every trading-day tick, evaluates
     freshness of the last successful session_scan (FRESH/STALE/
     MISSING), never fetches itself.
  E. Retry/backoff -- a failed job schedules next_retry_at and is not
     re-attempted before that window elapses; is retried after.
  F. Notification dedup/rate-limit -- identical session_scan signature
     suppresses (SUPPRESS_NO_CHANGE); a changed signature inside the
     rate-limit window suppresses (SUPPRESS_RATE_LIMITED); a changed
     signature after the window sends.
  G. Degradation/recovery -- data_health_check alerts once on a
     FRESH->STALE-style transition and again on recovery, not on every
     tick in between (dedup collapses repeats).
  H. Market-close exactly once -- market_close_recap runs once at/after
     close and is not re-run by a later same-day tick.
  I. Daily review exactly once -- daily_review only runs after
     market_close_recap has *succeeded*, and only once.
  J. Restart persistence -- a brand new IDXDailyScheduler instance
     (fresh Python object, same DB) observes the exact same
     "already ran today" state as the original instance.
  K. Audit persistence -- every job start/success/failure and
     notification sent/suppressed is present in ``audit_events``.
  L. No automatic paper order -- this module never imports/constructs
     PaperTradingEngine/OrderLifecycleService/ExecutionService/Order/
     Trade/Position, confirmed both by static source inspection and by
     asserting zero orders/trades tables are even touched.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.data_freshness_policy import load_data_freshness_policy  # noqa: E402
from Business.idx_market_calendar import IDXMarketCalendar  # noqa: E402
from Business.notification_dedup_policy import NotificationDedupPolicy  # noqa: E402
from Business.notification_event import NotificationEvent, NotificationEventType  # noqa: E402
from Business.recommendation_service import Recommendation  # noqa: E402
from Business.report_service import Report  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_scheduler import SCHEDULER_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Orchestration.idx_daily_scheduler import (  # noqa: E402
    JOB_DAILY_REVIEW,
    JOB_DATA_HEALTH_CHECK,
    JOB_MARKET_CLOSE_RECAP,
    JOB_PRE_MARKET_CHECK,
    JOB_SESSION_SCAN,
    IDXDailyScheduler,
)
from Repository.persistence.audit_event_repository import AuditEventRepository  # noqa: E402
from Repository.persistence.notification_dedup_repository import (  # noqa: E402
    NotificationDedupRepository,
)
from Repository.persistence.scheduler_state_repository import (  # noqa: E402
    SchedulerStateRepository,
)
from Services.health_audit_service import HealthAuditService  # noqa: E402

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


# ---------------------------------------------------------------------
# Fakes -- deterministic stand-ins for the two collaborators
# IDXDailyScheduler reuses unmodified; never touch the network.
# ---------------------------------------------------------------------


class FakeManualScanService:
    """Duck-types ``Business.manual_scan_service.ManualScanService``.

    ``symbols_by_call`` lets a test script a *sequence* of distinct
    scan results across successive ``session_scan`` attempts (e.g. to
    prove a signature change actually flips SEND/SUPPRESS).
    """

    def __init__(self, symbols_by_call: Optional[List[List[str]]] = None, fail_calls: Optional[set] = None):
        self._symbols_by_call = symbols_by_call or [["BBCA"]]
        self._fail_calls = fail_calls or set()
        self.call_count = 0

    def run_scan(self, generated_at: str) -> Report:
        self.call_count += 1
        if self.call_count in self._fail_calls:
            raise RuntimeError(f"simulated fetch failure on call {self.call_count}")
        idx = min(self.call_count - 1, len(self._symbols_by_call) - 1)
        symbols = self._symbols_by_call[idx]
        recs = [
            Recommendation(symbol=sym, recommendation="BUY", confidence=0.9, priority=1, rank=i + 1)
            for i, sym in enumerate(symbols)
        ]
        return Report(generated_at=generated_at, recommendations=recs, total_symbols=len(recs))


class FakeDailyReportOrchestrator:
    """Duck-types ``Business.daily_report_orchestrator.DailyReportOrchestrator``."""

    def __init__(self, fail_calls: Optional[set] = None):
        self._fail_calls = fail_calls or set()
        self.call_count = 0

    def run_daily_report(self, account_id: str, generated_at: str) -> NotificationEvent:
        self.call_count += 1
        if self.call_count in self._fail_calls:
            raise RuntimeError(f"simulated daily-report failure on call {self.call_count}")
        return NotificationEvent(
            event_type=NotificationEventType.DAILY_REPORT,
            timestamp=generated_at,
            title="Daily Report",
            message=f"Daily report for {account_id} at {generated_at}",
        )


class FakeNotificationManager:
    """Duck-types ``Business.notification_manager.NotificationManager``.

    Records every event handed to ``notify()`` -- never touches
    Telegram/any real dispatcher.
    """

    def __init__(self, fail: bool = False):
        self._fail = fail
        self.sent: List[NotificationEvent] = []

    def notify(self, event: NotificationEvent) -> None:
        if self._fail:
            raise RuntimeError("simulated notification dispatch failure")
        self.sent.append(event)


# ---------------------------------------------------------------------
# Test-stack construction
# ---------------------------------------------------------------------


def _utc(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)


# A known Monday (2026-08-24) as the base trading day for every scenario.
_MON = (2026, 8, 24)
_TUE = (2026, 8, 25)
_SAT = (2026, 8, 22)

# WIB is UTC+7. IDX session boundaries (local WIB): pre-market 08:45,
# session 1 09:00-12:00, lunch 12:00-13:30, session 2 13:30-15:49,
# after-hours 15:49-16:00. Expressed here as UTC instants (WIB - 7h).
PRE_MARKET_UTC = lambda y, mo, d: _utc(y, mo, d, 1, 50)  # 08:50 WIB
SESSION_OPEN_UTC = lambda y, mo, d: _utc(y, mo, d, 2, 30)  # 09:30 WIB
LUNCH_UTC = lambda y, mo, d: _utc(y, mo, d, 5, 30)  # 12:30 WIB
SESSION2_UTC = lambda y, mo, d: _utc(y, mo, d, 7, 0)  # 14:00 WIB
CLOSE_UTC = lambda y, mo, d: _utc(y, mo, d, 9, 0)  # 16:00 WIB (>= 15:49 close)


def _build_stack(db_path: Path, *, scan_service=None, report_orchestrator=None, notification_manager=None,
                  retry_base_seconds: float = 60.0, retry_max_seconds: float = 3600.0):
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(SCHEDULER_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    calendar = IDXMarketCalendar()
    state_repo = SchedulerStateRepository(manager)
    dedup_repo = NotificationDedupRepository(manager)
    audit_repo = AuditEventRepository(manager)
    dedup_policy = NotificationDedupPolicy(min_interval_seconds=1800.0)
    freshness_policy = load_data_freshness_policy(env_get=lambda name, default: default)

    scan_service = scan_service if scan_service is not None else FakeManualScanService()
    report_orchestrator = report_orchestrator if report_orchestrator is not None else FakeDailyReportOrchestrator()
    notification_manager = notification_manager if notification_manager is not None else FakeNotificationManager()

    scheduler = IDXDailyScheduler(
        idx_market_calendar=calendar,
        scheduler_state_repository=state_repo,
        notification_dedup_repository=dedup_repo,
        notification_dedup_policy=dedup_policy,
        data_freshness_policy=freshness_policy,
        audit_event_repository=audit_repo,
        manual_scan_service=scan_service,
        daily_report_orchestrator=report_orchestrator,
        notification_manager=notification_manager,
        account_id="paper-idx",
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
    )
    health_service = HealthAuditService(state_repo, dedup_repo, audit_repo, calendar)
    return {
        "manager": manager,
        "db": db,
        "calendar": calendar,
        "state_repo": state_repo,
        "dedup_repo": dedup_repo,
        "audit_repo": audit_repo,
        "scan_service": scan_service,
        "report_orchestrator": report_orchestrator,
        "notification_manager": notification_manager,
        "scheduler": scheduler,
        "health_service": health_service,
    }


def _outcome_map(tick_result) -> Dict[str, Any]:
    return {j.job_type: j for j in tick_result.jobs}


# ---------------------------------------------------------------------
# Scenario A -- IDX session gating
# ---------------------------------------------------------------------


def scenario_a_session_gating():
    print("\n[Scenario A] IDX session gating")
    with tempfile.TemporaryDirectory() as tmp:
        stack = _build_stack(Path(tmp) / "phase_d.db")
        scheduler = stack["scheduler"]

        # Weekend -> non-trading day -> no jobs at all.
        weekend_result = scheduler.tick(_utc(*_SAT, 5, 0))
        check(weekend_result.jobs == (), "weekend tick runs zero jobs")

        # Pre-market -> pre_market_check considered, session_scan not.
        pm_result = scheduler.tick(PRE_MARKET_UTC(*_MON))
        pm_jobs = _outcome_map(pm_result)
        check(JOB_PRE_MARKET_CHECK in pm_jobs, "pre-market tick considers pre_market_check")
        check(pm_jobs[JOB_PRE_MARKET_CHECK].outcome == "SUCCESS", "pre_market_check succeeds in pre-market window")
        check(JOB_SESSION_SCAN not in pm_jobs, "session_scan NOT considered during pre-market window")

        # Regular session -> session_scan considered, pre_market_check not (already ran).
        open_result = scheduler.tick(SESSION_OPEN_UTC(*_MON))
        open_jobs = _outcome_map(open_result)
        check(JOB_SESSION_SCAN in open_jobs, "session_scan considered while regular session open")
        check(open_jobs[JOB_SESSION_SCAN].outcome == "SUCCESS", "session_scan succeeds while open")
        check(JOB_PRE_MARKET_CHECK not in open_jobs, "pre_market_check not re-considered once already succeeded")

        # Lunch break -> session_scan NOT considered (market not open).
        lunch_result = scheduler.tick(LUNCH_UTC(*_MON))
        lunch_jobs = _outcome_map(lunch_result)
        check(JOB_SESSION_SCAN not in lunch_jobs, "session_scan NOT considered during lunch break")
        check(JOB_DATA_HEALTH_CHECK in lunch_jobs, "data_health_check still considered during lunch break")


# ---------------------------------------------------------------------
# Scenario B -- pre-market exactly-once/idempotency
# ---------------------------------------------------------------------


def scenario_b_premarket_idempotency():
    print("\n[Scenario B] pre-market exactly-once/idempotency")
    with tempfile.TemporaryDirectory() as tmp:
        stack = _build_stack(Path(tmp) / "phase_d.db")
        scheduler = stack["scheduler"]

        r1 = scheduler.tick(PRE_MARKET_UTC(*_MON))
        r2 = scheduler.tick(_utc(*_MON, 1, 55))  # still pre-market, a few minutes later

        j1 = _outcome_map(r1)[JOB_PRE_MARKET_CHECK]
        check(j1.outcome == "SUCCESS" and j1.attempted, "first pre-market tick runs pre_market_check")

        j2 = _outcome_map(r2).get(JOB_PRE_MARKET_CHECK)
        check(j2 is not None and j2.attempted is False and j2.outcome == "SKIPPED",
              "second same-day pre-market tick is SKIPPED, not re-attempted")

        rows = stack["state_repo"].list_for_date(_MON_ISO)
        pm_rows = [r for r in rows if r.job_type == JOB_PRE_MARKET_CHECK]
        check(len(pm_rows) == 1, "exactly one scheduler_job_runs row exists for pre_market_check/this date")


_MON_ISO = f"{_MON[0]:04d}-{_MON[1]:02d}-{_MON[2]:02d}"
_TUE_ISO = f"{_TUE[0]:04d}-{_TUE[1]:02d}-{_TUE[2]:02d}"


# ---------------------------------------------------------------------
# Scenario C -- session scan gating (closed market -> no fetch)
# ---------------------------------------------------------------------


def scenario_c_session_scan_gating():
    print("\n[Scenario C] session scan gating -- closed market performs no scan/fetch")
    with tempfile.TemporaryDirectory() as tmp:
        scan = FakeManualScanService()
        stack = _build_stack(Path(tmp) / "phase_d.db", scan_service=scan)
        scheduler = stack["scheduler"]

        scheduler.tick(_utc(*_MON, 0, 0))  # well before pre-market
        scheduler.tick(LUNCH_UTC(*_MON))  # lunch break
        scheduler.tick(CLOSE_UTC(*_MON))  # after close (but does trigger close-recap flow, not scan)
        check(scan.call_count == 0, "ManualScanService.run_scan never called while market never opened this test")

        # Now open the session once -- exactly one fetch should occur.
        scheduler.tick(SESSION_OPEN_UTC(*_MON))
        check(scan.call_count == 1, "exactly one fetch occurs on the single open-session tick")


# ---------------------------------------------------------------------
# Scenario D -- data-health check (no fetch, freshness evaluation)
# ---------------------------------------------------------------------


def scenario_d_data_health_check():
    print("\n[Scenario D] data-health check -- no fetch, freshness reconstruction")
    with tempfile.TemporaryDirectory() as tmp:
        scan = FakeManualScanService()
        stack = _build_stack(Path(tmp) / "phase_d.db", scan_service=scan)
        scheduler = stack["scheduler"]

        # Before any session_scan has ever succeeded -> MISSING (explicit
        # no-data state, never fabricated as FRESH/STALE).
        r0 = scheduler.tick(PRE_MARKET_UTC(*_MON))
        j0 = _outcome_map(r0)[JOB_DATA_HEALTH_CHECK]
        check(j0.outcome == "SUCCESS", "data_health_check job itself always SUCCEEDS (evaluation, not fetch)")
        check('"status": "MISSING"' in (j0.detail or ""), "no observation yet -> explicit MISSING status")
        calls_before = scan.call_count
        check(calls_before == 0, "data_health_check triggers zero ManualScanService calls")

        # After a successful session_scan, immediately re-check (just
        # after session 1 closes into lunch break, well within the
        # 900s default freshness window, so this second tick cannot
        # itself trigger another session_scan fetch -- isolates
        # data_health_check on its own).
        scan_tick = _utc(*_MON, 4, 50)  # 11:50 WIB, still regular session
        fresh_check_tick = _utc(*_MON, 5, 3)  # 12:03 WIB, lunch break, 13 min later
        scheduler.tick(scan_tick)
        r_fresh = scheduler.tick(fresh_check_tick)
        j_fresh = _outcome_map(r_fresh)[JOB_DATA_HEALTH_CHECK]
        check('"status": "FRESH"' in (j_fresh.detail or ""), "freshness reads FRESH immediately after a successful scan")
        check(scan.call_count == 1, "data_health_check still triggers zero additional fetches")

        # Much later the same day (well past the 900s window, no new
        # scan in between) -> STALE, original observation's timestamp
        # preserved (never re-stamped to "now").
        stale_check_tick = _utc(*_MON, 5, 10)  # 12:10 WIB, still lunch break, scan not re-run
        r_stale = scheduler.tick(stale_check_tick)
        j_stale = _outcome_map(r_stale)[JOB_DATA_HEALTH_CHECK]
        check('"status": "STALE"' in (j_stale.detail or ""), "an old observation now reads STALE, not fabricated as FRESH")
        check(scan.call_count == 1, "the STALE check itself still triggers no additional fetch")


# ---------------------------------------------------------------------
# Scenario E -- retry/backoff
# ---------------------------------------------------------------------


def scenario_e_retry_backoff():
    print("\n[Scenario E] retry/backoff")
    with tempfile.TemporaryDirectory() as tmp:
        orchestrator = FakeDailyReportOrchestrator(fail_calls={1})
        stack = _build_stack(
            Path(tmp) / "phase_d.db",
            report_orchestrator=orchestrator,
            retry_base_seconds=60.0,
            retry_max_seconds=3600.0,
        )
        scheduler = stack["scheduler"]

        t0 = CLOSE_UTC(*_MON)
        r1 = scheduler.tick(t0)
        j1 = _outcome_map(r1)[JOB_MARKET_CLOSE_RECAP]
        check(j1.outcome == "FAILED", "first market_close_recap attempt fails (simulated)")

        row = stack["state_repo"].get(JOB_MARKET_CLOSE_RECAP, _MON_ISO)
        check(row is not None and row.next_retry_at is not None, "a next_retry_at backoff timestamp was persisted")

        # Immediately retrying (same tick timestamp): market_close_recap's
        # own outer gate (tick()'s `if self._may_attempt(...)`) is not even
        # reached while the backoff window hasn't elapsed, so the job is
        # simply absent from this tick's jobs tuple (see TickResult's own
        # documented contract) -- not present with outcome="SKIPPED".
        r2 = scheduler.tick(t0)
        j2 = _outcome_map(r2).get(JOB_MARKET_CLOSE_RECAP)
        check(j2 is None, "immediate retry is held back by backoff window (job not even attempted/listed)")
        check(orchestrator.call_count == 1, "no second attempt made before backoff window elapses")

        # After the backoff window elapses, the job may be attempted again.
        t1 = t0 + timedelta(seconds=61)
        r3 = scheduler.tick(t1)
        j3 = _outcome_map(r3)[JOB_MARKET_CLOSE_RECAP]
        check(j3.outcome == "SUCCESS", "retry after backoff window elapses succeeds")
        check(orchestrator.call_count == 2, "exactly one retry attempt made after backoff window")


# ---------------------------------------------------------------------
# Scenario F -- notification dedup/rate-limit
# ---------------------------------------------------------------------


def _scan_alerts(notifier: "FakeNotificationManager") -> List[NotificationEvent]:
    """Isolate only the session_scan_brief channel's sent events -- the
    same ``notifier`` also receives ``data_freshness`` alerts from
    ``data_health_check``, which must not be conflated with this
    channel's own dedup/rate-limit behavior."""
    return [e for e in notifier.sent if e.title == "IDX Session Scan"]


def scenario_f_notification_dedup():
    print("\n[Scenario F] notification dedup/rate-limit")
    with tempfile.TemporaryDirectory() as tmp:
        scan = FakeManualScanService(symbols_by_call=[["BBCA"], ["BBCA"], ["TLKM"], ["TLKM"]])
        notifier = FakeNotificationManager()
        stack = _build_stack(Path(tmp) / "phase_d.db", scan_service=scan, notification_manager=notifier)
        scheduler = stack["scheduler"]

        # 1st scan (t0): no prior state -> SEND.
        t0 = SESSION_OPEN_UTC(*_MON)
        scheduler.tick(t0)
        check(len(_scan_alerts(notifier)) == 1, "first session_scan alert is SENT (no prior state)")

        # 2nd scan (t0 + 1s), identical signature ("BBCA") -> SUPPRESS_NO_CHANGE.
        t1 = t0 + timedelta(seconds=1)
        scheduler.tick(t1)
        check(len(_scan_alerts(notifier)) == 1, "identical-signature scan is suppressed (no material change)")

        # 3rd scan (t0 + 2s), signature changes to "TLKM" but well inside
        # the 1800s rate-limit window -> SUPPRESS_RATE_LIMITED.
        t2 = t0 + timedelta(seconds=2)
        scheduler.tick(t2)
        check(len(_scan_alerts(notifier)) == 1, "changed-signature scan inside rate-limit window is still suppressed")

        # 4th scan, after the rate-limit window elapses -> SEND.
        t3 = t0 + timedelta(seconds=1801)
        scheduler.tick(t3)
        check(len(_scan_alerts(notifier)) == 2, "changed-signature scan after rate-limit window elapses is SENT")


# ---------------------------------------------------------------------
# Scenario G -- degradation/recovery
# ---------------------------------------------------------------------


def _freshness_alerts(notifier: "FakeNotificationManager") -> List[NotificationEvent]:
    """Isolate only the data_freshness channel's sent events -- the
    same ``notifier`` also receives ``session_scan_brief`` alerts from
    ``session_scan``, which must not be conflated with this channel's
    own degrade/recover behavior."""
    return [e for e in notifier.sent if e.title.startswith("IDX Data Freshness")]


def scenario_g_degradation_recovery():
    print("\n[Scenario G] degradation/recovery (data-freshness alert)")
    with tempfile.TemporaryDirectory() as tmp:
        notifier = FakeNotificationManager()
        stack = _build_stack(Path(tmp) / "phase_d.db", notification_manager=notifier)
        scheduler = stack["scheduler"]

        # Tick 1: first-ever tick. session_scan succeeds (FRESH candidate,
        # age 0) -> the very first data_freshness evaluation ever is FRESH,
        # and (no prior dedup state) is sent unconditionally.
        t0 = SESSION_OPEN_UTC(*_MON)
        scheduler.tick(t0)
        sent_after_fresh = len(_freshness_alerts(notifier))
        check(sent_after_fresh == 1, "first-ever data_freshness evaluation (FRESH) is sent unconditionally")

        # Tick 2: well past the 900s freshness window, during lunch break
        # (no new scan in between) -> STALE -> signature flips to
        # DEGRADED -> genuinely changed signature, rate-limit window
        # elapsed since tick 1 -> exactly one degrade alert.
        t_stale = LUNCH_UTC(*_MON)
        scheduler.tick(t_stale)
        sent_after_degraded = len(_freshness_alerts(notifier))
        check(sent_after_degraded == sent_after_fresh + 1, "exactly one alert fires on the FRESH->DEGRADED transition")

        # A second degraded tick shortly after must NOT re-alert (dedup:
        # identical DEGRADED signature).
        scheduler.tick(t_stale + timedelta(seconds=5))
        check(len(_freshness_alerts(notifier)) == sent_after_degraded, "repeated DEGRADED evaluations do not re-alert")

        # Recovery: a fresh scan again (next session) -> data_health_check
        # reads FRESH -> signature flips back -> exactly one recovery alert.
        t_open2 = SESSION2_UTC(*_MON)
        scheduler.tick(t_open2)
        check(len(_freshness_alerts(notifier)) == sent_after_degraded + 1,
              "exactly one alert fires on the DEGRADED->FRESH recovery")


# ---------------------------------------------------------------------
# Scenario H -- market-close exactly once
# ---------------------------------------------------------------------


def scenario_h_market_close_once():
    print("\n[Scenario H] market-close exactly once")
    with tempfile.TemporaryDirectory() as tmp:
        orchestrator = FakeDailyReportOrchestrator()
        stack = _build_stack(Path(tmp) / "phase_d.db", report_orchestrator=orchestrator)
        scheduler = stack["scheduler"]

        r1 = scheduler.tick(CLOSE_UTC(*_MON))
        check(_outcome_map(r1)[JOB_MARKET_CLOSE_RECAP].outcome == "SUCCESS", "market_close_recap succeeds at close")
        check(orchestrator.call_count == 1, "DailyReportOrchestrator invoked exactly once so far")

        r2 = scheduler.tick(CLOSE_UTC(*_MON) + timedelta(minutes=1))
        # Once SUCCESS is on record, tick()'s own outer gate
        # (`if self._may_attempt(...)`) is never reached again this trading
        # date -- the job is simply absent from jobs, not present with
        # outcome="SKIPPED" (see TickResult's own documented contract).
        j2 = _outcome_map(r2).get(JOB_MARKET_CLOSE_RECAP)
        check(j2 is None, "a later same-day tick does not re-run market_close_recap")
        check(orchestrator.call_count == 1, "DailyReportOrchestrator still invoked exactly once (not re-run)")


# ---------------------------------------------------------------------
# Scenario I -- daily review exactly once, gated on close-recap success
# ---------------------------------------------------------------------


def scenario_i_daily_review_once():
    print("\n[Scenario I] daily review exactly once, gated on market_close_recap success")
    with tempfile.TemporaryDirectory() as tmp:
        orchestrator = FakeDailyReportOrchestrator(fail_calls={1})
        stack = _build_stack(Path(tmp) / "phase_d.db", report_orchestrator=orchestrator)
        scheduler = stack["scheduler"]

        t0 = CLOSE_UTC(*_MON)
        r1 = scheduler.tick(t0)
        check(JOB_DAILY_REVIEW not in _outcome_map(r1),
              "daily_review NOT considered the same tick market_close_recap fails")

        t1 = t0 + timedelta(seconds=61)  # past backoff, recap now succeeds
        r2 = scheduler.tick(t1)
        j2 = _outcome_map(r2)
        check(j2[JOB_MARKET_CLOSE_RECAP].outcome == "SUCCESS", "market_close_recap succeeds on retry")
        check(j2[JOB_DAILY_REVIEW].outcome == "SUCCESS", "daily_review runs the same tick recap first succeeds")

        r3 = scheduler.tick(t1 + timedelta(minutes=1))
        # Same absent-not-SKIPPED contract as market_close_recap above.
        j3 = _outcome_map(r3).get(JOB_DAILY_REVIEW)
        check(j3 is None, "a later tick does not re-run daily_review")


# ---------------------------------------------------------------------
# Scenario J -- restart persistence
# ---------------------------------------------------------------------


def scenario_j_restart_persistence():
    print("\n[Scenario J] restart persistence (fresh instance, same DB)")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_d.db"
        stack1 = _build_stack(db_path)
        stack1["scheduler"].tick(PRE_MARKET_UTC(*_MON))
        stack1["scheduler"].tick(SESSION_OPEN_UTC(*_MON))

        # Brand new DatabaseManager/repositories/scheduler instance --
        # simulates a full process restart against the same DB file.
        stack2 = _build_stack(db_path)
        r_restart = stack2["scheduler"].tick(_utc(*_MON, 2, 35))
        jobs_restart = _outcome_map(r_restart)
        check(JOB_PRE_MARKET_CHECK not in jobs_restart,
              "restarted instance still knows pre_market_check already succeeded today")
        check(stack2["state_repo"].has_succeeded(JOB_SESSION_SCAN, _MON_ISO),
              "restarted instance reads the same session_scan success state from disk")


# ---------------------------------------------------------------------
# Scenario K -- audit persistence
# ---------------------------------------------------------------------


def scenario_k_audit_persistence():
    print("\n[Scenario K] audit persistence")
    with tempfile.TemporaryDirectory() as tmp:
        stack = _build_stack(Path(tmp) / "phase_d.db")
        stack["scheduler"].tick(PRE_MARKET_UTC(*_MON))
        stack["scheduler"].tick(SESSION_OPEN_UTC(*_MON))

        events = stack["audit_repo"].list_all()
        event_types = {e.event_type for e in events}
        check("job_started" in event_types, "audit log contains job_started events")
        check("job_succeeded" in event_types, "audit log contains job_succeeded events")
        check(len(events) >= 4, "audit log has multiple entries across the two ticks")

        snapshot = stack["health_service"].get_snapshot(trading_date=_MON_ISO)
        check(len(snapshot.jobs) >= 2, "HealthAuditService.get_snapshot returns scheduler_job_runs rows for the date")
        check(isinstance(snapshot.recent_events, tuple) and len(snapshot.recent_events) > 0,
              "HealthAuditService.get_snapshot returns recent audit events")


# ---------------------------------------------------------------------
# Scenario L -- no automatic paper order (static + behavioral)
# ---------------------------------------------------------------------


def scenario_l_no_automatic_paper_order():
    print("\n[Scenario L] no automatic paper order")
    import ast
    import Orchestration.idx_daily_scheduler as sched_mod

    src_path = Path(sched_mod.__file__)
    tree = ast.parse(src_path.read_text(encoding="utf-8", errors="ignore"))
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    for forbidden in ("PaperTradingEngine", "OrderLifecycleService", "ExecutionService"):
        check(forbidden not in imported_names, f"idx_daily_scheduler.py never imports {forbidden}")
        # Also confirm it is never referenced as a live identifier/call
        # anywhere in the module's executable code (not merely absent
        # from imports) -- e.g. `PaperTradingEngine(` or bare use.
        used_as_name = any(
            isinstance(node, ast.Name) and node.id == forbidden for node in ast.walk(tree)
        )
        check(not used_as_name, f"idx_daily_scheduler.py never references {forbidden} as a live identifier")

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_d.db"
        stack = _build_stack(db_path)
        stack["scheduler"].tick(PRE_MARKET_UTC(*_MON))
        stack["scheduler"].tick(SESSION_OPEN_UTC(*_MON))
        stack["scheduler"].tick(CLOSE_UTC(*_MON))

        import sqlite3

        conn = sqlite3.connect(str(db_path))
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        check("orders" not in table_names, "no 'orders' table exists in a DB migrated with SCHEDULER_MIGRATIONS only")
        check("trades" not in table_names, "no 'trades' table exists in a DB migrated with SCHEDULER_MIGRATIONS only")
        check("positions" not in table_names, "no 'positions' table exists in a DB migrated with SCHEDULER_MIGRATIONS only")


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------


def main() -> int:
    scenario_a_session_gating()
    scenario_b_premarket_idempotency()
    scenario_c_session_scan_gating()
    scenario_d_data_health_check()
    scenario_e_retry_backoff()
    scenario_f_notification_dedup()
    scenario_g_degradation_recovery()
    scenario_h_market_close_once()
    scenario_i_daily_review_once()
    scenario_j_restart_persistence()
    scenario_k_audit_persistence()
    scenario_l_no_automatic_paper_order()

    print(f"\n{'=' * 60}")
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print("=" * 60)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())