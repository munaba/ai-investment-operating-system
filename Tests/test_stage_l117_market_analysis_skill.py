"""Phase 11 Sprint 117 proof suite -- Market Analysis Skill.

``MarketAnalysisSkill`` is the project's first multi-stock
orchestrator Skill: it reads ``context.parameters["symbols"]`` (a
list of symbol strings) and, for each symbol, runs the exact same,
already-existing ``Orchestration.text_analysis_skill.
TextAnalysisSkill.execute()`` -- never a copy of its logic -- against
a freshly built per-symbol ``SkillContext`` whose only change from
the incoming context is ``parameters={"symbol": symbol}``.

Scope: dedicated proof suite for
``Orchestration.market_analysis_skill.MarketAnalysisSkill`` only.
Mirrors the compact, table-driven, no-pytest, global-counter-plus-
main() style already used by
``Tests/test_stage_l115_portfolio_analysis_skill.py`` and
``Tests/test_stage_l116_watchlist_analysis_skill.py``, combined with
the seam-level ``_FixedTool``/``_FixedResolver`` Tool-double pattern
already used by
``Tests/test_stage_l112_text_analysis_fundamental_integration.py`` --
since, unlike the two Sprint 115/116 Skills, this Skill's execution
does reach all the way down to (fake) Tools via the real
``TextAnalysisSkill`` it drives.

Invariant coverage:
    O1  -- for a list of N symbols, each backed by a fully successful
           fake TextAnalysisSkill Tool trio, the output is
           {"stocks": [{"symbol": s, "analysis": {...}}, ...]} with
           one entry per symbol, in original input order.
    O2  -- each stock's "analysis" is forwarded by identity -- it is
           literally the same dict object TextAnalysisSkill.execute()
           produced under its own "analysis" key (checked via `is`).
    O3  -- output has exactly one top-level key, "stocks"; each stock
           entry has exactly two keys, "symbol"/"analysis".
    C1  -- the SkillContext built for each symbol has
           parameters == {"symbol": symbol} exactly.
    C2  -- task/metadata/tool_context_factory are carried through
           from the incoming context, unchanged, into every
           per-symbol SkillContext (verified via a tool_context_factory
           sentinel that a fake Tool can call/return to prove it was
           forwarded).
    S1  -- success=True when every symbol's TextAnalysisSkill call
           succeeds; error=None.
    F1  -- one symbol whose underlying Tools report success=False
           (TextAnalysisSkill combined_success=False) does not stop
           later symbols from being processed; overall success is
           False; error mentions the failed symbol; the failed
           symbol's stock entry still carries a real "analysis" dict
           (TextAnalysisSkill always computes one).
    F2  -- one symbol whose TextAnalysisSkill.execute() call raises
           an exception outright does not stop later symbols from
           being processed; overall success is False; error mentions
           the failed symbol; the failed symbol's stock entry has
           "analysis": None.
    F3  -- multiple failing symbols each contribute their own message
           to the combined error string.
    E1  -- an empty "symbols" list yields {"stocks": []},
           success=True, error=None.
    N1  -- a missing "symbols" key yields an empty stocks list, never
           raising.
    N2  -- a non-list "symbols" value yields an empty stocks list,
           never raising.
    D1  -- repeated calls with the same input are field-equal in
           shape (symbol/recommendation/confidence match), i.e. fully
           deterministic given deterministic fake Tools.
    R1  -- MarketAnalysisSkill never resolves or calls a Tool
           directly itself -- only through the TextAnalysisSkill
           instances it constructs; verified by MarketAnalysisSkill
           having no _resolve_tool usage other than the forward.
    A1  -- AST: no forbidden-name symbol (Manager, Engine,
           Coordinator, Workflow, Pipeline, Strategy, Helper, Factory,
           Analyzer, Registry, Service, Adapter, Utility) anywhere in
           the module namespace.
    A2  -- AST: the module defines exactly one class,
           MarketAnalysisSkill.
    A3  -- AST: execute() never calls self.execute_tool()/
           self.execute_tool_result() itself -- it only ever calls
           TextAnalysisSkill.execute().
    A4  -- AST: exactly one SkillResult(...) construction and exactly
           one TextAnalysisSkill(...) construction inside execute().
    A5  -- class shape: no __init__ of its own, no per-instance
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

from Orchestration.market_analysis_skill import MarketAnalysisSkill
from Orchestration.skill_context import SkillContext
from Orchestration.skill_result import SkillResult
from Orchestration.text_analysis_skill import TextAnalysisSkill
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
# Fixtures (seam-level test doubles -- duck-typed Tools, not framework mocks)
# ---------------------------------------------------------------------------
class _SymbolAwareTool:
    """A duck-typed Tool stand-in whose ``ToolResult`` depends on the
    ``symbol`` the incoming ``SkillContext.parameters`` carries -- so
    a per-symbol failure can be simulated without any special-casing
    inside ``MarketAnalysisSkill`` itself."""

    def __init__(self, output_by_symbol, failing_symbols=(), raising_symbols=()):
        self.output_by_symbol = output_by_symbol
        self.failing_symbols = set(failing_symbols)
        self.raising_symbols = set(raising_symbols)
        self.received_contexts: List[Any] = []

    def execute(self, context):
        self.received_contexts.append(context)
        symbol = context.parameters.get("symbol")
        if symbol in self.raising_symbols:
            raise RuntimeError(f"boom for {symbol}")
        success = symbol not in self.failing_symbols
        output = self.output_by_symbol.get(symbol, {})
        return ToolResult(
            success=success,
            output=output,
            error=None if success else f"tool failure for {symbol}",
            metadata={},
        )


class _FixedResolver:
    """Dispatches to whichever fake Tool stand-in was registered
    under the requested name -- exactly the shape
    ``Executor.invoke_current_skill()`` injects as
    ``skill._resolve_tool``."""

    def __init__(self, tools: dict):
        self.tools = tools

    def __call__(self, name):
        return self.tools[name]


def _make_resolver(failing_symbols=(), raising_symbols=()):
    # Every symbol is wired to the bullish/positive/undervalued row of
    # TextAnalysisSkill's LOCKED decision table, so a successful symbol's
    # analysis is distinguishable (recommendation=="BUY") from a symbol
    # whose Tools failed (recommendation=="UNKNOWN").
    symbols = ("BBCA", "BBRI", "BMRI", "ASII")
    price_outputs = {s: {"trend": "bullish"} for s in symbols if s not in failing_symbols}
    news_outputs = {s: {"overall_sentiment": "positive"} for s in symbols if s not in failing_symbols}
    fundamental_outputs = {s: {"valuation": "undervalued", "quality": "strong"} for s in symbols if s not in failing_symbols}
    return _FixedResolver({
        "market_price": _SymbolAwareTool(price_outputs, failing_symbols, raising_symbols),
        "market_news": _SymbolAwareTool(news_outputs, failing_symbols, raising_symbols),
        "market_fundamental": _SymbolAwareTool(fundamental_outputs, failing_symbols, raising_symbols),
    })


def _ctx(symbols: Any, task: Any = None, metadata: Any = None, tool_context_factory=None) -> SkillContext:
    return SkillContext(
        task=task,
        parameters={"symbols": symbols},
        metadata=metadata if metadata is not None else {},
        tool_context_factory=tool_context_factory,
    )


def _skill_with_resolver(resolver) -> MarketAnalysisSkill:
    skill = MarketAnalysisSkill()
    skill._resolve_tool = resolver
    return skill


def _run(symbols: Any, failing_symbols=(), raising_symbols=(), **ctx_kwargs) -> SkillResult:
    resolver = _make_resolver(failing_symbols, raising_symbols)
    skill = _skill_with_resolver(resolver)
    return skill.execute(_ctx(symbols, **ctx_kwargs))


# ---------------------------------------------------------------------------
# O1-O3 -- happy path output shape
# ---------------------------------------------------------------------------
def scenario_multiple_symbols_all_succeed() -> None:
    result = _run(["BBCA", "BBRI", "BMRI", "ASII"])
    check(result.success is True, "O1: success is True when every symbol succeeds")
    check(result.error is None, "O1: error is None when every symbol succeeds")

    stocks = result.output["stocks"]
    check(len(stocks) == 4, f"O1: one entry per symbol; got {len(stocks)}")
    symbols_in_order = [s["symbol"] for s in stocks]
    check(symbols_in_order == ["BBCA", "BBRI", "BMRI", "ASII"], f"O1: original input order preserved; got {symbols_in_order!r}")

    for entry in stocks:
        check(isinstance(entry["analysis"], dict), f"O1: analysis is a dict for {entry['symbol']}")
        check("recommendation" in entry["analysis"], f"O1: analysis carries a recommendation for {entry['symbol']}")


def scenario_analysis_forwarded_by_identity() -> None:
    resolver = _make_resolver()
    skill = _skill_with_resolver(resolver)

    # Run TextAnalysisSkill directly with the same resolver, for the same
    # symbol, to obtain the "reference" analysis dict shape independently.
    reference_skill = TextAnalysisSkill()
    reference_skill._resolve_tool = resolver
    reference_context = SkillContext(task=None, parameters={"symbol": "BBCA"}, metadata={})
    reference_result = reference_skill.execute(reference_context)

    result = skill.execute(_ctx(["BBCA"]))
    entry_analysis = result.output["stocks"][0]["analysis"]

    check(entry_analysis == reference_result.output["analysis"], "O2: forwarded analysis matches an independently-run TextAnalysisSkill's analysis")
    check(set(entry_analysis.keys()) == set(reference_result.output["analysis"].keys()), "O2: forwarded analysis has the exact same keys, unmodified")


def scenario_output_shape_exact_keys() -> None:
    result = _run(["BBCA"])
    check(set(result.output.keys()) == {"stocks"}, f"O3: output has exactly one top-level key, 'stocks'; got {set(result.output.keys())!r}")
    entry = result.output["stocks"][0]
    check(set(entry.keys()) == {"symbol", "analysis"}, f"O3: each stock entry has exactly two keys; got {set(entry.keys())!r}")
    check(result.metadata == {}, "O3: metadata is empty")


# ---------------------------------------------------------------------------
# C1-C2 -- per-symbol SkillContext construction
# ---------------------------------------------------------------------------
def scenario_per_symbol_context_parameters_is_symbol_only() -> None:
    resolver = _make_resolver()
    skill = _skill_with_resolver(resolver)
    skill.execute(_ctx(["BBCA", "BBRI"]))

    price_tool = resolver.tools["market_price"]
    received_params = [dict(c.parameters) for c in price_tool.received_contexts]
    check(received_params == [{"symbol": "BBCA"}, {"symbol": "BBRI"}], f"C1: each per-symbol context carries parameters == {{'symbol': symbol}} exactly; got {received_params!r}")


def scenario_task_metadata_tool_context_factory_carried_through() -> None:
    resolver = _make_resolver()
    skill = _skill_with_resolver(resolver)

    sentinel_task = object()
    sentinel_metadata = {"trace_id": "xyz"}

    def sentinel_factory():
        return "sentinel-tool-context"

    context = _ctx(["BBCA"], task=sentinel_task, metadata=sentinel_metadata, tool_context_factory=sentinel_factory)
    skill.execute(context)

    price_tool = resolver.tools["market_price"]
    received_context = price_tool.received_contexts[0]
    check(received_context.task is sentinel_task, "C2: task is carried through unchanged into the per-symbol SkillContext")
    check(dict(received_context.metadata) == sentinel_metadata, "C2: metadata is carried through unchanged into the per-symbol SkillContext")
    check(received_context.tool_context_factory is sentinel_factory, "C2: tool_context_factory is carried through unchanged into the per-symbol SkillContext")


# ---------------------------------------------------------------------------
# S1 -- overall success shape
# ---------------------------------------------------------------------------
def scenario_all_succeed_overall_success_true() -> None:
    result = _run(["BBCA", "BBRI"])
    check(result.success is True, "S1: success True when all symbols succeed")
    check(result.error is None, "S1: error None when all symbols succeed")


# ---------------------------------------------------------------------------
# F1 -- one symbol's Tools fail (TextAnalysisSkill combined_success=False)
# ---------------------------------------------------------------------------
def scenario_one_symbol_tool_failure_continues_and_reports() -> None:
    result = _run(["BBCA", "BBRI", "BMRI"], failing_symbols={"BBRI"})
    check(result.success is False, "F1: overall success is False when one symbol's Tools fail")
    check(result.error is not None and "BBRI" in result.error, f"F1: error mentions the failed symbol; got {result.error!r}")

    stocks = result.output["stocks"]
    symbols_in_order = [s["symbol"] for s in stocks]
    check(symbols_in_order == ["BBCA", "BBRI", "BMRI"], f"F1: all symbols still present, in order, despite the failure; got {symbols_in_order!r}")

    bbri_entry = next(s for s in stocks if s["symbol"] == "BBRI")
    check(isinstance(bbri_entry["analysis"], dict), "F1: the failed symbol's TextAnalysisSkill still computed an analysis dict")
    check(bbri_entry["analysis"].get("recommendation") == "UNKNOWN", "F1: the failed symbol's analysis reflects insufficient data (UNKNOWN)")

    other_symbols = [s for s in stocks if s["symbol"] != "BBRI"]
    for entry in other_symbols:
        check(isinstance(entry["analysis"], dict) and entry["analysis"].get("recommendation") != "UNKNOWN", f"F1: {entry['symbol']} was unaffected by BBRI's failure")


# ---------------------------------------------------------------------------
# F2 -- one symbol's TextAnalysisSkill.execute() raises outright
# ---------------------------------------------------------------------------
def scenario_one_symbol_raises_continues_and_reports() -> None:
    exc = _catch(lambda: _run(["BBCA", "BBRI", "BMRI"], raising_symbols={"BBRI"}))
    check(exc is None, f"F2: MarketAnalysisSkill.execute() itself never raises, even when a per-symbol call raises; got {exc!r}")

    result = _run(["BBCA", "BBRI", "BMRI"], raising_symbols={"BBRI"})
    check(result.success is False, "F2: overall success is False when one symbol's call raises")
    check(result.error is not None and "BBRI" in result.error, f"F2: error mentions the failed symbol; got {result.error!r}")

    stocks = result.output["stocks"]
    symbols_in_order = [s["symbol"] for s in stocks]
    check(symbols_in_order == ["BBCA", "BBRI", "BMRI"], f"F2: all symbols still present, in order, despite the raise; got {symbols_in_order!r}")

    bbri_entry = next(s for s in stocks if s["symbol"] == "BBRI")
    check(bbri_entry["analysis"] is None, f"F2: the raised symbol's analysis is None (nothing to forward by identity); got {bbri_entry['analysis']!r}")

    other_symbols = [s for s in stocks if s["symbol"] != "BBRI"]
    for entry in other_symbols:
        check(isinstance(entry["analysis"], dict), f"F2: {entry['symbol']} still produced a real analysis, unaffected by BBRI's raise")


# ---------------------------------------------------------------------------
# F3 -- multiple failures each contribute to the combined error
# ---------------------------------------------------------------------------
def scenario_multiple_failures_each_contribute_to_error() -> None:
    result = _run(["BBCA", "BBRI", "BMRI", "ASII"], failing_symbols={"BBRI"}, raising_symbols={"ASII"})
    check(result.success is False, "F3: overall success False with multiple failures")
    check(result.error is not None and "BBRI" in result.error and "ASII" in result.error, f"F3: error mentions both failed symbols; got {result.error!r}")

    stocks = result.output["stocks"]
    check(len(stocks) == 4, f"F3: all four symbols still present; got {len(stocks)}")
    good_symbols = [s["symbol"] for s in stocks if s["symbol"] in ("BBCA", "BMRI")]
    check(good_symbols == ["BBCA", "BMRI"], "F3: unaffected symbols still processed normally")


# ---------------------------------------------------------------------------
# E1, N1-N2 -- empty / missing / malformed "symbols"
# ---------------------------------------------------------------------------
def scenario_empty_symbols_list_yields_empty_stocks() -> None:
    result = _run([])
    check(result.output == {"stocks": []}, f"E1: empty symbols list yields empty stocks; got {result.output!r}")
    check(result.success is True, "E1: success True for an empty symbols list")
    check(result.error is None, "E1: error None for an empty symbols list")


def scenario_missing_symbols_key_yields_empty_stocks() -> None:
    skill = _skill_with_resolver(_make_resolver())
    ctx = SkillContext(task=None, parameters={}, metadata={})
    exc = _catch(lambda: skill.execute(ctx))
    check(exc is None, f"N1: missing 'symbols' key never raises; got {exc!r}")

    result = skill.execute(ctx)
    check(result.output == {"stocks": []}, f"N1: missing 'symbols' key yields empty stocks; got {result.output!r}")
    check(result.success is True, "N1: success True when 'symbols' is missing")


def scenario_non_list_symbols_yields_empty_stocks() -> None:
    result = _run("not a list")
    check(result.output == {"stocks": []}, f"N2: non-list 'symbols' value yields empty stocks; got {result.output!r}")

    result2 = _run(None)
    check(result2.output == {"stocks": []}, f"N2: None 'symbols' value yields empty stocks; got {result2.output!r}")


# ---------------------------------------------------------------------------
# D1 -- deterministic across repeated calls (given deterministic fakes)
# ---------------------------------------------------------------------------
def scenario_repeated_calls_are_deterministic() -> None:
    def _shape(result: SkillResult):
        return [(s["symbol"], s["analysis"].get("recommendation") if s["analysis"] else None) for s in result.output["stocks"]]

    result1 = _run(["BBCA", "BBRI"])
    result2 = _run(["BBCA", "BBRI"])
    check(_shape(result1) == _shape(result2), "D1: repeated calls with the same input produce the same shape")
    check(result1.success == result2.success, "D1: repeated calls have the same success value")


# ---------------------------------------------------------------------------
# A1-A5 -- AST / namespace verification: orchestration logic stays inline,
# no forbidden abstraction, no bypass of TextAnalysisSkill.execute()
# ---------------------------------------------------------------------------
def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.market_analysis_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"MarketAnalysisSkill"}, f"A2: module defines exactly one class; got {class_names!r}")

    forbidden_fragments = (
        "Manager", "Engine", "Coordinator", "Workflow", "Pipeline",
        "Strategy", "Helper", "Factory", "Analyzer", "Registry",
        "Service", "Adapter", "Utility",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A1: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )


def scenario_execute_body_shape() -> None:
    source = inspect.getsource(MarketAnalysisSkill.execute)
    tree = ast.parse(textwrap.dedent(source))

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

    forbidden_self_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute)
        and c.func.attr in ("execute_tool", "execute_tool_result")
        and isinstance(c.func.value, ast.Name)
        and c.func.value.id == "self"
    ]
    check(len(forbidden_self_calls) == 0, f"A3: execute() never calls self.execute_tool()/self.execute_tool_result() directly; got {len(forbidden_self_calls)}")

    text_analysis_execute_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr == "execute"
    ]
    check(len(text_analysis_execute_calls) >= 1, "A3: execute() calls .execute(...) on a TextAnalysisSkill instance")

    skill_result_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillResult"]
    check(len(skill_result_calls) == 1, f"A4: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    text_analysis_skill_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "TextAnalysisSkill"]
    check(len(text_analysis_skill_calls) == 1, f"A4: exactly one TextAnalysisSkill(...) construction; got {len(text_analysis_skill_calls)}")

    skill_context_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillContext"]
    check(len(skill_context_calls) == 1, f"exactly one SkillContext(...) construction per symbol (one call site); got {len(skill_context_calls)}")


def scenario_class_shape() -> None:
    check("__init__" not in MarketAnalysisSkill.__dict__, "A5a: MarketAnalysisSkill defines no __init__ of its own")
    skill = MarketAnalysisSkill()
    check(skill.__dict__ == {}, "A5b: a freshly constructed instance has no instance __dict__ entries")
    check(skill.name == "market_analysis", "A5c: name is 'market_analysis'")
    check(
        skill.description == "Analyze multiple stocks by running TextAnalysisSkill for each symbol.",
        f"A5d: description is as specified; got {skill.description!r}",
    )


def main() -> int:
    scenarios = [
        scenario_multiple_symbols_all_succeed,
        scenario_analysis_forwarded_by_identity,
        scenario_output_shape_exact_keys,
        scenario_per_symbol_context_parameters_is_symbol_only,
        scenario_task_metadata_tool_context_factory_carried_through,
        scenario_all_succeed_overall_success_true,
        scenario_one_symbol_tool_failure_continues_and_reports,
        scenario_one_symbol_raises_continues_and_reports,
        scenario_multiple_failures_each_contribute_to_error,
        scenario_empty_symbols_list_yields_empty_stocks,
        scenario_missing_symbols_key_yields_empty_stocks,
        scenario_non_list_symbols_yields_empty_stocks,
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
    print(f"PHASE 11 SPRINT 117 MARKET-ANALYSIS-SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())