"""TradeHoldingPeriodEngine -- Activation 5.6 STEP (LOCKED DECISION).

Computes, for every ``Trade`` belonging to a single ``account_id`` +
``symbol`` pair, the holding period of the *position episode* that
``Trade`` belongs to -- one of the five Activation 5.6 attribution
dimensions (``strategy``/``market``/``signal``/``holding_period``/
``risk_category``).

This engine does NOT read ``Position``, any repository, or the
database -- it never persists a "holding period" anywhere, never adds
a column/field to ``Position``/``Trade``, and never recomputes or
overrides anything ``Business.position_manager.PositionManager``
already owns (``quantity``/``average_price``/``realized_pnl``/
``status`` are untouched, not even read). It is a read-only, in-memory
replay of the exact same episode boundaries ``PositionManager``
already enforces on the real ``Position`` row -- built purely from the
immutable ``Trade`` ledger, for reporting/attribution purposes only.

LOCKED episode rules (Activation 5.6, verbatim from the roadmap):

    * the first ``BUY`` (from zero open quantity) opens an episode;
    * an additional ``BUY`` while quantity is already open does NOT
      reset the episode's entry time;
    * a partial ``SELL`` (quantity remains > 0 afterward) does NOT
      close the episode;
    * a ``SELL`` that brings quantity to exactly ``0.0`` closes the
      episode;
    * a ``BUY`` after the prior episode closed starts a brand new
      episode;
    * the holding period of a position that has not yet closed is
      ``None`` (\"unavailable\") -- never fabricated as ``0.0`` or any
      other placeholder.

LOCKED formula, once an episode closes:

    holding_period_seconds = (
        closing_SELL.executed_at - opening_BUY.executed_at
    ).total_seconds()

Every ``Trade`` belonging to that episode (the opening ``BUY``, any
additional ``BUY``s, any partial ``SELL``s, and the final closing
``SELL``) is assigned the SAME ``holding_period_seconds`` value once
the episode closes -- the holding period is a property of the
episode, not of any single trade within it. A trade belonging to a
still-open episode is assigned ``None``.

Public API (LOCKED): exactly one public method, ``calculate()``,
taking a single ``List[Trade]`` for one ``account_id`` + ``symbol``
pair, in chronological (``executed_at`` ascending) order -- this
engine performs no sorting, filtering, or grouping across symbols/
accounts itself; that is the caller's responsibility (mirrors
``Business.trade_statistics_engine.TradeStatisticsEngine`` taking the
list exactly as given).

Constructor (LOCKED): ``TradeHoldingPeriodEngine()`` -- no dependency,
mirrors every other Sprint 6 / Activation 5.x engine.

``executed_at`` timestamps are parsed with ``datetime.fromisoformat``
-- the exact inverse of the ``datetime.now(timezone.utc).isoformat()``
format every write path in this project already uses (see
``Database.models.Trade``/``Order``/``Position`` field docstrings).
No new timestamp format, no new parsing library.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from Database.models import Trade

#: LOCKED domain values (mirrors ``Business.position_manager.
#: _VALID_ACTIONS``) -- kept as a local tuple rather than importing a
#: private name from another module, same convention every other
#: engine in this project already follows.
_ACTION_BUY = "BUY"
_ACTION_SELL = "SELL"


class TradeHoldingPeriodEngine:
    """Computes per-``trade_id`` holding periods from a single
    account+symbol's ``List[Trade]``.

    Pure business object -- no dependency, no repository, no
    database, no composition-root wiring beyond being constructed and
    handed to whatever caller assembles attribution (mirrors every
    other Sprint 6 / Activation 5.x engine): never exposed on
    ``ApplicationGraph`` on its own, always used through
    ``Business.trade_attribution_service.TradeAttributionService``.
    """

    def __init__(self) -> None:
        """No dependency of any kind."""

    def calculate(self, trades: List[Trade]) -> Dict[int, Optional[float]]:
        """Compute the holding period (in seconds) of the position
        episode each trade in ``trades`` belongs to.

        Does not mutate ``trades`` or any element within it. Does not
        read ``Position``, any repository, or the database.

        Args:
            trades: Every trade for exactly one ``account_id`` +
                ``symbol`` pair, in chronological (``executed_at``
                ascending) order. Mixing more than one symbol or
                account into a single call produces a meaningless
                result -- this method performs no grouping/filtering
                to protect against that itself, exactly like
                ``TradeStatisticsEngine.calculate()`` performs no
                sorting.

        Returns:
            A ``dict`` mapping every ``trade.trade_id`` in ``trades``
            to either the closed episode's holding period in seconds
            (a ``float``, shared by every trade in that episode), or
            ``None`` if that trade's episode has not closed yet (or
            the trade's ``action`` is neither ``"BUY"`` nor
            ``"SELL"``). Empty ``dict`` for an empty ``trades`` list.
        """
        result: Dict[int, Optional[float]] = {}

        quantity_open = 0.0
        episode_opened_at: Optional[str] = None
        episode_trade_ids: List[int] = []

        for trade in trades:
            if trade.action == _ACTION_BUY:
                if quantity_open == 0.0:
                    episode_opened_at = trade.executed_at
                    episode_trade_ids = []
                quantity_open += trade.quantity
                episode_trade_ids.append(trade.trade_id)
                result[trade.trade_id] = None

            elif trade.action == _ACTION_SELL:
                episode_trade_ids.append(trade.trade_id)
                quantity_open -= trade.quantity

                if quantity_open == 0.0:
                    holding_period_seconds = (
                        _parse(trade.executed_at) - _parse(episode_opened_at)
                    ).total_seconds()
                    for episode_trade_id in episode_trade_ids:
                        result[episode_trade_id] = holding_period_seconds
                    quantity_open = 0.0
                    episode_opened_at = None
                    episode_trade_ids = []
                else:
                    result[trade.trade_id] = None

            else:
                # Unknown action: not a BUY/SELL episode participant.
                # Never raises here (mirrors TradeStatisticsEngine's
                # own silent-skip-from-counting behavior for anything
                # outside its two known actions) -- holding period is
                # simply unavailable for it.
                result[trade.trade_id] = None

        return result


def _parse(timestamp: str) -> datetime:
    """Parse an ISO-8601 ``executed_at`` string into a ``datetime``.

    The exact inverse of ``datetime.now(timezone.utc).isoformat()``,
    the one and only timestamp format this project's write paths ever
    produce (see ``Database.models`` field docstrings) -- no other
    format is supported or guarded against.
    """
    return datetime.fromisoformat(timestamp)
