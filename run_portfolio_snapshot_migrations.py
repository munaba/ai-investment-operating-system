from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS


def run_portfolio_snapshot_migrations() -> int:
    """Apply ``PORTFOLIO_SNAPSHOTS_MIGRATIONS`` to the production database.

    Manual, standalone operation (Activation 5.2) -- mirrors
    ``run_snapshot_migrations.py``/``run_account_migrations.py``: a
    thin wrapper around
    ``Database.migration_cli_helper.apply_domain_migrations``.
    Deliberately NOT reachable via ``python main.py init`` (this
    domain is not registered in ``Database.migration_registry`` --
    see ``Database.migrations_portfolio_snapshots`` module docstring
    for why).

    Returns:
        ``0`` on success (including "nothing pending"). ``1`` if
        applying the migration raised a ``DatabaseError``.
    """
    return apply_domain_migrations(PORTFOLIO_SNAPSHOTS_MIGRATIONS, "portfolio snapshot")


def main() -> int:
    return run_portfolio_snapshot_migrations()


if __name__ == "__main__":
    sys.exit(main())
