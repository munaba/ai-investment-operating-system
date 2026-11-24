import json

import streamlit as st

from aios_data import format_time, require_snapshot
from ui import as_badges, page_footer, rec_badge_column

snapshot = require_snapshot()
scans = snapshot.table("ranking_snapshots")

if scans.empty:
    st.info("No scans recorded yet.")
    st.stop()

scan_times = sorted(scans["scan_time"].unique(), reverse=True)
selected_time = st.selectbox(
    "Scan",
    scan_times,
    format_func=lambda t: f"{format_time(t)}  ({(scans['scan_time'] == t).sum()} symbols)",
)
scan = scans[scans["scan_time"] == selected_time].sort_values("rank")

with st.container(horizontal=True):
    st.metric("Symbols", len(scan), border=True)
    st.metric("BUY", int((scan["recommendation"] == "BUY").sum()), border=True)
    st.metric("WAIT", int((scan["recommendation"] == "WAIT").sum()), border=True)
    st.metric("SELL", int((scan["recommendation"] == "SELL").sum()), border=True)
    st.metric("Errors", int((scan["status"] != "success").sum()), border=True)

st.dataframe(
    as_badges(scan)[["rank", "symbol", "recommendation", "confidence", "priority", "score", "status", "error_message"]],
    hide_index=True,
    column_config={
        "rank": st.column_config.NumberColumn("#", width="small"),
        "symbol": st.column_config.TextColumn("Symbol", width="small"),
        "recommendation": rec_badge_column(),
        "confidence": "Confidence",
        "priority": st.column_config.NumberColumn("Priority", width="small"),
        "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
        "status": "Status",
        "error_message": "Error",
    },
    alt=f"Ranking for the scan of {format_time(selected_time)}",
)

st.subheader("Evidence for one symbol", anchor=False)
symbol = st.selectbox("Symbol", scan["symbol"].tolist())
row = scan[scan["symbol"] == symbol].iloc[0]

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.markdown("**Evidence summary**")
        summary = row["evidence_summary"]  # NULL arrives as NaN, not None
        st.text(summary if isinstance(summary, str) and summary else "No evidence recorded for this symbol.")
with right:
    with st.container(border=True):
        st.markdown("**Score breakdown**")
        raw_breakdown = row["score_breakdown_json"]
        try:
            breakdown = json.loads(raw_breakdown) if isinstance(raw_breakdown, str) else {}
        except ValueError:
            breakdown = {}
        if not isinstance(breakdown, dict):
            breakdown = {}
        contributions = {k: v for k, v in breakdown.items() if k.endswith("_contribution")}
        if contributions:
            st.bar_chart(
                {k.removesuffix("_contribution").replace("_", " "): v for k, v in contributions.items()},
                horizontal=True,
                alt=f"Score contribution per factor for {symbol}",
            )
        else:
            st.caption("No score breakdown recorded.")

st.subheader("Score history", anchor=False)
history = scans[scans["symbol"] == symbol].sort_values("scan_time")
st.line_chart(
    history, x="scan_time", y="score", x_label="Scan time (WIB)", y_label="Score (0–100)",
    alt=f"Score of {symbol} across all scans",
)
page_footer()
