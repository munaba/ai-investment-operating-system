"""Backtest candidate price rules on years of daily closes (exploratory only).

The live v1 signal calls a stock "bullish" when the price at scan time is
above the previous price, and BUY needs that plus PE < 15. This module asks
whether better *price* rules exist, using the same outcome definition as the
pre-registered test (Docs/SIGNAL_EVALUATION.md):

* a signal on trading day t (decided from closes up to and including t),
* entry at the close of t+1, exit at the close five trading days later,
* excess return = forward return minus the equal-weight mean of the universe
  over the same days.

To keep a lucky winner from looking like a discovery, the history is split:
rules are compared on the *selection* period and only then checked on the
later *holdout* period. Valuation and news are not tested: Yahoo only gives
today's PE, so using it for past dates would leak the future.

Nothing here changes how live signals are produced or feeds the official
verdict.

    python Evaluation/backtest_rules.py [--years 5] [--symbols BBCA BBRI ...]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):  # run as a script: make the repo importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Evaluation.signal_evaluation import (
    _DEFAULT_DB,
    HORIZON_TRADING_DAYS,
    yahoo_closes,
)

#: Share of the history used to compare rules; the rest is the holdout.
SELECTION_SHARE = 0.7
TOP_N = 3

Rule = Callable[[pd.DataFrame], pd.DataFrame]


def _top_n(score: pd.DataFrame, n: int = TOP_N, largest: bool = True) -> pd.DataFrame:
    ranks = score.rank(axis=1, ascending=not largest, method="first")
    return (ranks <= n) & score.notna()


#: Each rule maps a (date x symbol) frame of closes to a boolean BUY frame,
#: using only closes up to each row's date.
RULES: dict[str, Rule] = {
    "v1_up_vs_prev_close": lambda c: c > c.shift(1),
    "momentum_20d_positive": lambda c: c / c.shift(20) - 1 > 0,
    "above_sma50": lambda c: c > c.rolling(50).mean(),
    "top3_momentum_20d": lambda c: _top_n(c / c.shift(20) - 1),
    "top3_momentum_60d": lambda c: _top_n(c / c.shift(60) - 1),
    "bottom3_return_5d (reversal)": lambda c: _top_n(c / c.shift(5) - 1, largest=False),
}


def closes_frame(closes: dict[str, pd.Series]) -> pd.DataFrame:
    frame = pd.DataFrame(closes).sort_index()
    frame.index = pd.to_datetime(frame.index)
    return frame


def excess_returns(frame: pd.DataFrame, horizon: int = HORIZON_TRADING_DAYS) -> pd.DataFrame:
    """Excess forward return for a signal dated on each row (NaN at the end)."""
    entry = frame.shift(-1)
    exit_ = frame.shift(-(1 + horizon))
    forward = exit_ / entry - 1
    return forward.sub(forward.mean(axis=1), axis=0)


def _stats(values: pd.Series) -> dict:
    n = int(values.count())
    if n == 0:
        return {"signals": 0}
    mean = float(values.mean())
    out = {"signals": n, "mean_excess": mean, "hit_rate": float((values > 0).mean())}
    if n > 1 and values.std() > 0:
        out["t_stat"] = mean / (float(values.std()) / n**0.5)
    return out


def evaluate_rule(frame: pd.DataFrame, rule: Rule, excess: pd.DataFrame, horizon: int = HORIZON_TRADING_DAYS) -> dict:
    signals = rule(frame).fillna(False).astype(bool) & excess.notna()
    picked = excess.where(signals)
    # Signals on consecutive days share most of their holding period, so the
    # t-statistic uses non-overlapping dates (every horizon+1 rows) only.
    non_overlap = picked.iloc[:: horizon + 1].stack()
    stats = _stats(picked.stack())
    stats["non_overlapping"] = _stats(non_overlap)
    stats["buy_share"] = float(signals.to_numpy().sum() / max(int(excess.notna().to_numpy().sum()), 1))
    return stats


def backtest(
    closes: dict[str, pd.Series], selection_share: float = SELECTION_SHARE, horizon: int = HORIZON_TRADING_DAYS
) -> dict:
    frame = closes_frame(closes)
    excess = excess_returns(frame, horizon)
    cut = frame.index[int(len(frame.index) * selection_share)]
    periods = {
        "selection": (frame.index <= cut),
        "holdout": (frame.index > cut),
    }
    report: dict = {
        "symbols": list(frame.columns),
        "start": frame.index.min().date().isoformat(),
        "split": cut.date().isoformat(),
        "end": frame.index.max().date().isoformat(),
        "horizon": horizon,
        "rules": {},
    }
    for name, rule in RULES.items():
        report["rules"][name] = {
            label: evaluate_rule(frame, rule, excess.where(pd.Series(mask, index=frame.index), axis=0), horizon)
            for label, mask in periods.items()
        }
    return report


def watchlist(db_path: Path) -> list[str]:
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        return [row[0] for row in conn.execute("SELECT ticker FROM watchlist ORDER BY ticker")]


def _print(report: dict) -> None:
    def pct(v: float | None) -> str:
        return "     -" if v is None else f"{v * 100:+6.2f}%"

    print(f"Universe ({len(report['symbols'])}): {' '.join(report['symbols'])}")
    print(f"Horizon: {report['horizon']} trading days after entry")
    print(f"Selection {report['start']} .. {report['split']}   holdout .. {report['end']}\n")
    header = f"{'rule':<30} {'period':<10} {'n':>6} {'buy%':>5} {'excess':>8} {'hit':>5} {'t(non-overlap)':>15}"
    print(header)
    print("-" * len(header))
    for name, periods in report["rules"].items():
        for label, s in periods.items():
            if not s.get("signals"):
                print(f"{name:<30} {label:<10} {0:>6}")
                continue
            t = s["non_overlapping"].get("t_stat")
            print(
                f"{name:<30} {label:<10} {s['signals']:>6} {s['buy_share']:>5.0%} {pct(s['mean_excess']):>8}"
                f" {s['hit_rate']:>5.0%} {'-' if t is None else f'{t:+.2f}':>15}"
            )
    print(
        "\nRead: a rule is only interesting if it beats the watchlist in BOTH periods and its "
        "non-overlapping |t| is above ~2. Several rules are tested, so one lucky winner is expected."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB, help="read the watchlist from this DB")
    parser.add_argument("--symbols", nargs="*", help="universe to test instead of the watchlist")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--horizon", type=int, default=HORIZON_TRADING_DAYS,
                        help="holding period in trading days (the official test uses 5)")
    args = parser.parse_args()
    symbols = args.symbols or watchlist(args.db)
    end = date.today()
    closes = yahoo_closes(symbols, end - timedelta(days=365 * args.years), end - timedelta(days=1))
    _print(backtest(closes, horizon=args.horizon))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
