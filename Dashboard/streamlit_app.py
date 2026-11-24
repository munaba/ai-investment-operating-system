"""AIOS public dashboard (read-only).

Run locally from the repository root:

    streamlit run Dashboard/streamlit_app.py
"""
import streamlit as st

from aios_data import format_time, load_snapshot
from ui import REPO_URL

st.set_page_config(page_title="AIOS dashboard", page_icon=":material/monitoring:", layout="wide")

page = st.navigation(
    [
        st.Page(
            "app_pages/overview.py",
            title="Overview",
            icon=":material/dashboard:",
            default=True,
            help="Latest scan, decision briefs, paper account and data freshness at a glance.",
        ),
        st.Page(
            "app_pages/scans.py",
            title="Scans and signals",
            icon=":material/query_stats:",
            help="Every recorded watchlist scan: ranking, recommendation, confidence and the evidence behind it.",
        ),
        st.Page(
            "app_pages/stock.py",
            title="Stock detail",
            icon=":material/candlestick_chart:",
            url_path="stock",
            help="One stock across every scan: signal history, evaluated outcomes, evidence and briefs.",
        ),
        st.Page(
            "app_pages/signals.py",
            title="Signal track record",
            icon=":material/fact_check:",
            help="Pre-registered test of whether BUY signals beat the watchlist over the next five trading days.",
        ),
        st.Page(
            "app_pages/briefs.py",
            title="Decision briefs",
            icon=":material/assignment:",
            help="Conditional trade plans and the risk-policy checks that blocked or allowed them.",
        ),
        st.Page(
            "app_pages/paper.py",
            title="Paper trading",
            icon=":material/account_balance_wallet:",
            help="Simulated account, positions, trades and equity. No real broker is connected.",
        ),
        st.Page(
            "app_pages/system.py",
            title="System health",
            icon=":material/monitor_heart:",
            help="Scheduler job runs, schema migrations and the operator observation window.",
        ),
    ]
)

with st.sidebar:
    st.caption(
        "AIOS is a decision-support system for Indonesian (IDX) stocks. "
        "It never places real orders; every plan needs human approval."
    )
    snapshot = load_snapshot()
    if snapshot is not None:
        st.caption(f"Data exported {format_time(snapshot.exported_at)}")
    st.link_button("Source code on GitHub", REPO_URL, icon=":material/code:", width="stretch")

st.title(page.title, anchor=False)
page.run()
