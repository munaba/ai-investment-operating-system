"""
Activation 2.5 proof suite -- RankingEngine (supersedes the Sprint 5
STEP 2 proof suite: that suite proved "no score, no sorting, output
order == input order"; this suite proves the opposite, deliberately,
per Activation 2.5's LOCKED DECISION override).

Scope:

  1. ``RankingEngine()`` still takes no constructor argument.
  2. ``rank()`` computes a score from (recommendation, confidence)
     using the LOCKED formula.
  3. ``rank()`` sorts surviving symbols by score, descending.
  4. ``rank()`` assigns a unique, sequential, 1-based ``rank`` across
     the whole watchlist -- not read from ``portfolio_entry`` anymore.
  5. ``rank()`` excludes (silently, no exception) any symbol whose
     ``"watchlist"`` SkillResult is missing, unsuccessful, or
     malformed ("keluarkan hasil gagal").
  6. Equal-score symbols keep their original watchlist order (stable
     sort, deterministic tie-break).
  7. ``rank()`` on an empty ``scan_result``, or one where every symbol
     failed, returns an empty list -- never raises.
  8. ``priority`` is still read from the ``"watchlist"`` entry,
     unchanged in meaning.

Uses hand-built ``SkillResult`` fixtures matching the real,
already-documented output shapes of ``WatchlistAnalysisSkill`` --
no real ``WatchlistScanner``, ``MarketAnalysisAgent``, database, or
Tool involved. Purely hermetic, no I/O, matching every other
``Tests/test_*.py`` file in this project.

Run directly: ``python Tests/test_ranking_engine.py``
-- no external test framework required.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.ranking_engine import RankedSymbol, RankingEngine  # noqa: E402
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


def _watchlist_success(
    symbol: str,
    recommendation: str,
    confidence: str,
    priority: int,
) -> SkillResult:
    """A successful 'watchlist' SkillResult, matching
    WatchlistAnalysisSkill's real documented output shape."""
    return SkillResult(
        success=True,
        output={
            "watchlist": [
                {
                    "priority": priority,
                    "symbol": symbol,
                    "recommendation": recommendation,
                    "confidence": confidence,
                    "summary": None,
                }
            ]
        },
        error=None,
        metadata={},
    )


def _agent_result(
    symbol: str,
    recommendation: str,
    confidence: str,
    priority: int,
    watchlist_result: Optional[SkillResult] = None,
) -> Dict[str, SkillResult]:
    """Build a single symbol's entry exactly in the shape
    WatchlistScanner.scan() returns it. 'market' is deliberately
    success=False (matches the real, already-documented STEP 1 known
    state) to prove RankingEngine does NOT use 'market' as a failure
    gate. 'portfolio' is present but must never be read by
    RankingEngine anymore (Activation 2.5 LOCKED DECISION)."""
    return {
        "market": SkillResult(
            success=False,
            output={"stocks": [{"symbol": symbol, "analysis": None}]},
            error=f"{symbol}: missing resolver",
            metadata={},
        ),
        "portfolio": SkillResult(
            success=True,
            output={
                "ranking": [
                    {
                        "rank": 999,  # deliberately wrong/unused sentinel
                        "symbol": symbol,
                        "recommendation": recommendation,
                        "confidence": confidence,
                    }
                ]
            },
            error=None,
            metadata={},
        ),
        "watchlist": (
            watchlist_result
            if watchlist_result is not None
            else _watchlist_success(symbol, recommendation, confidence, priority)
        ),
    }


def scenario_constructor_takes_no_dependency() -> None:
    engine = RankingEngine()
    check(isinstance(engine, RankingEngine), "RankingEngine() constructs with no arguments")


def scenario_score_formula_buy_high_beats_wait_beats_sell() -> None:
    """Score formula: recommendation dominates, confidence breaks
    ties within the same recommendation bucket."""
    engine = RankingEngine()
    scan_result = {
        "SELL_HIGH": _agent_result("SELL_HIGH", "SELL", "HIGH", 1),
        "WAIT_LOW": _agent_result("WAIT_LOW", "WAIT", "LOW", 1),
        "BUY_LOW": _agent_result("BUY_LOW", "BUY", "LOW", 1),
    }

    result = engine.rank(scan_result)
    by_symbol = {r.symbol: r for r in result}

    check(
        by_symbol["BUY_LOW"].score > by_symbol["WAIT_LOW"].score,
        "BUY (any confidence) scores higher than WAIT (any confidence)",
    )
    check(
        by_symbol["WAIT_LOW"].score > by_symbol["SELL_HIGH"].score,
        "WAIT (any confidence) scores higher than SELL (any confidence), even SELL/HIGH",
    )


def scenario_rank_sorts_by_score_descending() -> None:
    engine = RankingEngine()
    scan_result = {
        "BBCA": _agent_result("BBCA", "SELL", "LOW", 1),
        "TLKM": _agent_result("TLKM", "BUY", "HIGH", 1),
        "ASII": _agent_result("ASII", "WAIT", "MEDIUM", 1),
    }

    result = engine.rank(scan_result)

    check(len(result) == 3, "rank() returns one RankedSymbol per surviving symbol")
    check(
        [r.symbol for r in result] == ["TLKM", "ASII", "BBCA"],
        "rank() sorts BUY/HIGH first, WAIT/MEDIUM second, SELL/LOW last",
    )
    check(
        result[0].score >= result[1].score >= result[2].score,
        "scores are non-increasing across the sorted list",
    )


def scenario_rank_assigns_unique_sequential_cross_watchlist_rank() -> None:
    engine = RankingEngine()
    scan_result = {
        "BBCA": _agent_result("BBCA", "SELL", "LOW", 1),
        "TLKM": _agent_result("TLKM", "BUY", "HIGH", 1),
        "ASII": _agent_result("ASII", "WAIT", "MEDIUM", 1),
    }

    result = engine.rank(scan_result)

    check([r.rank for r in result] == [1, 2, 3], "rank is unique, sequential, 1-based, best first")
    check(
        result[0].rank != result[1].rank != result[2].rank,
        "no two symbols share the same rank",
    )


def scenario_rank_no_longer_reads_portfolio_rank_field() -> None:
    """Every _agent_result fixture sets portfolio's 'rank' to the
    sentinel 999 -- if RankingEngine still read it, every RankedSymbol
    would have rank == 999, which is not unique across symbols."""
    engine = RankingEngine()
    scan_result = {
        "BBCA": _agent_result("BBCA", "BUY", "HIGH", 1),
        "TLKM": _agent_result("TLKM", "WAIT", "MEDIUM", 1),
    }

    result = engine.rank(scan_result)

    check(
        all(r.rank != 999 for r in result),
        "rank is computed by RankingEngine itself, never copied from portfolio_entry's sentinel value",
    )


def scenario_rank_ties_preserve_original_watchlist_order() -> None:
    """Equal scores (identical recommendation+confidence) must keep
    their original scan_result order -- stable sort, no arbitrary
    tie-break."""
    engine = RankingEngine()
    scan_result = {
        "ASII": _agent_result("ASII", "BUY", "HIGH", 1),
        "BBCA": _agent_result("BBCA", "BUY", "HIGH", 1),
        "TLKM": _agent_result("TLKM", "BUY", "HIGH", 1),
    }

    result = engine.rank(scan_result)

    check(
        [r.symbol for r in result] == ["ASII", "BBCA", "TLKM"],
        "equal-score symbols keep original watchlist order (stable sort)",
    )


def scenario_failed_watchlist_result_excludes_symbol() -> None:
    """success=False on the 'watchlist' SkillResult -- the symbol is
    dropped silently, no exception, and does not consume a rank slot."""
    engine = RankingEngine()
    failed = SkillResult(success=False, output=None, error="boom", metadata={})
    scan_result = {
        "BBCA": _agent_result("BBCA", "BUY", "HIGH", 1, watchlist_result=failed),
        "TLKM": _agent_result("TLKM", "WAIT", "MEDIUM", 1),
    }

    result = engine.rank(scan_result)

    check(len(result) == 1, "failed symbol is excluded from the result")
    check(result[0].symbol == "TLKM", "only the successful symbol survives")
    check(result[0].rank == 1, "surviving symbol still gets rank 1, not rank 2")


def scenario_malformed_watchlist_output_excludes_symbol_without_raising() -> None:
    """Missing key, empty list, wrong type -- all excluded, none raise."""
    engine = RankingEngine()
    missing_key = SkillResult(success=True, output={}, error=None, metadata={})
    empty_list = SkillResult(success=True, output={"watchlist": []}, error=None, metadata={})
    wrong_type = SkillResult(success=True, output={"watchlist": "not-a-list"}, error=None, metadata={})
    unknown_recommendation = _watchlist_success("ZZZZ", "STRONG_BUY", "HIGH", 1)

    scan_result = {
        "MISSING": _agent_result("MISSING", "BUY", "HIGH", 1, watchlist_result=missing_key),
        "EMPTY": _agent_result("EMPTY", "BUY", "HIGH", 1, watchlist_result=empty_list),
        "WRONGTYPE": _agent_result("WRONGTYPE", "BUY", "HIGH", 1, watchlist_result=wrong_type),
        "UNKNOWNREC": _agent_result("UNKNOWNREC", "BUY", "HIGH", 1, watchlist_result=unknown_recommendation),
        "OK": _agent_result("OK", "BUY", "HIGH", 1),
    }

    result = engine.rank(scan_result)

    check(len(result) == 1, "all four malformed symbols excluded, only OK survives")
    check(result[0].symbol == "OK", "the one well-formed symbol survives")


def scenario_market_failure_is_not_used_as_a_failure_gate() -> None:
    """Every fixture's 'market' SkillResult is success=False (matching
    the real, documented STEP 1 known state). If RankingEngine used it
    as a failure gate, every symbol would be excluded, always."""
    engine = RankingEngine()
    scan_result = {
        "BBCA": _agent_result("BBCA", "BUY", "HIGH", 1),
        "TLKM": _agent_result("TLKM", "WAIT", "MEDIUM", 1),
    }

    result = engine.rank(scan_result)

    check(
        len(result) == 2,
        "market's success=False does not exclude symbols -- only 'watchlist' gates failure",
    )


def scenario_all_symbols_failed_returns_empty_list() -> None:
    engine = RankingEngine()
    failed = SkillResult(success=False, output=None, error="boom", metadata={})
    scan_result = {
        "BBCA": _agent_result("BBCA", "BUY", "HIGH", 1, watchlist_result=failed),
        "TLKM": _agent_result("TLKM", "WAIT", "MEDIUM", 1, watchlist_result=failed),
    }

    result = engine.rank(scan_result)

    check(result == [], "rank() returns an empty list when every symbol failed, never raises")


def scenario_rank_empty_input_returns_empty_list() -> None:
    engine = RankingEngine()
    result = engine.rank({})
    check(result == [], "rank({}) returns an empty list")


def scenario_priority_still_read_from_watchlist_entry() -> None:
    engine = RankingEngine()
    scan_result = {"BBCA": _agent_result("BBCA", "BUY", "HIGH", priority=5)}

    result = engine.rank(scan_result)

    check(result[0].priority == 5, "priority is still read from the 'watchlist' SkillResult entry, unchanged")


def main() -> int:
    scenarios = [
        scenario_constructor_takes_no_dependency,
        scenario_score_formula_buy_high_beats_wait_beats_sell,
        scenario_rank_sorts_by_score_descending,
        scenario_rank_assigns_unique_sequential_cross_watchlist_rank,
        scenario_rank_no_longer_reads_portfolio_rank_field,
        scenario_rank_ties_preserve_original_watchlist_order,
        scenario_failed_watchlist_result_excludes_symbol,
        scenario_malformed_watchlist_output_excludes_symbol_without_raising,
        scenario_market_failure_is_not_used_as_a_failure_gate,
        scenario_all_symbols_failed_returns_empty_list,
        scenario_rank_empty_input_returns_empty_list,
        scenario_priority_still_read_from_watchlist_entry,
    ]
    for scenario in scenarios:
        print(f"\n{scenario.__name__}")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"RANKING ENGINE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())