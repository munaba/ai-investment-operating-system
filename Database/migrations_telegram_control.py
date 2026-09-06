"""Production migrations for ``telegram_command_audit`` and
``telegram_inbound_state`` (Phase E -- "Telegram Control Plane",
foundational task).

Version=25/26 (LOCKED DECISION): the next two free slots after
``Database.migrations_scheduler`` version=24 (Phase D), per
``Database.migration_registry.all_migrations()``'s single global
version sequence -- versions are reserved once, across every domain,
never reused or renumbered.

Two tables, both restart-safety infrastructure for a future Telegram
inbound-command control plane (router/executor NOT built in this
task -- see module docstring constraints):

* ``telegram_command_audit`` -- an append-only log (auto-increment
  ``id``) of every inbound Telegram command received and its
  resulting status. Never updated after insert -- mirrors the
  ``audit_events`` append-only pattern from
  ``Database.migrations_scheduler``.

* ``telegram_inbound_state`` -- one row per polling identity (primary
  key ``state_key``), recording the durable long-poll offset
  (``last_update_id``) so the inbound poller can resume after a
  restart without re-processing or dropping updates. A genuine upsert
  target, not an append-only log -- mirrors the
  ``notification_dedup_state`` single-row-per-key pattern from
  ``Database.migrations_scheduler``.

Not wired to automatic migration running by itself -- follows the
same manual-operator-step convention as
``migrations_scheduler``/``migrations_risk_ledger``: a caller passes
``TELEGRAM_CONTROL_MIGRATIONS`` to
``MigrationRunner(database).apply(TELEGRAM_CONTROL_MIGRATIONS)``
explicitly (see ``run_telegram_control_migrations.py``). Deliberately
NOT added to ``Database.migration_registry.MIGRATION_MODULES`` in this
task, mirroring every prior manual-migration domain -- ``python
main.py init`` behavior is left untouched, per the "preserve Phase
A-D" constraint.
"""

from __future__ import annotations

from .migrations import Migration

TELEGRAM_CONTROL_MIGRATIONS = (
    Migration(
        version=25,
        name="create_telegram_command_audit_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS telegram_command_audit (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                update_id     INTEGER,
                chat_id       TEXT,
                command       TEXT NOT NULL,
                raw_text      TEXT,
                status        TEXT NOT NULL,
                detail        TEXT,
                received_at   TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_telegram_command_audit_received_at "
            "ON telegram_command_audit (received_at)",
        ],
    ),
    Migration(
        version=26,
        name="create_telegram_inbound_state_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS telegram_inbound_state (
                state_key       TEXT PRIMARY KEY,
                last_update_id  INTEGER,
                updated_at      TEXT NOT NULL
            )
            """,
        ],
    ),
)