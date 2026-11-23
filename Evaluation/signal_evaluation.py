"""Pre-registered evaluation of AIOS scan signals (see Docs/SIGNAL_EVALUATION.md).

    python Evaluation/signal_evaluation.py                # live DB, prices from Yahoo
    python Evaluation/signal_evaluation.py --db PATH

The database is opened read-only. Price fetching is injectable so the
logic is tested offline (Tests/test_signal_evaluation.py).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

# ---- Pre-registered rules (Docs/SIGNAL_EVALUATION.md). Do not edit. --------
HORIZON_TRADING_DAYS = 5
MIN_BUY_SIGNALS = 30
HIT_RATE_THRESHOLD = 0.5
REGISTERED_ON = date(2026, 11, 24)
RECOMMENDATIONS = ("BUY", "WAIT", "SELL")
# ---------------------------------------------------------------------------

WIB = "Asia/Jakarta"
INSUFFICIENT = "DATA_TIDAK_CUKUP"

#: symbol -> Series of daily closes indexed by date (datetime.date)
Closes = Dict[str, pd.Series]
PriceFetcher = Callable[[Iterable[str], date, date], Closes]

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _REPO_ROOT / "data" / "investment_platform.db"


def load_signals(db_path: Path) -> pd.DataFrame:
    """Successful BUY/WAIT/SELL rows, one per symbol per WIB date (first scan wins)."""
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        rows = pd.read_sql_query(
            "SELECT scan_time, symbol, recommendation FROM ranking_snapshots "
            "WHERE status = 'success' AND recommendation IN ('BUY', 'WAIT', 'SELL')",
            conn,
        )
    return first_signal_per_day(rows)


def first_signal_per_day(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows.assign(scan_date=pd.Series(dtype="object"))
    scan_time = pd.to_datetime(rows["scan_time"], utc=True, format="ISO8601").dt.tz_convert(WIB)
    out = rows.assign(scan_time=scan_time, scan_date=scan_time.dt.date)
    out = out.sort_values("scan_time").drop_duplicates(["symbol", "scan_date"], keep="first")
    return out.reset_index(drop=True)


def yahoo_closes(symbols: Iterable[str], start: date, end: date) -> Closes:
    """Daily closes from Yahoo Finance for IDX symbols (adds the .JK suffix)."""
    import yfinance as yf

    closes: Closes = {}
    for symbol in symbols:
        ticker = symbol if "." in symbol else f"{symbol}.JK"
        history = yf.Ticker(ticker).history(
            start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), interval="1d",
            auto_adjust=True, timeout=30,
        )
        if history.empty:
            continue
        series = history["Close"].dropna()
        series.index = [ts.date() for ts in series.index]
        closes[symbol] = series
    return closes


def _entry_exit(series: pd.Series, scan_date: date) -> Optional[tuple[date, date]]:
    dates = [d for d in series.index if d > scan_date]
    if len(dates) <= HORIZON_TRADING_DAYS:
        return None  # pending: no entry yet, or exit not reached
    return dates[0], dates[HORIZON_TRADING_DAYS]


def _forward_return(series: pd.Series, entry: date, exit_: date) -> Optional[float]:
    if entry not in series.index or exit_ not in series.index:
        return None
    start, end = float(series[entry]), float(series[exit_])
    return end / start - 1 if start > 0 else None


def score_signals(signals: pd.DataFrame, closes: Closes, universe: Iterable[str]) -> pd.DataFrame:
    """Add entry/exit dates, forward, benchmark and excess return to each signal."""
    universe = list(universe)
    records = []
    for row in signals.itertuples(index=False):
        record = {
            "scan_date": row.scan_date,
            "symbol": row.symbol,
            "recommendation": row.recommendation,
            "entry_date": None,
            "exit_date": None,
            "forward_return": None,
            "benchmark_return": None,
            "excess_return": None,
            "status": "pending",
        }
        series = closes.get(row.symbol)
        window = _entry_exit(series, row.scan_date) if series is not None else None
        if window is not None:
            entry, exit_ = window
            fwd = _forward_return(series, entry, exit_)
            peers = [
                r for s in universe if s in closes
                for r in [_forward_return(closes[s], entry, exit_)] if r is not None
            ]
            if fwd is not None and peers:
                bench = sum(peers) / len(peers)
                record.update(
                    entry_date=entry, exit_date=exit_, forward_return=fwd,
                    benchmark_return=bench, excess_return=fwd - bench, status="complete",
                )
        records.append(record)
    return pd.DataFrame.from_records(records)


def summarize(scored: pd.DataFrame) -> dict:
    """Per-recommendation statistics and the BUY verdict for one sample."""
    by_rec = {}
    for rec in RECOMMENDATIONS:
        rows = scored[scored["recommendation"] == rec]
        part = rows[rows["status"] == "complete"]
        n = int(len(part))
        stats = {"completed": n, "pending": int((rows["status"] == "pending").sum())}
        if n:
            stats["mean_return"] = float(part["forward_return"].mean())
            stats["mean_excess"] = float(part["excess_return"].mean())
            if rec == "BUY":
                stats["hit_rate"] = float((part["excess_return"] > 0).mean())
            elif rec == "SELL":
                stats["hit_rate"] = float((part["excess_return"] < 0).mean())
        by_rec[rec] = stats

    buy = by_rec["BUY"]
    if buy["completed"] < MIN_BUY_SIGNALS:
        verdict = INSUFFICIENT
    elif buy["mean_excess"] > 0 and buy["hit_rate"] > HIT_RATE_THRESHOLD:
        verdict = "PASS"
    else:
        verdict = "FAIL"
    return {"verdict": verdict, "by_recommendation": by_rec}


def evaluate(signals: pd.DataFrame, fetch: PriceFetcher = yahoo_closes, today: Optional[date] = None) -> dict:
    """Score every signal and split into official (out-of-sample) and exploratory."""
    today = today or datetime.now(ZoneInfo(WIB)).date()
    rules = {
        "horizon_trading_days": HORIZON_TRADING_DAYS,
        "min_buy_signals": MIN_BUY_SIGNALS,
        "hit_rate_threshold": HIT_RATE_THRESHOLD,
        "registered_on": REGISTERED_ON.isoformat(),
    }
    if signals.empty:
        empty = summarize(pd.DataFrame(columns=["recommendation", "status"]))
        return {"rules": rules, "official": empty, "exploratory": empty, "signals": []}

    universe = sorted(signals["symbol"].unique())
    fetched = fetch(universe, min(signals["scan_date"]), today)
    # Only fully closed sessions count: today's bar is a live quote until the
    # closing auction ends, and the daily publish runs around 15:50 WIB.
    closes = {symbol: series[[d < today for d in series.index]] for symbol, series in fetched.items()}
    scored = score_signals(signals, closes, universe)

    official = scored[scored["scan_date"] >= REGISTERED_ON]
    exploratory = scored[scored["scan_date"] < REGISTERED_ON]
    return {
        "rules": rules,
        "official": summarize(official),
        "exploratory": summarize(exploratory),
        "signals": json.loads(scored.to_json(orient="records", date_format="iso")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)
    args = parser.parse_args()
    result = evaluate(load_signals(args.db))
    print(json.dumps({k: result[k] for k in ("rules", "official", "exploratory")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
