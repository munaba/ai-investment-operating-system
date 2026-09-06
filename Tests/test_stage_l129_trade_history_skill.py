"""Phase 11 Sprint 129 proof suite -- TradeHistorySkill.

``TradeHistorySkill`` is the project's first execution-history
formatter: it reads a list of already-produced paper-trade execution
entries (each carrying ``"symbol"``/``"action"``/``"capital"``/
``"execution_status"``/``"message"`` values, in the same shape
``PaperTradingSkill.execute()`` already produces, Phase 11 Sprint
128) and copies every entry, unchanged and in order, into a
``{"history": [...]}`` output. This Skill never writes to a
database, never persists anything to disk, and never touches a
network -- it only formats.

Scope: dedicated proof suite for
``Orchestration.trade_history_skill.TradeHistorySkill`` only. Mirrors
the compact, table-driven, no-pytest, global-counter-plus-``main()``
style already used by
``Tests/test_stage_l128_paper_trading_skill.py``.

Invariant coverage:
    N1  -- a normal execution entry is copied through exactly,
           preserving every field's raw value.
    N2  -- multiple entries are all copied through, each exactly.
    M1  -- a malformed (non-dict) execution entry yields symbol=None,
           action=None, capital=None, execution_status=None,
           message=None, never raising.
    M2  -- an entry missing one or more keys yields None for those
           missing fields, never raising.
    E1  -- an empty "executions" list yields {"history": []},
           success=True.
    E2  -- a missing "executions" key yields {"history": []}, never
           raising.
    E3  -- a non-list "executions" value yields {"history": []},
           never raising.
    E4  -- parameters that are not a Mapping at all never raises,
           yields {"history": []}.
    S1  -- output shape: each history entry has exactly the five
           keys symbol/action/capital/execution_status/message,
           nothing more.
    S2  -- values on the output entry are the exact raw values read
           from input, never normalized or transformed.
    S3  -- SkillResult shape: success=True, error=None, metadata={},
           output={"history": [...]}.
    S4  -- original input order is preserved.
    D1  -- repeated execute() calls with the same input are
           deterministic (field-equal SkillResults).
    A1  -- AST: exactly one SkillResult(...) construction.
    A2  -- AST: no forbidden-name symbol (Engine, Manager, Strategy,
           Planner, Workflow, Coordinator, Factory, Registry, Helper,
           Provider, Repository, Service) anywhere in the module
           namespace.
    A3  -- AST: the module defines exactly one class,
           TradeHistorySkill, subclassing BaseSkill only.
    A4  -- class shape: no __init__ defined on TradeHistorySkill
           itself; no instance state after construction.
    A5  -- AST: execute() defines no nested function/lambda.
    A6  -- AST: no execute_tool()/execute_tool_result() call anywhere
           in the module; TradeHistorySkill never calls a Tool;
           module never imports Tool machinery.
    A7  -- AST: no private (leading single-underscore, non-dunder)
           method, and no extra public method, defined on
           TradeHistorySkill beyond the three BaseSkill-required
           members.
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

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult
from Orchestration.trade_history_skill import TradeHistorySkill

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


class _FakeContext:
    """A minimal context-like object exposing only ``.parameters``,
    to prove TradeHistorySkill never touches any other attribute."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _execution_entry(symbol: Any, action: Any, capital: Any, execution_status: Any, message: Any) -> dict:
    return {
        "symbol": symbol,
        "action": action,
        "capital": capital,
        "execution_status": execution_status,
        "message": message,
    }


def _run(executions: Any) -> SkillResult:
    skill = TradeHistorySkill()
    return skill.execute(_FakeContext({"executions": executions}))


# ---------------------------------------------------------------------------
# N1-N2 -- normal history
# ---------------------------------------------------------------------------
def scenario_normal_entry_copied_exactly() -> None:
    entry = _execution_entry("BBCA", "BUY", 100_000_000, "EXECUTED", "paper trade executed")
    result = _run([entry])
    history_entry = result.output["history"][0]
    check(history_entry == entry, f"N1: normal entry copied exactly; got {history_entry!r}")


def scenario_multiple_entries_all_copied() -> None:
    entries = [
        _execution_entry("AAA", "BUY", 100, "EXECUTED", "paper trade executed"),
        _execution_entry("BBB", "WAIT", 0, "PENDING", "waiting for market confirmation"),
        _execution_entry("CCC", "SELL", 50, "CLOSED", "paper position closed"),
        _execution_entry("DDD", "SHORT", 10, "SKIPPED", "order not executed"),
    ]
    result = _run(entries)
    check(result.output["history"] == entries, f"N2: all entries copied exactly; got {result.output['history']!r}")


# ---------------------------------------------------------------------------
# M1-M2 -- malformed entries
# ---------------------------------------------------------------------------
def scenario_malformed_entry_yields_safe_default_never_raises() -> None:
    for entry in (None, "not-a-dict", 42, [1, 2, 3]):
        result = _run([entry])
        history_entry = result.output["history"][0]
        check(
            history_entry == {"symbol": None, "action": None, "capital": None, "execution_status": None, "message": None},
            f"M1: malformed entry {entry!r} -> safe default entry; got {history_entry!r}",
        )


def scenario_missing_fields_never_raise() -> None:
    result = _run([{}])
    history_entry = result.output["history"][0]
    check(
        history_entry == {"symbol": None, "action": None, "capital": None, "execution_status": None, "message": None},
        f"M2: empty entry dict -> all-None entry; got {history_entry!r}",
    )

    result = _run([{"symbol": "BBCA", "action": "BUY"}])
    history_entry = result.output["history"][0]
    check(history_entry["symbol"] == "BBCA", "M2: present 'symbol' key preserved")
    check(history_entry["action"] == "BUY", "M2: present 'action' key preserved")
    check(history_entry["capital"] is None, "M2: missing 'capital' key -> None")
    check(history_entry["execution_status"] is None, "M2: missing 'execution_status' key -> None")
    check(history_entry["message"] is None, "M2: missing 'message' key -> None")


# ---------------------------------------------------------------------------
# E1-E4 -- empty/missing/malformed input
# ---------------------------------------------------------------------------
def scenario_empty_executions_list() -> None:
    result = _run([])
    check(result.output == {"history": []}, f"E1: empty executions -> {{'history': []}}; got {result.output!r}")
    check(result.success is True, "E1: success=True for empty executions")


def scenario_missing_executions_key_never_raises() -> None:
    skill = TradeHistorySkill()
    result = skill.execute(_FakeContext({}))
    check(result.output == {"history": []}, f"E2: missing 'executions' key -> {{'history': []}}; got {result.output!r}")


def scenario_non_list_executions_never_raises() -> None:
    skill = TradeHistorySkill()
    for bad_executions in (None, "not-a-list", 42, {"a": 1}):
        result = skill.execute(_FakeContext({"executions": bad_executions}))
        check(result.output == {"history": []}, f"E3: non-list executions {bad_executions!r} -> {{'history': []}}; got {result.output!r}")


def scenario_non_mapping_parameters_never_raises() -> None:
    skill = TradeHistorySkill()
    for bad_parameters in (None, "not-a-mapping", 42, ["a", "list"]):
        result = skill.execute(_FakeContext(bad_parameters))
        check(result.output == {"history": []}, f"E4: non-Mapping parameters {bad_parameters!r} -> {{'history': []}}; got {result.output!r}")
        check(result.success is True, f"E4: success=True for non-Mapping parameters {bad_parameters!r}")


# ---------------------------------------------------------------------------
# S1-S4 -- output shape
# ---------------------------------------------------------------------------
def scenario_history_entry_has_exactly_five_keys() -> None:
    result = _run([_execution_entry("BBCA", "BUY", 100_000_000, "EXECUTED", "paper trade executed")])
    history_entry = result.output["history"][0]
    check(
        set(history_entry.keys()) == {"symbol", "action", "capital", "execution_status", "message"},
        f"S1: exactly five keys; got {set(history_entry.keys())!r}",
    )


def scenario_values_are_raw_not_normalized() -> None:
    entry = _execution_entry("bbca", "buy", 100_000_000, "executed", "Paper Trade Executed")
    result = _run([entry])
    history_entry = result.output["history"][0]
    check(history_entry["symbol"] == "bbca", f"S2: symbol unchanged; got {history_entry['symbol']!r}")
    check(history_entry["action"] == "buy", f"S2: action unchanged; got {history_entry['action']!r}")
    check(history_entry["execution_status"] == "executed", f"S2: execution_status unchanged; got {history_entry['execution_status']!r}")
    check(history_entry["message"] == "Paper Trade Executed", f"S2: message unchanged; got {history_entry['message']!r}")


def scenario_skill_result_shape() -> None:
    result = _run([_execution_entry("BBCA", "BUY", 1, "EXECUTED", "paper trade executed")])
    check(result.success is True, "S3: success=True")
    check(result.error is None, "S3: error=None")
    check(dict(result.metadata) == {}, f"S3: metadata={{}}; got {dict(result.metadata)!r}")
    check(isinstance(result.output, dict) and "history" in result.output, "S3: output is a dict with a 'history' key")


def scenario_original_input_order_preserved() -> None:
    entries = [
        _execution_entry("AAA", "BUY", 100, "EXECUTED", "paper trade executed"),
        _execution_entry("BBB", "WAIT", 0, "PENDING", "waiting for market confirmation"),
        _execution_entry("CCC", "SELL", 50, "CLOSED", "paper position closed"),
        _execution_entry("DDD", "SHORT", 10, "SKIPPED", "order not executed"),
    ]
    result = _run(entries)
    symbols = [e["symbol"] for e in result.output["history"]]
    check(symbols == ["AAA", "BBB", "CCC", "DDD"], f"S4: original order preserved; got {symbols!r}")


# ---------------------------------------------------------------------------
# D1 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    entries = [
        _execution_entry("AAA", "BUY", 100, "EXECUTED", "paper trade executed"),
        _execution_entry("BBB", "WAIT", 0, "PENDING", "waiting for market confirmation"),
        _execution_entry(None, None, None, None, None),
    ]
    first = _run(entries)
    second = _run(entries)
    check(first == second, f"D1: repeated execute() calls are deterministic; got {first!r} vs {second!r}")


# ---------------------------------------------------------------------------
# A1-A7 -- AST / structural verification
# ---------------------------------------------------------------------------
def scenario_exactly_one_skill_result_construction() -> None:
    import Orchestration.trade_history_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")


def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.trade_history_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_fragments = (
        "Engine", "Manager", "Strategy", "Planner", "Workflow",
        "Coordinator", "Factory", "Registry", "Helper",
        "Provider", "Repository", "Service",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A2: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )

    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = {n.name for n in class_defs}
    check(class_names == {"TradeHistorySkill"}, f"A3: module defines exactly one class; got {class_names!r}")


def scenario_class_subclasses_base_skill_only() -> None:
    check(issubclass(TradeHistorySkill, BaseSkill), "A3: TradeHistorySkill subclasses BaseSkill")
    check(TradeHistorySkill.__bases__ == (BaseSkill,), f"A3: TradeHistorySkill has exactly one base class, BaseSkill; got {TradeHistorySkill.__bases__!r}")


def scenario_no_init_no_instance_state() -> None:
    check("__init__" not in TradeHistorySkill.__dict__, "A4: TradeHistorySkill defines no __init__ of its own")
    skill = TradeHistorySkill()
    check(skill.__dict__ == {}, f"A4: TradeHistorySkill instances carry no instance state; got {skill.__dict__!r}")


def scenario_execute_has_no_nested_function() -> None:
    source = inspect.getsource(TradeHistorySkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A5: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")


def scenario_no_tool_calls_anywhere() -> None:
    import Orchestration.trade_history_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    forbidden_tool_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr in ("execute_tool", "execute_tool_result")
    ]
    check(len(forbidden_tool_calls) == 0, f"A6: module never calls execute_tool()/execute_tool_result(); got {len(forbidden_tool_calls)}")

    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.add(node.module or "")
            for alias in node.names:
                imported_names.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name)
    forbidden_imports = (
        "Orchestration.tool_resolver", "Orchestration.tool_registry",
        "Orchestration.tool_context", "Orchestration.base_tool",
        "Orchestration.market_price_tool", "Orchestration.market_news_tool",
        "Orchestration.market_fundamental_tool", "Orchestration.text_analysis_skill",
        "Orchestration.market_analysis_skill", "Orchestration.market_analysis_agent",
        "Orchestration.recommendation_skill", "Orchestration.position_risk_skill",
        "Orchestration.trade_plan_skill", "Orchestration.position_sizing_skill",
        "Orchestration.capital_allocation_skill", "Orchestration.order_validation_skill",
        "Orchestration.paper_trading_skill", "Orchestration.trading_decision_agent",
        "Orchestration.executor",
        "ToolResolver", "ToolRegistry", "ToolContext",
        "requests", "websocket", "asyncio", "threading",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"A6: module never imports {forbidden!r}")


def scenario_no_extra_public_or_private_methods() -> None:
    required_members = {"name", "description", "execute"}
    for attr_name, attr_value in TradeHistorySkill.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A7: no additional method/property defined on TradeHistorySkill beyond name/description/execute; found {attr_name!r}",
        )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_normal_entry_copied_exactly,
        scenario_multiple_entries_all_copied,
        scenario_malformed_entry_yields_safe_default_never_raises,
        scenario_missing_fields_never_raise,
        scenario_empty_executions_list,
        scenario_missing_executions_key_never_raises,
        scenario_non_list_executions_never_raises,
        scenario_non_mapping_parameters_never_raises,
        scenario_history_entry_has_exactly_five_keys,
        scenario_values_are_raw_not_normalized,
        scenario_skill_result_shape,
        scenario_original_input_order_preserved,
        scenario_repeated_execution_is_deterministic,
        scenario_exactly_one_skill_result_construction,
        scenario_no_forbidden_abstractions,
        scenario_class_subclasses_base_skill_only,
        scenario_no_init_no_instance_state,
        scenario_execute_has_no_nested_function,
        scenario_no_tool_calls_anywhere,
        scenario_no_extra_public_or_private_methods,
    ]

    for scenario in scenarios:
        print(f"\n{scenario.__name__}")
        scenario()

    print(f"\n{'=' * 70}")
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())