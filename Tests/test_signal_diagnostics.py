"""Offline tests for Evaluation/signal_diagnostics.py (exploratory breakdowns)."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import pytest

from Evaluation import signal_diagnostics as sd
from Evaluation import signal_evaluation as se


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _inputs(n_symbols: int) -> tuple[pd.DataFrame, dict]:
    """One scan day, n symbols. Symbol i scores 10+i and its price rises
    i percent over the horizon, so score and excess return are perfectly
    rank-correlated; the technical factor is the reverse."""
    days = _weekdays(date(2026, 11, 2), 12)
    rows, closes = [], {}
    for i in range(n_symbols):
        symbol = f"S{i:02d}"
        rows.append({
            "scan_time": "2026-11-02T02:05:00+00:00",
            "symbol": symbol,
            "recommendation": "BUY",
            "confidence": "HIGH" if i % 2 else "MEDIUM",
            "score": 10 + i,
            "score_breakdown_json": json.dumps({"technical_contribution": -i, "sentiment_contribution": 0}),
        })
        prices = [100.0] * 12
        for k in range(6, 12):  # exit bar is the 7th trading day (entry + 5)
            prices[k] = 100.0 * (1 + i / 100)
        closes[symbol] = pd.Series(prices, index=days)
    return se.first_signal_per_day(pd.DataFrame(rows)), closes


def test_correlations_follow_the_factor_direction() -> None:
    inputs, closes = _inputs(12)
    report = sd.diagnose(inputs, fetch=lambda symbols, start, end: closes, today=date(2026, 12, 31))
    assert report["completed"] == 12
    assert report["correlation"]["score"] == pytest.approx(1.0)
    assert report["correlation"]["technical"] == pytest.approx(-1.0)
    # A constant factor carries no information and is reported as None.
    assert report["correlation"]["sentiment"] is None


def test_groups_and_small_sample_flag() -> None:
    inputs, closes = _inputs(12)
    report = sd.diagnose(inputs, fetch=lambda symbols, start, end: closes, today=date(2026, 12, 31))
    assert set(report["by_confidence"]) == {"HIGH", "MEDIUM"}
    assert all(group["too_small"] for group in report["by_confidence"].values())  # 6 each < MIN_GROUP
    assert sum(group["completed"] for group in report["by_score_band"].values()) == 12
    assert len(report["by_score_band"]) == 3


def test_no_signals_is_an_empty_report() -> None:
    empty = se.first_signal_per_day(pd.DataFrame(columns=[
        "scan_time", "symbol", "recommendation", "confidence", "score", "score_breakdown_json",
    ]))
    report = sd.diagnose(empty, fetch=lambda symbols, start, end: {}, today=date(2026, 12, 31))
    assert report["completed"] == 0
