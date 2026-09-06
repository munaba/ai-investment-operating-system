"""Phase 10 Sprint 111 proof suite -- First Real Fundamental Analysis.

``MarketFundamentalTool.execute(context)`` is no longer a bare
``NotImplementedError`` stub. It now derives ``"valuation"`` (from
``context.parameters["pe_ratio"]``) and ``"quality"`` (from
``context.parameters["roe"]``) deterministically, independently of
each other, via the LOCKED rule tables -- entirely inline inside
``execute()`` itself. No new class, Manager, Engine, Strategy,
Analyzer, Registry, Factory, Adapter, Pipeline, or helper module was
introduced anywhere in this project to add it.

Note: as of this sprint, ``MarketFundamentalTool`` is still not wired
into ``TextAnalysisSkill`` (which continues to call only
``market_price`` and ``market_news``, unchanged since Sprint 108) --
this sprint upgrades the standalone Tool only, exactly as scoped.
That is why this suite has no Executor -> Skill -> Tool integration
scenario analogous to Sprint 110's ``I1``/``I2``: there is no
production caller of ``market_fundamental`` yet to integrate through.
Direct, real ``ToolContext`` scenarios (T-series) plus AST/namespace
verification (A-series) are the appropriate coverage for a
not-yet-wired Tool, matching this project's own Sprint 60/61/99/107
history (each of which shipped Tool-level proof suites before any
Skill ever called them).

Scope: dedicated proof suite for the Sprint 111 change to
``Orchestration.market_fundamental_tool.MarketFundamentalTool`` only.
Mirrors the compact, table-driven, no-pytest, global-counter-plus-
main() style already used by
``Tests/test_stage_l110_market_price_tool_analysis.py``.

Invariant coverage:
    T1  -- pe_ratio < 15 -> valuation="undervalued".
    T2  -- 15 <= pe_ratio <= 25 -> valuation="fair" (including both
           boundary values 15 and 25 exactly).
    T3  -- pe_ratio > 25 -> valuation="overvalued".
    T4  -- pe_ratio missing/None/non-numeric/bool ->
           valuation="unknown".
    T5  -- roe >= 15 -> quality="strong" (including the boundary
           value 15 exactly).
    T6  -- roe < 15 -> quality="weak".
    T7  -- roe missing/None/non-numeric/bool -> quality="unknown".
    T8  -- valuation and quality are derived independently: an
           invalid pe_ratio does not affect quality, and an invalid
           roe does not affect valuation.
    T9  -- missing symbol -> symbol="UNKNOWN".
    T10 -- non-str / empty-str symbol -> symbol="UNKNOWN".
    T11 -- a real, present symbol is forwarded unchanged.
    T12 -- no other valuation value is ever produced -- only
           "undervalued", "fair", "overvalued", "unknown".
    T13 -- no other quality value is ever produced -- only "strong",
           "weak", "unknown".
    T14 -- determinism: identical parameters always produce an
           identical (field-equal) ToolResult, across repeated calls
           and across separate MarketFundamentalTool instances.
    T15 -- never raises: None, a plain string, a dict without
           .parameters, and an arbitrary object are all tolerated as
           ``context`` without exception.
    T16 -- success/error/metadata shape: success=True, error=None,
           metadata={} on every call.
    T17 -- a real ToolContext (not just a duck-typed stand-in) flows
           through the same code path correctly.
    T18 -- bool values for pe_ratio/roe are treated as invalid (not
           coerced to 1/0), yielding "unknown".
    A1  -- AST: no forbidden-name symbol (Manager, Registry, Adapter,
           Factory, Analyzer, Strategy, Engine, DecisionEngine,
           Pipeline, Utility, Helper) anywhere in the module
           namespace.
    A2  -- AST: the module defines exactly one class,
           MarketFundamentalTool.
    A3  -- AST: execute() defines no nested function/lambda -- the
           analysis is flat code inside execute() itself.
    A4  -- class shape: still no __init__ of its own, no
           per-instance state; name/description unchanged.
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.market_fundamental_tool import MarketFundamentalTool
from Orchestration.tool_context import ToolContext
from Orchestration.tool_result import ToolResult

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
class _DuckContext:
    """A minimal duck-typed context stand-in exposing only
    ``.parameters`` -- MarketFundamentalTool never requires a real
    ToolContext, matching MarketPriceTool's Sprint 110 tolerance."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _run(parameters: Any) -> ToolResult:
    tool = MarketFundamentalTool()
    return tool.execute(_DuckContext(parameters))


# ---------------------------------------------------------------------------
# T1-T3 -- the three valuation rules, including boundaries
# ---------------------------------------------------------------------------
def scenario_undervalued() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": 10})
    check(result.output["valuation"] == "undervalued", "T1: pe_ratio < 15 -> valuation=undervalued")


def scenario_undervalued_boundary_just_below() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": 14.999})
    check(result.output["valuation"] == "undervalued", "T1: pe_ratio just below 15 -> valuation=undervalued")


def scenario_fair_lower_boundary() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": 15})
    check(result.output["valuation"] == "fair", "T2: pe_ratio == 15 (lower boundary) -> valuation=fair")


def scenario_fair_mid() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": 20})
    check(result.output["valuation"] == "fair", "T2: pe_ratio == 20 -> valuation=fair")


def scenario_fair_upper_boundary() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": 25})
    check(result.output["valuation"] == "fair", "T2: pe_ratio == 25 (upper boundary) -> valuation=fair")


def scenario_overvalued() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": 30})
    check(result.output["valuation"] == "overvalued", "T3: pe_ratio > 25 -> valuation=overvalued")


def scenario_overvalued_boundary_just_above() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": 25.001})
    check(result.output["valuation"] == "overvalued", "T3: pe_ratio just above 25 -> valuation=overvalued")


# ---------------------------------------------------------------------------
# T4 -- invalid pe_ratio -> unknown
# ---------------------------------------------------------------------------
def scenario_missing_pe_ratio() -> None:
    result = _run({"symbol": "AAPL", "roe": 20})
    check(result.output["valuation"] == "unknown", "T4: missing pe_ratio -> valuation=unknown")


def scenario_none_pe_ratio() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": None})
    check(result.output["valuation"] == "unknown", "T4: None pe_ratio -> valuation=unknown")


def scenario_string_pe_ratio() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": "20"})
    check(result.output["valuation"] == "unknown", "T4: string pe_ratio -> valuation=unknown (never coerced)")


def scenario_bool_pe_ratio() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": True})
    check(result.output["valuation"] == "unknown", "T4/T18: bool pe_ratio -> valuation=unknown (not coerced to 1)")


def scenario_list_pe_ratio() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": [20]})
    check(result.output["valuation"] == "unknown", "T4: list pe_ratio -> valuation=unknown")


# ---------------------------------------------------------------------------
# T5-T6 -- the two quality rules, including boundary
# ---------------------------------------------------------------------------
def scenario_strong_quality() -> None:
    result = _run({"symbol": "AAPL", "roe": 20})
    check(result.output["quality"] == "strong", "T5: roe >= 15 -> quality=strong")


def scenario_strong_quality_boundary() -> None:
    result = _run({"symbol": "AAPL", "roe": 15})
    check(result.output["quality"] == "strong", "T5: roe == 15 (boundary) -> quality=strong")


def scenario_weak_quality() -> None:
    result = _run({"symbol": "AAPL", "roe": 10})
    check(result.output["quality"] == "weak", "T6: roe < 15 -> quality=weak")


def scenario_weak_quality_boundary_just_below() -> None:
    result = _run({"symbol": "AAPL", "roe": 14.999})
    check(result.output["quality"] == "weak", "T6: roe just below 15 -> quality=weak")


def scenario_negative_roe_is_weak() -> None:
    result = _run({"symbol": "AAPL", "roe": -5})
    check(result.output["quality"] == "weak", "T6: negative roe -> quality=weak (still a valid, comparable number)")


# ---------------------------------------------------------------------------
# T7 -- invalid roe -> unknown
# ---------------------------------------------------------------------------
def scenario_missing_roe() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": 20})
    check(result.output["quality"] == "unknown", "T7: missing roe -> quality=unknown")


def scenario_none_roe() -> None:
    result = _run({"symbol": "AAPL", "roe": None})
    check(result.output["quality"] == "unknown", "T7: None roe -> quality=unknown")


def scenario_string_roe() -> None:
    result = _run({"symbol": "AAPL", "roe": "20"})
    check(result.output["quality"] == "unknown", "T7: string roe -> quality=unknown (never coerced)")


def scenario_bool_roe() -> None:
    result = _run({"symbol": "AAPL", "roe": False})
    check(result.output["quality"] == "unknown", "T7/T18: bool roe -> quality=unknown (not coerced to 0)")


# ---------------------------------------------------------------------------
# T8 -- independence of valuation and quality
# ---------------------------------------------------------------------------
def scenario_invalid_pe_valid_roe() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": "bad", "roe": 18})
    check(result.output["valuation"] == "unknown", "T8: invalid pe_ratio -> valuation=unknown")
    check(result.output["quality"] == "strong", "T8: a valid roe still produces a real quality despite invalid pe_ratio")


def scenario_valid_pe_invalid_roe() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": 10, "roe": "bad"})
    check(result.output["valuation"] == "undervalued", "T8: a valid pe_ratio still produces a real valuation despite invalid roe")
    check(result.output["quality"] == "unknown", "T8: invalid roe -> quality=unknown")


def scenario_both_valid() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": 12, "roe": 22})
    check(result.output == {"symbol": "AAPL", "valuation": "undervalued", "quality": "strong"}, f"T8: both valid produces the full expected output; got {result.output!r}")


def scenario_both_invalid() -> None:
    result = _run({"symbol": "AAPL"})
    check(result.output == {"symbol": "AAPL", "valuation": "unknown", "quality": "unknown"}, f"T8: both missing produces unknown/unknown; got {result.output!r}")


# ---------------------------------------------------------------------------
# T9-T11 -- symbol defaulting
# ---------------------------------------------------------------------------
def scenario_missing_symbol() -> None:
    result = _run({"pe_ratio": 10, "roe": 20})
    check(result.output["symbol"] == "UNKNOWN", "T9: missing symbol -> symbol=UNKNOWN")


def scenario_non_str_symbol() -> None:
    result = _run({"symbol": 12345, "pe_ratio": 10, "roe": 20})
    check(result.output["symbol"] == "UNKNOWN", "T10: non-str symbol -> symbol=UNKNOWN")


def scenario_empty_str_symbol() -> None:
    result = _run({"symbol": "", "pe_ratio": 10, "roe": 20})
    check(result.output["symbol"] == "UNKNOWN", "T10: empty-str symbol -> symbol=UNKNOWN")


def scenario_real_symbol_forwarded() -> None:
    result = _run({"symbol": "BBCA", "pe_ratio": 10, "roe": 20})
    check(result.output["symbol"] == "BBCA", "T11: a real symbol is forwarded unchanged")


# ---------------------------------------------------------------------------
# T12-T13 -- exhaustive sweeps: only the LOCKED values ever appear
# ---------------------------------------------------------------------------
def scenario_exhaustive_valuation_values() -> None:
    pe_values = [10, 14.999, 15, 20, 25, 25.001, 30, None, "20", [1], True, False]
    allowed = {"undervalued", "fair", "overvalued", "unknown"}
    all_valid = True
    for pe in pe_values:
        params = {"symbol": "X", "roe": 20}
        if pe is not None or True:
            params["pe_ratio"] = pe
        result = _run(params)
        if result.output["valuation"] not in allowed:
            all_valid = False
    check(all_valid, "T12: every valuation value produced is one of undervalued/fair/overvalued/unknown")


def scenario_exhaustive_quality_values() -> None:
    roe_values = [10, 14.999, 15, 20, -5, None, "20", [1], True, False]
    allowed = {"strong", "weak", "unknown"}
    all_valid = True
    for roe in roe_values:
        result = _run({"symbol": "X", "pe_ratio": 20, "roe": roe})
        if result.output["quality"] not in allowed:
            all_valid = False
    check(all_valid, "T13: every quality value produced is one of strong/weak/unknown")


# ---------------------------------------------------------------------------
# T14 -- determinism
# ---------------------------------------------------------------------------
def scenario_determinism() -> None:
    params = {"symbol": "AAPL", "pe_ratio": 12, "roe": 18}
    result1 = _run(params)
    result2 = _run(params)
    tool2 = MarketFundamentalTool()
    result3 = tool2.execute(_DuckContext(dict(params)))

    check(result1 == result2, "T14a: repeated calls with identical parameters are field-equal")
    check(result1 == result3, "T14b: separate MarketFundamentalTool instances are field-equal for identical parameters")
    check(result1.output == {"symbol": "AAPL", "valuation": "undervalued", "quality": "strong"}, "T14c: output matches expected deterministic value")


# ---------------------------------------------------------------------------
# T15 -- never raises on malformed context
# ---------------------------------------------------------------------------
def scenario_never_raises() -> None:
    tool = MarketFundamentalTool()
    for label, ctx in [
        ("None context", None),
        ("plain string context", "not a context"),
        ("dict without .parameters attr", {"symbol": "AAPL"}),
        ("arbitrary object", object()),
    ]:
        exc = _catch(lambda ctx=ctx: tool.execute(ctx))
        check(exc is None, f"T15: execute() never raises for {label}; got {exc!r}")


def scenario_malformed_context_falls_back_to_defaults() -> None:
    tool = MarketFundamentalTool()
    result = tool.execute(object())
    check(result.output == {"symbol": "UNKNOWN", "valuation": "unknown", "quality": "unknown"}, f"T15: malformed context falls back to full LOCKED defaults; got {result.output!r}")


# ---------------------------------------------------------------------------
# T16 -- success/error/metadata shape
# ---------------------------------------------------------------------------
def scenario_result_shape() -> None:
    result = _run({"symbol": "AAPL", "pe_ratio": 10, "roe": 20})
    check(result.success is True, "T16: success is always True")
    check(result.error is None, "T16: error is always None")
    check(dict(result.metadata) == {}, "T16: metadata is always {}")
    check(type(result) is ToolResult, "T16: returned object's exact type is ToolResult")


# ---------------------------------------------------------------------------
# T17 -- a real ToolContext flows through correctly
# ---------------------------------------------------------------------------
def scenario_real_tool_context() -> None:
    tool = MarketFundamentalTool()
    context = ToolContext(task=None, parameters={"symbol": "BBCA", "pe_ratio": 30, "roe": 8}, metadata={})
    result = tool.execute(context)
    check(result.output == {"symbol": "BBCA", "valuation": "overvalued", "quality": "weak"}, f"T17: real ToolContext flows through correctly; got {result.output!r}")


# ---------------------------------------------------------------------------
# A1-A4 -- AST / namespace verification: analysis stays inline, no new
# abstraction of any kind
# ---------------------------------------------------------------------------
def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.market_fundamental_tool as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"MarketFundamentalTool"}, f"A2: module defines exactly one class; got {class_names!r}")

    forbidden_fragments = (
        "Manager", "Registry", "Adapter", "Factory", "Aggregator",
        "Pipeline", "Engine", "Analyzer", "Strategy", "DecisionEngine",
        "Utility", "Helper",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A1: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )


def scenario_execute_body_shape() -> None:
    source = inspect.getsource(MarketFundamentalTool.execute)
    tree = ast.parse(_dedent(source))

    top_level_def = tree.body[0]
    nested_defs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_defs) == 0, f"A3: execute() defines no nested function/lambda; got {len(nested_defs)}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    tool_result_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "ToolResult"]
    check(len(tool_result_calls) == 1, f"A3: exactly one ToolResult(...) construction; got {len(tool_result_calls)}")

    forbidden_call_names = {"ToolResolver", "ToolRegistry", "ToolContext", "Ollama"}
    called_names = {
        (c.func.id if isinstance(c.func, ast.Name) else c.func.attr)
        for c in calls
        if isinstance(c.func, (ast.Name, ast.Attribute))
    }
    check(forbidden_call_names.isdisjoint(called_names), f"A3: no forbidden construction call present; got overlap {forbidden_call_names & called_names}")


def _dedent(source: str) -> str:
    import textwrap
    return textwrap.dedent(source)


def scenario_class_shape_unchanged() -> None:
    check("__init__" not in MarketFundamentalTool.__dict__, "A4a: MarketFundamentalTool still defines no __init__ of its own")
    tool = MarketFundamentalTool()
    check(tool.__dict__ == {}, "A4b: a freshly constructed instance still has no instance __dict__ entries")
    check(tool.name == "market_fundamental", "A4c: name is unchanged ('market_fundamental')")
    check(tool.description == "Retrieve market fundamental information.", "A4d: description is unchanged")


def main() -> int:
    scenarios = [
        scenario_undervalued,
        scenario_undervalued_boundary_just_below,
        scenario_fair_lower_boundary,
        scenario_fair_mid,
        scenario_fair_upper_boundary,
        scenario_overvalued,
        scenario_overvalued_boundary_just_above,
        scenario_missing_pe_ratio,
        scenario_none_pe_ratio,
        scenario_string_pe_ratio,
        scenario_bool_pe_ratio,
        scenario_list_pe_ratio,
        scenario_strong_quality,
        scenario_strong_quality_boundary,
        scenario_weak_quality,
        scenario_weak_quality_boundary_just_below,
        scenario_negative_roe_is_weak,
        scenario_missing_roe,
        scenario_none_roe,
        scenario_string_roe,
        scenario_bool_roe,
        scenario_invalid_pe_valid_roe,
        scenario_valid_pe_invalid_roe,
        scenario_both_valid,
        scenario_both_invalid,
        scenario_missing_symbol,
        scenario_non_str_symbol,
        scenario_empty_str_symbol,
        scenario_real_symbol_forwarded,
        scenario_exhaustive_valuation_values,
        scenario_exhaustive_quality_values,
        scenario_determinism,
        scenario_never_raises,
        scenario_malformed_context_falls_back_to_defaults,
        scenario_result_shape,
        scenario_real_tool_context,
        scenario_no_forbidden_abstractions,
        scenario_execute_body_shape,
        scenario_class_shape_unchanged,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 10 SPRINT 111 MARKET-FUNDAMENTAL-TOOL-ANALYSIS RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())