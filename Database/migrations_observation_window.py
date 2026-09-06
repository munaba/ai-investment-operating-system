"""Production migration for ``operator_observation_windows`` (Phase H
Task 1 -- "Observation Window + Sustained-Use Review Record").

Version=30 (LOCKED DECISION): the next free slot after
``Database.migrations_portfolio_snapshot_valuation_status`` version=29,
per the same "grep every ``Database/migrations_*.py`` ``version=``
literal before choosing it" convention every prior domain migration
documents (confirmed: 1-29 are all already allocated across the other
``migrations_*.py`` files; 30 is the first free slot).

Purpose: Phase H's objective is a human decision -- continue,
simplify, or separately authorize a future market/broker investigation
-- made only after reviewing real operating records over an
operator-selected stretch of time. Before that review can happen at
all, there must be a durable, restart-safe record of *which* stretch
of time the operator actually chose to review. This table is exactly
that record and nothing more: it holds no metric, no computed
adherence/drawdown/reconciliation figure, no alert or freshness data.
Every other Phase H sub-concern (review availability, data freshness
failures, alert usefulness, plan/journal adherence, paper
reconciliation, drawdown/process metrics, operator feedback) is
future, separate work that would read data already produced by
Phase A-G's existing tables (journal, paper review, portfolio
snapshots, scheduler/Telegram audit) filtered to a window recorded
here -- not implemented in this task.

``operator_observation_windows`` is an append-only history of windows
(mirrors ``DecisionBriefRepository``'s append-only design, not
``RiskLimitsRepository``'s single mutable row): a person may open,
close, and later open a second, different window to compare periods,
so each ``open`` gets its own row rather than overwriting the last
one. Exactly one row may be ``ACTIVE`` at a time (enforced by
``Services.observation_window_service.ObservationWindowService``, not
by this schema) -- ``status`` is what lets a restart distinguish "the
window currently being reviewed" from "a window reviewed previously".

Not wired to automatic migration running by itself -- follows the
same manual-operator-step convention as
``SCHEDULER_MIGRATIONS``/``RISK_LEDGER_MIGRATIONS``/
``DECISION_BRIEFS_MIGRATIONS``: a caller passes
``OBSERVATION_WINDOW_MIGRATIONS`` to
``MigrationRunner(database).apply(OBSERVATION_WINDOW_MIGRATIONS)``
explicitly (see ``run_observation_window_migrations.py``). Deliberately
NOT added to ``Database.migration_registry.MIGRATION_MODULES`` in this
phase, for the same reason -- ``python main.py init`` behavior for
existing domains is left untouched.
"""

from __future__ import annotations

from .migrations import Migration

# Migration version allocation (global, shared schema_migrations table):
#   ... 28 = valuation_observations, 29 = portfolio_snapshot_valuation_status
#   -- 30 is the first free slot after 1-29, confirmed by grepping every
#   Database/migrations_*.py `version=` literal before choosing it.
OBSERVATION_WINDOW_MIGRATIONS = (
    Migration(
        version=30,
        name="create_operator_observation_windows_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS operator_observation_windows (
                window_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                start_at     TEXT NOT NULL,
                end_at       TEXT NOT NULL,
                timezone     TEXT NOT NULL,
                note         TEXT,
                status       TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                closed_at    TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_observation_windows_status "
            "ON operator_observation_windows (status)",
        ],
    ),
)
