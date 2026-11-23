"""Headless smoke test: every dashboard page renders without an exception.

Run with the dashboard environment (needs streamlit):

    python -m pytest Dashboard/test_dashboard.py -q
"""
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


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page: str) -> None:
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    at.switch_page(page)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title, "page title missing"
