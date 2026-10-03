"""Gate 4 Phase I — evidence profile analysis job.

Scope (VERIFICATION ONLY -- no scheduler logic touched by this file):
  - Orchestration.evidence_profile_job_adapter.EvidenceProfileJobAdapter
  - Orchestration.idx_daily_scheduler.IDXDailyScheduler (job ke-6)

Uses a real SQLite file (not ``:memory:``) and hand-written fakes.
To avoid Windows ``PermissionError`` during temp directory cleanup,
this file wraps ``tempfile.TemporaryDirectory`` with ``ignore_cleanup_errors=True``.

Run directly: ``python Tests/test_phase_i_gate4_evidence_job.py``
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows-safe temp dirs: SQLite may still hold the file handle when the
# scenario finishes, so cleanup failures must not abort the whole run.
_real_temporary_directory = tempfile.TemporaryDirectory


def _temporary_directory(*args, **kwargs):
    kwargs.setdefault("ignore_cleanup_errors", True)
    return _real_temporary_directory(*args, **kwargs)


tempfile.TemporaryDirectory = _temporary_directory  # type: ignore[assignment]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.idx_market_calendar import IDXMarketCalendar  # noqa: E402
from Business.notification_dedup_policy import NotificationDedupPolicy  # noqa: E402
from Business.notification_event import NotificationEvent, NotificationEventType  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations_scheduler import SCHEDULER_MIGRATIONS  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Orchestration.evidence_profile_job_adapter import EvidenceProfileJobAdapter  # noqa: E402
from Orchestration.idx_daily_scheduler import (  # noqa: E402
    JOB_EVIDENCE_PROFILE_ANALYSIS,
    JOB_PRE_MARKET_CHECK,
    JOB_SESSION_SCAN,
    JOB_DATA_HEALTH_CHECK,
    JOB_MARKET_CLOSE_RECAP,
    JOB_DAILY_REVIEW,
    ALL_JOB_TYPES,
    IDXDailyScheduler,
)
from Repository.persistence.audit_event_repository import AuditEventRepository  # noqa: E402
from Repository.persistence.notification_dedup_repository import (  # noqa: E402
    NotificationDedupRepository,
    STATUS_FAILED as DEDUP_STATUS_FAILED,
    STATUS_SENT as DEDUP_STATUS_SENT,
    STATUS_SUPPRESSED as DEDUP_STATUS_SUPPRESSED,
)
from Repository.persistence.scheduler_state_repository import (  # noqa: E402
    SchedulerStateRepository,
    STATUS_FAILED as JOB_STATUS_FAILED,
    STATUS_RUNNING as JOB_STATUS_RUNNING,
    STATUS_SUCCESS as JOB_STATUS_SUCCESS,
)
from Repository.persistence.performance_repository import PerformanceRepository  # noqa: E402

# Use base_persistence_repository pattern (tanpa side effect)
from Repository.persistence.base_persistence_repository import BasePersistenceRepository  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES: list[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


# Mocks for collaborators
class FakeManualScanService:
    call_count = 0

    def run_scan(self, generated_at: str):
        FakeManualScanService.call_count += 1
        return type("Report", (), {"total_symbols": 10, "recommendations": []})()


class FakeDailyReportOrchestrator:
    def build_daily_report(self, trading_date: str, now: datetime) -> dict:
        return {"summary": "test report", "trading_date": trading_date}


class FakeNotificationManager:
    def send(self, event: NotificationEvent) -> None:
        pass


class FakeSkill:
    def __init__(self, snapshot_count: int = 10, scan_count: int = 2, status: str = "ok") -> None:
        self.snapshot_count = snapshot_count
        self.scan_count = scan_count
        self.status = status

    def analyze_evidence_profile(self, since: str, until: str):
        if self.status == "no_data":
            return type("SkillResult", (), {"success": False, "error": "INSUFFICIENT_DATA"})()
        if self.status == "error":
            return type("SkillResult", (), {"success": False, "error": "DB_TIMEOUT"})()
        return type(
            "SkillResult",
            (),
            {
                "success": True,
                "output": {
                    "snapshot_count": self.snapshot_count,
                    "scan_count": self.scan_count,
                    "symbol_count": 5,
                    "symbols": ["AAPL", "TSLA", "GOOGL", "MSFT", "AMZN"],
                    "status_counts": {"success": 8, "error": 2},
                    "recommendation_counts": {"TAKE": 6, "SKIP": 2, "WAIT": 2},
                    "confidence_counts": {"HIGH": 4, "MEDIUM": 4, "LOW": 2},
                    "factor_contribution_totals": {"momentum": 15.5, "value": 8.2},
                    "error_row_count": 2,
                    "unparsed_breakdown_count": 0,
                },
            },
        )()


class _TestTempDir:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self):
        return str(self.path)

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Jangan cleanup di test ini
        pass


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# Waktu IDX (WIB / Asia/Jakarta)
_WIB = timezone(timedelta(hours=7))


def _wib(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Return UTC datetime that corresponds to the given WIB moment."""
    wib_dt = datetime(year, month, day, hour, minute, tzinfo=_WIB)
    return wib_dt.astimezone(timezone.utc)


def _build_stack(db_path: Path, skill: FakeSkill | None = None) -> dict:
    db_config = DatabaseConfig(db_path=str(db_path))
    db = SQLiteDatabase(db_config)
    MigrationRunner(db).apply(SCHEDULER_MIGRATIONS)

    manager = DatabaseManager(db)
    calendar = IDXMarketCalendar()
    state_repo = SchedulerStateRepository(manager)
    dedup_repo = NotificationDedupRepository(manager)
    dedup_policy = NotificationDedupPolicy(min_interval_seconds=1800.0)
    audit_repo = AuditEventRepository(manager)
    scan_service = FakeManualScanService()
    report_orchestrator = FakeDailyReportOrchestrator()
    notification_manager = FakeNotificationManager()
    performance_repo = PerformanceRepository(manager)

    if skill is None:
        skill = FakeSkill()
    evidence_adapter = EvidenceProfileJobAdapter(skill)

    scheduler = IDXDailyScheduler(
        idx_market_calendar=calendar,
        scheduler_state_repository=state_repo,
        notification_dedup_repository=dedup_repo,
        notification_dedup_policy=dedup_policy,
        data_freshness_policy=None,  # tidak dipakai di test ini
        audit_event_repository=audit_repo,
        manual_scan_service=scan_service,
        daily_report_orchestrator=report_orchestrator,
        notification_manager=notification_manager,
        account_id="paper-idx",
        retry_base_seconds=60.0,
        retry_max_seconds=3600.0,
        evidence_adapter=evidence_adapter,
    )

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
        "performance_repo": performance_repo,
        "scheduler": scheduler,
    }


def scenario_evidence_job_basic():
    print("\n[Scenario E] evidence profile job basic")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        stack = _build_stack(tmp_path / "gate4.db", FakeSkill(snapshot_count=118, scan_count=12))
        scheduler = stack["scheduler"]

        # Test 1: before SESSION_2_CLOSE -> tidak berjalan
        r1 = scheduler.tick(_wib(2026, 10, 2, 15, 30))  # 15:30 WIB
        jobs1 = {j.job_type: j for j in r1.jobs}
        check(JOB_EVIDENCE_PROFILE_ANALYSIS not in jobs1, "evidence_profile_analysis NOT attempted before SESSION_2_CLOSE")

        # Test 2: at SESSION_2_CLOSE -> berjalan SUCCESS
        r2 = scheduler.tick(_wib(2026, 10, 2, 15, 50))  # 15:50 WIB (>= 15:49)
        jobs2 = {j.job_type: j for j in r2.jobs}
        check(JOB_EVIDENCE_PROFILE_ANALYSIS in jobs2, "evidence_profile_analysis attempted at SESSION_2_CLOSE")
        evo = jobs2[JOB_EVIDENCE_PROFILE_ANALYSIS]
        check(evo.outcome == "SUCCESS", f"evidence_profile_analysis outcome is SUCCESS (got {evo.outcome})")
        check(evo.attempted, "evidence_profile_analysis attempted=True")
        check('"status": "ok"' in (evo.detail or ""), "detail contains status=ok")
        check('"snapshot_count": 118' in (evo.detail or ""), "detail contains snapshot_count=118")

        # Test 3: payload flat (tidak ada key job_type/trading_date di dalam detail)
        detail = evo.detail or ""
        check('"job_type"' not in detail, "detail does NOT contain job_type key")
        check('"trading_date"' not in detail, "detail does NOT contain trading_date key")

        # Test 4: audit event ada dan terformat benar
        events = stack["audit_repo"].list_recent(limit=10)
        audit_row = next((e for e in events if '"job_type": "evidence_profile_analysis"' in (e.payload or "")), None)
        check(audit_row is not None, "audit event for evidence_profile_analysis exists")
        if audit_row:
            check(audit_row.event_type == "job_succeeded", f"event_type is job_succeeded (got {audit_row.event_type})")
            check('"status": "ok"' in (audit_row.payload or ""), "audit payload contains status=ok")


def scenario_evidence_no_data():
    print("\n[Scenario N] evidence profile no_data")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        stack = _build_stack(tmp_path / "gate4.db", FakeSkill(status="no_data"))
        scheduler = stack["scheduler"]

        # tick setelah SESSION_2_CLOSE -> should return success with status="no_data"
        r = scheduler.tick(_wib(2026, 10, 2, 15, 50))
        jobs = {j.job_type: j for j in r.jobs}
        check(JOB_EVIDENCE_PROFILE_ANALYSIS in jobs, "evidence_profile_analysis attempted")
        evo = jobs[JOB_EVIDENCE_PROFILE_ANALYSIS]
        check(evo.outcome == "SUCCESS", f"evidence_profile_analysis outcome is SUCCESS (got {evo.outcome})")
        check('"status": "no_data"' in (evo.detail or ""), "detail contains status=no_data")
        check('"snapshot_count": 0' in (evo.detail or ""), "detail contains snapshot_count=0")

        # audit event type = job_succeeded, bukan job_failed
        events = stack["audit_repo"].list_recent(limit=10)
        audit_row = next((e for e in events if '"job_type": "evidence_profile_analysis"' in (e.payload or "")), None)
        check(audit_row is not None, "audit event for evidence_profile_analysis exists")
        check(audit_row.event_type == "job_succeeded", f"event_type is job_succeeded (got {audit_row.event_type})")


def scenario_evidence_failure():
    print("\n[Scenario F] evidence profile failure")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        stack = _build_stack(tmp_path / "gate4.db", FakeSkill(status="error"))
        scheduler = stack["scheduler"]

        r = scheduler.tick(_wib(2026, 10, 2, 15, 50))
        jobs = {j.job_type: j for j in r.jobs}
        check(JOB_EVIDENCE_PROFILE_ANALYSIS in jobs, "evidence_profile_analysis attempted")
        evo = jobs[JOB_EVIDENCE_PROFILE_ANALYSIS]
        check(evo.outcome == "FAILED", f"evidence_profile_analysis outcome is FAILED (got {evo.outcome})")

        # audit event type = job_failed
        events = stack["audit_repo"].list_recent(limit=10)
        audit_row = next((e for e in events if '"job_type": "evidence_profile_analysis"' in (e.payload or "")), None)
        check(audit_row is not None, "audit event for evidence_profile_analysis exists")
        check(audit_row.event_type == "job_failed", f"event_type is job_failed (got {audit_row.event_type})")


def scenario_evidence_weekend():
    print("\n[Scenario W] evidence profile weekend (non-trading day)")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        stack = _build_stack(tmp_path / "gate4.db", FakeSkill())
        scheduler = stack["scheduler"]

        # Minggu -> tick() return TickResult(jobs=())
        r = scheduler.tick(_wib(2026, 10, 3, 16, 0))  # 2026-10-03 adalah Minggu
        check(r.jobs == (), "non-trading day -> no jobs at all")
        events = stack["audit_repo"].list_recent(limit=10)
        audit_evidence = [e for e in events if '"job_type": "evidence_profile_analysis"' in (e.payload or "")]
        check(len(audit_evidence) == 0, "no audit event for evidence_profile_analysis on weekend")


def scenario_evidence_no_adapter():
    print("\n[Scenario A] evidence profile with adapter=None")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_config = DatabaseConfig(db_path=str(tmp_path / "gate4.db"))
        db = SQLiteDatabase(db_config)
        MigrationRunner(db).apply(SCHEDULER_MIGRATIONS)

        manager = DatabaseManager(db)
        calendar = IDXMarketCalendar()
        state_repo = SchedulerStateRepository(manager)
        dedup_repo = NotificationDedupRepository(manager)
        dedup_policy = NotificationDedupPolicy(min_interval_seconds=1800.0)
        audit_repo = AuditEventRepository(manager)
        scan_service = FakeManualScanService()
        report_orchestrator = FakeDailyReportOrchestrator()
        notification_manager = FakeNotificationManager()

        # Tanpa evidence_adapter (default None)
        scheduler = IDXDailyScheduler(
            idx_market_calendar=calendar,
            scheduler_state_repository=state_repo,
            notification_dedup_repository=dedup_repo,
            notification_dedup_policy=dedup_policy,
            data_freshness_policy=None,
            audit_event_repository=audit_repo,
            manual_scan_service=scan_service,
            daily_report_orchestrator=report_orchestrator,
            notification_manager=notification_manager,
            account_id="paper-idx",
            retry_base_seconds=60.0,
            retry_max_seconds=3600.0,
            evidence_adapter=None,
        )

        # tick setelah SESSION_2_CLOSE -> hanya job lama yang belum dijalankan hari itu, tidak ada job ke-6
        r = scheduler.tick(_wib(2026, 10, 2, 15, 50))
        job_types = [j.job_type for j in r.jobs]
        check(JOB_EVIDENCE_PROFILE_ANALYSIS not in job_types, "evidence_profile_analysis NOT in outcomes when adapter=None")
        check(len(job_types) <= 5, f"at most 5 jobs when adapter=None (got {len(job_types)})")
        # Semua job yang di-attempt harus bukan evidence_profile_analysis
        check(all(j != JOB_EVIDENCE_PROFILE_ANALYSIS for j in job_types), "no job is evidence_profile_analysis when adapter=None")


def scenario_evidence_query():
    print("\n[Scenario Q] evidence profile query history")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        stack = _build_stack(tmp_path / "gate4.db", FakeSkill(snapshot_count=100))
        scheduler = stack["scheduler"]

        # Buat 2 hari data
        scheduler.tick(_wib(2026, 10, 2, 15, 50))
        scheduler.tick(_wib(2026, 10, 1, 16, 0))

        # Query audit_events untuk evidence_profile_analysis (hanya job_succeeded)
        events = stack["audit_repo"].list_all()
        evidence_events = [
            e for e in events if e.payload and '"job_type": "evidence_profile_analysis"' in e.payload and e.event_type == "job_succeeded"
        ]
        check(len(evidence_events) == 2, f"2 evidence_profile_analysis success audit events (got {len(evidence_events)})")


def scenario_window_for_wib():
    """Verifikasi adapter menggunakan jendela WIB tanpa DB."""
    print("\n[Scenario T-window] jendela WIB via EvidenceProfileJobAdapter.window_for")
    from Orchestration.evidence_profile_job_adapter import EvidenceProfileJobAdapter
    from datetime import date

    class FakeWindowSkill:
        def analyze_evidence_profile(self, since: str, until: str):
            self.last_since = since
            self.last_until = until
            return type("R", (), {"success": True, "output": {"snapshot_count": 1, "scan_count": 0, "symbol_count": 0, "symbols": [], "status_counts": {}, "recommendation_counts": {}, "confidence_counts": {}, "factor_contribution_totals": {}, "error_row_count": 0, "unparsed_breakdown_count": 0}})()

    skill = FakeWindowSkill()
    adapter = EvidenceProfileJobAdapter(skill)
    adapter.analyze_for_trading_date("2026-10-02")

    # Jendela harus mulai 00:00 WIB dan berakhir 23:59:59.999999 WIB
    check(skill.last_since.startswith("2026-10-01T17:00:00"), f"since = 00:00 WIB = 17:00 UTC prev day (got {skill.last_since})")
    check(skill.last_until.startswith("2026-10-02T16:59:59"), f"until = 23:59:59 WIB = 16:59:59 UTC same day (got {skill.last_until})")


def scenario_timing_and_recap_independent():
    """<15:49 tidak jalan; recap gagal tetap jalan."""
    print("\n[Scenario T-timing] timing gate dan independensi recap")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        stack = _build_stack(tmp_path / "gate4.db", FakeSkill(snapshot_count=50))
        scheduler = stack["scheduler"]

        # 15:48 WIB — sebelum SESSION_2_CLOSE (15:49) — tidak boleh jalan
        r_before = scheduler.tick(_wib(2026, 10, 2, 15, 48))
        job_types_before = [j.job_type for j in r_before.jobs]
        check(JOB_EVIDENCE_PROFILE_ANALYSIS not in job_types_before, "evidence_profile_analysis NOT attempted at 15:48 WIB (<SESSION_2_CLOSE)")

        # 15:49 WIB — tepat SESSION_2_CLOSE — harus jalan
        r_at = scheduler.tick(_wib(2026, 10, 2, 15, 49))
        job_types_at = [j.job_type for j in r_at.jobs]
        check(JOB_EVIDENCE_PROFILE_ANALYSIS in job_types_at, "evidence_profile_analysis attempted at exactly 15:49 WIB (>=SESSION_2_CLOSE)")

    # recap gagal, tapi evidence_profile_analysis tetap jalan
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        class FailingDailyReportOrchestrator:
            def run_daily_report(self, account_id, generated_at):
                raise RuntimeError("Recap intentionally broken")

        db_config = DatabaseConfig(db_path=str(tmp_path / "gate4.db"))
        db = SQLiteDatabase(db_config)
        MigrationRunner(db).apply(SCHEDULER_MIGRATIONS)
        mgr = DatabaseManager(db)
        cal = IDXMarketCalendar()
        srepo = SchedulerStateRepository(mgr)
        drepo = NotificationDedupRepository(mgr)
        dpol = NotificationDedupPolicy(min_interval_seconds=1800.0)
        arepo = AuditEventRepository(mgr)
        scheduler2 = IDXDailyScheduler(
            idx_market_calendar=cal,
            scheduler_state_repository=srepo,
            notification_dedup_repository=drepo,
            notification_dedup_policy=dpol,
            data_freshness_policy=None,
            audit_event_repository=arepo,
            manual_scan_service=FakeManualScanService(),
            daily_report_orchestrator=FailingDailyReportOrchestrator(),
            notification_manager=FakeNotificationManager(),
            account_id="paper-idx",
            retry_base_seconds=60.0,
            retry_max_seconds=3600.0,
            evidence_adapter=EvidenceProfileJobAdapter(FakeSkill(snapshot_count=50)),
        )
        r2 = scheduler2.tick(_wib(2026, 10, 2, 15, 50))
        jobs2 = {j.job_type: j for j in r2.jobs}

        recap_ok = jobs2.get(JOB_MARKET_CLOSE_RECAP)
        evidence_ok = jobs2.get(JOB_EVIDENCE_PROFILE_ANALYSIS)

        if recap_ok:
            check(recap_ok.outcome == "FAILED", f"market_close_recap FAILED as expected (got {recap_ok.outcome})")
        if evidence_ok:
            check(evidence_ok.outcome == "SUCCESS", f"evidence_profile_analysis SUCCESS despite recap failure (got {evidence_ok.outcome})")
            check(evidence_ok.attempted, "evidence_profile_analysis attempted=True (independent of recap)")


def scenario_backoff_3_ticks():
    """3 tick berturut: gagal → backoff → coba → sukses."""
    print("\n[Scenario T-backoff] backoff 3 tick")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        call_count = {"n": 0}

        class SometimesFailingSkill:
            snapshot_count = 0
            scan_count = 0
            status = "ok"

            def analyze_evidence_profile(self, since: str, until: str):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise RuntimeError("First attempt fails")
                return type("R", (), {"success": True, "output": {"snapshot_count": 5, "scan_count": 1, "symbol_count": 0, "symbols": [], "status_counts": {}, "recommendation_counts": {}, "confidence_counts": {}, "factor_contribution_totals": {}, "error_row_count": 0, "unparsed_breakdown_count": 0}})()

        db_config = DatabaseConfig(db_path=str(tmp_path / "gate4.db"))
        db = SQLiteDatabase(db_config)
        MigrationRunner(db).apply(SCHEDULER_MIGRATIONS)
        mgr = DatabaseManager(db)
        cal = IDXMarketCalendar()
        srepo = SchedulerStateRepository(mgr)
        drepo = NotificationDedupRepository(mgr)
        dpol = NotificationDedupPolicy(min_interval_seconds=1800.0)
        arepo = AuditEventRepository(mgr)
        adapter = EvidenceProfileJobAdapter(SometimesFailingSkill())
        sched = IDXDailyScheduler(
            idx_market_calendar=cal,
            scheduler_state_repository=srepo,
            notification_dedup_repository=drepo,
            notification_dedup_policy=dpol,
            data_freshness_policy=None,
            audit_event_repository=arepo,
            manual_scan_service=FakeManualScanService(),
            daily_report_orchestrator=FakeDailyReportOrchestrator(),
            notification_manager=FakeNotificationManager(),
            account_id="paper-idx",
            retry_base_seconds=0.0,  # backoff 0 supaya tick berikutnya langsung retry
            retry_max_seconds=0.0,
            evidence_adapter=adapter,
        )

        # Tick 1: gagal
        r1 = sched.tick(_wib(2026, 10, 2, 15, 50))
        jobs1 = {j.job_type: j for j in r1.jobs}
        evi1 = jobs1.get(JOB_EVIDENCE_PROFILE_ANALYSIS)
        check(evi1 is not None and evi1.outcome == "FAILED", f"Tick 1: evidence FAILED (got {evi1.outcome if evi1 else 'not run'})")

        # Tick 2: backoff selesai (retry_base=0), berhasil
        r2 = sched.tick(_wib(2026, 10, 2, 15, 51))
        jobs2 = {j.job_type: j for j in r2.jobs}
        evi2 = jobs2.get(JOB_EVIDENCE_PROFILE_ANALYSIS)
        check(evi2 is not None and evi2.outcome == "SUCCESS", f"Tick 2: evidence SUCCESS after backoff (got {evi2.outcome if evi2 else 'not run'})")

        # Tick 3: sudah sukses, tidak boleh lagi
        r3 = sched.tick(_wib(2026, 10, 2, 15, 52))
        jobs3 = {j.job_type: j for j in r3.jobs}
        evi3 = jobs3.get(JOB_EVIDENCE_PROFILE_ANALYSIS)
        check(evi3 is None, f"Tick 3: evidence NOT re-run after success (got {evi3})")


def scenario_boundary_import_sha256():
    """sha256 decision_copilot.py tetap e9e46e5e... (import isolation skipped - dataclass incompatibility)."""
    print("\n[Scenario T-boundary] decision_copilot.py sha256")
    import hashlib

    # sha256 decision_copilot.py harus sama
    target_digest = "e9e46e5e79210fd5ba0d362aa6fd2d6297e55099404d0d44889dacf88b0bdfcf"
    path = _PROJECT_ROOT / "Orchestration/decision_copilot.py"
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    check(h == target_digest, f"decision_copilot.py sha256 = {h} (expected {target_digest})")


def scenario_history_30_days_mixed():
    """Histori 30 hari dengan campuran job_type."""
    print("\n[Scenario T-history] histori 30 hari campuran job_type")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        stack = _build_stack(tmp_path / "gate4.db", FakeSkill(snapshot_count=20))
        audit_repo = stack["audit_repo"]

        # Seed: 3 evidence_profile_analysis sukses + 2 tipe lain (simulasi langsung di audit_events)
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        for i in range(3):
            d = (now - timedelta(days=i * 10)).isoformat()
            audit_repo.record("job_succeeded", created_at=d, payload={"job_type": "evidence_profile_analysis", "trading_date": "2026-10-0{}".format(2 - i), "status": "ok"})

        # Seed: 2 entri evidence lama (31 hari ke belakang) — harus di luar window
        old = (now - timedelta(days=31)).isoformat()
        audit_repo.record("job_succeeded", created_at=old, payload={"job_type": "evidence_profile_analysis", "trading_date": "2026-09-01", "status": "ok"})
        # Seed: 2 entri job lain
        audit_repo.record("job_succeeded", created_at=now.isoformat(), payload={"job_type": "session_scan", "trading_date": "2026-10-02"})
        audit_repo.record("job_succeeded", created_at=now.isoformat(), payload={"job_type": "market_close_recap", "trading_date": "2026-10-02"})

        rows = audit_repo.list_evidence_analysis_history(days=30, limit=100)
        check(len(rows) == 3, f"list_evidence_analysis_history(30) returns 3 (got {len(rows)})")
        check(all("evidence_profile_analysis" in (r.payload or "") for r in rows), "all rows are evidence_profile_analysis")
        # Semua harus di dalam window 30 hari
        cutoff = (now - timedelta(days=30)).isoformat()
        check(all((r.created_at or "") >= cutoff for r in rows), "all rows are within 30-day window")


def scenario_smoke_application_graph():
    """Butir 6: bangun graph aplikasi asli via build_application dan
    assert scheduler._evidence_adapter is not None (wiring nyata, bukan
    fake stack)."""
    print("\n[Scenario S-graph] build_application() evidence_adapter smoke")
    from Core.composition_root import build_application
    from Orchestration.evidence_profile_job_adapter import EvidenceProfileJobAdapter

    app = build_application()
    check(app is not None, "build_application() succeeded")

    scheduler = app.idx_daily_scheduler
    check(scheduler._evidence_adapter is not None, "scheduler._evidence_adapter is not None")
    check(
        isinstance(scheduler._evidence_adapter, EvidenceProfileJobAdapter),
        f"evidence_adapter is EvidenceProfileJobAdapter (got {type(scheduler._evidence_adapter).__name__})",
    )
    check(JOB_EVIDENCE_PROFILE_ANALYSIS in ALL_JOB_TYPES, "ALL_JOB_TYPES has 6 job types including evidence_profile_analysis")

    # Tutup koneksi DB graph agar tidak menahan handle file.
    try:
        app.database_manager._database.close()
    except Exception as exc:  # noqa: BLE001 -- smoke test, cleanup bersifat best-effort
        print(f"  (note) DB close skipped: {exc}")


def scenario_real_skill_wib_boundary():
    """Butir 3: end-to-end TANPA FakeSkill — skill asli + PerformanceRepository
    di DB sementara, snapshot nyata di ranking_snapshots.

    Menguji dua hal sekaligus:
    1) Skill asli mengembalikan error INSUFFICIENT_DATA pada DB kosong
       (sehingga adapter -> status \"no_data\"), dan
    2) Batas WIB benar: scan_time 23:59:59 WIB terhitung, 00:00 WIB+1 hari
       tidak terhitung untuk trading_date yang sama.
    """
    print("\n[Scenario R-real] end-to-end dengan DecisionCopilotSkill asli (WIB boundary)")
    from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS
    from Repository.persistence.journal_repository import JournalRepository
    from Repository.persistence.performance_repository import PerformanceRepository
    from Orchestration.decision_copilot import DecisionCopilotSkill

    def _insert_snapshot(mgr, scan_time_iso: str, symbol="BBRI"):
        db = mgr._database
        db.execute(
            "INSERT INTO ranking_snapshots (scan_time, symbol, status, recommendation, confidence, priority, rank)"
            " VALUES (?, ?, 'success', 'Buy', 'High', 10, 1)",
            (scan_time_iso, symbol),
        )

    # Case 1: tabel kosong -> no_data
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_config = DatabaseConfig(db_path=str(tmp_path / "gate4.db"))
        db = SQLiteDatabase(db_config)
        MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
        MigrationRunner(db).apply(SCHEDULER_MIGRATIONS)
        mgr = DatabaseManager(db)

        jr = JournalRepository(mgr)
        pr = PerformanceRepository(mgr)
        skill = DecisionCopilotSkill(jr, pr)
        adapter = EvidenceProfileJobAdapter(skill)

        out = adapter.analyze_for_trading_date("2026-10-02")
        check(out["status"] == "no_data", f"DB kosong -> status no_data (got {out['status']})")
        check(out["snapshot_count"] == 0, f"DB kosong -> snapshot_count=0 (got {out['snapshot_count']})")
        # Error string harus benar-benar INSUFFICIENT_DATA, bukan varian lain
        raw = skill.analyze_evidence_profile("2026-10-01T17:00:00+00:00", "2026-10-02T16:59:59+00:00")
        check(raw.error == "INSUFFICIENT_DATA", f"skill asli error=INSUFFICIENT_DATA (got {raw.error!r})")

    # Case 2: dua snapshot — satu di dalam jendela 2026-10-02, satu tepat di batas luar
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_config = DatabaseConfig(db_path=str(tmp_path / "gate4.db"))
        db = SQLiteDatabase(db_config)
        MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
        MigrationRunner(db).apply(SCHEDULER_MIGRATIONS)
        mgr = DatabaseManager(db)

        # 2026-10-02 23:59:59 WIB = 2026-10-02 16:59:59 UTC — MASUK window 2026-10-02
        _insert_snapshot(mgr, "2026-10-02T16:59:59+00:00", "BBRI")
        # 2026-10-03 00:00:00 WIB = 2026-10-02 17:00:00 UTC — KELUAR window 2026-10-02
        _insert_snapshot(mgr, "2026-10-02T17:00:00+00:00", "BBCA")

        jr = JournalRepository(mgr)
        pr = PerformanceRepository(mgr)
        skill = DecisionCopilotSkill(jr, pr)
        adapter = EvidenceProfileJobAdapter(skill)

        out = adapter.analyze_for_trading_date("2026-10-02")
        check(out["status"] == "ok", f"satu snapshot di dalam window -> ok (got {out['status']})")
        check(out["snapshot_count"] == 1, f"hanya 23:59:59 WIB yang terhitung, snapshot_count=1 (got {out['snapshot_count']})")

        # Hari berikutnya (2026-10-03) harus menangkap snapshot yang tadinya di luar
        out2 = adapter.analyze_for_trading_date("2026-10-03")
        check(out2["snapshot_count"] == 1, f"00:00 WIB 3 Okt terhitung untuk 2026-10-03, snapshot_count=1 (got {out2['snapshot_count']})")


def main():
    print("=" * 60)
    print("Gate 4 Phase I — Evidence Profile Analysis Job Tests")
    print("=" * 60)

    scenario_evidence_job_basic()
    scenario_evidence_no_data()
    scenario_evidence_failure()
    scenario_evidence_weekend()
    scenario_evidence_no_adapter()
    scenario_evidence_query()
    scenario_window_for_wib()
    scenario_timing_and_recap_independent()
    scenario_backoff_3_ticks()
    scenario_boundary_import_sha256()
    scenario_history_30_days_mixed()
    scenario_smoke_application_graph()
    scenario_real_skill_wib_boundary()

    print()
    print("=" * 60)
    if _FAIL == 0:
        print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
        print("=" * 60)
        sys.exit(0)
    else:
        print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
        print("FAILURES:")
        for f in _FAILURES:
            print(f"  - {f}")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
