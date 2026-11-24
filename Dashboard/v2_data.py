"""Helpers added after aios_data: v2/v3 per-market state and compact times.

Kept in their own module on purpose. During a Streamlit Cloud redeploy a
page can run against the previously imported aios_data module; a page
importing new names from it then fails with ImportError. A module that was
never imported before is always loaded fresh.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from aios_data import Snapshot


def format_short(value: pd.Timestamp | None) -> str:
    """Compact time for narrow table columns, e.g. "24 Nov 16:39"."""
    if value is None or pd.isna(value):
        return "—"
    return value.strftime("%d %b %H:%M")


@dataclass(frozen=True)
class V2Market:
    market: str
    rebalance_date: str | None
    picks: pd.DataFrame  # ranks 1-10 on the last rebalance: symbol, rank, score
    latest_date: str | None
    sessions_since_rebalance: int | None


V2_HOLD_SESSIONS = 20


def v2_markets(snapshot: Snapshot) -> list[V2Market]:
    """Current v2/v3 state per market from the exported v2_rankings rows."""
    rows = snapshot.table("v2_rankings")
    if rows.empty:
        return []
    holidays = getattr(snapshot, "market_holidays", [])
    out = []
    for market, frame in sorted(rows.groupby("market"), key=lambda kv: kv[0]):
        rebalances = frame[frame["is_rebalance"] == 1]
        latest = str(frame["signal_date"].max())
        if rebalances.empty:
            out.append(V2Market(market, None, pd.DataFrame(), latest, None))
            continue
        last = str(rebalances["signal_date"].max())
        picks = rebalances[rebalances["signal_date"] == last].sort_values("rank").head(10)
        # Approximate: weekdays, plus IDX holidays for the IDX market.
        sessions = int(np.busday_count(last, latest, holidays=holidays if market == "idx" else []))
        out.append(V2Market(market, last, picks[["symbol", "rank", "score"]], latest, sessions))
    return out
