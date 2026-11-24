import numpy as np
import pandas as pd
import streamlit as st
from aios_data import WIB, format_time, latest_scan, require_snapshot
from ui import (
    REPO_URL,
    page_footer,
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
        date = f" :gray[{pd.Timestamp(m.rebalance_date).strftime('%d %b')}]" if m is not None and m.rebalance_date else ""
        st.markdown(f"**{MARKET_NAMES[name]}**{date}")
        if m is None or m.picks.empty:
            st.caption(f"First ranking at {SCHEDULE[name]}")
            continue
        top5 = m.picks[m.picks["rank"] <= 5].assign(score=lambda d: d["score"] * 100)
        st.dataframe(
            top5[["rank", "symbol", "score"]],
            hide_index=True,
            column_config={
                "rank": st.column_config.NumberColumn("#", width="small"),
                "symbol": st.column_config.TextColumn("Symbol", width="small"),
                "score": st.column_config.ProgressColumn(
                    "vs 200-day avg", format="%+.1f%%", min_value=0,
                    max_value=max(float(top5["score"].max()), 1.0),
                    help="How far the close is above its 200-day average."),
            },
            alt=f"Current v2 picks for {m.market.upper()}",
        )
        extra = list(m.picks[m.picks["rank"] > 5]["symbol"])
        if extra:
            st.markdown(":gray[v3 +] " + " ".join(f":gray-badge[{s}]" for s in extra))
st.page_link("app_pages/v2.py", label="Rankings and track record", icon=":material/arrow_forward:")

# --- v1, kept as the comparison ---------------------------------------------
with st.container(border=True):
    if current_v1.empty:
        st.markdown("**v1 scanner** :gray[comparison]")
        st.caption("No scans yet")
    else:
        counts = with_rec(current_v1)["recommendation"].value_counts()
        buy, wait, sell = (int(counts.get(r, 0)) for r in ("BUY", "WAIT", "SELL"))
        st.markdown(
            f"**v1 scanner** :gray[{format_time(last_scan_time)}]  \n"
            f":blue-badge[{buy} BUY] :orange-badge[{wait} WAIT] :violet-badge[{sell} SELL]"
        )
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
        f"[Full rules]({METHOD_URL})\n\n"
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
    f"Updated {format_time(snapshot.exported_at)} · WIB (UTC+7) · not investment advice"
)
page_footer()
