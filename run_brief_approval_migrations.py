from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_brief_approvals import BRIEF_APPROVALS_MIGRATIONS


def run_brief_approval_migrations() -> int:
    """Apply ``BRIEF_APPROVALS_MIGRATIONS`` to the production database.

    Manual, standalone operation -- see ``run_watchlist_migrations.py``
    for the full rationale. Thin wrapper around
    ``Database.migration_cli_helper.apply_domain_migrations``.

    Returns:
        ``0`` on success (including "nothing pending"). ``1`` if
        applying the migrations raised a ``DatabaseError``.
    """
    return apply_domain_migrations(BRIEF_APPROVALS_MIGRATIONS, "brief_approval")


def main() -> int:
    return run_brief_approval_migrations()


if __name__ == "__main__":
    sys.exit(main())