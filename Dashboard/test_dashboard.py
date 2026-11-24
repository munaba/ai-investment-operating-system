"""Headless smoke test: every dashboard page renders without an exception,
both on the real exported snapshot and on one full of NULLs.

Run with the dashboard environment (needs streamlit):

    python -m pytest Dashboard/test_dashboard.py -q -c NUL
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parent / "streamlit_app.py"
PAGES = [
    "app_pages/overview.py",
    "app_pages/scans.py",
    "app_pages/signals.py",
    "app_pages/briefs.py",
    "app_pages/paper.py",
    "app_pages/system.py",
]


def _run(page: str, monkeypatch, snapshot_path: Path | None = None) -> AppTest:
    if snapshot_path is not None:
        monkeypatch.setenv("AIOS_SNAPSHOT_URL", "")
    at = AppTest.from_file(str(APP), default_timeout=30)
    if snapshot_path is not None:
        import aios_data

        monkeypatch.setattr(aios_data, "SNAPSHOT_PATH", snapshot_path)
        monkeypatch.setattr(aios_data, "SNAPSHOT_URL", "")
        aios_data._load_raw.clear()
    at.run()
    at.switch_page(page)
    at.run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page: str, monkeypatch) -> None:
    at = _run(page, monkeypatch)
    assert not at.exception, [e.value for e in at.exception]
    assert at.title, "page title missing"


@pytest.mark.parametrize("page", PAGES)
def test_page_survives_null_columns(page: str, monkeypatch, tmp_path: Path) -> None:
    """NULLs become NaN floats in pandas; no page may crash on them."""
    snapshot = {
        "exported_at": "2026-11-24T08:00:00+00:00",
        "migrations": {"applied": [1], "expected": [1, 2]},
        "market_holidays": [],
        "signal_evaluation": {"status": "UNAVAILABLE", "error": "offline"},
        "tables": {
            # NULLs mixed with real values: that is when pandas turns them into NaN floats.
            "ranking_snapshots": [
                {"snapshot_id": 1, "scan_time": "2026-11-24T02:00:00+00:00", "symbol": "BBCA", "status": "error",
                 "recommendation": None, "confidence": None, "priority": None, "rank": 1, "score": None,
                 "score_breakdown_json": None, "evidence_summary": None, "error_message": "timeout"},
                {"snapshot_id": 2, "scan_time": "2026-11-24T02:00:00+00:00", "symbol": "BBRI", "status": "success",
                 "recommendation": "BUY", "confidence": "HIGH", "priority": 1, "rank": 2, "score": 80,
                 "score_breakdown_json": "{\"recommendation_contribution\": 30}", "evidence_summary": "ok",
                 "error_message": None},
            ],
            "scheduler_job_runs": [
                {"job_type": "session_scan", "trading_date": "2026-11-24", "status": "RUNNING", "attempt": 1,
                 "started_at": "2026-11-24T02:00:00+00:00", "finished_at": None, "next_retry_at": None,
                 "detail": None},
                {"job_type": "pre_market_check", "trading_date": "2026-11-24", "status": "SUCCESS", "attempt": 1,
                 "started_at": "2026-11-24T01:50:00+00:00", "finished_at": "2026-11-24T01:50:00+00:00",
                 "next_retry_at": None, "detail": "{\"session\": \"pre_market\"}"},
            ],
            "decision_briefs": [], "watchlist": [], "accounts": [], "positions": [], "orders": [],
            "trades": [], "portfolio_snapshots": [], "daily_performance": [], "journal_entries": [],
            "risk_limits": [], "operator_observation_windows": [], "final_review_records": [],
        },
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    at = _run(page, monkeypatch, path)
    assert not at.exception, [e.value for e in at.exception]
