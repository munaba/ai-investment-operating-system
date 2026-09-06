"""Phase 11 Sprint 115 proof suite -- Portfolio Analysis Skill.

``PortfolioAnalysisSkill`` is the project's first portfolio-level
Skill: it consumes a ``list`` of already-analyzed stocks (each
already carrying a ``TextAnalysisSkill``-shaped
``"recommendation"``/``"confidence"`` pair) from
``context.parameters["stocks"]`` and produces exactly one
deterministic ``SkillResult`` -- a ranking -- with no AI, no scoring
engine, no probability, no optimization algorithm, and no portfolio
mathematics of any kind. The entire ranking is one fixed, LOCKED
lookup table (recommendation priority, then confidence priority, then
original input order via Python's stable ``sorted()``), applied
entirely inline inside ``execute()``. No new class
(``PortfolioManager``, ``RankingEngine``, ``ScoreCalculator``,
``Optimizer``, ``PortfolioEngine``, ``Strategy``, ``Analyzer``,
``Factory``, ``Registry``, ``Pipeline``, ``Helper``, or utility
module) was introduced anywhere in this project to build it.

Scope: dedicated proof suite for
``Orchestration.portfolio_analysis_skill.PortfolioAnalysisSkill``
only. Mirrors the compact, table-driven, no-pytest,
global-counter-plus-main() style already used by
``Tests/test_stage_l114_text_analysis_summary.py`` and
``Tests/test_stage_l113_text_analysis_investment_thesis.py``.

Two layers of coverage (this Skill calls no Tool at all, so there is
no seam-level Tool-double layer and no real-Tool integration layer --
only the input ``context`` itself needs to be constructed):

  1. Behavioral scenarios constructing real
     ``Orchestration.skill_context.SkillContext`` instances (the same
     value object ``Executor.invoke_current_skill()`` constructs in
     production) with varying ``"stocks"`` parameters, driving every
     ranking rule, every normalization rule, and every malformed-input
     edge case.
  2. AST/namespace verification proving the ranking logic lives
     entirely inline inside ``execute()`` and that no forbidden
     abstraction was introduced.

Invariant coverage:
    R1  -- the canonical BBCA/BBRI/BMRI/ASII example from the sprint
           brief reproduces the LOCKED expected order exactly:
           BBRI, BMRI, BBCA, ASII.
    R2  -- BUY always ranks above WAIT, which always ranks above
           SELL, regardless of confidence.
    R3  -- within the same recommendation, HIGH ranks above MEDIUM,
           which ranks above LOW.
    R4  -- identical recommendation+confidence pairs preserve the
           original input order (stable sort), with no other
           tie-breaker.
    N1  -- an unrecognized/misspelled recommendation value is
           normalized to SELL priority.
    N2  -- an unrecognized/misspelled confidence value is normalized
           to LOW priority.
    N3  -- a missing "analysis" key is normalized to SELL/LOW.
    N4  -- a non-dict "analysis" value is normalized to SELL/LOW.
    N5  -- a non-dict stock entry itself is normalized to SELL/LOW,
           with symbol None, and never raises.
    N6  -- a missing "stocks" key in parameters yields an empty
           ranking, never raising.
    N7  -- a non-list "stocks" value yields an empty ranking, never
           raising.
    S1  -- each ranking entry has exactly the four keys: rank,
           symbol, recommendation, confidence -- nothing more (no
           reason/strengths/risks/summary, no score).
    S2  -- "rank" is always a 1-based, contiguous position matching
           the entry's index in the final ordered list.
    S3  -- the returned SkillResult always has success=True and
           error=None, regardless of how malformed the input was.
    S4  -- output is always exactly {"ranking": [...]} -- no other
           top-level key.
    D1  -- repeated calls with the same input are field-equal
           (deterministic, no randomness, no timestamps).
    A1  -- AST: no forbidden-name symbol (PortfolioManager,
           RankingEngine, ScoreCalculator, Optimizer, PortfolioEngine,
           Strategy, Analyzer, Factory, Registry, Pipeline, Helper,
           Utility, Engine, Manager) anywhere in the module namespace.
    A2  -- AST: the module defines exactly one class,
           PortfolioAnalysisSkill.
    A3  -- AST: execute() defines no nested function/lambda (the
           sort key lambda is the one documented, necessary
           exception -- checked separately and allowed).
    A4  -- AST: execute_tool()/execute_tool_result() are never called
           -- this Skill calls no Tool.
    A5  -- AST: exactly one SkillResult(...) construction.
    A6  -- class shape: no __init__ of its own, no per-instance
           state; name/description as specified.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.portfolio_analysis_skill import PortfolioAnalysisSkill
from Orchestration.skill_context import SkillContext
from Orchestration.skill_result import SkillResult

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
    skill = PortfolioAnalysisSkill()
    return skill.execute(_ctx(stocks))


def _stock(symbol, recommendation=None, confidence=None, with_analysis=True):
    if not with_analysis:
        return {"symbol": symbol}
    return {"symbol": symbol, "analysis": {"recommendation": recommendation, "confidence": confidence}}


# ---------------------------------------------------------------------------
# R1 -- canonical example from the sprint brief
# ---------------------------------------------------------------------------
def scenario_canonical_example() -> None:
    stocks = [
        _stock("BBCA", "WAIT", "MEDIUM"),
        _stock("BBRI", "BUY", "HIGH"),
        _stock("BMRI", "BUY", "LOW"),
        _stock("ASII", "SELL", "HIGH"),
    ]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["ranking"]]
    check(symbols_in_order == ["BBRI", "BMRI", "BBCA", "ASII"], f"R1: canonical example matches LOCKED expected order; got {symbols_in_order!r}")

    ranks = [entry["rank"] for entry in result.output["ranking"]]
    check(ranks == [1, 2, 3, 4], f"R1: ranks are 1..4 in order; got {ranks!r}")


# ---------------------------------------------------------------------------
# R2 -- recommendation priority dominates confidence
# ---------------------------------------------------------------------------
def scenario_recommendation_priority_dominates() -> None:
    stocks = [
        _stock("A", "SELL", "HIGH"),
        _stock("B", "WAIT", "LOW"),
        _stock("C", "BUY", "LOW"),
    ]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["ranking"]]
    check(
        symbols_in_order == ["C", "B", "A"],
        f"R2: BUY(LOW) beats WAIT(LOW) beats SELL(HIGH) -- recommendation always dominates confidence; got {symbols_in_order!r}",
    )


# ---------------------------------------------------------------------------
# R3 -- confidence priority within the same recommendation
# ---------------------------------------------------------------------------
def scenario_confidence_priority_within_group() -> None:
    stocks = [
        _stock("A", "BUY", "LOW"),
        _stock("B", "BUY", "HIGH"),
        _stock("C", "BUY", "MEDIUM"),
    ]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["ranking"]]
    check(symbols_in_order == ["B", "C", "A"], f"R3: within BUY, HIGH > MEDIUM > LOW; got {symbols_in_order!r}")


# ---------------------------------------------------------------------------
# R4 -- stable ordering: identical pairs preserve original input order
# ---------------------------------------------------------------------------
def scenario_stable_ordering_preserves_input_order() -> None:
    stocks = [
        _stock("Z", "BUY", "HIGH"),
        _stock("Y", "BUY", "HIGH"),
        _stock("X", "BUY", "HIGH"),
    ]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["ranking"]]
    check(symbols_in_order == ["Z", "Y", "X"], f"R4: identical recommendation+confidence preserves original input order; got {symbols_in_order!r}")


def scenario_stable_ordering_mixed_with_ties() -> None:
    stocks = [
        _stock("A", "WAIT", "MEDIUM"),
        _stock("B", "BUY", "HIGH"),
        _stock("C", "WAIT", "MEDIUM"),
        _stock("D", "BUY", "HIGH"),
    ]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["ranking"]]
    check(symbols_in_order == ["B", "D", "A", "C"], f"R4: ties within a group keep relative input order even when interleaved; got {symbols_in_order!r}")


# ---------------------------------------------------------------------------
# N1-N2 -- unrecognized recommendation/confidence normalization
# ---------------------------------------------------------------------------
def scenario_unrecognized_recommendation_normalizes_to_sell() -> None:
    stocks = [
        _stock("A", "HOLD", "HIGH"),
        _stock("B", "SELL", "HIGH"),
    ]
    result = _run(stocks)
    ranking = result.output["ranking"]
    entry_a = next(e for e in ranking if e["symbol"] == "A")
    check(entry_a["recommendation"] == "SELL", "N1: an unrecognized recommendation value is normalized to 'SELL' in the entry itself, same as the ranking priority it receives")
    symbols_in_order = [e["symbol"] for e in ranking]
    check(symbols_in_order == ["A", "B"], f"N1: unrecognized recommendation 'HOLD' ranks with SELL priority (tied with real SELL, so input order applies); got {symbols_in_order!r}")


def scenario_unrecognized_confidence_normalizes_to_low() -> None:
    stocks = [
        _stock("A", "BUY", "SUPER"),
        _stock("B", "BUY", "LOW"),
    ]
    result = _run(stocks)
    ranking = result.output["ranking"]
    entry_a = next(e for e in ranking if e["symbol"] == "A")
    check(entry_a["confidence"] == "LOW", "N2: an unrecognized confidence value is normalized to 'LOW' in the entry itself, same as the ranking priority it receives")
    symbols_in_order = [e["symbol"] for e in ranking]
    check(symbols_in_order == ["A", "B"], f"N2: unrecognized confidence 'SUPER' ranks with LOW priority (tied with real LOW, so input order applies); got {symbols_in_order!r}")


# ---------------------------------------------------------------------------
# N3-N5 -- missing/malformed analysis and stock entries
# ---------------------------------------------------------------------------
def scenario_missing_analysis_normalizes_to_sell_low() -> None:
    stocks = [
        _stock("A", with_analysis=False),
        _stock("B", "BUY", "HIGH"),
    ]
    result = _run(stocks)
    ranking = result.output["ranking"]
    entry_a = next(e for e in ranking if e["symbol"] == "A")
    check(entry_a["recommendation"] == "SELL", "N3: missing analysis normalizes recommendation to SELL")
    check(entry_a["confidence"] == "LOW", "N3: missing analysis normalizes confidence to LOW")


def scenario_non_dict_analysis_normalizes_to_sell_low() -> None:
    stocks = [
        {"symbol": "A", "analysis": "not a dict"},
        _stock("B", "BUY", "HIGH"),
    ]
    result = _run(stocks)
    ranking = result.output["ranking"]
    entry_a = next(e for e in ranking if e["symbol"] == "A")
    check(entry_a["recommendation"] == "SELL", "N4: non-dict analysis normalizes recommendation to SELL")
    check(entry_a["confidence"] == "LOW", "N4: non-dict analysis normalizes confidence to LOW")


def scenario_non_dict_stock_entry_never_raises() -> None:
    stocks = [None, "not a stock", 42, _stock("B", "BUY", "HIGH")]
    exc = _catch(lambda: _run(stocks))
    check(exc is None, f"N5: non-dict stock entries never raise; got {exc!r}")

    result = _run(stocks)
    ranking = result.output["ranking"]
    check(len(ranking) == 4, f"N5: all four entries (including malformed ones) are present; got {len(ranking)}")
    malformed_entries = [e for e in ranking if e["symbol"] is None]
    check(len(malformed_entries) == 3, f"N5: malformed entries surface symbol=None; got {len(malformed_entries)}")
    for entry in malformed_entries:
        check(entry["recommendation"] == "SELL" and entry["confidence"] == "LOW", "N5: malformed entries normalize to SELL/LOW")


# ---------------------------------------------------------------------------
# N6-N7 -- missing/non-list "stocks" parameter
# ---------------------------------------------------------------------------
def scenario_missing_stocks_key_yields_empty_ranking() -> None:
    skill = PortfolioAnalysisSkill()
    ctx = SkillContext(task=None, parameters={}, metadata={})
    exc = _catch(lambda: skill.execute(ctx))
    check(exc is None, f"N6: missing 'stocks' key never raises; got {exc!r}")

    result = skill.execute(ctx)
    check(result.output == {"ranking": []}, f"N6: missing 'stocks' key yields an empty ranking; got {result.output!r}")


def scenario_non_list_stocks_yields_empty_ranking() -> None:
    result = _run("not a list")
    check(result.output == {"ranking": []}, f"N7: non-list 'stocks' value yields an empty ranking; got {result.output!r}")

    result2 = _run(None)
    check(result2.output == {"ranking": []}, f"N7: None 'stocks' value yields an empty ranking; got {result2.output!r}")

    result3 = _run([])
    check(result3.output == {"ranking": []}, f"N7: empty 'stocks' list yields an empty ranking; got {result3.output!r}")


# ---------------------------------------------------------------------------
# S1-S4 -- output shape
# ---------------------------------------------------------------------------
def scenario_entry_shape_exact_keys() -> None:
    result = _run([_stock("A", "BUY", "HIGH")])
    entry = result.output["ranking"][0]
    check(
        set(entry.keys()) == {"rank", "symbol", "recommendation", "confidence"},
        f"S1: each ranking entry has exactly four keys; got {set(entry.keys())!r}",
    )


def scenario_rank_is_contiguous_one_based() -> None:
    stocks = [_stock(s, "BUY", "HIGH") for s in ("A", "B", "C", "D", "E")]
    result = _run(stocks)
    ranks = [entry["rank"] for entry in result.output["ranking"]]
    check(ranks == [1, 2, 3, 4, 5], f"S2: rank is 1-based and contiguous; got {ranks!r}")


def scenario_success_true_error_none_even_when_malformed() -> None:
    result = _run([None, "garbage", 42, {}])
    check(result.success is True, "S3: success is always True")
    check(result.error is None, "S3: error is always None")

    result2 = _run("not a list")
    check(result2.success is True, "S3: success is True even with a completely malformed 'stocks' value")
    check(result2.error is None, "S3: error is None even with a completely malformed 'stocks' value")


def scenario_output_has_only_ranking_key() -> None:
    result = _run([_stock("A", "BUY", "HIGH")])
    check(set(result.output.keys()) == {"ranking"}, f"S4: output has exactly one top-level key, 'ranking'; got {set(result.output.keys())!r}")
    check(result.metadata == {}, "S4: metadata is empty")


# ---------------------------------------------------------------------------
# D1 -- deterministic across repeated calls
# ---------------------------------------------------------------------------
def scenario_repeated_calls_are_deterministic() -> None:
    stocks = [
        _stock("BBCA", "WAIT", "MEDIUM"),
        _stock("BBRI", "BUY", "HIGH"),
        _stock("BMRI", "BUY", "LOW"),
        _stock("ASII", "SELL", "HIGH"),
    ]
    skill = PortfolioAnalysisSkill()
    result1 = skill.execute(_ctx(stocks))
    result2 = skill.execute(_ctx(stocks))
    check(result1 is not result2, "D1a: two separate execute() calls produce two distinct SkillResult objects")
    check(result1 == result2, "D1b: the two SkillResults are field-equal (fully deterministic, no randomness/timestamps)")


# ---------------------------------------------------------------------------
# A1-A6 -- AST / namespace verification: ranking logic stays inline, no new
# abstraction of any kind
# ---------------------------------------------------------------------------
def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.portfolio_analysis_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"PortfolioAnalysisSkill"}, f"A2: module defines exactly one class; got {class_names!r}")

    forbidden_fragments = (
        "PortfolioManager", "RankingEngine", "ScoreCalculator", "Optimizer",
        "PortfolioEngine", "Strategy", "Analyzer", "Factory", "Registry",
        "Pipeline", "Helper", "Utility", "Engine", "Manager", "Adapter",
        "Aggregator", "Builder", "Formatter", "Renderer", "TemplateEngine",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A1: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )


def scenario_execute_body_shape() -> None:
    import inspect
    import textwrap

    source = inspect.getsource(PortfolioAnalysisSkill.execute)
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
    check(len(sorted_calls) == 1, f"exactly one sorted(...) call implements the ranking; got {len(sorted_calls)}")

    forbidden_call_names = {"ToolResult", "ToolResolver", "ToolRegistry", "ToolContext", "Ollama", "PortfolioManager", "RankingEngine", "ScoreCalculator"}
    called_names = {
        (c.func.id if isinstance(c.func, ast.Name) else c.func.attr)
        for c in calls
        if isinstance(c.func, (ast.Name, ast.Attribute))
    }
    check(forbidden_call_names.isdisjoint(called_names), f"A5: no forbidden construction call present; got overlap {forbidden_call_names & called_names}")


def scenario_class_shape() -> None:
    check("__init__" not in PortfolioAnalysisSkill.__dict__, "A6a: PortfolioAnalysisSkill defines no __init__ of its own")
    skill = PortfolioAnalysisSkill()
    check(skill.__dict__ == {}, "A6b: a freshly constructed instance has no instance __dict__ entries")
    check(skill.name == "portfolio_analysis", "A6c: name is 'portfolio_analysis'")
    check(
        skill.description == "Rank multiple analyzed stocks by recommendation and confidence.",
        f"A6d: description is as specified; got {skill.description!r}",
    )


def main() -> int:
    scenarios = [
        scenario_canonical_example,
        scenario_recommendation_priority_dominates,
        scenario_confidence_priority_within_group,
        scenario_stable_ordering_preserves_input_order,
        scenario_stable_ordering_mixed_with_ties,
        scenario_unrecognized_recommendation_normalizes_to_sell,
        scenario_unrecognized_confidence_normalizes_to_low,
        scenario_missing_analysis_normalizes_to_sell_low,
        scenario_non_dict_analysis_normalizes_to_sell_low,
        scenario_non_dict_stock_entry_never_raises,
        scenario_missing_stocks_key_yields_empty_ranking,
        scenario_non_list_stocks_yields_empty_ranking,
        scenario_entry_shape_exact_keys,
        scenario_rank_is_contiguous_one_based,
        scenario_success_true_error_none_even_when_malformed,
        scenario_output_has_only_ranking_key,
        scenario_repeated_calls_are_deterministic,
        scenario_no_forbidden_abstractions,
        scenario_execute_body_shape,
        scenario_class_shape,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 11 SPRINT 115 PORTFOLIO-ANALYSIS-SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())