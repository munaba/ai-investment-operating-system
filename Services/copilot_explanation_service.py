"""CopilotExplanationService -- Phase F, Task 4: explain an existing,
already-persisted ``DecisionBrief`` in natural language.

Scope note (LOCKED for this task): this module introduces exactly two
things.

  1. ``CopilotExplanationResult`` -- an immutable value object carrying
     the explanation this service produces.
  2. ``CopilotExplanationService`` -- a pure, stateless, template-only
     component that turns an already-computed
     ``Database.models.DecisionBrief`` into a
     ``CopilotExplanationResult``.

This is deliberately the narrowest possible slice of the "explanation"
capability declared by the Phase F, Task 1 copilot contract. It
explains existing state; it never computes new state.

Explicitly NOT part of this task: an LLM/provider call (this is
template-based, exactly like ``Orchestration.text_analysis_skill.
TextAnalysisSkill``'s deterministic ``"summary"`` string -- plain
f-strings over already-computed values, nothing else), a database
read (the caller is responsible for fetching the ``DecisionBrief``,
e.g. via ``Repository.persistence.decision_brief_repository.
DecisionBriefRepository``, and handing it to this service -- this
module never imports that repository or any other Repository/Database
I/O path), a tool/skill invocation, memory reads or writes, a paper or
live order, or any Telegram side effect. This module never generates a
new recommendation, entry/stop/target plan, confidence score, or
status -- it only narrates the ``DecisionBrief`` it is given, and
carries its ``status``/``reason``/prices/timestamps through verbatim.
It never invents a value that ``DecisionBrief`` did not already supply.

Status vocabulary (verbatim, from ``Services.decision_brief_service``,
LOCKED there -- not redefined here): ``SUCCESS``, ``NO_TRADE``,
``DATA_STALE``, ``DATA_ERROR``, ``INSUFFICIENT_DATA``,
``ANALYSIS_FAILED``, ``RISK_REJECTED``, ``POLICY_BLOCKED``. This
service does not import ``Services.decision_brief_service`` (to avoid
any accidental coupling to its DB/Risk/Repository dependencies) --
it matches on the literal status strings a ``DecisionBrief`` already
carries.

Three distinct questions, kept separate in every ``CopilotExplanationResult``
this service returns (per this task's requirement):

  - "What the system decided" -- ``title``, built from ``status``
    (and, for ``SUCCESS``, the concrete entry/stop/target plan) alone.
  - "Why" -- ``reason``, ``DecisionBrief.reason`` carried through
    verbatim, never paraphrased or reworded, so no new claim is ever
    introduced.
  - "What blocked it" -- ``blocked_by``, a short, fixed label derived
    only from ``status`` (e.g. ``"risk policy"`` for
    ``RISK_REJECTED``, ``"stale data"`` for ``DATA_STALE``), ``None``
    for ``SUCCESS`` where nothing was blocked.

Dependency direction: this module imports only the stdlib
``dataclasses``/``typing`` modules plus ``Database.models.
DecisionBrief`` (for a type annotation only -- no Database I/O). It
does not import from, and is not imported by, ``Core.composition_root``,
any Telegram module, ``Providers``, any tool/skill module, or
``Orchestration.memory``. It is additive-only, standing on its own
until a future task wires it behind a copilot-facing entry point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from Database.models import DecisionBrief

#: Fixed, human-readable label for what blocked each non-SUCCESS status.
#: Deliberately a short phrase, not a restatement of ``reason`` -- this
#: answers "what kind of thing blocked it", while ``reason`` (carried
#: through from the ``DecisionBrief`` verbatim) answers "why, in detail".
_BLOCKED_BY_LABELS = {
    "NO_TRADE": "no actionable recommendation",
    "DATA_STALE": "stale data",
    "DATA_ERROR": "data error",
    "INSUFFICIENT_DATA": "insufficient data",
    "ANALYSIS_FAILED": "analysis failure",
    "RISK_REJECTED": "risk policy",
    "POLICY_BLOCKED": "decision policy",
}

#: Fixed, human-readable title fragment for each non-SUCCESS status.
_STATUS_TITLES = {
    "NO_TRADE": "No trade",
    "DATA_STALE": "Not evaluated -- data stale",
    "DATA_ERROR": "Not evaluated -- data error",
    "INSUFFICIENT_DATA": "Not evaluated -- insufficient data",
    "ANALYSIS_FAILED": "Not evaluated -- analysis failed",
    "RISK_REJECTED": "Blocked -- risk rejected",
    "POLICY_BLOCKED": "Blocked -- policy blocked",
}

_KNOWN_STATUSES = frozenset({"SUCCESS", *_STATUS_TITLES.keys()})


@dataclass(frozen=True)
class CopilotExplanationResult:
    """Immutable outcome of ``CopilotExplanationService.explain``.

    Mirrors the shape already used by ``Business.decision_brief_policy.
    DecisionBriefGateResult`` (frozen dataclass, ``Optional`` fields
    for anything that only applies in some cases) rather than the
    generic ``Services.service_result.ServiceResult`` -- this result
    is a specific, typed shape for one capability (explanation), not
    a service's uniform envelope.

    Attributes:
        success: Whether an explanation could be produced at all.
            ``False`` only for missing/invalid input (no
            ``DecisionBrief`` was supplied, or it carried an
            unrecognized ``status``) -- never ``False`` merely because
            the underlying decision was ``NO_TRADE``/``DATA_STALE``/
            etc.; those are still valid, fully explained outcomes.
        title: Short label for "what the system decided" -- e.g.
            ``"Trade plan: BBCA"`` for ``SUCCESS``, ``"No trade"`` for
            ``NO_TRADE``. ``None`` when ``success`` is ``False``.
        summary: One or two plain-text sentences restating the
            decision and its concrete plan (for ``SUCCESS``) or status
            (otherwise), built only from fields already present on the
            input ``DecisionBrief``. ``None`` when ``success`` is
            ``False``.
        reason: "Why" -- ``DecisionBrief.reason`` carried through
            verbatim (never reworded, never fabricated). ``None`` if
            the brief itself carried no reason (e.g. a bare
            ``SUCCESS`` brief with no explanatory text) or when
            ``success`` is ``False``.
        blocked_by: "What blocked it" -- a short fixed label naming
            the category of blocker (see ``_BLOCKED_BY_LABELS``).
            ``None`` for ``SUCCESS`` (nothing was blocked) and
            ``None`` when ``success`` is ``False``.
        status: The ``DecisionBrief.status`` this explanation was
            derived from, carried through verbatim. ``None`` when
            ``success`` is ``False``.
        symbol: The ``DecisionBrief.symbol`` this explanation was
            derived from, carried through verbatim. ``None`` when
            ``success`` is ``False``.
        brief_id: The source ``DecisionBrief.brief_id``, carried
            through verbatim, for traceability. ``None`` when
            ``success`` is ``False``.
        source_snapshot_id: The source ``DecisionBrief.
            source_snapshot_id``, carried through verbatim when the
            brief had one. ``None`` if the brief had none, or when
            ``success`` is ``False``.
        generated_at: The ``DecisionBrief.generated_at`` timestamp,
            carried through verbatim. ``None`` when ``success`` is
            ``False``.
        error: Human-readable explanation of why ``success`` is
            ``False``. ``None`` when ``success`` is ``True``.
    """

    success: bool
    title: Optional[str] = None
    summary: Optional[str] = None
    reason: Optional[str] = None
    blocked_by: Optional[str] = None
    status: Optional[str] = None
    symbol: Optional[str] = None
    brief_id: Optional[int] = None
    source_snapshot_id: Optional[int] = None
    generated_at: Optional[str] = None
    error: Optional[str] = None


class CopilotExplanationService:
    """Pure, stateless, deterministic explainer for an existing
    ``DecisionBrief``.

    Holds no mutable state and no collaborators -- construction takes
    no arguments, and every call to :meth:`explain` depends only on
    its ``brief`` argument. Performs no database read, no provider
    call, no tool execution, and no side effect of any kind: given the
    same ``DecisionBrief`` (or ``None``), :meth:`explain` always
    returns the same ``CopilotExplanationResult``.
    """

    def explain(self, brief: Optional[DecisionBrief]) -> CopilotExplanationResult:
        """Explain ``brief`` in natural language, using only values it
        already carries.

        Never fabricates a price, confidence, timestamp, reason, or
        outcome -- every non-``None`` field on the returned
        ``CopilotExplanationResult`` (other than the small set of
        fixed template labels in ``_STATUS_TITLES``/
        ``_BLOCKED_BY_LABELS``) traces directly back to a field
        already present on ``brief``. Never computes a new
        recommendation or plan.

        Args:
            brief: An already-fetched ``DecisionBrief``, or ``None``
                if none exists for the query this call is answering
                (e.g. no brief has ever been generated for a symbol).

        Returns:
            A ``CopilotExplanationResult``. ``success`` is ``False``
            only when ``brief`` is ``None`` or its ``status`` is not
            one of the eight known Phase-B statuses -- both are
            missing/invalid input, not a normal blocked outcome.
        """
        if brief is None:
            return CopilotExplanationResult(
                success=False,
                error="No decision brief was provided to explain.",
            )

        status = brief.status
        if status not in _KNOWN_STATUSES:
            return CopilotExplanationResult(
                success=False,
                error=f"Unrecognized decision brief status: {status!r}",
            )

        if status == "SUCCESS":
            title, summary = self._explain_success(brief)
            blocked_by = None
        else:
            title, summary = self._explain_blocked(brief, status)
            blocked_by = _BLOCKED_BY_LABELS[status]

        return CopilotExplanationResult(
            success=True,
            title=title,
            summary=summary,
            reason=brief.reason,
            blocked_by=blocked_by,
            status=status,
            symbol=brief.symbol,
            brief_id=brief.brief_id,
            source_snapshot_id=brief.source_snapshot_id,
            generated_at=brief.generated_at,
        )

    @staticmethod
    def _explain_success(brief: DecisionBrief) -> "tuple[str, str]":
        """Build the ("what the system decided") title/summary for a
        ``SUCCESS`` brief -- the concrete, already-computed plan.

        Args:
            brief: A ``DecisionBrief`` with ``status == "SUCCESS"``.

        Returns:
            A ``(title, summary)`` tuple built only from ``brief``'s
            own plan fields.
        """
        title = f"Trade plan: {brief.symbol}"
        plan_parts = []
        if brief.entry_price is not None:
            plan_parts.append(f"entry {brief.entry_price}")
        if brief.stop_loss_price is not None:
            plan_parts.append(f"stop-loss {brief.stop_loss_price}")
        if brief.take_profit_price is not None:
            plan_parts.append(f"take-profit {brief.take_profit_price}")
        if brief.position_size is not None:
            plan_parts.append(f"position size {brief.position_size}")
        if brief.risk_reward_ratio is not None:
            plan_parts.append(f"risk/reward {brief.risk_reward_ratio}")

        if plan_parts:
            summary = (
                f"A trade plan for {brief.symbol} was generated "
                f"({', '.join(plan_parts)})."
            )
        else:
            summary = (
                f"Status is SUCCESS for {brief.symbol}, but no plan "
                f"fields were recorded on this brief."
            )
        return title, summary

    @staticmethod
    def _explain_blocked(brief: DecisionBrief, status: str) -> "tuple[str, str]":
        """Build the ("what the system decided") title/summary for any
        non-``SUCCESS`` (blocked/not-evaluated) brief.

        Args:
            brief: A ``DecisionBrief`` whose ``status`` is not
                ``"SUCCESS"``.
            status: ``brief.status``, already validated to be one of
                the seven non-``SUCCESS`` known statuses.

        Returns:
            A ``(title, summary)`` tuple built only from ``brief``'s
            own fields plus the fixed ``_STATUS_TITLES`` label for
            ``status``.
        """
        title = f"{_STATUS_TITLES[status]}: {brief.symbol}"
        summary = f"No trade plan was produced for {brief.symbol} (status: {status})."
        return title, summary