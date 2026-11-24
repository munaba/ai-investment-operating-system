"""Credentials never reach stored error text or the public dashboard snapshot."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from Core.redaction import redact_secrets

_FAKE_TOKEN = "1234567890:AAH" + "x" * 32  # Telegram token shape, not a real token
_REQUESTS_ERROR = (
    "HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries exceeded with url: "
    f"/bot{_FAKE_TOKEN}/sendMessage (Caused by NameResolutionError(...))"
)


def test_telegram_token_in_request_url_is_redacted() -> None:
    redacted = redact_secrets(_REQUESTS_ERROR)
    assert _FAKE_TOKEN not in redacted
    assert "bot<redacted-telegram-token>/sendMessage" in redacted
    assert "api.telegram.org" in redacted  # the rest of the message stays useful


def test_other_credential_shapes_are_redacted() -> None:
    text = (
        "https://discord.com/api/webhooks/123456789012/abcDEF_ghi-JKL "
        "key=AIza" + "B" * 35 + " https://x.test/?api_key=secret123&q=1"
    )
    redacted = redact_secrets(text)
    assert "abcDEF_ghi-JKL" not in redacted
    assert "AIza" + "B" * 35 not in redacted
    assert "secret123" not in redacted
    assert "q=1" in redacted


def test_key_pattern_needs_a_word_boundary() -> None:
    assert redact_secrets("monkey=banana turnkey=yes") == "monkey=banana turnkey=yes"
    assert "secret" not in redact_secrets("GET /x?key=secret&page=2")


def test_log_lines_are_redacted_by_the_formatter() -> None:
    import logging

    from Core.logger import RedactingFormatter

    record = logging.LogRecord("t", logging.WARNING, __file__, 1, "send failed: %s", (_REQUESTS_ERROR,), None)
    line = RedactingFormatter("%(message)s").format(record)
    assert _FAKE_TOKEN not in line
    assert "redacted-telegram-token" in line


def test_discord_transport_error_does_not_carry_the_webhook_token() -> None:
    from Services.notification_service import NotificationService, NotificationServiceError

    webhook = "https://discord.com/api/webhooks/123456789012/AbCdEfGhIjKlMnOpQrStUvWxYz012345"

    class Boom:
        def post(self, url, **_kw):
            raise ConnectionError(f"Max retries exceeded with url: {url}")

    try:
        NotificationService._send_discord(Boom(), webhook, "hi", None, None)
    except NotificationServiceError as exc:
        text = str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected NotificationServiceError")
    assert "AbCdEfGhIjKlMnOpQrStUvWxYz012345" not in text
    assert "ConnectionError" in text


def test_db_writers_redact_error_text(tmp_path: Path) -> None:
    from Database.database_config import DatabaseConfig
    from Database.database_manager import DatabaseManager
    from Database.migration_registry import all_migrations
    from Database.migrations import MigrationRunner
    from Database.sqlite_database import SQLiteDatabase
    from Repository.persistence.audit_event_repository import AuditEventRepository
    from Repository.persistence.scheduler_state_repository import SchedulerStateRepository
    from Repository.persistence.telegram_command_audit_repository import TelegramCommandAuditRepository

    cfg = DatabaseConfig(db_path=tmp_path / "w.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    try:
        MigrationRunner(db).apply([m for m, _ in all_migrations()])
        manager = DatabaseManager(db, cfg)
        AuditEventRepository(manager).record("job_failed", created_at="t", payload={"error": _REQUESTS_ERROR})
        state = SchedulerStateRepository(manager)
        state.start("market_close_recap", "2026-11-24", started_at="t")
        state.mark_failed("market_close_recap", "2026-11-24", finished_at="t", detail=_REQUESTS_ERROR)
        TelegramCommandAuditRepository(manager).record("/x", status="ERROR", received_at="t", detail=_REQUESTS_ERROR)
        stored = " ".join(
            str(r) for table in ("audit_events", "scheduler_job_runs", "telegram_command_audit")
            for r in db.execute(f"SELECT * FROM {table}").rows
        )
    finally:
        db.disconnect()
    assert _FAKE_TOKEN not in stored
    assert stored.count("redacted-telegram-token") == 3


def test_plain_text_is_unchanged() -> None:
    assert redact_secrets("market data provider not reachable (BBCA.JK)") == (
        "market data provider not reachable (BBCA.JK)"
    )


def test_export_scrubs_tokens_and_drops_operator_free_text(tmp_path: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Dashboard"))
    from export_snapshot import export

    db = tmp_path / "live.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT);
        CREATE TABLE scheduler_job_runs (job_type TEXT, trading_date TEXT, status TEXT, attempt INTEGER,
            started_at TEXT, finished_at TEXT, next_retry_at TEXT, detail TEXT);
        CREATE TABLE accounts (account_id TEXT, account_name TEXT, mode TEXT, currency TEXT,
            asset_class TEXT, cash REAL, equity REAL, buying_power REAL, created_at TEXT, updated_at TEXT);
        CREATE TABLE final_review_records (review_id INTEGER, observation_window_id INTEGER,
            reviewed_at TEXT, evidence_status TEXT, known_limitations TEXT, operator_feedback_ids TEXT,
            human_decision TEXT, decision_note TEXT, decided_at TEXT, decided_by TEXT,
            created_at TEXT, updated_at TEXT);
        """
    )
    conn.execute(
        "INSERT INTO scheduler_job_runs VALUES ('market_close_recap','2026-11-24','FAILED',1,'t','t',NULL,?)",
        (_REQUESTS_ERROR,),
    )
    conn.execute("INSERT INTO accounts VALUES ('paper','Private Name','paper','IDR','stock_id',1,1,1,'t','t')")
    conn.execute(
        "INSERT INTO final_review_records VALUES (1,1,'t','PARTIAL','private limits','[1]','CONTINUE',"
        "'private note','t','Private Name','t','t')"
    )
    conn.commit()
    conn.close()

    out = tmp_path / "snapshot.json"
    export(db, out, with_evaluation=False)
    text = out.read_text(encoding="utf-8")

    assert _FAKE_TOKEN not in text
    assert "Private Name" not in text
    assert "private note" not in text and "private limits" not in text
    data = json.loads(text)
    assert data["tables"]["accounts"][0]["cash"] == 1
    assert "redacted-telegram-token" in data["tables"]["scheduler_job_runs"][0]["detail"]
