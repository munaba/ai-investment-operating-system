"""Standalone regression checks for
``Business.stop_loss_take_profit_monitor.StopLossTakeProfitMonitor``.

Covers Activation 3.8 STEP 3 (explicit/manual SL/TP monitoring):

* price strictly between stop_loss/take_profit -> NO_TRIGGER;
* market_price <= stop_loss -> STOP_LOSS_TRIGGERED (incl. boundary);
* market_price >= take_profit -> TAKE_PROFIT_TRIGGERED (incl. boundary);
* no configured stop_loss/take_profit -> NO_TRIGGER, no price fetch;
* a CLOSED position -> NO_TRIGGER, no price fetch;
* an ambiguous/invalid configuration (stop_loss/take_profit not
  straddling average_price) raises ValidationError, no price fetch
  attempted before that guard;
* a missing/invalid market price raises ValidationError;
* this monitor never writes anything and never calls
  ``PaperTradingEngine``/``PositionManager`` -- it has no such
  dependency on the instance at all;
* repeated calls against an unchanged, still-triggering price both
  return the same triggered result (stateless, no persisted
  "already triggered" flag).

Builds ``Database.models.Position`` instances directly -- no database,
no repository, no I/O -- matching ``Tests/test_expectancy_engine.py``'s
own no-DB pattern, and uses a small duck-typed ``_FixedPriceTool``/
``_PoisonPriceTool`` test double for the market-price dependency,
mirroring ``Tests/activation_3_7_step4_proof.py``'s own
``_FixedPriceTool`` pattern for ``UnrealizedPnLEngine``.

Run directly with ``python Tests/test_stop_loss_take_profit_monitor.py``
-- no external test framework required.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.stop_loss_take_profit_monitor import (  # noqa: E402
    NO_TRIGGER,
    STOP_LOSS_TRIGGERED,
    TAKE_PROFIT_TRIGGERED,
    StopLossTakeProfitCheckResult,
    StopLossTakeProfitMonitor,
)
from Core.exceptions import ValidationError  # noqa: E402
from Database.models import Position  # noqa: E402
from Orchestration.tool_result import ToolResult  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


class _FixedPriceTool:
    """Test double for ``MarketPriceTool``: same ``execute(context)``
    contract, reports a fixed, caller-supplied price. Records how many
    times it was called, so tests can prove a fetch did/did not
    happen. Never touched by production code.
    """

    def __init__(self, price):
        self._price = price
        self.call_count = 0

    def execute(self, context):
        self.call_count += 1
        symbol = context.parameters.get("symbol")
        return ToolResult(
            success=True,
            output={"symbol": symbol, "price": self._price, "trend": "manual-fixture"},
            error=None,
            metadata={},
        )


class _PoisonPriceTool:
    """Test double that raises if ``execute()`` is ever called -- used
    to prove a guard-clause path never reaches the market-price fetch
    at all.
    """

    def execute(self, context):
        raise AssertionError("MarketPriceTool.execute() should not have been called")


def _position(
    position_id=1,
    account_id="paper-id",
    symbol="BBCA",
    quantity=100.0,
    average_price=9500.0,
    realized_pnl=0.0,
    status="open",
    stop_loss=None,
    take_profit=None,
):
    return Position(
        position_id=position_id,
        account_id=account_id,
        symbol=symbol,
        quantity=quantity,
        average_price=average_price,
        realized_pnl=realized_pnl,
        status=status,
        created_at="2026-08-01T00:00:00+00:00",
        updated_at="2026-08-01T00:00:00+00:00",
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def scenario_price_between_levels_no_trigger():
    print("\n[Scenario A] price strictly between stop_loss and take_profit -> NO_TRIGGER")
    position = _position(stop_loss=9000.0, take_profit=10000.0, average_price=9500.0)
    tool = _FixedPriceTool(9500.0)
    monitor = StopLossTakeProfitMonitor(tool)

    result = monitor.check(position)

    check(isinstance(result, StopLossTakeProfitCheckResult), "check() returns a StopLossTakeProfitCheckResult")
    check(result.trigger == NO_TRIGGER, "price between SL and TP produces NO_TRIGGER")
    check(result.market_price == 9500.0, "market_price reflects the fetched price")
    check(bool(result.market_timestamp), "market_timestamp is populated when a fetch happened")
    check(tool.call_count == 1, "exactly one market-price fetch happened")


def scenario_stop_loss_triggered_below():
    print("\n[Scenario B] market_price below stop_loss -> STOP_LOSS_TRIGGERED")
    position = _position(stop_loss=9000.0, take_profit=10000.0)
    monitor = StopLossTakeProfitMonitor(_FixedPriceTool(8800.0))

    result = monitor.check(position)

    check(result.trigger == STOP_LOSS_TRIGGERED, "price below stop_loss triggers STOP_LOSS_TRIGGERED")
    check(result.configured_stop_loss == 9000.0, "configured_stop_loss is echoed back")
    check(result.configured_take_profit == 10000.0, "configured_take_profit is echoed back")


def scenario_take_profit_triggered_above():
    print("\n[Scenario C] market_price above take_profit -> TAKE_PROFIT_TRIGGERED")
    position = _position(stop_loss=9000.0, take_profit=10000.0)
    monitor = StopLossTakeProfitMonitor(_FixedPriceTool(10500.0))

    result = monitor.check(position)

    check(result.trigger == TAKE_PROFIT_TRIGGERED, "price above take_profit triggers TAKE_PROFIT_TRIGGERED")


def scenario_no_configured_levels_no_trigger_no_fetch():
    print("\n[Scenario D] no configured stop_loss/take_profit -> NO_TRIGGER, no price fetch")
    position = _position(stop_loss=None, take_profit=None)
    tool = _PoisonPriceTool()
    monitor = StopLossTakeProfitMonitor(tool)

    result = monitor.check(position)

    check(result.trigger == NO_TRIGGER, "no configured levels produces NO_TRIGGER")
    check(result.market_price is None, "market_price is None when no fetch happened")
    check(result.market_timestamp is None, "market_timestamp is None when no fetch happened")


def scenario_closed_position_no_trigger_no_fetch():
    print("\n[Scenario E] CLOSED position -> NO_TRIGGER, no price fetch")
    position = _position(status="closed", stop_loss=9000.0, take_profit=10000.0)
    tool = _PoisonPriceTool()
    monitor = StopLossTakeProfitMonitor(tool)

    result = monitor.check(position)

    check(result.trigger == NO_TRIGGER, "a CLOSED position never triggers")
    check(result.market_price is None, "market_price is None -- no fetch happened for a CLOSED position")


def scenario_boundary_stop_loss_triggers():
    print("\n[Scenario F1] market_price exactly == stop_loss -> STOP_LOSS_TRIGGERED (inclusive boundary)")
    position = _position(stop_loss=9000.0, take_profit=10000.0)
    monitor = StopLossTakeProfitMonitor(_FixedPriceTool(9000.0))

    result = monitor.check(position)

    check(result.trigger == STOP_LOSS_TRIGGERED, "price == stop_loss is inclusive and triggers")


def scenario_boundary_take_profit_triggers():
    print("\n[Scenario F2] market_price exactly == take_profit -> TAKE_PROFIT_TRIGGERED (inclusive boundary)")
    position = _position(stop_loss=9000.0, take_profit=10000.0)
    monitor = StopLossTakeProfitMonitor(_FixedPriceTool(10000.0))

    result = monitor.check(position)

    check(result.trigger == TAKE_PROFIT_TRIGGERED, "price == take_profit is inclusive and triggers")


def scenario_only_stop_loss_configured():
    print("\n[Scenario G] only stop_loss configured (no take_profit)")
    position = _position(stop_loss=9000.0, take_profit=None)

    below = StopLossTakeProfitMonitor(_FixedPriceTool(8900.0)).check(position)
    check(below.trigger == STOP_LOSS_TRIGGERED, "stop_loss alone still triggers when price drops below it")

    above = StopLossTakeProfitMonitor(_FixedPriceTool(20000.0)).check(position)
    check(above.trigger == NO_TRIGGER, "with no take_profit configured, an arbitrarily high price never triggers")


def scenario_only_take_profit_configured():
    print("\n[Scenario H] only take_profit configured (no stop_loss)")
    position = _position(stop_loss=None, take_profit=10000.0)

    above = StopLossTakeProfitMonitor(_FixedPriceTool(10500.0)).check(position)
    check(above.trigger == TAKE_PROFIT_TRIGGERED, "take_profit alone still triggers when price rises above it")

    below = StopLossTakeProfitMonitor(_FixedPriceTool(1.0)).check(position)
    check(below.trigger == NO_TRIGGER, "with no stop_loss configured, an arbitrarily low price never triggers")


def scenario_invalid_configuration_raises_before_fetch():
    print("\n[Scenario I] ambiguous/invalid SL+TP configuration raises ValidationError, no fetch attempted")
    # average_price=9500.0 but stop_loss is ABOVE average_price -- an
    # invalid LONG configuration that PositionManager.
    # set_stop_loss_take_profit would never have allowed to be written
    # in the first place; this monitor defends against it anyway.
    position = _position(average_price=9500.0, stop_loss=9600.0, take_profit=10000.0)
    tool = _PoisonPriceTool()
    monitor = StopLossTakeProfitMonitor(tool)

    raised = False
    try:
        monitor.check(position)
    except ValidationError:
        raised = True
    check(raised, "stop_loss above average_price (with take_profit also set) raises ValidationError")


def scenario_missing_market_price_raises():
    print("\n[Scenario J] missing/invalid market price raises ValidationError, no trigger fabricated")
    position = _position(stop_loss=9000.0, take_profit=10000.0)
    monitor = StopLossTakeProfitMonitor(_FixedPriceTool(None))

    raised = False
    try:
        monitor.check(position)
    except ValidationError:
        raised = True
    check(raised, "a missing market price raises ValidationError rather than returning a fabricated trigger")


def scenario_repeated_checks_are_stateless():
    print("\n[Scenario K] repeated checks against an unchanged price both trigger (stateless)")
    position = _position(stop_loss=9000.0, take_profit=10000.0)
    tool = _FixedPriceTool(8800.0)
    monitor = StopLossTakeProfitMonitor(tool)

    first = monitor.check(position)
    second = monitor.check(position)

    check(first.trigger == STOP_LOSS_TRIGGERED, "first call triggers")
    check(second.trigger == STOP_LOSS_TRIGGERED, "second call against the same unchanged price also triggers")
    check(tool.call_count == 2, "each check() call performs its own independent fetch")


def scenario_read_only_no_write_dependency():
    print("\n[Scenario L] StopLossTakeProfitMonitor holds no repository/engine/execution dependency")
    monitor = StopLossTakeProfitMonitor(_FixedPriceTool(9500.0))
    attrs = sorted(vars(monitor).keys())
    check(
        attrs == ["_market_price_tool"],
        "StopLossTakeProfitMonitor holds exactly one collaborator: _market_price_tool",
    )
    forbidden_names = (
        "submit_order", "sell", "apply_trade", "create", "update", "delete",
        "execute_order", "position_repository", "position_manager",
        "paper_trading_engine", "order_repository", "trade_repository",
    )
    for name in forbidden_names:
        check(not hasattr(StopLossTakeProfitMonitor, name), f"StopLossTakeProfitMonitor has no '{name}' method/attribute")


def main() -> int:
    scenario_price_between_levels_no_trigger()
    scenario_stop_loss_triggered_below()
    scenario_take_profit_triggered_above()
    scenario_no_configured_levels_no_trigger_no_fetch()
    scenario_closed_position_no_trigger_no_fetch()
    scenario_boundary_stop_loss_triggers()
    scenario_boundary_take_profit_triggers()
    scenario_only_stop_loss_configured()
    scenario_only_take_profit_configured()
    scenario_invalid_configuration_raises_before_fetch()
    scenario_missing_market_price_raises()
    scenario_repeated_checks_are_stateless()
    scenario_read_only_no_write_dependency()

    print("\n" + "=" * 70)
    print(f"ACTIVATION 3.8 STEP 3 (SL/TP MONITOR) TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 70)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
