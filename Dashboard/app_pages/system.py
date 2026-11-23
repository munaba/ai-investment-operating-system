import json

import streamlit as st

from aios_data import format_time, require_snapshot

snapshot = require_snapshot()
jobs = snapshot.table("scheduler_job_runs")
windows = snapshot.table("operator_observation_windows")
reviews = snapshot.table("final_review_records")

applied = set(snapshot.applied_migrations)
expected = set(snapshot.expected_migrations)
pending = sorted(expected - applied)

with st.container(horizontal=True):
    st.metric("Migrations applied", len(applied), border=True)
    st.metric("Migrations pending", len(pending), border=True)
    st.metric("Scheduler runs", len(jobs), border=True)
    failed = int((jobs["status"] == "FAILED").sum()) if not jobs.empty else 0
    st.metric("Failed runs", failed, border=True)
    running = int((jobs["status"] == "RUNNING").sum()) if not jobs.empty else 0
    if running:
        st.metric("Running", running, border=True, help="Started but not finished (or interrupted).")

if pending:
    st.warning(
        f"Schema versions {', '.join(map(str, pending))} are declared in the code but not yet "
        "applied to this database. Run `python main.py init` on the operator machine.",
        title="Pending migrations",
    )

with st.container(border=True):
    st.subheader("Scheduler job runs", anchor=False)
    st.caption(
        "The IDX scheduler runs on trading days: a pre-market check, session scans while the "
        "market is open, a data-health check every tick, and four closing jobs after 15:49 WIB."
    )
    if jobs.empty:
        st.info("The scheduler has not run yet.")
    else:
        def _summary(detail: str | None) -> str:
            try:
                data = json.loads(detail or "{}")
            except ValueError:
                return detail or ""
            keys = ("status", "total_symbols", "title", "snapshot_count")
            return ", ".join(f"{k}={data[k]}" for k in keys if k in data)

        st.dataframe(
            jobs.sort_values("started_at", ascending=False).assign(
                started_at=lambda f: f["started_at"].map(format_time),
                detail=lambda f: f["detail"].map(_summary),
            )[["trading_date", "job_type", "status", "attempt", "started_at", "detail"]],
            hide_index=True,
            column_config={
                "trading_date": "Trading date",
                "job_type": "Job",
                "status": "Status",
                "attempt": st.column_config.NumberColumn("Attempt", width="small"),
                "started_at": "Started",
                "detail": st.column_config.TextColumn("Detail", width="large"),
            },
            alt="All scheduler job runs, newest first",
        )

left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.subheader("Observation window", anchor=False)
        if windows.empty:
            st.info("No observation window recorded.")
        else:
            st.dataframe(
                windows[["window_id", "start_at", "end_at", "status"]],
                hide_index=True,
                alt="Operator observation windows",
            )
with right:
    with st.container(border=True):
        st.subheader("Final review", anchor=False)
        if reviews.empty:
            st.info("No final review recorded.")
        else:
            st.dataframe(
                reviews.assign(decided_at=reviews["decided_at"].map(format_time))[
                    ["review_id", "evidence_status", "human_decision", "decided_at"]
                ],
                hide_index=True,
                alt="Final review decisions",
            )
