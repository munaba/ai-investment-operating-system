"""AIOS v2 signal model: cross-sectional trend ranking (plus research factors).

Pre-registered in Docs/SIGNAL_EVALUATION.md ("v2 registration"). Research
and backtests: Evaluation/factor_research.py.

v2 rule, for a market (IDX or US) and a signal date t (the last *completed*
close): rank every stock with at least ``MIN_HISTORY`` closes by how far its
close is above its 200-day simple moving average (``trend_vs_sma200``); the
``TOP_K`` highest are the picks, held ``HOLD`` trading days.

Why this rule: on every one of the 20 possible rebalance schedules it was
the only logic positive in at least 85% of schedules in the *selection*
period of both markets (IDX 20/20, US 17/20), and the holdouts confirmed
it (IDX 18/20, US 19/20). The IC-weighted eight-factor composite also lives
here (:func:`ic_weights`) for research; it failed the US selection period.

The module is pure (pandas/numpy) apart from :func:`yahoo_panel`, which
downloads prices lazily through yfinance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

MODEL_VERSION = "v2.0"
#: The single factor the v2 rule ranks on.
V2_FACTOR = "trend_vs_sma200"
HOLD = 20
TOP_K = 5
MIN_HISTORY = 252
#: Fewer earlier outcomes than this and the weights fall back to the
#: evidence composite below.
MIN_IC_SAMPLES = 6

#: Fixed from published evidence before testing: momentum that skips the
#: last month, residual momentum, and closeness to the 52-week high.
EVIDENCE_COMPOSITE = ("momentum_120d_skip20", "residual_momentum", "near_52w_high")


@dataclass(frozen=True)
class Market:
    name: str
    yahoo_suffix: str
    universe: tuple[str, ...]
    #: Approximate round-trip trading cost, used by research and evaluation.
    round_trip_cost: float
    timezone: str


IDX = Market(
    name="idx",
    yahoo_suffix=".JK",
    # Liquid IDX names as of late 2026 (today's list: survivorship bias).
    universe=("AALI", "ACES", "ADRO", "AKRA", "AMRT", "ANTM", "ARTO", "ASII", "AUTO", "BBCA", "BBNI", "BBRI", "BBTN", "BMRI", "BRIS", "BRPT", "BSDE", "CPIN", "CTRA", "ELSA", "EMTK", "ERAA", "ESSA", "EXCL", "HEAL", "HRUM", "ICBP", "INCO", "INDF", "INKP", "INTP", "ISAT", "ITMG", "JPFA", "JSMR", "KLBF", "LSIP", "MAPA", "MAPI", "MDKA", "MEDC", "MIKA", "MNCN", "MYOR", "PGAS", "PTBA", "PTPP", "PWON", "SCMA", "SIDO", "SMGR", "SMRA", "TINS", "TKIM", "TLKM", "TOWR", "UNTR", "UNVR", "WIKA"),
    round_trip_cost=0.004,  # buy + sell fees incl. 0.1% sales tax
    timezone="Asia/Jakarta",
)

US = Market(
    name="us",
    yahoo_suffix="",
    # About 100 large, liquid US stocks as of late 2026 (survivorship bias).
    universe=("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "AVGO", "TSLA", "JPM", "LLY", "V", "UNH", "XOM", "MA", "JNJ", "PG", "HD", "COST", "ABBV", "MRK", "CVX", "KO", "PEP", "WMT", "BAC", "ADBE", "CRM", "NFLX", "AMD", "TMO", "ORCL", "CSCO", "ACN", "MCD", "ABT", "LIN", "DHR", "WFC", "TXN", "DIS", "PM", "INTU", "VZ", "CMCSA", "NEE", "AMGN", "QCOM", "IBM", "HON", "UNP", "CAT", "GE", "AMAT", "LOW", "SPGI", "BA", "GS", "RTX", "ISRG", "BKNG", "PLD", "ELV", "SBUX", "MDT", "BLK", "DE", "NOW", "T", "SYK", "MS", "ADP", "GILD", "LMT", "TJX", "MMC", "VRTX", "ADI", "CVS", "C", "REGN", "SCHW", "MDLZ", "ZTS", "BMY", "CB", "MU", "LRCX", "PGR", "SO", "CI", "ETN", "BSX", "PANW", "KLAC", "DUK", "MO", "SNPS", "CDNS", "ICE"),
    round_trip_cost=0.001,  # commission-free brokers; spread and fees on large caps
    timezone="America/New_York",
)

MARKETS = {m.name: m for m in (IDX, US)}

# ---------------------------------------------------------------- data ----


def yahoo_panel(market: Market, start: date, end: date, symbols: tuple[str, ...] | None = None):
    """(close, volume) frames, date x symbol, for [start, end) from Yahoo."""
    import yfinance as yf

    symbols = symbols or market.universe
    tickers = [f"{s}{market.yahoo_suffix}" for s in symbols]
    raw = yf.download(
        tickers, start=start.isoformat(), end=end.isoformat(), interval="1d", auto_adjust=True,
        group_by="ticker", threads=True, progress=False, timeout=30,
    )
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame()
    rename = {f"{s}{market.yahoo_suffix}": s for s in symbols}
    close = raw.xs("Close", axis=1, level=1).rename(columns=rename)
    volume = raw.xs("Volume", axis=1, level=1).rename(columns=rename)
    close.index = pd.to_datetime([ts.date() for ts in close.index])
    volume.index = close.index
    close = close.dropna(axis=1, how="all").sort_index()
    return close, volume.reindex(columns=close.columns)


# ------------------------------------------------------------- factors ----


def residual_momentum(close: pd.DataFrame, window: int = 120, skip: int = 20) -> pd.DataFrame:
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
    """The eight v2 factors; higher = more attractive. Data up to each row only."""
    ret = close.pct_change(fill_method=None)
    traded = (close * volume).where(volume > 0)
    return {
        "momentum_60d": close / close.shift(60) - 1,
        "momentum_120d_skip20": close.shift(20) / close.shift(120) - 1,
        "residual_momentum": residual_momentum(close),
        "near_52w_high": close / close.rolling(MIN_HISTORY).max(),
        "low_volatility_60d": -ret.rolling(60).std(),
        "reversal_5d": -(close / close.shift(5) - 1),
        "trend_vs_sma200": close / close.rolling(200).mean() - 1,
        "liquidity_20d": np.log(traded.rolling(20).mean()),
    }


def cross_sectional_rank(frame: pd.DataFrame) -> pd.DataFrame:
    """Per-date percentile rank centred on 0 (-0.5 .. +0.5)."""
    return frame.rank(axis=1, pct=True) - 0.5


def forward_excess(close: pd.DataFrame, hold: int = HOLD) -> pd.DataFrame:
    """Excess return of a signal dated on each row: entry at the next close,
    exit ``hold`` trading days later, minus the equal-weight universe mean."""
    entry = close.shift(-1)
    exit_ = close.shift(-(1 + hold))
    forward = exit_ / entry - 1
    return forward.sub(forward.mean(axis=1), axis=0)


# ------------------------------------------------------------- weights ----


def known_dates(dates: list, t: pd.Timestamp, index: pd.DatetimeIndex, hold: int) -> list:
    """Sample dates whose outcome was complete at t (exit close on or before t)."""
    pos = index.get_loc(t)
    if pos <= hold + 1:
        return []
    cutoff = index[pos - (hold + 1)]
    return [d for d in dates if d <= cutoff]


def ic_weights(ranks: dict[str, pd.DataFrame], excess: pd.DataFrame, sample_dates: list,
               cache: dict | None = None) -> dict[str, float]:
    """Mean rank IC per factor over ``sample_dates``, scaled so sum(|w|) = 1.
    Falls back to equal weights on the evidence composite when there are
    fewer than ``MIN_IC_SAMPLES`` dates."""
    if len(sample_dates) < MIN_IC_SAMPLES:
        return {n: (1 / len(EVIDENCE_COMPOSITE) if n in EVIDENCE_COMPOSITE else 0.0) for n in ranks}
    cache = {} if cache is None else cache
    excess_rank = excess.rank(axis=1, pct=True)

    def rank_ic(name: str, d: pd.Timestamp) -> float:
        key = (name, d)
        if key not in cache:
            pair = pd.concat([ranks[name].loc[d], excess_rank.loc[d]], axis=1).dropna()
            cache[key] = float(pair.iloc[:, 0].corr(pair.iloc[:, 1])) if len(pair) > 10 else np.nan
        return cache[key]

    raw = {name: float(np.nanmean([rank_ic(name, d) for d in sample_dates])) for name in ranks}
    raw = {k: (0.0 if np.isnan(v) else v) for k, v in raw.items()}
    total = sum(abs(v) for v in raw.values()) or 1.0
    return {k: v / total for k, v in raw.items()}


def weighted_score(ranks: dict[str, pd.DataFrame], weights: dict[str, float], t: pd.Timestamp) -> pd.Series:
    return sum(ranks[n].loc[t] * w for n, w in weights.items())


# ------------------------------------------------------------- ranking ----


@dataclass(frozen=True)
class Ranking:
    market: str
    signal_date: date
    scores: pd.Series  # symbol -> score, highest first
    weights: dict[str, float] = field(default_factory=dict)
    model_version: str = MODEL_VERSION

    def picks(self, top_k: int = TOP_K) -> list[str]:
        return list(self.scores.head(top_k).index)


def sample_dates_ending_at(index: pd.DatetimeIndex, hold: int = HOLD) -> list[pd.Timestamp]:
    """Every ``hold``-th trading date counted back from the last one."""
    usable = len(index) - MIN_HISTORY
    if usable < 0:
        return []
    return sorted(index[::-hold][: usable // hold + 1])


def rank_universe(market: Market, close: pd.DataFrame, volume: pd.DataFrame, hold: int = HOLD) -> Ranking:
    """Apply the v2 rule on the last row of ``close``.

    Score = close / SMA200 - 1 for stocks with a full ``MIN_HISTORY`` of
    closes; highest first. ``volume`` and ``hold`` are accepted so the
    signature stays stable if a later version ranks on more factors."""
    if len(close.index) <= MIN_HISTORY:
        raise ValueError(f"need more than {MIN_HISTORY} trading days of history, got {len(close.index)}")
    t = close.index[-1]
    trend = close / close.rolling(200).mean() - 1
    eligible = close.iloc[-MIN_HISTORY:].notna().all()
    scores = trend.loc[t][eligible].dropna().sort_values(ascending=False)
    return Ranking(market=market.name, signal_date=t.date(), scores=scores, weights={V2_FACTOR: 1.0})


def history_window(signal_end: date, years: int = 5) -> tuple[date, date]:
    """[start, end) for :func:`yahoo_panel` so the last row is before ``signal_end``."""
    return signal_end - timedelta(days=365 * years), signal_end
