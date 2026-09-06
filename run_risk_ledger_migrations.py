from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_risk_ledger import RISK_LEDGER_MIGRATIONS


def run_risk_ledger_migrations() -> int:
    """Apply ``RISK_LEDGER_MIGRATIONS`` to the production database.

    Manual, standalone operation -- see ``run_watchlist_migrations.py``
    for the full rationale. Thin wrapper around
    ``Database.migration_cli_helper.apply_domain_migrations``. Applies
    both the ``risk_limits`` and ``journal_entries`` tables (versions
    20 and 21) together -- they are one domain, Phase C's personal
    risk ledger + decision journal.
    """
    return apply_domain_migrations(RISK_LEDGER_MIGRATIONS, "risk_ledger")


def main() -> int:
    return run_risk_ledger_migrations()


if __name__ == "__main__":
    sys.exit(main())