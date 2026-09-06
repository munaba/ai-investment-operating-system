"""
Sprint 5 STEP 4 proof suite -- RecommendationService.

Scope (per Sprint 5 STEP 4 LOCKED DECISION): proves
``RecommendationService`` is a pure adapter, nothing more --

  1. ``RecommendationService()`` takes no constructor argument.
  2. ``build_recommendations([])`` returns an empty list.
  3. ``build_recommendations()`` maps one ``RankedSymbol`` correctly.
  4. ``build_recommendations()`` maps many ``RankedSymbol`` correctly.
  5. Output order is exactly input order.
  6. Every field is copied correctly (``symbol``/``recommendation``/
     ``confidence``/``priority``/``rank``).
  7. Each ``Recommendation`` is a newly constructed object, never the
     same object as (nor sharing identity with) its source
     ``RankedSymbol``.
  8. Input ``RankedSymbol`` objects are never mutated by
     ``build_recommendations()``.

Uses hand-built ``RankedSymbol`` fixtures -- no ``RankingEngine``,
``WatchlistScanner``, database, or Tool involved. Purely hermetic, no
I/O, matching every other ``Tests/test_*.py`` file in this project.

Run directly: ``python Tests/test_recommendation_service.py``
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

from Business.ranking_engine import RankedSymbol  # noqa: E402
from Business.recommendation_service import Recommendation, RecommendationService  # noqa: E402

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


def _ranked_symbol(
    symbol: str,
    recommendation: str = "SELL",
    confidence: str = "LOW",
    priority: int = 1,
    rank: int = 1,
    score: int = 0,
) -> RankedSymbol:
    # score is Activation 2.5's addition to RankedSymbol -- irrelevant
    # to RecommendationService (which never reads it), so a fixed
    # placeholder is fine here; only symbol/recommendation/confidence/
    # priority/rank matter for this test file's own scenarios.
    return RankedSymbol(
        symbol=symbol,
        recommendation=recommendation,
        confidence=confidence,
        priority=priority,
        score=score,
        rank=rank,
    )


def scenario_constructor_takes_no_dependency() -> None:
    print("\n[Scenario 1] constructor takes no dependency")
    service = RecommendationService()
    check(isinstance(service, RecommendationService), "RecommendationService() constructs with no arguments")


def scenario_empty_list() -> None:
    print("\n[Scenario 2] empty list in -> empty list out")
    service = RecommendationService()
    result = service.build_recommendations([])
    check(result == [], "build_recommendations([]) returns an empty list")
    check(isinstance(result, list), "build_recommendations([]) still returns a list, not None")


def scenario_single_recommendation() -> None:
    print("\n[Scenario 3] single RankedSymbol maps to a single Recommendation")
    service = RecommendationService()
    ranked = _ranked_symbol("BBCA", recommendation="BUY", confidence="HIGH", priority=1, rank=1)
    result = service.build_recommendations([ranked])
    check(len(result) == 1, "one RankedSymbol in produces one Recommendation out")
    check(isinstance(result[0], Recommendation), "output element is a Recommendation instance")
    check(result[0].symbol == "BBCA", "symbol copied correctly")
    check(result[0].recommendation == "BUY", "recommendation copied correctly")
    check(result[0].confidence == "HIGH", "confidence copied correctly")
    check(result[0].priority == 1, "priority copied correctly")
    check(result[0].rank == 1, "rank copied correctly")


def scenario_multiple_recommendations() -> None:
    print("\n[Scenario 4] multiple RankedSymbol map to multiple Recommendation, same order")
    service = RecommendationService()
    ranked_symbols = [
        _ranked_symbol("BBCA", recommendation="BUY", confidence="HIGH", priority=1, rank=1),
        _ranked_symbol("TLKM", recommendation="WAIT", confidence="MEDIUM", priority=2, rank=2),
        _ranked_symbol("ASII", recommendation="SELL", confidence="LOW", priority=3, rank=3),
    ]
    result = service.build_recommendations(ranked_symbols)
    check(len(result) == 3, "three RankedSymbol in produce three Recommendation out")
    check(
        [r.symbol for r in result] == ["BBCA", "TLKM", "ASII"],
        "output order is exactly input order (no sorting)",
    )
    for source, output in zip(ranked_symbols, result):
        check(output.symbol == source.symbol, f"symbol matches for {source.symbol}")
        check(output.recommendation == source.recommendation, f"recommendation matches for {source.symbol}")
        check(output.confidence == source.confidence, f"confidence matches for {source.symbol}")
        check(output.priority == source.priority, f"priority matches for {source.symbol}")
        check(output.rank == source.rank, f"rank matches for {source.symbol}")


def scenario_output_is_new_object_not_source() -> None:
    print("\n[Scenario 5] Recommendation is a newly constructed object, never the source RankedSymbol")
    service = RecommendationService()
    ranked = _ranked_symbol("BBCA")
    result = service.build_recommendations([ranked])
    check(result[0] is not ranked, "output Recommendation is not the same object as the source RankedSymbol")
    check(not isinstance(result[0], RankedSymbol), "output Recommendation is not a RankedSymbol instance")
    check(type(result[0]) is Recommendation, "output element's exact type is Recommendation")


def scenario_no_mutation_of_input() -> None:
    print("\n[Scenario 6] input RankedSymbol objects are never mutated")
    service = RecommendationService()
    ranked = _ranked_symbol("BBCA", recommendation="BUY", confidence="HIGH", priority=1, rank=1)
    snapshot_before = (ranked.symbol, ranked.recommendation, ranked.confidence, ranked.priority, ranked.rank)
    service.build_recommendations([ranked])
    snapshot_after = (ranked.symbol, ranked.recommendation, ranked.confidence, ranked.priority, ranked.rank)
    check(snapshot_before == snapshot_after, "source RankedSymbol's fields are unchanged after build_recommendations()")

    # Also verify with a list of many, then re-verify each source is untouched.
    many = [
        _ranked_symbol("BBCA", recommendation="BUY", confidence="HIGH", priority=1, rank=1),
        _ranked_symbol("TLKM", recommendation="WAIT", confidence="MEDIUM", priority=2, rank=2),
    ]
    before = [(s.symbol, s.recommendation, s.confidence, s.priority, s.rank) for s in many]
    service.build_recommendations(many)
    after = [(s.symbol, s.recommendation, s.confidence, s.priority, s.rank) for s in many]
    check(before == after, "every source RankedSymbol in a multi-element list remains unmutated")


def scenario_recommendation_has_exactly_five_fields() -> None:
    print("\n[Scenario 7] Recommendation has exactly five fields, no more")
    field_names = set(Recommendation.__dataclass_fields__.keys())
    check(
        field_names == {"symbol", "recommendation", "confidence", "priority", "rank"},
        f"Recommendation's fields are exactly {sorted(field_names)}",
    )


def scenario_service_has_only_one_public_method() -> None:
    print("\n[Scenario 8] RecommendationService exposes exactly one public method")
    public_methods = {name for name in dir(RecommendationService) if not name.startswith("_")}
    check(
        public_methods == {"build_recommendations"},
        f"RecommendationService's public API is exactly {sorted(public_methods)}",
    )


def main() -> int:
    scenarios = [
        scenario_constructor_takes_no_dependency,
        scenario_empty_list,
        scenario_single_recommendation,
        scenario_multiple_recommendations,
        scenario_output_is_new_object_not_source,
        scenario_no_mutation_of_input,
        scenario_recommendation_has_exactly_five_fields,
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
    print(f"SPRINT 5 STEP 4 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())