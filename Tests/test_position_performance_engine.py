"""Standalone regression checks for
``Business.position_performance_engine.PositionPerformanceEngine``.

Covers Sprint 6 STEP 3 (position-level P/L statistics, the ONE place
in Sprint 6 that reads ``Position.realized_pnl``):

* constructor takes no dependency;
* ``calculate()`` on an empty list returns all-zero fields;
* all profit / all loss / all breakeven / mixed positions;
* ``gross_profit``/``gross_loss`` sums are correct (``gross_loss`` is
  positive -- ``abs(realized_pnl)`` accumulated, per LOCKED DECISION 5);
* ``net_profit`` == ``gross_profit - gross_loss``;
* ``average_win``/``average_loss`` correct, including the zero-division
  guards;
* the return value is a real ``PositionPerformanceStatistics``
  instance;
* the input list (and its ``Position`` elements) are never mutated.

Uses hand-built ``Position`` instances directly -- no database, no
repository, no I/O, matching every other ``Tests/test_*.py`` file in
this project.

Run directly with ``python Tests/test_position_performance_engine.py``
-- no external test framework required.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.position_performance_engine import (  # noqa: E402
    PositionPerformanceEngine,
    PositionPerformanceStatistics,
)
from Database.models import Position  # noqa: E402

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


def _position(
    position_id: int,
    realized_pnl: float,
    symbol: str = "BBCA",
    status: str = "closed",
) -> Position:
    return Position(
        position_id=position_id,
        account_id="paper-id",
        symbol=symbol,
        quantity=100.0,
        average_price=9500.0,
        realized_pnl=realized_pnl,
        status=status,
        created_at="2026-08-01T09:00:00+00:00",
        updated_at="2026-08-01T09:00:00+00:00",
    )


def scenario_constructor_no_dependency():
    print("\n[Scenario 1] constructor takes no dependency")
    engine = PositionPerformanceEngine()
    check(isinstance(engine, PositionPerformanceEngine), "constructs a PositionPerformanceEngine instance")


def scenario_empty_list():
    print("\n[Scenario 2] calculate() on an empty list")
    engine = PositionPerformanceEngine()
    result = engine.calculate([])
    check(isinstance(result, PositionPerformanceStatistics), "returns a PositionPerformanceStatistics instance")
    check(result.winning_positions == 0, "winning_positions is 0 for an empty list")
    check(result.losing_positions == 0, "losing_positions is 0 for an empty list")
    check(result.breakeven_positions == 0, "breakeven_positions is 0 for an empty list")
    check(result.gross_profit == 0.0, "gross_profit is 0.0 for an empty list")
    check(result.gross_loss == 0.0, "gross_loss is 0.0 for an empty list")
    check(result.net_profit == 0.0, "net_profit is 0.0 for an empty list")
    check(result.average_win == 0.0, "average_win is 0.0 for an empty list")
    check(result.average_loss == 0.0, "average_loss is 0.0 for an empty list")


def scenario_all_profit():
    print("\n[Scenario 3] all positions are profitable")
    engine = PositionPerformanceEngine()
    positions = [
        _position(1, 100_000.0),
        _position(2, 50_000.0),
        _position(3, 25_000.0),
    ]
    result = engine.calculate(positions)
    check(result.winning_positions == 3, "winning_positions == 3 when all positions profit")
    check(result.losing_positions == 0, "losing_positions == 0 when all positions profit")
    check(result.breakeven_positions == 0, "breakeven_positions == 0 when all positions profit")
    check(result.gross_profit == 175_000.0, "gross_profit sums all positive realized_pnl values")
    check(result.gross_loss == 0.0, "gross_loss is 0.0 when no position lost")
    check(result.net_profit == 175_000.0, "net_profit == gross_profit - gross_loss (gross_loss is 0)")
    check(result.average_win == 175_000.0 / 3, "average_win == gross_profit / winning_positions")
    check(result.average_loss == 0.0, "average_loss is 0.0 when losing_positions is 0")


def scenario_all_loss():
    print("\n[Scenario 4] all positions are losses")
    engine = PositionPerformanceEngine()
    positions = [
        _position(1, -40_000.0),
        _position(2, -10_000.0),
    ]
    result = engine.calculate(positions)
    check(result.losing_positions == 2, "losing_positions == 2 when all positions lose")
    check(result.winning_positions == 0, "winning_positions == 0 when all positions lose")
    check(result.gross_loss == 50_000.0, "gross_loss is the sum of abs(realized_pnl) -- positive, not negative")
    check(result.gross_profit == 0.0, "gross_profit is 0.0 when no position won")
    check(result.net_profit == -50_000.0, "net_profit == gross_profit - gross_loss == -50000")
    check(result.average_loss == 25_000.0, "average_loss == gross_loss / losing_positions (positive)")
    check(result.average_win == 0.0, "average_win is 0.0 when winning_positions is 0")


def scenario_all_breakeven():
    print("\n[Scenario 5] all positions are breakeven")
    engine = PositionPerformanceEngine()
    positions = [_position(1, 0.0), _position(2, 0.0)]
    result = engine.calculate(positions)
    check(result.breakeven_positions == 2, "breakeven_positions == 2 when all realized_pnl are 0")
    check(result.winning_positions == 0, "winning_positions == 0 when all positions are breakeven")
    check(result.losing_positions == 0, "losing_positions == 0 when all positions are breakeven")
    check(result.gross_profit == 0.0, "gross_profit is 0.0 when all positions are breakeven")
    check(result.gross_loss == 0.0, "gross_loss is 0.0 when all positions are breakeven")
    check(result.net_profit == 0.0, "net_profit is 0.0 when all positions are breakeven")


def scenario_mixed():
    print("\n[Scenario 6] a mix of profit, loss, and breakeven positions")
    engine = PositionPerformanceEngine()
    positions = [
        _position(1, 100_000.0),
        _position(2, -30_000.0),
        _position(3, 0.0),
        _position(4, 20_000.0),
        _position(5, -10_000.0),
    ]
    result = engine.calculate(positions)
    check(result.winning_positions == 2, "winning_positions counts only realized_pnl > 0")
    check(result.losing_positions == 2, "losing_positions counts only realized_pnl < 0")
    check(result.breakeven_positions == 1, "breakeven_positions counts only realized_pnl == 0")
    check(result.gross_profit == 120_000.0, "gross_profit sums only the positive realized_pnl values")
    check(result.gross_loss == 40_000.0, "gross_loss sums abs() of only the negative realized_pnl values")
    check(result.net_profit == 80_000.0, "net_profit == gross_profit - gross_loss for a mixed set")
    check(result.average_win == 60_000.0, "average_win == gross_profit / winning_positions for a mixed set")
    check(result.average_loss == 20_000.0, "average_loss == gross_loss / losing_positions for a mixed set")


def scenario_output_is_dataclass_instance():
    print("\n[Scenario 7] output dataclass shape")
    engine = PositionPerformanceEngine()
    result = engine.calculate([])
    fields = set(vars(result).keys())
    check(
        fields == {
            "winning_positions", "losing_positions", "breakeven_positions",
            "gross_profit", "gross_loss", "net_profit", "average_win", "average_loss",
        },
        "PositionPerformanceStatistics has exactly the eight LOCKED fields, no more",
    )


def scenario_input_not_mutated():
    print("\n[Scenario 8] input list and its Position elements are never mutated")
    engine = PositionPerformanceEngine()
    positions = [_position(1, 100_000.0), _position(2, -30_000.0)]
    positions_before = copy.deepcopy(positions)
    engine.calculate(positions)
    check(positions == positions_before, "the input list of Position instances is unchanged after calculate()")
    check(len(positions) == 2, "calculate() does not add or remove elements from the input list")


def scenario_no_public_method_other_than_calculate():
    print("\n[Scenario 9] PositionPerformanceEngine exposes only calculate() publicly")
    public_methods = {name for name in dir(PositionPerformanceEngine) if not name.startswith("_")}
    check(public_methods == {"calculate"}, "PositionPerformanceEngine's public API is exactly {'calculate'}")


def main() -> int:
    scenario_constructor_no_dependency()
    scenario_empty_list()
    scenario_all_profit()
    scenario_all_loss()
    scenario_all_breakeven()
    scenario_mixed()
    scenario_output_is_dataclass_instance()
    scenario_input_not_mutated()
    scenario_no_public_method_other_than_calculate()

    print("\n" + "=" * 60)
    print(f"POSITION PERFORMANCE ENGINE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())