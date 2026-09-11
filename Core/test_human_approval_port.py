"""HumanApprovalPort -- Activation 8.3 ("HUMAN APPROVAL ONLY").

Audit: what already existed, and what was actually missing
------------------------------------------------------------
Two independent "approval" mechanisms already existed in this
codebase before this Activation. Neither of them models an actual
human decision -- both resolve to a final verdict the instant they
are called, with no human ever consulted:

1. ``Core.approval`` / ``Core.approval_config.build_approval_port()``
   -- five ``Core.runtime.ApprovalPort`` implementations
   (``AlwaysApproveApprovalPort``, ``DenyAllApprovalPort``,
   ``ToolWhitelistApprovalPort``, ``ToolBlacklistApprovalPort``,
   ``PredicateApprovalPort``). Every one is synchronous and fully
   deterministic: ``check(event)`` always resolves to
   ``ApprovalOutcome.APPROVED`` or ``ApprovalOutcome.DENIED`` from a
   static policy/list/predicate decided in advance.
   ``Core.runtime.ApprovalOutcome`` already has a third member,
   ``PENDING`` (Runtime Spec v1.0 Gap 4: "Approved | Denied |
   Pending") -- but no ``ApprovalPort`` implementation in this
   codebase has ever returned it before this Activation. That is the
   exact gap this module closes.

   This module deliberately does NOT implement ``Core.runtime.
   ApprovalPort`` (the ``check(event: Event) -> ApprovalOutcome``
   Protocol) or touch ``Core/runtime.py``/``Core/approval.py`` at
   all. That Port is scoped to ``Core.event.Event``/
   ``EventType.INTENT`` inside the Runtime's own event-sourced
   Semantic Boundary, and ``Core.event.EventID`` is only ever
   constructible via ``EventStore.append()`` (see ``Core/event.py``)
   -- there is no legitimate way for an unrelated trading-domain
   caller to manufacture a real ``Event`` just to satisfy that
   Protocol's shape. Forcing that coupling would invent an
   integration nothing asked for. What this module *does* reuse is
   the one component that generalizes cleanly across both domains:
   the ``ApprovalOutcome`` enum itself (``APPROVED``/``DENIED``/
   ``PENDING``) -- imported, not redefined, so a human-approval
   outcome from this module is the exact same vocabulary as a
   Runtime approval outcome.

2. ``Orchestration.order_validation_skill.OrderValidationSkill`` --
   already reused by ``Business.dry_run_order_service.
   DryRunOrderService`` (Activation 8.2) for its "approval" pipeline
   stage. It is also fully automatic: a fixed four-rule chain
   evaluated purely from the request's own fields
   (``action``/``capital``). No human is ever consulted, and there is
   no path by which one could be -- the Skill takes no reviewer
   identity, no decision store, and has no "not yet decided" outcome
   in its four-rule vocabulary (APPROVED/HOLD/EXIT/REJECTED are all
   terminal, all computed).

3. ``Business.paper_trading_engine.PaperTradingEngine.submit_order()``
   gate 3 (``user_approval: bool``), audited by
   ``Repository.persistence.order_approval_repository.
   OrderApprovalRepository`` -- the closest existing thing to "human
   approval" in this codebase, and still not it. Gate 3's own LOCKED
   DECISION (see that module) states plainly that
   ``user_approval``/``signal_evidence`` are "supplied by the caller
   as plain parameters, not looked up by this engine from some
   evidence/approval store" -- i.e. gate 3 trusts whatever boolean the
   caller hands it at call time; it cannot distinguish "a human
   actually decided this" from "some code path passed ``True``". It
   has no ``PENDING`` outcome (nothing can be *asked* whether a human
   has decided yet, only told after the fact), and
   ``OrderApprovalRepository`` only ever records an approval
   *after* a real ``Order``/``Trade`` already exists and is fully
   committed -- structurally unusable for a not-yet-submitted dry-run
   preview, which by definition never creates either row (see
   ``Business.dry_run_order_service``). This Activation does not
   touch ``PaperTradingEngine``, gate 3, or
   ``OrderApprovalRepository`` -- paper trading stays exactly as
   LOCKED.

Conclusion: nothing in this codebase, before this Activation, could
ever gate an order on an actual human's explicit decision made ahead
of time and queryable as pending/decided. That is the one missing
piece added here -- nothing else. This module does not replace,
wrap, subclass, or modify any of the three mechanisms above.
``OrderValidationSkill``'s verdict remains exactly what it was
(Activation 8.2 kept it as the dry run's automated *recommendation*,
unchanged). ``HumanApprovalPort`` adds the human *decision* gate that
``Business.dry_run_order_service.DryRunOrderService`` now additionally
consults before it will ever report that an order is ready to submit
-- see that module for how the two are combined.

Scope (LOCKED for this Activation): no broker API, no network call,
no order execution, and no endpoint/UI assumption anywhere in this
module. It is a pure, in-memory decision registry: a dict from a
caller-chosen ``decision_key`` to an immutable ``HumanDecision``.
Nothing about *how* a human decision reaches ``record_decision()``
(CLI prompt, web form, chat command, ...) is decided here -- that is
future, out-of-scope surface work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from Core.runtime import ApprovalOutcome

__all__ = ["ApprovalOutcome", "HumanApprovalPort", "HumanDecision"]


@dataclass(frozen=True)
class HumanDecision:
    """One immutable, human-recorded approve/deny decision.

    Attributes:
        approved: ``True`` == approved, ``False`` == denied. There is
            no third value here -- "not yet decided" is represented
            by the *absence* of a ``HumanDecision`` for a given key,
            never by a value carried on one.
        reviewer: Optional free-text identity of the human who made
            this decision. Never validated, authenticated, or
            authorized by this module -- establishing who a reviewer
            actually is belongs to whatever future surface calls
            ``record_decision()``, not to this decision registry.
        note: Optional free-text reason the reviewer supplied.
    """

    approved: bool
    reviewer: Optional[str] = None
    note: Optional[str] = None


class HumanApprovalPort:
    """An approval gate that only ever reflects an explicit human
    decision -- never a computed/automatic one.

    In-memory only: a private ``dict[str, HumanDecision]``. No I/O, no
    database, no network, no broker call anywhere in this class -- it
    is a pure decision registry, nothing more.

    A decision, once recorded for a given ``decision_key``, is
    immutable: ``record_decision()`` raises ``ValueError`` on a second
    call for the same key rather than silently overwriting a human's
    prior call. This mirrors the append-only discipline
    ``Core.event_store.EventStore`` already uses for ``Event``\\ s in
    this codebase, applied here to a human decision instead.
    """

    #: Opaque policy_version, present for the same reason every
    #: ``Core.approval`` port declares one. This gate has exactly one
    #: policy -- "PENDING until a human explicitly decides" -- so the
    #: version is fixed, not configurable.
    version: str = "human-approval-v1"

    def __init__(self) -> None:
        self._decisions: Dict[str, HumanDecision] = {}

    def record_decision(
        self,
        decision_key: str,
        approved: bool,
        reviewer: Optional[str] = None,
        note: Optional[str] = None,
    ) -> HumanDecision:
        """Record a human's approve/deny decision for ``decision_key``.

        Args:
            decision_key: Caller-chosen identifier for the request
                being decided (e.g. a dry-run request id). Opaque to
                this class -- never parsed, normalized, or
                interpreted.
            approved: ``True`` to approve, ``False`` to deny.
            reviewer: Optional identity of the human deciding.
            note: Optional free-text reason.

        Returns:
            The ``HumanDecision`` just recorded.

        Raises:
            ValueError: If ``decision_key`` is empty/blank, or a
                decision was already recorded for it (decisions are
                immutable and cannot be overwritten).
        """
        if not isinstance(decision_key, str) or not decision_key.strip():
            raise ValueError("decision_key must be a non-empty string")

        if decision_key in self._decisions:
            raise ValueError(
                f"A human decision was already recorded for {decision_key!r}; "
                "decisions are immutable and cannot be overwritten."
            )

        decision = HumanDecision(approved=approved, reviewer=reviewer, note=note)
        self._decisions[decision_key] = decision
        return decision

    def get_decision(self, decision_key: str) -> Optional[HumanDecision]:
        """Return the recorded ``HumanDecision`` for ``decision_key``,
        or ``None`` if no human has decided yet.
        """
        return self._decisions.get(decision_key)

    def check(self, decision_key: str) -> ApprovalOutcome:
        """Return this gate's outcome for ``decision_key``.

        Args:
            decision_key: Same identifier passed to
                ``record_decision()``.

        Returns:
            ``ApprovalOutcome.PENDING`` if no human has recorded a
            decision yet for ``decision_key``; otherwise
            ``ApprovalOutcome.APPROVED`` or ``ApprovalOutcome.DENIED``
            per the recorded ``HumanDecision.approved`` value. Never
            raises -- an unknown ``decision_key`` is simply
            ``PENDING``, exactly like one nobody has looked at yet.
        """
        decision = self._decisions.get(decision_key)
        if decision is None:
            return ApprovalOutcome.PENDING
        return ApprovalOutcome.APPROVED if decision.approved else ApprovalOutcome.DENIED