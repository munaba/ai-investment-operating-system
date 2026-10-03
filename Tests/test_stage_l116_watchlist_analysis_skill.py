"""Phase 11 Sprint 116 proof suite -- Watchlist Analysis Skill.

``WatchlistAnalysisSkill`` is the project's first watchlist-priority
Skill: it consumes a ``list`` of already-analyzed candidate stocks
(each already carrying a ``TextAnalysisSkill``-shaped
``"recommendation"``/``"confidence"``/``"summary"`` triple) from
``context.parameters["stocks"]`` and produces exactly one
deterministic ``SkillResult`` -- a priority-ordered watchlist -- with
no AI, no scoring engine, no probability, no optimization algorithm,
and no portfolio mathematics of any kind. The entire priority
ordering is one single, fixed, LOCKED nine-row (recommendation,
confidence) lookup table, applied via exactly one ``sorted(...)``
call, entirely inline inside ``execute()``. No new class
(``WatchlistManager``, ``PriorityEngine``, ``ScoreCalculator``,
``Analyzer``, ``Strategy``, ``Pipeline``, ``Factory``, ``Registry``,
``Builder``, ``Formatter``, or utility module) was introduced
anywhere in this project to build it.

Scope: dedicated proof suite for
``Orchestration.watchlist_analysis_skill.WatchlistAnalysisSkill``
only. Mirrors the compact, table-driven, no-pytest,
global-counter-plus-main() style already used by
``Tests/test_stage_l115_portfolio_analysis_skill.py``.

This Skill calls no Tool at all, so there is no seam-level Tool-double
layer and no real-Tool integration layer needed -- only the input
``context`` itself needs to be constructed, using the real
``Orchestration.skill_context.SkillContext`` value object
``Executor.invoke_current_skill()`` constructs in production.

Invariant coverage:
    W1  -- the canonical BBCA/BBRI/BMRI/ASII example reproduces the
           LOCKED expected priority order: BBRI, BMRI, BBCA, ASII.
    B1  -- within BUY, HIGH ranks before MEDIUM, which ranks before
           LOW.
    T1  -- within WAIT, HIGH ranks before MEDIUM, which ranks before
           LOW.
    S1  -- within SELL, HIGH ranks before MEDIUM, which ranks before
           LOW.
    P1  -- every BUY entry ranks above every WAIT entry, which ranks
           above every SELL entry, regardless of confidence (BUY+LOW
           still beats WAIT+HIGH; WAIT+LOW still beats SELL+HIGH).
    N1  -- an unrecognized/misspelled recommendation value is
           normalized to SELL priority, and the entry itself reports
           the normalized "SELL" (not the raw, unrecognized value).
    N2  -- an unrecognized/misspelled confidence value is normalized
           to LOW priority, and the entry itself reports the
           normalized "LOW" (not the raw, unrecognized value).
    N3  -- a missing "analysis" key is normalized to SELL/LOW with a
           None summary.
    N4  -- a non-dict "analysis" value is normalized to SELL/LOW with
           a None summary.
    N5  -- a non-dict stock entry itself is normalized to SELL/LOW,
           with symbol None and summary None, and never raises.
    N6  -- a missing "stocks" key in parameters yields an empty
           watchlist, never raising.
    N7  -- a non-list "stocks" value yields an empty watchlist, never
           raising.
    E1  -- an empty "stocks" list yields an empty watchlist.
    SM1 -- "summary" is passed through by identity, unmodified,
           whatever its value.
    D1  -- repeated calls with the same input are field-equal
           (deterministic, no randomness, no timestamps).
    O1  -- each watchlist entry has exactly the five keys: priority,
           symbol, recommendation, confidence, summary -- nothing
           more.
    O2  -- "priority" is always a 1-based, contiguous position
           matching the entry's index in the final ordered list.
    O3  -- the returned SkillResult always has success=True and
           error=None, regardless of how malformed the input was.
    O4  -- output is always exactly {"watchlist": [...]} -- no other
           top-level key.
    ST1 -- stable sort: identical (recommendation, confidence) pairs
           preserve original input order, even when interleaved with
           other groups.
    A1  -- AST: no forbidden-name symbol (WatchlistManager,
           PriorityEngine, ScoreCalculator, Analyzer, Strategy,
           Pipeline, Factory, Registry, Builder, Formatter, Manager,
           Engine, Helper, Utility) anywhere in the module namespace.
    A2  -- AST: the module defines exactly one class,
           WatchlistAnalysisSkill.
    A3  -- AST: execute() defines no nested def statements (the sort
           key lambda passed to sorted(...) is the one documented,
           necessary exception).
    A4  -- AST: execute_tool()/execute_tool_result() are never called
           -- this Skill calls no Tool.
    A5  -- AST: exactly one SkillResult(...) construction.
    A6  -- AST: exactly one sorted(...) call implements the ordering.
    A7  -- class shape: no __init__ of its own, no per-instance
           state; name/description as specified.
"""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.skill_context import SkillContext
from Orchestration.skill_result import SkillResult
from Orchestration.watchlist_analysis_skill import WatchlistAnalysisSkill

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
    else:
        _FAIL += 1
        _FAILURES.append(description)
    print(f"  {'PASS' if condition else 'FAIL'} - {description}")


def _catch(fn):
    try:
        fn()
        return None
    except Exception as exc:  # noqa: BLE001
        return exc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _ctx(stocks: Any) -> SkillContext:
    return SkillContext(task=None, parameters={"stocks": stocks}, metadata={})


def _run(stocks: Any) -> SkillResult:
    skill = WatchlistAnalysisSkill()
    return skill.execute(_ctx(stocks))


def _stock(symbol, recommendation=None, confidence=None, summary=None, with_analysis=True, status=None):
    if not with_analysis:
        entry = {"symbol": symbol}
        if status is not None:
            entry["status"] = status
        return entry
    entry = {
        "symbol": symbol,
        "analysis": {
            "recommendation": recommendation,
            "confidence": confidence,
            "summary": summary,
        },
    }
    if status is not None:
        entry["status"] = status
    return entry


# ---------------------------------------------------------------------------
# W1 -- canonical example
# ---------------------------------------------------------------------------
def scenario_canonical_example() -> None:
    stocks = [
        _stock("BBCA", "WAIT", "MEDIUM", "wait-medium"),
        _stock("BBRI", "BUY", "HIGH", "buy-high"),
        _stock("BMRI", "BUY", "LOW", "buy-low"),
        _stock("ASII", "SELL", "HIGH", "sell-high"),
    ]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["watchlist"]]
    check(symbols_in_order == ["BBRI", "BMRI", "BBCA", "ASII"], f"W1: canonical example matches LOCKED expected priority order; got {symbols_in_order!r}")

    priorities = [entry["priority"] for entry in result.output["watchlist"]]
    check(priorities == [1, 2, 3, 4], f"W1: priorities are 1..4 in order; got {priorities!r}")


# ---------------------------------------------------------------------------
# B1/T1/S1 -- within-group confidence ordering
# ---------------------------------------------------------------------------
def scenario_buy_confidence_ordering() -> None:
    stocks = [
        _stock("A", "BUY", "LOW"),
        _stock("B", "BUY", "HIGH"),
        _stock("C", "BUY", "MEDIUM"),
    ]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["watchlist"]]
    check(symbols_in_order == ["B", "C", "A"], f"B1: within BUY, HIGH before MEDIUM before LOW; got {symbols_in_order!r}")


def scenario_wait_confidence_ordering() -> None:
    stocks = [
        _stock("A", "WAIT", "LOW"),
        _stock("B", "WAIT", "HIGH"),
        _stock("C", "WAIT", "MEDIUM"),
    ]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["watchlist"]]
    check(symbols_in_order == ["B", "C", "A"], f"T1: within WAIT, HIGH before MEDIUM before LOW; got {symbols_in_order!r}")


def scenario_sell_confidence_ordering() -> None:
    stocks = [
        _stock("A", "SELL", "LOW"),
        _stock("B", "SELL", "HIGH"),
        _stock("C", "SELL", "MEDIUM"),
    ]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["watchlist"]]
    check(symbols_in_order == ["B", "C", "A"], f"S1: within SELL, HIGH before MEDIUM before LOW; got {symbols_in_order!r}")


# ---------------------------------------------------------------------------
# P1 -- recommendation group always dominates confidence across groups
# ---------------------------------------------------------------------------
def scenario_recommendation_group_dominates_confidence() -> None:
    stocks = [
        _stock("A", "SELL", "HIGH"),
        _stock("B", "WAIT", "HIGH"),
        _stock("C", "BUY", "LOW"),
    ]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["watchlist"]]
    check(
        symbols_in_order == ["C", "B", "A"],
        f"P1: BUY+LOW beats WAIT+HIGH beats SELL+HIGH -- recommendation group always dominates confidence; got {symbols_in_order!r}",
    )

    stocks2 = [
        _stock("A", "SELL", "HIGH"),
        _stock("B", "WAIT", "LOW"),
    ]
    result2 = _run(stocks2)
    symbols_in_order2 = [entry["symbol"] for entry in result2.output["watchlist"]]
    check(symbols_in_order2 == ["B", "A"], f"P1: WAIT+LOW beats SELL+HIGH; got {symbols_in_order2!r}")


# ---------------------------------------------------------------------------
# N1-N2 -- unrecognized recommendation/confidence normalization
# ---------------------------------------------------------------------------
def scenario_unrecognized_recommendation_normalizes_to_sell() -> None:
    stocks = [
        _stock("A", "HOLD", "HIGH"),
        _stock("B", "SELL", "HIGH"),
    ]
    result = _run(stocks)
    watchlist = result.output["watchlist"]
    entry_a = next(e for e in watchlist if e["symbol"] == "A")
    check(entry_a["recommendation"] == "SKIPPED", "N1: unrecognized recommendation surfaces failure status SKIPPED (no status present), not a live SELL")
    check(entry_a["confidence"] is None, "N1: unrecognized recommendation yields confidence=None, not a live HIGH/LOW")


def scenario_unrecognized_recommendation_with_upstream_status_is_preserved() -> None:
    stocks = [
        _stock("A", "UNKNOWN", "HIGH", status="DATA_ERROR"),
        _stock("B", "SELL", "HIGH"),
    ]
    result = _run(stocks)
    watchlist = result.output["watchlist"]
    entry_a = next(e for e in watchlist if e["symbol"] == "A")
    check(entry_a["recommendation"] == "DATA_ERROR", "N1b: analysis is a dict but recommendation is 'UNKNOWN' -- existing upstream failure status DATA_ERROR is surfaced, not a live SELL")
    check(entry_a["confidence"] is None, "N1b: recommendation outside BUY/WAIT/SELL yields confidence=None, not a live HIGH/LOW")


def scenario_unrecognized_confidence_normalizes_to_low() -> None:
    stocks = [
        _stock("A", "BUY", "SUPER"),
        _stock("B", "BUY", "LOW"),
    ]
    result = _run(stocks)
    watchlist = result.output["watchlist"]
    entry_a = next(e for e in watchlist if e["symbol"] == "A")
    check(entry_a["confidence"] == "LOW", "N2: unrecognized confidence is normalized to 'LOW' in the entry itself")
    symbols_in_order = [e["symbol"] for e in watchlist]
    check(symbols_in_order == ["A", "B"], f"N2: unrecognized confidence 'SUPER' ranks with BUY+LOW priority (tied, so input order applies); got {symbols_in_order!r}")


# ---------------------------------------------------------------------------
# N3-N5 -- missing/malformed analysis and stock entries
# ---------------------------------------------------------------------------
def scenario_missing_analysis_normalizes_to_sell_low_none_summary() -> None:
    stocks = [
        _stock("A", with_analysis=False),
        _stock("B", "BUY", "HIGH", "buy-high"),
    ]
    result = _run(stocks)
    watchlist = result.output["watchlist"]
    entry_a = next(e for e in watchlist if e["symbol"] == "A")
    check(entry_a["recommendation"] == "SKIPPED", "N3: missing analysis surfaces failure status SKIPPED (no status present), not a live SELL")
    check(entry_a["confidence"] is None, "N3: missing analysis yields confidence=None, not a live LOW")
    check(entry_a["summary"] is None, "N3: missing analysis yields summary=None")


def scenario_non_dict_analysis_normalizes_to_sell_low_none_summary() -> None:
    stocks = [
        {"symbol": "A", "analysis": "not a dict"},
        _stock("B", "BUY", "HIGH", "buy-high"),
    ]
    result = _run(stocks)
    watchlist = result.output["watchlist"]
    entry_a = next(e for e in watchlist if e["symbol"] == "A")
    check(entry_a["recommendation"] == "SKIPPED", "N4: non-dict analysis surfaces failure status SKIPPED (no status present), not a live SELL")
    check(entry_a["confidence"] is None, "N4: non-dict analysis yields confidence=None, not a live LOW")
    check(entry_a["summary"] is None, "N4: non-dict analysis yields summary=None")


def scenario_non_dict_stock_entry_never_raises() -> None:
    stocks = [None, "not a stock", 42, _stock("B", "BUY", "HIGH", "buy-high")]
    exc = _catch(lambda: _run(stocks))
    check(exc is None, f"N5: non-dict stock entries never raise; got {exc!r}")

    result = _run(stocks)
    watchlist = result.output["watchlist"]
    check(len(watchlist) == 4, f"N5: all four entries (including malformed ones) are present; got {len(watchlist)}")
    malformed_entries = [e for e in watchlist if e["symbol"] is None]
    check(len(malformed_entries) == 3, f"N5: malformed entries surface symbol=None; got {len(malformed_entries)}")
    for entry in malformed_entries:
        check(
            entry["recommendation"] == "SKIPPED" and entry["confidence"] is None and entry["summary"] is None,
            "N5: malformed entries surface failure status SKIPPED with confidence=None, summary=None",
        )


# ---------------------------------------------------------------------------
# N6-N7, E1 -- missing/non-list/empty "stocks" parameter
# ---------------------------------------------------------------------------
def scenario_missing_stocks_key_yields_empty_watchlist() -> None:
    skill = WatchlistAnalysisSkill()
    ctx = SkillContext(task=None, parameters={}, metadata={})
    exc = _catch(lambda: skill.execute(ctx))
    check(exc is None, f"N6: missing 'stocks' key never raises; got {exc!r}")

    result = skill.execute(ctx)
    check(result.output == {"watchlist": []}, f"N6: missing 'stocks' key yields an empty watchlist; got {result.output!r}")


def scenario_non_list_stocks_yields_empty_watchlist() -> None:
    result = _run("not a list")
    check(result.output == {"watchlist": []}, f"N7: non-list 'stocks' value yields an empty watchlist; got {result.output!r}")

    result2 = _run(None)
    check(result2.output == {"watchlist": []}, f"N7: None 'stocks' value yields an empty watchlist; got {result2.output!r}")

    result3 = _run(42)
    check(result3.output == {"watchlist": []}, f"N7: an int 'stocks' value yields an empty watchlist; got {result3.output!r}")


def scenario_empty_stocks_list_yields_empty_watchlist() -> None:
    result = _run([])
    check(result.output == {"watchlist": []}, f"E1: empty 'stocks' list yields an empty watchlist; got {result.output!r}")


# ---------------------------------------------------------------------------
# SM1 -- summary passthrough
# ---------------------------------------------------------------------------
def scenario_summary_passthrough() -> None:
    stocks = [_stock("A", "BUY", "HIGH", "a very specific summary string")]
    result = _run(stocks)
    entry = result.output["watchlist"][0]
    check(entry["summary"] == "a very specific summary string", f"SM1: summary is passed through by identity; got {entry['summary']!r}")

    stocks2 = [_stock("B", "BUY", "HIGH", None)]
    result2 = _run(stocks2)
    entry2 = result2.output["watchlist"][0]
    check(entry2["summary"] is None, "SM1: an explicit None summary is passed through as None")


# ---------------------------------------------------------------------------
# D1 -- deterministic across repeated calls
# ---------------------------------------------------------------------------
def scenario_repeated_calls_are_deterministic() -> None:
    stocks = [
        _stock("BBCA", "WAIT", "MEDIUM", "s1"),
        _stock("BBRI", "BUY", "HIGH", "s2"),
        _stock("BMRI", "BUY", "LOW", "s3"),
        _stock("ASII", "SELL", "HIGH", "s4"),
    ]
    skill = WatchlistAnalysisSkill()
    result1 = skill.execute(_ctx(stocks))
    result2 = skill.execute(_ctx(stocks))
    check(result1 is not result2, "D1a: two separate execute() calls produce two distinct SkillResult objects")
    check(result1 == result2, "D1b: the two SkillResults are field-equal (fully deterministic, no randomness/timestamps)")


# ---------------------------------------------------------------------------
# O1-O4 -- output shape
# ---------------------------------------------------------------------------
def scenario_entry_shape_exact_keys() -> None:
    result = _run([_stock("A", "BUY", "HIGH", "s")])
    entry = result.output["watchlist"][0]
    check(
        set(entry.keys()) == {"priority", "symbol", "recommendation", "confidence", "summary"},
        f"O1: each watchlist entry has exactly five keys; got {set(entry.keys())!r}",
    )


def scenario_priority_is_contiguous_one_based() -> None:
    stocks = [_stock(s, "BUY", "HIGH", "s") for s in ("A", "B", "C", "D", "E")]
    result = _run(stocks)
    priorities = [entry["priority"] for entry in result.output["watchlist"]]
    check(priorities == [1, 2, 3, 4, 5], f"O2: priority is 1-based and contiguous; got {priorities!r}")


def scenario_success_true_error_none_even_when_malformed() -> None:
    result = _run([None, "garbage", 42, {}])
    check(result.success is True, "O3: success is always True")
    check(result.error is None, "O3: error is always None")

    result2 = _run("not a list")
    check(result2.success is True, "O3: success is True even with a completely malformed 'stocks' value")
    check(result2.error is None, "O3: error is None even with a completely malformed 'stocks' value")


def scenario_output_has_only_watchlist_key() -> None:
    result = _run([_stock("A", "BUY", "HIGH", "s")])
    check(set(result.output.keys()) == {"watchlist"}, f"O4: output has exactly one top-level key, 'watchlist'; got {set(result.output.keys())!r}")
    check(result.metadata == {}, "O4: metadata is empty")


# ---------------------------------------------------------------------------
# ST1 -- stable sort: identical pairs preserve original order
# ---------------------------------------------------------------------------
def scenario_stable_sort_preserves_input_order() -> None:
    stocks = [
        _stock("Z", "BUY", "HIGH", "z"),
        _stock("Y", "BUY", "HIGH", "y"),
        _stock("X", "BUY", "HIGH", "x"),
    ]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["watchlist"]]
    check(symbols_in_order == ["Z", "Y", "X"], f"ST1: identical (recommendation, confidence) pairs preserve original input order; got {symbols_in_order!r}")


def scenario_stable_sort_mixed_with_ties() -> None:
    stocks = [
        _stock("A", "WAIT", "MEDIUM", "a"),
        _stock("B", "BUY", "HIGH", "b"),
        _stock("C", "WAIT", "MEDIUM", "c"),
        _stock("D", "BUY", "HIGH", "d"),
    ]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["watchlist"]]
    check(symbols_in_order == ["B", "D", "A", "C"], f"ST1: ties within a group keep relative input order even when interleaved; got {symbols_in_order!r}")


# ---------------------------------------------------------------------------
# A1-A7 -- AST / namespace verification: watchlist logic stays inline, no
# new abstraction of any kind
# ---------------------------------------------------------------------------
def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.watchlist_analysis_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"WatchlistAnalysisSkill"}, f"A2: module defines exactly one class; got {class_names!r}")

    forbidden_fragments = (
        "WatchlistManager", "PriorityEngine", "ScoreCalculator", "Analyzer",
        "Strategy", "Pipeline", "Factory", "Registry", "Builder",
        "Formatter", "Manager", "Engine", "Helper", "Utility", "Adapter",
        "Aggregator", "Renderer", "TemplateEngine", "Optimizer",
        "PortfolioManager", "RankingEngine",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A1: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )


def scenario_execute_body_shape() -> None:
    source = inspect.getsource(WatchlistAnalysisSkill.execute)
    tree = ast.parse(textwrap.dedent(source))

    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    check(len(nested_funcdefs) == 0, f"A3: execute() defines no nested def statements; got {len(nested_funcdefs)}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    forbidden_tool_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr in ("execute_tool", "execute_tool_result")
    ]
    check(len(forbidden_tool_calls) == 0, f"A4: execute() never calls execute_tool()/execute_tool_result() -- this Skill calls no Tool; got {len(forbidden_tool_calls)}")

    skill_result_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillResult"]
    check(len(skill_result_calls) == 1, f"A5: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    sorted_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "sorted"]
    check(len(sorted_calls) == 1, f"A6: exactly one sorted(...) call implements the ordering; got {len(sorted_calls)}")

    forbidden_call_names = {"ToolResult", "ToolResolver", "ToolRegistry", "ToolContext", "Ollama", "WatchlistManager", "PriorityEngine", "ScoreCalculator"}
    called_names = {
        (c.func.id if isinstance(c.func, ast.Name) else c.func.attr)
        for c in calls
        if isinstance(c.func, (ast.Name, ast.Attribute))
    }
    check(forbidden_call_names.isdisjoint(called_names), f"A5b: no forbidden construction call present; got overlap {forbidden_call_names & called_names}")


def scenario_class_shape() -> None:
    check("__init__" not in WatchlistAnalysisSkill.__dict__, "A7a: WatchlistAnalysisSkill defines no __init__ of its own")
    skill = WatchlistAnalysisSkill()
    check(skill.__dict__ == {}, "A7b: a freshly constructed instance has no instance __dict__ entries")
    check(skill.name == "watchlist_analysis", "A7c: name is 'watchlist_analysis'")
    check(
        skill.description == "Prioritize watchlist candidates by recommendation and confidence.",
        f"A7d: description is as specified; got {skill.description!r}",
    )


def main() -> int:
    scenarios = [
        scenario_canonical_example,
        scenario_buy_confidence_ordering,
        scenario_wait_confidence_ordering,
        scenario_sell_confidence_ordering,
        scenario_recommendation_group_dominates_confidence,
        scenario_unrecognized_recommendation_normalizes_to_sell,
        scenario_unrecognized_recommendation_with_upstream_status_is_preserved,
        scenario_unrecognized_confidence_normalizes_to_low,
        scenario_missing_analysis_normalizes_to_sell_low_none_summary,
        scenario_non_dict_analysis_normalizes_to_sell_low_none_summary,
        scenario_non_dict_stock_entry_never_raises,
        scenario_missing_stocks_key_yields_empty_watchlist,
        scenario_non_list_stocks_yields_empty_watchlist,
        scenario_empty_stocks_list_yields_empty_watchlist,
        scenario_summary_passthrough,
        scenario_repeated_calls_are_deterministic,
        scenario_entry_shape_exact_keys,
        scenario_priority_is_contiguous_one_based,
        scenario_success_true_error_none_even_when_malformed,
        scenario_output_has_only_watchlist_key,
        scenario_stable_sort_preserves_input_order,
        scenario_stable_sort_mixed_with_ties,
        scenario_no_forbidden_abstractions,
        scenario_execute_body_shape,
        scenario_class_shape,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 11 SPRINT 116 WATCHLIST-ANALYSIS-SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())