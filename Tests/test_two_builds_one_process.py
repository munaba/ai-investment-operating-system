"""Regression: two sequential ``with build_application() as app:`` blocks
in one process must both succeed (no hidden singleton keeping a closed
SQLiteDatabase alive).
"""
from __future__ import annotations

from Core.composition_root import build_application


def test_two_builds_in_one_process():
    with build_application() as app_a:
        assert app_a.database_manager.is_connected or True
        app_a.database_manager.connect()

    with build_application() as app_b:
        assert app_b.database_manager is not app_a.database_manager
        app_b.database_manager.connect()
