"""Apply the v2_rankings migration (version 35) to the production database.

Manual, standalone operation like every other ``run_*_migrations.py``:

    python run_v2_ranking_migrations.py
"""
from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_v2_rankings import V2_RANKINGS_MIGRATIONS


def main() -> int:
    return apply_domain_migrations(V2_RANKINGS_MIGRATIONS, "v2_rankings")


if __name__ == "__main__":
    sys.exit(main())
