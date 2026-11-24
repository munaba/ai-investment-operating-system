"""v2 / v3 trend signal: current picks, latest ranking and track record."""
import altair as alt
import pandas as pd
import streamlit as st
from aios_data import require_snapshot
from ui import REPO_URL, page_footer

snapshot = require_snapshot()
rankings = snapshot.table("v2_rankings")
# getattr: a hot-reloaded page can briefly run against the previous
# aios_data module (Streamlit Cloud redeploy) that lacks this field.
evaluation = getattr(snapshot, "v2_evaluation", None) or {
    "status": "UNAVAILABLE", "error": "the app is still reloading; refresh in a minute"}

with st.expander("How v2 / v3 work", icon=":material/info:"):
    st.caption(
        "v2 ranks liquid stocks by how far the close is above its 200-day average and buys the top 5 "
        "every 20 trading days, holding 20 days. v3 is the same ranking with the top 10. Both rules were "
        "registered before their first signal and are judged against the average of every ranked stock."
    )

if rankings.empty:
    st.info("No ranking yet · IDX 08:30 WIB, US 20:45 WIB")
    page_footer()
    st.stop()

markets = sorted(rankings["market"].unique())
market = st.segmented_control(
    "Market", markets, default=markets[0], format_func=str.upper, key="market", bind="query-params",
) or markets[0]
rows = rankings[rankings["market"] == market]
rebalances = rows[rows["is_rebalance"] == 1]

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.subheader("Current picks", anchor=False)
        if rebalances.empty:
            st.caption("No rebalance stored yet.")
        else:
            last = rebalances["signal_date"].max()
            current = rebalances[rebalances["signal_date"] == last].sort_values("rank").head(10)
            st.caption(f"Rebalance {last}")
            st.space("small")  # keeps the table toolbar off the caption on phones
            st.dataframe(
                current.assign(version=["v2, v3" if r <= 5 else "v3" for r in current["rank"]],
                               score=current["score"] * 100)[["symbol", "score", "version"]],
                hide_index=True,
                column_config={
                    "symbol": st.column_config.TextColumn("Stock", width="small"),
                    "score": st.column_config.NumberColumn("vs 200-day", format="%+.1f%%", width="small"),
                    "version": st.column_config.TextColumn("In", width="small"),
                },
                alt=f"Current v2 and v3 picks for {market.upper()}",
            )
with right:
    with st.container(border=True):
        st.subheader("Latest ranking", anchor=False)
        latest_date = rows["signal_date"].max()
        latest = rows[rows["signal_date"] == latest_date].sort_values("rank").head(10)
        st.caption(f"Closes up to {latest_date}")
        chart = (
            alt.Chart(latest.assign(pct=latest["score"] * 100))
            .mark_bar(cornerRadiusEnd=3, color="#3987e5")
            .encode(  # ty: ignore[missing-attribute] -- Altair's decorated mark_* methods
                x=alt.X("pct:Q", title="% above 200-day average"),
                y=alt.Y("symbol:N", sort=alt.EncodingSortField("rank"), title=None),
                tooltip=[alt.Tooltip("rank:Q", title="Rank"), alt.Tooltip("symbol:N", title="Stock"),
                         alt.Tooltip("pct:Q", title="Above 200-day avg (%)", format="+.1f")],
            )
            .properties(height=300)
        )
        st.altair_chart(chart, alt=f"Top 10 {market.upper()} stocks by distance above the 200-day average")

with st.container(border=True):
    st.subheader("Track record", anchor=False)
    if evaluation.get("status") != "OK":
        st.info(f"Evaluation not in this export ({evaluation.get('error', 'unknown reason')}).",
                title="Evaluation unavailable")
    else:
        summary = evaluation.get("markets", {}).get(market)
        if not summary:
            st.caption("No rebalance to evaluate yet.")
        else:
            labels = {"DATA_TIDAK_CUKUP": ("Not enough data yet", "gray"), "PASS": ("Pass", "green"),
                      "FAIL": ("Fail", "red")}
            with st.container(horizontal=True):
                for version in ("v2", "v3"):
                    s = summary[version]
                    text, color = labels.get(s["verdict"], (s["verdict"], "gray"))
                    with st.container(border=True):
                        st.markdown(f"**{version}** :{color}-badge[{text}]")
                        st.metric("Completed picks", f"{s['completed']} / {evaluation['rules']['min_completed']}",
                                  help="A verdict needs this many picks whose 20-day hold has ended.")
                        st.metric("Mean net excess", "—" if "mean_net" not in s else f"{s['mean_net']:+.2%}")
                        st.metric("Pending", s["pending"])
            picks = pd.DataFrame([p for p in evaluation.get("picks", []) if p["market"] == market])
            if not picks.empty:
                picks = picks.assign(**{c: pd.to_numeric(picks[c], errors="coerce") * 100
                                        for c in ("return", "excess", "net_excess")})
                st.dataframe(
                    picks.sort_values(["signal_date", "version"], ascending=[False, True])[
                        ["signal_date", "version", "symbol", "status", "entry_date", "exit_date", "return", "net_excess"]
                    ],
                    hide_index=True,
                    column_config={
                        "signal_date": "Signal", "version": "Version", "symbol": "Stock", "status": "Status",
                        "entry_date": "Entry", "exit_date": "Exit",
                        "return": st.column_config.NumberColumn("Return (%)", format="%+.2f"),
                        "net_excess": st.column_config.NumberColumn("Net excess (%)", format="%+.2f"),
                    },
                    alt=f"Every evaluated v2 and v3 pick for {market.upper()}",
                )

st.caption(f"Not financial advice · [Rules]({REPO_URL}/blob/master/Docs/SIGNAL_EVALUATION.md)")
page_footer()
