"""Load the exported AIOS snapshot (data/snapshot.json) into pandas frames.

The dashboard never touches the live database; it only reads the JSON file
written by export_snapshot.py. All timestamps are converted to WIB.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

SNAPSHOT_PATH = Path(__file__).resolve().parent / "data" / "snapshot.json"
WIB = "Asia/Jakarta"

_TIME_COLUMNS = {
    "ranking_snapshots": ["scan_time"],
    "decision_briefs": ["generated_at"],
    "scheduler_job_runs": ["started_at", "finished_at", "next_retry_at"],
    "positions": ["created_at", "updated_at"],
    "orders": ["created_at", "updated_at", "filled_at"],
    "trades": ["executed_at"],
    "portfolio_snapshots": ["timestamp"],
    "daily_performance": ["start_timestamp", "end_timestamp", "timestamp"],
    "journal_entries": ["decided_at", "closed_at", "created_at"],
    "operator_observation_windows": ["created_at", "closed_at"],
    "final_review_records": ["reviewed_at", "decided_at"],
}


@dataclass(frozen=True)
class Snapshot:
    exported_at: pd.Timestamp
    applied_migrations: list[int]
    expected_migrations: list[int]
    tables: dict[str, pd.DataFrame]

    def table(self, name: str) -> pd.DataFrame:
        return self.tables.get(name, pd.DataFrame())


def _to_wib(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce", format="ISO8601").dt.tz_convert(WIB)


@st.cache_data(ttl="10m")
def load_snapshot(path: str = str(SNAPSHOT_PATH)) -> Snapshot | None:
    file = Path(path)
    if not file.is_file():
        return None
    raw = json.loads(file.read_text(encoding="utf-8"))

    tables: dict[str, pd.DataFrame] = {}
    for name, rows in raw.get("tables", {}).items():
        frame = pd.DataFrame(rows)
        for column in _TIME_COLUMNS.get(name, []):
            if column in frame:
                frame[column] = _to_wib(frame[column])
        tables[name] = frame

    migrations = raw.get("migrations", {})
    return Snapshot(
        exported_at=pd.Timestamp(raw["exported_at"]).tz_convert(WIB),
        applied_migrations=list(migrations.get("applied", [])),
        expected_migrations=list(migrations.get("expected", [])),
        tables=tables,
    )


def require_snapshot() -> Snapshot:
    """Return the snapshot or stop the page with an explanation."""
    snapshot = load_snapshot()
    if snapshot is None:
        st.warning(
            "Run `python Dashboard/export_snapshot.py` from the repository root to create "
            "`Dashboard/data/snapshot.json`.",
            title="No data exported yet",
        )
        st.stop()
    return snapshot


def latest_scan(snapshot: Snapshot) -> pd.DataFrame:
    scans = snapshot.table("ranking_snapshots")
    if scans.empty:
        return scans
    return scans[scans["scan_time"] == scans["scan_time"].max()].sort_values("rank")


def format_time(value: pd.Timestamp | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    return value.strftime("%d %b %Y, %H:%M WIB")
