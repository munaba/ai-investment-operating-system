"""``DecisionBriefPolicy`` -- Phase B ("Decision Copilot").

Pure, stateless component that inspects an existing ``RankingSnapshot``
(and how stale it is) and decides which non-``SUCCESS`` Phase-B status
applies, if any. Never computes a plan, never calls
``RiskManagementService``, never persists anything, never reads a
database or the network.

Deliberately distinct from ``Orchestration.decision_policy.
DecisionPolicy``: that component maps an autonomous-agent ``Decision``
(action/confidence) to entry/exit permissions for the L20A pipeline. It
is unrelated to briefs. This class does not import it, extend it, or
reuse its name, to avoid any collision with that existing, LOCKED
component.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from Database.models import RankingSnapshot

#: A snapshot older than this is considered stale for brief purposes.
#: Mirrors the scan cadence documented for ``ManualScanService`` --
#: intraday data older than a few hours is no longer a safe basis for
#: a same-day entry/stop/target plan.
DEFAULT_STALE_AFTER = timedelta(hours=6)


@dataclass(frozen=True)
class DecisionBriefGateResult:
    """Outcome of ``DecisionBriefPolicy.evaluate``.

    Attributes:
        blocked_status: ``None`` if the snapshot passes every gate and
            a plan may be attempted (``DecisionBriefService`` still
            must successfully price the trade and pass
            ``RiskManagementService`` for the brief to actually reach
            ``SUCCESS``). Otherwise, one of ``DATA_STALE``,
            ``DATA_ERROR``, ``INSUFFICIENT_DATA``, ``ANALYSIS_FAILED``,
            ``NO_TRADE``, ``POLICY_BLOCKED`` -- the status
            ``DecisionBriefService`` must persist as-is, with no plan.
        reason: Human-readable explanation for ``blocked_status``,
            ``None`` when ``blocked_status`` is ``None``.
    """

    blocked_status: Optional[str]
    reason: Optional[str]


class DecisionBriefPolicy:
    """Stateless gate: ``RankingSnapshot`` -> allow-plan-attempt or a
    concrete non-``SUCCESS`` status.

    Design constraints, mirroring ``Orchestration.decision_policy.
    DecisionPolicy``: no Database dependency, no Service dependency, no
    Provider dependency, no LLM calls, deterministic (same snapshot +
    same "now" always produces the same result).
    """

    def evaluate(
        self,
        snapshot: Optional[RankingSnapshot],
        *,
        now: Optional[datetime] = None,
        stale_after: timedelta = DEFAULT_STALE_AFTER,
    ) -> DecisionBriefGateResult:
        """Decide whether ``snapshot`` may proceed to a risk-managed plan.

        Args:
            snapshot: The latest ``RankingSnapshot`` for a symbol, or
                ``None`` if no scan has ever recorded one.
            now: Current time for staleness comparison. Defaults to
                real UTC now.
            stale_after: Maximum snapshot age before it is considered
                stale.

        Returns:
            A :class:`DecisionBriefGateResult`. ``blocked_status is
            None`` means every gate passed here -- it does NOT mean
            the brief will be ``SUCCESS``; pricing and
            ``RiskManagementService`` still have to succeed.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        if snapshot is None:
            return DecisionBriefGateResult(
                blocked_status="INSUFFICIENT_DATA",
                reason="No ranking snapshot exists for this symbol yet. Run a scan first.",
            )

        if snapshot.status == "error":
            return DecisionBriefGateResult(
                blocked_status="DATA_ERROR",
                reason=snapshot.error_message or "The most recent scan recorded an error for this symbol.",
            )

        scan_time = self._parse_timestamp(snapshot.scan_time)
        if scan_time is None:
            return DecisionBriefGateResult(
                blocked_status="DATA_ERROR",
                reason=f"Snapshot scan_time '{snapshot.scan_time}' could not be parsed.",
            )

        age = now - scan_time
        if age > stale_after:
            return DecisionBriefGateResult(
                blocked_status="DATA_STALE",
                reason=(
                    f"Most recent scan for this symbol is {age} old "
                    f"(stale after {stale_after}). Run a fresh scan first."
                ),
            )

        if not snapshot.recommendation or not snapshot.confidence:
            return DecisionBriefGateResult(
                blocked_status="INSUFFICIENT_DATA",
                reason="Snapshot is missing recommendation/confidence needed to brief this symbol.",
            )

        if snapshot.recommendation.upper() != "BUY":
            return DecisionBriefGateResult(
                blocked_status="NO_TRADE",
                reason=f"Latest recommendation is '{snapshot.recommendation}', not BUY -- nothing actionable to plan.",
            )

        return DecisionBriefGateResult(blocked_status=None, reason=None)

    @staticmethod
    def _parse_timestamp(value: str) -> Optional[datetime]:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed