"""Standalone regression checks for
``Business.performance_summary_service.PerformanceSummaryService``.

Covers Sprint 6 STEP 7 (pure orchestration -- this service computes
NO metric itself; every field of ``PerformanceSummary`` must be
exactly what its own engine returned):

* constructor takes exactly six dependencies, one per Sprint 6
  engine;
* ``build()`` calls all six engines exactly once each;
* the six engines are called in the LOCKED order (STEP 6 ->
  TradeStatisticsEngine, PositionPerformanceEngine, WinRateEngine,
  ExpectancyEngine, ProfitFactorEngine, MaximumDrawdownEngine);
* ``TradeStatisticsEngine.calculate()`` receives exactly ``trades``;
* ``PositionPerformanceEngine.calculate()`` receives exactly
  ``positions``;
* ``MaximumDrawdownEngine.calculate()`` receives exactly
  ``equity_curve``;
* ``WinRateEngine``/``ExpectancyEngine``/``ProfitFactorEngine`` each
  receive exactly the ``PositionPerformanceStatistics`` instance
  ``PositionPerformanceEngine.calculate()`` returned -- never a
  ``Position``, never a copy;
* ``PerformanceSummary``'s six fields are the exact same objects
  (identity, not equality) each engine returned -- no copy, no
  reconstruction;
* ``trades``/``positions``/``equity_curve`` are never mutated.

Uses hand-built fake/spy engines (plain Python classes recording
calls) rather than a mocking library, to keep this file
dependency-free and standalone, matching every other
``Tests/test_*.py`` file in this project. Uses hand-built ``Trade``/
``Position`` instances directly -- no database, no repository, no I/O.

Run directly with ``python Tests/test_performance_summary_service.py``
-- no external test framework required.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.expectancy_engine import ExpectancyResult  # noqa: E402
from Business.maximum_drawdown_engine import MaximumDrawdownResult  # noqa: E402
from Business.performance_summary_service import (  # noqa: E402
    PerformanceSummary,
    PerformanceSummaryService,
)
from Business.position_performance_engine import (  # noqa: E402
    PositionPerformanceStatistics,
)
from Business.profit_factor_engine import ProfitFactorResult  # noqa: E402
from Business.trade_statistics_engine import TradeExecutionStatistics  # noqa: E402
from Database.models import Position, Trade  # noqa: E402

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


# ---------------------------------------------------------------------------
# Fake/spy engines -- record every call (args + call order) via a shared log,
# and return a fixed, easily-identifiable sentinel object each time.
# ---------------------------------------------------------------------------


def _trade(trade_id: int = 1) -> Trade:
    return Trade(
        trade_id=trade_id,
        order_id=1,
        account_id="paper-id",
        symbol="BBCA",
        action="BUY",
        quantity=100.0,
        fill_price=9500.0,
        fee=10.0,
        tax=5.0,
        executed_at="2026-08-01T09:00:00+00:00",
    )


def _position(position_id: int = 1) -> Position:
    return Position(
        position_id=position_id,
        account_id="paper-id",
        symbol="BBCA",
        quantity=100.0,
        average_price=9500.0,
        realized_pnl=1000.0,
        status="closed",
        created_at="2026-08-01T09:00:00+00:00",
        updated_at="2026-08-01T09:00:00+00:00",
    )


class _SpyTradeStatisticsEngine:
    def __init__(self, log, result):
        self._log = log
        self._result = result
        self.call_count = 0
        self.received_args = None

    def calculate(self, trades):
        self.call_count += 1
        self.received_args = trades
        self._log.append(("TradeStatisticsEngine", trades))
        return self._result


class _SpyPositionPerformanceEngine:
    def __init__(self, log, result):
        self._log = log
        self._result = result
        self.call_count = 0
        self.received_args = None

    def calculate(self, positions):
        self.call_count += 1
        self.received_args = positions
        self._log.append(("PositionPerformanceEngine", positions))
        return self._result


class _SpyWinRateEngine:
    def __init__(self, log, result):
        self._log = log
        self._result = result
        self.call_count = 0
        self.received_args = None

    def calculate(self, statistics):
        self.call_count += 1
        self.received_args = statistics
        self._log.append(("WinRateEngine", statistics))
        return self._result


class _SpyExpectancyEngine:
    def __init__(self, log, result):
        self._log = log
        self._result = result
        self.call_count = 0
        self.received_args = None

    def calculate(self, statistics):
        self.call_count += 1
        self.received_args = statistics
        self._log.append(("ExpectancyEngine", statistics))
        return self._result


class _SpyProfitFactorEngine:
    def __init__(self, log, result):
        self._log = log
        self._result = result
        self.call_count = 0
        self.received_args = None

    def calculate(self, statistics):
        self.call_count += 1
        self.received_args = statistics
        self._log.append(("ProfitFactorEngine", statistics))
        return self._result


class _SpyMaximumDrawdownEngine:
    def __init__(self, log, result):
        self._log = log
        self._result = result
        self.call_count = 0
        self.received_args = None

    def calculate(self, equity_curve):
        self.call_count += 1
        self.received_args = equity_curve
        self._log.append(("MaximumDrawdownEngine", equity_curve))
        return self._result


def _build_spies():
    """Builds one fresh set of spy engines + their fixed sentinel results."""
    log = []

    trade_statistics_result = TradeExecutionStatistics(
        total_trades=1, buy_trades=1, sell_trades=0, total_volume=100.0,
        total_fees=10.0, total_tax=5.0, first_trade_time="2026-08-01T09:00:00+00:00",
        last_trade_time="2026-08-01T09:00:00+00:00",
    )
    position_statistics_result = PositionPerformanceStatistics(
        winning_positions=1, losing_positions=0, breakeven_positions=0,
        gross_profit=1000.0, gross_loss=0.0, net_profit=1000.0,
        average_win=1000.0, average_loss=0.0,
    )
    win_rate_result = 0.75
    expectancy_result = ExpectancyResult(expectancy=42.0)
    profit_factor_result = ProfitFactorResult(profit_factor=3.0)
    maximum_drawdown_result = MaximumDrawdownResult(maximum_drawdown=0.1)

    trade_statistics_engine = _SpyTradeStatisticsEngine(log, trade_statistics_result)
    position_performance_engine = _SpyPositionPerformanceEngine(log, position_statistics_result)
    win_rate_engine = _SpyWinRateEngine(log, win_rate_result)
    expectancy_engine = _SpyExpectancyEngine(log, expectancy_result)
    profit_factor_engine = _SpyProfitFactorEngine(log, profit_factor_result)
    maximum_drawdown_engine = _SpyMaximumDrawdownEngine(log, maximum_drawdown_result)

    service = PerformanceSummaryService(
        trade_statistics_engine=trade_statistics_engine,
        position_performance_engine=position_performance_engine,
        win_rate_engine=win_rate_engine,
        expectancy_engine=expectancy_engine,
        profit_factor_engine=profit_factor_engine,
        maximum_drawdown_engine=maximum_drawdown_engine,
    )

    return {
        "log": log,
        "service": service,
        "engines": {
            "trade_statistics_engine": trade_statistics_engine,
            "position_performance_engine": position_performance_engine,
            "win_rate_engine": win_rate_engine,
            "expectancy_engine": expectancy_engine,
            "profit_factor_engine": profit_factor_engine,
            "maximum_drawdown_engine": maximum_drawdown_engine,
        },
        "results": {
            "trade_statistics": trade_statistics_result,
            "position_statistics": position_statistics_result,
            "win_rate": win_rate_result,
            "expectancy": expectancy_result,
            "profit_factor": profit_factor_result,
            "maximum_drawdown": maximum_drawdown_result,
        },
    }


def scenario_constructor_exactly_six_dependencies():
    print("\n[Scenario 10] constructor requires exactly six dependencies")
    import inspect
    params = [
        p for p in inspect.signature(PerformanceSummaryService.__init__).parameters
        if p != "self"
    ]
    check(len(params) == 6, "PerformanceSummaryService.__init__ takes exactly six parameters beyond self")
    check(
        set(params) == {
            "trade_statistics_engine", "position_performance_engine", "win_rate_engine",
            "expectancy_engine", "profit_factor_engine", "maximum_drawdown_engine",
        },
        "the six constructor parameters are exactly the six Sprint 6 engines, named as expected",
    )
    fixture = _build_spies()
    check(isinstance(fixture["service"], PerformanceSummaryService), "constructs a PerformanceSummaryService instance with all six engines given")


def scenario_each_engine_called_exactly_once():
    print("\n[Scenario 1] every engine is called exactly once")
    fixture = _build_spies()
    trades = [_trade()]
    positions = [_position()]
    equity_curve = [100.0, 110.0]
    fixture["service"].build(trades, positions, equity_curve)
    engines = fixture["engines"]
    check(engines["trade_statistics_engine"].call_count == 1, "TradeStatisticsEngine.calculate() called exactly once")
    check(engines["position_performance_engine"].call_count == 1, "PositionPerformanceEngine.calculate() called exactly once")
    check(engines["win_rate_engine"].call_count == 1, "WinRateEngine.calculate() called exactly once")
    check(engines["expectancy_engine"].call_count == 1, "ExpectancyEngine.calculate() called exactly once")
    check(engines["profit_factor_engine"].call_count == 1, "ProfitFactorEngine.calculate() called exactly once")
    check(engines["maximum_drawdown_engine"].call_count == 1, "MaximumDrawdownEngine.calculate() called exactly once")
    check(len(fixture["log"]) == 6, "exactly six engine calls total were logged for a single build() call")


def scenario_call_order_locked():
    print("\n[Scenario 2] engines are called in the LOCKED order")
    fixture = _build_spies()
    fixture["service"].build([_trade()], [_position()], [100.0, 90.0])
    call_names = [entry[0] for entry in fixture["log"]]
    check(
        call_names == [
            "TradeStatisticsEngine", "PositionPerformanceEngine", "WinRateEngine",
            "ExpectancyEngine", "ProfitFactorEngine", "MaximumDrawdownEngine",
        ],
        "the six engines are invoked in exactly the LOCKED order",
    )
    check(call_names[0] == "TradeStatisticsEngine", "TradeStatisticsEngine is called first")
    check(call_names[1] == "PositionPerformanceEngine", "PositionPerformanceEngine is called second")
    check(call_names[2] == "WinRateEngine", "WinRateEngine is called third")
    check(call_names[3] == "ExpectancyEngine", "ExpectancyEngine is called fourth")
    check(call_names[4] == "ProfitFactorEngine", "ProfitFactorEngine is called fifth")
    check(call_names[-1] == "MaximumDrawdownEngine", "MaximumDrawdownEngine is called last (sixth)")


def scenario_trade_statistics_receives_trades():
    print("\n[Scenario 3] TradeStatisticsEngine receives exactly trades")
    fixture = _build_spies()
    trades = [_trade(1), _trade(2)]
    positions = [_position()]
    equity_curve = [100.0]
    fixture["service"].build(trades, positions, equity_curve)
    check(
        fixture["engines"]["trade_statistics_engine"].received_args is trades,
        "TradeStatisticsEngine.calculate() receives the exact `trades` object passed to build()",
    )


def scenario_position_performance_receives_positions():
    print("\n[Scenario 4] PositionPerformanceEngine receives exactly positions")
    fixture = _build_spies()
    trades = [_trade()]
    positions = [_position(1), _position(2)]
    equity_curve = [100.0]
    fixture["service"].build(trades, positions, equity_curve)
    check(
        fixture["engines"]["position_performance_engine"].received_args is positions,
        "PositionPerformanceEngine.calculate() receives the exact `positions` object passed to build()",
    )


def scenario_maximum_drawdown_receives_equity_curve():
    print("\n[Scenario 5] MaximumDrawdownEngine receives exactly equity_curve")
    fixture = _build_spies()
    trades = [_trade()]
    positions = [_position()]
    equity_curve = [100.0, 120.0, 90.0]
    fixture["service"].build(trades, positions, equity_curve)
    check(
        fixture["engines"]["maximum_drawdown_engine"].received_args is equity_curve,
        "MaximumDrawdownEngine.calculate() receives the exact `equity_curve` object passed to build()",
    )


def scenario_win_rate_receives_position_statistics_not_position():
    print("\n[Scenario 6] WinRateEngine receives position_statistics, not Position")
    fixture = _build_spies()
    fixture["service"].build([_trade()], [_position()], [100.0])
    received = fixture["engines"]["win_rate_engine"].received_args
    check(
        received is fixture["results"]["position_statistics"],
        "WinRateEngine.calculate() receives exactly the PositionPerformanceStatistics PositionPerformanceEngine returned",
    )
    check(isinstance(received, PositionPerformanceStatistics), "WinRateEngine's argument is a PositionPerformanceStatistics instance")
    check(not isinstance(received, Position), "WinRateEngine's argument is NOT a Position instance")


def scenario_expectancy_receives_position_statistics():
    print("\n[Scenario 7] ExpectancyEngine receives position_statistics")
    fixture = _build_spies()
    fixture["service"].build([_trade()], [_position()], [100.0])
    received = fixture["engines"]["expectancy_engine"].received_args
    check(
        received is fixture["results"]["position_statistics"],
        "ExpectancyEngine.calculate() receives exactly the PositionPerformanceStatistics PositionPerformanceEngine returned",
    )
    check(isinstance(received, PositionPerformanceStatistics), "ExpectancyEngine's argument is a PositionPerformanceStatistics instance")


def scenario_profit_factor_receives_position_statistics():
    print("\n[Scenario 8] ProfitFactorEngine receives position_statistics")
    fixture = _build_spies()
    fixture["service"].build([_trade()], [_position()], [100.0])
    received = fixture["engines"]["profit_factor_engine"].received_args
    check(
        received is fixture["results"]["position_statistics"],
        "ProfitFactorEngine.calculate() receives exactly the PositionPerformanceStatistics PositionPerformanceEngine returned",
    )
    check(isinstance(received, PositionPerformanceStatistics), "ProfitFactorEngine's argument is a PositionPerformanceStatistics instance")


def scenario_summary_holds_exact_identity_no_copy():
    print("\n[Scenario 9] PerformanceSummary holds the exact same objects (identity), not copies")
    fixture = _build_spies()
    summary = fixture["service"].build([_trade()], [_position()], [100.0])
    results = fixture["results"]
    check(isinstance(summary, PerformanceSummary), "build() returns a PerformanceSummary instance")
    check(summary.trade_statistics is results["trade_statistics"], "summary.trade_statistics IS the exact object TradeStatisticsEngine returned")
    check(summary.position_statistics is results["position_statistics"], "summary.position_statistics IS the exact object PositionPerformanceEngine returned")
    check(summary.win_rate == results["win_rate"], "summary.win_rate equals the exact float WinRateEngine returned")
    check(summary.expectancy is results["expectancy"], "summary.expectancy IS the exact object ExpectancyEngine returned")
    check(summary.profit_factor is results["profit_factor"], "summary.profit_factor IS the exact object ProfitFactorEngine returned")
    check(summary.maximum_drawdown is results["maximum_drawdown"], "summary.maximum_drawdown IS the exact object MaximumDrawdownEngine returned")
    fields = set(vars(summary).keys())
    check(
        fields == {
            "trade_statistics", "position_statistics", "win_rate",
            "expectancy", "profit_factor", "maximum_drawdown",
        },
        "PerformanceSummary has exactly the six LOCKED fields, no more",
    )


def scenario_inputs_not_mutated():
    print("\n[Scenario 11] trades/positions/equity_curve are never mutated")
    fixture = _build_spies()
    trades = [_trade(1), _trade(2)]
    positions = [_position(1), _position(2)]
    equity_curve = [100.0, 130.0, 90.0]
    trades_before = copy.deepcopy(trades)
    positions_before = copy.deepcopy(positions)
    equity_curve_before = copy.deepcopy(equity_curve)
    fixture["service"].build(trades, positions, equity_curve)
    check(trades == trades_before, "the input `trades` list is unchanged after build()")
    check(positions == positions_before, "the input `positions` list is unchanged after build()")
    check(equity_curve == equity_curve_before, "the input `equity_curve` list is unchanged after build()")


def scenario_no_public_method_other_than_build():
    print("\n[Scenario 12] PerformanceSummaryService exposes only build() publicly")
    public_methods = {name for name in dir(PerformanceSummaryService) if not name.startswith("_")}
    check(public_methods == {"build"}, "PerformanceSummaryService's public API is exactly {'build'}")
    check(len(public_methods) == 1, "PerformanceSummaryService exposes exactly one public method")


def main() -> int:
    scenario_each_engine_called_exactly_once()
    scenario_call_order_locked()
    scenario_trade_statistics_receives_trades()
    scenario_position_performance_receives_positions()
    scenario_maximum_drawdown_receives_equity_curve()
    scenario_win_rate_receives_position_statistics_not_position()
    scenario_expectancy_receives_position_statistics()
    scenario_profit_factor_receives_position_statistics()
    scenario_summary_holds_exact_identity_no_copy()
    scenario_constructor_exactly_six_dependencies()
    scenario_inputs_not_mutated()
    scenario_no_public_method_other_than_build()

    print("\n" + "=" * 60)
    print(f"PERFORMANCE SUMMARY SERVICE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())