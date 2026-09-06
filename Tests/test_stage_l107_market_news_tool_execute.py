"""Phase 10 Sprint 107 -- ``MarketNewsTool.execute()`` first real
feature: deterministic, keyword-based headline sentiment
classification.

Scope: this suite proves the new, real behavior of ``execute()`` --
it no longer raises, it processes ``context.parameters`` (``symbol``,
``headlines``) deterministically via a fixed in-module keyword
lexicon, and it returns a real, varying ``ToolResult`` shaped exactly
as documented. It also proves the continued absence of everything
this sprint forbids: no network, filesystem, database, AI/Runtime/
Workflow/Service/Repository/Registry/Resolver/Manager involvement, and
no new class/Manager/Registry/Context/Factory/Adapter/Interface
introduced anywhere in the module. Compact, table-driven, no-pytest
style, matching the project's existing Stage L conventions (global
pass/fail counter, plain fixtures, ``main()`` runner).

Invariant coverage:
    T1  -- execute() returns a ToolResult for a well-formed
           ToolContext with symbol + headlines.
    T2  -- Sentiment classification is correct for clearly positive,
           clearly negative, and neutral/mixed headlines.
    T3  -- Aggregate output (headline_count, overall_sentiment,
           sentiment_score) is computed correctly across a mixed set.
    T4  -- Symbol defaults to "UNKNOWN" when missing or malformed;
           a valid string symbol is passed through unchanged.
    T5  -- headlines defaults to an empty tuple when missing,
           malformed, or of an unsupported type; output reflects an
           empty, neutral, zero-score result in that case.
    T6  -- A single bare string is accepted as a one-item headlines
           list.
    T7  -- execute() never raises regardless of what `context` is
           (None, a string, an int, an arbitrary object, a dict,
           a ToolContext with malformed parameters).
    T8  -- Determinism: repeated calls and independent instances
           given equal inputs produce equal ToolResults.
    T9  -- ToolResult contract: success=True, error=None,
           metadata=={}, output is a dict with exactly the five
           documented keys.
    T10 -- No forbidden import present (network/db/AI/Runtime/
           Workflow/Service/Repository/Registry/Resolver/Manager),
           verified via AST inspection of the module source.
    T11 -- No new class defined in the module beyond MarketNewsTool;
           no new public method on MarketNewsTool beyond
           name/description/execute.
    T12 -- name/description are unchanged from prior sprints.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.base_tool import BaseTool
from Orchestration.market_news_tool import MarketNewsTool
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


# ---------------------------------------------------------------------------
# T1 -- basic well-formed call
# ---------------------------------------------------------------------------
def scenario_basic_well_formed_call() -> None:
    tool = MarketNewsTool()
    ctx = ToolContext(
        task=None,
        parameters={"symbol": "BBCA", "headlines": ["Profits surge to record high"]},
        metadata={},
    )
    result = tool.execute(ctx)

    check(isinstance(result, ToolResult), "T1: execute() returns a ToolResult")
    check(result.success is True, "T1: result.success is True")
    check(result.error is None, "T1: result.error is None")
    check(result.output["symbol"] == "BBCA", "T1: output['symbol'] passed through")
    check(result.output["headline_count"] == 1, "T1: output['headline_count'] == 1")


# ---------------------------------------------------------------------------
# T2 -- per-headline classification correctness
# ---------------------------------------------------------------------------
def scenario_headline_classification_correctness() -> None:
    tool = MarketNewsTool()

    cases = [
        ("Company profits surge to a record high", "positive"),
        ("Stock rallies after strong earnings beat", "positive"),
        ("Shares plunge after profit warning", "negative"),
        ("Analyst downgrade cites weak outlook", "negative"),
        ("Company announces quarterly results today", "neutral"),
        ("Markets closed for a public holiday", "neutral"),
    ]
    for headline, expected in cases:
        ctx = ToolContext(task=None, parameters={"headlines": [headline]}, metadata={})
        result = tool.execute(ctx)
        got = result.output["headlines"][0]["sentiment"]
        check(got == expected, f"T2: {headline!r} classified as {expected!r} (got {got!r})")


# ---------------------------------------------------------------------------
# T3 -- aggregate correctness across a mixed set
# ---------------------------------------------------------------------------
def scenario_aggregate_correctness() -> None:
    tool = MarketNewsTool()
    headlines = [
        "Profits surge to a record high",
        "Stock rallies after strong earnings beat",
        "Shares plunge after profit warning",
        "Company announces quarterly results today",
    ]
    ctx = ToolContext(task=None, parameters={"headlines": headlines}, metadata={})
    result = tool.execute(ctx)

    check(result.output["headline_count"] == 4, "T3: headline_count == 4")
    check(len(result.output["headlines"]) == 4, "T3: per-headline list has 4 entries")
    check(result.output["sentiment_score"] == 1, "T3: sentiment_score == positive(2) - negative(1) == 1")
    check(result.output["overall_sentiment"] == "positive", "T3: overall_sentiment == 'positive' (2 positive beats 1 negative, 1 neutral)")


def scenario_aggregate_tie_resolves_neutral() -> None:
    tool = MarketNewsTool()
    headlines = [
        "Profits surge to a record high",
        "Shares plunge after profit warning",
    ]
    ctx = ToolContext(task=None, parameters={"headlines": headlines}, metadata={})
    result = tool.execute(ctx)
    check(result.output["sentiment_score"] == 0, "T3b: tie yields sentiment_score == 0")
    check(result.output["overall_sentiment"] == "neutral", "T3b: 1-1 tie resolves to 'neutral'")


# ---------------------------------------------------------------------------
# T4 -- symbol defaulting / passthrough
# ---------------------------------------------------------------------------
def scenario_symbol_defaulting() -> None:
    tool = MarketNewsTool()

    ctx_missing = ToolContext(task=None, parameters={}, metadata={})
    check(tool.execute(ctx_missing).output["symbol"] == "UNKNOWN", "T4: missing symbol defaults to 'UNKNOWN'")

    ctx_malformed = ToolContext(task=None, parameters={"symbol": 12345}, metadata={})
    check(tool.execute(ctx_malformed).output["symbol"] == "UNKNOWN", "T4: non-str symbol defaults to 'UNKNOWN'")

    ctx_empty_str = ToolContext(task=None, parameters={"symbol": ""}, metadata={})
    check(tool.execute(ctx_empty_str).output["symbol"] == "UNKNOWN", "T4: empty-string symbol defaults to 'UNKNOWN'")

    ctx_valid = ToolContext(task=None, parameters={"symbol": "TLKM"}, metadata={})
    check(tool.execute(ctx_valid).output["symbol"] == "TLKM", "T4: valid str symbol passed through unchanged")


# ---------------------------------------------------------------------------
# T5 -- headlines defaulting for missing/malformed input
# ---------------------------------------------------------------------------
def scenario_headlines_defaulting() -> None:
    tool = MarketNewsTool()

    for parameters in ({}, {"headlines": None}, {"headlines": 42}, {"headlines": {"a": 1}}, {"headlines": object()}):
        ctx = ToolContext(task=None, parameters=parameters, metadata={})
        result = tool.execute(ctx)
        check(result.output["headline_count"] == 0, f"T5: malformed headlines={parameters!r} yields headline_count == 0")
        check(result.output["headlines"] == (), f"T5: malformed headlines={parameters!r} yields empty headlines tuple")
        check(result.output["overall_sentiment"] == "neutral", f"T5: malformed headlines={parameters!r} yields 'neutral' overall_sentiment")
        check(result.output["sentiment_score"] == 0, f"T5: malformed headlines={parameters!r} yields sentiment_score == 0")


# ---------------------------------------------------------------------------
# T6 -- a bare string is treated as a single headline
# ---------------------------------------------------------------------------
def scenario_bare_string_headline() -> None:
    tool = MarketNewsTool()
    ctx = ToolContext(task=None, parameters={"headlines": "Profits surge to a record high"}, metadata={})
    result = tool.execute(ctx)
    check(result.output["headline_count"] == 1, "T6: a bare string headlines value counts as one headline")
    check(result.output["headlines"][0]["headline"] == "Profits surge to a record high", "T6: bare-string headline content preserved")
    check(result.output["headlines"][0]["sentiment"] == "positive", "T6: bare-string headline classified correctly")


# ---------------------------------------------------------------------------
# T7 -- never raises for any context shape
# ---------------------------------------------------------------------------
def scenario_never_raises() -> None:
    tool = MarketNewsTool()

    class _Parameterless:
        pass

    class _BadParameters:
        parameters = ["not", "a", "mapping"]

    contexts = [
        None,
        "not a real context",
        42,
        object(),
        {"parameters": {"symbol": "X"}},
        _Parameterless(),
        _BadParameters(),
        ToolContext(task=None, parameters={}, metadata={}),
        ToolContext(task="AAPL", parameters={"symbol": "AAPL", "headlines": ["ok"]}, metadata={}),
    ]
    for ctx in contexts:
        raised = False
        result = None
        try:
            result = tool.execute(ctx)
        except Exception:  # noqa: BLE001
            raised = True
        check(not raised, f"T7: execute() does not raise for context={ctx!r}")
        check(isinstance(result, ToolResult), f"T7: execute() returns a ToolResult for context={ctx!r}")


# ---------------------------------------------------------------------------
# T8 -- determinism across calls/instances
# ---------------------------------------------------------------------------
def scenario_determinism() -> None:
    ctx = ToolContext(
        task=None,
        parameters={"symbol": "BBRI", "headlines": ["Earnings beat expectations", "Layoffs announced amid slump"]},
        metadata={},
    )
    tool = MarketNewsTool()
    r1, r2 = tool.execute(ctx), tool.execute(ctx)
    check(r1 == r2, "T8: repeated calls on the same instance return equal ToolResults")

    tool_a, tool_b = MarketNewsTool(), MarketNewsTool()
    ra, rb = tool_a.execute(ctx), tool_b.execute(ctx)
    check(ra == rb, "T8: two independent instances given equal input return equal ToolResults")
    check(tool_a is not tool_b, "T8: the two instances are distinct objects")


# ---------------------------------------------------------------------------
# T9 -- ToolResult contract shape
# ---------------------------------------------------------------------------
def scenario_tool_result_contract_shape() -> None:
    tool = MarketNewsTool()
    ctx = ToolContext(task=None, parameters={"symbol": "X", "headlines": ["neutral news item today"]}, metadata={})
    result = tool.execute(ctx)

    check(result.success is True, "T9: success is True")
    check(result.error is None, "T9: error is None")
    check(dict(result.metadata) == {}, "T9: metadata is empty")
    check(isinstance(result.output, dict), "T9: output is a dict")
    check(
        set(result.output.keys())
        == {"symbol", "headline_count", "headlines", "overall_sentiment", "sentiment_score"},
        f"T9: output has exactly the five documented keys; got {set(result.output.keys())!r}",
    )
    entry = result.output["headlines"][0]
    check(
        set(entry.keys()) == {"headline", "sentiment", "positive_matches", "negative_matches"},
        f"T9: each per-headline entry has exactly the four documented keys; got {set(entry.keys())!r}",
    )


# ---------------------------------------------------------------------------
# T10 -- no forbidden import (AST-verified)
# ---------------------------------------------------------------------------
def scenario_no_forbidden_imports() -> None:
    import Orchestration.market_news_tool as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    allowed_roots = {"__future__", "typing", "Orchestration"}
    check(
        imported_roots <= allowed_roots,
        f"T10: only allowed top-level modules are imported; got {imported_roots!r}",
    )

    # Mentions of forbidden names in the module's own prose (docstrings
    # explaining what this Tool deliberately does NOT use) are expected
    # and fine -- what matters is that none of these names are ever
    # *referenced* as actual code (an import, a Name load, or an
    # Attribute access). Verified at the AST level, which never looks
    # inside docstring text.
    forbidden_symbols = (
        "requests", "httpx", "aiohttp", "feedparser", "bs4",
        "beautifulsoup4", "selenium", "playwright", "newspaper", "lxml",
        "pandas", "numpy", "sqlite3", "Repository", "Services",
        "Providers", "Database", "Planner", "Executor", "Workflow",
        "Runtime", "EventBus", "Memory", "LearningLoop", "Reflection",
        "CompositionRoot", "ToolRegistry", "ToolResolver", "ToolManager",
    )
    referenced_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    referenced_attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    referenced_imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            referenced_imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            referenced_imports.add(node.module)

    all_referenced = referenced_names | referenced_attrs | referenced_imports
    for symbol in forbidden_symbols:
        check(
            symbol not in all_referenced,
            f"T10: forbidden symbol {symbol!r} is never referenced as actual code (import/Name/Attribute)",
        )


# ---------------------------------------------------------------------------
# T11 -- no new class/abstraction introduced; public surface unchanged
# ---------------------------------------------------------------------------
def scenario_no_new_abstractions() -> None:
    import Orchestration.market_news_tool as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"MarketNewsTool"}, f"T11: module defines exactly one class; got {class_names!r}")

    public_members = {
        name
        for name in dir(MarketNewsTool)
        if not name.startswith("_")
        and (
            callable(vars(MarketNewsTool).get(name) or getattr(MarketNewsTool, name, None))
            or isinstance(vars(MarketNewsTool).get(name), property)
        )
    }
    check(
        public_members == {"name", "description", "execute"},
        f"T11: MarketNewsTool's public surface is still exactly name/description/execute; got {public_members!r}",
    )

    forbidden_names_on_module = ("Manager", "Registry", "Factory", "Adapter", "Resolver", "Orchestrator")
    module_names = {n for n in dir(module) if not n.startswith("_")}
    for forbidden in forbidden_names_on_module:
        check(
            not any(forbidden in name for name in module_names),
            f"T11: no module-level symbol containing {forbidden!r} (new abstraction)",
        )


# ---------------------------------------------------------------------------
# T12 -- name / description unchanged, still subclasses BaseTool
# ---------------------------------------------------------------------------
def scenario_name_description_and_subclass_unchanged() -> None:
    tool = MarketNewsTool()
    check(issubclass(MarketNewsTool, BaseTool), "T12: MarketNewsTool still subclasses BaseTool")
    check(tool.name == "market_news", "T12: name is still 'market_news'")
    check(tool.description == "Retrieve market news.", "T12: description is still 'Retrieve market news.'")


def main() -> int:
    scenarios = [
        scenario_basic_well_formed_call,
        scenario_headline_classification_correctness,
        scenario_aggregate_correctness,
        scenario_aggregate_tie_resolves_neutral,
        scenario_symbol_defaulting,
        scenario_headlines_defaulting,
        scenario_bare_string_headline,
        scenario_never_raises,
        scenario_determinism,
        scenario_tool_result_contract_shape,
        scenario_no_forbidden_imports,
        scenario_no_new_abstractions,
        scenario_name_description_and_subclass_unchanged,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 10 SPRINT 107 MARKET-NEWS-TOOL-EXECUTE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())