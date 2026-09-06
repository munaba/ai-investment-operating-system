"""Phase 9 Sprint 99 -- ``MarketPriceTool.execute()`` first real
implementation.

Scope: ``execute()`` no longer raises; it unconditionally returns the
literal, deterministic ``ToolResult(success=True, output={"symbol":
"UNKNOWN", "price": None}, error=None, metadata={})``. This suite
proves that behavior and the continued absence of everything Sprint
99 forbids (network, database, filesystem, Runtime/Workflow/AI/
Provider/Repository, cache, retry, logging, ``ToolContext``
mutation). Compact, table-driven, no-pytest style, mirroring
``Tests/test_stage_l89_market_price_tool_tool_result.py``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.market_price_tool import MarketPriceTool
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


# T1 -- basic return-shape invariants
def scenario_basic_shape() -> None:
    tool = MarketPriceTool()
    ctx = ToolContext(task=None, parameters={}, metadata={})
    r = tool.execute(ctx)

    check(isinstance(r, ToolResult), "T1: execute() returns a ToolResult")
    check(r.success is True, "T1: result.success is True")
    check(r.error is None, "T1: result.error is None")
    check(dict(r.metadata) == {}, "T1: result.metadata is empty")
    check(isinstance(r.output, dict), "T1: result.output is a dict")
    check("symbol" in r.output and "price" in r.output, "T1: output has symbol and price keys")
    check(r.output["symbol"] == "UNKNOWN", "T1: output['symbol'] == 'UNKNOWN'")
    check(r.output["price"] is None, "T1: output['price'] is None")
    check(set(r.output.keys()) == {"symbol", "price"}, "T1: output has exactly two keys")


# T2 -- never raises, for a variety of context inputs
def scenario_never_raises() -> None:
    tool = MarketPriceTool()
    contexts = [
        ToolContext(task=None, parameters={}, metadata={}),
        ToolContext(task="AAPL", parameters={"symbol": "AAPL"}, metadata={"x": 1}),
        None, "not a real context", object(), 42,
    ]
    for ctx in contexts:
        try:
            ok = isinstance(tool.execute(ctx), ToolResult)
        except Exception:  # noqa: BLE001
            ok = False
        check(ok, f"T2: execute() never raises, returns ToolResult for context={ctx!r}")


# T3 -- deterministic across repeated calls and across instances
def scenario_deterministic() -> None:
    tool = MarketPriceTool()
    ctx = ToolContext(task=None, parameters={}, metadata={})

    r1, r2 = tool.execute(ctx), tool.execute(ctx)
    check(r1 == r2, "T3: repeated calls on same instance return equal ToolResults")

    tool_a, tool_b = MarketPriceTool(), MarketPriceTool()
    ra, rb = tool_a.execute(ctx), tool_b.execute(ctx)
    check(ra == rb, "T3: two independent instances return equal ToolResults")
    check(tool_a is not tool_b, "T3: the two instances are distinct objects")

    r3 = tool.execute("a totally different context")
    check(r1.output == r3.output, "T3: output identical regardless of context value")


# T4 -- ToolContext is never mutated
def scenario_context_not_mutated() -> None:
    tool = MarketPriceTool()
    ctx = ToolContext(task="AAPL", parameters={"symbol": "AAPL"}, metadata={"note": "hi"})
    before = (ctx.task, dict(ctx.parameters), dict(ctx.metadata))

    tool.execute(ctx)

    after = (ctx.task, dict(ctx.parameters), dict(ctx.metadata))
    check(before == after, "T4: ToolContext (task/parameters/metadata) unchanged after execute()")


# T5 -- multiple instances independent, no shared mutable state
def scenario_instances_independent() -> None:
    tool_a, tool_b = MarketPriceTool(), MarketPriceTool()
    ctx = ToolContext(task=None, parameters={}, metadata={})

    ra, rb = tool_a.execute(ctx), tool_b.execute(ctx)
    check(ra.output is not rb.output, "T5: two calls produce independently-constructed output dicts")

    ra.output["price"] = 999  # mutate a prior result; must not leak into a fresh call
    rc = tool_a.execute(ctx)
    check(rc.output["price"] is None, "T5: mutating a prior result's output doesn't affect later calls")
    check(not hasattr(tool_a, "__dict__") or tool_a.__dict__ == {}, "T5: instance carries no instance attributes")


# T6 -- AST / source verification: execute()'s body and imports
def scenario_ast_verification() -> None:
    import Orchestration.market_price_tool as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "execute")
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(
        getattr(body[0], "value", None), ast.Constant
    ) and isinstance(body[0].value.value, str):
        body = body[1:]  # drop the docstring
    code_only = "\n".join(ast.get_source_segment(source, s) or "" for s in body)

    check("raise" not in code_only, "T6: execute()'s code body contains no raise statement")
    check(code_only.strip().startswith("return"), "T6: execute()'s code body is a single return statement")

    forbidden = (
        "requests", "httpx", "aiohttp", "urllib", "pandas", "numpy", "yfinance",
        "ccxt", "polygon", "alpaca", "finnhub", "binance", "sqlite3", "open(",
        "socket", "Provider", "Repository", "Runtime", "Workflow", "Executor",
        "Planner", "Registry", "Resolver", "ToolManager", "cache", "retry",
        "logging", "logger", "Composition",
    )
    check(
        not any(tok in code_only for tok in forbidden),
        f"T6: execute()'s code body references none of the forbidden tokens {forbidden!r}",
    )

    top_modules, names = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            top_modules.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            top_modules.add(n.module.split(".")[0])
            names.update(a.name for a in n.names)

    check(top_modules == {"__future__", "typing", "Orchestration"}, f"T6: top-level modules unchanged; got {top_modules!r}")
    check(names == {"annotations", "Any", "BaseTool", "ToolResult"}, f"T6: imported names unchanged; got {names!r}")


# T7 -- namespace verification
def scenario_namespace_verification() -> None:
    import Orchestration.market_price_tool as mod

    check(hasattr(mod, "ToolResult") and mod.ToolResult is ToolResult, "T7: mod.ToolResult is the real ToolResult")
    check(hasattr(mod, "MarketPriceTool"), "T7: module namespace exposes MarketPriceTool")
    check(
        not hasattr(mod, "requests") and not hasattr(mod, "yfinance") and not hasattr(mod, "pandas"),
        "T7: module namespace contains no forbidden data-provider modules",
    )


def main() -> int:
    scenarios = [
        scenario_basic_shape,
        scenario_never_raises,
        scenario_deterministic,
        scenario_context_not_mutated,
        scenario_instances_independent,
        scenario_ast_verification,
        scenario_namespace_verification,
    ]
    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            import traceback
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"PHASE 9 SPRINT 99 MARKET PRICE TOOL EXECUTE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())