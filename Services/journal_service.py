"""``JournalService`` -- Phase C ("Personal Risk Ledger + Decision
Journal").

Records a person's own TAKE/SKIP/WAIT call against an existing
``DecisionBrief``, enforcing their persisted ``RiskLimits`` on every
TAKE via ``Business.risk_ledger_policy.RiskLedgerPolicy``, and lets
them later attach optional, manually-supplied execution/close
information to an ACCEPTED TAKE.

This service invents nothing. It reuses exactly these existing,
LOCKED components:

    * ``Repository.persistence.decision_brief_repository.
      DecisionBriefRepository`` -- read-only lookup of the
      ``DecisionBrief`` a decision is linked to. This service never
      generates or reprices a brief.
    * ``Business.risk_ledger_policy.RiskLedgerPolicy`` -- the one and
      only personal-risk-limit enforcement in this codebase. This
      service never recomputes a stop, target, position size, or risk
      amount itself.

Recording a journal decision -- of any kind, including an ACCEPTED
TAKE -- never creates a paper order, a ``Trade``, or a ``Position``:
this service holds no reference to ``PaperTradingEngine``/
``OrderLifecycleService``/``ExecutionService`` and calls none of them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from Business.risk_ledger_policy import RiskLedgerPolicy, RiskLedgerStats
from Database.models import JournalEntry
from Repository.persistence.decision_brief_repository import DecisionBriefRepository
from Repository.persistence.journal_repository import JournalRepository
from Repository.persistence.risk_limits_repository import RiskLimitsRepository

#: Every valid Phase-C journal decision.
DECISION_TAKE = "TAKE"
DECISION_SKIP = "SKIP"
DECISION_WAIT = "WAIT"
VALID_DECISIONS = frozenset({DECISION_TAKE, DECISION_SKIP, DECISION_WAIT})

#: Every valid Phase-C outcome status.
VALID_OUTCOME_STATUSES = frozenset({"OPEN", "CLOSED_WIN", "CLOSED_LOSS", "CLOSED_BREAKEVEN"})


class JournalService:
    """Orchestrates one decision-recording or one outcome-recording
    request.

    Constructor injection only, mirroring ``DecisionBriefService``:
    ``brief_repository`` (read-only lookup of the linked brief),
    ``risk_limits_repository`` (read-only lookup of the person's
    limits), ``journal_repository`` (persist decisions/outcomes),
    ``risk_ledger_policy`` (the one risk-ledger gate). Stateless beyond
    these collaborators -- safe to reuse across calls.
    """

    def __init__(
        self,
        brief_repository: DecisionBriefRepository,
        risk_limits_repository: RiskLimitsRepository,
        journal_repository: JournalRepository,
        risk_ledger_policy: RiskLedgerPolicy,
    ) -> None:
        self._brief_repository = brief_repository
        self._risk_limits_repository = risk_limits_repository
        self._journal_repository = journal_repository
        self._risk_ledger_policy = risk_ledger_policy

    def record_decision(
        self,
        brief_id: int,
        decision: str,
        *,
        note: Optional[str] = None,
    ) -> JournalEntry:
        """Record a TAKE/SKIP/WAIT decision against ``brief_id``.

        Never raises for business-level rejection (a TAKE that
        exceeds a personal limit) -- that outcome is represented as a
        persisted, ``RISK_REJECTED`` journal entry, exactly like
        ``DecisionBriefService.generate_brief`` represents every
        business-level outcome as a persisted row rather than an
        exception. Only a missing/invalid ``brief_id`` or an invalid
        ``decision`` value raises ``ValueError`` -- those are caller
        errors, not risk-policy outcomes.

        Args:
            brief_id: The ``DecisionBrief.brief_id`` to decide on.
            decision: One of ``"TAKE"``/``"SKIP"``/``"WAIT"``
                (case-insensitive).
            note: Optional free-text note from the person.

        Returns:
            The persisted :class:`Database.models.JournalEntry`.

        Raises:
            ValueError: If ``decision`` is not one of the three valid
                values, or if no ``DecisionBrief`` exists for
                ``brief_id``.
            RepositoryError: If the underlying statement fails.
        """
        decision = decision.upper()
        if decision not in VALID_DECISIONS:
            raise ValueError(f"decision must be one of {sorted(VALID_DECISIONS)}, got {decision!r}.")

        brief = self._brief_repository.get_by_id(brief_id)
        if brief is None:
            raise ValueError(f"No DecisionBrief exists with brief_id={brief_id}.")

        limits = self._risk_limits_repository.get_current()
        stats = self._compute_stats()
        gate = self._risk_ledger_policy.evaluate(decision, brief, limits, stats)

        decided_at = datetime.now(timezone.utc).isoformat()
        planned_r = brief.risk_reward_ratio if (decision == DECISION_TAKE and brief.status == "SUCCESS") else None

        return self._journal_repository.create(
            brief_id=brief.brief_id,
            symbol=brief.symbol,
            decision=decision,
            decided_at=decided_at,
            note=note,
            risk_policy_status=gate.status,
            risk_policy_reason=gate.reason,
            planned_r=planned_r,
            created_at=decided_at,
        )

    def record_outcome(
        self,
        entry_id: int,
        *,
        outcome_status: str,
        exit_price: Optional[float] = None,
        closed_at: Optional[str] = None,
    ) -> JournalEntry:
        """Attach manual execution/close information to an existing,
        ACCEPTED TAKE journal entry.

        Only ever recomputes ``realized_r`` when it is genuinely
        calculable: a real ``exit_price`` was supplied AND the linked
        brief has a real ``entry_price``/``stop_loss_price`` with
        positive risk-per-unit. Otherwise ``realized_r`` stays
        ``None`` -- never guessed.

        Args:
            entry_id: The journal entry to update.
            outcome_status: One of ``"OPEN"``/``"CLOSED_WIN"``/
                ``"CLOSED_LOSS"``/``"CLOSED_BREAKEVEN"``
                (case-insensitive).
            exit_price: Real, caller-supplied exit price, if known.
            closed_at: ISO-8601 timestamp of this close. Defaults to
                real UTC now.

        Returns:
            The updated :class:`Database.models.JournalEntry`.

        Raises:
            ValueError: If ``entry_id`` does not exist, ``outcome_status``
                is invalid, or the entry is not an ACCEPTED TAKE (only
                a decision that actually committed capital can have an
                outcome).
            RepositoryError: If the underlying statement fails.
        """
        entry = self._journal_repository.get_by_id(entry_id)
        if entry is None:
            raise ValueError(f"No journal entry exists with entry_id={entry_id}.")

        if entry.decision != DECISION_TAKE or entry.risk_policy_status != "ACCEPTED":
            raise ValueError(
                f"Journal entry {entry_id} is a {entry.decision}/{entry.risk_policy_status} decision -- "
                "only an ACCEPTED TAKE can record an outcome."
            )

        outcome_status = outcome_status.upper()
        if outcome_status not in VALID_OUTCOME_STATUSES:
            raise ValueError(f"outcome_status must be one of {sorted(VALID_OUTCOME_STATUSES)}, got {outcome_status!r}.")

        realized_r = self._calculate_realized_r(entry, exit_price)
        resolved_closed_at = closed_at or datetime.now(timezone.utc).isoformat()

        updated = self._journal_repository.record_outcome(
            entry_id,
            outcome_status=outcome_status,
            exit_price=exit_price,
            realized_r=realized_r,
            closed_at=resolved_closed_at,
        )
        assert updated is not None  # entry existed above; no concurrent delete path exists
        return updated

    def get_by_id(self, entry_id: int) -> Optional[JournalEntry]:
        """Read-only retrieval of one journal entry, or ``None``."""
        return self._journal_repository.get_by_id(entry_id)

    def list_by_symbol(self, symbol: str) -> List[JournalEntry]:
        """Read-only retrieval of every journal entry for ``symbol``."""
        return self._journal_repository.list_by_symbol(symbol.upper())

    def list_all(self) -> List[JournalEntry]:
        """Read-only retrieval of every journal entry."""
        return self._journal_repository.list_all()

    def _calculate_realized_r(self, entry: JournalEntry, exit_price: Optional[float]) -> Optional[float]:
        if exit_price is None:
            return None
        brief = self._brief_repository.get_by_id(entry.brief_id)
        if brief is None or brief.entry_price is None or brief.stop_loss_price is None:
            return None
        risk_per_unit = brief.entry_price - brief.stop_loss_price
        if risk_per_unit <= 0:
            return None
        return (exit_price - brief.entry_price) / risk_per_unit

    def _compute_stats(self) -> RiskLedgerStats:
        """Derive today's ``RiskLedgerStats`` from real, already-persisted
        journal entries -- recomputed fresh on every call, never
        cached, so this is automatically restart-safe.
        """
        entries = self._journal_repository.list_all()
        today = datetime.now(timezone.utc).date().isoformat()

        trades_taken_today = sum(
            1
            for e in entries
            if e.decision == DECISION_TAKE and e.risk_policy_status == "ACCEPTED" and e.decided_at[:10] == today
        )

        closed_entries = [e for e in entries if e.outcome_status in ("CLOSED_WIN", "CLOSED_LOSS", "CLOSED_BREAKEVEN")]
        closed_entries.sort(key=lambda e: (e.closed_at or "", e.entry_id))

        realized_loss_today = 0.0
        for e in closed_entries:
            if e.outcome_status == "CLOSED_LOSS" and e.closed_at and e.closed_at[:10] == today and e.realized_r is not None:
                brief = self._brief_repository.get_by_id(e.brief_id)
                if brief is not None and brief.risk_amount is not None:
                    realized_loss_today += abs(e.realized_r) * brief.risk_amount

        current_loss_streak = 0
        for e in reversed(closed_entries):
            if e.outcome_status == "CLOSED_LOSS":
                current_loss_streak += 1
            else:
                break

        return RiskLedgerStats(
            trades_taken_today=trades_taken_today,
            realized_loss_today=realized_loss_today,
            current_loss_streak=current_loss_streak,
        )