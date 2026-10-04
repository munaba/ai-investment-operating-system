
"""Test that IDXDailyScheduler.tick() is no-op on non-trading days.

Evidence (from SELECT on data/investment_platform.db):
  ranking_snapshots has 40 rows with scan_time
  '2026-08-22T08:06:26.024842+00:00' -- 2026-08-22 is a Saturday in both
  UTC and WIB (see test module docstring math in the report). The writer
  of those rows is NOT identified by the table schema (no source/job
  column; the only INSERT path found by git grep is
  Repository/persistence/snapshot_repository.py::create, called from
  Business/manual_scan_service.py).

The scheduler guard (Orchestration/idx_daily_scheduler.py:256-257):
    if not self._calendar.is_trading_day(local_date):
        return TickResult(now=..., trading_date=..., session=..., jobs=())
returns an empty jobs tuple BEFORE any job is considered, so no
ranking_snapshots row can be written by tick() on such a day. These
tests prove that on a temp DB copy (row count before == row count
after == 0) and that tick_runner exercises the same tick() path.
"""
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from Business.data_freshness_policy import load_data_freshness_policy
from Business.idx_market_calendar import IDXMarketCalendar
from Business.notification_dedup_policy import NotificationDedupPolicy
from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.migrations import MigrationRunner
from Database.migrations_scheduler import SCHEDULER_MIGRATIONS
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS
from Database.sqlite_database import SQLiteDatabase
from Orchestration.idx_daily_scheduler import IDXDailyScheduler, TickResult
from Repository.persistence.audit_event_repository import AuditEventRepository
from Repository.persistence.notification_dedup_repository import (
    NotificationDedupRepository,
)
from Repository.persistence.scheduler_state_repository import SchedulerStateRepository


# Saturday 2026-08-22, the date of the 40 rows in the real DB.
# scan_time was '2026-08-22T08:06:26.024842+00:00' (UTC) = WIB
# '2026-08-22T15:06:26+07:00'; both dates are Saturday (weekday=5).
SAT_UTC_MORNING = datetime(2026, 8, 22, 8, 6, 26, tzinfo=timezone.utc)
SAT_UTC_AFTERNOON = datetime(2026, 8, 22, 15, 0, 0, tzinfo=timezone.utc)
# Friday 2026-08-21 market open (09:30 WIB = 02:30 UTC).
FRI_MARKET_OPEN = datetime(2026, 8, 21, 2, 30, 0, tzinfo=timezone.utc)


class _MustNotRunScanService:
    def run_scan(self, generated_at):
        raise AssertionError("run_scan() must not be called on a non-trading day")


class _MustNotRunReportOrchestrator:
    def run_daily_report(self, account_id, generated_at):
        raise AssertionError("run_daily_report() must not be called on a non-trading day")


class _NoopNotifier:
    def notify(self, event):
        pass


def _build_scheduler(db_path: str):
    """Build the real scheduler stack on a temp DB copy; return (manager, scheduler)."""
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(SCHEDULER_MIGRATIONS)
    MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    scheduler = IDXDailyScheduler(
        idx_market_calendar=IDXMarketCalendar(),
        scheduler_state_repository=SchedulerStateRepository(manager),
        notification_dedup_repository=NotificationDedupRepository(manager),
        notification_dedup_policy=NotificationDedupPolicy(min_interval_seconds=1800.0),
        data_freshness_policy=load_data_freshness_policy(
            env_get=lambda name, default: default
        ),
        audit_event_repository=AuditEventRepository(manager),
        manual_scan_service=_MustNotRunScanService(),
        daily_report_orchestrator=_MustNotRunReportOrchestrator(),
        notification_manager=_NoopNotifier(),
        account_id="test",
    )
    return manager, scheduler


def _row_count(manager) -> int:
    result = manager.execute("SELECT COUNT(*) AS n FROM ranking_snapshots")
    return result.rows[0]["n"]


def test_tick_on_saturday_2026_08_22_writes_no_rows():
    """tick() on 2026-08-22 (Saturday) writes zero ranking_snapshots rows.

    Guard (Orchestration/idx_daily_scheduler.py:256-257) returns
    TickResult(..., jobs=()) before any job is considered. Row count is
    taken before and after on the same temp DB copy via the real
    DatabaseManager the scheduler writes through.
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    try:
        import os
        os.close(fd)  # release the handle; sqlite reopens by path
        manager, scheduler = _build_scheduler(db_path)

        before = _row_count(manager)
        assert before == 0

        result = scheduler.tick(SAT_UTC_MORNING)
        assert result.jobs == (), f"tick() on Saturday must return empty jobs, got {result.jobs}"

        after_morning = _row_count(manager)
        assert after_morning == 0

        result2 = scheduler.tick(SAT_UTC_AFTERNOON)
        assert result2.jobs == (), f"tick() on Saturday afternoon must return empty jobs, got {result2.jobs}"

        after = _row_count(manager)
        assert after == 0, f"tick() on Saturday must not write ranking_snapshots rows: before={before}, after={after}"
    finally:
        # close_all releases the OS-level file handle on Windows so unlink works.
        try:
            scheduler._scheduler_state_repository  # noqa: B018
        except Exception:
            pass
        # The SQLiteDatabase instance is held by DatabaseManager; close via it.
        try:
            manager.database.close_all()
        except Exception:
            pass
        Path(db_path).unlink(missing_ok=True)


def test_tick_on_friday_market_open_returns_jobs():
    """Sanity check: tick() on Friday 09:30 WIB returns non-empty jobs."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    try:
        import os
        os.close(fd)
        manager, scheduler = _build_scheduler(db_path)

        result = scheduler.tick(FRI_MARKET_OPEN)
        assert len(result.jobs) > 0, f"tick() on Friday must return jobs, got {result.jobs}"
    finally:
        try:
            manager.database.close_all()
        except Exception:
            pass
        Path(db_path).unlink(missing_ok=True)


def test_tick_runner_calls_same_tick_path(monkeypatch):
    """tick_runner.main() calls scheduler.tick(now) -- the same guarded path.

    build_application() and datetime.now are stubbed so the CLI's single
    tick() call is observed on a recording scheduler stub. The stub
    returns a real TickResult (as the real scheduler does on
    non-trading days) and records the `now` argument it was called with.
    """
    import sys
    import Orchestration.tick_runner as tick_runner

    recorded = {}

    class RecordingScheduler:
        def tick(self, now):
            recorded["now"] = now
            return TickResult(
                now=now.isoformat(),
                trading_date=now.date().isoformat(),
                session="SESSION_PRE_MARKET",
                jobs=(),
            )

    recording_scheduler = RecordingScheduler()
    fake_app = MagicMock()
    fake_app.idx_daily_scheduler = recording_scheduler

    fixed_now = datetime(2026, 8, 22, 8, 6, 26, tzinfo=timezone.utc)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(tick_runner, "build_application", lambda: fake_app)
    monkeypatch.setattr(tick_runner, "datetime", _FixedDateTime)
    # mock sys.argv so we don't accidentally run with real args
    monkeypatch.setattr(sys, "argv", ["tick_runner.py"])

    # Output capture
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)

    exit_code = tick_runner.main()

    assert exit_code == 0
    assert recorded.get("now") == fixed_now, (
        f"tick_runner must call scheduler.tick(now) with the current time; got {recorded}"
    )
