from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_sustained_use_final_review import (
    SUSTAINED_USE_FINAL_REVIEW_MIGRATIONS,
)


def run_sustained_use_final_review_migrations() -> int:
    """Apply ``SUSTAINED_USE_FINAL_REVIEW_MIGRATIONS`` to the production
    database.

    Manual, standalone operation -- see ``run_observation_window_migrations.py``
    for the full rationale. Thin wrapper around
    ``Database.migration_cli_helper.apply_domain_migrations``. Applies
    the two Phase H Task 4 tables (``operator_feedback`` -- version 31,
    ``final_review_records`` -- version 32).
    """
    return apply_domain_migrations(
        SUSTAINED_USE_FINAL_REVIEW_MIGRATIONS, "sustained-use final review"
    )


def main() -> int:
    return run_sustained_use_final_review_migrations()


if __name__ == "__main__":
    sys.exit(main())