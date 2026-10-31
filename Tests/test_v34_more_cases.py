
from __future__ import annotations
import hashlib, os, sqlite3, tempfile
from pathlib import Path
import pytest
from Database.database_config import DatabaseConfig
from Database.migrations import MigrationRunner
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS
from Database.sqlite_database import SQLiteDatabase
from Repository.persistence.snapshot_repository import SnapshotRepository

_ROW_A = "'2026-01-01','BBCA','success','BUY','0.9',1,1,80.0,'{}','ok',''"
_ROW_B = "'2026-01-01','BBCA','error','SELL','0.1',2,2,10.0,'{}','bad','err'"
_INSERT = "INSERT INTO ranking_snapshots (scan_time, symbol, status, recommendation, confidence, priority, rank, score, score_breakdown_json, evidence_summary, error_message) VALUES "

def _seed_db(tmp_path, migrations_up_to=11):
    config = DatabaseConfig.from_env()
    config.db_path = str(tmp_path / "test.db")
    db = SQLiteDatabase(config)
    db.connect()
    MigrationRunner(db).apply([m for m in SNAPSHOTS_MIGRATIONS if m.version <= migrations_up_to])
    return db

def _table_checksum(db):
    rows = db.execute("SELECT * FROM ranking_snapshots ORDER BY snapshot_id").rows
    blob = repr(rows).encode()
    return hashlib.md5(blob).hexdigest()

def _schema_version(db):
    versions = db.execute("SELECT MAX(version) AS v FROM schema_migrations").rows
    return int(versions[0]["v"]) if versions else 0

def test_v34_conflicting_duplicates_error_full(tmp_path):
    db = _seed_db(tmp_path, 11)
    db.execute(_INSERT + "(" + _ROW_A + ")")
    db.execute(_INSERT + "(" + _ROW_B + ")")
    cksum_before = _table_checksum(db)
    ver_before = _schema_version(db)
    assert ver_before == 11
    runner = MigrationRunner(db)
    with pytest.raises(Exception, match="v34.*conflicting"):
        runner.apply([m for m in SNAPSHOTS_MIGRATIONS if m.version == 34])
    cksum_after = _table_checksum(db)
    ver_after = _schema_version(db)
    assert cksum_after == cksum_before
    assert ver_after == 11
    cnt = db.execute("SELECT COUNT(*) AS c FROM ranking_snapshots").rows[0]["c"]
    assert cnt == 2
    db.close_all()

def test_v34_mixed_duplicates_error_full(tmp_path):
    db = _seed_db(tmp_path, 11)
    db.execute(_INSERT + "(" + _ROW_A + ")")
    db.execute(_INSERT + "(" + _ROW_A + ")")
    db.execute(_INSERT + "(" + _ROW_B + ")")
    cksum_before = _table_checksum(db)
    ver_before = _schema_version(db)
    runner = MigrationRunner(db)
    with pytest.raises(Exception, match="v34.*conflicting"):
        runner.apply([m for m in SNAPSHOTS_MIGRATIONS if m.version == 34])
    cksum_after = _table_checksum(db)
    ver_after = _schema_version(db)
    assert cksum_after == cksum_before
    assert ver_after == ver_before
    cnt = db.execute("SELECT COUNT(*) AS c FROM ranking_snapshots").rows[0]["c"]
    assert cnt == 3
    db.close_all()

def test_v34_trigger_cleaned_after_failure_full(tmp_path):
    db = _seed_db(tmp_path, 11)
    db.execute(_INSERT + "(" + _ROW_A + ")")
    db.execute(_INSERT + "(" + _ROW_B + ")")
    runner = MigrationRunner(db)
    with pytest.raises(Exception):
        runner.apply([m for m in SNAPSHOTS_MIGRATIONS if m.version == 34])
    temp_triggers = db.execute("SELECT name FROM sqlite_temp_master WHERE type='trigger'").rows
    assert "v34_conflict_guard" not in [r["name"] for r in temp_triggers]
    db.close_all()

def test_rowcount_new_and_duplicate_repo(tmp_path):
    db = _seed_db(tmp_path, 34)
    repo = SnapshotRepository(db)
    snap1 = repo.create(scan_time="2026-02-02", symbol="BBCA", status="success", recommendation="BUY", confidence="0.9", priority=1, rank=1, score=80.0, score_breakdown_json="{}", evidence_summary="ok", error_message="")
    snap2 = repo.create(scan_time="2026-02-02", symbol="BBCA", status="success", recommendation="BUY", confidence="0.9", priority=1, rank=1, score=80.0, score_breakdown_json="{}", evidence_summary="ok", error_message="")
    assert snap1 and snap2 and snap1.snapshot_id == snap2.snapshot_id
    db.close_all()

def test_create_duplicate_returns_existing_full(tmp_path):
    db = _seed_db(tmp_path, 34)
    repo = SnapshotRepository(db)
    original = repo.create(scan_time="2026-03-03", symbol="TLKM", status="success", recommendation="HOLD", confidence="0.5", priority=2, rank=3, score=50.0, score_breakdown_json='{"x":1}', evidence_summary="test", error_message=None)
    duplicate = repo.create(scan_time="2026-03-03", symbol="TLKM", status="success", recommendation="HOLD", confidence="0.5", priority=2, rank=3, score=50.0, score_breakdown_json='{"x":1}', evidence_summary="test", error_message=None)
    assert duplicate.snapshot_id == original.snapshot_id
    cnt = db.execute("SELECT COUNT(*) AS c FROM ranking_snapshots WHERE scan_time='2026-03-03' AND symbol='TLKM'").rows[0]["c"]
    assert cnt == 1
    db.close_all()

def test_raw_duplicate_insert_after_v34_raises_full(tmp_path):
    db = _seed_db(tmp_path, 34)
    db.execute(_INSERT + "(" + _ROW_A + ")")
    with pytest.raises(Exception) as exc_info:
        db.execute(_INSERT + "(" + _ROW_A + ")")
    assert "UNIQUE" in str(exc_info.value) or "IntegrityError" in str(type(exc_info.value).__name__)
    db.close_all()

def test_live_db_migration_copy_full():
    src = "data/investment_platform.db"
    if not os.path.exists(src):
        pytest.skip("live DB not available")
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
    runner.apply([m for m in SNAPSHOTS_MIGRATIONS if m.version == 34])
    cnt = db.execute("SELECT COUNT(*) AS c FROM ranking_snapshots").rows[0]["c"]
    assert cnt == 94
    idx = db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='ux_ranking_snapshots_scan_time_symbol'").rows
    assert idx
    ver = _schema_version(db)
    assert ver == 34
    db.close_all()
    os.remove(dst)
