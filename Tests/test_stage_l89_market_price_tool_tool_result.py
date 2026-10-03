"""Phase 8 Sprint 89 -- ``MarketPriceTool.execute()`` ``ToolResult``
contract.

Scope: return annotation (``Any`` -> ``ToolResult``) + docstring on
``execute()``, plus the one new import that annotation requires.
``execute()`` stays exactly as before: no return statement, still
unconditionally raises ``NotImplementedError``. ``name``/
``description`` untouched. No constructor, attribute, helper, or
class variable added. Compact, table-driven, no-pytest style,
mirroring ``Tests/test_stage_l88_base_skill_skill_result.py``.
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.base_tool import BaseTool
from Orchestration.market_price_tool import MarketPriceTool
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


# T1 -- execute()'s return annotation is ToolResult
def scenario_return_annotation() -> None:
    ann = inspect.signature(MarketPriceTool.execute).return_annotation
    ok = ann == "ToolResult" or ann is ToolResult
    check(ok, f"T1: execute()'s return annotation refers to ToolResult; got {ann!r}")

    doc = MarketPriceTool.execute.__doc__ or ""
    check("ToolResult" in doc, "T1: execute()'s docstring mentions ToolResult")

    params = inspect.signature(MarketPriceTool.execute).parameters
    check(list(params) == ["self", "context"], "T1: parameter list unchanged (self, context)")
    ctx_ann = params["context"].annotation
    check(ctx_ann in ("Any", Any), "T1: parameter 'context' annotation unchanged (Any)")
    check(
        not getattr(MarketPriceTool.execute, "__isabstractmethod__", False),
        "T1: execute() remains a concrete (non-abstract) method on MarketPriceTool",
    )


# T2 -- execute() still raises NotImplementedError unconditionally, no return
def scenario_execute_still_raises() -> None:
    tool = MarketPriceTool()
    raised = False
    try:
        tool.execute("some context")
    except NotImplementedError:
        raised = True
    check(raised, "T2: execute() still raises NotImplementedError")

    raised2 = False
    try:
        tool.execute(None)
    except NotImplementedError:
        raised2 = True
    check(raised2, "T2: execute() raises NotImplementedError regardless of context value")

    raised3 = False
    try:
        MarketPriceTool.execute(tool, object())
    except NotImplementedError:
        raised3 = True
    check(raised3, "T2: calling execute() unbound still raises NotImplementedError")


# T3 -- name / description unchanged
def scenario_name_and_description_unchanged() -> None:
    tool = MarketPriceTool()
    check(tool.name == "market_price", "T3: name is still the literal string 'market_price'")
    check(
        tool.description == "Retrieve market price information.",
        "T3: description is still the literal string 'Retrieve market price information.'",
    )
    check(isinstance(type(MarketPriceTool.name), type(property)), "T3: 'name' is still a property")
    check(isinstance(type(MarketPriceTool.description), type(property)), "T3: 'description' is still a property")
    check(
        not getattr(MarketPriceTool.name.fget, "__isabstractmethod__", False),
        "T3: 'name' is concrete (not abstract) on MarketPriceTool",
    )
    check(
        not getattr(MarketPriceTool.description.fget, "__isabstractmethod__", False),
        "T3: 'description' is concrete (not abstract) on MarketPriceTool",
    )


# T4 -- no constructor, no attributes, no helpers, no class variables
def scenario_no_constructor_no_helpers() -> None:
    check("__init__" not in vars(MarketPriceTool), "T4: MarketPriceTool still defines no __init__ of its own")

    tool = MarketPriceTool()
    check(not hasattr(tool, "__dict__") or tool.__dict__ == {}, "T4: instance carries no instance attributes")

    public_members = {
        n for n in dir(MarketPriceTool)
        if not n.startswith("_")
        and (callable(vars(MarketPriceTool).get(n) or getattr(MarketPriceTool, n, None))
             or isinstance(vars(MarketPriceTool).get(n), property))
    }
    check(
        public_members == {"name", "description", "execute"},
        f"T4: public surface unchanged -- exactly name/description/execute; got {public_members!r}",
    )

    forbidden_methods = (
        "fetch", "download", "request", "query", "history", "latest",
        "price", "ohlcv", "candles", "ticker", "quote", "stream",
        "subscribe", "connect", "disconnect", "refresh", "update",
        "reset", "validate", "build", "prepare", "cache", "retry",
    )
    check(
        not any(hasattr(MarketPriceTool, m) for m in forbidden_methods),
        f"T4: MarketPriceTool has none of the forbidden methods {forbidden_methods!r}",
    )

    check(
        not any(
            k for k in vars(MarketPriceTool)
            if not k.startswith("__") and k not in ("name", "description", "execute", "_abc_impl")
        ),
        "T4: no additional class variable was added to MarketPriceTool",
    )


# T5 -- MarketPriceTool still subclasses BaseTool, instantiable
def scenario_subclass_and_instantiation() -> None:
    check(issubclass(MarketPriceTool, BaseTool), "T5: MarketPriceTool still subclasses BaseTool")
    try:
        MarketPriceTool()
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    check(ok, "T5: MarketPriceTool is still freely instantiable (all abstract members satisfied)")

    tool_a, tool_b = MarketPriceTool(), MarketPriceTool()
    check(tool_a is not tool_b, "T5: two MarketPriceTool() instances are distinct objects")
    check(tool_a.name == tool_b.name == "market_price", "T5: both instances report the same stable name")


# T6 -- AST verification: exactly the expected import set, source-level checks
def scenario_ast_verification() -> None:
    import Orchestration.market_price_tool as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    top_modules, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            top_modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_modules.add(node.module.split(".")[0])
            names.update(a.name for a in node.names)

    check(
        top_modules == {"__future__", "typing", "Orchestration"},
        f"T6: top-level imported modules exactly as expected; got {top_modules!r}",
    )
    check(
        names == {"annotations", "Any", "BaseTool", "ToolResult"},
        f"T6: imported names exactly as expected; got {names!r}",
    )

    imported_tokens = top_modules | names
    data_provider_tokens = (
        "yfinance", "requests", "httpx", "aiohttp", "urllib", "pandas",
        "numpy", "ccxt", "polygon", "alpaca", "finnhub", "binance",
        "sqlite3",
    )
    architecture_tokens = (
        "Provider", "Repository", "Service", "Runtime", "Workflow",
        "Executor", "Planner", "Registry", "Resolver", "ToolManager",
    )
    check(
        not any(any(tok in t for t in imported_tokens) for tok in data_provider_tokens),
        f"T6: no import statement references any data-provider token {data_provider_tokens!r}",
    )
    check(
        not any(any(tok in t for t in imported_tokens) for tok in architecture_tokens),
        f"T6: no import statement references any architecture token {architecture_tokens!r}",
    )

    operational_tokens = ("isinstance(", "logging", "logger", "retry")
    check(
        not any(tok in source for tok in operational_tokens),
        f"T6: source contains none of the forbidden operational tokens {operational_tokens!r}",
    )

    # Isolate execute()'s code (excluding its docstring) so token checks test behavior, not wording.
    execute_node = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "execute"
    )
    body_stmts = execute_node.body
    if body_stmts and isinstance(body_stmts[0], ast.Expr) and isinstance(
        getattr(body_stmts[0], "value", None), ast.Constant
    ) and isinstance(body_stmts[0].value.value, str):
        body_stmts = body_stmts[1:]  # drop the docstring statement
    code_only = "\n".join(
        ast.get_source_segment(source, stmt) or "" for stmt in body_stmts
    )
    check(
        code_only.strip() == "raise NotImplementedError",
        f"T6: execute()'s code body is exactly 'raise NotImplementedError'; got {code_only!r}",
    )
    check("return" not in code_only, "T6: execute()'s code body contains no return statement")

    # name/description bodies unchanged
    for method_name, expected_return in (("name", '"market_price"'), ("description", None)):
        node = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == method_name
        )
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(
            getattr(body[0], "value", None), ast.Constant
        ) and isinstance(body[0].value.value, str):
            body = body[1:]
        seg = "\n".join(ast.get_source_segment(source, s) or "" for s in body)
        check(seg.strip().startswith("return"), f"T6: {method_name}()'s code body is a single return statement")


# T7 -- namespace verification
def scenario_namespace_verification() -> None:
    import Orchestration.market_price_tool as mod

    check(hasattr(mod, "ToolResult"), "T7: module namespace exposes the new ToolResult import")
    check(mod.ToolResult is ToolResult, "T7: mod.ToolResult is the same object as Orchestration.tool_result.ToolResult")
    check(hasattr(mod, "BaseTool"), "T7: module namespace still exposes BaseTool")
    check(mod.BaseTool is BaseTool, "T7: mod.BaseTool is the same object as Orchestration.base_tool.BaseTool")
    check(hasattr(mod, "MarketPriceTool"), "T7: module namespace exposes MarketPriceTool")


def main() -> int:
    scenarios = [
        scenario_return_annotation,
        scenario_execute_still_raises,
        scenario_name_and_description_unchanged,
        scenario_no_constructor_no_helpers,
        scenario_subclass_and_instantiation,
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
    print(f"PHASE 8 SPRINT 89 MARKET PRICE TOOL TOOL RESULT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())