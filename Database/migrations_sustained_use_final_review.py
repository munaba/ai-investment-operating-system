"""Production migrations for ``operator_feedback`` and
``final_review_records`` (Phase H Task 4 -- "Operator Feedback + Final
Review Record").

Version=31/32 (LOCKED DECISION): the next two free slots after
``Database.migrations_observation_window`` version=30, per the same
"grep every ``Database/migrations_*.py`` ``version=`` literal before
choosing it" convention every prior domain migration documents
(confirmed: 1-30 are all already allocated across the other
``migrations_*.py`` files; 31/32 are the first two free slots).

Purpose: Phase H Task 2 (``SustainedUseReviewService``) and Task 3
(``SustainedUseReportService``) already produce real, honest,
possibly-partial evidence about one ``ObservationWindow``. Task 4 adds
exactly two durable records on top of that evidence -- nothing else:

    * ``operator_feedback`` -- real, explicitly-given operator
      feedback about a window's sustained-use review (append-only,
      mirrors ``decision_briefs``/``operator_observation_windows``: an
      operator may give feedback more than once for the same window).
    * ``final_review_records`` -- the single durable record per
      window that ties evidence status + known limitations + linked
      feedback together with the one deliberate human decision
      (``PENDING``/``CONTINUE``/``SIMPLIFY``/
      ``AUTHORIZE_FUTURE_INVESTIGATION``) that closes Phase H's review
      loop for that window. Exactly one row per
      ``observation_window_id`` (unique index), updated in place --
      mirrors ``risk_limits``'s single-mutable-row convention, not an
      append-only history, because a window has exactly one final
      review.

Neither table stores, computes, or infers any trading/risk/execution
value -- both are pure operator-input/decision-bookkeeping records,
same spirit as ``operator_observation_windows``.

Not wired to automatic migration running by itself -- follows the same
manual-operator-step convention as
``SCHEDULER_MIGRATIONS``/``RISK_LEDGER_MIGRATIONS``/
``OBSERVATION_WINDOW_MIGRATIONS``: a caller passes
``SUSTAINED_USE_FINAL_REVIEW_MIGRATIONS`` to
``MigrationRunner(database).apply(SUSTAINED_USE_FINAL_REVIEW_MIGRATIONS)``
explicitly (see ``run_sustained_use_final_review_migrations.py``).
Deliberately NOT added to ``Database.migration_registry.
MIGRATION_MODULES`` in this phase, for the same reason --
``python main.py init`` behavior for existing domains is left
untouched.
"""

from __future__ import annotations

from .migrations import Migration

# Migration version allocation (global, shared schema_migrations table):
#   ... 29 = portfolio_snapshot_valuation_status, 30 = observation_window
#   -- 31/32 are the first two free slots after 1-30, confirmed by
#   grepping every Database/migrations_*.py `version=` literal before
#   choosing them.
SUSTAINED_USE_FINAL_REVIEW_MIGRATIONS = (
    Migration(
        version=31,
        name="create_operator_feedback_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS operator_feedback (
                feedback_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_window_id       INTEGER NOT NULL,
                recorded_at                 TEXT NOT NULL,
                operator_rating             INTEGER,
                alert_usefulness            TEXT,
                data_reliability_feedback   TEXT,
                decision_quality_feedback   TEXT,
                workflow_usability_feedback TEXT,
                free_text                   TEXT,
                concerns                    TEXT NOT NULL DEFAULT '[]',
                operator_label              TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_operator_feedback_window "
            "ON operator_feedback (observation_window_id)",
        ],
    ),
    Migration(
        version=32,
        name="create_final_review_records_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS final_review_records (
                review_id              INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_window_id  INTEGER NOT NULL,
                reviewed_at            TEXT NOT NULL,
                evidence_status        TEXT NOT NULL,
                known_limitations      TEXT NOT NULL DEFAULT '[]',
                operator_feedback_ids  TEXT NOT NULL DEFAULT '[]',
                human_decision         TEXT NOT NULL DEFAULT 'PENDING',
                decision_note          TEXT,
                decided_at             TEXT,
                decided_by             TEXT,
                created_at             TEXT NOT NULL,
                updated_at             TEXT NOT NULL
            )
            """,
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_final_review_records_window "
            "ON final_review_records (observation_window_id)",
            "CREATE INDEX IF NOT EXISTS idx_final_review_records_decision "
            "ON final_review_records (human_decision)",
        ],
    ),
)