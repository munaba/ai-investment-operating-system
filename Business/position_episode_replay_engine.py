"""PositionEpisodeReplayEngine -- ACTIVATION 7 (performance per strategy).

Reconstructs, purely from the immutable ``Trade`` ledger, the list of
position episodes ("closed Position episode") a single ``account_id``
+ ``symbol``'s trades belong to -- the same episode boundaries
``Business.position_manager.PositionManager`` already enforces on the
real ``Position`` row (Activation 5.6 LOCKED episode rules: first
``BUY`` from zero quantity opens an episode, a ``SELL`` that brings
quantity to exactly ``0.0`` closes it).

This engine does not reimplement those boundary rules itself -- it
REPLAYS ``Business.trade_holding_period_engine.TradeHoldingPeriodEngine``
(its sole collaborator) to learn, per trade, whether that trade's
episode has closed (``holding_period_seconds is not None``) or is
still open (``None``). It only adds one thing on top of that replay:
grouping -- which trades belong to the same episode, and which trade
is that episode's *opening trade* ("trade yang membuka episode").

Never reads ``Position``, any repository, or the database. Never
mutates ``trades`` or any element within it. Never recomputes the
holding-period formula itself -- ``TradeHoldingPeriodEngine`` remains
the sole owner of that computation.

Public API: exactly one public method, ``replay()``, taking a single
``List[Trade]`` for one ``account_id`` + ``symbol`` pair, in
chronological (``executed_at`` ascending / ``trade_id`` ascending)
order -- mirrors ``TradeHoldingPeriodEngine.calculate()``'s own
contract exactly (no sorting/filtering/grouping across symbols or
accounts performed here; that remains the caller's responsibility).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from Business.trade_holding_period_engine import TradeHoldingPeriodEngine
from Database.models import Trade


@dataclass
class PositionEpisode:
    """One position episode reconstructed from a chronological
    ``List[Trade]`` for a single ``account_id`` + ``symbol``.

    Attributes:
        account_id: ``Trade.account_id`` shared by every trade in
            this episode.
        symbol: ``Trade.symbol`` shared by every trade in this
            episode.
        opening_trade: The trade that opened this episode (the first
            ``BUY`` from zero open quantity) -- "trade yang membuka
            episode".
        trades: Every trade belonging to this episode, in
            chronological order -- the opening ``BUY``, any
            additional ``BUY``s, any partial ``SELL``s, and (if
            ``closed``) the final closing ``SELL``.
        closed: ``True`` if a ``SELL`` brought this episode's
            quantity to exactly ``0.0`` (per
            ``TradeHoldingPeriodEngine``'s own replay), ``False`` if
            this episode is still open as of the last trade supplied.
    """

    account_id: str
    symbol: str
    opening_trade: Trade
    trades: List[Trade] = field(default_factory=list)
    closed: bool = False


class PositionEpisodeReplayEngine:
    """Groups a chronological ``List[Trade]`` (single account+symbol)
    into :class:`PositionEpisode` rows, by replaying
    ``TradeHoldingPeriodEngine``.

    Pure business object apart from its single, existing, already-
    LOCKED ``TradeHoldingPeriodEngine`` dependency (constructed with
    no argument of its own). No repository, no database, reads no
    ``Position`` -- mirrors
    ``Business.trade_attribution_engine.TradeAttributionEngine``'s own
    single-collaborator style.
    """

    def __init__(self, trade_holding_period_engine: TradeHoldingPeriodEngine) -> None:
        """Store the single collaborator this engine replays.

        Args:
            trade_holding_period_engine: The existing, LOCKED
                Activation 5.6 episode-boundary reconstructor. Never
                reimplemented here -- this engine only asks it,
                per trade, whether that trade's episode has closed.
        """
        self._trade_holding_period_engine = trade_holding_period_engine

    def replay(self, trades: List[Trade]) -> List[PositionEpisode]:
        """Reconstruct every position episode ``trades`` passes
        through, in chronological order.

        Does not mutate ``trades`` or any element within it. Does not
        read ``Position``, any repository, or the database.

        Args:
            trades: Every trade for exactly one ``account_id`` +
                ``symbol`` pair, in chronological (``executed_at``
                ascending) order -- the exact same contract
                ``TradeHoldingPeriodEngine.calculate()`` requires.
                Mixing more than one symbol or account into a single
                call produces a meaningless result -- this method
                performs no grouping/filtering to protect against
                that itself.

        Returns:
            One :class:`PositionEpisode` per episode observed in
            ``trades``, in chronological order (including a trailing
            still-open episode, if any, with ``closed=False``).
            Empty ``list`` for an empty ``trades`` list. A trade whose
            ``action`` is neither ``"BUY"`` nor ``"SELL"`` is skipped
            entirely (it belongs to no episode, mirroring
            ``TradeHoldingPeriodEngine``'s own silent-``None``
            treatment of it).
        """
        episodes: List[PositionEpisode] = []
        current_episode: PositionEpisode = None  # type: ignore[assignment]

        for index, trade in enumerate(trades):
            if trade.action not in ("BUY", "SELL"):
                continue

            if current_episode is None:
                current_episode = PositionEpisode(
                    account_id=trade.account_id,
                    symbol=trade.symbol,
                    opening_trade=trade,
                    trades=[],
                    closed=False,
                )

            current_episode.trades.append(trade)

            if trade.action == "SELL":
                # Replay TradeHoldingPeriodEngine over the prefix of
                # trades ending at (and including) this SELL, and ask
                # it whether *this exact SELL* closed its episode
                # (non-None holding_period_seconds). This is a true
                # replay, not a re-derivation of the LOCKED zero-
                # quantity boundary rule ourselves: the engine's own
                # ``calculate()`` is the sole place that rule lives.
                #
                # A prefix, rather than the full ``trades`` list, is
                # required here: once ``calculate()`` has processed
                # every trade, EVERY trade in a now-closed episode --
                # including a still-partial SELL that happened to
                # close later in that same call -- carries that
                # episode's shared, non-None holding_period_seconds
                # (see that engine's own module docstring: "Every
                # Trade belonging to that episode ... is assigned the
                # SAME holding_period_seconds value"). Checking the
                # full-list result for a partial SELL would therefore
                # misreport it as closing. A prefix ending exactly at
                # this SELL has no such later trade to leak a shared
                # value backwards, so it reports this SELL's own,
                # true, as-of-this-trade closed/open state.
                prefix_holding_periods = self._trade_holding_period_engine.calculate(
                    trades[: index + 1]
                )
                if prefix_holding_periods.get(trade.trade_id) is not None:
                    current_episode.closed = True
                    episodes.append(current_episode)
                    current_episode = None

        if current_episode is not None:
            episodes.append(current_episode)

        return episodes