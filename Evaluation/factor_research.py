"""Factor research for a v2 signal: which stock-ranking logic holds up out of sample?

Exploratory only. Nothing here changes live signals or the official verdict.

Design (see Docs/SIGNAL_EVALUATION.md, "Factor research"):

* Universe: liquid IDX stocks (``UNIVERSE``), daily closes and volume from
  Yahoo, cached locally so reruns are fast.
* Every factor at day t uses only data up to and including t.
* Every ``HOLD`` trading days the strategy buys the ``TOP_K`` best-scored
  stocks at the next close and holds them for ``HOLD`` days. The result per
  period is the picks' mean excess return over the equal-weight universe,
  minus a round-trip cost on the names that changed.
* The first ``SELECTION_SHARE`` of rebalance dates is the selection period;
  the "smartest" logic is chosen there only, then reported on the holdout.

Candidates: each single factor, a composite fixed from published evidence
before testing, an IC-weighted composite whose weights come only from
earlier outcomes (walk-forward), and a ridge regression retrained at every
rebalance on earlier outcomes only (a small, linear stand-in for Qlib's
Alpha158 + LightGBM baseline).

    python Evaluation/factor_research.py [--years 7] [--hold 20] [--top 5]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):  # run as a script: make the repo importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Evaluation.backtest_rules import excess_returns

#: Liquid IDX names as of late 2026. Today's list, so results carry
#: survivorship bias in favour of strategies that buy past winners.
UNIVERSE = ["AALI", "ACES", "ADRO", "AKRA", "AMRT", "ANTM", "ARTO", "ASII", "AUTO", "BBCA", "BBNI", "BBRI", "BBTN", "BMRI", "BRIS", "BRPT", "BSDE", "CPIN", "CTRA", "ELSA", "EMTK", "ERAA", "ESSA", "EXCL", "HEAL", "HRUM", "ICBP", "INCO", "INDF", "INKP", "INTP", "ISAT", "ITMG", "JPFA", "JSMR", "KLBF", "LSIP", "MAPA", "MAPI", "MDKA", "MEDC", "MIKA", "MNCN", "MYOR", "PGAS", "PTBA", "PTPP", "PWON", "SCMA", "SIDO", "SMGR", "SMRA", "TINS", "TKIM", "TLKM", "TOWR", "UNTR", "UNVR", "WIKA"]

HOLD = 20
TOP_K = 5
SELECTION_SHARE = 0.7
#: Approximate IDX round-trip cost (buy fee + sell fee incl. 0.1% sales tax).
ROUND_TRIP_COST = 0.004
MIN_HISTORY = 252
CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "AIOS" / "price_cache"

# ---------------------------------------------------------------- data ----


def fetch_panel(symbols: list[str], years: int, cache_dir: Path = CACHE_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(close, volume) frames, date x symbol. Cached per symbol for a day."""
    import yfinance as yf

    cache_dir.mkdir(parents=True, exist_ok=True)
    end = date.today()
    start = end - timedelta(days=365 * years)
    closes, volumes = {}, {}
    for symbol in symbols:
        path = cache_dir / f"{symbol}_{years}y_{end.isoformat()}.pkl"
        if path.exists():
            history = pd.read_pickle(path)
        else:
            history = yf.Ticker(f"{symbol}.JK").history(
                start=start.isoformat(), end=end.isoformat(), interval="1d", auto_adjust=True, timeout=30
            )
            history.to_pickle(path)
            time.sleep(0.2)  # be gentle with Yahoo
        if history.empty:
            continue
        index = pd.to_datetime([ts.date() for ts in history.index])
        closes[symbol] = pd.Series(history["Close"].to_numpy(), index=index)
        volumes[symbol] = pd.Series(history["Volume"].to_numpy(), index=index)
    close = pd.DataFrame(closes).sort_index()
    volume = pd.DataFrame(volumes).reindex(close.index)
    return close, volume


# ------------------------------------------------------------- factors ----


def _residual_momentum(close: pd.DataFrame, window: int = 120, skip: int = 20) -> pd.DataFrame:
    """Momentum of the part of each stock's return the market does not explain,
    scaled by its own volatility (Blitz, Huij and Martens, 2011)."""
    ret = close.pct_change(fill_method=None)
    market = ret.mean(axis=1)
    mean_r = ret.rolling(window).mean()
    mean_m = market.rolling(window).mean()
    cov = (ret.mul(market, axis=0)).rolling(window).mean().sub(mean_r.mul(mean_m, axis=0))
    var = market.rolling(window).var(ddof=0)
    beta = cov.div(var, axis=0)
    resid = ret.sub(beta.mul(market, axis=0))
    lagged = resid.shift(skip)
    span = window - skip
    return lagged.rolling(span).sum() / lagged.rolling(span).std()


def compute_factors(close: pd.DataFrame, volume: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Each factor: higher = more attractive. Uses data up to each row only."""
    ret = close.pct_change(fill_method=None)
    traded = (close * volume).where(volume > 0)
    return {
        "v1_like_1d_return": close / close.shift(1) - 1,
        "momentum_60d": close / close.shift(60) - 1,
        "momentum_120d_skip20": close.shift(20) / close.shift(120) - 1,
        "residual_momentum": _residual_momentum(close),
        "near_52w_high": close / close.rolling(MIN_HISTORY).max(),
        "low_volatility_60d": -ret.rolling(60).std(),
        "reversal_5d": -(close / close.shift(5) - 1),
        "trend_vs_sma200": close / close.rolling(200).mean() - 1,
        "liquidity_20d": np.log(traded.rolling(20).mean()),
    }


#: Fixed from published evidence before looking at results: momentum that
#: skips the last month, residual momentum, and closeness to the 52-week high.
EVIDENCE_COMPOSITE = ("momentum_120d_skip20", "residual_momentum", "near_52w_high")


def cross_sectional_rank(frame: pd.DataFrame) -> pd.DataFrame:
    """Per-date percentile rank centred on 0 (-0.5 .. +0.5)."""
    return frame.rank(axis=1, pct=True) - 0.5


# ------------------------------------------------------------ backtest ----


def rebalance_dates(index: pd.DatetimeIndex, hold: int, first: int) -> list[pd.Timestamp]:
    return list(index[first::hold])


def run_strategy(
    score_at: Callable[[pd.Timestamp], pd.Series],
    dates: list[pd.Timestamp],
    excess: pd.DataFrame,
    top_k: int,
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
        rows.append({"date": t, "gross": gross, "net": gross - turnover * ROUND_TRIP_COST})
        previous = picks
    return pd.DataFrame(rows)


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


def _known_dates(dates: list[pd.Timestamp], t: pd.Timestamp, index: pd.DatetimeIndex, hold: int) -> list:
    """Rebalance dates whose outcome was fully known at t (exit close <= t)."""
    pos = index.get_loc(t)
    cutoff = index[pos - (hold + 1)] if pos > hold + 1 else None
    return [d for d in dates if cutoff is not None and d <= cutoff]


def ic_weighted_scorer(ranks: dict[str, pd.DataFrame], excess: pd.DataFrame, dates: list, index, hold: int):
    names = [n for n in ranks if n != "v1_like_1d_return"]
    excess_rank = excess.rank(axis=1, pct=True)

    def rank_ic(name: str, d: pd.Timestamp) -> float:
        pair = pd.concat([ranks[name].loc[d], excess_rank.loc[d]], axis=1).dropna()
        return float(pair.iloc[:, 0].corr(pair.iloc[:, 1])) if len(pair) > 10 else np.nan

    ic_cache: dict = {}

    def score_at(t: pd.Timestamp) -> pd.Series:
        known = _known_dates(dates, t, index, hold)
        if len(known) < 6:  # not enough history yet: fall back to the evidence prior
            return sum(ranks[n].loc[t] for n in EVIDENCE_COMPOSITE) / len(EVIDENCE_COMPOSITE)
        weights = {}
        for name in names:
            ics = [ic_cache.setdefault((name, d), rank_ic(name, d)) for d in known]
            weights[name] = float(np.nanmean(ics))
        total = sum(abs(w) for w in weights.values()) or 1.0
        return sum(ranks[n].loc[t] * (w / total) for n, w in weights.items())

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
        known = _known_dates(dates, t, index, hold)
        if len(known) < 6:
            return sum(ranks[n].loc[t] for n in EVIDENCE_COMPOSITE) / len(EVIDENCE_COMPOSITE)
        xs, ys = zip(*(rows_for(d) for d in known))
        x, y = np.vstack(xs), np.concatenate(ys)
        coef = np.linalg.solve(x.T @ x + alpha * len(y) / 100 * np.eye(x.shape[1]), x.T @ y)
        today = pd.concat([ranks[n].loc[t] for n in names], axis=1)
        return pd.Series(today.fillna(0).to_numpy() @ coef, index=today.index).where(today.notna().all(axis=1))

    return score_at


# ------------------------------------------------------------- research ----


def research(close: pd.DataFrame, volume: pd.DataFrame, hold: int = HOLD, top_k: int = TOP_K,
             selection_share: float = SELECTION_SHARE) -> dict:
    factors = compute_factors(close, volume)
    ranks = {name: cross_sectional_rank(f) for name, f in factors.items()}
    excess = excess_returns(close, hold)
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
        periods = run_strategy(scorer, dates, excess, top_k)
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
        "results": results,
        "chosen_on_selection": winner,
    }


def current_picks(close: pd.DataFrame, volume: pd.DataFrame, hold: int = HOLD, top_k: int = TOP_K) -> dict:
    """Today's v2 candidate ranking: IC-weighted factors, weights learned only
    from rebalances whose outcome is already known. This was the only logic
    positive in every holdout of the 2026-11-24 robustness runs."""
    factors = compute_factors(close, volume)
    ranks = {name: cross_sectional_rank(f) for name, f in factors.items()}
    excess = excess_returns(close, hold)
    index = close.index
    # Rebalance dates counted back from today so the last one is today.
    dates = sorted(index[::-hold][: (len(index) - MIN_HISTORY) // hold + 1])
    scorer = ic_weighted_scorer(ranks, excess, dates, index, hold)
    today = index[-1]
    score = scorer(today).dropna().sort_values(ascending=False)
    return {
        "as_of": today.date().isoformat(),
        "hold_days": hold,
        "picks": [{"symbol": s, "score": float(v)} for s, v in score.head(top_k).items()],
        "ranked": len(score),
    }


def _print(report: dict) -> None:
    def pct(v):
        return "     -" if v is None else f"{v * 100:+6.2f}%"

    print(f"Universe: {len(report['universe'])} stocks | top {report['top_k']} | hold {report['hold']} days")
    print(f"Selection {report['first_rebalance']} .. {report['split']} | holdout .. {report['last_rebalance']}")
    print(f"Costs: {ROUND_TRIP_COST:.1%} round trip on changed names\n")
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
    parser.add_argument("--years", type=int, default=7)
    parser.add_argument("--hold", type=int, default=HOLD)
    parser.add_argument("--top", type=int, default=TOP_K)
    parser.add_argument("--symbols", nargs="*", default=list(UNIVERSE))
    parser.add_argument("--today", action="store_true",
                        help="print today's v2 candidate picks instead of the research table")
    args = parser.parse_args()
    close, volume = fetch_panel(args.symbols, args.years)
    if args.today:
        result = current_picks(close, volume, hold=args.hold, top_k=args.top)
        print(f"v2 candidate (IC-weighted, exploratory) as of {result['as_of']}, "
              f"hold {result['hold_days']} trading days, {result['ranked']} stocks ranked:")
        for i, pick in enumerate(result["picks"], 1):
            print(f"  {i}. {pick['symbol']:<6} score {pick['score']:+.3f}")
        return 0
    _print(research(close, volume, hold=args.hold, top_k=args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
