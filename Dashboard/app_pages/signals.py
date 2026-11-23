import pandas as pd
import streamlit as st

from aios_data import require_snapshot

snapshot = require_snapshot()
evaluation = snapshot.signal_evaluation

st.caption(
    "Do BUY recommendations beat the rest of the watchlist over the next week? The rules were "
    "registered before the automated scans started and are not changed afterwards: one signal per "
    "stock per day, entry at the next close, exit five trading days later, compared with the "
    "equal-weight watchlist average."
)

if evaluation.get("status") != "OK":
    st.info(
        f"The evaluation was not included in this export ({evaluation.get('error', 'unknown reason')}). "
        "It needs Yahoo Finance prices and runs when the snapshot is published.",
        title="Evaluation unavailable",
    )
    st.stop()

rules = evaluation["rules"]

VERDICT_TEXT = {
    "DATA_TIDAK_CUKUP": ("Not enough data yet", "gray"),
    "PASS": ("Pass", "green"),
    "FAIL": ("Fail", "red"),
}


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:+.2f}%"


def _sample(title: str, summary: dict, *, official: bool) -> None:
    with st.container(border=True):
        st.subheader(title, anchor=False)
        label, color = VERDICT_TEXT.get(summary["verdict"], (summary["verdict"], "gray"))
        if official:
            st.badge(f"Verdict: {label}", color=color)
        buy = summary["by_recommendation"]["BUY"]
        with st.container(horizontal=True):
            st.metric(
                "Completed BUY signals",
                f"{buy['completed']} / {rules['min_buy_signals']}",
                border=True,
                help="A verdict needs this many BUY signals whose exit date has passed.",
            )
            st.metric("Mean excess return", _pct(buy.get("mean_excess")), border=True)
            st.metric("Hit rate", "—" if "hit_rate" not in buy else f"{buy['hit_rate']:.0%}", border=True)
            st.metric("Pending", buy["pending"], border=True)

        rows = [
            {
                "Recommendation": rec,
                "Completed": stats["completed"],
                "Pending": stats["pending"],
                "Mean return": _pct(stats.get("mean_return")),
                "Mean excess": _pct(stats.get("mean_excess")),
                "Hit rate": "—" if "hit_rate" not in stats else f"{stats['hit_rate']:.0%}",
            }
            for rec, stats in summary["by_recommendation"].items()
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, alt=f"{title}: statistics per recommendation")


_sample(f"Official (signals from {rules['registered_on']})", evaluation["official"], official=True)
_sample("Exploratory (earlier scans, not part of the verdict)", evaluation["exploratory"], official=False)

signals = pd.DataFrame(evaluation.get("signals", []))
completed = signals[signals["status"] == "complete"] if not signals.empty else signals
with st.container(border=True):
    st.subheader("Excess return per completed signal", anchor=False)
    if completed.empty:
        st.info("No completed signals yet. A signal completes six trading days after its scan.")
    else:
        chart = completed.assign(
            scan_date=pd.to_datetime(completed["scan_date"]),
            excess_pct=completed["excess_return"] * 100,
        )
        st.scatter_chart(
            chart,
            x="scan_date",
            y="excess_pct",
            color="recommendation",
            x_label="Scan date",
            y_label="Excess return vs. watchlist (%)",
            alt="Excess return of each completed signal by scan date, coloured by recommendation",
        )

st.caption(
    "Limitations: hand-picked large-cap watchlist, no fees or slippage, and signals on the same day "
    "move together. A pass means 'worth a longer look', not a proven edge. Full rules: "
    "Docs/SIGNAL_EVALUATION.md."
)
