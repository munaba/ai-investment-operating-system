"""``SustainedUseReportService`` -- Phase H Task 3 ("Sustained-Use
Review Report", reporting/formatting layer only).

Turns an already-computed
``Services.sustained_use_review_service.SustainedUseReviewResult``
(Phase H Task 2, produced by
``SustainedUseReviewService.generate_review()``) into a durable,
human-readable evidence report. This module is a pure adapter,
mirroring ``Business.report_service.ReportService``'s "pure adapter,
no IO" pattern: it reads fields off an already-frozen result and
formats them, nothing more.

This service explicitly does NOT:

    * recalculate, re-derive, or second-guess any evidence value --
      every number/string/tuple already present on
      ``SustainedUseReviewResult`` (and the ``WindowMetadata``/
      ``AvailabilityEvidence``/``DataFreshnessEvidence``/
      ``AlertUsefulnessEvidence``/``PlanJournalAdherenceEvidence``/
      ``PaperReconciliationEvidence``/``DrawdownProcessEvidence``/
      ``StrategyRegimeEvidence``/``EvidenceLimitation`` sections it
      carries) is copied through verbatim;
    * call any repository, service, or engine itself -- it is
      constructed with **no** collaborator at all (mirrors
      ``ReportService()``'s own no-dependency constructor) and reads
      only the ``SustainedUseReviewResult`` object handed to
      ``build_report()``;
    * generate its own timestamp -- ``SustainedUseReviewReport.
      generated_at`` is copied verbatim from
      ``SustainedUseReviewResult.generated_at`` (the moment the
      *review* was assembled), never ``datetime.now()`` re-stamped at
      report-formatting time, so that formatting the same
      already-computed result twice (e.g. across a process restart)
      produces byte-identical output;
    * write anything anywhere -- no repository ``.create``/``.update``/
      ``.record`` call exists in this module, no file is opened, no
      order/trade/journal/window row is ever touched. Purely an
      in-memory, read-only transformation of one dataclass into
      another.

Determinism: ``build_report()`` performs no randomness, no wall-clock
read, no set/dict iteration over an unordered collection -- every
tuple on ``SustainedUseReviewResult`` is already deterministically
ordered by ``SustainedUseReviewService`` itself (sorted by the
underlying row's own id/timestamp), so rendering the same result
object (or two separately-built-but-identical result objects, e.g.
across a restart against the same on-disk database) always yields the
exact same ``SustainedUseReviewReport.lines``/``.text``.

Evidence-status vocabulary (unchanged, reused verbatim from
``Services.sustained_use_review_service``): ``AVAILABLE`` /
``NOT_AVAILABLE`` / ``INSUFFICIENT_DATA`` / ``EXTERNAL_BLOCKED``. This
module does not define its own status vocabulary -- it only ever
prints the status string already on the result, never translates or
collapses it.

Traceability: every source record already carried on the result
(``SchedulerJobRun``, ``AuditEvent``, ``TelegramCommandAudit``,
``NotificationDedupState``, ``DecisionBrief``, ``JournalEntry``,
``DailyPerformance``) is rendered with its own real id/timestamp
field(s) still visible in the report text, so any line can be traced
back to the exact row it came from via that row's own repository.

No human CONTINUE/SIMPLIFY/AUTHORIZE-FUTURE-BROKER-INVESTIGATION
decision is rendered anywhere in this report -- that decision remains
explicitly out of scope (see
``Services.sustained_use_review_service`` module docstring and the
Phase H roadmap); this module only ever prints evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from Services.sustained_use_review_service import (
    STATUS_NOT_AVAILABLE,
    SustainedUseReviewResult,
)

_RULE = "=" * 72
_SUBRULE = "-" * 72


@dataclass(frozen=True)
class SustainedUseReviewReport:
    """A durable, deterministic, human-readable rendering of one
    already-computed ``SustainedUseReviewResult``.

    Attributes:
        result: The exact, untouched ``SustainedUseReviewResult`` this
            report was built from -- kept on the report itself so a
            caller/test can cross-check any rendered line against its
            own original evidence value.
        generated_at: Copied verbatim from ``result.generated_at``
            (see module docstring -- never re-stamped here).
        lines: The report body, one already-formatted line per entry,
            in deterministic, fixed section order.
    """

    result: SustainedUseReviewResult
    generated_at: str
    lines: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def text(self) -> str:
        """The full report as one newline-joined string."""
        return "\n".join(self.lines)


class SustainedUseReportService:
    """Builds one :class:`SustainedUseReviewReport` from one
    caller-supplied :class:`SustainedUseReviewResult`.

    No constructor argument (mirrors ``Business.report_service.
    ReportService``) -- every value this service reads comes from the
    ``result`` parameter of ``build_report()`` itself, never from a
    repository, service, or engine this class holds a reference to.
    """

    def build_report(self, result: SustainedUseReviewResult) -> SustainedUseReviewReport:
        """Render ``result`` into a :class:`SustainedUseReviewReport`.

        Read-only: reads attributes off ``result`` and its nested
        evidence dataclasses only. Never calls ``.generate_review()``,
        never recalculates a count, never re-derives a status.

        Args:
            result: An already-built ``SustainedUseReviewResult``
                (typically ``SustainedUseReviewService.
                generate_review()``'s own return value).

        Returns:
            A frozen ``SustainedUseReviewReport`` whose
            ``generated_at`` equals ``result.generated_at`` verbatim.
        """
        lines: List[str] = []
        lines.extend(self._render_header(result))
        lines.extend(self._render_window(result))
        lines.extend(self._render_availability(result))
        lines.extend(self._render_data_freshness(result))
        lines.extend(self._render_alert_usefulness(result))
        lines.extend(self._render_plan_journal_adherence(result))
        lines.extend(self._render_paper_reconciliation(result))
        lines.extend(self._render_drawdown_process(result))
        lines.extend(self._render_strategy_regime(result))
        lines.extend(self._render_known_limitations(result))
        lines.extend(self._render_footer(result))
        return SustainedUseReviewReport(
            result=result, generated_at=result.generated_at, lines=tuple(lines)
        )

    # -- header/footer ----------------------------------------------------

    @staticmethod
    def _render_header(result: SustainedUseReviewResult) -> List[str]:
        return [
            _RULE,
            "SUSTAINED-USE REVIEW -- EVIDENCE REPORT",
            _RULE,
            f"generated_at            : {result.generated_at}",
            f"overall_evidence_status : {result.overall_evidence_status}",
            "",
            "This report is evidence only. It contains no CONTINUE / SIMPLIFY /",
            "AUTHORIZE-FUTURE-BROKER-INVESTIGATION decision -- that remains a",
            "separate, future, human decision outside this report's scope.",
            "",
        ]

    @staticmethod
    def _render_footer(result: SustainedUseReviewResult) -> List[str]:
        return ["", _RULE, "END OF SUSTAINED-USE REVIEW EVIDENCE REPORT", _RULE]

    # -- section 1: window metadata ----------------------------------------

    @staticmethod
    def _render_window(result: SustainedUseReviewResult) -> List[str]:
        window = result.window
        return [
            _SUBRULE,
            "1. OBSERVATION WINDOW",
            _SUBRULE,
            f"  window_id     : {window.window_id}",
            f"  start_at      : {window.start_at}",
            f"  end_at        : {window.end_at}",
            f"  timezone      : {window.timezone}",
            f"  window_status : {window.window_status}",
            "",
        ]

    # -- section 2: availability -------------------------------------------

    @staticmethod
    def _render_availability(result: SustainedUseReviewResult) -> List[str]:
        availability = result.availability
        lines = [
            _SUBRULE,
            "2. AVAILABILITY / OPERATIONS",
            _SUBRULE,
            f"  status               : {availability.status}",
            f"  scheduled_job_count  : {availability.scheduled_job_count}",
            f"  success_count        : {availability.success_count}",
            f"  failure_count        : {availability.failure_count}",
            f"  running_count        : {availability.running_count}",
            f"  job_runs ({len(availability.job_runs)}):",
        ]
        if not availability.job_runs:
            lines.append("    (none in this window)")
        for run in availability.job_runs:
            lines.append(
                f"    job_type={run.job_type}  trading_date={run.trading_date}  "
                f"status={run.status}  attempt={run.attempt}  started_at={run.started_at}  "
                f"finished_at={run.finished_at}  next_retry_at={run.next_retry_at}  "
                f"detail={run.detail!r}"
            )
        lines.append("")
        return lines

    # -- section 3: data freshness ------------------------------------------

    @staticmethod
    def _render_data_freshness(result: SustainedUseReviewResult) -> List[str]:
        freshness = result.data_freshness
        lines = [
            _SUBRULE,
            "3. DATA FRESHNESS",
            _SUBRULE,
            f"  status                     : {freshness.status}",
            f"  valuation_snapshot_status  : {freshness.valuation_snapshot_status}",
            f"  fresh_snapshot_count       : {freshness.fresh_snapshot_count}",
            f"  stale_snapshot_count       : {freshness.stale_snapshot_count}",
            f"  unavailable_snapshot_count : {freshness.unavailable_snapshot_count}",
            f"  freshness_degraded_events ({len(freshness.freshness_degraded_events)}):",
        ]
        if not freshness.freshness_degraded_events:
            lines.append("    (none in this window)")
        for event in freshness.freshness_degraded_events:
            lines.append(f"    id={event.id}  created_at={event.created_at}  payload={event.payload!r}")
        lines.append(f"  freshness_recovered_events ({len(freshness.freshness_recovered_events)}):")
        if not freshness.freshness_recovered_events:
            lines.append("    (none in this window)")
        for event in freshness.freshness_recovered_events:
            lines.append(f"    id={event.id}  created_at={event.created_at}  payload={event.payload!r}")
        lines.append("")
        return lines

    # -- section 4: alert usefulness -----------------------------------------

    @staticmethod
    def _render_alert_usefulness(result: SustainedUseReviewResult) -> List[str]:
        alerts = result.alert_usefulness
        lines = [
            _SUBRULE,
            "4. ALERT USEFULNESS",
            _SUBRULE,
            f"  status                        : {alerts.status}",
            f"  sent_count                    : {alerts.sent_count}",
            f"  suppress_no_change_count      : {alerts.suppress_no_change_count}",
            f"  suppress_rate_limited_count   : {alerts.suppress_rate_limited_count}",
            f"  other_suppressed_count        : {alerts.other_suppressed_count}",
            f"  failed_count                  : {alerts.failed_count}",
            f"  notification_events ({len(alerts.notification_events)}):",
        ]
        if not alerts.notification_events:
            lines.append("    (none in this window)")
        for event in alerts.notification_events:
            lines.append(
                f"    id={event.id}  event_type={event.event_type}  "
                f"created_at={event.created_at}  payload={event.payload!r}"
            )
        lines.append(f"  telegram_status               : {alerts.telegram_status}")
        lines.append(f"  command_audit_count           : {alerts.command_audit_count}")
        lines.append(f"  command_audits ({len(alerts.command_audits)}):")
        if not alerts.command_audits:
            lines.append("    (none in this window, or telegram_status is NOT_AVAILABLE)")
        for command in alerts.command_audits:
            lines.append(
                f"    id={command.id}  update_id={command.update_id}  chat_id={command.chat_id}  "
                f"command={command.command}  status={command.status}  "
                f"received_at={command.received_at}  detail={command.detail!r}"
            )
        lines.append(f"  dedup_states ({len(alerts.dedup_states)}) -- current, NOT window-scoped, context only:")
        if not alerts.dedup_states:
            lines.append("    (none)")
        for state in alerts.dedup_states:
            lines.append(
                f"    alert_type={state.alert_type}  last_status={state.last_status}  "
                f"last_sent_at={state.last_sent_at}  updated_at={state.updated_at}"
            )
        lines.append("")
        return lines

    # -- section 5: plan/journal adherence -----------------------------------

    @staticmethod
    def _render_plan_journal_adherence(result: SustainedUseReviewResult) -> List[str]:
        adherence = result.plan_journal_adherence
        lines = [
            _SUBRULE,
            "5. PLAN / JOURNAL ADHERENCE",
            _SUBRULE,
            f"  status                : {adherence.status}",
            f"  briefs_in_window ({len(adherence.briefs_in_window)}):",
        ]
        if not adherence.briefs_in_window:
            lines.append("    (none in this window)")
        for brief in adherence.briefs_in_window:
            lines.append(
                f"    brief_id={brief.brief_id}  symbol={brief.symbol}  status={brief.status}  "
                f"generated_at={brief.generated_at}"
            )
        lines.append(f"  brief_status_counts   : {dict(adherence.brief_status_counts)}")
        lines.append(f"  journal_entries_in_window ({len(adherence.journal_entries_in_window)}):")
        if not adherence.journal_entries_in_window:
            lines.append("    (none in this window)")
        for entry in adherence.journal_entries_in_window:
            lines.append(
                f"    entry_id={entry.entry_id}  brief_id={entry.brief_id}  symbol={entry.symbol}  "
                f"decision={entry.decision}  decided_at={entry.decided_at}  "
                f"outcome_status={entry.outcome_status}"
            )
        lines.append(f"  take_count            : {adherence.take_count}")
        lines.append(f"  skip_count            : {adherence.skip_count}")
        lines.append(f"  wait_count            : {adherence.wait_count}")
        lines.append(f"  paper_review_status   : {adherence.paper_review_status}")
        if adherence.paper_review_status == STATUS_NOT_AVAILABLE:
            lines.append("  approved_paper_count  : NOT_AVAILABLE")
            lines.append("  linked_order_count    : NOT_AVAILABLE")
            lines.append("  linked_trade_count    : NOT_AVAILABLE")
            lines.append("  adherence_summary     : NOT_AVAILABLE")
        else:
            lines.append(f"  approved_paper_count  : {adherence.approved_paper_count}")
            lines.append(f"  linked_order_count    : {adherence.linked_order_count}")
            lines.append(f"  linked_trade_count    : {adherence.linked_trade_count}")
            lines.append(f"  adherence_summary     : {dict(adherence.adherence_summary or {})}")
        lines.append("")
        return lines

    # -- section 6: paper reconciliation -------------------------------------

    @staticmethod
    def _render_paper_reconciliation(result: SustainedUseReviewResult) -> List[str]:
        reconciliation = result.paper_reconciliation
        lines = [
            _SUBRULE,
            "6. PAPER RECONCILIATION",
            _SUBRULE,
            f"  status         : {reconciliation.status}",
            f"  account_id     : {reconciliation.account_id}",
            f"  consistent     : {reconciliation.consistent}",
            f"  violations ({len(reconciliation.violations)}):",
        ]
        if not reconciliation.violations:
            lines.append("    (none)")
        for violation in reconciliation.violations:
            lines.append(f"    {violation}")
        lines.append(f"  not_verifiable ({len(reconciliation.not_verifiable)}):")
        if not reconciliation.not_verifiable:
            lines.append("    (none)")
        for item in reconciliation.not_verifiable:
            lines.append(f"    {item}")
        lines.append("")
        return lines

    # -- section 7: drawdown/process metrics ----------------------------------

    @staticmethod
    def _render_drawdown_process(result: SustainedUseReviewResult) -> List[str]:
        drawdown = result.drawdown_process
        lines = [
            _SUBRULE,
            "7. DRAWDOWN / PROCESS METRICS",
            _SUBRULE,
            f"  status      : {drawdown.status}",
            f"  account_id  : {drawdown.account_id}",
            f"  records ({len(drawdown.records)}):",
        ]
        if not drawdown.records:
            lines.append("    (none in this window)")
        for record in drawdown.records:
            lines.append(
                f"    daily_performance_id={record.daily_performance_id}  "
                f"start_timestamp={record.start_timestamp}  end_timestamp={record.end_timestamp}  "
                f"net_result={record.net_result}  drawdown={record.drawdown}  "
                f"starting_equity={record.starting_equity}  ending_equity={record.ending_equity}"
            )
        lines.append("")
        return lines

    # -- section 8: strategy/regime ---------------------------------------------

    @staticmethod
    def _render_strategy_regime(result: SustainedUseReviewResult) -> List[str]:
        strategy_regime = result.strategy_regime
        lines = [
            _SUBRULE,
            "8. STRATEGY / REGIME EVIDENCE",
            _SUBRULE,
            f"  status                   : {strategy_regime.status}",
            f"  account_id               : {strategy_regime.account_id}",
        ]
        if strategy_regime.status == STATUS_NOT_AVAILABLE:
            lines.append("  strategy_breakdown       : NOT_AVAILABLE")
            lines.append("  market_regime_breakdown  : NOT_AVAILABLE")
        else:
            lines.append(f"  strategy_breakdown       : {strategy_regime.strategy_breakdown!r}")
            lines.append(f"  market_regime_breakdown  : {strategy_regime.market_regime_breakdown!r}")
        lines.append("")
        return lines

    # -- section 9: known limitations --------------------------------------------

    @staticmethod
    def _render_known_limitations(result: SustainedUseReviewResult) -> List[str]:
        lines = [
            _SUBRULE,
            "9. KNOWN LIMITATIONS",
            _SUBRULE,
            f"  known_limitations ({len(result.known_limitations)}):",
        ]
        if not result.known_limitations:
            lines.append("    (none)")
        for limitation in result.known_limitations:
            lines.append(f"    [{limitation.status}] dimension={limitation.dimension}")
            lines.append(f"        {limitation.detail}")
        return lines