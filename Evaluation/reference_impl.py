"""Independent reference implementations for AIOS L2 deterministic engines.

CRITICAL: these are deliberately naive, dependency-free implementations
written from the engine's own documented contract (module docstring +
``calculate()`` docstring). They exist SOLELY to cross-check the engine.
They must never be imported by production code.

ponytail: intentionally O(N^2) / string-based where the engine is
O(N) / Decimal-based -- that divergence is the point of the check.
Add a faster reference only if a divergence ever proves to be an engine bug.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List


# ---------------------------------------------------------------------------
# Business/expectancy_engine.py -- ExpectancyEngine.calculate
# Contract (module docstring L11-35):
#     total = winning + losing + breakeven
#     expectancy = (winning/total * average_win) - (losing/total * average_loss)
#     total == 0 -> expectancy = 0.0
# ---------------------------------------------------------------------------


def ref_expectancy(
    winning_positions: int,
    losing_positions: int,
    breakeven_positions: int,
    average_win: float,
    average_loss: float,
) -> float:
    total = winning_positions + losing_positions + breakeven_positions
    if total == 0:
        return 0.0
    win_rate = winning_positions / total
    loss_rate = losing_positions / total
    return (win_rate * average_win) - (loss_rate * average_loss)


# ---------------------------------------------------------------------------
# Business/maximum_drawdown_engine.py -- MaximumDrawdownEngine.calculate
# Contract (calculate() docstring L90-95): largest (peak - equity) / peak
# over the running maximum, starting from equity_curve[0]. len < 2 -> 0.0.
# Reference is deliberately O(N^2) brute force.
# ---------------------------------------------------------------------------


def ref_maximum_drawdown(equity_curve: List[float]) -> float:
    """Brute-force O(N^2): peak is the max over curve[0..i] (running peak,
    inclusive of i), then worst (peak - curve[i]) / peak over all i."""
    if len(equity_curve) < 2:
        return 0.0
    worst = 0.0
    n = len(equity_curve)
    for i in range(n):
        peak = equity_curve[0]
        for j in range(0, i + 1):
            if equity_curve[j] > peak:
                peak = equity_curve[j]
        if peak == 0:
            continue
        drawdown = (peak - equity_curve[i]) / peak
        if drawdown > worst:
            worst = drawdown
    return worst


# ---------------------------------------------------------------------------
# Business/profit_factor_engine.py -- ProfitFactorEngine.calculate
# Contract (calculate() docstring L90-96): gross_profit / gross_loss;
# gross_loss == 0 -> 0.0, never inf/-inf/NaN/None.
# ---------------------------------------------------------------------------


def ref_profit_factor(gross_profit: float, gross_loss: float) -> float:
    if gross_loss == 0:
        return 0.0
    return gross_profit / gross_loss


# ---------------------------------------------------------------------------
# Business/forex_max_loss_policy.py -- calculate_maximum_loss
# Contract (docstring L127-130):
#     pip_distance = abs(entry_price - stop_loss) / pip_size
#     maximum_loss = pip_distance * pip_value
# Supported pip-value pairs (via forex_pip_policy): USD-quoted only.
# ---------------------------------------------------------------------------

SUPPORTED_PAIRS = ("EUR/USD", "GBP/USD")

# Pip size: standard 1 pip == 0.0001 for non-JPY, 0.01 for JPY pairs.
PIP_SIZE = Decimal("0.0001")


def ref_forex_maximum_loss(
    pair: str, entry_price: float, stop_loss: float, quantity: float
) -> Decimal:
    """Naive string/Decimal reference -- no rounding applied."""
    candidate = pair.strip().upper()
    if "/" in candidate:
        base, quote = candidate.split("/")
        normalized = f"{base}/{quote}"
    elif len(candidate) == 6 and candidate.isalpha():
        normalized = f"{candidate[:3]}/{candidate[3:]}"
    else:
        raise ValueError(f"malformed pair: {pair!r}")
    if normalized not in SUPPORTED_PAIRS:
        raise ValueError(f"unsupported pair: {pair!r} -> {normalized!r} not in {SUPPORTED_PAIRS}")

    entry = Decimal(str(entry_price))
    stop = Decimal(str(stop_loss))
    qty = Decimal(str(quantity))

    if entry <= 0 or stop <= 0 or qty <= 0:
        raise ValueError("all inputs must be strictly positive")

    pip_size = PIP_SIZE
    distance = abs(entry - stop)
    # pip_value == pip_size * quantity (USD-quoted pair, quote == USD)
    pip_value = pip_size * qty
    return (distance / pip_size) * pip_value
# ---------------------------------------------------------------------------
# Business/position_performance_engine.py -- PositionPerformanceEngine.calculate
# Contract: computes win/loss/breakeven counts, gross profit/loss, net profit,
# average win/loss directly from realized_pnl.
# ---------------------------------------------------------------------------

def ref_position_performance(pnls: List[float]) -> dict:
    winning = 0
    losing = 0
    breakeven = 0
    gross_profit = 0.0
    gross_loss = 0.0
    
    for pnl in pnls:
        if pnl > 0:
            winning += 1
            gross_profit += pnl
        elif pnl < 0:
            losing += 1
            gross_loss += abs(pnl)
        else:
            breakeven += 1
            
    net = gross_profit - gross_loss
    avg_win = gross_profit / winning if winning > 0 else 0.0
    avg_loss = gross_loss / losing if losing > 0 else 0.0
    
    return {
        "winning_positions": winning,
        "losing_positions": losing,
        "breakeven_positions": breakeven,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_profit": net,
        "average_win": avg_win,
        "average_loss": avg_loss,
    }
