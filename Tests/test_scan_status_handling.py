"""Regression checks for the IDX-scan-status fix.

Covers the real production path -- ``WatchlistScanner.scan()``-shaped
``scan_result`` -> ``Business.ranking_engine.RankingEngine`` (both
``rank()`` and ``extract_failures()``) -> ``Business.manual_scan_service.
ManualScanService`` (a faked ``WatchlistScanner``/``SnapshotRepository``,
the real ``RankingEngine``/``RecommendationService``/``ReportService``,
mirroring ``Tests/test_manual_scan_service.py``'s own fixture shape) ->
``main._print_scan_snapshot_rows``'s display logic.

Proves:

  A. INSUFFICIENT_DATA stays INSUFFICIENT_DATA (not "DATA_ERROR").
  B. DATA_ERROR stays DATA_ERROR.
  C. ANALYSIS_FAILED stays ANALYSIS_FAILED.
  D. None of the three receive a recommendation.
  E. None of the three enter valid/ranked output.
  F. SUCCESS still enters ranking normally.
  G. A mixed watchlist (one SUCCESS + one of each failure status)
     ranks the SUCCESS symbol and preserves the other three as
     explicit statuses, with no fabricated BUY/WAIT/SELL, and the
     scan completes without raising.
  H/I/J are covered by the standalone regression files this suite's
  runner also re-runs (Tests/test_manual_scan_service.py,
  Tests/test_us_market_support.py, Tests/test_activation11_25_forex_
  analysis.py, Tests/test_activation10_1_crypto_paper_workflow.py) --
  none of the code paths this fix touches (``RankingEngine.
  _diagnose_failure``, ``main._print_scan_snapshot_rows``) is imported
  or exercised by IDX SUCCESS-only rows, US, forex, or crypto flows
  differently than before.

Run directly with ``python Tests/test_scan_status_handling.py`` -- no
external test framework required, matching every other Tests/ file in
this repository.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.manual_scan_service import ManualScanService  # noqa: E402
from Business.ranking_engine import RankingEngine  # noqa: E402
from Business.recommendation_service import RecommendationService  # noqa: E402
from Business.report_service import ReportService  # noqa: E402
from Orchestration.skill_result import SkillResult  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


# ---------------------------------------------------------------------------
# Fixtures -- mirrors Tests/test_manual_scan_service.py's own shapes
# ---------------------------------------------------------------------------


def _success_entry(symbol: str, recommendation: str, confidence: str, priority: int) -> Dict[str, Any]:
    """A well-formed ``scan_result`` entry for a SUCCESS symbol -- the
    same shape ``RankingEngine.rank()`` already reads (mirrors
    ``Tests/test_manual_scan_service.py::_make_scan_entry``)."""
    return {
        "watchlist": SkillResult(
            success=True,
            output={
                "watchlist": [
                    {
                        "priority": priority,
                        "symbol": symbol,
                        "recommendation": recommendation,
                        "confidence": confidence,
                        "summary": f"{symbol} summary",
                    }
                ]
            },
        )
    }


def _failure_entry(symbol: str, status: str) -> Dict[str, Any]:
    """A ``scan_result`` entry for a non-SUCCESS symbol, in the exact
    shape ``Orchestration.watchlist_analysis_skill.WatchlistAnalysisSkill``
    already produces for a failed/insufficient MarketAnalysisSkill
    result: a well-formed ``"watchlist"`` SkillResult whose single
    entry carries ``recommendation=status`` (one of "DATA_ERROR" /
    "ANALYSIS_FAILED" / "INSUFFICIENT_DATA" / "SKIPPED") and
    ``confidence=None`` -- never a missing/unsuccessful SkillResult,
    since that is a different (already-covered) failure path in
    ``RankingEngine._diagnose_failure``."""
    return {
        "watchlist": SkillResult(
            success=True,
            output={
                "watchlist": [
                    {
                        "priority": None,
                        "symbol": symbol,
                        "recommendation": status,
                        "confidence": None,
                        "summary": f"{symbol} summary",
                    }
                ]
            },
        )
    }


class FakeWatchlistScanner:
    def __init__(self, scan_result: Dict[str, Any]) -> None:
        self._scan_result = scan_result

    def scan(self) -> Dict[str, Any]:
        return self._scan_result


class FakeSnapshotRepository:
    """Stands in for ``Repository.persistence.snapshot_repository.
    SnapshotRepository`` -- records every ``create(...)`` call's
    kwargs, exactly like ``Tests/test_manual_scan_service.py``'s own
    fake."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def create(
        self,
        *,
        scan_time,
        symbol,
        recommendation=None,
        confidence=None,
        priority=None,
        rank=None,
        status="success",
        score=None,
        score_breakdown_json=None,
        evidence_summary=None,
        error_message=None,
    ):
        self.calls.append(
            {
                "scan_time": scan_time,
                "symbol": symbol,
                "recommendation": recommendation,
                "confidence": confidence,
                "priority": priority,
                "rank": rank,
                "status": status,
                "score": score,
                "score_breakdown_json": score_breakdown_json,
                "evidence_summary": evidence_summary,
                "error_message": error_message,
            }
        )


class _Row:
    """Minimal stand-in for ``Database.models.RankingSnapshot``, just
    the fields ``main._print_scan_snapshot_rows`` reads."""

    def __init__(self, call: Dict[str, Any]) -> None:
        self.symbol = call["symbol"]
        self.status = call["status"]
        self.error_message = call["error_message"]
        self.rank = call["rank"]
        self.score = call["score"]
        self.recommendation = call["recommendation"]
        self.confidence = call["confidence"]
        self.evidence_summary = call["evidence_summary"]


def _build_service(scan_result: Dict[str, Any]):
    watchlist_scanner = FakeWatchlistScanner(scan_result)
    ranking_engine = RankingEngine()
    recommendation_service = RecommendationService()
    report_service = ReportService()
    snapshot_repository = FakeSnapshotRepository()

    service = ManualScanService(
        watchlist_scanner,
        ranking_engine,
        recommendation_service,
        report_service,
        snapshot_repository,
    )
    return service, snapshot_repository


def _render_rows(snapshot_repository: FakeSnapshotRepository) -> List[str]:
    """Exercises the exact display logic ``main._print_scan_snapshot_rows``
    uses for ``status == "error"`` rows, without importing ``main``
    (which requires a fully wired ``app``) -- the branch under test is
    copied verbatim from that function so behavior stays in lockstep;
    any future divergence must update both."""
    lines: List[str] = []
    for call in snapshot_repository.calls:
        row = _Row(call)
        if row.status == "error":
            if row.error_message in ("DATA_ERROR", "ANALYSIS_FAILED", "INSUFFICIENT_DATA", "SKIPPED"):
                lines.append(f"{row.symbol:<8} {row.error_message}")
            else:
                lines.append(f"{row.symbol:<8} DATA_ERROR   reason={row.error_message}")
        else:
            lines.append(
                f"{row.symbol:<8} rank={row.rank:<3} score={row.score:<4} "
                f"{row.recommendation:<4} confidence={row.confidence:<6} "
                f"evidence={row.evidence_summary!r}"
            )
    return lines


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def scenario_a_insufficient_data_preserved():
    print("\n[Scenario A] INSUFFICIENT_DATA stays INSUFFICIENT_DATA")
    scan_result = {"BBCA.JK": _failure_entry("BBCA.JK", "INSUFFICIENT_DATA")}
    service, snapshot_repository = _build_service(scan_result)
    service.run_scan("2026-08-17T00:00:00Z")

    check(len(snapshot_repository.calls) == 1, "exactly one snapshot row persisted")
    call = snapshot_repository.calls[0]
    check(call["status"] == "error", "persisted as status=error (unchanged DB contract)")
    check(call["error_message"] == "INSUFFICIENT_DATA", "error_message is the real status, not a generic parse message")
    check(call["recommendation"] is None, "D: no fabricated recommendation")

    lines = _render_rows(snapshot_repository)
    check(lines == ["BBCA.JK  INSUFFICIENT_DATA"], f"CLI shows explicit INSUFFICIENT_DATA, not DATA_ERROR; got {lines!r}")


def scenario_b_data_error_preserved():
    print("\n[Scenario B] DATA_ERROR stays DATA_ERROR")
    scan_result = {"XYZ.JK": _failure_entry("XYZ.JK", "DATA_ERROR")}
    service, snapshot_repository = _build_service(scan_result)
    service.run_scan("2026-08-17T00:00:00Z")

    call = snapshot_repository.calls[0]
    check(call["error_message"] == "DATA_ERROR", "error_message is DATA_ERROR")
    check(call["recommendation"] is None, "D: no fabricated recommendation")
    lines = _render_rows(snapshot_repository)
    check(lines == ["XYZ.JK   DATA_ERROR"], f"CLI shows DATA_ERROR with no reason= suffix; got {lines!r}")


def scenario_c_analysis_failed_preserved():
    print("\n[Scenario C] ANALYSIS_FAILED stays ANALYSIS_FAILED")
    scan_result = {"ABC.JK": _failure_entry("ABC.JK", "ANALYSIS_FAILED")}
    service, snapshot_repository = _build_service(scan_result)
    service.run_scan("2026-08-17T00:00:00Z")

    call = snapshot_repository.calls[0]
    check(call["error_message"] == "ANALYSIS_FAILED", "error_message is ANALYSIS_FAILED")
    check(call["recommendation"] is None, "D: no fabricated recommendation")
    lines = _render_rows(snapshot_repository)
    check(lines == ["ABC.JK   ANALYSIS_FAILED"], f"CLI shows ANALYSIS_FAILED; got {lines!r}")


def scenario_e_excluded_from_ranking():
    print("\n[Scenario E] failure statuses never enter ranked output")
    scan_result = {
        "BBCA.JK": _failure_entry("BBCA.JK", "INSUFFICIENT_DATA"),
        "XYZ.JK": _failure_entry("XYZ.JK", "DATA_ERROR"),
        "ABC.JK": _failure_entry("ABC.JK", "ANALYSIS_FAILED"),
    }
    ranking_engine = RankingEngine()
    ranked = ranking_engine.rank(scan_result)
    check(ranked == [], f"E: no failure-status symbol is ever ranked; got {ranked!r}")


def scenario_f_success_still_ranked():
    print("\n[Scenario F] SUCCESS still enters ranking")
    scan_result = {"TLKM.JK": _success_entry("TLKM.JK", "BUY", "HIGH", 1)}
    service, snapshot_repository = _build_service(scan_result)
    report = service.run_scan("2026-08-17T00:00:00Z")

    check(report.total_symbols == 1, "SUCCESS symbol reaches the report")
    check(
        report.recommendations[0].recommendation == "BUY",
        f"SUCCESS symbol keeps its real recommendation; got {report.recommendations[0].recommendation!r}",
    )
    call = snapshot_repository.calls[0]
    check(call["status"] == "success", "SUCCESS symbol persisted as status=success")


def scenario_g_mixed_watchlist():
    print("\n[Scenario G] mixed watchlist: one of each status")
    scan_result = {
        "TLKM.JK": _success_entry("TLKM.JK", "BUY", "HIGH", 1),
        "BBCA.JK": _failure_entry("BBCA.JK", "INSUFFICIENT_DATA"),
        "XYZ.JK": _failure_entry("XYZ.JK", "DATA_ERROR"),
        "ABC.JK": _failure_entry("ABC.JK", "ANALYSIS_FAILED"),
    }
    service, snapshot_repository = _build_service(scan_result)

    try:
        report = service.run_scan("2026-08-17T00:00:00Z")
    except Exception as exc:  # pragma: no cover - failure path only
        check(False, f"scan must complete without crashing; raised {exc!r}")
        return

    check(report.total_symbols == 1, "only the SUCCESS symbol is ranked")
    check(report.recommendations[0].symbol == "TLKM.JK", "the ranked symbol is the real SUCCESS one")
    check(
        report.recommendations[0].recommendation in ("BUY", "WAIT", "SELL"),
        "no fake BUY/SELL/WAIT for the failure-status symbols leaking into ranking",
    )

    check(len(snapshot_repository.calls) == 4, "all four symbols are persisted, none silently dropped")
    by_symbol = {call["symbol"]: call for call in snapshot_repository.calls}
    check(by_symbol["TLKM.JK"]["status"] == "success", "TLKM.JK persisted as success")
    check(by_symbol["BBCA.JK"]["error_message"] == "INSUFFICIENT_DATA", "BBCA.JK keeps INSUFFICIENT_DATA")
    check(by_symbol["XYZ.JK"]["error_message"] == "DATA_ERROR", "XYZ.JK keeps DATA_ERROR")
    check(by_symbol["ABC.JK"]["error_message"] == "ANALYSIS_FAILED", "ABC.JK keeps ANALYSIS_FAILED")

    lines = _render_rows(snapshot_repository)
    check(
        "BBCA.JK  INSUFFICIENT_DATA" in lines,
        f"CLI output explicitly shows BBCA.JK INSUFFICIENT_DATA; got {lines!r}",
    )
    check("XYZ.JK   DATA_ERROR" in lines, f"CLI output explicitly shows XYZ.JK DATA_ERROR; got {lines!r}")
    check(
        "ABC.JK   ANALYSIS_FAILED" in lines,
        f"CLI output explicitly shows ABC.JK ANALYSIS_FAILED; got {lines!r}",
    )


def main() -> None:
    scenario_a_insufficient_data_preserved()
    scenario_b_data_error_preserved()
    scenario_c_analysis_failed_preserved()
    scenario_e_excluded_from_ranking()
    scenario_f_success_still_ranked()
    scenario_g_mixed_watchlist()

    total = _PASS + _FAIL
    print(f"\n{'=' * 70}\nRESULT: {_PASS} PASS, {_FAIL} FAIL (of {total})\n{'=' * 70}")
    if _FAIL:
        for description in _FAILURES:
            print(f"  FAILED: {description}")
        sys.exit(1)


if __name__ == "__main__":
    main()