"""Test that SnapshotRepository.create() raises a helpful RepositoryError
when the unique index ux_ranking_snapshots_scan_time_symbol is missing.

This is a standalone pytest (collected by pytest, unlike the scenario_* tests
in Tests/test_snapshot_repository.py which are run as a script). Uses tmp_path
and closes the connection in finally to avoid leaking connections on Windows.
"""
from __future__ import annotations

import os

import pytest

from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.migrations import MigrationRunner
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS
from Database.sqlite_database import SQLiteDatabase
from Repository.persistence.snapshot_repository import SnapshotRepository
from Core.exceptions import RepositoryError


def test_create_missing_unique_index_raises_helpful_error(tmp_path):
    db_path = os.path.join(str(tmp_path), "snapshots_repo.db")
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    try:
        # Apply only up to v11 (no unique index)
        MigrationRunner(db).apply([m for m in SNAPSHOTS_MIGRATIONS if m.version <= 11])
        manager = DatabaseManager(db, cfg)
        repo = SnapshotRepository(manager)
        with pytest.raises(RepositoryError) as exc_info:
            repo.create(
                scan_time="2026-08-01T09:00:00+00:00",
                symbol="BBCA",
                recommendation="SELL",
                confidence="LOW",
                priority=1,
                rank=1,
            )
        assert "run_snapshot_migrations.py" in str(exc_info.value)
    finally:
        db.close_all()
