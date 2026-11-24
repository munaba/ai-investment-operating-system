"""Offline tests for Evaluation/factor_research.py (synthetic prices, no network)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from Evaluation import factor_research as fr


def _panel(days: int = 700, n: int = 24, seed: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Random walks where half the stocks carry a persistent positive drift,
    so medium-term momentum genuinely predicts the next month."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2020-01-01", periods=days)
    drift = np.where(np.arange(n) < n // 2, 0.0015, -0.0005)
    returns = rng.normal(drift, 0.015, size=(days, n))
    close = pd.DataFrame(100 * np.cumprod(1 + returns, axis=0), index=index, columns=[f"S{i:02d}" for i in range(n)])
    volume = pd.DataFrame(1e6, index=index, columns=close.columns)
    return close, volume


def test_factors_use_no_future_data() -> None:
    close, volume = _panel()
    full = fr.compute_factors(close, volume)
    cut = fr.compute_factors(close.iloc[:400], volume.iloc[:400])
    for name in full:
        pd.testing.assert_frame_equal(full[name].iloc[:400], cut[name], check_freq=False, obj=name)


def test_known_dates_exclude_unfinished_outcomes() -> None:
    close, _ = _panel(days=300)
    index = close.index
    dates = list(index[::20])
    t = index[200]
    known = fr._known_dates(dates, t, index, hold=20)
    # Every known date's exit close (21 rows later) is on or before t.
    assert all(index.get_loc(d) + 21 <= index.get_loc(t) for d in known)
    assert known and max(known) < t


def test_run_strategy_charges_cost_on_turnover() -> None:
    close, _ = _panel(days=300)
    excess = fr.excess_returns(close, 20)
    dates = list(close.index[260:261])
    constant = pd.Series(np.arange(close.shape[1], dtype=float), index=close.columns)
    periods = fr.run_strategy(lambda t: constant, dates, excess, top_k=5)
    row = periods.iloc[0]
    assert row["gross"] - row["net"] == pytest.approx(fr.ROUND_TRIP_COST)  # first period: full turnover


def test_momentum_logics_beat_the_universe_when_drift_persists() -> None:
    close, volume = _panel()
    report = fr.research(close, volume, hold=20, top_k=5)
    for name in ("momentum_60d", "ic_weighted_walk_forward"):
        assert report["results"][name]["selection"]["mean_net"] > 0, name
    assert report["chosen_on_selection"] is not None


def test_current_picks_returns_top_k_for_the_last_date() -> None:
    close, volume = _panel()
    result = fr.current_picks(close, volume, hold=20, top_k=5)
    assert result["as_of"] == close.index[-1].date().isoformat()
    assert len(result["picks"]) == 5
    # The drifting half should dominate today's picks.
    assert sum(int(p["symbol"][1:]) < 12 for p in result["picks"]) >= 4
