from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_daily_performance import DAILY_PERFORMANCE_MIGRATIONS


def run_daily_performance_migrations() -> int:
    """Apply ``DAILY_PERFORMANCE_MIGRATIONS`` to the production database.

    Manual, standalone operation (Activation 5.3) -- mirrors
    ``run_portfolio_snapshot_migrations.py``/``run_snapshot_migrations.py``:
    a thin wrapper around
    ``Database.migration_cli_helper.apply_domain_migrations``.
    Deliberately NOT reachable via ``python main.py init`` (this
    domain is not registered in ``Database.migration_registry`` --
    see ``Database.migrations_daily_performance`` module docstring
    for why).

    Returns:
        ``0`` on success (including "nothing pending"). ``1`` if
        applying the migration raised a ``DatabaseError``.
    """
    return apply_domain_migrations(DAILY_PERFORMANCE_MIGRATIONS, "daily performance")


def main() -> int:
    return run_daily_performance_migrations()


if __name__ == "__main__":
    sys.exit(main())
