"""Production migration for the ``accounts`` table (Sprint 3 STEP 3).

Accounts are the root of every portfolio (paper/live, ID/US stock,
crypto, forex). ``account_id`` is a stable, caller-assigned string
identifier (e.g. ``"paper-id"``, ``"crypto-main"``) -- deliberately
NOT an autoincrement integer, so identity survives database export/
import/restore/cross-device sync. Repository never generates it.

``mode`` and ``asset_class`` are constrained via SQL ``CHECK``,
generated from ``Database.account_constants`` -- the same single
source of truth ``Repository.persistence.account_repository.
AccountRepository`` reads for its own Python-level validation. See
that module's docstring for the trade-off around changing these
values after this migration has already been applied.

Kept separate from ``Database.schema.BOOTSTRAP_STATEMENTS`` (bootstrap
is reserved for the ``schema_migrations`` table itself) and from
``Database.migrations_watchlist`` (a different, already-applied
version), mirroring the same pattern.

Not wired to ``Core.composition_root`` or ``main.py`` (same A2 scope
decision as watchlist: no composition-root changes, no automatic
migration run, no wiring). A caller passes ``ACCOUNTS_MIGRATIONS`` to
``MigrationRunner(database).apply(ACCOUNTS_MIGRATIONS)`` explicitly --
see ``run_account_migrations.py``.
"""

from __future__ import annotations

from .account_constants import ACCOUNT_ASSET_CLASSES, ACCOUNT_MODES
from .migrations import Migration


def _sql_in_list(values: "tuple[str, ...]") -> str:
    """Render ``values`` as a SQL ``IN (...)`` literal list, e.g. ('paper', 'live').

    ``values`` are always literal Python tuples defined in
    ``Database.account_constants``, never external/user input -- this
    is schema-definition code, not a query builder, so there is no SQL
    injection surface here.
    """
    return ", ".join(f"'{v}'" for v in values)


# Migration version allocation (global, shared schema_migrations table):
#   1 = watchlist (Database.migrations_watchlist)
#   2 = accounts (this file)
#   3 = positions, 4 = orders, 5 = trades, 6 = analysis_snapshots,
#   7 = recommendations, 8 = portfolio_snapshots, 9 = daily_performance
#   -- reserved in that order for later Sprint 3 STEPs. Do not reuse.
ACCOUNTS_MIGRATIONS = (
    Migration(
        version=2,
        name="create_accounts_table",
        up_statements=[
            f"""
            CREATE TABLE IF NOT EXISTS accounts (
                account_id      TEXT PRIMARY KEY,
                account_name    TEXT NOT NULL UNIQUE,
                mode            TEXT NOT NULL CHECK (mode IN ({_sql_in_list(ACCOUNT_MODES)})),
                currency        TEXT NOT NULL,
                asset_class     TEXT NOT NULL CHECK (
                                    asset_class IN ({_sql_in_list(ACCOUNT_ASSET_CLASSES)})
                                ),
                cash            REAL NOT NULL,
                equity          REAL NOT NULL,
                buying_power    REAL NOT NULL,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """
        ],
    ),
)
