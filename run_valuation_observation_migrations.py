from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_valuation_observations import VALUATION_OBSERVATIONS_MIGRATIONS


def run_valuation_observation_migrations() -> int:
    """Apply ``VALUATION_OBSERVATIONS_MIGRATIONS`` to the production database.

    Manual, standalone operation -- see ``run_brief_approval_migrations.py``
    for the full rationale. Thin wrapper around
    ``Database.migration_cli_helper.apply_domain_migrations``.

    Returns:
        ``0`` on success (including "nothing pending"). ``1`` if
        applying the migrations raised a ``DatabaseError``.
    """
    return apply_domain_migrations(VALUATION_OBSERVATIONS_MIGRATIONS, "valuation_observation")


def main() -> int:
    return run_valuation_observation_migrations()


if __name__ == "__main__":
    sys.exit(main())
