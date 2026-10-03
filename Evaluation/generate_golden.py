"""Regenerate Evaluation/golden_cases/*.json FROM the independent reference.

This replaces the hand-written (guessed) golden files. Expected values come
from Evaluation/reference_impl.py only; run_eval.py then checks the engine
agrees. Run:

    python Evaluation/generate_golden.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJ))

from Evaluation.reference_impl import (  # noqa: E402
    ref_expectancy,
    ref_forex_maximum_loss,
    ref_maximum_drawdown,
    ref_profit_factor,
)

OUT = _PROJ / "Evaluation" / "golden_cases"
OUT.mkdir(parents=True, exist_ok=True)

EXPECTANCY_CASES = [
    # (winning, losing, breakeven, average_win, average_loss)
    (7, 3, 0, 100.0, 50.0),
    (0, 5, 0, 0.0, 100.0),
    (5, 5, 0, 100.0, 100.0),
    (0, 0, 0, 0.0, 0.0),
    (100, 50, 0, 150.0, 50.0),
    (1, 1, 8, 1000.0, 400.0),
]

DRAWDOWN_CASES = [
    [100.0, 110.0, 105.0, 115.0, 108.0, 120.0],
    [100.0],
    [100.0, 90.0, 80.0, 70.0],
    [100.0, 110.0, 120.0, 130.0],
    [],
    [100.0, 100.0, 100.0],
    [10000.0, 10500.0, 11000.0, 10800.0],
]

PROFIT_FACTOR_CASES = [
    # (gross_profit, gross_loss)
    (1500.0, 500.0),
    (0.0, 500.0),
    (500.0, 0.0),
    (0.0, 0.0),
    (1e-9, 1e-9),
    (1e12, 1.0),
]

FOREX_MAX_LOSS_CASES = [
    # (pair, entry, stop, quantity)
    ("EUR/USD", 1.1000, 1.0950, 10000.0),
    ("EUR/USD", 1.1000, 1.0900, 100000.0),
    ("GBP/USD", 1.2500, 1.2460, 25000.0),
    ("GBP/USD", 1.3000, 1.2900, 50000.0),
    ("EUR/USD", 1.1000, 1.1050, 10000.0),
    ("eurusd", 1.0500, 1.0450, 10000.0),
]


def main() -> None:
    expectancy = [
        {
            "input": {
                "winning_positions": w,
                "losing_positions": l,
                "breakeven_positions": b,
                "average_win": aw,
                "average_loss": al,
            },
            "expected": {"expectancy": ref_expectancy(w, l, b, aw, al)},
        }
        for (w, l, b, aw, al) in EXPECTANCY_CASES
    ]
    drawdown = [
        {"input": {"equity_curve": c}, "expected": {"maximum_drawdown": ref_maximum_drawdown(c)}}
        for c in DRAWDOWN_CASES
    ]
    profit = [
        {"input": {"gross_profit": gp, "gross_loss": gl},
         "expected": {"profit_factor": ref_profit_factor(gp, gl)}}
        for (gp, gl) in PROFIT_FACTOR_CASES
    ]
    forex = [
        {"input": {"pair": p, "entry_price": e, "stop_loss": s, "quantity": q},
         "expected": {"max_loss": str(ref_forex_maximum_loss(p, e, s, q))}}
        for (p, e, s, q) in FOREX_MAX_LOSS_CASES
    ]

    files = {
        "l2_expectancy_golden.json": expectancy,
        "l2_max_drawdown_golden.json": drawdown,
        "l2_profit_factor_golden.json": profit,
        "l2_forex_max_loss_golden.json": forex,
    }
    for name, payload in files.items():
        (OUT / name).write_text(json.dumps(payload, indent=2))
        print(f"wrote {name}: {len(payload)} cases")


if __name__ == "__main__":
    main()