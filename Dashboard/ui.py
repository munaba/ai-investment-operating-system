"""Shared presentation pieces: one color per recommendation everywhere,
badge columns for tables, and Altair charts that use those colors.

Recommendation colors were checked with the dataviz palette validator on the
dark theme surface (#0F172A): lightness band, chroma, colour-blind and
normal-vision separation for every pair, and 3:1 contrast all pass. NONE
(no signal / insufficient data) is a neutral gray on purpose.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

REPO_URL = "https://github.com/munaba/ai-investment-operating-system"

RECOMMENDATIONS = ["BUY", "WAIT", "SELL", "NONE"]
REC_COLORS = {"BUY": "#3987e5", "WAIT": "#c98500", "SELL": "#d55181", "NONE": "#64748b"}
_SCALE = alt.Scale(domain=RECOMMENDATIONS, range=[REC_COLORS[r] for r in RECOMMENDATIONS])


def with_rec(frame: pd.DataFrame, column: str = "recommendation") -> pd.DataFrame:
    """Missing recommendations become the explicit label NONE."""
    return frame.assign(**{column: frame[column].fillna("NONE")})


def rec_badge_column(label: str = "Signal"):
    """Column config that renders a one-item list as a colored badge."""
    return st.column_config.MultiselectColumn(
        label, options=RECOMMENDATIONS, color=[REC_COLORS[r] for r in RECOMMENDATIONS], width="small"
    )


def as_badges(frame: pd.DataFrame, column: str = "recommendation") -> pd.DataFrame:
    """Wrap each value in a list so MultiselectColumn draws it as a badge."""
    return frame.assign(**{column: frame[column].fillna("NONE").map(lambda v: [v])})


def rec_legend_color(field: str = "recommendation") -> alt.Color:
    # Legend below the plot so narrow containers keep their width for data.
    return alt.Color(
        f"{field}:N", title=None, scale=_SCALE, sort=RECOMMENDATIONS,
        legend=alt.Legend(orient="bottom", direction="horizontal"),
    )


def recommendations_per_scan_chart(per_scan: pd.DataFrame, order: list[str]) -> alt.Chart:
    """Stacked bars: one bar per scan (in time order), one segment per recommendation."""
    return (
        alt.Chart(per_scan)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(  # ty: ignore[missing-attribute] -- Altair's decorated mark_* methods
            x=alt.X("scan:N", sort=order, title=None, axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("count:Q", title="Symbols"),
            color=rec_legend_color(),
            order=alt.Order("rec_rank:Q"),
            tooltip=[alt.Tooltip("scan:N", title="Scan"), "recommendation:N", alt.Tooltip("count:Q", title="Symbols")],
        )
        .transform_calculate(rec_rank=f"indexof({RECOMMENDATIONS!r}, datum.recommendation)")
        .properties(height=280)
    )


def excess_return_chart(points: pd.DataFrame) -> alt.LayerChart:
    """Excess return per completed signal, with the zero line that separates
    'beat the watchlist' from 'lagged it'."""
    dots = (
        alt.Chart(points)
        .mark_circle(size=70, opacity=0.85, stroke="#0F172A", strokeWidth=1)
        .encode(  # ty: ignore[missing-attribute]
            x=alt.X("scan_date:T", title="Scan date"),
            y=alt.Y("excess_pct:Q", title="Excess return vs. watchlist (%)"),
            color=rec_legend_color(),
            tooltip=[
                alt.Tooltip("symbol:N", title="Symbol"),
                "recommendation:N",
                alt.Tooltip("scan_date:T", title="Scan date", format="%d %b %Y"),
                alt.Tooltip("excess_pct:Q", title="Excess (%)", format="+.2f"),
                alt.Tooltip("forward_pct:Q", title="Return (%)", format="+.2f"),
            ],
        )
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(strokeDash=[4, 4], opacity=0.6).encode(y="y:Q")  # ty: ignore[missing-attribute]
    return (zero + dots).properties(height=320)


def page_footer() -> None:
    st.caption(
        f"Read-only view of AIOS, a personal research project. Not financial advice. "
        f"Source code: [{REPO_URL.removeprefix('https://')}]({REPO_URL})"
    )
