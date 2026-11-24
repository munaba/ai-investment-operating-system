"""Factor research for the v2 signal: which stock-ranking logic holds up out of sample?

Exploratory only. The production model lives in Business/factor_model.py and
this module reuses its factors and weighting, so research and live picks
are computed by the same code.

Design (see Docs/SIGNAL_EVALUATION.md, "Factor research"):

* Universe: the market's liquid stocks (``Market.universe``), daily closes
  and volume from Yahoo, cached locally for the day.
* Every factor at day t uses only data up to and including t.
* Every ``HOLD`` trading days the strategy buys the ``TOP_K`` best-scored
  stocks at the next close and holds them for ``HOLD`` days. The result per
  period is the picks' mean excess return over the equal-weight universe,
  minus the market's round-trip cost on the names that changed.
* The first ``SELECTION_SHARE`` of rebalance dates is the selection period;
  the remaining dates are the holdout.

Candidates: each single factor, a v1-like 1-day return rule, a composite
fixed from published evidence, the IC-weighted composite (the v2 model),
and a ridge regression retrained at every rebalance on earlier outcomes
(a small, linear stand-in for Qlib's Alpha158 + LightGBM baseline).

    python Evaluation/factor_research.py [--market idx|us] [--years 7] [--hold 20] [--top 5]
    python Evaluation/factor_research.py --market us --today
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):  # run as a script: make the repo importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Business.factor_model import (
    EVIDENCE_COMPOSITE,
    HOLD,
    IDX,
    MARKETS,
    MIN_HISTORY,
    MIN_IC_SAMPLES,
    TOP_K,
    Market,
    cross_sectional_rank,
    forward_excess,
    ic_weights,
    known_dates,
    rank_universe,
    weighted_score,
    yahoo_panel,
)
from Business.factor_model import (
    compute_factors as _model_factors,
)

SELECTION_SHARE = 0.7
CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "AIOS" / "price_cache"
#: Kept for callers that predate markets; IDX cost.
ROUND_TRIP_COST = IDX.round_trip_cost
UNIVERSE = list(IDX.universe)
excess_returns = forward_excess
_known_dates = known_dates

# ---------------------------------------------------------------- data ----


def fetch_panel(market: Market, years: int, symbols: list[str] | None = None,
                cache_dir: Path = CACHE_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(close, volume) for the market, cached for the day."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    end = date.today()
    key = "custom" if symbols else "universe"
    path = cache_dir / f"panel_{market.name}_{key}_{years}y_{end.isoformat()}.pkl"
    if path.exists():
        close, volume = pd.read_pickle(path)
    else:
        start = date(end.year - years, end.month, min(end.day, 28))
        close, volume = yahoo_panel(market, start, end, tuple(symbols) if symbols else None)
        pd.to_pickle((close, volume), path)
    return close, volume


def compute_factors(close: pd.DataFrame, volume: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """The v2 factors plus the v1-like 1-day return, for comparison."""
    return {"v1_like_1d_return": close / close.shift(1) - 1, **_model_factors(close, volume)}


# ------------------------------------------------------------ backtest ----


def rebalance_dates(index: pd.DatetimeIndex, hold: int, first: int) -> list[pd.Timestamp]:
    return list(index[first::hold])


def run_strategy(
    score_at: Callable[[pd.Timestamp], pd.Series],
    dates: list[pd.Timestamp],
    excess: pd.DataFrame,
    top_k: int,
    cost: float = ROUND_TRIP_COST,
) -> pd.DataFrame:
    """One row per rebalance: gross and net excess of the top-k picks."""
    rows, previous = [], set()
    for t in dates:
        realized = excess.loc[t]
        score = score_at(t).dropna()
        score = score[score.index.isin(realized.dropna().index)]
        if len(score) < top_k * 2:
            continue
        picks = set(score.nlargest(top_k).index)
        gross = float(realized[list(picks)].mean())
        turnover = len(picks - previous) / top_k
        rows.append({"date": t, "gross": gross, "net": gross - turnover * cost})
        previous = picks
    return pd.DataFrame(rows, columns=["date", "gross", "net"])


def summarize(periods: pd.DataFrame, hold: int) -> dict:
    n = len(periods)
    if n == 0:
        return {"periods": 0}
    net = periods["net"]
    out = {
        "periods": n,
        "mean_gross": float(periods["gross"].mean()),
        "mean_net": float(net.mean()),
        "hit_rate": float((net > 0).mean()),
        "annualized_net": float(net.mean() * 252 / hold),
    }
    if n > 2 and net.std() > 0:
        out["t_stat"] = float(net.mean() / (net.std() / np.sqrt(n)))
    return out


# ---------------------------------------------------- walk-forward models --


def ic_weighted_scorer(ranks: dict[str, pd.DataFrame], excess: pd.DataFrame, dates: list, index, hold: int):
    """The v2 model, evaluated walk-forward: weights from earlier outcomes only."""
    model_ranks = {n: r for n, r in ranks.items() if n != "v1_like_1d_return"}
    cache: dict = {}

    def score_at(t: pd.Timestamp) -> pd.Series:
        weights = ic_weights(model_ranks, excess, known_dates(dates, t, index, hold), cache)
        return weighted_score(model_ranks, weights, t)

    return score_at


def ridge_scorer(ranks: dict[str, pd.DataFrame], excess: pd.DataFrame, dates: list, index, hold: int,
                 alpha: float = 5.0):
    names = [n for n in ranks if n != "v1_like_1d_return"]
    target = excess.sub(excess.mean(axis=1), axis=0)

    def rows_for(d: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
        x = pd.concat([ranks[n].loc[d] for n in names], axis=1)
        frame = pd.concat([x, target.loc[d]], axis=1).dropna()
        return frame.iloc[:, :-1].to_numpy(), frame.iloc[:, -1].to_numpy()

    def score_at(t: pd.Timestamp) -> pd.Series:
        known = known_dates(dates, t, index, hold)
        if len(known) < MIN_IC_SAMPLES:
            return sum(ranks[n].loc[t] for n in EVIDENCE_COMPOSITE) / len(EVIDENCE_COMPOSITE)
        xs, ys = zip(*(rows_for(d) for d in known))
        x, y = np.vstack(xs), np.concatenate(ys)
        coef = np.linalg.solve(x.T @ x + alpha * len(y) / 100 * np.eye(x.shape[1]), x.T @ y)
        today = pd.concat([ranks[n].loc[t] for n in names], axis=1)
        return pd.Series(today.fillna(0).to_numpy() @ coef, index=today.index).where(today.notna().all(axis=1))

    return score_at


# ------------------------------------------------------------- research ----


def research(close: pd.DataFrame, volume: pd.DataFrame, hold: int = HOLD, top_k: int = TOP_K,
             selection_share: float = SELECTION_SHARE, cost: float = ROUND_TRIP_COST) -> dict:
    factors = compute_factors(close, volume)
    ranks = {name: cross_sectional_rank(f) for name, f in factors.items()}
    excess = forward_excess(close, hold)
    index = close.index
    dates = rebalance_dates(index, hold, first=MIN_HISTORY)
    dates = [d for d in dates if excess.loc[d].notna().sum() >= top_k * 2]
    split = dates[int(len(dates) * selection_share)]

    candidates: dict[str, Callable] = {name: (lambda t, r=r: r.loc[t]) for name, r in ranks.items()}
    candidates["evidence_composite"] = lambda t: sum(ranks[n].loc[t] for n in EVIDENCE_COMPOSITE) / len(
        EVIDENCE_COMPOSITE
    )
    candidates["ic_weighted_walk_forward"] = ic_weighted_scorer(ranks, excess, dates, index, hold)
    candidates["ridge_walk_forward"] = ridge_scorer(ranks, excess, dates, index, hold)

    results = {}
    for name, scorer in candidates.items():
        periods = run_strategy(scorer, dates, excess, top_k, cost)
        results[name] = {
            "selection": summarize(periods[periods["date"] < split], hold),
            "holdout": summarize(periods[periods["date"] >= split], hold),
        }

    eligible = {k: v for k, v in results.items() if k != "v1_like_1d_return" and v["selection"].get("t_stat")}
    winner = max(eligible, key=lambda k: eligible[k]["selection"]["t_stat"]) if eligible else None
    return {
        "universe": list(close.columns),
        "first_rebalance": dates[0].date().isoformat(),
        "split": split.date().isoformat(),
        "last_rebalance": dates[-1].date().isoformat(),
        "hold": hold,
        "top_k": top_k,
        "cost": cost,
        "results": results,
        "chosen_on_selection": winner,
    }


def daily_ic_scores(close: pd.DataFrame, volume: pd.DataFrame, hold: int = HOLD) -> pd.DataFrame:
    """The IC-weighted composite score for every trading day, as a live job
    would have computed it that day (sample dates counted back from the day).
    Research only: it failed the US selection period, so v2 does not use it."""
    ranks = {n: cross_sectional_rank(f) for n, f in _model_factors(close, volume).items()}
    excess = forward_excess(close, hold)
    index = close.index
    cache: dict = {}
    rows = {}
    for pos in range(MIN_HISTORY, len(index)):
        t = index[pos]
        sample = sorted(index[: pos + 1][::-hold][: (pos + 1 - MIN_HISTORY) // hold + 1])
        weights = ic_weights(ranks, excess, known_dates(sample, t, index, hold), cache)
        rows[t] = weighted_score(ranks, weights, t)
    return pd.DataFrame(rows).T


def robustness(close: pd.DataFrame, volume: pd.DataFrame, hold: int = HOLD, top_k: int = TOP_K,
               selection_share: float = SELECTION_SHARE, cost: float = ROUND_TRIP_COST) -> dict:
    """Run each logic on every possible rebalance schedule (offset 0..hold-1).
    One schedule can be lucky; the share of schedules that stay positive in
    the holdout is the honest measure."""
    factors = compute_factors(close, volume)
    ranks = {n: cross_sectional_rank(f) for n, f in factors.items()}
    excess = forward_excess(close, hold)
    index = close.index
    split = index[MIN_HISTORY + int((len(index) - MIN_HISTORY) * selection_share)]
    model = daily_ic_scores(close, volume, hold)
    logics: dict[str, Callable] = {
        "ic_weighted_composite": lambda t: model.loc[t] if t in model.index else pd.Series(dtype=float),
        "v1_like_1d_return": lambda t: ranks["v1_like_1d_return"].loc[t],
        "evidence_composite": lambda t: sum(ranks[n].loc[t] for n in EVIDENCE_COMPOSITE) / len(EVIDENCE_COMPOSITE),
        "momentum_60d": lambda t: ranks["momentum_60d"].loc[t],
        "v2_trend_vs_sma200": lambda t: ranks["trend_vs_sma200"].loc[t],
    }
    out = {}
    for name, scorer in logics.items():
        per_offset = {"selection": [], "holdout": []}
        for offset in range(hold):
            dates = [d for d in index[MIN_HISTORY + offset :: hold] if excess.loc[d].notna().sum() >= top_k * 2]
            periods = run_strategy(scorer, dates, excess, top_k, cost)
            if periods.empty:
                continue
            per_offset["selection"].append(periods.loc[periods["date"] < split, "net"].mean())
            per_offset["holdout"].append(periods.loc[periods["date"] >= split, "net"].mean())
        out[name] = {
            label: {
                "mean_net": float(np.nanmean(v)),
                "positive_schedules": int(np.sum(np.array(v) > 0)),
                "schedules": len(v),
                "worst": float(np.nanmin(v)),
                "best": float(np.nanmax(v)),
            }
            for label, v in per_offset.items()
        }
    return {"split": split.date().isoformat(), "start": index[MIN_HISTORY].date().isoformat(),
            "end": index[-1].date().isoformat(), "hold": hold, "top_k": top_k, "cost": cost,
            "universe": len(close.columns), "logics": out}


def _print_robustness(report: dict) -> None:
    print(f"Universe {report['universe']} | top {report['top_k']} | hold {report['hold']} | cost "
          f"{report['cost']:.1%} | selection {report['start']}..{report['split']} | holdout ..{report['end']}")
    print(f"{'logic':<22} {'period':<9} {'mean net/period':>15} {'positive':>9} {'worst':>8} {'best':>8}")
    for name, periods in report["logics"].items():
        for label, s in periods.items():
            print(f"{name:<22} {label:<9} {s['mean_net'] * 100:>+14.2f}% "
                  f"{s['positive_schedules']:>4}/{s['schedules']:<4} {s['worst'] * 100:>+7.2f}% {s['best'] * 100:>+7.2f}%")


def current_picks(close: pd.DataFrame, volume: pd.DataFrame, hold: int = HOLD, top_k: int = TOP_K,
                  market: Market = IDX) -> dict:
    """Today's v2 ranking, computed by the production model."""
    ranking = rank_universe(market, close, volume, hold)
    return {
        "market": market.name,
        "as_of": ranking.signal_date.isoformat(),
        "hold_days": hold,
        "picks": [{"symbol": s, "score": float(v)} for s, v in ranking.scores.head(top_k).items()],
        "ranked": len(ranking.scores),
        "weights": ranking.weights,
    }


def _print(report: dict) -> None:
    def pct(v):
        return "     -" if v is None else f"{v * 100:+6.2f}%"

    print(f"Universe: {len(report['universe'])} stocks | top {report['top_k']} | hold {report['hold']} days")
    print(f"Selection {report['first_rebalance']} .. {report['split']} | holdout .. {report['last_rebalance']}")
    print(f"Costs: {report['cost']:.1%} round trip on changed names\n")
    head = f"{'logic':<28} {'period':<9} {'n':>3} {'net/period':>10} {'hit':>5} {'t':>6} {'net/yr':>8}"
    print(head)
    print("-" * len(head))
    for name, periods in sorted(
        report["results"].items(), key=lambda kv: -(kv[1]["selection"].get("t_stat") or -99)
    ):
        for label, s in periods.items():
            if not s.get("periods"):
                continue
            t = s.get("t_stat")
            print(
                f"{name:<28} {label:<9} {s['periods']:>3} {pct(s['mean_net']):>10} {s['hit_rate']:>5.0%}"
                f" {'-' if t is None else f'{t:+.2f}':>6} {pct(s['annualized_net']):>8}"
            )
    print(f"\nChosen on the selection period only: {report['chosen_on_selection']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--market", choices=sorted(MARKETS), default="idx")
    parser.add_argument("--years", type=int, default=7)
    parser.add_argument("--hold", type=int, default=HOLD)
    parser.add_argument("--top", type=int, default=TOP_K)
    parser.add_argument("--symbols", nargs="*", help="override the market's universe")
    parser.add_argument("--today", action="store_true",
                        help="print today's v2 picks instead of the research table")
    parser.add_argument("--robust", action="store_true",
                        help="run each logic on every rebalance schedule instead of one")
    args = parser.parse_args()
    market = MARKETS[args.market]
    close, volume = fetch_panel(market, args.years, args.symbols)
    # Only completed sessions: drop a bar dated today (a live quote).
    close, volume = close[close.index.date < date.today()], volume[volume.index.date < date.today()]
    if args.today:
        result = current_picks(close, volume, hold=args.hold, top_k=args.top, market=market)
        print(f"v2 picks ({market.name.upper()}) from closes up to {result['as_of']}, "
              f"hold {result['hold_days']} trading days, {result['ranked']} stocks ranked:")
        for i, pick in enumerate(result["picks"], 1):
            print(f"  {i}. {pick['symbol']:<6} score {pick['score']:+.3f}")
        top_weights = sorted(result["weights"].items(), key=lambda kv: -abs(kv[1]))[:4]
        print("Heaviest factor weights: " + ", ".join(f"{k} {v:+.2f}" for k, v in top_weights))
        return 0
    if args.robust:
        _print_robustness(robustness(close, volume, hold=args.hold, top_k=args.top, cost=market.round_trip_cost))
        return 0
    _print(research(close, volume, hold=args.hold, top_k=args.top, cost=market.round_trip_cost))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
