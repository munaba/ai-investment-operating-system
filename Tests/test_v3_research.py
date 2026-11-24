"""Offline tests for Evaluation/v3_research.py (synthetic prices, no network)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from Evaluation import v3_research as v3


def _close(days: int = 500, n: int = 30, seed: int = 7, down: bool = False) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2023-01-02", periods=days)
    drift = np.linspace(0.0015, -0.0005, n) - (0.002 if down else 0.0)
    returns = rng.normal(drift, 0.012, (days, n))
    return pd.DataFrame(100 * np.cumprod(1 + returns, axis=0), index=index, columns=[f"S{i:02d}" for i in range(n)])


def test_trend_candidates_beat_the_universe_when_drift_persists() -> None:
    close = _close()
    for name in ("A_v2_top5", "B_top10"):
        m = v3.measures(v3.simulate(close, v3.CANDIDATES[name], cost=0.001))
        assert m["mean_net"] > 0, name
        assert m["positive_share"] == 1.0, name


def test_top10_depends_less_on_the_single_best_pick() -> None:
    close = _close()
    a = v3.measures(v3.simulate(close, v3.CANDIDATES["A_v2_top5"], cost=0.001))
    b = v3.measures(v3.simulate(close, v3.CANDIDATES["B_top10"], cost=0.001))
    # Removing one pick out of ten costs less than one out of five.
    assert (b["mean_net"] - b["without_best"]) < (a["mean_net"] - a["without_best"])


def test_regime_filter_holds_the_universe_in_a_falling_market() -> None:
    rows = v3.simulate(_close(down=True), v3.CANDIDATES["C_top10_regime"], cost=0.001)
    held_universe = rows[~rows["held"]]
    assert len(held_universe) > 0
    assert (held_universe["net"] == 0).all()


def test_improvements_counts_each_better_measure() -> None:
    base = {"without_best": -0.02, "beat_share": 0.50, "worst_drawdown": -0.30}
    assert v3.improvements({"without_best": -0.01, "beat_share": 0.49, "worst_drawdown": -0.20}, base) == 2


def test_validation_universes_do_not_overlap_the_development_sets() -> None:
    from Business.factor_model import IDX, US

    assert not set(v3.IDX_VALIDATION) & set(IDX.universe)
    assert not set(v3.US_VALIDATION) & set(US.universe)
