"""Regression: SQLiteDatabase.close_all() is terminal.

After close_all(), the instance must not be reused; connect() raises
DatabaseError with a clear message.
"""
from __future__ import annotations

from pathlib import Path
import tempfile

from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.sqlite_database import SQLiteDatabase


def test_connect_after_close_all_raises():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "t.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        assert db.health_check() is True

        db.close_all()

        try:
            db.connect()
        except Exception as exc:  # DatabaseError
            assert str(exc) == "database was closed via close_all()"
            return
        raise AssertionError("connect() after close_all() must raise DatabaseError")


def test_connect_after_close_all_raises_with_database_manager():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "t2.db")
        db = SQLiteDatabase(cfg)
        mgr = DatabaseManager(db, config=cfg)
        db.connect()
        assert db.health_check() is True

        mgr.close_all()

        try:
            db.connect()
        except Exception as exc:
            assert str(exc) == "database was closed via close_all()"
            return
        raise AssertionError("connect() after close_all() must raise DatabaseError")
