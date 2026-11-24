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

snapshot = require_snapshot()
scans = snapshot.table("ranking_snapshots")
briefs = snapshot.table("decision_briefs")
accounts = snapshot.table("accounts")
jobs = snapshot.table("scheduler_job_runs")
evaluation = snapshot.signal_evaluation

current = latest_scan(snapshot)
last_scan_time = current["scan_time"].iloc[0] if not current.empty else None

# Age is measured against *now*, not the export time: if publishing stops,
# the page must still show that the data is getting old. Weekends and the
# IDX holidays exported with the snapshot are not counted.
age_days = (
    None
    if last_scan_time is None
    else int(np.busday_count(
        last_scan_time.date(), pd.Timestamp.now(tz=WIB).date(), holidays=snapshot.market_holidays
    ))
)
counts = with_rec(current)["recommendation"].value_counts() if not current.empty else pd.Series(dtype=int)

# --- One-line status: what a first-time visitor needs to know -------------
if last_scan_time is None:
    st.info("No scans recorded yet. The scheduler fills this page on IDX trading days.")
else:
    buy, wait, sell = (int(counts.get(r, 0)) for r in ("BUY", "WAIT", "SELL"))
    official = evaluation.get("official", {}).get("by_recommendation", {}).get("BUY", {})
    done = official.get("completed", 0)
    need = evaluation.get("rules", {}).get("min_buy_signals", 30)
    st.markdown(
        f"Last scan **{format_time(last_scan_time)}** on {len(current)} IDX stocks: "
        f":blue-badge[{buy} BUY] :orange-badge[{wait} WAIT] :violet-badge[{sell} SELL]  \n"
        f"Signal evaluation: **{done} of {need}** BUY signals completed "
        f"(verdict after {need}; see *Signal track record*)."
    )

if age_days is not None and age_days > 1:
    st.warning(
        f"The newest scan is {age_days} trading days old (exported {format_time(snapshot.exported_at)}), "
        "so AIOS treats this data as stale and will not produce new trade plans from it.",
        title="Data is stale",
    )

with st.container(horizontal=True):
    st.metric(
        "Trading days since last scan",
        "—" if age_days is None else age_days,
        border=True,
        help="Counted up to now, skipping weekends and IDX holidays. More than one means the data is stale.",
    )
    st.metric("Trading days scanned", scans["scan_time"].dt.date.nunique() if not scans.empty else 0, border=True)
    st.metric("Decision briefs", len(briefs), border=True)
    blocked = int((briefs["status"] == "POLICY_BLOCKED").sum()) if not briefs.empty else 0
    st.metric("Blocked by risk policy", blocked, border=True)
    equity = accounts["equity"].iloc[0] if not accounts.empty else None
    st.metric("Paper equity", "—" if equity is None else f"Rp {equity:,.0f}", border=True)

left, right = st.columns([3, 2], gap="medium")
with left:
    with st.container(border=True):
        st.subheader("Latest scan ranking", anchor=False)
        if current.empty:
            st.info("No scans recorded yet.")
        else:
            st.dataframe(
                as_badges(current)[["rank", "symbol", "recommendation", "confidence", "score"]],
                hide_index=True,
                column_config={
                    "rank": st.column_config.NumberColumn("#", width="small"),
                    "symbol": st.column_config.TextColumn("Symbol", width="small"),
                    "recommendation": rec_badge_column(),
                    "confidence": st.column_config.TextColumn("Confidence", width="small"),
                    "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                },
                alt="Ranking of the latest watchlist scan with each stock's recommendation and score",
            )

with right:
    with st.container(border=True):
        st.subheader("Latest scheduler activity", anchor=False)
        if jobs.empty:
            st.info("The scheduler has not run yet.")
        else:
            recent = jobs.sort_values("started_at", ascending=False).head(5)
            st.dataframe(
                recent.assign(started_at=recent["started_at"].map(format_time))[
                    ["job_type", "status", "started_at"]
                ],
                hide_index=True,
                column_config={"job_type": "Job", "status": "Status", "started_at": "Started"},
                alt="Five most recent scheduler job runs",
            )

with st.container(border=True):
    st.subheader("Recommendations by trading day", anchor=False)
    if scans.empty:
        st.info("No scans recorded yet.")
    else:
        # One bar per trading day, from that day's last scan, so the chart
        # stays readable with ~13 scans a day.
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
            alt="Count of BUY, WAIT, SELL and no-signal stocks in the last scan of each trading day",
        )

with st.expander("How AIOS works", icon=":material/info:"):
    st.markdown(
        "1. **Scan.** On IDX trading days a scheduler scans an 11-stock watchlist (at most every "
        "30 minutes) and combines price trend, news sentiment and valuation into BUY, WAIT or SELL.\n"
        "2. **Fail closed.** Stale or missing evidence gives no signal at all, never a guess.\n"
        "3. **Plan, then a human decides.** An actionable signal becomes a conditional plan "
        "(entry, stop, target, size) only if the risk policy passes; AIOS never places real orders.\n"
        "4. **Measure.** A pre-registered test checks whether BUY signals beat the watchlist "
        "over the next five trading days.\n\n"
        f"Code and documentation: [GitHub]({REPO_URL})."
    )

st.caption(
    f"Read-only export of the AIOS database, {format_time(snapshot.exported_at)}. "
    "Times are shown in WIB (UTC+7)."
)
page_footer()
