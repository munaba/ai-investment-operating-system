from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS


def run_idempotency_migrations() -> int:
    """Apply ``IDEMPOTENCY_MIGRATIONS`` to the production database.

    Manual, standalone operation -- see ``run_account_migrations.py``
    for the full rationale. Thin wrapper around
    ``Database.migration_cli_helper.apply_domain_migrations``; use
    ``python main.py init`` to apply every domain together.

    Returns:
        ``0`` on success (including "nothing pending"). ``1`` if
        applying the migrations raised a ``DatabaseError``.
    """
    return apply_domain_migrations(IDEMPOTENCY_MIGRATIONS, "idempotency")


def main() -> int:
    return run_idempotency_migrations()


if __name__ == "__main__":
    sys.exit(main())
