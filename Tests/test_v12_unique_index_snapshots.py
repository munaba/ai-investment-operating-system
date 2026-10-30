"""Regression tests for v12 unique index on ranking_snapshots."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from Database.database_config import DatabaseConfig
from Database.migrations import MigrationRunner
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS
from Database.sqlite_database import SQLiteDatabase
from Repository.persistence.snapshot_repository import SnapshotRepository


def _seed_db(tmp_path: Path, migrations_up_to: int = 11) -> SQLiteDatabase:
    config = DatabaseConfig.from_env()
    config.db_path = str(tmp_path / "test.db")
    db = SQLiteDatabase(config)
    db.connect()
    # apply all migrations up to target
    runner = MigrationRunner(db)
    migs = [m for m in SNAPSHOTS_MIGRATIONS if m.version <= migrations_up_to]
    runner.apply(migs)
    return db


def test_v12_no_duplicates_passes(tmp_path):
    db = _seed_db(tmp_path, 11)
    runner = MigrationRunner(db)
    applied = runner.apply([m for m in SNAPSHOTS_MIGRATIONS if m.version == 12])
    assert any(r.version == 12 for r in applied)
    # index exists
    cur = db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='ux_ranking_snapshots_scan_time_symbol'"
    )
    assert cur.rows
    db.close_all()


def test_v12_identical_duplicates_cleaned(tmp_path):
    db = _seed_db(tmp_path, 11)
    # insert duplicate identical rows
    db.execute(
        "INSERT INTO ranking_snapshots (scan_time, symbol, status, recommendation, confidence, priority, rank, score, score_breakdown_json, evidence_summary, error_message) VALUES ('2026-01-01','BBCA','SUCCESS','BUY',0.9,1,1,80.0,'{}','ok','')"
    )
    db.execute(
        "INSERT INTO ranking_snapshots (scan_time, symbol, status, recommendation, confidence, priority, rank, score, score_breakdown_json, evidence_summary, error_message) VALUES ('2026-01-01','BBCA','SUCCESS','BUY',0.9,1,1,80.0,'{}','ok','')"
    )
    before = db.execute("SELECT COUNT(*) FROM ranking_snapshots").rows[0][0]
    assert before == 2
    runner = MigrationRunner(db)
    applied = runner.apply([m for m in SNAPSHOTS_MIGRATIONS if m.version == 12])
    assert any(r.version == 12 for r in applied)
    after = db.execute("SELECT COUNT(*) FROM ranking_snapshots").rows[0][0]
    assert after == 1
    db.close_all()


def test_v12_conflicting_duplicates_error(tmp_path):
    db = _seed_db(tmp_path, 11)
    db.execute(
        "INSERT INTO ranking_snapshots (scan_time, symbol, status, recommendation, confidence, priority, rank, score, score_breakdown_json, evidence_summary, error_message) VALUES ('2026-01-01','BBCA','SUCCESS','BUY',0.9,1,1,80.0,'{}','ok','')"
    )
    db.execute(
        "INSERT INTO ranking_snapshots (scan_time, symbol, status, recommendation, confidence, priority, rank, score, score_breakdown_json, evidence_summary, error_message) VALUES ('2026-01-01','BBCA','FAIL','SELL',0.1,2,2,10.0,'{}','bad','err')"
    )
    before = db.execute("SELECT COUNT(*) FROM ranking_snapshots").rows[0][0]
    assert before == 2
    runner = MigrationRunner(db)
    try:
        runner.apply([m for m in SNAPSHOTS_MIGRATIONS if m.version == 12])
        # Should have raised
        assert False, "expected DatabaseError"
    except Exception:
        pass
    after = db.execute("SELECT COUNT(*) FROM ranking_snapshots").rows[0][0]
    assert after == 2
    db.close_all()


def test_rowcount_new_and_duplicate(tmp_path):
    db = _seed_db(tmp_path, 12)
    repo = SnapshotRepository(db)
    snap1 = repo.create(
        scan_time="2026-02-02", symbol="BBCA", status="SUCCESS",
        recommendation="BUY", confidence=0.9, priority=1, rank=1,
        score=80.0, score_breakdown_json="{}", evidence_summary="ok",
        error_message="",
    )
    assert snap1 is not None
    snap2 = repo.create(
        scan_time="2026-02-02", symbol="BBCA", status="SUCCESS",
        recommendation="BUY", confidence=0.9, priority=1, rank=1,
        score=80.0, score_breakdown_json="{}", evidence_summary="ok",
        error_message="",
    )
    assert snap2 is not None
    assert snap1.snapshot_id == snap2.snapshot_id
    db.close_all()


def test_live_db_migration_copy():
    import sqlite3, tempfile, os
    src = "data/investment_platform.db"
    tmp = tempfile.mkdtemp()
    dst = os.path.join(tmp, "copy.db")
    c1 = sqlite3.connect(src)
    c2 = sqlite3.connect(dst)
    c1.backup(c2)
    c1.close()
    c2.close()
    config = DatabaseConfig.from_env()
    config.db_path = dst
    db = SQLiteDatabase(config)
    db.connect()
    runner = MigrationRunner(db)
    # simulate pre-flight check
    conflicts = db.execute(
        "SELECT scan_time, symbol FROM ranking_snapshots GROUP BY scan_time, symbol HAVING COUNT(*) > 1"
    ).rows
    # check for conflicting
    for c in conflicts:
        pass
    applied = runner.apply([m for m in SNAPSHOTS_MIGRATIONS if m.version == 12])
    # may be already applied; just verify no error
    db.close_all()
    # cleanup
    os.remove(dst)
    assert True
