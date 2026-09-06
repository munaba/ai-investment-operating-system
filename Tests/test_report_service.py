"""
Sprint 5 STEP 5 proof suite -- ReportService.

Scope (per Sprint 5 STEP 5 LOCKED DECISION): proves ``ReportService``
is a pure adapter, nothing more --

  1. ``ReportService()`` takes no constructor argument.
  2. ``build_report([], generated_at)`` produces a Report with
     ``total_symbols == 0``.
  3. ``build_report()`` with one ``Recommendation``.
  4. ``build_report()`` with many ``Recommendation``.
  5. ``generated_at`` is copied exactly as supplied (never generated
     internally).
  6. ``total_symbols`` equals ``len(recommendations)``.
  7. ``Report.recommendations`` is the exact same list object passed
     in -- no re-copy, no re-sort, no re-order.
  8. Recommendation order is unchanged.
  9. Input ``Recommendation`` objects (and the input list) are never
     mutated by ``build_report()``.
  10. ``build_report()`` returns a ``Report`` instance.

Uses hand-built ``Recommendation`` fixtures -- no ``RecommendationService``,
``RankingEngine``, database, or Tool involved. Purely hermetic, no I/O,
matching every other ``Tests/test_*.py`` file in this project.

Run directly: ``python Tests/test_report_service.py``
-- no external test framework required, matching every other
``Tests/test_*.py`` file in this project.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.recommendation_service import Recommendation  # noqa: E402
from Business.report_service import Report, ReportService  # noqa: E402

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


def _recommendation(
    symbol: str,
    recommendation: str = "SELL",
    confidence: str = "LOW",
    priority: int = 1,
    rank: int = 1,
) -> Recommendation:
    return Recommendation(
        symbol=symbol,
        recommendation=recommendation,
        confidence=confidence,
        priority=priority,
        rank=rank,
    )


def scenario_constructor_takes_no_dependency() -> None:
    print("\n[Scenario 1] constructor takes no dependency")
    service = ReportService()
    check(isinstance(service, ReportService), "ReportService() constructs with no arguments")


def scenario_empty_recommendations() -> None:
    print("\n[Scenario 2] empty recommendations -> Report with total_symbols == 0")
    service = ReportService()
    report = service.build_report([], "2026-08-01T09:00:00+00:00")
    check(isinstance(report, Report), "build_report() returns a Report instance")
    check(report.recommendations == [], "report.recommendations is an empty list")
    check(report.total_symbols == 0, "report.total_symbols is 0 for empty input")
    check(report.generated_at == "2026-08-01T09:00:00+00:00", "report.generated_at copied exactly")


def scenario_single_recommendation() -> None:
    print("\n[Scenario 3] single Recommendation")
    service = ReportService()
    rec = _recommendation("BBCA", recommendation="BUY", confidence="HIGH", priority=1, rank=1)
    report = service.build_report([rec], "2026-08-01T09:15:00+00:00")
    check(isinstance(report, Report), "build_report() returns a Report instance")
    check(report.total_symbols == 1, "total_symbols == 1 for a single recommendation")
    check(report.recommendations == [rec], "recommendations list contains exactly the input recommendation")
    check(report.generated_at == "2026-08-01T09:15:00+00:00", "generated_at copied exactly")


def scenario_multiple_recommendations() -> None:
    print("\n[Scenario 4] multiple Recommendation, order preserved, total_symbols correct")
    service = ReportService()
    recs = [
        _recommendation("BBCA", recommendation="BUY", confidence="HIGH", priority=1, rank=1),
        _recommendation("TLKM", recommendation="WAIT", confidence="MEDIUM", priority=2, rank=2),
        _recommendation("ASII", recommendation="SELL", confidence="LOW", priority=3, rank=3),
    ]
    report = service.build_report(recs, "2026-08-01T09:30:00+00:00")
    check(report.total_symbols == 3, "total_symbols == len(recommendations)")
    check(
        [r.symbol for r in report.recommendations] == ["BBCA", "TLKM", "ASII"],
        "recommendation order is unchanged (no sorting)",
    )


def scenario_generated_at_never_self_generated() -> None:
    print("\n[Scenario 5] generated_at comes only from the caller, in two separate calls")
    service = ReportService()
    rec = _recommendation("BBCA")
    report_a = service.build_report([rec], "2026-01-01T00:00:00+00:00")
    report_b = service.build_report([rec], "2099-12-31T23:59:59+00:00")
    check(report_a.generated_at == "2026-01-01T00:00:00+00:00", "first call's generated_at is exactly what was supplied")
    check(report_b.generated_at == "2099-12-31T23:59:59+00:00", "second call's generated_at is exactly what was supplied")
    check(report_a.generated_at != report_b.generated_at, "no internally-generated timestamp overrides the caller's value")


def scenario_recommendations_is_same_object_no_recopy() -> None:
    print("\n[Scenario 6] Report.recommendations is the exact same list object, not a copy")
    service = ReportService()
    recs = [_recommendation("BBCA"), _recommendation("TLKM")]
    report = service.build_report(recs, "2026-08-01T09:45:00+00:00")
    check(report.recommendations is recs, "report.recommendations is identity-equal to the input list (no re-copy)")
    check(report.recommendations[0] is recs[0], "individual Recommendation objects are not re-copied either")


def scenario_no_mutation_of_input() -> None:
    print("\n[Scenario 7] input list and its Recommendation objects are never mutated")
    service = ReportService()
    recs = [
        _recommendation("BBCA", recommendation="BUY", confidence="HIGH", priority=1, rank=1),
        _recommendation("TLKM", recommendation="WAIT", confidence="MEDIUM", priority=2, rank=2),
    ]
    before_len = len(recs)
    before_snapshot = [(r.symbol, r.recommendation, r.confidence, r.priority, r.rank) for r in recs]

    service.build_report(recs, "2026-08-01T10:00:00+00:00")

    after_len = len(recs)
    after_snapshot = [(r.symbol, r.recommendation, r.confidence, r.priority, r.rank) for r in recs]
    check(before_len == after_len, "input list length is unchanged after build_report()")
    check(before_snapshot == after_snapshot, "every input Recommendation's fields are unchanged after build_report()")


def scenario_report_has_exactly_three_fields() -> None:
    print("\n[Scenario 8] Report has exactly three fields, no more")
    field_names = set(Report.__dataclass_fields__.keys())
    check(
        field_names == {"generated_at", "recommendations", "total_symbols"},
        f"Report's fields are exactly {sorted(field_names)}",
    )


def scenario_service_has_only_one_public_method() -> None:
    print("\n[Scenario 9] ReportService exposes exactly one public method")
    public_methods = {name for name in dir(ReportService) if not name.startswith("_")}
    check(
        public_methods == {"build_report"},
        f"ReportService's public API is exactly {sorted(public_methods)}",
    )


def main() -> int:
    scenarios = [
        scenario_constructor_takes_no_dependency,
        scenario_empty_recommendations,
        scenario_single_recommendation,
        scenario_multiple_recommendations,
        scenario_generated_at_never_self_generated,
        scenario_recommendations_is_same_object_no_recopy,
        scenario_no_mutation_of_input,
        scenario_report_has_exactly_three_fields,
        scenario_service_has_only_one_public_method,
    ]
    for scenario in scenarios:
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"SPRINT 5 STEP 5 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())