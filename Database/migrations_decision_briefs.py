"""Production migration for the ``decision_briefs`` table (Phase B --
Decision Copilot).

Version=19 (LOCKED DECISION): the next free slot after
``Database.migrations_positions`` version=18, per
``Database.migration_registry.all_migrations()``'s single global
version sequence -- versions are reserved once, across every domain,
never reused or renumbered.

Deliberately minimal, mirroring ``Database.migrations_snapshots``'s
own append-only design:

* ``brief_id`` -- repository-generated surrogate integer primary key,
  same reasoning as ``RankingSnapshot.snapshot_id``: a symbol has no
  stable natural key here, since ``DecisionBriefService`` can be asked
  to brief the same symbol many times over.
* ``status`` -- one of the eight Phase-B statuses. Only ``SUCCESS``
  rows may carry a non-NULL plan; every other status leaves the five
  plan columns NULL. Enforced in ``Services.decision_brief_service``,
  not by a DB constraint, mirroring how ``RankingSnapshot.status``
  ("success"/"error") is application-enforced rather than
  constraint-enforced.
* ``source_snapshot_id`` -- a plain ``REFERENCES ranking_snapshots``
  foreign key (this project's ``SQLiteDatabase`` enables
  ``PRAGMA foreign_keys = ON`` by default, so this is enforced, not
  decorative), pointing at the exact ``RankingSnapshot`` a brief was
  derived from. Nullable: a brief with no matching snapshot at all
  (e.g. ``DATA_STALE``/``INSUFFICIENT_DATA`` because nothing has ever
  been scanned) still gets a row, with no snapshot to point at.
* Plan columns (``entry_price``/``stop_loss_price``/
  ``take_profit_price``/``risk_amount``/``position_size``/
  ``risk_reward_ratio``) -- the verbatim ``RiskManagementService``
  output for ``SUCCESS`` rows, NULL otherwise. Never recomputed by any
  query against this table.

Not wired to automatic migration running by itself -- follows the same
manual-operator-step convention as ``ORDERS_MIGRATIONS``/
``SNAPSHOTS_MIGRATIONS``/etc: a caller passes
``DECISION_BRIEFS_MIGRATIONS`` to
``MigrationRunner(database).apply(DECISION_BRIEFS_MIGRATIONS)``
explicitly (see ``run_decision_brief_migrations.py``), and it is
additionally registered in ``Database.migration_registry.
MIGRATION_MODULES`` so ``python main.py init`` picks it up like every
other domain.
"""

from __future__ import annotations

from .migrations import Migration

DECISION_BRIEFS_MIGRATIONS = (
    Migration(
        version=19,
        name="create_decision_briefs_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS decision_briefs (
                brief_id            INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol              TEXT NOT NULL,
                generated_at        TEXT NOT NULL,
                status              TEXT NOT NULL,
                source_snapshot_id  INTEGER REFERENCES ranking_snapshots(snapshot_id),
                reason              TEXT,
                entry_price         REAL,
                stop_loss_price     REAL,
                take_profit_price   REAL,
                risk_amount         REAL,
                position_size       REAL,
                risk_reward_ratio   REAL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_decision_briefs_symbol_generated_at
            ON decision_briefs (symbol, generated_at)
            """,
        ],
    ),
)