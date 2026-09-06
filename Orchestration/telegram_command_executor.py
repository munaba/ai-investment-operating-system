"""telegram_command_executor -- Phase E (Telegram Control Plane,
foundational task).

EXECUTION ONLY. Takes one already-parsed ``Business.
telegram_command_router.ParsedCommand`` (Task 3) and dispatches it to
exactly the existing, already-LOCKED ``ApplicationGraph`` services
listed below -- never a new strategy engine, never a new risk engine,
never a paper order, never broker/live execution, and never a network
call of its own. This module never runs ``main.py``, never touches
``Core.composition_root``, never touches ``Core.doctor`` internals
(it only calls doctor's own public, already-read-only
``run_doctor()``/``format_report()`` entry points, unmodified), and
never decides Telegram authorization -- that is
``Business.telegram_allowlist_policy``'s job (Task 2), applied by a
future router *before* this executor is ever called.

Command -> collaborator mapping (LOCKED for this task):

* ``/scan``    -> ``ManualScanService.run_scan(generated_at)``.
* ``/plan``    -> ``DecisionBriefService``: ``get_latest_brief(symbol)``
  first (pure retrieval); only when that returns ``None`` does this
  fall back to ``generate_brief(symbol, risk_inputs=None)``. Risk
  parameters are never parsed out of Telegram text and never
  fabricated here -- ``risk_inputs`` is always literally ``None``,
  exactly like every other caller in this codebase that has no real
  risk parameters to supply (mirrors ``DecisionBriefService``'s own
  documented "never invented" contract). A brief generated this way
  can only ever reach ``SUCCESS`` in the narrow case the underlying
  service already handles without risk inputs -- for every
  actionable-but-unpriced snapshot it resolves to
  ``POLICY_BLOCKED``, exactly as ``DecisionBriefService.generate_brief``
  already documents.
* ``/journal`` -> ``JournalService.list_all()`` -- read-only history,
  never ``record_decision``/``record_outcome``.
* ``/review``  -> ``PerformanceSummaryProductionService.
  get_performance_summary(account_id)`` -- read-only, scoped to the
  single configured ``account_id`` (defaults to
  ``Core.bootstrap.DEFAULT_PAPER_ACCOUNT_ID``, the same default every
  other one-shot CLI report path already uses).
* ``/health``  -> ``Core.doctor.run_doctor()`` +
  ``Core.doctor.format_report()`` -- the exact same read-only
  diagnostic path ``python main.py doctor`` already uses. Imported
  lazily inside the handler (not at module import time) so this
  module's own import graph stays minimal and matches the
  lazy-import convention ``Core.doctor.run_doctor`` itself already
  uses for ``Core.self_diagnostic``.
* ``/help``    -> a static, deterministic string constant. No
  service call at all.

Collaborators are accepted via constructor injection as plain
duck-typed objects (see the ``Protocol`` definitions below) rather
than by importing the concrete service classes -- this executor only
ever calls the exact public methods named above, so it depends on
that narrow shape, not on ``Services.decision_brief_service``'s or
``Business.manual_scan_service``'s full implementation. A caller
wires the real ``ApplicationGraph.manual_scan_service`` /
``.decision_brief_service`` / ``.journal_service`` /
``.performance_summary_production_service`` singletons into this
constructor unchanged.

Result contract: ``execute()`` never raises. Every outcome -- a
successful dispatch, an unknown/malformed ``ParsedCommand``, or an
underlying service exception -- becomes an ``ExecutionResult`` whose
``outcome`` field is always one of the exact outcome constants
``Repository.persistence.telegram_command_audit_repository`` already
defines (imported from there, never redefined here), so a future
caller can pass this result straight into
``TelegramCommandAuditRepository.record()`` without any translation.
This module does not itself call that repository -- Task 4's own
constraint is that auditing remains the future control plane's
responsibility; only the vocabulary is shared.

``REJECTED_UNAUTHORIZED`` and ``EXECUTED_REPLY_FAILED`` are
deliberately never produced by this module: authorization happens
before this executor is invoked (Task 2's policy), and a reply-send
failure can only be known after this executor's ``reply_text`` has
been handed to whatever actually calls the Telegram API (out of
scope here -- no network access in this module at all).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional, Protocol

from Business.performance_summary_service import PerformanceSummary
from Business.report_service import Report
from Business.telegram_command_router import INVALID_COMMAND as PARSE_INVALID_COMMAND
from Business.telegram_command_router import PARSED as PARSE_PARSED
from Business.telegram_command_router import ParsedCommand
from Business.telegram_command_router import UNKNOWN_COMMAND as PARSE_UNKNOWN_COMMAND
from Core.bootstrap import DEFAULT_PAPER_ACCOUNT_ID
from Database.models import DecisionBrief, JournalEntry
from Repository.persistence.telegram_command_audit_repository import (
    ERROR,
    EXECUTED,
    UNKNOWN_COMMAND,
)

#: Static, deterministic ``/help`` text -- no service call involved.
HELP_TEXT: str = (
    "Available commands:\n"
    "/scan - run the manual watchlist scan and list recommendations\n"
    "/plan SYMBOL - show (or generate) the latest decision brief for SYMBOL\n"
    "/journal - list your recorded journal entries\n"
    "/review - show the current performance summary\n"
    "/health - run the system diagnostic check\n"
    "/help - show this message"
)

#: Most recent journal entries shown in a ``/journal`` reply -- a
#: fixed, deterministic cap so the reply text never grows unbounded.
_JOURNAL_REPLY_LIMIT: int = 10


class _ManualScanServiceProtocol(Protocol):
    def run_scan(self, generated_at: str) -> Report: ...


class _DecisionBriefServiceProtocol(Protocol):
    def generate_brief(self, symbol: str, *, risk_inputs=None) -> DecisionBrief: ...

    def get_latest_brief(self, symbol: str) -> Optional[DecisionBrief]: ...


class _JournalServiceProtocol(Protocol):
    def list_all(self) -> List[JournalEntry]: ...


class _PerformanceSummaryProductionServiceProtocol(Protocol):
    def get_performance_summary(
        self,
        account_id: str,
        *,
        start_timestamp: Optional[str] = None,
        end_timestamp: Optional[str] = None,
    ) -> PerformanceSummary: ...


def _default_clock() -> str:
    """Real UTC-now ISO-8601 timestamp -- the executor's sole source
    of non-determinism, isolated to this one function so it can be
    overridden by ``TelegramCommandExecutor``'s injectable ``clock``
    for deterministic tests. Mirrors every other caller in this
    codebase that supplies ``ManualScanService.run_scan()``'s required
    ``generated_at`` from its own top-level clock read rather than
    letting that LOCKED service generate one itself.
    """
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ExecutionResult:
    """The outcome of executing one previously parsed Telegram command.

    Never constructed for anything other than a fully-resolved
    outcome -- ``execute()`` always returns one of these, never
    raises.

    Attributes:
        command: The normalized command word from the originating
            ``ParsedCommand`` (e.g. ``"/plan"``), preserved verbatim
            for audit even when execution failed.
        success: ``True`` iff a supported command actually ran and
            produced its reply without a service exception --
            equivalent to ``outcome == EXECUTED``.
        reply_text: The exact text to send back to the chat. Always
            populated, success or failure -- never empty.
        outcome: One of the outcome constants imported from
            ``Repository.persistence.telegram_command_audit_repository``
            (``EXECUTED`` / ``UNKNOWN_COMMAND`` / ``ERROR`` in
            practice for this module -- see module docstring for why
            ``REJECTED_UNAUTHORIZED``/``EXECUTED_REPLY_FAILED`` never
            appear here), suitable to pass straight into
            ``TelegramCommandAuditRepository.record()``.
        chat_id: Pass-through of the ``chat_id`` the caller supplied
            to ``execute()``, unchanged -- this executor does not
            interpret or validate it.
        update_id: Pass-through of the ``update_id`` the caller
            supplied to ``execute()``, unchanged.
        raw_text: Pass-through of ``parsed.raw_text``, unchanged --
            the original inbound message text, for audit fidelity.
        detail: Optional free-text detail (e.g. the exact exception
            message on ``ERROR``), or ``None``.
    """

    command: str
    success: bool
    reply_text: str
    outcome: str
    chat_id: Optional[str]
    update_id: Optional[int]
    raw_text: str
    detail: Optional[str] = None


class TelegramCommandExecutor:
    """Dispatches one ``ParsedCommand`` to the real, already-existing
    ``ApplicationGraph`` services.

    Constructor injection only, mirroring every other
    service/orchestrator in this codebase. Holds no reference to any
    broker, execution, or paper-order component -- there is no import
    of any of those here, enforcing the read-only/no-execution
    boundary structurally, not just by convention. Owns no polling
    state (``Repository.persistence.telegram_inbound_state_repository``
    is never touched here) and writes no audit record itself
    (``Repository.persistence.telegram_command_audit_repository`` is
    never called here) -- both remain the future control plane's job.
    """

    def __init__(
        self,
        manual_scan_service: _ManualScanServiceProtocol,
        decision_brief_service: _DecisionBriefServiceProtocol,
        journal_service: _JournalServiceProtocol,
        performance_summary_production_service: _PerformanceSummaryProductionServiceProtocol,
        *,
        account_id: str = DEFAULT_PAPER_ACCOUNT_ID,
        clock: Callable[[], str] = _default_clock,
    ) -> None:
        """Store the exactly four collaborators this executor dispatches to.

        Args:
            manual_scan_service: The real
                ``ApplicationGraph.manual_scan_service`` singleton (or
                any object with the same ``run_scan(generated_at)``
                shape, e.g. a test double). Stored by identity.
            decision_brief_service: The real
                ``ApplicationGraph.decision_brief_service`` singleton
                (or a compatible test double). Stored by identity.
            journal_service: The real
                ``ApplicationGraph.journal_service`` singleton (or a
                compatible test double). Stored by identity.
            performance_summary_production_service: The real
                ``ApplicationGraph.performance_summary_production_service``
                singleton (or a compatible test double). Stored by
                identity.
            account_id: The single account ``/review`` is scoped to.
                Defaults to ``Core.bootstrap.DEFAULT_PAPER_ACCOUNT_ID``
                -- the same default every other one-shot CLI report
                path already uses. Never accepted from Telegram text.
            clock: Injectable ISO-8601 UTC-now supplier, used only for
                ``/scan``'s required ``generated_at``. Defaults to a
                real clock read; tests may inject a fixed string
                supplier for determinism.
        """
        self._manual_scan_service = manual_scan_service
        self._decision_brief_service = decision_brief_service
        self._journal_service = journal_service
        self._performance_summary_production_service = performance_summary_production_service
        self._account_id = account_id
        self._clock = clock

    def execute(
        self,
        parsed: ParsedCommand,
        *,
        chat_id: Optional[str] = None,
        update_id: Optional[int] = None,
    ) -> ExecutionResult:
        """Execute ``parsed`` and return a typed, audit-shaped result.

        Never raises: any exception any underlying collaborator
        raises is caught here and turned into an ``ERROR`` outcome
        with the exception's message preserved in ``detail`` --
        exactly the "service exceptions must become an explicit
        execution error result" contract this module exists to
        satisfy.

        Args:
            parsed: The already-parsed command, from
                ``Business.telegram_command_router.parse_command``.
            chat_id: The chat this command came from, passed straight
                through onto the returned ``ExecutionResult`` for the
                caller's own audit/reply use. Not interpreted here.
            update_id: The Telegram ``update_id`` this command came
                from, passed straight through the same way.

        Returns:
            An ``ExecutionResult`` whose ``outcome`` is always one of
            ``EXECUTED`` / ``UNKNOWN_COMMAND`` / ``ERROR``.
        """
        if parsed.action != PARSE_PARSED:
            # Covers both the router's PARSE_UNKNOWN_COMMAND (a
            # genuinely unrecognized command word) and its own
            # PARSE_INVALID_COMMAND (a recognized command word with
            # the wrong arguments, e.g. a malformed "/plan"). Neither
            # ran anything, and the audit vocabulary this module
            # shares has no separate "malformed" bucket -- both map
            # to the same UNKNOWN_COMMAND audit outcome, distinguished
            # for the person only by `reply_text` (`parsed.reason`).
            assert parsed.action in (PARSE_UNKNOWN_COMMAND, PARSE_INVALID_COMMAND)
            return ExecutionResult(
                command=parsed.command,
                success=False,
                reply_text=parsed.reason or "Unrecognized or malformed command.",
                outcome=UNKNOWN_COMMAND,
                chat_id=chat_id,
                update_id=update_id,
                raw_text=parsed.raw_text,
                detail=parsed.reason,
            )

        try:
            reply_text = self._dispatch(parsed)
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: any
            # collaborator failure must become an explicit ERROR result,
            # never an unhandled exception escaping this executor.
            return ExecutionResult(
                command=parsed.command,
                success=False,
                reply_text=(
                    f"Something went wrong running {parsed.command}. "
                    "Please try again later."
                ),
                outcome=ERROR,
                chat_id=chat_id,
                update_id=update_id,
                raw_text=parsed.raw_text,
                detail=str(exc),
            )

        return ExecutionResult(
            command=parsed.command,
            success=True,
            reply_text=reply_text,
            outcome=EXECUTED,
            chat_id=chat_id,
            update_id=update_id,
            raw_text=parsed.raw_text,
            detail=None,
        )

    def _dispatch(self, parsed: ParsedCommand) -> str:
        """Route one successfully-parsed command to its handler and
        return the reply text. The only place this class's ``if``
        chain over ``parsed.command`` exists.
        """
        if parsed.command == "/scan":
            return self._handle_scan()
        if parsed.command == "/plan":
            assert parsed.symbol is not None  # PARSED /plan always has a symbol
            return self._handle_plan(parsed.symbol)
        if parsed.command == "/journal":
            return self._handle_journal()
        if parsed.command == "/review":
            return self._handle_review()
        if parsed.command == "/health":
            return self._handle_health()
        if parsed.command == "/help":
            return HELP_TEXT
        # Unreachable: SUPPORTED_COMMANDS in telegram_command_router is
        # exactly these six, and parsed.action == PARSED implies
        # parsed.command is one of them.
        raise AssertionError(f"unhandled supported command: {parsed.command!r}")

    def _handle_scan(self) -> str:
        report = self._manual_scan_service.run_scan(generated_at=self._clock())
        if not report.recommendations:
            return f"Scan complete ({report.generated_at}): no recommendations."
        lines = [f"Scan complete ({report.generated_at}), {report.total_symbols} symbol(s):"]
        for rec in report.recommendations:
            lines.append(
                f"  #{rec.rank} {rec.symbol}: {rec.recommendation} "
                f"(confidence={rec.confidence}, priority={rec.priority})"
            )
        return "\n".join(lines)

    def _handle_plan(self, symbol: str) -> str:
        brief = self._decision_brief_service.get_latest_brief(symbol)
        if brief is None:
            brief = self._decision_brief_service.generate_brief(symbol, risk_inputs=None)
        lines = [f"Plan for {brief.symbol} ({brief.generated_at}): {brief.status}"]
        if brief.status == "SUCCESS":
            lines.append(
                f"  entry={brief.entry_price} stop={brief.stop_loss_price} "
                f"target={brief.take_profit_price} size={brief.position_size} "
                f"r:r={brief.risk_reward_ratio}"
            )
        elif brief.reason:
            lines.append(f"  {brief.reason}")
        return "\n".join(lines)

    def _handle_journal(self) -> str:
        entries = self._journal_service.list_all()
        if not entries:
            return "Journal is empty."
        recent = list(reversed(entries[-_JOURNAL_REPLY_LIMIT:]))
        lines = [f"Journal ({len(entries)} total, showing {len(recent)} most recent):"]
        for entry in recent:
            outcome = f", outcome={entry.outcome_status}" if entry.outcome_status else ""
            lines.append(
                f"  #{entry.entry_id} {entry.symbol} {entry.decision} "
                f"({entry.decided_at}){outcome}"
            )
        return "\n".join(lines)

    def _handle_review(self) -> str:
        summary = self._performance_summary_production_service.get_performance_summary(
            self._account_id
        )
        return (
            f"Performance summary for account {self._account_id}:\n"
            f"  trades={summary.trade_statistics.total_trades} "
            f"win_rate={summary.win_rate:.2%} "
            f"expectancy={summary.expectancy.expectancy:.4f} "
            f"profit_factor={summary.profit_factor.profit_factor} "
            f"max_drawdown={summary.maximum_drawdown.maximum_drawdown}"
        )

    def _handle_health(self) -> str:
        from Core.doctor import format_report, run_doctor

        report = run_doctor()
        return format_report(report)