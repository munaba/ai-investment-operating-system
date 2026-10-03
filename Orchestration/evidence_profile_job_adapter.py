"""Thin wrapper for evidence profile analysis job.

This module provides a thin adapter layer between ``IDXDailyScheduler``
and ``DecisionCopilotSkill.analyze_evidence_profile()``. It handles
timezone conversion for daily windows, timing, and the special case
where ``INSUFFICIENT_DATA`` is treated as SUCCESS (not failure) so the
job does not retry unnecessarily on non-trading days or days with no
scan data.

The adapter is constructed once in ``composition_root.py`` and passed
to ``IDXDailyScheduler.__init__``. It never imports or modifies
``decision_copilot.py``.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from time import perf_counter
from typing import Any, Dict

from zoneinfo import ZoneInfo

from Business.idx_market_calendar import IDX_MARKET_TIMEZONE_NAME


_PROFILE_KEYS = (
    "status_counts",
    "recommendation_counts",
    "confidence_counts",
    "factor_contribution_totals",
    "error_row_count",
    "unparsed_breakdown_count",
)


class EvidenceProfileJobAdapter:
    """Thin wrapper. Skill dibangun sekali di composition_root.
    Tidak memodifikasi decision_copilot.py."""

    def __init__(self, skill) -> None:
        self._skill = skill
        self._tz = ZoneInfo(IDX_MARKET_TIMEZONE_NAME)

    def window_for(self, trading_date: str):
        day = date.fromisoformat(trading_date)
        start = datetime.combine(day, time.min, tzinfo=self._tz).astimezone(timezone.utc)
        next_start = datetime.combine(day + timedelta(days=1), time.min, tzinfo=self._tz).astimezone(timezone.utc)
        return start, next_start - timedelta(microseconds=1)

    def analyze_for_trading_date(self, trading_date: str) -> Dict[str, Any]:
        since, until = self.window_for(trading_date)
        t0 = perf_counter()
        result = self._skill.analyze_evidence_profile(since.isoformat(), until.isoformat())
        elapsed_ms = int((perf_counter() - t0) * 1000)

        if not result.success:
            if result.error == "INSUFFICIENT_DATA":
                return {"status": "no_data", "snapshot_count": 0, "elapsed_ms": elapsed_ms}
            raise ValueError(f"Evidence analysis failed: {result.error}")

        out = result.output
        return {
            "status": "ok",
            "elapsed_ms": elapsed_ms,
            "snapshot_count": out["snapshot_count"],
            "scan_count": out["scan_count"],
            "symbol_count": out["symbol_count"],
            "profile": {k: out[k] for k in _PROFILE_KEYS},
        }
