"""Production migrations for ``scheduler_job_runs``,
``notification_dedup_state``, and ``audit_events`` (Phase D --
"Proactive IDX Scheduler Routine").

Version=22/23/24 (LOCKED DECISION): the next three free slots after
``Database.migrations_risk_ledger`` version=21 (Phase C), per
``Database.migration_registry.all_migrations()``'s single global
version sequence -- versions are reserved once, across every domain,
never reused or renumbered.

Three tables, all restart-safety infrastructure for
``Orchestration.idx_daily_scheduler.IDXDailyScheduler``:

* ``scheduler_job_runs`` -- one row per ``(job_type, trading_date)``
  pair (composite primary key -- a genuine upsert target, not an
  append-only log), recording the latest attempt's status/attempt
  count/timestamps for that job on that IDX trading date. This is the
  *sole* mechanism the scheduler uses to decide "has this already run
  today" -- surviving a process restart requires nothing more than
  re-reading this table, which is exactly what
  ``SchedulerStateRepository.has_run_succeeded`` does.

* ``notification_dedup_state`` -- one row per ``alert_type`` (primary
  key), recording the signature and timestamp of the last alert
  actually *sent* for that type. Consulted by
  ``Business.notification_dedup_policy.NotificationDedupPolicy``
  (via ``NotificationDedupRepository``) before every candidate Telegram
  send.

* ``audit_events`` -- an append-only log (auto-increment ``id``) of
  every job start/success/failure, notification sent/suppressed/
  failed, and freshness degradation/recovery transition the scheduler
  produces. This is the "command/brief/error audit events" half of the
  Phase D Health/audit requirement; ``HealthAuditService`` reads the
  most recent rows from here.

Not wired to automatic migration running by itself -- follows the same
manual-operator-step convention as ``RISK_LEDGER_MIGRATIONS``: a
caller passes ``SCHEDULER_MIGRATIONS`` to
``MigrationRunner(database).apply(SCHEDULER_MIGRATIONS)`` explicitly
(see ``run_scheduler_migrations.py``). Deliberately NOT added to
``Database.migration_registry.MIGRATION_MODULES`` in this phase,
mirroring ``migrations_risk_ledger``/``migrations_decision_briefs`` --
``python main.py init`` behavior for existing domains is left
untouched, per the "preserve Phase A/B/C" constraint.
"""

from __future__ import annotations

from .migrations import Migration

SCHEDULER_MIGRATIONS = (
    Migration(
        version=22,
        name="create_scheduler_job_runs_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS scheduler_job_runs (
                job_type       TEXT NOT NULL,
                trading_date   TEXT NOT NULL,
                status         TEXT NOT NULL,
                attempt        INTEGER NOT NULL DEFAULT 1,
                started_at     TEXT NOT NULL,
                finished_at    TEXT,
                next_retry_at  TEXT,
                detail         TEXT,
                PRIMARY KEY (job_type, trading_date)
            )
            """,
        ],
    ),
    Migration(
        version=23,
        name="create_notification_dedup_state_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS notification_dedup_state (
                alert_type      TEXT PRIMARY KEY,
                last_signature  TEXT,
                last_sent_at    TEXT,
                last_status     TEXT,
                updated_at      TEXT NOT NULL
            )
            """,
        ],
    ),
    Migration(
        version=24,
        name="create_audit_events_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type  TEXT NOT NULL,
                payload     TEXT,
                created_at  TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_audit_events_created_at "
            "ON audit_events (created_at)",
        ],
    ),
)