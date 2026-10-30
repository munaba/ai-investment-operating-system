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

import pytest

from Database.database_manager import DatabaseManager
from Database.sqlite_database import close_all_instances, SQLiteDatabase
from Tests.E2e_test import setup_fixtures
from Tests.integration_test import test_instantiation_and_health_checks


# Dotted filenames like test_phase_i_gate3.1_datetime.py are not valid Python
# module names (the dot truncates the module at "test_phase_i_gate3"), so they
# cannot be imported. Pre-existing condition, not introduced by this work.
collect_ignore = ["test_phase_i_gate3.1_datetime.py"]


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
