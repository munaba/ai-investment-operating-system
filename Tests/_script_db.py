"""Shared helper for the standalone ``Tests/test_*.py`` scenario scripts.

``scenario_tempdir()`` is a drop-in replacement for
``tempfile.TemporaryDirectory()``. Before the directory is deleted it
disconnects every ``SQLiteDatabase`` whose file lives inside it.

Why: the scripts build repositories on a temp database and never close
it. On Windows an open SQLite handle blocks the directory cleanup with
``PermissionError [WinError 32]``, which crashed the script after its
assertions ran and hid the remaining scenarios. Only databases inside the
scenario's own directory are closed, so shared/module-level instances are
left alone.

The file name has no ``test_`` prefix so neither pytest nor the script
runners pick it up as a test.
"""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from typing import Iterator


def _close_databases_under(directory: str) -> None:
    from Database.sqlite_database import _instances

    root = os.path.normcase(os.path.abspath(directory))
    for instance in list(_instances):
        try:
            db_path = os.path.normcase(os.path.abspath(str(instance.config.db_path)))
        except Exception:  # noqa: BLE001 -- odd configs (e.g. URIs) are not ours
            continue
        if os.path.commonpath([root, db_path]) != root:
            continue
        # close_all() closes this instance's connections on every thread;
        # the instance belongs to a directory that is about to disappear,
        # so marking it closed is correct.
        instance.close_all()


@contextmanager
def scenario_tempdir(*args, **kwargs) -> Iterator[str]:
    with tempfile.TemporaryDirectory(*args, **kwargs) as tmp:
        try:
            yield tmp
        finally:
            _close_databases_under(tmp)


__all__ = ["scenario_tempdir"]
