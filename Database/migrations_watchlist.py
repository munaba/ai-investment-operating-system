"""Production migrations for the ``watchlist`` table (A2).

Deliberately minimal, per the A2 scope decision:

* ``ticker`` is the primary key -- no surrogate ``id``, since a ticker is
  already naturally unique on a single-user watchlist.
* ``added_at`` (ISO-8601 UTC string) is the only other column.
* No ``user_id``/scope, no ``notes``, no ``category``, no other metadata --
  none of it has a use-case yet. Extending the schema later is a new
  migration appended to ``WATCHLIST_MIGRATIONS`` (or a new tuple), not a
  change to this one -- ``version=1`` is never edited once applied.

Kept separate from ``Database.schema.BOOTSTRAP_STATEMENTS`` on purpose:
bootstrap is reserved for the ``schema_migrations`` bookkeeping table
itself (see ``Database/schema.py``); everything domain-specific, including
this, goes through ``Database.migrations.MigrationRunner`` instead.

Not wired to ``Core.composition_root`` or ``main.py`` (A2 scope: no
composition-root changes, no automatic migration run, no wiring). A
caller passes ``WATCHLIST_MIGRATIONS`` to
``MigrationRunner(database).apply(WATCHLIST_MIGRATIONS)`` explicitly --
see ``Tests/test_watchlist_migration.py`` for the exact usage.
"""

from __future__ import annotations

from .migrations import Migration

WATCHLIST_MIGRATIONS = (
    Migration(
        version=1,
        name="create_watchlist_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker      TEXT PRIMARY KEY,
                added_at    TEXT NOT NULL
            )
            """
        ],
    ),
)