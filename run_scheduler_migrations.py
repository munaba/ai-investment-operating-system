from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_scheduler import SCHEDULER_MIGRATIONS


def run_scheduler_migrations() -> int:
    """Apply ``SCHEDULER_MIGRATIONS`` to the production database.

    Manual, standalone operation -- see ``run_risk_ledger_migrations.py``
    for the full rationale. Thin wrapper around
    ``Database.migration_cli_helper.apply_domain_migrations``. Applies
    all three Phase D tables (``scheduler_job_runs``,
    ``notification_dedup_state``, ``audit_events`` -- versions 22/23/24)
    together -- they are one domain, the Phase D proactive IDX
    scheduler routine's restart-safety infrastructure.
    """
    return apply_domain_migrations(SCHEDULER_MIGRATIONS, "scheduler")


def main() -> int:
    return run_scheduler_migrations()


if __name__ == "__main__":
    sys.exit(main())