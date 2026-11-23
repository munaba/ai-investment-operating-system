"""Offline tests for Evaluation/signal_evaluation.py (pre-registered rules)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from Evaluation import signal_evaluation as se


def _days(start: date, n: int) -> list[date]:
    """n consecutive weekdays from start (inclusive)."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _series(dates: list[date], prices: list[float]) -> pd.Series:
    return pd.Series(prices, index=dates)


def _signals(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    return se.first_signal_per_day(pd.DataFrame(rows, columns=["scan_time", "symbol", "recommendation"]))


def test_only_first_scan_per_symbol_per_wib_day_counts() -> None:
    sig = _signals([
        ("2026-11-24T02:05:00+00:00", "BBCA", "BUY"),   # 09:05 WIB
        ("2026-11-24T02:10:00+00:00", "BBCA", "WAIT"),  # same WIB day -> ignored
        ("2026-11-24T18:00:00+00:00", "BBCA", "SELL"),  # 01:00 WIB on the 25th -> new day
    ])
    assert list(sig["recommendation"]) == ["BUY", "SELL"]
    assert list(sig["scan_date"]) == [date(2026, 11, 24), date(2026, 11, 25)]


def test_entry_is_next_trading_day_and_exit_five_days_later() -> None:
    days = _days(date(2026, 11, 23), 10)  # Mon 23 .. Fri 4 Dec
    closes = {
        "AAA": _series(days, [100, 100, 110, 110, 110, 110, 121, 121, 121, 121]),
        "BBB": _series(days, [100] * 10),
    }
    sig = _signals([("2026-11-24T02:05:00+00:00", "AAA", "BUY")])  # scan on Tue 24
    scored = se.score_signals(sig, closes, ["AAA", "BBB"])
    row = scored.iloc[0]
    assert row["entry_date"] == days[2]          # Wed 25 (first day after the scan date)
    assert row["exit_date"] == days[7]           # 5 trading days later
    assert row["forward_return"] == pytest.approx(121 / 110 - 1)
    assert row["benchmark_return"] == pytest.approx((0.1 + 0.0) / 2)
    assert row["excess_return"] == pytest.approx(0.1 - 0.05)


def test_signal_without_exit_bar_is_pending() -> None:
    days = _days(date(2026, 11, 23), 4)
    closes = {"AAA": _series(days, [1, 2, 3, 4])}
    sig = _signals([("2026-11-24T02:05:00+00:00", "AAA", "BUY")])
    scored = se.score_signals(sig, closes, ["AAA"])
    assert scored.iloc[0]["status"] == "pending"
    assert se.summarize(scored)["by_recommendation"]["BUY"] == {"completed": 0, "pending": 1}


def _scored(excess: list[float], rec: str = "BUY") -> pd.DataFrame:
    return pd.DataFrame({
        "recommendation": [rec] * len(excess),
        "status": ["complete"] * len(excess),
        "forward_return": excess,
        "excess_return": excess,
    })


def test_verdict_insufficient_below_thirty_buy_signals() -> None:
    assert se.summarize(_scored([0.05] * 29))["verdict"] == se.INSUFFICIENT


def test_verdict_pass_needs_positive_excess_and_hit_rate_above_half() -> None:
    assert se.summarize(_scored([0.02] * 20 + [-0.01] * 10))["verdict"] == "PASS"


def test_verdict_fail_when_hit_rate_is_not_above_half() -> None:
    # Mean excess is positive (one big winner) but only half the picks beat the benchmark.
    assert se.summarize(_scored([0.30] + [0.01] * 14 + [-0.01] * 15))["verdict"] == "FAIL"


def test_wait_and_sell_never_decide_the_verdict() -> None:
    scored = pd.concat([_scored([0.05] * 40, "WAIT"), _scored([-0.05] * 40, "SELL")])
    summary = se.summarize(scored)
    assert summary["verdict"] == se.INSUFFICIENT
    assert summary["by_recommendation"]["SELL"]["hit_rate"] == 1.0
    assert "hit_rate" not in summary["by_recommendation"]["WAIT"]


def test_evaluate_splits_official_from_exploratory() -> None:
    days = _days(date(2026, 11, 10), 25)
    closes = {"AAA": _series(days, [100 + i for i in range(25)]), "BBB": _series(days, [100] * 25)}
    sig = _signals([
        ("2026-11-11T02:05:00+00:00", "AAA", "BUY"),  # before registration -> exploratory
        ("2026-11-24T02:05:00+00:00", "AAA", "BUY"),  # official
    ])
    result = se.evaluate(sig, fetch=lambda symbols, start, end: closes, today=date(2026, 12, 14))
    assert result["official"]["by_recommendation"]["BUY"]["completed"] == 1
    assert result["exploratory"]["by_recommendation"]["BUY"]["completed"] == 1
    assert result["rules"]["registered_on"] == "2026-11-24"


def test_rules_match_the_registered_document() -> None:
    doc = (se._REPO_ROOT / "Docs" / "SIGNAL_EVALUATION.md").read_text(encoding="utf-8")
    assert f"**{se.MIN_BUY_SIGNALS}**" in doc
    assert f"{se.HORIZON_TRADING_DAYS} trading days after entry" in doc
    assert se.REGISTERED_ON.isoformat() in doc
