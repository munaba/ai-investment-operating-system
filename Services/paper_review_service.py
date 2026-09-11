"""``PaperReviewService`` -- Phase G Task 4 ("Continuous Review Inputs").

The smallest additive review layer needed to trace, for one account:

    decision (JournalEntry) -> brief (DecisionBrief)
        -> approval (BriefApproval) -> order (Order) -> trade (Trade)
        -> price/valuation (PortfolioSnapshot.valuation_status)

and to produce review inputs grouped by strategy, by market regime,
and by decision adherence.

This service invents nothing. It reuses exactly these existing,
LOCKED components -- read-only, every one of them:

    * ``Repository.persistence.journal_repository.JournalRepository``
      -- the one and only source of TAKE/SKIP/WAIT decisions
      (``Services.journal_service.JournalService`` already owns
      writing them; this service never writes a ``JournalEntry``).
    * ``Repository.persistence.decision_brief_repository.
      DecisionBriefRepository`` -- the brief each decision references.
    * ``Repository.persistence.brief_approval_repository.
      BriefApprovalRepository`` -- the one place a brief's link to a
      real paper order/trade is recorded
      (``Services.brief_approval_service.BriefApprovalService`` owns
      writing it; this service never writes a ``BriefApproval``).
    * ``Repository.persistence.order_repository.OrderRepository`` /
      ``Repository.persistence.trade_repository.TradeRepository`` --
      the real, already-persisted order/trade a linked brief resulted
      in.
    * ``Business.strategy_performance_service.
      StrategyPerformanceService`` -- the one and only per-strategy
      performance engine. This service never recomputes a strategy
      P/L statistic itself.
    * ``Business.market_regime_attribution_service.
      MarketRegimeAttributionService`` -- the one and only per-regime
      performance engine. This service never recomputes a regime P/L
      statistic itself.
    * ``Repository.persistence.portfolio_snapshot_repository.
      PortfolioSnapshotRepository`` -- the one place a portfolio-level
      ``valuation_status`` (``"FRESH"``/``"STALE"``, Phase G Task 3) is
      already recorded. This service never fetches a market price,
      never recomputes freshness, and never invents one.

Read-only for this task (Phase G Task 4 instruction, LOCKED): this
service never creates, updates, or cancels a ``JournalEntry``,
``DecisionBrief``, ``BriefApproval``, ``Order``, ``Trade``,
``Position``, or ``PortfolioSnapshot``. It holds no reference to
``PaperTradingEngine``/``OrderLifecycleService``/``ExecutionService``
and calls none of them -- no paper execution, no broker/live
execution, nothing automatic.

Every metric on :class:`PaperReviewResult` is either derived from a
real, already-persisted record (with the source id/timestamp
preserved so it can be traced back), or is one of the two explicit
sentinels below when it genuinely cannot be derived -- never a
fabricated number:

    * :data:`NOT_AVAILABLE` -- the collaborator needed to compute this
      dimension was not supplied to this service (e.g. no
      ``strategy_performance_service`` was injected), or the
      dimension structurally does not apply to a given decision (e.g.
      adherence for a SKIP/WAIT, which never results in a paper
      order).
    * :data:`INSUFFICIENT_DATA` -- the collaborator *was* supplied but
      the real, persisted data needed to compute this dimension does
      not exist yet (e.g. an ACCEPTED TAKE whose outcome has not been
      recorded yet).

Restart-safe by construction: every read goes through a repository
freshly queried on each call -- nothing is cached across calls or
across a process restart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union

from Business.market_regime_attribution_service import MarketRegimeAttributionService
from Business.market_regime_performance_engine import MarketRegimePerformanceStatistics
from Business.strategy_performance_service import StrategyPerformanceService
from Business.strategy_performance_engine import StrategyPerformanceStatistics
from Core.exceptions import ValidationError
from Database.models import JournalEntry
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.brief_approval_repository import BriefApprovalRepository
from Repository.persistence.decision_brief_repository import DecisionBriefRepository
from Repository.persistence.journal_repository import JournalRepository
from Repository.persistence.order_repository import OrderRepository
from Repository.persistence.portfolio_snapshot_repository import (
    PortfolioSnapshotRepository,
)
from Repository.persistence.trade_repository import TradeRepository
from Services.journal_service import DECISION_SKIP, DECISION_TAKE, DECISION_WAIT

#: Emitted whenever a review dimension's required collaborator was
#: never injected into this service -- distinct from
#: :data:`INSUFFICIENT_DATA`, which means the collaborator exists but
#: the underlying persisted data does not (yet).
NOT_AVAILABLE = "NOT_AVAILABLE"

#: Emitted whenever a review dimension's collaborator *is* available
#: but the real, persisted records needed to compute it for this
#: particular decision do not exist yet.
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

#: Per-decision adherence outcomes (Phase G Task 4's own vocabulary --
#: not reused from any prior phase, since no prior phase computes
#: "did the person follow through on their own TAKE/SKIP/WAIT call").
#:
#: ``FOLLOWED``: an ACCEPTED TAKE that really was linked (via
#:     ``BriefApproval``) to a real paper order/trade, AND that trade's
#:     outcome has since been closed and recorded on the same
#:     ``JournalEntry`` -- the full decision -> ... -> outcome chain
#:     exists in persisted records.
#: ``NOT_EXECUTED``: an ACCEPTED TAKE that was never linked to any
#:     paper order/trade -- the person decided to TAKE but the
#:     decision was never actually carried out.
#: ``OUTCOME_PENDING``: an ACCEPTED TAKE that *was* linked to a real
#:     paper order/trade, but no outcome has been recorded on the
#:     journal entry yet (``outcome_status is None``) -- adherence is
#:     not yet knowable, not "not adhered".
#: ``NOT_APPLICABLE``: SKIP, WAIT, or a RISK_REJECTED TAKE -- none of
#:     these can ever result in a paper order by design (see
#:     ``Business.risk_ledger_policy.RiskLedgerPolicy`` /
#:     ``Services.brief_approval_service.BriefApprovalService``), so
#:     "did they follow through" does not apply.
ADHERENCE_FOLLOWED = "FOLLOWED"
ADHERENCE_NOT_EXECUTED = "NOT_EXECUTED"
ADHERENCE_OUTCOME_PENDING = "OUTCOME_PENDING"
ADHERENCE_NOT_APPLICABLE = "NOT_APPLICABLE"

_RISK_POLICY_ACCEPTED = "ACCEPTED"

#: ``PortfolioSnapshot.valuation_status`` values already written by
#: Phase G Task 3's ``UnrealizedPnLEngine``/``PortfolioSnapshotService``
#: -- reused verbatim, never redefined here.
_VALUATION_FRESH = "FRESH"
_VALUATION_STALE = "STALE"


@dataclass(frozen=True)
class DecisionTrace:
    """One reviewed decision's full, traceable chain -- every id and
    timestamp on this row points at a real, persisted record (or is
    genuinely ``None`` because that step of the chain never happened),
    never a summary that loses the ability to look the source row up
    again.

    ``entry_id``/``decided_at`` trace back to ``JournalEntry``;
    ``brief_id`` to ``DecisionBrief``; ``order_id``/``trade_id`` (when
    not ``None``) to the real ``Order``/``Trade`` a ``BriefApproval``
    link resulted in.
    """

    entry_id: int
    brief_id: int
    symbol: str
    decision: str
    decided_at: str
    risk_policy_status: str
    outcome_status: Optional[str]
    approved_paper: bool
    order_id: Optional[int]
    trade_id: Optional[int]
    adherence: str


@dataclass(frozen=True)
class ValuationFreshnessCounts:
    """Fresh/stale/unavailable ``PortfolioSnapshot.valuation_status``
    counts for the account and review period, sourced verbatim from
    already-persisted ``PortfolioSnapshot`` rows (Phase G Task 3).

    ``status`` is :data:`NOT_AVAILABLE` (with all three counts left at
    ``0``) whenever no ``PortfolioSnapshotRepository`` was supplied to
    this service at all -- distinguishing "we didn't look" from "we
    looked and there were genuinely zero snapshots in range" (the
    latter is reported as ``status == "AVAILABLE"`` with all-zero
    counts, since that is itself a real, honest finding).
    """

    status: str
    fresh: int = 0
    stale: int = 0
    unavailable: int = 0


@dataclass(frozen=True)
class PaperReviewResult:
    """Typed, frozen Phase G Task 4 continuous-review result.

    Every field is either a plain count/derived-metric over real,
    already-persisted records, a tuple of :class:`DecisionTrace` rows
    preserving source ids/timestamps for full traceability, or one of
    the two explicit sentinels (:data:`NOT_AVAILABLE`/
    :data:`INSUFFICIENT_DATA`) documented on each field below. Nothing
    here is fabricated.
    """

    account_id: str
    generated_at: str
    period_since: Optional[str]
    period_until: Optional[str]

    total_reviewed_decisions: int
    take_count: int
    skip_count: int
    wait_count: int

    #: Count of reviewed decisions whose ``brief_id`` has a real,
    #: persisted ``BriefApproval`` link (i.e. actually resulted in a
    #: paper order/trade) -- not merely "decision == TAKE".
    approved_paper_count: int

    #: Count of distinct, real ``Order`` rows traced back to from the
    #: reviewed decisions via their ``BriefApproval`` link.
    linked_order_count: int

    #: Count of distinct, real ``Trade`` rows traced back to from
    #: those same linked orders (via ``TradeRepository.list_by_order``
    #: -- never assumed to be exactly one trade per order).
    linked_trade_count: int

    #: Full per-decision traceability chain, one row per reviewed
    #: ``JournalEntry``, ordered by ``entry_id`` ascending.
    decision_traces: Tuple[DecisionTrace, ...]

    #: ``StrategyPerformanceService.get_performance_by_strategy``'s
    #: verbatim output, or the literal string :data:`NOT_AVAILABLE`
    #: when no ``strategy_performance_service`` was injected into this
    #: service.
    strategy_breakdown: Union[Dict[str, StrategyPerformanceStatistics], str]

    #: ``MarketRegimeAttributionService.get_performance_by_regime``'s
    #: verbatim output, or the literal string :data:`NOT_AVAILABLE`
    #: when no ``market_regime_attribution_service`` was injected into
    #: this service.
    market_regime_breakdown: Union[Dict[str, MarketRegimePerformanceStatistics], str]

    #: Count of reviewed decisions per :data:`ADHERENCE_FOLLOWED` /
    #: :data:`ADHERENCE_NOT_EXECUTED` / :data:`ADHERENCE_OUTCOME_PENDING`
    #: / :data:`ADHERENCE_NOT_APPLICABLE` -- the same four labels
    #: already present, per-decision, on each ``DecisionTrace.adherence``.
    adherence_summary: Dict[str, int]

    #: Fresh/stale/unavailable ``PortfolioSnapshot`` counts for this
    #: account and period.
    valuation_freshness: ValuationFreshnessCounts


class PaperReviewService:
    """Builds one :class:`PaperReviewResult` for a real ``account_id``
    from real, already-persisted data.

    Constructor injection only, mirroring ``JournalService``/
    ``BriefApprovalService``: every repository/service collaborator is
    supplied by the caller, never constructed here. The strategy,
    market-regime, and valuation-freshness collaborators are all
    ``Optional`` -- Phase G Task 4's own instruction is "explicit
    NOT_AVAILABLE where a metric cannot be derived", so a caller that
    genuinely has none of these wired up yet still gets a complete,
    honest result rather than an exception. Stateless beyond these
    collaborators -- safe to reuse across calls, and restart-safe
    since nothing is cached.
    """

    def __init__(
        self,
        account_repository: AccountRepository,
        journal_repository: JournalRepository,
        decision_brief_repository: DecisionBriefRepository,
        brief_approval_repository: BriefApprovalRepository,
        order_repository: OrderRepository,
        trade_repository: TradeRepository,
        strategy_performance_service: Optional[StrategyPerformanceService] = None,
        market_regime_attribution_service: Optional[MarketRegimeAttributionService] = None,
        portfolio_snapshot_repository: Optional[PortfolioSnapshotRepository] = None,
    ) -> None:
        self._account_repository = account_repository
        self._journal_repository = journal_repository
        self._decision_brief_repository = decision_brief_repository
        self._brief_approval_repository = brief_approval_repository
        self._order_repository = order_repository
        self._trade_repository = trade_repository
        self._strategy_performance_service = strategy_performance_service
        self._market_regime_attribution_service = market_regime_attribution_service
        self._portfolio_snapshot_repository = portfolio_snapshot_repository

    def review(
        self,
        account_id: str,
        *,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> PaperReviewResult:
        """Build one continuous-review snapshot for ``account_id``.

        Purely observational: no repository is ever written to.

        Args:
            account_id: The real account this review is scoped to
                (used for the strategy/market-regime/valuation-
                freshness dimensions -- every underlying read for
                those three is filtered to this ``account_id``, same
                convention as ``StrategyPerformanceService``/
                ``MarketRegimeAttributionService``). Reviewed
                decisions themselves (``JournalEntry`` rows) are not
                account-scoped at the schema level (Phase C's
                personal risk ledger is account-agnostic by design),
                so every ``JournalEntry`` in the period is reviewed
                regardless of which account (if any) its eventual
                paper trade landed in.
            since: Optional inclusive ISO-8601 lower bound on
                ``JournalEntry.decided_at`` (string comparison, same
                convention ``JournalService._compute_stats`` already
                uses for its own ``today`` filter). ``None`` means "no
                lower bound".
            until: Optional exclusive ISO-8601 upper bound on
                ``JournalEntry.decided_at``. ``None`` means "no upper
                bound".

        Returns:
            A fully-populated, frozen :class:`PaperReviewResult`.

        Raises:
            ValidationError: If ``account_id`` does not exist.
            RepositoryError: If any underlying repository call fails.
        """
        account = self._account_repository.get_by_id(account_id)
        if account is None:
            raise ValidationError(
                f"Cannot build paper review: account {account_id} not found",
                details={"account_id": account_id},
            )

        entries = self._reviewed_entries(since, until)

        take_count = sum(1 for e in entries if e.decision == DECISION_TAKE)
        skip_count = sum(1 for e in entries if e.decision == DECISION_SKIP)
        wait_count = sum(1 for e in entries if e.decision == DECISION_WAIT)

        traces: List[DecisionTrace] = []
        adherence_summary: Dict[str, int] = {
            ADHERENCE_FOLLOWED: 0,
            ADHERENCE_NOT_EXECUTED: 0,
            ADHERENCE_OUTCOME_PENDING: 0,
            ADHERENCE_NOT_APPLICABLE: 0,
        }
        linked_order_ids: List[int] = []

        for entry in entries:
            approval = self._brief_approval_repository.get_by_brief_id(entry.brief_id)
            approved_paper = approval is not None
            order_id = approval.order_id if approval is not None else None
            trade_id = approval.trade_id if approval is not None else None

            if approved_paper:
                linked_order_ids.append(order_id)  # type: ignore[arg-type]

            adherence = self._resolve_adherence(entry, approved_paper)
            adherence_summary[adherence] += 1

            traces.append(
                DecisionTrace(
                    entry_id=entry.entry_id,
                    brief_id=entry.brief_id,
                    symbol=entry.symbol,
                    decision=entry.decision,
                    decided_at=entry.decided_at,
                    risk_policy_status=entry.risk_policy_status,
                    outcome_status=entry.outcome_status,
                    approved_paper=approved_paper,
                    order_id=order_id,
                    trade_id=trade_id,
                    adherence=adherence,
                )
            )

        approved_paper_count = sum(1 for t in traces if t.approved_paper)
        linked_trade_count = self._count_linked_trades(linked_order_ids)

        return PaperReviewResult(
            account_id=account_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            period_since=since,
            period_until=until,
            total_reviewed_decisions=len(entries),
            take_count=take_count,
            skip_count=skip_count,
            wait_count=wait_count,
            approved_paper_count=approved_paper_count,
            linked_order_count=len(set(linked_order_ids)),
            linked_trade_count=linked_trade_count,
            decision_traces=tuple(traces),
            strategy_breakdown=self._strategy_breakdown(account_id),
            market_regime_breakdown=self._market_regime_breakdown(account_id),
            adherence_summary=adherence_summary,
            valuation_freshness=self._valuation_freshness(account_id, since, until),
        )

    # -- internal helpers ------------------------------------------------

    def _reviewed_entries(
        self, since: Optional[str], until: Optional[str]
    ) -> List[JournalEntry]:
        """Real, already-persisted ``JournalEntry`` rows in
        ``[since, until)``, ordered by ``entry_id`` ascending.

        Pure in-memory filter over ``JournalRepository.list_all()`` --
        mirrors ``JournalService._compute_stats``'s own string-prefix
        comparison convention for ISO-8601 timestamps rather than
        introducing a second, parallel date-range query on the
        repository.
        """
        entries = sorted(self._journal_repository.list_all(), key=lambda e: e.entry_id)
        if since is not None:
            entries = [e for e in entries if e.decided_at >= since]
        if until is not None:
            entries = [e for e in entries if e.decided_at < until]
        return entries

    @staticmethod
    def _resolve_adherence(entry: JournalEntry, approved_paper: bool) -> str:
        """Per-decision adherence -- see the four labels documented
        above ``ADHERENCE_FOLLOWED``. Only a TAKE that the
        ``RiskLedgerPolicy`` genuinely ``ACCEPTED`` was ever eligible
        to become a real paper order in the first place (see
        ``Services.brief_approval_service.BriefApprovalService`` --
        approval is never inferred), so every other decision is
        :data:`ADHERENCE_NOT_APPLICABLE`.
        """
        if entry.decision != DECISION_TAKE or entry.risk_policy_status != _RISK_POLICY_ACCEPTED:
            return ADHERENCE_NOT_APPLICABLE
        if not approved_paper:
            return ADHERENCE_NOT_EXECUTED
        if entry.outcome_status is None:
            return ADHERENCE_OUTCOME_PENDING
        return ADHERENCE_FOLLOWED

    def _count_linked_trades(self, linked_order_ids: List[int]) -> int:
        """Real ``Trade`` count traced back from every distinct linked
        ``order_id`` -- never assumed to be exactly one trade per
        order (an order could, in principle, have more than one fill
        recorded against it).
        """
        total = 0
        for order_id in set(linked_order_ids):
            total += len(self._trade_repository.list_by_order(order_id))
        return total

    def _strategy_breakdown(
        self, account_id: str
    ) -> Union[Dict[str, StrategyPerformanceStatistics], str]:
        if self._strategy_performance_service is None:
            return NOT_AVAILABLE
        return self._strategy_performance_service.get_performance_by_strategy(account_id)

    def _market_regime_breakdown(
        self, account_id: str
    ) -> Union[Dict[str, MarketRegimePerformanceStatistics], str]:
        if self._market_regime_attribution_service is None:
            return NOT_AVAILABLE
        return self._market_regime_attribution_service.get_performance_by_regime(account_id)

    def _valuation_freshness(
        self, account_id: str, since: Optional[str], until: Optional[str]
    ) -> ValuationFreshnessCounts:
        if self._portfolio_snapshot_repository is None:
            return ValuationFreshnessCounts(status=NOT_AVAILABLE)

        snapshots = self._portfolio_snapshot_repository.list_by_account(account_id)
        if since is not None:
            snapshots = [s for s in snapshots if s.timestamp >= since]
        if until is not None:
            snapshots = [s for s in snapshots if s.timestamp < until]

        fresh = sum(1 for s in snapshots if s.valuation_status == _VALUATION_FRESH)
        stale = sum(1 for s in snapshots if s.valuation_status == _VALUATION_STALE)
        unavailable = sum(1 for s in snapshots if s.valuation_status is None)

        return ValuationFreshnessCounts(
            status="AVAILABLE",
            fresh=fresh,
            stale=stale,
            unavailable=unavailable,
        )