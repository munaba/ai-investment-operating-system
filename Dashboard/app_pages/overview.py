import numpy as np
import pandas as pd
import streamlit as st
from aios_data import WIB, format_time, latest_scan, require_snapshot
from ui import (
    REPO_URL,
    as_badges,
    page_footer,
    rec_badge_column,
    recommendations_per_scan_chart,
    with_rec,
)
from v2_data import V2_HOLD_SESSIONS, v2_markets

METHOD_URL = f"{REPO_URL}/blob/master/Docs/SIGNAL_EVALUATION.md"
MARKET_NAMES = {"idx": "Indonesia (IDX)", "us": "United States"}

snapshot = require_snapshot()
scans = snapshot.table("ranking_snapshots")
markets = v2_markets(snapshot)
# getattr: a hot-reloaded page can briefly run against the previous aios_data
# module (Streamlit Cloud redeploy) that lacks this field.
v2_eval = getattr(snapshot, "v2_evaluation", None) or {}

# --- What this is, for a first-time visitor ---------------------------------
st.markdown(
    "AIOS ranks liquid **Indonesian and US stocks** every trading day with a simple trend rule "
    "(close vs. its 200-day average), buys the top picks on paper every 20 trading days, and is "
    "judged only on live results against rules fixed in advance. It runs unattended and never "
    f"places real orders. [How it works and the rules]({METHOD_URL})"
)

# --- Key numbers ------------------------------------------------------------
current_v1 = latest_scan(snapshot)
last_scan_time = current_v1["scan_time"].iloc[0] if not current_v1.empty else None
# Measured against *now*: if publishing stops, the page must show the data ageing.
age_days = (
    None
    if last_scan_time is None
    else int(np.busday_count(last_scan_time.date(), pd.Timestamp.now(tz=WIB).date(),
                             holidays=getattr(snapshot, "market_holidays", [])))
)

active = [m for m in markets if m.rebalance_date]
completed = sum(v2_eval.get("markets", {}).get(m.market, {}).get("v2", {}).get("completed", 0) for m in markets)
need = v2_eval.get("rules", {}).get("min_completed", 30)
next_due = [max(V2_HOLD_SESSIONS - (m.sessions_since_rebalance or 0), 0) for m in active]
newest = max((m.latest_date for m in markets if m.latest_date), default=None)

# Short labels and values so tiles can share a row on narrow screens.
with st.container(horizontal=True):
    st.metric("Active picks", sum(min(len(m.picks), 5) for m in active), border=True, width="stretch",
              help="Top 5 per market from the last rebalance (v3 holds the top 10).")
    st.metric("Next rebalance", "—" if not next_due else f"~{min(next_due)} days", border=True, width="stretch",
              help="Trading days until the next 20-session rebalance in the soonest market (approximate).")
    st.metric("Completed picks", f"{completed}/{need * max(len(markets), 1)}", border=True, width="stretch",
              help=f"A market's verdict needs {need} picks whose 20-day hold has ended.")
    st.metric("Latest close", pd.Timestamp(newest).strftime("%d %b") if newest else "—", border=True,
              width="stretch",
              help="Closing date the latest v2 ranking is based on.")

if age_days is not None and age_days > 1:
    st.warning(
        f"The newest IDX scan is {age_days} trading days old (exported {format_time(snapshot.exported_at)}). "
        "The scheduler may have stopped.",
        title="Data is getting old",
    )

# --- Current picks per market -----------------------------------------------
st.subheader("Current picks", anchor=False)
SCHEDULE = {"idx": "08:30 WIB", "us": "20:45 WIB"}
by_market = {m.market: m for m in markets}
# Both markets always get a card, so the layout stays balanced.
for column, name in zip(st.columns(len(MARKET_NAMES), gap="medium"), MARKET_NAMES, strict=True):
    m = by_market.get(name)
    with column, st.container(border=True, height="stretch"):
        st.markdown(f"**{MARKET_NAMES[name]}**")
        if m is None or m.picks.empty:
            st.caption(f"No picks yet. The first ranking runs at {SCHEDULE[name]} on the next "
                       "trading day and its picks appear here.")
            continue
        st.caption(f"Rebalanced on closes of {m.rebalance_date}; held 20 trading days.")
        st.space("small")  # keeps the table toolbar off the caption on phones
        top5 = m.picks[m.picks["rank"] <= 5]
        st.dataframe(
            top5.assign(score=top5["score"] * 100)[["symbol", "score"]],
            hide_index=True,
            column_config={
                "symbol": st.column_config.TextColumn("v2 pick", width="small"),
                "score": st.column_config.NumberColumn("vs 200-day avg", format="%+.1f%%"),
            },
            alt=f"Current v2 picks for {m.market.upper()}",
        )
        extra = list(m.picks[m.picks["rank"] > 5]["symbol"])
        if extra:
            st.caption("v3 also holds: " + ", ".join(extra))
st.page_link("app_pages/v2.py", label="Rankings and track record", icon=":material/arrow_forward:")

# --- v1, kept as the comparison ---------------------------------------------
with st.container(border=True):
    st.subheader("v1 scanner (comparison)", anchor=False)
    if current_v1.empty:
        st.info("No v1 scans recorded yet.")
    else:
        counts = with_rec(current_v1)["recommendation"].value_counts()
        buy, wait, sell = (int(counts.get(r, 0)) for r in ("BUY", "WAIT", "SELL"))
        st.markdown(
            f"The original rule-based scanner still runs every 30 minutes on 11 IDX stocks. "
            f"Last scan **{format_time(last_scan_time)}**: :blue-badge[{buy} BUY] "
            f":orange-badge[{wait} WAIT] :violet-badge[{sell} SELL]. Backtests showed its price "
            "input has no edge; it stays as the baseline v2 must beat."
        )
        st.space("small")  # keeps the table toolbar off the paragraph on phones
        left, right = st.columns([2, 3], gap="medium")
        with left:
            top_score = float(current_v1["score"].max()) if current_v1["score"].notna().any() else 1.0
            st.dataframe(
                as_badges(current_v1)[["symbol", "recommendation", "score"]],
                hide_index=True,
                column_config={
                    "symbol": st.column_config.TextColumn("Stock", width="small"),
                    "recommendation": rec_badge_column(),
                    "score": st.column_config.ProgressColumn(
                        "Score", min_value=0, max_value=max(top_score, 1.0), format="%d",
                        help="Bar relative to the highest score in this scan."),
                },
                alt="Latest v1 scan: each stock's recommendation and score",
            )
        with right:
            day = scans["scan_time"].dt.date
            last_of_day = scans[scans["scan_time"] == scans.groupby(day)["scan_time"].transform("max")]
            order = [d.strftime("%d %b") for d in sorted(day.unique())]
            per_day = (
                with_rec(last_of_day)
                .assign(scan=last_of_day["scan_time"].dt.strftime("%d %b"))
                .value_counts(["scan", "recommendation"], sort=False)
                .reset_index(name="count")
            )
            st.altair_chart(
                recommendations_per_scan_chart(per_day, order),
                alt="Count of BUY, WAIT, SELL and no-signal stocks in the last v1 scan of each trading day",
            )

with st.expander("How AIOS works", icon=":material/info:"):
    st.markdown(
        "1. **Rank.** Each trading morning (IDX 08:30 WIB, US 20:45 WIB) AIOS ranks a fixed list of "
        "liquid stocks by how far the close is above its 200-day average.\n"
        "2. **Rebalance.** Every 20 trading days the top 5 (v2) and top 10 (v3) become the picks, "
        "sent to Telegram.\n"
        "3. **Measure.** Each pick is scored 20 trading days later against the average of all ranked "
        "stocks, after costs. A verdict needs 30 completed picks per market.\n"
        "4. **No shortcuts.** The rules were registered before the first signal, chosen with "
        "out-of-sample tests on stocks never used to design them, and are never edited afterwards.\n\n"
        f"Code and documentation: [GitHub]({REPO_URL})."
    )

st.caption(
    f"Read-only export of the AIOS database, {format_time(snapshot.exported_at)}. "
    "Times are shown in WIB (UTC+7)."
)
page_footer()
