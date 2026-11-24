"""Evaluation of the registered v2 (top 5) and v3 (top 10) signals.

Rules: Docs/SIGNAL_EVALUATION.md, "v2 registration" and "v3 registration".
Reads ``v2_rankings`` read-only. For every rebalance signal date and every
pick:

* entry = close of the first session after the signal date,
* exit = close ``HOLD`` sessions after entry,
* excess = pick return minus the equal-weight mean return of every stock
  ranked that date (same entry and exit),
* net = excess minus the market's round-trip cost when the pick was not
  held at the previous rebalance.

A pick whose exit close does not exist yet (or is dated today, a live
quote) is pending. Verdict per market and version: fewer than 30 completed
picks -> DATA_TIDAK_CUKUP; else PASS if mean net excess > 0 and more than
50% of picks have positive net excess; else FAIL.

    python Evaluation/v2_evaluation.py [--db PATH]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):  # run as a script: make the repo importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Business.factor_model import HOLD, MARKETS, Market, yahoo_panel

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "investment_platform.db"
MIN_COMPLETED = 30
INSUFFICIENT = "DATA_TIDAK_CUKUP"
VERSIONS = {"v2": 5, "v3": 10}

Fetcher = Callable[[Market, date, date, tuple[str, ...]], tuple[pd.DataFrame, pd.DataFrame]]


def load_rebalances(db_path: Path) -> pd.DataFrame:
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_rankings'").fetchone()
        if not exists:
            return pd.DataFrame(columns=["market", "signal_date", "symbol", "rank"])
        return pd.read_sql_query(
            "SELECT market, signal_date, symbol, rank FROM v2_rankings WHERE is_rebalance = 1 "
            "ORDER BY market, signal_date, rank",
            conn,
        )


def _summary(picks: pd.DataFrame) -> dict:
    done = picks[picks["status"] == "complete"]
    n = len(done)
    out = {"completed": n, "pending": int((picks["status"] == "pending").sum())}
    if n:
        out["mean_net"] = float(done["net_excess"].mean())
        out["mean_excess"] = float(done["excess"].mean())
        out["hit_rate"] = float((done["net_excess"] > 0).mean())
    if n < MIN_COMPLETED:
        out["verdict"] = INSUFFICIENT
    elif out["mean_net"] > 0 and out["hit_rate"] > 0.5:
        out["verdict"] = "PASS"
    else:
        out["verdict"] = "FAIL"
    return out


def score_market(rows: pd.DataFrame, close: pd.DataFrame, market: Market, today: date,
                 hold: int = HOLD) -> pd.DataFrame:
    """One row per (version, signal date, pick) with its outcome."""
    close = close[close.index.date < today]  # completed sessions only
    records = []
    for version, top_k in VERSIONS.items():
        previous: set[str] = set()
        for signal_date, day in rows.groupby("signal_date", sort=True):
            picks = list(day.sort_values("rank").head(top_k)["symbol"])
            after = close.index[close.index.date > date.fromisoformat(signal_date)]
            entry = after[0] if len(after) > 0 else None
            exit_ = after[hold] if len(after) > hold else None
            universe = [s for s in day["symbol"] if s in close.columns]
            bench = None
            if entry is not None and exit_ is not None:
                fwd = (close.loc[exit_, universe] / close.loc[entry, universe] - 1).dropna()
                bench = float(fwd.mean()) if len(fwd) else None
            for symbol in picks:
                rec = {"market": market.name, "version": version, "signal_date": signal_date, "symbol": symbol,
                       "entry_date": entry.date().isoformat() if entry is not None else None,
                       "exit_date": exit_.date().isoformat() if exit_ is not None else None,
                       "return": None, "excess": None, "net_excess": None, "status": "pending"}
                if bench is not None and symbol in close.columns:
                    start, end = close.loc[entry, symbol], close.loc[exit_, symbol]
                    if pd.notna(start) and pd.notna(end) and start > 0:
                        ret = float(end / start - 1)
                        cost = market.round_trip_cost if symbol not in previous else 0.0
                        rec.update({"return": ret, "excess": ret - bench, "net_excess": ret - bench - cost,
                                    "status": "complete"})
                records.append(rec)
            previous = set(picks)
    return pd.DataFrame.from_records(records)


def evaluate(rebalances: pd.DataFrame, fetch: Fetcher | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    fetch = fetch or (lambda m, s, e, syms: yahoo_panel(m, s, e, syms))
    result: dict = {"rules": {"hold_sessions": HOLD, "min_completed": MIN_COMPLETED,
                              "versions": VERSIONS}, "markets": {}, "picks": []}
    for market_name, rows in rebalances.groupby("market"):
        market = MARKETS[market_name]
        start = date.fromisoformat(rows["signal_date"].min()) - timedelta(days=7)
        close, _ = fetch(market, start, today + timedelta(days=1), tuple(sorted(rows["symbol"].unique())))
        scored = score_market(rows, close, market, today)
        result["markets"][market_name] = {
            version: _summary(scored[scored["version"] == version]) for version in VERSIONS
        }
        result["markets"][market_name]["rebalances"] = int(rows["signal_date"].nunique())
        result["picks"].extend(json.loads(scored.to_json(orient="records")))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    report = evaluate(load_rebalances(args.db))
    print(json.dumps({k: report[k] for k in ("rules", "markets")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
