"""UnrealizedPnLEngine -- Activation 3.7 STEP 4.

Additive-only. This is the SOLE business owner of unrealized P/L, per
the Activation 3.7 STEP 3 audit's findings:

* ``PositionManager`` is the write-path (applies an already-created
  ``Trade`` onto its ``Position``, once per trade) -- unrealized P/L
  must reflect the *current* market price at query time, independent
  of whether a trade just happened, so it cannot live there. This
  module never imports ``Business.position_manager`` and never
  mutates a ``Position`` in any way.
* ``PositionPerformanceEngine`` is a pure aggregator with no
  dependency of any kind (see its own docstring: "no dependency, no
  repository, no database") -- it cannot fetch a market price, and
  its ``PositionPerformanceStatistics`` output is LOCKED to exactly
  eight fields that are all derived from ``Position.realized_pnl``.
  It stays a potential *consumer* of a value this engine computes; it
  is never asked to compute one itself, and this module does not
  import or modify it.

Source of Truth (LOCKED for this Activation): this module is the ONE
and ONLY place in the codebase that computes ``unrealized_pnl``. No
other file computes this formula -- not ``PositionPerformanceEngine``,
not ``PerformanceSummaryService``, not any ``Repository``, not any
``Tool``, not ``PaperTradingEngine``. Every one of those either does
not touch this concept at all, or (if a future STEP wants to surface
this engine's result there) would only ever pass this engine's own
output through unchanged, never recompute it.

Formula (LOCKED, matches the roadmap exactly):

    unrealized_pnl = (market_price - position.average_price) * position.quantity

``average_price`` and ``quantity`` come from the ``Position`` object
the caller supplies -- this engine never fetches a ``Position``
itself (no ``PositionRepository`` dependency, mirroring
``PositionPerformanceEngine``'s own "caller already fetched it"
convention) and never recomputes ``average_price`` (the weighted
average formula in ``PositionManager`` is untouched and is not
duplicated here). ``Order`` is never read, directly or indirectly --
this module has no import of ``Database.models.Order`` or any
``OrderRepository``.

Market price pipeline (per the STEP 3 audit): this engine calls the
existing, already-production ``Orchestration.market_price_tool.
MarketPriceTool`` -- the same Tool already registered in
``Core.composition_root`` as ``"market_price"`` -- via its existing
public contract (``execute(context)`` where ``context`` exposes a
``.parameters`` mapping, per ``Orchestration.tool_context.
ToolContext``). No new fetch logic, no second yfinance/StockService
call path, no new Repository -- this is the one pipeline the STEP 3
audit already traced (``StockDataRepository`` -> ``StockService`` ->
``MarketPriceTool``), reused exactly as-is.

Timestamp (per the STEP 3 audit's "no market timestamp exists
anywhere in the pipeline" finding): ``MarketPriceTool``'s own output
carries no timestamp (LOCKED, by its own docstring: "No timestamp...
appears anywhere in this method") and the underlying OHLCV bar's
Date/Datetime index is discarded before it ever reaches
``MarketPriceTool``'s or ``StockService``'s output -- there is
nothing to pass through. Rather than reopen or extend that LOCKED
Tool (out of scope for this Activation, and would touch a file this
Activation's ``main`` roadmap item never mentions), this engine
generates its own timestamp the moment it captures the price, using
``datetime.now(timezone.utc).isoformat()`` -- the exact pattern
already established, unchanged, by ``PositionRepository``/
``AccountRepository``/``OrderRepository`` for ``created_at``/
``updated_at``. It is captured in the same method call, immediately
around the ``MarketPriceTool.execute()`` call that produces
``market_price`` -- i.e. it comes from "the same source" in the only
sense that pipeline currently supports: the exact moment this engine
observed that price, not a separately-fetched or unrelated clock
reading.

Persistence (LOCKED, per the STEP 3 audit's "no evidence requires
persistence" finding): this engine never writes anything. It has no
``update``/``create``/``save`` method, holds no reference to any
Repository capable of writing a ``Position`` row, and its result is
never passed to ``PositionRepository.update``. ``unrealized_pnl``,
``market_price``, and ``market_timestamp`` are computed fresh on
every call and returned to the caller; nothing is cached, memoized,
or persisted anywhere. This mirrors the audit's own reasoning: a
value that changes with every tick of the market would be stale the
instant it was written, unlike ``Position.realized_pnl`` (settled by
an actual ``Trade``).

Restart behavior (informational, matches the STEP 3 audit): after a
restart, this engine still works exactly the same way, because it
never depended on anything restart could lose -- ``Position`` state
is read fresh from ``PositionRepository``/``PerformanceRepository`` by
the caller (already durable, per Activation 3.7 STEP 2's restart
proof), and ``market_price``/``market_timestamp`` are always fetched
live on every call regardless of process age. There is no cache to
invalidate and no persisted unrealized value to go stale.

Dependency (LOCKED for the base contract, additive extension in Phase
G Task 3): the original, still-supported constructor signature takes
exactly one dependency, ``MarketPriceTool``. No ``PositionRepository``,
no ``PerformanceRepository``, no ``TradeRepository``, no
``OrderRepository``.

Phase G Task 3 ("Valuation Freshness + Paper Review Inputs") extends
this engine ADDITIVELY ONLY: two new, optional constructor keyword
arguments (``valuation_observation_repository`` and
``data_freshness_policy``) and three new, defaulted
``UnrealizedPnLResult`` fields (``valuation_status``, ``observed_at``,
``source``). When neither optional argument is supplied (every
existing call site in this codebase, unchanged), ``calculate()``
behaves byte-for-byte as before: a live price is fetched every call,
a missing price still raises ``ValidationError``, and nothing is
persisted. The new behavior only activates when a caller opts in by
supplying both new collaborators (see ``take_snapshot``-level callers
added in Phase G Task 3 for the one that does).

When opted in, this engine still never invents a price. A live
``MarketPriceTool`` fetch that succeeds is recorded via
``ValuationObservationRepository.record`` as the new "last-good"
observation and reported ``FRESH``. A live fetch that fails no longer
raises immediately -- it consults the durable last-good observation
for this ``(account_id, symbol)`` (restart-safe, since it was
persisted, not held in memory) via the existing, LOCKED
``Business.data_freshness_policy.DataFreshnessPolicy``. If a last-good
observation exists, its own ``observed_at`` is preserved unchanged
(never re-stamped to "now") and the result is reported ``STALE`` --
still computed from that last-good price (never zero, never silently
treated as current), but visibly labelled as such. If no observation
has ever been recorded for this ``(account_id, symbol)`` either, this
engine still raises ``ValidationError`` exactly as the base contract
always has -- an "unavailable" valuation is never silently reported as
``0``/``STALE``/current.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from Business.data_freshness_policy import (
    DataFreshnessPolicy,
    Observation,
    FreshnessResult,
)
from Core.exceptions import ValidationError
from Database.models import Position
from Orchestration.market_price_tool import MarketPriceTool
from Orchestration.tool_context import ToolContext

#: Valuation freshness labels this engine can attach to a result when
#: freshness tracking is enabled (Phase G Task 3). Reuses the exact
#: string constants ``Business.data_freshness_policy`` already defines
#: for ``FRESH``/``STALE``, plus one new label, ``UNAVAILABLE``, for
#: the "no live price and nothing durable to fall back on either" case
#: -- distinct from raising, for callers (e.g. a future portfolio-level
#: aggregator) that want to represent "unavailable" as a value rather
#: than catch an exception per position.
VALUATION_FRESH: str = "FRESH"
VALUATION_STALE: str = "STALE"
VALUATION_UNAVAILABLE: str = "UNAVAILABLE"


@dataclass
class UnrealizedPnLResult:
    """The on-demand unrealized P/L snapshot for a single ``Position``.

    Every field here is either read verbatim from the supplied
    ``Position`` (``position_id``/``account_id``/``symbol``/
    ``quantity``/``average_price``) or produced fresh by this engine's
    ``calculate()`` call (``market_price``/``market_timestamp``/
    ``unrealized_pnl``) -- nothing here is ever read back from a
    database, and nothing here is ever written to one, with the sole
    exception of the Phase G Task 3 last-good-observation cache (see
    module docstring), which is opt-in and orthogonal to this result.

    Phase G Task 3 additive fields (all defaulted so every pre-existing
    construction of this dataclass, positional or keyword, remains
    valid unchanged):

    Attributes:
        valuation_status: One of ``VALUATION_FRESH``/``VALUATION_STALE``
            (``VALUATION_UNAVAILABLE`` is never attached to a returned
            result -- that case raises instead, see ``calculate()``).
            ``None`` when freshness tracking was not enabled for this
            call (the base, backward-compatible contract).
        observed_at: The real timestamp the reported ``market_price``
            was genuinely obtained at -- equal to ``market_timestamp``
            when ``valuation_status`` is ``FRESH``, but the *original*,
            preserved timestamp of the retained last-good observation
            when ``valuation_status`` is ``STALE`` (never re-stamped to
            "now"). ``None`` when freshness tracking was not enabled.
        source: Free-text label identifying where ``market_price`` came
            from. ``None`` when freshness tracking was not enabled.
    """

    position_id: int
    account_id: str
    symbol: str
    quantity: float
    average_price: float
    market_price: float
    market_timestamp: str
    unrealized_pnl: float
    valuation_status: Optional[str] = None
    observed_at: Optional[str] = None
    source: Optional[str] = None


class UnrealizedPnLEngine:
    """Computes :class:`UnrealizedPnLResult` for a single ``Position``,
    on demand, using the current market price.

    The SOLE business owner of ``unrealized_pnl`` (Activation 3.7
    STEP 4) -- see the module docstring for the full Source-of-Truth
    rationale. Read-only toward trading state: no method on this class
    ever creates, updates, or deletes an ``Order``, ``Trade``,
    ``Account``, or ``Position``. The one Phase G Task 3 addition is
    writing/reading the opt-in ``valuation_observations`` cache
    (module docstring), which is not trading state.
    """

    def __init__(
        self,
        market_price_tool: MarketPriceTool,
        *,
        valuation_observation_repository: Optional[object] = None,
        data_freshness_policy: Optional[DataFreshnessPolicy] = None,
    ) -> None:
        """Store the collaborators this engine calls.

        Args:
            market_price_tool: The already-constructed
                ``MarketPriceTool`` used to obtain the current market
                price for a ``Position``'s symbol. Stored by
                reference only -- never wrapped, never copied.
            valuation_observation_repository: Optional Phase G Task 3
                addition -- an already-constructed
                ``Repository.persistence.valuation_observation_repository.
                ValuationObservationRepository`` used to persist and
                retrieve the durable last-good price observation per
                ``(account_id, symbol)``. When ``None`` (the default),
                freshness tracking is disabled and ``calculate()``
                behaves exactly as the pre-Phase-G-Task-3 contract
                (raises ``ValidationError`` immediately on any fetch
                failure, persists nothing). Must be supplied together
                with ``data_freshness_policy`` to enable freshness
                tracking -- supplying only one has no effect (treated
                as freshness tracking disabled).
            data_freshness_policy: Optional Phase G Task 3 addition --
                the existing, LOCKED
                ``Business.data_freshness_policy.DataFreshnessPolicy``
                used to decide FRESH vs STALE for a retained last-good
                observation. See ``valuation_observation_repository``
                above for the opt-in contract.
        """
        self._market_price_tool = market_price_tool
        self._valuation_observation_repository = valuation_observation_repository
        self._data_freshness_policy = data_freshness_policy

    def calculate(self, position: Position) -> UnrealizedPnLResult:
        """Compute the current unrealized P/L for ``position``.

        Args:
            position: An already-fetched ``Position`` (e.g. via
                ``PositionRepository.get_open_position``/
                ``get_by_id``/``list_by_account``, or
                ``PerformanceRepository.get_all_positions`` --
                whichever the caller already used). This engine never
                fetches a ``Position`` itself and never reads
                ``Order``. ``position.average_price`` and
                ``position.quantity`` are used exactly as given --
                never recomputed.

        Returns:
            A :class:`UnrealizedPnLResult` whose ``market_price`` is
            the current price for ``position.symbol`` (from
            ``MarketPriceTool``, or -- only when freshness tracking is
            enabled and the live fetch failed -- the retained
            last-good price), whose ``market_timestamp`` is this
            call's own UTC timestamp (ISO 8601, the same pattern
            ``PositionRepository``/``AccountRepository``/
            ``OrderRepository`` already use for ``created_at``/
            ``updated_at``), and whose ``unrealized_pnl`` is
            ``(market_price - position.average_price) *
            position.quantity``. When freshness tracking is disabled
            (the default), nothing is persisted, matching the base
            contract exactly.

        Raises:
            ValidationError: If ``MarketPriceTool`` cannot resolve a
                valid current price for ``position.symbol`` AND (when
                freshness tracking is enabled) no durable last-good
                observation exists for this ``(account_id, symbol)``
                either -- an unrealized P/L is never fabricated from a
                missing price, and an unavailable valuation is never
                silently reported as ``STALE``/zero/current.
        """
        context = ToolContext(task=None, parameters={"symbol": position.symbol})
        result = self._market_price_tool.execute(context)

        output = result.output if isinstance(result.output, dict) else {}
        raw_price = output.get("price")
        now = datetime.now(timezone.utc)
        market_timestamp = now.isoformat()
        live_price_valid = isinstance(raw_price, (int, float)) and not isinstance(raw_price, bool)

        freshness_enabled = (
            self._valuation_observation_repository is not None
            and self._data_freshness_policy is not None
        )

        if not freshness_enabled:
            if not live_price_valid:
                raise ValidationError(
                    f"Cannot compute unrealized P/L for {position.symbol} "
                    f"(account {position.account_id}): no valid current market price available",
                    details={
                        "account_id": position.account_id,
                        "symbol": position.symbol,
                        "position_id": position.position_id,
                    },
                )
            unrealized_pnl = (raw_price - position.average_price) * position.quantity
            return UnrealizedPnLResult(
                position_id=position.position_id,
                account_id=position.account_id,
                symbol=position.symbol,
                quantity=position.quantity,
                average_price=position.average_price,
                market_price=raw_price,
                market_timestamp=market_timestamp,
                unrealized_pnl=unrealized_pnl,
            )

        # Freshness tracking enabled (Phase G Task 3).
        source = "market_price_tool"
        candidate: Optional[Observation[float]] = None
        if live_price_valid:
            candidate = Observation(value=raw_price, observed_at=market_timestamp, source=source)

        last_good_row = self._valuation_observation_repository.get(position.account_id, position.symbol)
        last_good: Optional[Observation[float]] = None
        if last_good_row is not None:
            last_good = Observation(
                value=last_good_row.price,
                observed_at=last_good_row.observed_at,
                source=last_good_row.source,
            )

        freshness_result: FreshnessResult[float] = self._data_freshness_policy.evaluate(
            candidate, now=now, last_good=last_good
        )

        if freshness_result.observation is None:
            # MISSING: no live price this call, and nothing durable
            # ever recorded for this (account_id, symbol) -- an
            # unavailable valuation is explicit, never fabricated.
            raise ValidationError(
                f"Cannot compute unrealized P/L for {position.symbol} "
                f"(account {position.account_id}): no valid current market price available "
                f"and no prior observation is on record",
                details={
                    "account_id": position.account_id,
                    "symbol": position.symbol,
                    "position_id": position.position_id,
                    "valuation_status": VALUATION_UNAVAILABLE,
                },
            )

        market_price = freshness_result.observation.value
        observed_at = freshness_result.observation.observed_at
        observation_source = freshness_result.observation.source

        if freshness_result.status == "FRESH":
            self._valuation_observation_repository.record(
                position.account_id, position.symbol, market_price, observed_at, source
            )
            valuation_status = VALUATION_FRESH
        else:
            valuation_status = VALUATION_STALE

        unrealized_pnl = (market_price - position.average_price) * position.quantity

        return UnrealizedPnLResult(
            position_id=position.position_id,
            account_id=position.account_id,
            symbol=position.symbol,
            quantity=position.quantity,
            average_price=position.average_price,
            market_price=market_price,
            market_timestamp=market_timestamp,
            unrealized_pnl=unrealized_pnl,
            valuation_status=valuation_status,
            observed_at=observed_at,
            source=observation_source,
        )