"""
Pytest fixtures for Tests/.

- `fx`: returns the `Fixtures` dataclass instance from `E2e_test.setup_fixtures()`.
        8 tests in `E2e_test.py` consume this fixture.

- `services`: returns the `services` dict built in
        `integration_test.test_instantiation_and_health_checks()` (which already
        returns the dict it builds). 2 tests in `integration_test.py` consume
        this fixture.

- `cleanup_db_connections` (session-scoped, autouse): at session end,
  calls ``DatabaseManager.close_all()`` / ``SQLiteDatabase.close_all()`` on a
  real instance backed by ``DatabaseConfig.from_env()`` to close every tracked
  connection and detach leak-detection finalizers. Does not call
  ``build_application()``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from Database.database_manager import DatabaseManager
from Database.sqlite_database import close_all_instances, SQLiteDatabase
from Tests.E2e_test import setup_fixtures
from Tests.integration_test import test_instantiation_and_health_checks


# Dotted filenames like test_phase_i_gate3.1_datetime.py are not valid Python
# module names (the dot truncates the module at "test_phase_i_gate3"), so they
# cannot be imported. Pre-existing condition, not introduced by this work.
collect_ignore = ["test_phase_i_gate3.1_datetime.py"]
# Retired sprint snapshot scripts; see Tests/archive/README.md.
collect_ignore_glob = ["archive/*"]


# --------------------------------------------------------------------------
# Script-style tests
#
# Most files in Tests/ are scenario scripts with a main() and no test_*
# functions, so plain pytest collected nothing from them. Each one now
# becomes a single "script" item that runs the file in its own process
# (they keep module-level counters) with DB_PATH pointing at a private copy
# of a fully migrated template database -- never the live database -- and
# UTF-8 output. Skip them for a quick run with:  pytest -m "not script"
# --------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HAS_TEST_FUNCTION = re.compile(r"^\s*def test_", re.MULTILINE)
_SCRIPT_TIMEOUT_SECONDS = 600
_template_db: Path | None = None


def _migrated_template() -> Path:
    global _template_db
    if _template_db is None:
        from Database.database_config import DatabaseConfig
        from Database.migration_registry import all_migrations
        from Database.migrations import MigrationRunner

        path = Path(tempfile.mkdtemp(prefix="aios_script_tests_")) / "template.db"
        db = SQLiteDatabase(DatabaseConfig(db_path=path))
        db.connect()
        MigrationRunner(db).apply([migration for migration, _domain in all_migrations()])
        db.disconnect()
        _template_db = path
    return _template_db


def pytest_configure(config):
    config.addinivalue_line("markers", "script: a scenario script run in its own process")


def pytest_collect_file(file_path, parent):
    if (
        file_path.suffix == ".py"
        and file_path.name.startswith("test_")
        and file_path.parent == Path(__file__).resolve().parent
    ):
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        if not _HAS_TEST_FUNCTION.search(text) and "__main__" in text:
            return ScriptFile.from_parent(parent, path=file_path)
    return None


class ScriptFailure(Exception):
    pass


class ScriptFile(pytest.File):
    def collect(self):
        yield ScriptItem.from_parent(self, name="script")


class ScriptItem(pytest.Item):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_marker("script")

    def runtest(self):
        with tempfile.TemporaryDirectory(prefix="aios_script_") as tmp:
            db = Path(tmp) / "script.db"
            shutil.copyfile(_migrated_template(), db)
            env = {**os.environ, "DB_PATH": str(db), "PYTHONIOENCODING": "utf-8",
                   "PYTHONPATH": str(_REPO_ROOT)}
            try:
                proc = subprocess.run([sys.executable, str(self.path)], cwd=_REPO_ROOT, env=env,
                                      capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      timeout=_SCRIPT_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as exc:
                raise ScriptFailure(f"timed out after {_SCRIPT_TIMEOUT_SECONDS}s") from exc
        if proc.returncode != 0:
            tail = "\n".join((proc.stdout + "\n" + proc.stderr).strip().splitlines()[-25:])
            raise ScriptFailure(f"exit code {proc.returncode}\n{tail}")

    def repr_failure(self, excinfo):
        if isinstance(excinfo.value, ScriptFailure):
            return f"{self.path.name} failed: {excinfo.value}"
        return super().repr_failure(excinfo)

    def reportinfo(self):
        return self.path, None, f"script: {self.path.name}"


@pytest.fixture(autouse=True)
def isolate_default_db_path(tmp_path, monkeypatch):
    """Point DB_PATH at a per-test temp file.

    Without this, any test that calls ``build_application()`` or
    ``DatabaseConfig.from_env()`` opens (and, if missing, creates) the live
    ``data/investment_platform.db``. Tests that deliberately read the live DB
    use an explicit path and open it read-only.
    """
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test_default.db"))


@pytest.fixture(scope="session", autouse=True)
def cleanup_db_connections():
    """Session end teardown: close all tracked DB connections.

    Closes every connection tracked by any :class:`SQLiteDatabase` instance
    created during the session (test and production code paths alike), and
    detaches their leak-detection finalizers so ``_reclaim_leaked_connection``
    cannot fire at interpreter shutdown.
    """
    yield
    close_all_instances()


@pytest.fixture(name="fx")
def fx():
    """Wrap E2e_test.setup_fixtures() — registers providers/tools/services."""
    return setup_fixtures()


@pytest.fixture(name="services")
def services():
    """Wrap integration_test.test_instantiation_and_health_checks() — instantiates
    StockService / ChartService / NewsService / BacktestService / NotificationService
    and returns the dict consumed by test_chain_success_path and test_fail_paths.
    """
    return test_instantiation_and_health_checks()
