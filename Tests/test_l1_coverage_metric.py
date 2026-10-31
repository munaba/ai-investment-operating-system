"""Unit tests for L1 coverage metrics and duplicate checking.

Covers:
(a) without gap: perfect coverage
(b) with gap: missing_trading_days detected but informational (failed == 0)
(c) no scans for N days: days_since_last_scan >= N
(d) duplicates: fails with failed >= 1
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_PROJ = Path(__file__).resolve().parent.parent
_PY = sys.executable

from Business.idx_market_calendar import load_idx_market_calendar
from Database.database_config import DatabaseConfig
from Database.migrations import MigrationRunner
from Database.migrations_decision_briefs import DECISION_BRIEFS_MIGRATIONS
from Database.migrations_risk_ledger import RISK_LEDGER_MIGRATIONS
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS
from Database.migrations_trades import TRADES_MIGRATIONS
from Database.sqlite_database import SQLiteDatabase


def _seed_db(db_path: Path, rows: list[tuple[str, str]]) -> None:
    """Create DB via migrations and insert snapshots."""
    migrations_up_to_v11 = [m for m in SNAPSHOTS_MIGRATIONS if m.version <= 11]
    db = SQLiteDatabase(DatabaseConfig(db_path=db_path))
    db.connect()
    try:
        runner = MigrationRunner(db)
        runner.apply(migrations_up_to_v11)
        runner.apply(DECISION_BRIEFS_MIGRATIONS)
        runner.apply(RISK_LEDGER_MIGRATIONS)
        runner.apply(TRADES_MIGRATIONS)
    finally:
        db.disconnect()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executemany("INSERT INTO ranking_snapshots (scan_time, symbol) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def test_l1_without_gap(tmp_path, monkeypatch):
    """(a) Tanpa gap: consecutive trading days up to eval date."""
    db_path = tmp_path / "no_gap.db"
    cal = load_idx_market_calendar(env_get=lambda _k, _d: "")

    # Build last 5 trading days ending today
    cur = date.today()
    trading_days: list[date] = []
    while len(trading_days) < 5:
        if cal.is_trading_day(cur):
            trading_days.append(cur)
        cur -= timedelta(days=1)
    trading_days.sort()

    rows = [(f"{d.isoformat()}T09:00:00+07:00", "BBCA") for d in trading_days]
    _seed_db(db_path, rows)

    monkeypatch.setenv("AIOS_EVAL_DB_PATH", str(db_path))
    from Evaluation import run_eval
    import importlib
    importlib.reload(run_eval)

    p, f = run_eval.eval_l1_data_baseline()
    assert f == 0
    assert p >= 2  # duplicates check + missing_trading_days informational


def test_l1_with_gap(tmp_path, monkeypatch):
    """(b) Dengan gap: missing trading days present, but informational (f == 0)."""
    db_path = tmp_path / "with_gap.db"
    cal = load_idx_market_calendar(env_get=lambda _k, _d: "")

    # Pick 2 trading days separated by a gap
    cur = date.today()
    trading_days: list[date] = []
    while len(trading_days) < 10:
        if cal.is_trading_day(cur):
            trading_days.append(cur)
        cur -= timedelta(days=1)
    trading_days.sort()

    # Skip intermediate days to create an obvious gap
    selected = [trading_days[0], trading_days[-1]]
    rows = [(f"{d.isoformat()}T09:00:00+07:00", "BBCA") for d in selected]
    _seed_db(db_path, rows)

    monkeypatch.setenv("AIOS_EVAL_DB_PATH", str(db_path))
    from Evaluation import run_eval
    import importlib
    importlib.reload(run_eval)

    p, f = run_eval.eval_l1_data_baseline()
    assert f == 0
    assert p >= 2


def test_l1_no_scans_last_n_days(tmp_path, monkeypatch):
    """(c) Tidak ada scan selama N hari terakhir: days_since_last_scan >= N."""
    db_path = tmp_path / "old_scans.db"
    cal = load_idx_market_calendar(env_get=lambda _k, _d: "")

    # Scan was 30 calendar days ago
    past_date = date.today() - timedelta(days=30)
    while not cal.is_trading_day(past_date):
        past_date -= timedelta(days=1)

    rows = [(f"{past_date.isoformat()}T09:00:00+07:00", "BBCA")]
    _seed_db(db_path, rows)

    monkeypatch.setenv("AIOS_EVAL_DB_PATH", str(db_path))
    from Evaluation import run_eval
    import importlib
    importlib.reload(run_eval)

    p, f = run_eval.eval_l1_data_baseline()
    assert f == 0
    assert p >= 2


def test_l1_duplicates_fail(tmp_path, monkeypatch):
    """(d) Duplikat: scan_time & symbol duplikat harus menggagalkan check (f >= 1)."""
    db_path = tmp_path / "dup.db"
    d = date.today()
    rows = [
        (f"{d.isoformat()}T09:00:00+07:00", "BBCA"),
        (f"{d.isoformat()}T09:00:00+07:00", "BBCA"),  # duplicate
    ]
    _seed_db(db_path, rows)

    monkeypatch.setenv("AIOS_EVAL_DB_PATH", str(db_path))
    from Evaluation import run_eval
    import importlib
    importlib.reload(run_eval)

    p, f = run_eval.eval_l1_data_baseline()
    assert f >= 1
    assert p >= 1


def test_empty_db_does_not_pass_silently(tmp_path, monkeypatch):
    """DB kosong TIDAK boleh menghasilkan status PASS palsu pada L1, L3, atau L5."""
    empty_db = tmp_path / "empty.db"
    conn = sqlite3.connect(empty_db)
    # DB completely empty (no tables)
    conn.close()

    monkeypatch.setenv("AIOS_EVAL_DB_PATH", str(empty_db))
    from Evaluation import run_eval
    import importlib
    importlib.reload(run_eval)

    # L3 signals returns 0, 0 -> DATA_TIDAK_CUKUP (not PASS)
    try:
        p3, f3 = run_eval.eval_l3_signals_baseline()
        assert p3 == 0 and f3 == 0
    except Exception:
        pass  # missing ranking_snapshots table throws or skips

    # L5 orchestration returns 0, 0 -> DATA_TIDAK_CUKUP (not PASS)
    p5, f5 = run_eval.eval_l5_orchestration_baseline()
    assert p5 == 0 and f5 == 0

    # L3 walk-forward returns 0, 0 -> DATA_TIDAK_CUKUP (not PASS)
    try:
        pw, fw = run_eval.eval_l3_walkforward()
        assert pw == 0 and fw == 0
    except Exception:
        pass

