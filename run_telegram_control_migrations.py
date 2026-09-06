from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_telegram_control import TELEGRAM_CONTROL_MIGRATIONS


def run_telegram_control_migrations() -> int:
    """Apply ``TELEGRAM_CONTROL_MIGRATIONS`` to the production database.

    Manual, standalone operation -- see ``run_scheduler_migrations.py``
    for the full rationale. Thin wrapper around
    ``Database.migration_cli_helper.apply_domain_migrations``. Applies
    both Phase E foundational tables (``telegram_command_audit``,
    ``telegram_inbound_state`` -- versions 25/26) together -- they are
    one domain, the Telegram inbound control plane's restart-safety
    infrastructure.
    """
    return apply_domain_migrations(TELEGRAM_CONTROL_MIGRATIONS, "telegram_control")


def main() -> int:
    return run_telegram_control_migrations()


if __name__ == "__main__":
    sys.exit(main())