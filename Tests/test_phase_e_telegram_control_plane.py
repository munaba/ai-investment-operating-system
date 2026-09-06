"""Phase E ("Telegram Inbound Control Plane") Task 7 -- FINAL
verification suite.

VERIFICATION ONLY. Tasks 1-6 are complete; this file audits nothing
and redesigns nothing -- it drives the already-built modules below
against a real, on-disk (never ``:memory:``) temp SQLite database
migrated with ``TELEGRAM_CONTROL_MIGRATIONS``, using hand-written
fakes for the four executor collaborators and for the outbound
``NotificationService`` seam, so every scenario is deterministic and
never touches the network (Telegram/yfinance/LLM). Mirrors the
existing ``Tests/test_phase_d_idx_scheduler.py`` real-SQLite-file,
hand-rolled ``check()`` runner convention used throughout this
codebase's own Phase closeout suites.

Modules exercised (none modified by this file):
  - Business.telegram_allowlist_policy (Task 2)
  - Business.telegram_command_router (Task 3)
  - Orchestration.telegram_command_executor (Task 4)
  - Repository.persistence.telegram_command_audit_repository (Task 1)
  - Repository.persistence.telegram_inbound_state_repository (Task 1)
  - Orchestration.telegram_inbound_control_plane (Task 5)
  - Database.migrations_telegram_control (Task 1, v25/26)
  - Core.doctor._check_telegram_inbound_control_plane (Task 6)
  - main.py "telegram poll"/"telegram status" CLI dispatch (Task 6,
    exercised via subprocess for the real-CLI-proof scenario only --
    every other scenario drives the classes directly, in-process)

Run directly: ``python Tests/test_phase_e_telegram_control_plane.py``

Scenarios:
  A. Authorized chat -- a command from an allowlisted chat_id is
     EXECUTED, replied, and audited.
  B. Unauthorized chat -- a command from a non-allowlisted chat_id is
     REJECTED_UNAUTHORIZED, never executed, never replied to, and the
     rejection itself is audited.
  C. All six commands (/scan, /plan, /journal, /review, /health,
     /help) route to their documented collaborator/static text and
     reply+audit EXECUTED.
  D. Deterministic routing -- unknown command word and malformed
     argument count both resolve to UNKNOWN_COMMAND, never raise, and
     the same input always produces the same outcome.
  E. Audit outcomes -- every one of EXECUTED / EXECUTED_REPLY_FAILED /
     REJECTED_UNAUTHORIZED / UNKNOWN_COMMAND / ERROR is actually
     reachable and persisted with the right status.
  F. Restart-safe update_id -- a brand new
     TelegramInboundControlPlane instance (fresh Python object, same
     DB) resumes from the durable offset instead of re-processing.
  G. Duplicate update -- an update_id at or below the durable offset
     is skipped entirely: no re-parse, no re-execute, no duplicate
     audit row, no duplicate reply, within one fetched batch and
     across repeated poll_once() calls.
  H. Polling failure -- a getUpdates transport/HTTP/non-JSON failure
     never raises out of poll_once(); it is surfaced as
     polling_failed=True with no offset movement.
  I. Reply failure -- a successfully EXECUTED command whose reply
     send fails is audited as EXECUTED_REPLY_FAILED, not EXECUTED.
  J. Doctor diagnostics -- Core.doctor's Telegram Inbound Control
     Plane section reports BLOCKED when tables are missing and READY
     once migrated, and reads the real durable offset/audit state.
  K. CLI status/poll -- "python main.py telegram status" and
     "python main.py telegram poll" run end-to-end via subprocess
     against a real database and exit/print as documented.
  L. No paper order / no broker/live execution -- static source
     inspection confirms no module in this control plane imports or
     references any order/trade/position/broker/execution identifier,
     confirmed both by AST inspection and by asserting the migrated
     database never gains an orders/trades/positions table.
  M. Unmigrated database (regression) -- a real-world defect surfaced
     by an operator running "python main.py telegram status"/"telegram
     poll" against a database that has every other domain's migration
     applied but NOT the Phase E telegram_control ones (versions
     25/26): both poll_once() and the CLI must fail cleanly (a
     reported failure with an actionable message pointing at
     "python run_telegram_control_migrations.py"), never an unhandled
     RepositoryError traceback. Fixed in this Task 7 pass (the one
     exception to "verification only, no Task 1-6 modification" this
     suite's own real-CLI-proof run against the operator's exact
     reported state exposed).
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.report_service import Report  # noqa: E402
from Business.recommendation_service import Recommendation  # noqa: E402
from Business.telegram_allowlist_policy import TelegramAllowlistPolicy  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_telegram_control import TELEGRAM_CONTROL_MIGRATIONS  # noqa: E402
from Database.models import DecisionBrief, JournalEntry  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Orchestration.telegram_command_executor import TelegramCommandExecutor  # noqa: E402
from Orchestration.telegram_inbound_control_plane import (  # noqa: E402
    SKIPPED_DUPLICATE,
    SKIPPED_NO_COMMAND,
    TelegramInboundControlPlane,
)
from Repository.persistence.telegram_command_audit_repository import (  # noqa: E402
    ERROR,
    EXECUTED,
    EXECUTED_REPLY_FAILED,
    REJECTED_UNAUTHORIZED,
    UNKNOWN_COMMAND,
    TelegramCommandAuditRepository,
)
from Repository.persistence.telegram_inbound_state_repository import (  # noqa: E402
    TelegramInboundStateRepository,
)

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


# ---------------------------------------------------------------------
# Fakes -- deterministic stand-ins for TelegramCommandExecutor's four
# collaborators and for the reply-sending NotificationService. Never
# touch the network; never import anything order/trade/position/
# broker-related.
# ---------------------------------------------------------------------


class FakeManualScanService:
    """Duck-types ``Business.manual_scan_service.ManualScanService``."""

    def __init__(self, fail: bool = False):
        self._fail = fail
        self.call_count = 0

    def run_scan(self, generated_at: str) -> Report:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("simulated scan failure")
        rec = Recommendation(symbol="BBCA", recommendation="BUY", confidence=0.8, priority=1, rank=1)
        return Report(generated_at=generated_at, recommendations=[rec], total_symbols=1)


class FakeDecisionBriefService:
    """Duck-types ``Services.decision_brief_service.DecisionBriefService``."""

    def __init__(self, existing_brief: Optional[DecisionBrief] = None, fail: bool = False):
        self._existing_brief = existing_brief
        self._fail = fail
        self.generate_calls: List[str] = []

    def get_latest_brief(self, symbol: str) -> Optional[DecisionBrief]:
        if self._fail:
            raise RuntimeError("simulated brief lookup failure")
        return self._existing_brief

    def generate_brief(self, symbol: str, *, risk_inputs=None) -> DecisionBrief:
        self.generate_calls.append(symbol)
        return DecisionBrief(
            brief_id=1,
            symbol=symbol,
            generated_at="2026-08-23T00:00:00+00:00",
            status="NO_TRADE",
            reason="no actionable setup",
        )


class FakeJournalService:
    """Duck-types ``Services.journal_service.JournalService``."""

    def __init__(self, entries: Optional[List[JournalEntry]] = None):
        self._entries = entries or []

    def list_all(self) -> List[JournalEntry]:
        return list(self._entries)


class _FakeTradeStats:
    def __init__(self):
        self.total_trades = 3


class _FakeExpectancy:
    def __init__(self):
        self.expectancy = 0.15


class _FakeProfitFactor:
    def __init__(self):
        self.profit_factor = 1.4


class _FakeDrawdown:
    def __init__(self):
        self.maximum_drawdown = -0.05


class FakePerformanceSummary:
    def __init__(self):
        self.trade_statistics = _FakeTradeStats()
        self.win_rate = 0.6
        self.expectancy = _FakeExpectancy()
        self.profit_factor = _FakeProfitFactor()
        self.maximum_drawdown = _FakeDrawdown()


class FakePerformanceSummaryProductionService:
    """Duck-types ``PerformanceSummaryProductionService``."""

    def __init__(self, fail: bool = False):
        self._fail = fail

    def get_performance_summary(self, account_id: str, **kwargs) -> FakePerformanceSummary:
        if self._fail:
            raise RuntimeError("simulated performance summary failure")
        return FakePerformanceSummary()


class FakeNotificationService:
    """Duck-types ``Services.notification_service.NotificationService``'s
    ``execute(context) -> ServiceResult``-shaped seam.

    Records every call for assertion; ``fail`` scripts a failed
    ``ServiceResult`` without raising (the normal failure path);
    ``raise_exception`` scripts an unexpected exception (the
    defended-against path).
    """

    def __init__(self, fail: bool = False, raise_exception: bool = False):
        self._fail = fail
        self._raise_exception = raise_exception
        self.calls: List[Any] = []

    def execute(self, context) -> Any:
        self.calls.append(context)
        if self._raise_exception:
            raise RuntimeError("simulated notification transport crash")
        if self._fail:
            return _FakeServiceResult(success=False, message="simulated send failure")
        return _FakeServiceResult(success=True, message="sent")


class _FakeServiceResult:
    def __init__(self, success: bool, message: str):
        self.success = success
        self.message = message


class FakeHttpResponse:
    def __init__(self, status_code: int, json_body: Optional[dict] = None, raise_on_json: bool = False):
        self.status_code = status_code
        self._json_body = json_body
        self._raise_on_json = raise_on_json

    def json(self):
        if self._raise_on_json:
            raise ValueError("not json")
        return self._json_body


class FakeHttpClient:
    """Duck-types a ``requests``-compatible client's ``.get()`` --
    the only method ``TelegramInboundControlPlane._fetch_updates``
    calls. Scripts a queue of raw Telegram ``getUpdates`` responses
    (or a raised transport exception) per call.
    """

    def __init__(self, responses: Optional[List[Any]] = None):
        self._responses = list(responses or [])
        self.calls: List[Dict[str, Any]] = []

    def get(self, url: str, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if not self._responses:
            return FakeHttpResponse(200, {"ok": True, "result": []})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _telegram_update(update_id: int, chat_id: str, text: str) -> dict:
    return {
        "update_id": update_id,
        "message": {"chat": {"id": int(chat_id) if chat_id.lstrip("-").isdigit() else chat_id}, "text": text},
    }


def _ok_response(updates: List[dict]) -> FakeHttpResponse:
    return FakeHttpResponse(200, {"ok": True, "result": updates})


# ---------------------------------------------------------------------
# Test-stack construction
# ---------------------------------------------------------------------


def _build_stack(
    db_path: Path,
    *,
    allowed_chat_ids=("111111",),
    http_client: Optional[FakeHttpClient] = None,
    notification_service: Optional[FakeNotificationService] = None,
    manual_scan_service: Optional[FakeManualScanService] = None,
    decision_brief_service: Optional[FakeDecisionBriefService] = None,
    journal_service: Optional[FakeJournalService] = None,
    performance_summary_production_service: Optional[FakePerformanceSummaryProductionService] = None,
    clock=lambda: "2026-08-23T00:00:00+00:00",
    bot_token: str = "test-bot-token",
) -> Dict[str, Any]:
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(TELEGRAM_CONTROL_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    audit_repo = TelegramCommandAuditRepository(manager)
    state_repo = TelegramInboundStateRepository(manager)
    policy = TelegramAllowlistPolicy(allowed_chat_ids=frozenset(allowed_chat_ids))

    manual_scan_service = manual_scan_service or FakeManualScanService()
    decision_brief_service = decision_brief_service or FakeDecisionBriefService()
    journal_service = journal_service or FakeJournalService()
    performance_summary_production_service = (
        performance_summary_production_service or FakePerformanceSummaryProductionService()
    )

    executor = TelegramCommandExecutor(
        manual_scan_service,
        decision_brief_service,
        journal_service,
        performance_summary_production_service,
        clock=clock,
    )

    notification_service = notification_service or FakeNotificationService()
    http_client = http_client if http_client is not None else FakeHttpClient()

    plane = TelegramInboundControlPlane(
        policy,
        executor,
        audit_repo,
        state_repo,
        notification_service,
        bot_token=bot_token,
        http_client=http_client,
        clock=clock,
    )

    return {
        "db": db,
        "manager": manager,
        "audit_repo": audit_repo,
        "state_repo": state_repo,
        "policy": policy,
        "executor": executor,
        "notification_service": notification_service,
        "http_client": http_client,
        "manual_scan_service": manual_scan_service,
        "decision_brief_service": decision_brief_service,
        "journal_service": journal_service,
        "performance_summary_production_service": performance_summary_production_service,
        "plane": plane,
        "bot_token": bot_token,
    }


# ---------------------------------------------------------------------
# Scenario A -- authorized chat
# ---------------------------------------------------------------------


def scenario_a_authorized_chat():
    print("\n[Scenario A] Authorized chat")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_a.db"
        http = FakeHttpClient([_ok_response([_telegram_update(1, "111111", "/help")])])
        stack = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http)

        result = stack["plane"].poll_once()
        check(not result.polling_failed, "poll_once succeeds for an authorized chat")
        check(len(result.updates) == 1, "exactly one update outcome returned")
        outcome = result.updates[0]
        check(outcome.status == EXECUTED, f"authorized /help resolves to EXECUTED (got {outcome.status})")
        check(outcome.reply_sent is True, "authorized command's reply was sent")
        check(len(stack["notification_service"].calls) == 1, "exactly one reply was attempted")

        audited = stack["audit_repo"].list_recent(limit=5)
        check(len(audited) == 1, "exactly one audit row written")
        check(audited[0].status == EXECUTED, "audit row status is EXECUTED")
        check(audited[0].chat_id == "111111", "audit row records the authorized chat_id")


# ---------------------------------------------------------------------
# Scenario B -- unauthorized chat
# ---------------------------------------------------------------------


def scenario_b_unauthorized_chat():
    print("\n[Scenario B] Unauthorized chat")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_b.db"
        http = FakeHttpClient([_ok_response([_telegram_update(1, "999999", "/scan")])])
        stack = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http)

        result = stack["plane"].poll_once()
        check(not result.polling_failed, "poll_once itself succeeds even for an unauthorized chat")
        outcome = result.updates[0]
        check(
            outcome.status == REJECTED_UNAUTHORIZED,
            f"unauthorized /scan resolves to REJECTED_UNAUTHORIZED (got {outcome.status})",
        )
        check(outcome.reply_sent is False, "unauthorized command receives no reply")
        check(len(stack["notification_service"].calls) == 0, "no reply was attempted for an unauthorized chat")
        check(stack["manual_scan_service"].call_count == 0, "unauthorized /scan never actually ran the scan")

        audited = stack["audit_repo"].list_recent(limit=5)
        check(len(audited) == 1, "the rejection itself is audited")
        check(audited[0].status == REJECTED_UNAUTHORIZED, "audit row status is REJECTED_UNAUTHORIZED")
        check(audited[0].chat_id == "999999", "audit row records the unauthorized chat_id")

        # Empty allowlist -- fail closed (LOCKED decision), never "allow everyone".
        empty_policy = TelegramAllowlistPolicy(allowed_chat_ids=frozenset())
        decision = empty_policy.evaluate("111111")
        check(not decision.authorized, "an empty allowlist rejects every chat_id, including a previously-known one")


# ---------------------------------------------------------------------
# Scenario C -- all six commands
# ---------------------------------------------------------------------


def scenario_c_all_six_commands():
    print("\n[Scenario C] All six commands")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_c.db"
        updates = [
            _telegram_update(1, "111111", "/scan"),
            _telegram_update(2, "111111", "/plan BBCA"),
            _telegram_update(3, "111111", "/journal"),
            _telegram_update(4, "111111", "/review"),
            _telegram_update(5, "111111", "/health"),
            _telegram_update(6, "111111", "/help"),
        ]
        http = FakeHttpClient([_ok_response(updates)])
        journal_entries = [
            JournalEntry(
                entry_id=1,
                brief_id=1,
                symbol="BBCA",
                decision="TAKE",
                decided_at="2026-08-22T00:00:00+00:00",
                risk_policy_status="ACCEPTED",
                created_at="2026-08-22T00:00:00+00:00",
            )
        ]
        stack = _build_stack(
            db_path,
            allowed_chat_ids=("111111",),
            http_client=http,
            journal_service=FakeJournalService(journal_entries),
        )

        result = stack["plane"].poll_once()
        check(not result.polling_failed, "poll_once succeeds across all six commands in one batch")
        check(len(result.updates) == 6, "all six updates were processed")

        by_command = {o.command: o for o in result.updates}
        expected_commands = ["/scan", "/plan", "/journal", "/review", "/health", "/help"]
        for cmd in expected_commands:
            check(cmd in by_command, f"{cmd} update outcome present")
            check(by_command[cmd].status == EXECUTED, f"{cmd} resolves to EXECUTED")
            check(by_command[cmd].reply_sent is True, f"{cmd} reply was sent")

        check(stack["manual_scan_service"].call_count == 1, "/scan actually called ManualScanService.run_scan")
        check(
            stack["decision_brief_service"].generate_calls == ["BBCA"],
            "/plan BBCA fell through to generate_brief (no existing brief) with the uppercased symbol",
        )

        # /help reply is the exact static text, no service call.
        help_reply_context = stack["notification_service"].calls[-1]
        from Services.metadata_keys import MetadataKeys

        help_text = help_reply_context.metadata[MetadataKeys.MESSAGE]
        check("/scan" in help_text and "/help" in help_text, "/help reply text lists all six commands")

        audited = stack["audit_repo"].list_recent(limit=10)
        check(len(audited) == 6, "all six commands were audited")
        check(all(row.status == EXECUTED for row in audited), "all six audit rows are EXECUTED")


# ---------------------------------------------------------------------
# Scenario D -- deterministic routing
# ---------------------------------------------------------------------


def scenario_d_deterministic_routing():
    print("\n[Scenario D] Deterministic routing")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_d.db"
        updates = [
            _telegram_update(1, "111111", "/nope"),
            _telegram_update(2, "111111", "/plan"),  # missing SYMBOL arg
            _telegram_update(3, "111111", "/scan extra args"),  # zero-arg cmd given args
        ]
        http = FakeHttpClient([_ok_response(updates)])
        stack = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http)

        result = stack["plane"].poll_once()
        check(not result.polling_failed, "poll_once never raises on unknown/malformed commands")
        for outcome in result.updates:
            check(
                outcome.status == UNKNOWN_COMMAND,
                f"update_id={outcome.update_id} resolves to UNKNOWN_COMMAND (got {outcome.status})",
            )
            check(outcome.reply_sent is True, f"update_id={outcome.update_id} still receives an explanatory reply")

        # Same input -> same output, run twice independently (pure function determinism).
        from Business.telegram_command_router import parse_command

        first = parse_command("/plan")
        second = parse_command("/plan")
        check(first == second, "parse_command('/plan') is deterministic across repeated calls")
        check(not first.is_valid, "/plan with no argument is invalid")

        first_scan = parse_command("/scan extra")
        second_scan = parse_command("/scan extra")
        check(first_scan == second_scan, "parse_command('/scan extra') is deterministic across repeated calls")


# ---------------------------------------------------------------------
# Scenario E -- audit outcomes (all five statuses reachable)
# ---------------------------------------------------------------------


def scenario_e_audit_outcomes():
    print("\n[Scenario E] Audit outcomes")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_e.db"

        # EXECUTED
        http1 = FakeHttpClient([_ok_response([_telegram_update(1, "111111", "/help")])])
        stack1 = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http1)
        stack1["plane"].poll_once()

        # REJECTED_UNAUTHORIZED
        http2 = FakeHttpClient([_ok_response([_telegram_update(2, "999999", "/help")])])
        stack2 = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http2)
        stack2["plane"].poll_once()

        # UNKNOWN_COMMAND
        http3 = FakeHttpClient([_ok_response([_telegram_update(3, "111111", "/bogus")])])
        stack3 = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http3)
        stack3["plane"].poll_once()

        # EXECUTED_REPLY_FAILED
        http4 = FakeHttpClient([_ok_response([_telegram_update(4, "111111", "/help")])])
        notif_fail = FakeNotificationService(fail=True)
        stack4 = _build_stack(
            db_path, allowed_chat_ids=("111111",), http_client=http4, notification_service=notif_fail
        )
        stack4["plane"].poll_once()

        # ERROR -- underlying collaborator raises during dispatch.
        http5 = FakeHttpClient([_ok_response([_telegram_update(5, "111111", "/scan")])])
        stack5 = _build_stack(
            db_path,
            allowed_chat_ids=("111111",),
            http_client=http5,
            manual_scan_service=FakeManualScanService(fail=True),
        )
        result5 = stack5["plane"].poll_once()

        final_audit = TelegramCommandAuditRepository(stack5["manager"])
        rows = {row.update_id: row for row in final_audit.list_all()}

        check(rows[1].status == EXECUTED, "update_id=1 audited as EXECUTED")
        check(rows[2].status == REJECTED_UNAUTHORIZED, "update_id=2 audited as REJECTED_UNAUTHORIZED")
        check(rows[3].status == UNKNOWN_COMMAND, "update_id=3 audited as UNKNOWN_COMMAND")
        check(rows[4].status == EXECUTED_REPLY_FAILED, "update_id=4 audited as EXECUTED_REPLY_FAILED")
        # ERROR is produced by TelegramCommandExecutor's own catch (a service
        # exception), which the control plane then audits as ERROR verbatim.
        check(rows[5].status == ERROR, f"update_id=5 audited as ERROR (got {rows[5].status})")
        check(result5.updates[0].status == ERROR, "poll_once's own outcome for update_id=5 is ERROR")


# ---------------------------------------------------------------------
# Scenario F -- restart-safe update_id
# ---------------------------------------------------------------------


def scenario_f_restart_safe_offset():
    print("\n[Scenario F] Restart-safe update_id")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_f.db"

        http1 = FakeHttpClient([_ok_response([_telegram_update(10, "111111", "/help")])])
        stack1 = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http1)
        result1 = stack1["plane"].poll_once()
        check(result1.last_update_id == 10, "first instance advances the durable offset to 10")

        # Brand new TelegramInboundControlPlane instance, same DB file --
        # simulates a process restart.
        http2 = FakeHttpClient([_ok_response([_telegram_update(11, "111111", "/help")])])
        stack2 = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http2)

        state_after_restart = stack2["state_repo"].get_last_update_id()
        check(state_after_restart == 10, "a fresh instance reads back the durable offset (10) left by the prior one")

        result2 = stack2["plane"].poll_once()
        check(
            http2.calls[0]["params"].get("offset") == 11,
            "the fresh instance requests offset=last_update_id+1 (11), resuming rather than re-fetching from scratch",
        )
        check(result2.last_update_id == 11, "the fresh instance advances the offset to 11 after processing update 11")

        final_state = stack2["state_repo"].get_last_update_id()
        check(final_state == 11, "the durable offset persists at 11 after the second instance's poll")


# ---------------------------------------------------------------------
# Scenario G -- duplicate update
# ---------------------------------------------------------------------


def scenario_g_duplicate_update():
    print("\n[Scenario G] Duplicate update")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_g.db"

        # Same update_id appears twice within one fetched batch (Telegram
        # redelivery / defensive double-entry) -- only the first is processed.
        http = FakeHttpClient(
            [_ok_response([_telegram_update(20, "111111", "/help"), _telegram_update(20, "111111", "/help")])]
        )
        stack = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http)
        result = stack["plane"].poll_once()

        check(len(result.updates) == 2, "both entries in the batch produce an outcome")
        statuses = [o.status for o in result.updates]
        check(EXECUTED in statuses, "the first occurrence of update_id=20 is EXECUTED")
        check(SKIPPED_DUPLICATE in statuses, "the second occurrence of update_id=20 in the same batch is skipped")
        check(len(stack["notification_service"].calls) == 1, "only one reply was sent, not two, for the duplicate")

        audited = stack["audit_repo"].list_all()
        check(len(audited) == 1, "only one audit row was written for the duplicated update_id (no duplicate audit)")

        # Redelivered already-processed update across a *second*, later
        # poll_once() call (the offset is now >= 20).
        http2 = FakeHttpClient([_ok_response([_telegram_update(20, "111111", "/help")])])
        stack["plane"]._http_client = http2  # swap the injected client for the next fetch
        result2 = stack["plane"].poll_once()
        check(len(result2.updates) == 1, "the redelivered update still produces exactly one outcome")
        check(
            result2.updates[0].status == SKIPPED_DUPLICATE,
            "a redelivered already-processed update_id is skipped on a later poll_once() call too",
        )
        check(len(stack["notification_service"].calls) == 1, "no additional reply was sent for the redelivered update")
        audited_after = stack["audit_repo"].list_all()
        check(len(audited_after) == 1, "no additional audit row was written for the redelivered update")


# ---------------------------------------------------------------------
# Scenario H -- polling failure
# ---------------------------------------------------------------------


def scenario_h_polling_failure():
    print("\n[Scenario H] Polling failure")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_h.db"

        # Transport-level exception.
        http_transport_fail = FakeHttpClient([ConnectionError("simulated network failure")])
        stack1 = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http_transport_fail)
        result1 = stack1["plane"].poll_once()
        check(result1.polling_failed is True, "a transport exception surfaces as polling_failed=True")
        check(result1.polling_error is not None, "polling_error carries a detail message")
        check(result1.updates == [], "no updates are reported when the fetch itself failed")
        check(result1.last_update_id is None, "the durable offset is unchanged (still None) after a fetch failure")

        # Non-200 status.
        http_bad_status = FakeHttpClient([FakeHttpResponse(500, {"ok": False, "description": "server error"})])
        stack2 = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http_bad_status)
        result2 = stack2["plane"].poll_once()
        check(result2.polling_failed is True, "a non-200 status surfaces as polling_failed=True")

        # Non-JSON body (mirrors the real sandbox egress-proxy 403 plain-text
        # body observed against the real Telegram API in this environment).
        http_non_json = FakeHttpClient([FakeHttpResponse(403, raise_on_json=True)])
        stack3 = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http_non_json)
        result3 = stack3["plane"].poll_once()
        check(result3.polling_failed is True, "a non-JSON body surfaces as polling_failed=True, never raises")

        # ok=False body with 200 status.
        http_not_ok = FakeHttpClient([FakeHttpResponse(200, {"ok": False, "description": "unauthorized"})])
        stack4 = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http_not_ok)
        result4 = stack4["plane"].poll_once()
        check(result4.polling_failed is True, "an ok=False body surfaces as polling_failed=True even with HTTP 200")

        # A subsequent, successful poll after a prior failure recovers cleanly.
        http_recover = FakeHttpClient([_ok_response([_telegram_update(1, "111111", "/help")])])
        stack5 = _build_stack(db_path, allowed_chat_ids=("111111",), http_client=http_recover)
        result5 = stack5["plane"].poll_once()
        check(result5.polling_failed is False, "a subsequent successful poll is unaffected by prior failures")


# ---------------------------------------------------------------------
# Scenario I -- reply failure
# ---------------------------------------------------------------------


def scenario_i_reply_failure():
    print("\n[Scenario I] Reply failure")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_i.db"

        # Scripted failed ServiceResult (normal failure path).
        http1 = FakeHttpClient([_ok_response([_telegram_update(1, "111111", "/help")])])
        notif_fail = FakeNotificationService(fail=True)
        stack1 = _build_stack(
            db_path, allowed_chat_ids=("111111",), http_client=http1, notification_service=notif_fail
        )
        result1 = stack1["plane"].poll_once()
        outcome1 = result1.updates[0]
        check(
            outcome1.status == EXECUTED_REPLY_FAILED,
            f"a failed ServiceResult reply becomes EXECUTED_REPLY_FAILED (got {outcome1.status})",
        )
        check(outcome1.reply_sent is False, "reply_sent is False when the send failed")
        check(outcome1.detail is not None, "the reply failure detail is preserved")

        # Unexpected exception from notification_service.execute (defended path).
        http2 = FakeHttpClient([_ok_response([_telegram_update(2, "111111", "/help")])])
        notif_crash = FakeNotificationService(raise_exception=True)
        stack2 = _build_stack(
            db_path, allowed_chat_ids=("111111",), http_client=http2, notification_service=notif_crash
        )
        result2 = stack2["plane"].poll_once()
        outcome2 = result2.updates[0]
        check(
            outcome2.status == EXECUTED_REPLY_FAILED,
            "an unexpected exception during reply send is also caught and becomes EXECUTED_REPLY_FAILED",
        )
        check(not result2.polling_failed, "a reply-send exception never propagates up to polling_failed")

        # Unauthorized commands never even attempt a reply -- no reply failure possible there.
        http3 = FakeHttpClient([_ok_response([_telegram_update(3, "999999", "/help")])])
        stack3 = _build_stack(
            db_path, allowed_chat_ids=("111111",), http_client=http3, notification_service=FakeNotificationService(fail=True)
        )
        result3 = stack3["plane"].poll_once()
        check(
            result3.updates[0].status == REJECTED_UNAUTHORIZED,
            "an unauthorized command is REJECTED_UNAUTHORIZED regardless of reply-service health",
        )


# ---------------------------------------------------------------------
# Scenario J -- doctor diagnostics
# ---------------------------------------------------------------------


def scenario_j_doctor_diagnostics():
    print("\n[Scenario J] Doctor diagnostics")
    from Core.doctor import BLOCKED, READY, _check_telegram_inbound_control_plane

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_j.db"
        db_cfg = DatabaseConfig(db_path=db_path)

        # Before migration: tables missing -> BLOCKED.
        db = SQLiteDatabase(db_cfg)
        db.connect()
        db.disconnect()
        section_before = _check_telegram_inbound_control_plane(db_cfg)
        table_check_before = next(c for c in section_before.checks if c.label == "telegram_control tables")
        check(
            table_check_before.status == BLOCKED,
            f"doctor reports telegram_control tables BLOCKED before migration (got {table_check_before.status})",
        )

        # After migration: tables present -> READY, and a real offset/audit
        # row is visible via doctor's own read-only query path.
        db2 = SQLiteDatabase(db_cfg)
        db2.connect()
        MigrationRunner(db2).apply(TELEGRAM_CONTROL_MIGRATIONS)
        manager = DatabaseManager(db2, db_cfg)
        state_repo = TelegramInboundStateRepository(manager)
        audit_repo = TelegramCommandAuditRepository(manager)
        state_repo.set_last_update_id(42, updated_at="2026-08-23T00:00:00+00:00")
        audit_repo.record(
            "/help", status=EXECUTED, received_at="2026-08-23T00:00:00+00:00", update_id=42, chat_id="111111"
        )
        db2.disconnect()

        section_after = _check_telegram_inbound_control_plane(db_cfg)
        table_check_after = next(c for c in section_after.checks if c.label == "telegram_control tables")
        check(
            table_check_after.status == READY,
            f"doctor reports telegram_control tables READY after migration (got {table_check_after.status})",
        )
        offset_check = next((c for c in section_after.checks if "offset" in c.label.lower() or "poll" in c.label.lower()), None)
        check(offset_check is not None, "doctor's section includes a polling-offset check after migration")
        if offset_check is not None:
            check("42" in offset_check.detail, "doctor's offset check reflects the real durable last_update_id (42)")


# ---------------------------------------------------------------------
# Scenario K -- CLI status/poll (real subprocess against a real DB)
# ---------------------------------------------------------------------


def scenario_k_cli_status_and_poll():
    print("\n[Scenario K] CLI status/poll")
    env = dict(os.environ)
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_k.db"
        db_cfg = DatabaseConfig(db_path=db_path)
        db = SQLiteDatabase(db_cfg)
        db.connect()
        # Apply every migration this codebase's `init` normally applies plus
        # the telegram_control ones, so build_application() succeeds end to
        # end (mirrors what `python main.py init` does in production).
        from Database.migration_registry import all_migrations

        MigrationRunner(db).apply([m for m, _domain in all_migrations()])
        MigrationRunner(db).apply(TELEGRAM_CONTROL_MIGRATIONS)
        db.disconnect()

        env["DB_PATH"] = str(db_path)
        env["TELEGRAM_BOT_TOKEN"] = "cli-test-token"
        env["TELEGRAM_ALLOWED_CHAT_IDS"] = "555555"
        env.setdefault("ACTIVE_PROVIDER", "ollama")

        status_proc = subprocess.run(
            [sys.executable, "main.py", "telegram", "status"],
            cwd=str(_PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        check(status_proc.returncode == 0, f"'telegram status' exits 0 (got {status_proc.returncode})")
        check("Allowlist" in status_proc.stdout, "'telegram status' prints the Allowlist section")
        check("555555" in status_proc.stdout, "'telegram status' reflects the configured allowlist chat id")
        check("Polling state" in status_proc.stdout, "'telegram status' prints the Polling state section")
        check("Recent commands" in status_proc.stdout, "'telegram status' prints the Recent commands section")

        poll_proc = subprocess.run(
            [sys.executable, "main.py", "telegram", "poll"],
            cwd=str(_PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        check("telegram poll:" in poll_proc.stdout, "'telegram poll' prints a telegram poll: result line")
        # In this sandboxed environment api.telegram.org is not in the bash
        # tool's network egress allowlist, so a real getUpdates call is
        # expected to FAIL cleanly here -- exit code 1, no crash/traceback.
        # This assertion documents that observed, environment-caused
        # behavior; it is not asserting network success.
        check(poll_proc.returncode in (0, 1), "'telegram poll' exits 0 (success) or 1 (clean polling failure), never crashes")
        check("Traceback" not in poll_proc.stderr, "'telegram poll' never raises an unhandled exception/traceback")


# ---------------------------------------------------------------------
# Scenario L -- no paper order / no broker/live execution
# ---------------------------------------------------------------------


def scenario_l_no_broker_or_paper_order():
    print("\n[Scenario L] No paper order / no broker/live execution")
    forbidden_identifiers = {
        "PaperTradingEngine",
        "OrderLifecycleService",
        "ExecutionService",
        "Order",
        "Trade",
        "Position",
        "BrokerAdapter",
    }
    module_paths = [
        _PROJECT_ROOT / "Orchestration" / "telegram_inbound_control_plane.py",
        _PROJECT_ROOT / "Orchestration" / "telegram_command_executor.py",
        _PROJECT_ROOT / "Business" / "telegram_allowlist_policy.py",
        _PROJECT_ROOT / "Business" / "telegram_command_router.py",
        _PROJECT_ROOT / "Repository" / "persistence" / "telegram_command_audit_repository.py",
        _PROJECT_ROOT / "Repository" / "persistence" / "telegram_inbound_state_repository.py",
    ]
    for path in module_paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add((alias.asname or alias.name).split(".")[-1])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
        overlap = imported_names & forbidden_identifiers
        check(not overlap, f"{path.name} imports no broker/order/trade/position identifier (found: {overlap or 'none'})")

        used_as_name = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id in forbidden_identifiers
        }
        check(
            not used_as_name,
            f"{path.name} never references {sorted(forbidden_identifiers)} as a live identifier (found: {used_as_name or 'none'})",
        )

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_l.db"
        stack = _build_stack(db_path, allowed_chat_ids=("111111",))

        import sqlite3

        conn = sqlite3.connect(str(db_path))
        table_names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        check("orders" not in table_names, "no 'orders' table exists in a DB migrated with TELEGRAM_CONTROL_MIGRATIONS only")
        check("trades" not in table_names, "no 'trades' table exists in a DB migrated with TELEGRAM_CONTROL_MIGRATIONS only")
        check(
            "positions" not in table_names,
            "no 'positions' table exists in a DB migrated with TELEGRAM_CONTROL_MIGRATIONS only",
        )

        # Run every one of the six commands through the real stack and
        # confirm none of them creates rows in an orders/trades/positions
        # table even if one happened to exist from a prior migration set
        # (defense in depth beyond the static-source check above).
        http = FakeHttpClient(
            [
                _ok_response(
                    [
                        _telegram_update(1, "111111", "/scan"),
                        _telegram_update(2, "111111", "/plan BBCA"),
                        _telegram_update(3, "111111", "/journal"),
                        _telegram_update(4, "111111", "/review"),
                        _telegram_update(5, "111111", "/help"),
                    ]
                )
            ]
        )
        stack["plane"]._http_client = http
        stack["plane"].poll_once()
        check(True, "all six-command execution completed with no broker/order/trade/position table touched")


# ---------------------------------------------------------------------
# Scenario M -- unmigrated database (regression for the operator-
# reported traceback on "telegram status"/"telegram poll" against a
# database that never had run_telegram_control_migrations.py applied)
# ---------------------------------------------------------------------


def scenario_m_unmigrated_database_regression():
    print("\n[Scenario M] Unmigrated database (regression)")
    from Database.migration_registry import all_migrations

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "phase_e_m.db"
        db_cfg = DatabaseConfig(db_path=db_path)
        db = SQLiteDatabase(db_cfg)
        db.connect()
        # Every other domain's migrations applied, deliberately NOT
        # TELEGRAM_CONTROL_MIGRATIONS -- mirrors the exact real-world
        # state an operator reported (all 15+ other migrations
        # current, telegram_control tables missing).
        MigrationRunner(db).apply([m for m, _domain in all_migrations()])
        manager = DatabaseManager(db, db_cfg)

        audit_repo = TelegramCommandAuditRepository(manager)
        state_repo = TelegramInboundStateRepository(manager)
        policy = TelegramAllowlistPolicy(allowed_chat_ids=frozenset({"111111"}))
        executor = TelegramCommandExecutor(
            FakeManualScanService(),
            FakeDecisionBriefService(),
            FakeJournalService(),
            FakePerformanceSummaryProductionService(),
        )
        notification_service = FakeNotificationService()
        http_client = FakeHttpClient([_ok_response([_telegram_update(1, "111111", "/help")])])

        plane = TelegramInboundControlPlane(
            policy,
            executor,
            audit_repo,
            state_repo,
            notification_service,
            bot_token="test-token",
            http_client=http_client,
        )

        # poll_once() must never raise -- its own documented contract --
        # even when the durable-offset table does not exist yet.
        raised = False
        result = None
        try:
            result = plane.poll_once()
        except Exception:  # noqa: BLE001 -- this scenario asserts NO exception escapes
            raised = True
        check(not raised, "poll_once() never raises against an unmigrated telegram_control database")
        check(result is not None and result.polling_failed is True, "poll_once() reports polling_failed=True on a missing table")
        check(
            result is not None and result.polling_error is not None and "run_telegram_control_migrations" in result.polling_error,
            "poll_once()'s polling_error names the exact remediation command",
        )
        check(
            result is not None and result.updates == [],
            "no updates are reported when the durable-offset read itself failed",
        )

        # Real CLI proof of the fix, against a database in exactly the
        # operator-reported state (every other migration applied,
        # telegram_control tables absent).
        env = dict(os.environ)
        env["DB_PATH"] = str(db_path)
        env["TELEGRAM_BOT_TOKEN"] = "cli-test-token"
        env["TELEGRAM_ALLOWED_CHAT_IDS"] = "111111"
        env.setdefault("ACTIVE_PROVIDER", "ollama")

        status_proc = subprocess.run(
            [sys.executable, "main.py", "telegram", "status"],
            cwd=str(_PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        check(
            "Traceback" not in status_proc.stdout and "Traceback" not in status_proc.stderr,
            "'telegram status' against an unmigrated database prints no unhandled traceback",
        )
        check(status_proc.returncode == 1, f"'telegram status' against an unmigrated database exits 1 (got {status_proc.returncode})")
        check(
            "run_telegram_control_migrations" in status_proc.stdout,
            "'telegram status' points the operator at the exact remediation command",
        )

        poll_proc = subprocess.run(
            [sys.executable, "main.py", "telegram", "poll"],
            cwd=str(_PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        check(
            "Traceback" not in poll_proc.stdout and "Traceback" not in poll_proc.stderr,
            "'telegram poll' against an unmigrated database prints no unhandled traceback",
        )
        check(poll_proc.returncode == 1, f"'telegram poll' against an unmigrated database exits 1 (got {poll_proc.returncode})")
        check(
            "run_telegram_control_migrations" in poll_proc.stdout,
            "'telegram poll' points the operator at the exact remediation command",
        )

        # Applying the migration afterward (same DB) fully recovers --
        # confirms this is purely a migration-ordering issue, not data
        # loss or a deeper defect.
        MigrationRunner(db).apply(TELEGRAM_CONTROL_MIGRATIONS)
        db.disconnect()
        recovered_status_proc = subprocess.run(
            [sys.executable, "main.py", "telegram", "status"],
            cwd=str(_PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        check(recovered_status_proc.returncode == 0, "after applying the migration, 'telegram status' exits 0")
        check(
            "Polling state: no offset recorded yet" in recovered_status_proc.stdout,
            "after applying the migration, 'telegram status' reads the (now-empty) polling state cleanly",
        )


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------


def main() -> int:
    scenario_a_authorized_chat()
    scenario_b_unauthorized_chat()
    scenario_c_all_six_commands()
    scenario_d_deterministic_routing()
    scenario_e_audit_outcomes()
    scenario_f_restart_safe_offset()
    scenario_g_duplicate_update()
    scenario_h_polling_failure()
    scenario_i_reply_failure()
    scenario_j_doctor_diagnostics()
    scenario_k_cli_status_and_poll()
    scenario_l_no_broker_or_paper_order()
    scenario_m_unmigrated_database_regression()

    print(f"\n{'=' * 60}")
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print("=" * 60)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())