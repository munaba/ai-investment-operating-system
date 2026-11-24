"""Offline tests for Evaluation/backtest_rules.py."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from Evaluation import backtest_rules as bt


def _closes(days: int = 300) -> dict[str, pd.Series]:
    index = pd.bdate_range("2024-01-01", periods=days)
    rng = np.random.default_rng(0)
    return {
        # UP rises 0.5% a day, DOWN falls 0.5%, the rest wander randomly.
        "UP": pd.Series(100 * 1.005 ** np.arange(days), index=index),
        "DOWN": pd.Series(100 * 0.995 ** np.arange(days), index=index),
        **{
            f"R{i}": pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, days)), index=index)
            for i in range(4)
        },
    }


def test_excess_uses_next_close_entry_and_five_day_exit() -> None:
    index = pd.bdate_range("2024-01-01", periods=10)
    frame = pd.DataFrame({"A": range(100, 110), "B": [100.0] * 10}, index=index, dtype=float)
    excess = bt.excess_returns(frame)
    forward_a = 106 / 101 - 1  # entry at row 1 (101), exit 5 trading days later at row 6 (106)
    assert excess.loc[index[0], "A"] == pytest.approx(forward_a - forward_a / 2)
    assert excess.iloc[-6:].isna().all().all()  # no exit bar yet


def test_rules_use_no_future_data() -> None:
    frame = bt.closes_frame(_closes())
    for name, rule in bt.RULES.items():
        full = rule(frame)
        truncated = rule(frame.iloc[:200])
        assert full.iloc[:200].equals(truncated), name


def test_momentum_picks_the_steady_riser_and_beats_the_universe() -> None:
    report = bt.backtest(_closes())
    stats = report["rules"]["top3_momentum_60d"]["selection"]
    assert stats["mean_excess"] > 0
    reversal = report["rules"]["bottom3_return_5d (reversal)"]["selection"]
    assert reversal["mean_excess"] < stats["mean_excess"]
    assert report["split"] < report["end"]


def test_top_n_marks_exactly_n_per_day() -> None:
    frame = bt.closes_frame(_closes())
    picks = bt._top_n(frame / frame.shift(20) - 1)
    assert (picks.iloc[25:].sum(axis=1) == bt.TOP_N).all()
