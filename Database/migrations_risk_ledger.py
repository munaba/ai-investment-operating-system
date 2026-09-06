"""Production migrations for the ``risk_limits`` and ``journal_entries``
tables (Phase C -- "Personal Risk Ledger + Decision Journal").

Version=20/21 (LOCKED DECISION): the next two free slots after
``Database.migrations_decision_briefs`` version=19, per
``Database.migration_registry.all_migrations()``'s single global
version sequence -- versions are reserved once, across every domain,
never reused or renumbered.

Two tables, mirroring the append-only / mutable-singleton split
already established elsewhere in this schema:

* ``risk_limits`` -- a single mutable row (``id`` fixed to
  ``'default'``), the same "one row, updated in place" shape as
  ``accounts`` (see ``Database.migrations_accounts``): reference
  capital, max risk per trade (percent of reference capital), max
  daily loss (absolute), max decisions/trades per day, loss-streak
  cooldown (consecutive realized losses), and an optional
  comma-separated allowed-symbol allowlist. Restart-safe: the row
  survives a process restart unchanged until explicitly re-saved.

* ``journal_entries`` -- one row per TAKE/SKIP/WAIT decision a person
  records against an existing ``DecisionBrief``
  (``brief_id`` REFERENCES ``decision_briefs``, FK enforced --
  ``PRAGMA foreign_keys = ON``). The decision itself
  (``decision``/``risk_policy_status``/``risk_policy_reason``/
  ``planned_r``) is set once at creation and never changed after
  (mirrors ``decision_briefs``' append-only convention for its
  verdict). The five outcome columns
  (``outcome_status``/``exit_price``/``realized_r``/``closed_at``)
  start ``NULL`` and may be filled in exactly once, later, via a
  separate manual "close" call -- this is the one deliberate
  exception to strict append-only-ness in this table, matching how a
  real trade's outcome is only known after the fact. This table has
  no foreign key to, and no code path writes to, ``orders``/
  ``trades``/``positions``: recording a journal decision -- of any
  kind, including an ACCEPTED TAKE -- never creates a paper order.

Not wired to automatic migration running by itself -- follows the
same manual-operator-step convention as
``DECISION_BRIEFS_MIGRATIONS``/etc: a caller passes
``RISK_LEDGER_MIGRATIONS`` to
``MigrationRunner(database).apply(RISK_LEDGER_MIGRATIONS)`` explicitly
(see ``run_risk_ledger_migrations.py``). Deliberately NOT added to
``Database.migration_registry.MIGRATION_MODULES`` in this phase,
mirroring ``migrations_decision_briefs`` (Phase B), which is also not
registered there -- ``python main.py init`` behavior for existing
domains is left untouched, per the Phase C "preserve Phase A/B"
constraint.
"""

from __future__ import annotations

from .migrations import Migration

RISK_LEDGER_MIGRATIONS = (
    Migration(
        version=20,
        name="create_risk_limits_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS risk_limits (
                id                          TEXT PRIMARY KEY,
                reference_capital           REAL NOT NULL,
                max_risk_per_trade_percent  REAL NOT NULL,
                max_daily_loss              REAL NOT NULL,
                max_trades_per_day          INTEGER NOT NULL,
                loss_streak_cooldown        INTEGER NOT NULL,
                allowed_symbols             TEXT,
                updated_at                  TEXT NOT NULL
            )
            """,
        ],
    ),
    Migration(
        version=21,
        name="create_journal_entries_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS journal_entries (
                entry_id            INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_id            INTEGER NOT NULL REFERENCES decision_briefs(brief_id),
                symbol              TEXT NOT NULL,
                decision            TEXT NOT NULL CHECK (decision IN ('TAKE', 'SKIP', 'WAIT')),
                decided_at          TEXT NOT NULL,
                note                TEXT,
                risk_policy_status  TEXT NOT NULL CHECK (risk_policy_status IN ('ACCEPTED', 'RISK_REJECTED')),
                risk_policy_reason  TEXT,
                planned_r           REAL,
                outcome_status      TEXT CHECK (
                                        outcome_status IS NULL OR outcome_status IN (
                                            'OPEN', 'CLOSED_WIN', 'CLOSED_LOSS', 'CLOSED_BREAKEVEN'
                                        )
                                     ),
                exit_price          REAL,
                realized_r          REAL,
                closed_at           TEXT,
                created_at          TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_journal_entries_symbol_decided_at
            ON journal_entries (symbol, decided_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_journal_entries_brief_id
            ON journal_entries (brief_id)
            """,
        ],
    ),
)