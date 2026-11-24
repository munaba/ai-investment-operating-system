"""AIOS public dashboard (read-only).

Run locally from the repository root:

    streamlit run Dashboard/streamlit_app.py
"""
import streamlit as st
from aios_data import format_time, load_snapshot
from ui import REPO_URL

st.set_page_config(page_title="AIOS dashboard", page_icon=":material/monitoring:", layout="wide")

# Pages are grouped by what a visitor is looking for; url_path follows the
# title so a link like /paper-trading works.
page = st.navigation(
    {
        "": [
            st.Page(
                "app_pages/overview.py",
                title="Overview",
                icon=":material/dashboard:",
                default=True,
                help="Current v2/v3 picks for IDX and US, test progress and data freshness.",
            ),
        ],
        "v2 / v3 trend signal": [
            st.Page(
                "app_pages/v2.py",
                title="v2 / v3 picks",
                icon=":material/trending_up:",
                url_path="v2",
                help="Trend signal for IDX and US: current picks, latest ranking and track record.",
            ),
        ],
        "v1 scanner (comparison)": [
            st.Page(
                "app_pages/scans.py",
                title="Scans",
                icon=":material/query_stats:",
                url_path="scans",
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
                title="v1 track record",
                icon=":material/fact_check:",
                url_path="v1-track-record",
                help="Pre-registered test of whether v1 BUY signals beat the watchlist over five trading days.",
            ),
            st.Page(
                "app_pages/briefs.py",
                title="Decision briefs",
                icon=":material/assignment:",
                url_path="decision-briefs",
                help="Conditional trade plans and the risk-policy checks that blocked or allowed them.",
            ),
        ],
        "Operations": [
            st.Page(
                "app_pages/paper.py",
                title="Paper trading",
                icon=":material/account_balance_wallet:",
                url_path="paper-trading",
                help="Simulated account, positions, trades and equity. No real broker is connected.",
            ),
            st.Page(
                "app_pages/system.py",
                title="System health",
                icon=":material/monitor_heart:",
                url_path="system-health",
                help="Scheduler job runs, schema migrations and the operator observation window.",
            ),
        ],
    }
)

with st.sidebar:
    st.caption(
        "AIOS is a research system that ranks IDX and US stocks with a pre-registered "
        "trend rule. It never places real orders."
    )
    snapshot = load_snapshot()
    if snapshot is not None:
        st.caption(f"Data exported {format_time(snapshot.exported_at)}")
    st.link_button("Source code on GitHub", REPO_URL, icon=":material/code:", width="stretch")

st.title(page.title, anchor=False)
page.run()
