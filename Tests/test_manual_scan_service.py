"""Standalone regression checks for
``Business.manual_scan_service.ManualScanService``.

Covers Sprint 5 STEP 6 (pure orchestrator, LOCKED DECISION):

* constructor accepts exactly five collaborators, stored by
  identity, and nothing else;
* an empty watchlist (``WatchlistScanner.scan()`` returns ``{}``)
  produces an empty ``Report`` and never calls
  ``SnapshotRepository.create()``;
* a single-symbol scan produces one ``Recommendation`` and exactly
  one ``SnapshotRepository.create()`` call, with fields copied
  through unchanged;
* a multi-symbol scan produces one ``SnapshotRepository.create()``
  call per ``Recommendation`` -- never batched, never skipped;
* ``run_scan()`` returns the exact ``Report`` object
  ``ReportService.build_report()`` produced -- identity check, never
  rebuilt or wrapped;
* ``generated_at`` is threaded through unchanged into both the
  returned ``Report`` and every persisted snapshot's ``scan_time``
  -- this service never generates its own timestamp;
* the five pipeline stages run in exactly the LOCKED order:
  ``scan()`` -> ``rank()`` -> ``build_recommendations()`` ->
  ``build_report()`` -> ``create()`` (once per recommendation).

No real ``WatchlistRepository``/``MarketAnalysisAgent``/database is
constructed here -- ``WatchlistScanner``/``SnapshotRepository`` are
faked (this module is duck-typed like the rest of the codebase; the
real ``RankingEngine``/``RecommendationService``/``ReportService`` are
used unmodified so this suite also proves the real pipeline shape
lines up end-to-end).

Run directly with ``python Tests/test_manual_scan_service.py`` -- no
external test framework required, matching
``test_paper_trading_engine.py``/``test_ranking_engine.py``.
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
from Business.report_service import Report, ReportService  # noqa: E402
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
# Fakes / spies
# ---------------------------------------------------------------------------


def _make_scan_entry(symbol: str, recommendation: str, confidence: str, priority: int, rank: int) -> Dict[str, SkillResult]:
    """Build one symbol's ``scan_result`` entry, in the exact shape
    ``RankingEngine.rank()`` reads (mirrors ``Tests/test_ranking_engine.py``).
    """
    watchlist_result = SkillResult(
        success=True,
        output={
            "watchlist": [
                {
                    "priority": priority,
                    "symbol": symbol,
                    "recommendation": recommendation,
                    "confidence": confidence,
                    "summary": "",
                }
            ]
        },
    )
    portfolio_result = SkillResult(
        success=True,
        output={
            "ranking": [
                {
                    "rank": rank,
                    "symbol": symbol,
                    "recommendation": recommendation,
                    "confidence": confidence,
                }
            ]
        },
    )
    return {"watchlist": watchlist_result, "portfolio": portfolio_result}


class FakeWatchlistScanner:
    """Stands in for ``Orchestration.watchlist_scanner.WatchlistScanner``.

    Returns a caller-supplied ``scan_result`` and records each call
    (with its position) into a shared ``order_log``.
    """

    def __init__(self, scan_result: Dict[str, Any], order_log: List[str]) -> None:
        self._scan_result = scan_result
        self._order_log = order_log
        self.call_count = 0

    def scan(self) -> Dict[str, Any]:
        self.call_count += 1
        self._order_log.append("scan")
        return self._scan_result


class SpyRankingEngine(RankingEngine):
    """Real ``RankingEngine`` behavior, plus call-order recording."""

    def __init__(self, order_log: List[str]) -> None:
        super().__init__()  # Activation 2.6: base class now owns self._weights
        self._order_log = order_log

    def rank(self, scan_result):  # type: ignore[override]
        self._order_log.append("rank")
        return super().rank(scan_result)


class SpyRecommendationService(RecommendationService):
    """Real ``RecommendationService`` behavior, plus call-order recording."""

    def __init__(self, order_log: List[str]) -> None:
        self._order_log = order_log

    def build_recommendations(self, ranked_symbols):  # type: ignore[override]
        self._order_log.append("build_recommendations")
        return super().build_recommendations(ranked_symbols)


class SpyReportService(ReportService):
    """Real ``ReportService`` behavior, plus call-order recording and a
    captured reference to the exact ``Report`` it returns (so the test
    can assert ``run_scan()``'s return value is that same object).
    """

    def __init__(self, order_log: List[str]) -> None:
        self._order_log = order_log
        self.last_report: Report | None = None

    def build_report(self, recommendations, generated_at):  # type: ignore[override]
        self._order_log.append("build_report")
        report = super().build_report(recommendations, generated_at)
        self.last_report = report
        return report


class FakeSnapshotRepository:
    """Stands in for
    ``Repository.persistence.snapshot_repository.SnapshotRepository``.

    Records every ``create(...)`` call's kwargs, in order, and appends
    to the shared ``order_log`` per call so relative ordering against
    the other four stages can be asserted.
    """

    def __init__(self, order_log: List[str]) -> None:
        self._order_log = order_log
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
        self._order_log.append("create")
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


def _build_service(scan_result: Dict[str, Any]):
    order_log: List[str] = []
    watchlist_scanner = FakeWatchlistScanner(scan_result, order_log)
    ranking_engine = SpyRankingEngine(order_log)
    recommendation_service = SpyRecommendationService(order_log)
    report_service = SpyReportService(order_log)
    snapshot_repository = FakeSnapshotRepository(order_log)

    service = ManualScanService(
        watchlist_scanner,
        ranking_engine,
        recommendation_service,
        report_service,
        snapshot_repository,
    )
    return service, watchlist_scanner, ranking_engine, recommendation_service, report_service, snapshot_repository, order_log


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def scenario_constructor_dependency_exactly_five():
    print("\n[Scenario 1] constructor stores exactly five collaborators")
    service, watchlist_scanner, ranking_engine, recommendation_service, report_service, snapshot_repository, _ = (
        _build_service({})
    )
    attrs = sorted(vars(service).keys())
    check(
        attrs
        == [
            "_ranking_engine",
            "_recommendation_service",
            "_report_service",
            "_snapshot_repository",
            "_watchlist_scanner",
        ],
        "ManualScanService holds exactly five collaborator attributes",
    )
    check(service._watchlist_scanner is watchlist_scanner, "_watchlist_scanner stored by identity")
    check(service._ranking_engine is ranking_engine, "_ranking_engine stored by identity")
    check(service._recommendation_service is recommendation_service, "_recommendation_service stored by identity")
    check(service._report_service is report_service, "_report_service stored by identity")
    check(service._snapshot_repository is snapshot_repository, "_snapshot_repository stored by identity")


def scenario_empty_watchlist():
    print("\n[Scenario 2] empty watchlist produces an empty Report and no snapshot writes")
    service, _, _, _, _, snapshot_repository, _ = _build_service({})

    report = service.run_scan("2026-08-01T00:00:00+00:00")

    check(isinstance(report, Report), "run_scan() returns a Report instance")
    check(report.recommendations == [], "empty scan_result -> empty recommendations list")
    check(report.total_symbols == 0, "empty scan_result -> total_symbols == 0")
    check(len(snapshot_repository.calls) == 0, "SnapshotRepository.create() is never called for an empty watchlist")


def scenario_single_recommendation():
    print("\n[Scenario 3] single-symbol scan produces one Recommendation and one snapshot write")
    scan_result = {"BBCA": _make_scan_entry("BBCA", "BUY", "HIGH", 1, 1)}
    service, _, _, _, _, snapshot_repository, _ = _build_service(scan_result)

    report = service.run_scan("2026-08-01T09:00:00+00:00")

    check(report.total_symbols == 1, "one symbol in scan_result -> total_symbols == 1")
    check(len(report.recommendations) == 1, "one Recommendation produced")
    check(report.recommendations[0].symbol == "BBCA", "the one Recommendation carries the right symbol")
    check(len(snapshot_repository.calls) == 1, "SnapshotRepository.create() called exactly once")
    call = snapshot_repository.calls[0]
    check(
        {k: call[k] for k in ("scan_time", "symbol", "recommendation", "confidence", "priority", "rank")}
        == {
            "scan_time": "2026-08-01T09:00:00+00:00",
            "symbol": "BBCA",
            "recommendation": "BUY",
            "confidence": "HIGH",
            "priority": 1,
            "rank": 1,
        },
        "the snapshot call carries the recommendation's fields and this call's generated_at verbatim",
    )
    check(call["status"] == "success", "a successful recommendation persists with status='success'")
    check(call["score"] is not None, "a successful row carries the RankedSymbol's score (Activation 2.7)")
    check(call["score_breakdown_json"] is not None, "a successful row carries a serialized score breakdown")
    check(call["error_message"] is None, "a successful row has no error_message")


def scenario_multiple_recommendations():
    print("\n[Scenario 4] multi-symbol scan produces one snapshot write per Recommendation")
    scan_result = {
        "BBCA": _make_scan_entry("BBCA", "BUY", "HIGH", 1, 1),
        "TLKM": _make_scan_entry("TLKM", "SELL", "LOW", 2, 2),
        "ASII": _make_scan_entry("ASII", "WAIT", "MEDIUM", 3, 3),
    }
    service, _, _, _, _, snapshot_repository, _ = _build_service(scan_result)

    report = service.run_scan("2026-08-01T10:00:00+00:00")

    check(report.total_symbols == 3, "three symbols in scan_result -> total_symbols == 3")
    check(len(report.recommendations) == 3, "three Recommendations produced")
    check(len(snapshot_repository.calls) == 3, "SnapshotRepository.create() called exactly three times (never batched)")
    called_symbols = [call["symbol"] for call in snapshot_repository.calls]
    # Activation 2.5 LOCKED DECISION supersedes the old "no re-sort"
    # assumption: RankingEngine now sorts by score (BUY/HIGH=33 >
    # WAIT/MEDIUM=22 > SELL/LOW=11), so snapshot calls follow that
    # order, not scan_result's original insertion order.
    check(
        called_symbols == ["BBCA", "ASII", "TLKM"],
        "snapshot calls happen in RankingEngine's score-sorted order (BUY > WAIT > SELL), per Activation 2.5",
    )
    check(
        all(call["scan_time"] == "2026-08-01T10:00:00+00:00" for call in snapshot_repository.calls),
        "every snapshot call carries this run's generated_at, unchanged",
    )


def scenario_report_returned_is_the_exact_object():
    print("\n[Scenario 5] run_scan() returns the exact Report ReportService.build_report() produced")
    scan_result = {"BBCA": _make_scan_entry("BBCA", "BUY", "HIGH", 1, 1)}
    service, _, _, _, report_service, _, _ = _build_service(scan_result)

    report = service.run_scan("2026-08-01T11:00:00+00:00")

    check(
        report is report_service.last_report,
        "run_scan()'s return value is identity-equal to ReportService.build_report()'s return "
        "(never rebuilt, re-copied, or wrapped)",
    )


def scenario_generated_at_passed_through_verbatim():
    print("\n[Scenario 6] generated_at is threaded through unchanged, never generated internally")
    scan_result = {"BBCA": _make_scan_entry("BBCA", "BUY", "HIGH", 1, 1)}
    service, _, _, _, _, snapshot_repository, _ = _build_service(scan_result)

    custom_timestamp = "not-a-real-timestamp-format-42"
    report = service.run_scan(custom_timestamp)

    check(report.generated_at == custom_timestamp, "Report.generated_at is exactly the caller-supplied value")
    check(
        all(call["scan_time"] == custom_timestamp for call in snapshot_repository.calls),
        "every snapshot's scan_time is exactly the caller-supplied value",
    )


def scenario_pipeline_order_is_correct():
    print("\n[Scenario 7] the five pipeline stages run in exactly the LOCKED order")
    scan_result = {
        "BBCA": _make_scan_entry("BBCA", "BUY", "HIGH", 1, 1),
        "TLKM": _make_scan_entry("TLKM", "SELL", "LOW", 2, 2),
    }
    service, _, _, _, _, _, order_log = _build_service(scan_result)

    service.run_scan("2026-08-01T12:00:00+00:00")

    check(
        order_log
        == [
            "scan",
            "rank",
            "build_recommendations",
            "build_report",
            "create",
            "create",
        ],
        "call order is scan() -> rank() -> build_recommendations() -> build_report() -> "
        "create() once per recommendation, never reshuffled",
    )


def scenario_partial_ticker_failure_persists_error_row_without_stopping_others():
    print("\n[Scenario 8] a symbol RankingEngine excludes still persists as a status='error' row (Activation 2.7)")
    scan_result = {
        "BBCA": _make_scan_entry("BBCA", "BUY", "HIGH", 1, 1),
        # A ticker whose 'watchlist' SkillResult is entirely missing --
        # the same shape RankingEngine._extract_valid_entries already
        # silently excludes today; Activation 2.7 makes it visible.
        "FAILX": {"portfolio": SkillResult(success=True, output={"ranking": []})},
        "TLKM": _make_scan_entry("TLKM", "SELL", "LOW", 2, 2),
    }
    service, _, _, _, _, snapshot_repository, _ = _build_service(scan_result)

    report = service.run_scan("2026-08-01T13:00:00+00:00")

    check(report.total_symbols == 2, "RankingEngine.rank() still excludes FAILX from the Report (unchanged algorithm)")

    calls_by_symbol = {call["symbol"]: call for call in snapshot_repository.calls}
    check(len(snapshot_repository.calls) == 3, "one snapshot row per symbol, including the excluded one")
    check("FAILX" in calls_by_symbol, "the excluded symbol still got a snapshot row")
    check(calls_by_symbol["FAILX"]["status"] == "error", "the excluded symbol's row has status='error'")
    check(
        calls_by_symbol["FAILX"]["error_message"] == "missing 'watchlist' SkillResult",
        "the error row explains why the symbol was excluded",
    )
    check(calls_by_symbol["FAILX"]["recommendation"] is None, "an error row has no recommendation")
    check(calls_by_symbol["BBCA"]["status"] == "success", "other symbols still persist normally")
    check(calls_by_symbol["TLKM"]["status"] == "success", "the ticker after the failing one is not skipped")


def scenario_watchlist_scanner_isolates_per_ticker_exceptions():
    print("\n[Scenario 9] WatchlistScanner isolates one ticker's exception from the rest of the scan")
    from Orchestration.watchlist_scanner import WatchlistScanner

    class ExplodingAgent:
        def __init__(self):
            self.calls = []

        def execute(self, task):
            symbol = task.metadata["symbols"][0]
            self.calls.append(symbol)
            if symbol == "BOOM":
                raise RuntimeError("simulated infrastructure fault")
            return _make_scan_entry(symbol, "BUY", "HIGH", 1, 1)

    class FakeWatchlistRepo:
        def list_all(self):
            return ["BBCA", "BOOM", "TLKM"]

    agent = ExplodingAgent()
    scanner = WatchlistScanner(FakeWatchlistRepo(), agent)
    result = scanner.scan()

    check(agent.calls == ["BBCA", "BOOM", "TLKM"], "every ticker is still attempted, in order, despite BOOM raising")
    check(set(result.keys()) == {"BBCA", "BOOM", "TLKM"}, "scan() still returns an entry for every ticker")
    check(result["BOOM"]["watchlist"].success is False, "the exploding ticker's watchlist result is success=False")
    check("simulated infrastructure fault" in (result["BOOM"]["watchlist"].error or ""), "the exception message is preserved")
    check(result["BBCA"]["watchlist"].success is True, "the ticker before BOOM scanned normally")
    check(result["TLKM"]["watchlist"].success is True, "the ticker after BOOM still scanned normally (scan did not abort)")


def main() -> int:
    scenario_constructor_dependency_exactly_five()
    scenario_empty_watchlist()
    scenario_single_recommendation()
    scenario_multiple_recommendations()
    scenario_report_returned_is_the_exact_object()
    scenario_generated_at_passed_through_verbatim()
    scenario_pipeline_order_is_correct()
    scenario_partial_ticker_failure_persists_error_row_without_stopping_others()
    scenario_watchlist_scanner_isolates_per_ticker_exceptions()

    print("\n" + "=" * 60)
    print(f"SPRINT 5 STEP 6 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())