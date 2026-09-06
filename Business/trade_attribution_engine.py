"""TradeAttributionEngine -- Activation 5.6 (LOCKED DECISION).

Computes a single :class:`TradeAttribution` per ``Trade``, per the
Activation 5.6 LOCKED DECISION domain rules below. This is the ONE
place that assembles the five attribution dimensions -- it never
invents a sixth, never persists anything, and never recomputes a
value another already-LOCKED component owns:

    strategy:
        ``"recommendation_following"`` if ``Order.analysis_snapshot_id``
        is available (not ``None``), else ``"manual"``.
        ``strategy_version`` is the literal string ``"1"``.
        NOT a new ``Strategy`` entity -- ``strategy``/
        ``strategy_version`` are plain string fields on
        :class:`TradeAttribution`, derived, never persisted.

    market:
        ``Account.asset_class``, read verbatim -- never recomputed,
        never a new field on any entity.

    signal:
        ``RankingSnapshot.snapshot_id``, resolved through ``Order.
        analysis_snapshot_id`` -- see
        ``Business.trade_attribution_service.TradeAttributionService``
        for the actual resolution (a real
        ``SnapshotRepository.get_by_id()`` lookup, so an
        ``analysis_snapshot_id`` that does not point at a real,
        still-existing ``RankingSnapshot`` row resolves to ``None``,
        never a fabricated/blindly-copied id). This engine itself
        only places whatever already-resolved ``Optional[int]`` its
        caller supplies into ``signal_snapshot_id`` -- it does not
        call ``SnapshotRepository`` itself (this engine has no
        repository dependency of any kind, mirroring every other
        Sprint 6 / Activation 5.x engine).

    holding_period:
        ``Business.trade_holding_period_engine.
        TradeHoldingPeriodEngine`` is the sole owner of this
        computation (LOCKED DECISION, Activation 5.6) -- this engine
        never reimplements it, and only places the already-computed
        ``Optional[float]`` seconds value its caller supplies into
        ``holding_period_seconds``.

    risk_category:
        ``Orchestration.decision_policy.DecisionPolicy.risk_level``
        -- the existing, LOCKED Stage L20A policy map
        (``BUY`` -> ``"NORMAL"``, ``SELL`` -> ``"HIGH"``), called here
        with a minimal ``action``-only stand-in for its ``decision``
        parameter (``DecisionPolicy.apply()`` only ever reads
        ``decision.action`` and, optionally, ``decision.confidence``
        via ``getattr(..., 0.0)`` -- see its own module docstring).
        NOT a new risk engine: ``DecisionPolicy`` itself is untouched,
        called through its existing, unmodified public ``apply()``
        method exactly as any other caller would.

No pandas, no numpy, no SQL, no mutation of any argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional

from Database.models import Order, Trade
from Orchestration.decision_policy import DecisionPolicy

#: LOCKED domain values for ``TradeAttribution.strategy`` -- exactly
#: two, per the Activation 5.6 LOCKED DECISION. Not a new enum/domain
#: table -- plain string constants, mirroring every other LOCKED
#: string constant already in this project (e.g.
#: ``Business.position_manager._STATUS_OPEN``/``_STATUS_CLOSED``).
STRATEGY_RECOMMENDATION_FOLLOWING = "recommendation_following"
STRATEGY_MANUAL = "manual"

#: LOCKED: ``strategy_version`` is always this literal string for
#: every attribution this engine produces at Activation 5.6. Not
#: derived from anywhere else -- there is no versioned ``Strategy``
#: entity in this codebase (deliberately not created by this
#: Activation).
STRATEGY_VERSION = "1"


@dataclass
class TradeAttribution:
    """The five-dimension Activation 5.6 attribution for one ``Trade``,
    plus the identifying fields needed to trace it straight back to
    that ``Trade`` (and, through ``Trade.order_id``, its ``Order``).

    Every field beyond the five LOCKED dimensions
    (``strategy``/``strategy_version``, ``market``, ``signal_snapshot_id``,
    ``holding_period_seconds``, ``risk_category``) exists only for
    traceability back to the source ``Trade`` -- no additional metric,
    no re-derivation of anything ``Trade``/``Position``/``Order``
    already own.

    Attributes:
        trade_id: The ``Trade.trade_id`` this attribution describes.
            Traceability anchor back to the real ``Trade`` row.
        order_id: ``Trade.order_id`` -- traceability anchor back to
            the real ``Order`` row this trade filled.
        account_id: ``Trade.account_id``, verbatim.
        symbol: ``Trade.symbol``, verbatim.
        action: ``Trade.action`` (``"BUY"``/``"SELL"``), verbatim --
            not itself one of the five dimensions, but needed to
            interpret ``risk_category`` (which is a direct function of
            this).
        strategy: ``"recommendation_following"`` or ``"manual"``, per
            the LOCKED DECISION above.
        strategy_version: Always ``"1"`` (LOCKED).
        market: ``Account.asset_class``, verbatim.
        signal_snapshot_id: The resolved ``RankingSnapshot.
            snapshot_id`` this trade's order was placed against, or
            ``None`` if the order carried no ``analysis_snapshot_id``
            (a manual/no-signal order) or that id no longer resolves
            to a real snapshot row.
        holding_period_seconds: The closed position episode's holding
            period in seconds (``closing SELL.executed_at - opening
            BUY.executed_at``), or ``None`` if this trade's episode
            has not closed yet -- never fabricated.
        risk_category: ``"NORMAL"`` for ``BUY``, ``"HIGH"`` for
            ``SELL`` -- straight off ``DecisionPolicy.risk_level``.
    """

    trade_id: int
    order_id: int
    account_id: str
    symbol: str
    action: str
    strategy: str
    strategy_version: str
    market: str
    signal_snapshot_id: Optional[int]
    holding_period_seconds: Optional[float]
    risk_category: str


class TradeAttributionEngine:
    """Assembles one :class:`TradeAttribution` per ``Trade`` from
    already-resolved inputs.

    Pure business object apart from its single, existing,
    already-LOCKED ``DecisionPolicy`` dependency (constructed with no
    argument of its own -- see ``Orchestration.decision_policy.
    DecisionPolicy``). No repository, no database, reads no
    ``Position`` -- every value beyond ``risk_category`` is supplied
    by the caller, already resolved.
    """

    def __init__(self, decision_policy: DecisionPolicy) -> None:
        """Store the single collaborator this engine calls for
        ``risk_category``.

        Args:
            decision_policy: The existing, LOCKED ``DecisionPolicy``
                (Stage L20A). Never a new/second risk-mapping
                component -- this is the one and only place Activation
                5.6 derives ``risk_category`` from.
        """
        self._decision_policy = decision_policy

    def calculate(
        self,
        trade: Trade,
        order: Order,
        market: str,
        signal_snapshot_id: Optional[int],
        holding_period_seconds: Optional[float],
    ) -> TradeAttribution:
        """Assemble the :class:`TradeAttribution` for a single
        ``trade``.

        Does not mutate ``trade`` or ``order``. Performs no repository
        or database access -- ``market``, ``signal_snapshot_id``, and
        ``holding_period_seconds`` must already be resolved by the
        caller (see ``Business.trade_attribution_service.
        TradeAttributionService``, the sole production caller).

        Args:
            trade: The ``Trade`` this attribution describes. Its
                ``trade_id``/``order_id``/``account_id``/``symbol``/
                ``action`` are copied verbatim.
            order: The ``Order`` that produced ``trade`` (i.e.
                ``order.order_id == trade.order_id``). Only
                ``order.analysis_snapshot_id`` is read, to decide
                ``strategy`` -- never validated against ``trade``
                here (the caller is responsible for passing the
                matching ``Order``).
            market: The already-resolved ``Account.asset_class`` for
                ``trade.account_id``. Placed into ``market`` verbatim.
            signal_snapshot_id: The already-resolved
                ``RankingSnapshot.snapshot_id`` (or ``None``) -- see
                the module docstring's ``signal`` section for how the
                caller is expected to resolve this.
            holding_period_seconds: The already-computed holding
                period (or ``None``) from
                ``TradeHoldingPeriodEngine.calculate()``.

        Returns:
            The assembled :class:`TradeAttribution`.
        """
        strategy = (
            STRATEGY_RECOMMENDATION_FOLLOWING
            if order.analysis_snapshot_id is not None
            else STRATEGY_MANUAL
        )

        policy_result = self._decision_policy.apply(
            SimpleNamespace(action=trade.action)
        )

        return TradeAttribution(
            trade_id=trade.trade_id,
            order_id=trade.order_id,
            account_id=trade.account_id,
            symbol=trade.symbol,
            action=trade.action,
            strategy=strategy,
            strategy_version=STRATEGY_VERSION,
            market=market,
            signal_snapshot_id=signal_snapshot_id,
            holding_period_seconds=holding_period_seconds,
            risk_category=policy_result.risk_level,
        )
