import pandas as pd
import streamlit as st

from aios_data import format_time, latest_scan, require_snapshot

snapshot = require_snapshot()
scans = snapshot.table("ranking_snapshots")
briefs = snapshot.table("decision_briefs")
accounts = snapshot.table("accounts")
jobs = snapshot.table("scheduler_job_runs")

current = latest_scan(snapshot)
last_scan_time = current["scan_time"].iloc[0] if not current.empty else None
age_days = (snapshot.exported_at - last_scan_time).days if last_scan_time is not None else None

st.caption(
    "AIOS gathers timestamped evidence for a watchlist of IDX stocks, ranks it, and only "
    "surfaces a conditional plan when every risk check passes. Stale or missing data "
    "produces WAIT / INSUFFICIENT_DATA instead of a signal."
)

with st.container(horizontal=True):
    st.metric("Latest scan", format_time(last_scan_time), border=True)
    st.metric(
        "Days since last scan",
        "—" if age_days is None else age_days,
        border=True,
        help="Counted from the export time. More than one trading day means the data is stale.",
    )
    st.metric("Symbols in latest scan", len(current), border=True)
    st.metric("Scans recorded", scans["scan_time"].nunique() if not scans.empty else 0, border=True)

with st.container(horizontal=True):
    buys = int((current["recommendation"] == "BUY").sum()) if not current.empty else 0
    st.metric("BUY signals (latest scan)", buys, border=True)
    st.metric("Decision briefs", len(briefs), border=True)
    blocked = int((briefs["status"] == "POLICY_BLOCKED").sum()) if not briefs.empty else 0
    st.metric("Blocked by risk policy", blocked, border=True)
    equity = accounts["equity"].iloc[0] if not accounts.empty else None
    st.metric("Paper equity (IDR)", "—" if equity is None else f"{equity:,.0f}", border=True)

if age_days is not None and age_days > 1:
    st.warning(
        f"The newest scan is {age_days} days old, so AIOS treats this data as stale and "
        "will not produce new trade plans from it.",
        title="Data is stale",
    )

left, right = st.columns([3, 2])
with left:
    with st.container(border=True):
        st.subheader("Latest scan ranking", anchor=False)
        if current.empty:
            st.info("No scans recorded yet.")
        else:
            st.dataframe(
                current[["rank", "symbol", "recommendation", "confidence", "score", "status"]],
                hide_index=True,
                column_config={
                    "rank": st.column_config.NumberColumn("Rank", width="small"),
                    "symbol": "Symbol",
                    "recommendation": "Recommendation",
                    "confidence": "Confidence",
                    "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                    "status": "Status",
                },
                alt="Ranking of the latest watchlist scan",
            )

with right:
    with st.container(border=True):
        st.subheader("Recommendations per scan", anchor=False)
        if scans.empty:
            st.info("No scans recorded yet.")
        else:
            # One label per scan, in time order. Scans seconds apart get the
            # seconds appended so they don't merge into one bar.
            times = sorted(scans["scan_time"].unique())
            short = [t.strftime("%d %b %H:%M") for t in times]
            labels = [
                t.strftime("%d %b %H:%M:%S") if short.count(s) > 1 else s
                for t, s in zip(times, short, strict=True)
            ]
            label_of = dict(zip(times, labels, strict=True))
            per_scan = (
                scans.assign(
                    scan=pd.Categorical(scans["scan_time"].map(label_of), categories=labels, ordered=True),
                    recommendation=scans["recommendation"].fillna("NONE"),
                )
                .groupby(["scan", "recommendation"], observed=True)
                .size()
                .reset_index(name="count")
            )
            st.bar_chart(
                per_scan,
                x="scan",
                y="count",
                color="recommendation",
                stack=True,
                alt="Count of BUY, WAIT, SELL and other recommendations in each scan",
            )

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

st.caption(
    f"Read-only export of the AIOS database, {format_time(snapshot.exported_at)}. "
    "Times are shown in WIB (UTC+7)."
)
