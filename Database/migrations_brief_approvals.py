"""Production migration for the ``brief_approvals`` table (Phase G,
Task 1/2 -- "Approved Brief -> Paper Link Contract").

Version=27 (LOCKED DECISION): the next free slot after
``Database.migrations_telegram_control`` version=26, per the same
"grep every ``Database/migrations_*.py`` ``version=`` literal before
choosing it" convention every prior domain migration documents (see
e.g. ``Database.migrations_order_approvals``).

Purpose (Phase G Task 1 audit conclusion): nothing in the existing
schema can represent "this specific, explicitly-approved
``DecisionBrief`` was linked to this specific paper order/trade"
without conflating it with the unrelated ``order_approvals`` table
(Activation 7 Blocker #4), which records the ``user_approval`` boolean
``PaperTradingEngine.submit_order()`` gate 3 already required -- not
"which brief, if any, justified this order". This table is the
narrow, additive link the audit identified as missing, and nothing
else.

Columns:

* ``brief_id`` -- the primary key. Deliberately NOT a surrogate
  integer: a ``DecisionBrief`` may be linked to at most one paper
  order/trade (Phase G roadmap requirement -- "the linkage" is
  singular), so ``brief_id`` is already a unique, unambiguous key for
  its own link row, exactly like ``order_approvals.order_id`` is the
  natural (not surrogate) key for its table. A plain ``REFERENCES
  decision_briefs(brief_id)`` foreign key (this project's
  ``SQLiteDatabase`` enables ``PRAGMA foreign_keys = ON`` by default,
  so this is enforced, not decorative).
* ``order_id`` / ``trade_id`` -- linkage to the exact ``Order``/
  ``Trade`` this approved brief resulted in, both with ``REFERENCES``
  foreign keys, mirroring ``order_approvals.order_id``/``trade_id``
  exactly.
* ``approved_at`` -- the timestamp of the explicit human approval
  decision that gated this link (supplied by
  ``Services.brief_approval_service.BriefApprovalService``, which
  generates it at the moment it verifies ``approved is True`` --
  before ``PaperTradingEngine.submit_order()`` is ever called).
* ``recorded_at`` -- this row's own write timestamp, mirroring
  ``order_approvals.recorded_at``: written *after* the paper trade
  this row links to is already fully committed, best-effort, and
  never used to roll back that trade if the write fails (see
  ``BriefApprovalService`` for the exact call site and failure
  handling).

Immutable / append-only, mirroring ``order_approvals``: no
``UPDATE``/``DELETE`` statement is ever issued against this table by
this codebase. One row per ``brief_id`` -- the ``PRIMARY KEY``
constraint is what actually enforces "one link per brief", not
application code alone.

Not wired to ``Core.composition_root``, ``main.py``, or
``Database.migration_registry.MIGRATION_MODULES`` -- same scope
decision already made (in practice, not merely in an earlier
docstring) for every domain added after Activation 7 Blocker #4
(``decision_briefs``, ``daily_performance``, ``risk_ledger``,
``scheduler``, ``telegram_control`` are none of them present in
``MIGRATION_MODULES`` either): a caller applies
``BRIEF_APPROVALS_MIGRATIONS`` explicitly via
``MigrationRunner(database).apply(BRIEF_APPROVALS_MIGRATIONS)`` (see
``run_brief_approval_migrations.py``). ``Database.migration_registry``
itself is untouched by this Phase G task, per the roadmap's "do not
modify Phase A-F" instruction covering shared infrastructure.
"""

from __future__ import annotations

from .migrations import Migration

# Migration version allocation (global, shared schema_migrations table):
#   ... 16 = order_approvals, 19 = decision_briefs, 25/26 =
#   telegram_control -- 27 is the first free slot after 1-26,
#   confirmed by grepping every Database/migrations_*.py `version=`
#   literal before choosing it.
BRIEF_APPROVALS_MIGRATIONS = (
    Migration(
        version=27,
        name="create_brief_approvals_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS brief_approvals (
                brief_id     INTEGER PRIMARY KEY REFERENCES decision_briefs(brief_id),
                order_id     INTEGER NOT NULL REFERENCES orders(order_id),
                trade_id     INTEGER NOT NULL REFERENCES trades(trade_id),
                approved_at  TEXT NOT NULL,
                recorded_at  TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_brief_approvals_order_id
            ON brief_approvals (order_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_brief_approvals_trade_id
            ON brief_approvals (trade_id)
            """,
        ],
    ),
)