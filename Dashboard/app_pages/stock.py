"""One stock across every scan: signal history, evaluated outcomes and briefs."""
import pandas as pd
import streamlit as st
from aios_data import format_time, require_snapshot
from ui import as_badges, page_footer, rec_badge_column, signal_history_chart, with_rec

snapshot = require_snapshot()
scans = snapshot.table("ranking_snapshots")

if scans.empty:
    st.info("No scans recorded yet.")
    st.stop()

symbols = sorted(scans["symbol"].dropna().unique())
latest_time = scans["scan_time"].max()
latest = scans[scans["scan_time"] == latest_time].sort_values("rank")
# Default to the top-ranked stock of the latest scan.
default_symbol = latest["symbol"].iloc[0] if not latest.empty else symbols[0]

symbol = st.selectbox(
    "Stock",
    symbols,
    index=symbols.index(default_symbol),
    key="symbol",
    bind="query-params",
    help="The choice is kept in the page URL, so a link opens the same stock.",
)

history = with_rec(scans[scans["symbol"] == symbol].sort_values("scan_time"))
scored = history.dropna(subset=["score"])
current = history.iloc[-1]

with st.container(horizontal=True):
    st.metric("Latest signal", current["recommendation"], border=True, help=f"Scan of {format_time(current['scan_time'])}")
    if len(scored) >= 2:
        st.metric(
            "Score",
            f"{scored['score'].iloc[-1]:.0f}",
            float(scored["score"].iloc[-1] - scored["score"].iloc[-2]),
            delta_description="vs. previous scan",
            border=True,
        )
    else:
        st.metric("Score", "—" if scored.empty else f"{scored['score'].iloc[-1]:.0f}", border=True)
    st.metric("Rank in latest scan", "—" if pd.isna(current["rank"]) else f"#{int(current['rank'])}", border=True)
    st.metric("Scans recorded", len(history), border=True)
    st.metric("BUY share", f"{(history['recommendation'] == 'BUY').mean():.0%}", border=True,
              help="Share of this stock's scans that ended in a BUY recommendation.")

with st.container(border=True):
    st.subheader("Signal history", anchor=False)
    if scored.empty:
        st.caption("No scored scans for this stock yet.")
    else:
        st.altair_chart(
            signal_history_chart(scored),
            alt=f"Score of {symbol} per scan, each point coloured by its recommendation",
        )

evaluation = snapshot.signal_evaluation
signals = pd.DataFrame(evaluation.get("signals", [])) if evaluation.get("status") == "OK" else pd.DataFrame()
with st.container(border=True):
    st.subheader("Evaluated signals", anchor=False)
    st.caption("Entry next close · exit after 5 trading days · excess vs watchlist")
    mine = signals[signals["symbol"] == symbol] if not signals.empty else signals
    if mine.empty:
        st.info("No evaluated signals for this stock in this export.")
    else:
        completed = mine[mine["status"] == "complete"].assign(
            excess_return=lambda f: pd.to_numeric(f["excess_return"], errors="coerce")
        )
        if not completed.empty:
            with st.container(horizontal=True):
                st.metric("Completed", len(completed), border=True)
                st.metric("Beat the watchlist", f"{(completed['excess_return'] > 0).mean():.0%}", border=True)
                st.metric("Mean excess", f"{completed['excess_return'].mean() * 100:+.2f}%", border=True)
        table = mine.sort_values("scan_date", ascending=False).assign(
            scan_date=pd.to_datetime(mine["scan_date"]).dt.date,
            # Pending signals have no return yet: empty cells, not "None".
            forward_return=pd.to_numeric(mine["forward_return"], errors="coerce") * 100,
            excess_return=pd.to_numeric(mine["excess_return"], errors="coerce") * 100,
        )
        st.dataframe(
            as_badges(table)[["scan_date", "recommendation", "status", "forward_return", "excess_return"]],
            hide_index=True,
            column_config={
                "scan_date": st.column_config.DateColumn("Scan date", format="D MMM YYYY"),
                "recommendation": rec_badge_column(),
                "status": "Status",
                "forward_return": st.column_config.NumberColumn("Return (%)", format="%+.2f"),
                "excess_return": st.column_config.NumberColumn("Excess (%)", format="%+.2f"),
            },
            alt=f"Evaluated signals for {symbol}",
        )

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.markdown("**Latest evidence**")
        summary = current["evidence_summary"]  # NULL arrives as NaN, not None
        st.text(summary if isinstance(summary, str) and summary else "No evidence recorded for this scan.")
with right, st.container(border=True):
    st.markdown("**Decision briefs**")
    briefs = snapshot.table("decision_briefs")
    mine_briefs = briefs[briefs["symbol"] == symbol] if not briefs.empty else briefs
    if mine_briefs.empty:
        st.caption("No decision brief generated for this stock.")
    else:
        st.dataframe(
            mine_briefs.sort_values("generated_at", ascending=False).assign(
                generated_at=mine_briefs["generated_at"].map(format_time)
            )[["generated_at", "status", "reason"]],
            hide_index=True,
            column_config={
                "generated_at": "Generated",
                "status": "Status",
                "reason": st.column_config.TextColumn("Reason", width="large"),
            },
            alt=f"Decision briefs for {symbol}",
        )

page_footer()
