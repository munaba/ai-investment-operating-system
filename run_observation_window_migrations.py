from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_observation_window import OBSERVATION_WINDOW_MIGRATIONS


def run_observation_window_migrations() -> int:
    """Apply ``OBSERVATION_WINDOW_MIGRATIONS`` to the production database.

    Manual, standalone operation -- see ``run_risk_ledger_migrations.py``
    for the full rationale. Thin wrapper around
    ``Database.migration_cli_helper.apply_domain_migrations``. Applies
    the one Phase H Task 1 table (``operator_observation_windows`` --
    version 30).
    """
    return apply_domain_migrations(OBSERVATION_WINDOW_MIGRATIONS, "observation window")


def main() -> int:
    return run_observation_window_migrations()


if __name__ == "__main__":
    sys.exit(main())
