from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_trades import TRADES_MIGRATIONS


def run_trade_migrations() -> int:
    """Apply ``TRADES_MIGRATIONS`` to the production database.

    Manual, standalone operation, unchanged in behavior from before
    Activation 1.3 -- see ``run_watchlist_migrations.py`` for the full
    rationale. Now a thin wrapper around
    ``Database.migration_cli_helper.apply_domain_migrations``; use
    ``python main.py init`` to apply every domain together.

    Returns:
        ``0`` on success (including "nothing pending"). ``1`` if
        applying the migrations raised a ``DatabaseError``.
    """
    return apply_domain_migrations(TRADES_MIGRATIONS, "trade")


def main() -> int:
    return run_trade_migrations()


if __name__ == "__main__":
    sys.exit(main())
