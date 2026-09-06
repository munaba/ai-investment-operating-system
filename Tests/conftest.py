"""
Pytest fixtures for Tests/.

- `fx`: returns the `Fixtures` dataclass instance from `E2e_test.setup_fixtures()`.
        8 tests in `E2e_test.py` consume this fixture.

- `services`: returns the `services` dict built in
        `integration_test.test_instantiation_and_health_checks()` (which already
        returns the dict it builds). 2 tests in `integration_test.py` consume
        this fixture.

No new logic — these fixtures wrap the existing setup helpers so the test
files don't have to be edited. Side effects (provider_manager.register,
tool_registry.register, service instantiation) happen inside the wrapped
helpers.
"""

from __future__ import annotations

import pytest

from Tests.E2e_test import setup_fixtures
from Tests.integration_test import test_instantiation_and_health_checks


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
