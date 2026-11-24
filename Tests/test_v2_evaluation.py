"""Offline tests for Evaluation/v2_evaluation.py (registered v2/v3 outcome rules)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from Business.factor_model import IDX
from Evaluation import v2_evaluation as ev


def _close(days: int = 40) -> pd.DataFrame:
    index = pd.bdate_range("2026-12-01", periods=days)
    data = {f"S{i:02d}": [100.0 * (1 + 0.001 * i) ** k for k in range(days)] for i in range(12)}
    return pd.DataFrame(data, index=index)


def _rows(signal_date: str, n: int = 12) -> pd.DataFrame:
    # Rank 1 = S11 (fastest riser) ... rank 12 = S00.
    return pd.DataFrame({"market": "idx", "signal_date": signal_date,
                         "symbol": [f"S{i:02d}" for i in range(n - 1, -1, -1)], "rank": range(1, n + 1)})


def test_entry_next_session_exit_twenty_sessions_later_and_cost_on_new_picks() -> None:
    close = _close()
    scored = ev.score_market(_rows("2026-12-01"), close, IDX, today=date(2027, 6, 1))
    v2 = scored[scored["version"] == "v2"]
    assert len(v2) == 5 and set(v2["status"]) == {"complete"}
    first = v2.iloc[0]
    assert first["entry_date"] == close.index[1].date().isoformat()
    assert first["exit_date"] == close.index[21].date().isoformat()
    s11 = close["S11"]
    expected_ret = s11.iloc[21] / s11.iloc[1] - 1
    bench = (close.iloc[21] / close.iloc[1] - 1).mean()
    assert first["return"] == pytest.approx(expected_ret)
    assert first["excess"] == pytest.approx(expected_ret - bench)
    assert first["net_excess"] == pytest.approx(expected_ret - bench - IDX.round_trip_cost)
    assert len(scored[scored["version"] == "v3"]) == 10


def test_pick_without_exit_or_with_exit_today_is_pending() -> None:
    close = _close(25)
    scored = ev.score_market(_rows("2026-12-01"), close, IDX, today=close.index[21].date())
    assert set(scored["status"]) == {"pending"}  # the exit bar is dated today


def test_repeat_picks_pay_no_cost() -> None:
    close = _close(60)
    rows = pd.concat([_rows("2026-12-01"), _rows(close.index[20].date().isoformat())])
    scored = ev.score_market(rows, close, IDX, today=date(2027, 6, 1))
    second = scored[(scored["version"] == "v2") & (scored["signal_date"] != "2026-12-01")]
    assert (second["net_excess"] == second["excess"]).all()


def test_verdict_needs_thirty_completed_picks() -> None:
    picks = pd.DataFrame({"status": ["complete"] * 29, "excess": [0.01] * 29, "net_excess": [0.01] * 29})
    assert ev._summary(picks)["verdict"] == ev.INSUFFICIENT
    picks = pd.DataFrame({"status": ["complete"] * 30, "excess": [0.01] * 30, "net_excess": [0.01] * 30})
    assert ev._summary(picks)["verdict"] == "PASS"
    picks["net_excess"] = [-0.01] * 30
    assert ev._summary(picks)["verdict"] == "FAIL"


def test_evaluate_reports_each_market_and_version() -> None:
    close = _close()
    report = ev.evaluate(_rows("2026-12-01"), fetch=lambda m, s, e, syms: (close, close), today=date(2027, 6, 1))
    idx = report["markets"]["idx"]
    assert idx["v2"]["completed"] == 5 and idx["v3"]["completed"] == 10
    assert idx["rebalances"] == 1 and len(report["picks"]) == 15


def test_missing_table_gives_an_empty_report(tmp_path) -> None:
    import sqlite3

    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    assert ev.evaluate(ev.load_rebalances(db))["markets"] == {}
