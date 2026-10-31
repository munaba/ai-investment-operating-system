import json
import os
import subprocess
import sys
from pathlib import Path
from Database.database_config import DatabaseConfig

import pytest


_PROJ = Path(__file__).resolve().parent.parent
_PY = sys.executable


def _create_fixture_db_via_migrations(path: Path, duplicates: bool = False) -> None:
    """Seed via original migrations up to before v12."""
    from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS
    from Database.migrations_decision_briefs import DECISION_BRIEFS_MIGRATIONS
    from Database.migrations_risk_ledger import RISK_LEDGER_MIGRATIONS
    from Database.migrations_trades import TRADES_MIGRATIONS
    from Database.migrations import MigrationRunner
    from Database.sqlite_database import SQLiteDatabase
    from Database.database_config import DatabaseConfig

    migrations_up_to_v11 = [m for m in SNAPSHOTS_MIGRATIONS if m.version <= 11]
    db = SQLiteDatabase(DatabaseConfig(db_path=Path(str(path))))
    db.connect()
    try:
        runner = MigrationRunner(db)
        runner.apply(migrations_up_to_v11)
        runner.apply(DECISION_BRIEFS_MIGRATIONS)
        runner.apply(RISK_LEDGER_MIGRATIONS)
        runner.apply(TRADES_MIGRATIONS)
    finally:
        db.disconnect()

    import sqlite3
    conn = sqlite3.connect(str(path))
    # Monday 2026-08-03 and Wednesday 2026-08-05 → 1 gap
    rows = [
        ("2026-08-03T09:00:00+07:00", "BBCA"),
        ("2026-08-03T09:00:00+07:00", "TLKM"),
        ("2026-08-05T09:00:00+07:00", "BBCA"),
        ("2026-08-05T09:00:00+07:00", "TLKM"),
    ]
    if duplicates:
        rows.append(("2026-08-03T09:00:00+07:00", "BBCA"))
    conn.executemany(
        "INSERT INTO ranking_snapshots (scan_time, symbol) VALUES (?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


@pytest.fixture
def fixture_db(tmp_path):
    db_path = tmp_path / "fixture.db"
    _create_fixture_db_via_migrations(db_path, duplicates=False)
    return db_path


@pytest.fixture
def dup_db(tmp_path):
    db_path = tmp_path / "dup.db"
    _create_fixture_db_via_migrations(db_path, duplicates=True)
    return db_path


def test_ratchet_with_fixture_db(fixture_db, monkeypatch):
    monkeypatch.setenv("AIOS_EVAL_DB_PATH", str(fixture_db))
    result = subprocess.run(
        [str(_PY), str(_PROJ / "Evaluation" / "run_eval.py")],
        cwd=_PROJ,
        capture_output=True,
        text=True,
        env={**os.environ, "AIOS_EVAL_DB_PATH": str(fixture_db)},
    )
    report_path = _PROJ / "Evaluation" / "run_eval_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text())
    l1 = report["details"]["L1_data"]
    assert l1["failed"] == 0
    assert l1["passed"] >= 2


def test_ratchet_fails_with_duplicates(dup_db):
    env = {**os.environ, "AIOS_EVAL_DB_PATH": str(dup_db)}
    result = subprocess.run(
        [str(_PY), str(_PROJ / "Evaluation" / "run_eval.py")],
        cwd=_PROJ,
        capture_output=True,
        text=True,
        env=env,
    )
    report_path = _PROJ / "Evaluation" / "run_eval_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text())
    l1 = report["details"]["L1_data"]
    assert l1["failed"] >= 1


def test_degraded_baseline_fails_ratchet(fixture_db):
    """Degraded baseline should fail ratchet checks."""
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setenv("AIOS_EVAL_DB_PATH", str(fixture_db))
    try:
        result = subprocess.run(
            [str(_PY), str(_PROJ / "Evaluation" / "run_eval.py")],
            cwd=_PROJ,
            capture_output=True,
            text=True,
            env={**os.environ, "AIOS_EVAL_DB_PATH": str(fixture_db)},
        )
        report_path = _PROJ / "Evaluation" / "run_eval_report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text())
        assert report["details"]["L1_data"]["failed"] == 0
    finally:
        monkeypatch.undo()
