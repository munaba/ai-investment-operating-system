"""Daily backup retention: `python main.py backup --keep N`."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from Database.backup import prune_backups

_REPO = Path(__file__).resolve().parent.parent


def _touch(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_bytes(b"")
    return path


def test_prune_keeps_newest_and_ignores_foreign_files(tmp_path: Path) -> None:
    db = tmp_path / "investment_platform.db"
    backups = tmp_path / "backups"
    backups.mkdir()
    names = [f"investment_platform_202611{d:02d}T090000Z.db" for d in (20, 21, 22, 23, 24)]
    for name in names:
        _touch(backups, name)
    manual = _touch(backups, "investment_platform_before-migration.db")
    other = _touch(backups, "other_20261120T090000Z.db")

    deleted = prune_backups(db, keep=2)

    assert [p.name for p in deleted] == names[:3]
    remaining = sorted(p.name for p in backups.iterdir())
    assert remaining == sorted([*names[3:], manual.name, other.name])


def test_prune_rejects_keep_below_one(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        prune_backups(tmp_path / "x.db", keep=0)


def test_prune_without_backup_dir_is_a_no_op(tmp_path: Path) -> None:
    assert prune_backups(tmp_path / "x.db", keep=3) == []


def test_backup_command_with_keep_creates_verifies_and_prunes(tmp_path: Path) -> None:
    db = tmp_path / "live.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
    conn.close()
    backups = tmp_path / "backups"
    backups.mkdir()
    for day in (1, 2, 3):
        _touch(backups, f"live_2026110{day}T090000Z.db")

    result = subprocess.run(
        [sys.executable, "main.py", "backup", "--keep", "2"],
        cwd=_REPO,
        env={**os.environ, "DB_PATH": str(db), "PYTHONPATH": str(_REPO)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "retention: kept newest 2, deleted 2" in result.stdout
    assert len(list(backups.glob("live_*.db"))) == 2


def test_backup_command_rejects_bad_keep(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "main.py", "backup", "--keep", "0"],
        cwd=_REPO,
        env={**os.environ, "DB_PATH": str(tmp_path / "x.db"), "PYTHONPATH": str(_REPO)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 1
    assert "usage: python main.py backup [--keep N]" in result.stdout
