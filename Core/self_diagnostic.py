from __future__ import annotations

"""Activation 12 read-only self-diagnostic aggregation.

Reuses the existing doctor checks, repositories, reconciliation engine,
notification configuration, and tool registry. This module only observes
state; it never repairs, executes trades, sends notifications, or runs
migrations.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from Agents.tool_registry import tool_registry
from Business.reconciliation_engine import ReconciliationEngine
from Core.doctor import BLOCKED, OPTIONAL_MISSING, READY, CheckResult, Section
from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.sqlite_database import SQLiteDatabase
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.order_repository import OrderRepository
from Repository.persistence.position_repository import PositionRepository
from Repository.persistence.trade_repository import TradeRepository
from Core.config import config


@dataclass(frozen=True)
class SelfDiagnosticPolicy:
    """Small explicit policies used by the diagnostic only."""

    stale_after_hours: float = 24.0


def _parse_timestamp(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _policy() -> SelfDiagnosticPolicy:
    try:
        hours = config.get_float("AIOS_DATA_STALE_AFTER_HOURS", 24.0)
    except Exception:
        hours = 24.0
    return SelfDiagnosticPolicy(stale_after_hours=max(0.0, hours))


def _check_data_freshness(db_config: DatabaseConfig) -> Section:
    path = Path(db_config.db_path)
    if not path.is_file():
        return Section(
            name="Data Freshness",
            checks=[
                CheckResult(
                    "Latest ranking snapshot",
                    OPTIONAL_MISSING,
                    "database file does not exist; freshness cannot be measured",
                )
            ],
        )

    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        import sqlite3

        with sqlite3.connect(uri, uri=True, timeout=5.0) as conn:
            row = conn.execute(
                "SELECT MAX(scan_time) FROM ranking_snapshots"
            ).fetchone()
    except sqlite3.Error as exc:
        return Section(
            name="Data Freshness",
            checks=[CheckResult("Latest ranking snapshot", BLOCKED, f"read failed: {exc}")],
        )

    latest = row[0] if row else None
    if not latest:
        return Section(
            name="Data Freshness",
            checks=[
                CheckResult(
                    "Latest ranking snapshot",
                    BLOCKED,
                    "no ranking snapshot exists; data freshness cannot be established",
                )
            ],
        )

    parsed = _parse_timestamp(latest)
    if parsed is None:
        return Section(
            name="Data Freshness",
            checks=[
                CheckResult(
                    "Latest ranking snapshot",
                    BLOCKED,
                    f"latest scan_time is not valid ISO-8601: {latest!r}",
                )
            ],
        )

    age_hours = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0)
    threshold = _policy().stale_after_hours
    stale = age_hours > threshold
    return Section(
        name="Data Freshness",
        checks=[
            CheckResult(
                "Latest ranking snapshot",
                BLOCKED if stale else READY,
                f"latest={latest}; age={age_hours:.2f}h; threshold={threshold:.2f}h",
            )
        ],
    )


def _check_account_reconciliation(db_config: DatabaseConfig) -> Section:
    path = Path(db_config.db_path)
    if not path.is_file():
        return Section(
            name="Account Reconciliation",
            checks=[CheckResult("Accounts", OPTIONAL_MISSING, "database file does not exist")],
        )

    database = SQLiteDatabase(db_config)
    manager = DatabaseManager(database, db_config)
    try:
        manager.connect()
        accounts = AccountRepository(manager).list_all()
        if not accounts:
            return Section(
                name="Account Reconciliation",
                checks=[CheckResult("Accounts", OPTIONAL_MISSING, "no accounts exist")],
            )

        engine = ReconciliationEngine(
            OrderRepository(manager),
            TradeRepository(manager),
            AccountRepository(manager),
            PositionRepository(manager),
        )
        checks: List[CheckResult] = []
        for account in accounts:
            result = engine.reconcile_account(account.account_id)
            if result.consistent:
                detail = "CONSISTENT"
                if result.not_verifiable:
                    detail += "; " + "; ".join(result.not_verifiable)
                checks.append(CheckResult(account.account_id, READY, detail))
            else:
                detail = "; ".join(result.violations)
                if result.not_verifiable:
                    detail += "; not-verifiable: " + "; ".join(result.not_verifiable)
                checks.append(CheckResult(account.account_id, BLOCKED, detail))
        return Section(name="Account Reconciliation", checks=checks)
    except Exception as exc:  # diagnostic boundary: report, never repair
        return Section(
            name="Account Reconciliation",
            checks=[CheckResult("Accounts", BLOCKED, f"reconciliation check failed: {exc}")],
        )
    finally:
        manager.disconnect()


def _check_notification_health() -> Section:
    token = config.get("TELEGRAM_BOT_TOKEN")
    chat_id = config.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return Section(
            name="Notifications",
            checks=[
                CheckResult(
                    "Telegram channel",
                    OPTIONAL_MISSING,
                    "not configured; no persisted notification-failure ledger exists in the current schema",
                )
            ],
        )
    return Section(
        name="Notifications",
        checks=[
            CheckResult(
                "Telegram channel",
                READY,
                "credentials configured; current repository has no persisted notification-failure history to inspect",
            )
        ],
    )


def _check_tools() -> Section:
    tools = tool_registry.list()
    if not tools:
        return Section(
            name="Tool Availability",
            checks=[
                CheckResult(
                    "Agent tool registry",
                    OPTIONAL_MISSING,
                    "registry is not populated in this process; no tool execution was attempted",
                )
            ],
        )
    return Section(
        name="Tool Availability",
        checks=[
            CheckResult(
                "Agent tool registry",
                READY,
                f"{len(tools)} registered tool(s): {', '.join(sorted(t.name for t in tools))}",
            )
        ],
    )


def run_self_diagnostic(db_config: Optional[DatabaseConfig] = None) -> List[Section]:
    """Return Activation 12 diagnostic sections without mutating state."""
    db_config = db_config or DatabaseConfig.from_env()
    return [
        _check_data_freshness(db_config),
        _check_account_reconciliation(db_config),
        _check_notification_health(),
        _check_tools(),
    ]
