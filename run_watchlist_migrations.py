from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_watchlist import WATCHLIST_MIGRATIONS


def run_watchlist_migrations() -> int:
    """Apply ``WATCHLIST_MIGRATIONS`` to the production database.

    Manual, standalone operation (A2.1 scope decision -- explicitly NOT
    eager, NOT lazy): this function is never called by ``main.py``,
    ``Core.composition_root``, ``Core.startup_validation``, or any
    ``Repository.*`` module. An operator runs this file directly
    (``python run_watchlist_migrations.py``) when the watchlist schema
    needs to be applied to a real database.

    Activation 1.3: this is now a thin compatibility wrapper around
    ``Database.migration_cli_helper.apply_domain_migrations`` -- the
    construction order, messages, and return-code contract are
    unchanged from before Activation 1.3; only the boilerplate shared
    by all six ``run_*_migrations.py`` scripts was unified. For
    applying every domain's migrations together, in canonical order,
    with idempotency/rollback proof and a human-readable report, use
    ``python main.py init`` instead.

    Idempotent: safe to run any number of times. Migrations already
    recorded in ``schema_migrations`` are skipped (see
    ``Database.migrations.MigrationRunner.apply``).

    Returns:
        ``0`` on success (including "nothing pending"). ``1`` if
        applying the migrations raised a ``DatabaseError`` -- the error
        is logged and printed to stderr, never re-raised.
    """
    return apply_domain_migrations(WATCHLIST_MIGRATIONS, "watchlist")


def main() -> int:
    return run_watchlist_migrations()


if __name__ == "__main__":
    sys.exit(main())
