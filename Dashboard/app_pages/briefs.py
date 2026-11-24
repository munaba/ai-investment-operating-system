import pandas as pd
import streamlit as st

from aios_data import format_time, require_snapshot
from ui import page_footer

snapshot = require_snapshot()
briefs = snapshot.table("decision_briefs")

with st.expander("What a decision brief is", icon=":material/info:"):
    st.caption(
        "A decision brief turns an actionable scan result into a conditional plan: entry, stop "
        "loss, take profit and position size. The risk policy blocks the brief when any of those "
        "inputs is missing or the data is stale; a human still approves every plan."
    )

if briefs.empty:
    st.info("No decision briefs generated yet.")
    st.stop()

# Blocked briefs have no plan; make those cells empty numbers, not "None".
numeric = ["entry_price", "stop_loss_price", "take_profit_price", "risk_reward_ratio", "risk_amount", "position_size"]
briefs = briefs.assign(**{c: pd.to_numeric(briefs[c], errors="coerce") for c in numeric})

with st.container(horizontal=True):
    for status, count in briefs["status"].value_counts().items():
        st.metric(str(status), int(count), border=True)

st.dataframe(
    briefs.assign(generated_at=briefs["generated_at"].map(format_time))[
        [
            "brief_id",
            "symbol",
            "generated_at",
            "status",
            "entry_price",
            "stop_loss_price",
            "take_profit_price",
            "risk_reward_ratio",
            "risk_amount",
            "position_size",
            "reason",
        ]
    ],
    hide_index=True,
    column_config={
        "brief_id": st.column_config.NumberColumn("ID", width="small"),
        "symbol": "Symbol",
        "generated_at": "Generated",
        "status": "Status",
        "entry_price": st.column_config.NumberColumn("Entry", format="%.1f"),
        "stop_loss_price": st.column_config.NumberColumn("Stop loss", format="%.1f"),
        "take_profit_price": st.column_config.NumberColumn("Take profit", format="%.1f"),
        "risk_reward_ratio": st.column_config.NumberColumn("R:R", format="%.1f"),
        "risk_amount": st.column_config.NumberColumn("Risk (IDR)", format="%,.0f"),
        "position_size": st.column_config.NumberColumn("Size (shares)", format="%,.0f"),
        "reason": st.column_config.TextColumn("Reason", width="large"),
    },
    alt="All decision briefs with their risk plan and policy outcome",
)

page_footer()
