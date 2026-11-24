"""Which parts of the signal logic carry information? (exploratory only)

The official, pre-registered test (``signal_evaluation.py``) asks one yes/no
question about BUY signals and must not change while it collects data. This
module looks inside the same scored signals to guide the *next* version of
the signal logic:

* mean excess return and hit rate per confidence level and per score
  tercile (terciles, not fixed bands: in practice scores sit between 11
  and 38 because the recommendation weight dominates);
* rank correlation (Spearman) between excess return and the total score and
  each factor contribution in ``score_breakdown_json``.

Nothing here feeds the official verdict, and nothing here changes how
signals are produced. Run it from the repository root:

    python Evaluation/signal_diagnostics.py [--db PATH] [--json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import date
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):  # run as a script: make the repo importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Evaluation.signal_evaluation import (
    _DEFAULT_DB,
    PriceFetcher,
    evaluate,
    first_signal_per_day,
    yahoo_closes,
)

#: Fewer completed signals than this in a group and its statistics are
#: reported as too small to read anything into.
MIN_GROUP = 10


def load_scored_inputs(db_path: Path) -> pd.DataFrame:
    """Same rows as ``load_signals`` plus confidence, score and breakdown."""
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        rows = pd.read_sql_query(
            "SELECT scan_time, symbol, recommendation, confidence, score, score_breakdown_json "
            "FROM ranking_snapshots "
            "WHERE status = 'success' AND recommendation IN ('BUY', 'WAIT', 'SELL')",
            conn,
        )
    return first_signal_per_day(rows)


def _factors(raw: object) -> dict:
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        k.removesuffix("_contribution"): float(v)
        for k, v in parsed.items()
        if k.endswith("_contribution") and isinstance(v, (int, float))
    }


def _group_stats(frame: pd.DataFrame) -> dict:
    n = len(frame)
    out: dict = {"completed": n}
    if n:
        out["mean_excess"] = float(frame["excess_return"].mean())
        out["beat_watchlist"] = float((frame["excess_return"] > 0).mean())
        out["too_small"] = n < MIN_GROUP
    return out


def _spearman(x: pd.Series, y: pd.Series) -> float | None:
    pair = pd.concat([x, y], axis=1).dropna()
    if len(pair) < MIN_GROUP or pair.iloc[:, 0].nunique() < 2:
        return None
    ranks = pair.rank()
    return float(ranks.iloc[:, 0].corr(ranks.iloc[:, 1]))


def diagnose(inputs: pd.DataFrame, fetch: PriceFetcher = yahoo_closes, today: date | None = None) -> dict:
    """Join scored outcomes back onto the signal inputs and break them down."""
    result = evaluate(inputs[["scan_time", "symbol", "recommendation", "scan_date"]], fetch=fetch, today=today)
    scored = pd.DataFrame(result["signals"])
    if scored.empty:
        return {"completed": 0, "by_confidence": {}, "by_score_band": {}, "correlation": {}}

    scored["scan_date"] = pd.to_datetime(scored["scan_date"]).dt.date
    merged = scored.merge(
        inputs[["symbol", "scan_date", "confidence", "score", "score_breakdown_json"]],
        on=["symbol", "scan_date"],
        how="left",
    )
    done = merged[merged["status"] == "complete"].copy()
    done["excess_return"] = pd.to_numeric(done["excess_return"], errors="coerce")
    done["score"] = pd.to_numeric(done["score"], errors="coerce")

    by_confidence = {
        str(level): _group_stats(group)
        for level, group in done.groupby(done["confidence"].fillna("NONE"))
    }
    by_band = {}
    scored_rows = done.dropna(subset=["score"])
    if scored_rows["score"].nunique() >= 3:
        bands = pd.qcut(scored_rows["score"], 3, duplicates="drop")
        for interval, group in scored_rows.groupby(bands, observed=True):
            by_band[f"{interval.left:.0f}-{interval.right:.0f}"] = _group_stats(group)

    factors = pd.DataFrame([_factors(raw) for raw in done["score_breakdown_json"]], index=done.index)
    correlation = {"score": _spearman(done["score"], done["excess_return"])}
    for column in sorted(factors.columns):
        correlation[column] = _spearman(factors[column], done["excess_return"])

    return {
        "completed": len(done),
        "by_confidence": by_confidence,
        "by_score_band": by_band,
        "correlation": correlation,
    }


def _print_report(report: dict) -> None:
    def pct(v: float | None) -> str:
        return "   -  " if v is None else f"{v * 100:+.2f}%"

    print(f"Completed signals (all recommendations): {report['completed']}")
    for title, key in (("By confidence", "by_confidence"), ("By score band", "by_score_band")):
        print(f"\n{title}:")
        for name, stats in report[key].items():
            flag = "  (too small)" if stats.get("too_small") else ""
            beat = stats.get("beat_watchlist")
            print(
                f"  {name:<8} n={stats['completed']:>3}  mean excess {pct(stats.get('mean_excess'))}"
                f"  beat watchlist {'-' if beat is None else f'{beat:.0%}'}{flag}"
            )
    print("\nSpearman rank correlation with excess return (|r| < 0.2 is noise at this sample size):")
    for name, value in report["correlation"].items():
        print(f"  {name:<28} {'-' if value is None else f'{value:+.2f}'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)
    parser.add_argument("--json", action="store_true", help="print the raw report as JSON")
    args = parser.parse_args()
    report = diagnose(load_scored_inputs(args.db))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
