import streamlit as st
from aios_data import format_time, require_snapshot
from ui import page_footer

snapshot = require_snapshot()
accounts = snapshot.table("accounts")
positions = snapshot.table("positions")
trades = snapshot.table("trades")
equity_history = snapshot.table("portfolio_snapshots")

st.caption("Simulated · no real orders")

if accounts.empty:
    st.info("No paper account has been created yet.")
    st.stop()

account = accounts.iloc[0]
if positions.empty and trades.empty and equity_history.empty:
    # One honest line instead of five identical tiles and three empty tables.
    with st.container(border=True):
        st.markdown("**No paper trades yet**")
        st.markdown(f"Starting balance **Rp {account['equity']:,.0f}**")
        st.page_link("app_pages/briefs.py", label="See the decision briefs", icon=":material/arrow_forward:")
    page_footer()
    st.stop()

with st.container(horizontal=True):
    st.metric("Cash", f"Rp {account['cash']:,.0f}", border=True)
    st.metric("Equity", f"Rp {account['equity']:,.0f}", border=True)
    st.metric("Buying power", f"Rp {account['buying_power']:,.0f}", border=True)
    open_positions = int((positions["status"] == "OPEN").sum()) if not positions.empty else 0
    st.metric("Open positions", open_positions, border=True)
    st.metric("Trades", len(trades), border=True)

with st.container(border=True):
    st.subheader("Equity over time", anchor=False)
    if equity_history.empty:
        st.info("No snapshots yet.")
    else:
        st.line_chart(equity_history, x="timestamp", y="equity", alt="Paper account equity over time")

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.subheader("Positions", anchor=False)
        if positions.empty:
            st.info("No positions.")
        else:
            st.dataframe(
                positions[["symbol", "direction", "quantity", "average_price", "realized_pnl", "status"]],
                hide_index=True,
                alt="Paper positions",
            )
with right:
    with st.container(border=True):
        st.subheader("Trades", anchor=False)
        if trades.empty:
            st.info("No trades.")
        else:
            st.dataframe(
                trades.assign(executed_at=trades["executed_at"].map(format_time))[
                    ["executed_at", "symbol", "action", "quantity", "fill_price", "fee", "tax"]
                ],
                hide_index=True,
                alt="Paper trades",
            )

page_footer()
