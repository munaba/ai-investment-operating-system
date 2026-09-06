"""``RiskLedgerPolicy`` -- Phase C ("Personal Risk Ledger + Decision
Journal").

Pure, stateless component that decides whether a proposed TAKE
decision against an existing ``DecisionBrief`` is ``ACCEPTED`` or
``RISK_REJECTED`` under a person's own persisted ``RiskLimits`` and
their recent journal history. Never computes a stop, target, position
size, or risk amount itself -- those are exclusively
``RiskManagementService``'s job, already baked into the
``DecisionBrief`` this policy is handed. Never persists anything,
never reads a database or the network.

Deliberately distinct from ``Business.decision_brief_policy.
DecisionBriefPolicy``: that component gates whether a *plan* may be
attempted at all (fresh data, BUY recommendation); this component
gates whether a person may *commit capital* to an already-priced plan,
given their own limits. Neither imports, extends, or duplicates the
other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from Database.models import DecisionBrief, RiskLimits

#: Every valid Phase-C risk-policy verdict.
STATUS_ACCEPTED = "ACCEPTED"
STATUS_RISK_REJECTED = "RISK_REJECTED"


@dataclass(frozen=True)
class RiskLedgerStats:
    """A person's own recent journal history, as of "now" -- entirely
    caller-computed from real, persisted ``JournalEntry`` rows. This
    policy never queries a repository itself.

    Attributes:
        trades_taken_today: Count of this calendar day's ACCEPTED TAKE
            decisions.
        realized_loss_today: Sum, in the same currency as
            ``RiskLimits.reference_capital``, of this calendar day's
            realized losses across CLOSED_LOSS journal entries.
            ``0.0`` if none.
        current_loss_streak: Count of consecutive most-recent closed
            trades that were CLOSED_LOSS (broken by any CLOSED_WIN/
            CLOSED_BREAKEVEN). ``0`` if the most recent closed trade
            was not a loss, or nothing has closed yet.
    """

    trades_taken_today: int
    realized_loss_today: float
    current_loss_streak: int


@dataclass(frozen=True)
class RiskLedgerGateResult:
    """Outcome of ``RiskLedgerPolicy.evaluate``.

    Attributes:
        status: ``"ACCEPTED"`` or ``"RISK_REJECTED"`` -- the status
            ``JournalService`` persists as ``JournalEntry.risk_policy_status``.
        reason: Human-readable explanation, ``None`` when ``status``
            is ``"ACCEPTED"``.
    """

    status: str
    reason: Optional[str]


class RiskLedgerPolicy:
    """Stateless gate: (decision, brief, limits, stats) -> ACCEPTED or
    RISK_REJECTED-with-reason.

    Design constraints, mirroring ``DecisionBriefPolicy``: no Database
    dependency, no Service dependency, no LLM calls, deterministic
    (same inputs always produce the same result).
    """

    def evaluate(
        self,
        decision: str,
        brief: DecisionBrief,
        limits: Optional[RiskLimits],
        stats: RiskLedgerStats,
    ) -> RiskLedgerGateResult:
        """Decide whether ``decision`` may be recorded as ``ACCEPTED``.

        Only a ``"TAKE"`` decision is actually risk-checked: it is the
        only decision that implies committing capital. ``"SKIP"``/
        ``"WAIT"`` always resolve ``ACCEPTED`` -- there is nothing to
        enforce a limit against when no capital is being committed.

        Args:
            decision: One of ``"TAKE"``/``"SKIP"``/``"WAIT"``.
            brief: The ``DecisionBrief`` this decision is linked to.
            limits: The person's persisted ``RiskLimits``, or ``None``
                if none have ever been saved.
            stats: This person's own recent journal history.

        Returns:
            A :class:`RiskLedgerGateResult`.
        """
        if decision != "TAKE":
            return RiskLedgerGateResult(status=STATUS_ACCEPTED, reason=None)

        if limits is None:
            return RiskLedgerGateResult(
                status=STATUS_RISK_REJECTED,
                reason=(
                    "No personal risk limits are configured yet. Set them with "
                    "'python main.py risk-limits set ...' before recording a TAKE."
                ),
            )

        if limits.allowed_symbols and brief.symbol.upper() not in limits.allowed_symbols:
            return RiskLedgerGateResult(
                status=STATUS_RISK_REJECTED,
                reason=f"Symbol '{brief.symbol}' is not in the allowed symbol list {limits.allowed_symbols}.",
            )

        if brief.status != "SUCCESS" or brief.risk_amount is None or brief.entry_price is None or brief.stop_loss_price is None:
            return RiskLedgerGateResult(
                status=STATUS_RISK_REJECTED,
                reason=(
                    f"Linked brief (brief_id={brief.brief_id}, status={brief.status}) has no valid "
                    "priced plan to TAKE -- a brief must be SUCCESS with a real risk amount."
                ),
            )

        if brief.risk_amount <= 0:
            return RiskLedgerGateResult(
                status=STATUS_RISK_REJECTED,
                reason=f"Linked brief's risk amount ({brief.risk_amount}) is not positive.",
            )

        max_risk_dollars = limits.reference_capital * (limits.max_risk_per_trade_percent / 100)
        if brief.risk_amount > max_risk_dollars:
            return RiskLedgerGateResult(
                status=STATUS_RISK_REJECTED,
                reason=(
                    f"Planned risk {brief.risk_amount:.2f} exceeds max risk per trade "
                    f"{max_risk_dollars:.2f} ({limits.max_risk_per_trade_percent}% of reference "
                    f"capital {limits.reference_capital:.2f})."
                ),
            )

        if stats.realized_loss_today >= limits.max_daily_loss:
            return RiskLedgerGateResult(
                status=STATUS_RISK_REJECTED,
                reason=(
                    f"Max daily loss reached: realized loss today "
                    f"{stats.realized_loss_today:.2f} >= limit {limits.max_daily_loss:.2f}."
                ),
            )

        if stats.trades_taken_today >= limits.max_trades_per_day:
            return RiskLedgerGateResult(
                status=STATUS_RISK_REJECTED,
                reason=(
                    f"Max decisions/trades per day reached: {stats.trades_taken_today} "
                    f">= limit {limits.max_trades_per_day}."
                ),
            )

        if limits.loss_streak_cooldown > 0 and stats.current_loss_streak >= limits.loss_streak_cooldown:
            return RiskLedgerGateResult(
                status=STATUS_RISK_REJECTED,
                reason=(
                    f"Loss-streak cooldown active: {stats.current_loss_streak} consecutive "
                    f"losses >= cooldown threshold {limits.loss_streak_cooldown}."
                ),
            )

        return RiskLedgerGateResult(status=STATUS_ACCEPTED, reason=None)