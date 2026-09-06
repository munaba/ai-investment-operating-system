"""StopLossTakeProfitMonitor -- Activation 3.8 STEP 3.

Explicit/manual monitoring of a single OPEN ``Position``'s
``stop_loss``/``take_profit`` (persisted by Activation 3.8 STEP 2)
against the current market price. Read-only, on-demand -- one call =
one check.

Roadmap contract for this STEP (LOCKED):

    Pada activation awal, trigger boleh manual atau melalui explicit
    monitoring command. Jangan langsung membuat background autonomous
    execution.

Business owner (LOCKED, per this STEP's own scope decision): a new,
single, minimal component -- ``StopLossTakeProfitMonitor`` -- not
``PositionManager`` (which stays the owner of transactional state/
realized P/L, per its own module docstring's "Strictly DILARANG"
list -- stop loss/take profit *triggering* is not in the two items
that list has had removed from it), not
``Business.position_performance_engine.PositionPerformanceEngine``
(a pure, dependency-free aggregator over ``realized_pnl`` only, per
its own docstring), not ``Business.performance_summary_service.
PerformanceSummaryService``, and not ``Orchestration.market_price_tool.
MarketPriceTool`` itself (a stateless Tool, not a business owner of
anything). This mirrors the exact same "one new minimal component,
not an existing one with the wrong shape" decision Activation 3.7
STEP 4 already made for ``Business.unrealized_pnl_engine.
UnrealizedPnLEngine`` -- and this module is deliberately built as
close to that one's shape as the different subject matter allows.

Market price pipeline (LOCKED, reused verbatim, no second fetch path):
this monitor calls the existing, already-production
``Orchestration.market_price_tool.MarketPriceTool`` -- the same Tool
already registered in ``Core.composition_root`` as ``"market_price"``,
and the same Tool ``UnrealizedPnLEngine`` already depends on -- via its
existing public contract (``execute(context)`` where ``context``
exposes a ``.parameters`` mapping, per ``Orchestration.tool_context.
ToolContext``). No new Repository, no new Service, no second
StockService/yfinance call path, no cache.

Timestamp (LOCKED, same reasoning as ``UnrealizedPnLEngine``'s own
docstring): ``MarketPriceTool``'s output carries no market timestamp
of its own -- nothing to pass through. This monitor generates its own
application-level timestamp the moment it captures the price, using
``datetime.now(timezone.utc).isoformat()``, the same pattern already
established by ``PositionRepository``/``AccountRepository``/
``OrderRepository`` (``created_at``/``updated_at``) and by
``UnrealizedPnLEngine`` (``market_timestamp``). This is exactly what
the STEP 3 instructions permit: "Gunakan timestamp application-level
hanya jika memang diperlukan oleh contract monitoring yang dibuat" --
the ``StopLossTakeProfitCheckResult`` contract below does need one.

Trigger semantics (LOCKED, LONG-only -- this project has no short
position concept anywhere else in the codebase):

    stop_loss configured and market_price <= stop_loss
        -> STOP_LOSS_TRIGGERED
    take_profit configured and market_price >= take_profit
        -> TAKE_PROFIT_TRIGGERED
    otherwise
        -> NO_TRIGGER

Both boundaries are inclusive (``<=``/``>=``), per the STEP
instructions. No trailing-stop adjustment, no short-position mirror
rule, is implemented anywhere in this module.

Guard clauses (checked BEFORE any market-price fetch, so a closed
position or an unconfigured position never triggers a network/
StockService call at all):

* ``position.status != "open"`` -> ``NO_TRIGGER``, no fetch.
* both ``stop_loss`` and ``take_profit`` are ``None`` -> ``NO_TRIGGER``,
  no fetch.
* both are configured but do not satisfy the LONG-valid ordering
  ``stop_loss < position.average_price < take_profit`` -> this is the
  "configuration tidak valid atau ambiguous" case the STEP
  instructions call out; this monitor fails safely by raising
  ``ValidationError`` rather than guessing which side "should" win --
  no ``Position`` write happens (this module cannot write one at all;
  see "No execution" below). In practice this state should never be
  reachable, because ``PositionManager.set_stop_loss_take_profit``
  (Activation 3.8 STEP 2) already enforces this same ordering at
  write time -- this is defensive-in-depth for this monitor only, not
  a second copy of that write-time validation.

No execution (LOCKED, the STEP's primary acceptance criterion): this
module never creates an ``Order``/``Trade``, never calls
``Business.paper_trading_engine.PaperTradingEngine.submit_order``, and
never mutates a ``Position`` -- it has no ``PositionRepository``/
``PositionManager``/``PaperTradingEngine`` dependency of any kind, and
no method on this class performs a write of any kind to anything.
``trigger -> SELL -> PaperTradingEngine -> Trade`` is NOT implemented
here; that is explicitly reserved for a future Activation, per the
STEP instructions.

No background execution (LOCKED): no scheduler, worker, daemon,
polling loop, or event/notification dispatch of any kind exists in
this module. ``check()`` is a single, synchronous, stateless method
call -- exactly one explicit check per call, with no internal loop,
timer, or retry. ``Business.notification_event.
NotificationEventType.STOP_LOSS_TRIGGERED`` is not read, imported, or
wired anywhere in this module.

No new persistence/schema (LOCKED): this module holds no database
handle, no Repository reference capable of writing, and introduces no
new column/table -- it works entirely off the ``Position`` object the
caller already fetched (mirroring ``UnrealizedPnLEngine``'s "caller
already fetched it" convention) plus one live market-price lookup.
There is no "already triggered" persisted state anywhere: two
successive calls against an unchanged, still-triggering price both
return the same triggered result, by design (see the STEP
instructions' "Repeated checks" section) -- this is intentional
statelessness, not a bug.

Dependency (LOCKED): exactly one constructor dependency,
``MarketPriceTool`` -- mirrors ``UnrealizedPnLEngine`` exactly. No
``PositionRepository``, no ``PositionManager``, no
``PaperTradingEngine``, no database handle of any kind.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from Core.exceptions import ValidationError
from Database.models import Position
from Orchestration.market_price_tool import MarketPriceTool
from Orchestration.tool_context import ToolContext

#: The three possible outcomes of a single check() call (LOCKED,
#: STEP 3 contract). Plain string constants, mirroring
#: ``Business.position_manager``'s own local ``_STATUS_OPEN``/
#: ``_STATUS_CLOSED`` style -- this is a single-module concern, not a
#: cross-module/SQL-CHECK domain like ``Database.position_constants.
#: POSITION_STATUSES``, so it does not need that heavier single-
#: source-of-truth treatment.
NO_TRIGGER = "NO_TRIGGER"
STOP_LOSS_TRIGGERED = "STOP_LOSS_TRIGGERED"
TAKE_PROFIT_TRIGGERED = "TAKE_PROFIT_TRIGGERED"

#: ``Database.position_constants.POSITION_STATUSES``'s ``"open"``
#: value, kept as a local literal (matching ``PositionManager``'s own
#: ``_STATUS_OPEN`` -- not imported, since this module deliberately
#: has zero database-layer dependency of any kind, only
#: ``Database.models.Position`` for the type hint).
_STATUS_OPEN = "open"


@dataclass
class StopLossTakeProfitCheckResult:
    """The on-demand SL/TP check outcome for a single ``Position``.

    ``position_id``/``symbol`` are read verbatim from the supplied
    ``Position``. ``configured_stop_loss``/``configured_take_profit``
    are also read verbatim (never recomputed or validated beyond the
    LONG-ordering guard documented on ``StopLossTakeProfitMonitor``).
    ``market_price``/``market_timestamp`` are ``None`` when no
    price fetch was needed (the guard-clause NO_TRIGGER paths) and
    populated whenever a fetch did happen. ``trigger`` is always one
    of ``NO_TRIGGER``/``STOP_LOSS_TRIGGERED``/``TAKE_PROFIT_TRIGGERED``.
    Nothing here is ever written to a database.
    """

    position_id: int
    symbol: str
    trigger: str
    configured_stop_loss: Optional[float]
    configured_take_profit: Optional[float]
    market_price: Optional[float]
    market_timestamp: Optional[str]


class StopLossTakeProfitMonitor:
    """Explicit, read-only stop-loss/take-profit check for a single
    OPEN ``Position``, on demand.

    One call to ``check()`` is one explicit check -- there is no
    loop, no scheduling, and no persisted "already triggered" state
    anywhere on this class (see the module docstring's "Repeated
    checks" section). No method on this class ever creates, updates,
    or deletes anything in any Repository or database, and no method
    ever submits an order or trade.
    """

    def __init__(self, market_price_tool: MarketPriceTool) -> None:
        """Store the one collaborator this monitor calls.

        Args:
            market_price_tool: The already-constructed
                ``MarketPriceTool`` (or any duck-typed test double
                exposing the same ``execute(context) -> ToolResult``
                contract, mirroring ``UnrealizedPnLEngine``'s own
                injection seam) used to obtain the current market
                price for a ``Position``'s symbol. Stored by
                reference only -- never wrapped, never copied.
        """
        self._market_price_tool = market_price_tool

    def check(self, position: Position) -> StopLossTakeProfitCheckResult:
        """Run a single explicit stop-loss/take-profit check for
        ``position``.

        Args:
            position: An already-fetched ``Position`` (e.g. via
                ``PositionRepository.get_open_position``/
                ``get_by_id``/``list_by_account``). This monitor never
                fetches a ``Position`` itself, never reads ``Order``,
                and never recomputes ``average_price``.

        Returns:
            A :class:`StopLossTakeProfitCheckResult`. ``trigger`` is
            ``NO_TRIGGER`` if ``position.status`` is not ``"open"``,
            if neither ``stop_loss`` nor ``take_profit`` is
            configured, or if the current market price sits strictly
            between them; ``STOP_LOSS_TRIGGERED`` if the current
            market price is at or below a configured ``stop_loss``;
            ``TAKE_PROFIT_TRIGGERED`` if it is at or above a
            configured ``take_profit``. No market-price fetch happens
            for the first two ``NO_TRIGGER`` cases -- ``market_price``/
            ``market_timestamp`` are ``None`` on that result.

        Raises:
            ValidationError: If both ``stop_loss`` and ``take_profit``
                are configured but do not satisfy the LONG-valid
                ordering ``stop_loss < position.average_price <
                take_profit`` (see the module docstring's guard-clause
                section), or if ``MarketPriceTool`` cannot resolve a
                valid current price for ``position.symbol`` once a
                fetch is actually needed. In every case, nothing is
                written anywhere -- this monitor has no repository
                dependency capable of a write in the first place.
        """
        if position.status != _STATUS_OPEN:
            return StopLossTakeProfitCheckResult(
                position_id=position.position_id,
                symbol=position.symbol,
                trigger=NO_TRIGGER,
                configured_stop_loss=position.stop_loss,
                configured_take_profit=position.take_profit,
                market_price=None,
                market_timestamp=None,
            )

        if position.stop_loss is None and position.take_profit is None:
            return StopLossTakeProfitCheckResult(
                position_id=position.position_id,
                symbol=position.symbol,
                trigger=NO_TRIGGER,
                configured_stop_loss=None,
                configured_take_profit=None,
                market_price=None,
                market_timestamp=None,
            )

        if (
            position.stop_loss is not None
            and position.take_profit is not None
            and not (position.stop_loss < position.average_price < position.take_profit)
        ):
            raise ValidationError(
                f"Cannot monitor position {position.position_id} ({position.symbol}): "
                f"stop_loss={position.stop_loss} and take_profit={position.take_profit} "
                f"do not straddle average_price={position.average_price} (LONG)",
                details={
                    "position_id": position.position_id,
                    "symbol": position.symbol,
                    "stop_loss": position.stop_loss,
                    "take_profit": position.take_profit,
                    "average_price": position.average_price,
                },
            )

        context = ToolContext(task=None, parameters={"symbol": position.symbol})
        result = self._market_price_tool.execute(context)

        output = result.output if isinstance(result.output, dict) else {}
        market_price = output.get("price")
        market_timestamp = datetime.now(timezone.utc).isoformat()

        if not isinstance(market_price, (int, float)) or isinstance(market_price, bool):
            raise ValidationError(
                f"Cannot monitor {position.symbol} (position {position.position_id}): "
                f"no valid current market price available",
                details={
                    "position_id": position.position_id,
                    "symbol": position.symbol,
                },
            )

        if position.stop_loss is not None and market_price <= position.stop_loss:
            trigger = STOP_LOSS_TRIGGERED
        elif position.take_profit is not None and market_price >= position.take_profit:
            trigger = TAKE_PROFIT_TRIGGERED
        else:
            trigger = NO_TRIGGER

        return StopLossTakeProfitCheckResult(
            position_id=position.position_id,
            symbol=position.symbol,
            trigger=trigger,
            configured_stop_loss=position.stop_loss,
            configured_take_profit=position.take_profit,
            market_price=market_price,
            market_timestamp=market_timestamp,
        )
