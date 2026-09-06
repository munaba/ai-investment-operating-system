"""Phase 11 Sprint 128 proof suite -- PaperTradingSkill.

``PaperTradingSkill`` is the project's first simulated-execution
layer: it reads a list of already-validated orders (each carrying a
``"status"`` value, in the same shape
``OrderValidationSkill.execute()`` already produces) and attaches a
single, deterministic ``execution_status``/``message`` outcome to
every one, via one fixed, ordered rule chain --
APPROVED -> EXECUTED, HOLD -> PENDING, EXIT -> CLOSED, everything
else -> SKIPPED. This Skill never connects to a broker, places a
real order, or touches a network -- it only simulates.

Scope: dedicated proof suite for
``Orchestration.paper_trading_skill.PaperTradingSkill`` only. Mirrors
the compact, table-driven, no-pytest, global-counter-plus-``main()``
style already used by
``Tests/test_stage_l127_order_validation_skill.py``.

Invariant coverage:
    R1  -- APPROVED -> EXECUTED / "paper trade executed".
    R2  -- HOLD -> PENDING / "waiting for market confirmation".
    R3  -- EXIT -> CLOSED / "paper position closed".
    R4  -- REJECTED (and any other unrecognized status) -> SKIPPED /
           "order not executed".
    M1  -- a malformed (non-dict) order entry yields symbol=None,
           action=None, capital=None, execution_status=SKIPPED,
           never raising.
    M2  -- an entry missing "status"/"action"/"capital"/"symbol"
           keys behaves per the None-valued rule chain, never
           raising.
    E1  -- an empty "orders" list yields {"executions": []},
           success=True.
    E2  -- a missing "orders" key yields {"executions": []}, never
           raising.
    E3  -- a non-list "orders" value yields {"executions": []},
           never raising.
    E4  -- parameters that are not a Mapping at all never raises,
           yields {"executions": []}.
    S1  -- output shape: each execution entry has exactly the five
           keys symbol/action/capital/execution_status/message,
           nothing more.
    S2  -- symbol/action/capital on the output entry are the exact
           raw values read from input, never normalized.
    S3  -- SkillResult shape: success=True, error=None, metadata={},
           output={"executions": [...]}.
    S4  -- original input order is preserved.
    S5  -- the prompt's own worked examples for all four rules match
           exactly.
    D1  -- repeated execute() calls with the same input are
           deterministic (field-equal SkillResults).
    A1  -- AST: exactly one SkillResult(...) construction.
    A2  -- AST: no forbidden-name symbol (Engine, Manager, Strategy,
           Planner, Workflow, Coordinator, Factory, Registry, Helper,
           Simulator, Provider, Repository, Service) anywhere in the
           module namespace.
    A3  -- AST: the module defines exactly one class,
           PaperTradingSkill, subclassing BaseSkill only.
    A4  -- class shape: no __init__ defined on PaperTradingSkill
           itself; no instance state after construction.
    A5  -- AST: execute() defines no nested function/lambda.
    A6  -- AST: no execute_tool()/execute_tool_result() call anywhere
           in the module; PaperTradingSkill never calls a Tool;
           module never imports Tool machinery.
    A7  -- AST: no private (leading single-underscore, non-dunder)
           method, and no extra public method, defined on
           PaperTradingSkill beyond the three BaseSkill-required
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
from Orchestration.paper_trading_skill import PaperTradingSkill
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


class _FakeContext:
    """A minimal context-like object exposing only ``.parameters``,
    to prove PaperTradingSkill never touches any other attribute."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _order_entry(symbol: Any, action: Any, capital: Any, status: Any) -> dict:
    return {"symbol": symbol, "action": action, "capital": capital, "status": status}


def _run(orders: Any) -> SkillResult:
    skill = PaperTradingSkill()
    return skill.execute(_FakeContext({"orders": orders}))


# ---------------------------------------------------------------------------
# R1-R4 -- the four rules
# ---------------------------------------------------------------------------
def scenario_approved_is_executed() -> None:
    result = _run([_order_entry("BBCA", "BUY", 100_000_000, "APPROVED")])
    execution = result.output["executions"][0]
    check(execution["execution_status"] == "EXECUTED", f"R1: APPROVED -> EXECUTED; got {execution['execution_status']!r}")
    check(execution["message"] == "paper trade executed", f"R1: message -> 'paper trade executed'; got {execution['message']!r}")


def scenario_hold_is_pending() -> None:
    result = _run([_order_entry("BBCA", "WAIT", 0, "HOLD")])
    execution = result.output["executions"][0]
    check(execution["execution_status"] == "PENDING", f"R2: HOLD -> PENDING; got {execution['execution_status']!r}")
    check(execution["message"] == "waiting for market confirmation", f"R2: message -> 'waiting for market confirmation'; got {execution['message']!r}")


def scenario_exit_is_closed() -> None:
    result = _run([_order_entry("BBCA", "SELL", 50_000_000, "EXIT")])
    execution = result.output["executions"][0]
    check(execution["execution_status"] == "CLOSED", f"R3: EXIT -> CLOSED; got {execution['execution_status']!r}")
    check(execution["message"] == "paper position closed", f"R3: message -> 'paper position closed'; got {execution['message']!r}")


def scenario_rejected_and_unrecognized_status_is_skipped() -> None:
    for status in ("REJECTED", "approved", "CANCELLED", "", None):
        result = _run([_order_entry("XXX", "SHORT", 10, status)])
        execution = result.output["executions"][0]
        check(execution["execution_status"] == "SKIPPED", f"R4: status {status!r} -> SKIPPED; got {execution['execution_status']!r}")
        check(execution["message"] == "order not executed", f"R4: message -> 'order not executed'; got {execution['message']!r}")


# ---------------------------------------------------------------------------
# M1-M2 -- malformed entries
# ---------------------------------------------------------------------------
def scenario_malformed_entry_yields_skipped_never_raises() -> None:
    for entry in (None, "not-a-dict", 42, [1, 2, 3]):
        result = _run([entry])
        execution = result.output["executions"][0]
        check(execution["symbol"] is None, f"M1: malformed entry {entry!r} -> symbol=None; got {execution['symbol']!r}")
        check(execution["action"] is None, f"M1: malformed entry {entry!r} -> action=None; got {execution['action']!r}")
        check(execution["capital"] is None, f"M1: malformed entry {entry!r} -> capital=None; got {execution['capital']!r}")
        check(execution["execution_status"] == "SKIPPED", f"M1: malformed entry {entry!r} -> execution_status=SKIPPED; got {execution['execution_status']!r}")


def scenario_missing_fields_never_raise() -> None:
    result = _run([{}])
    execution = result.output["executions"][0]
    check(
        execution == {"symbol": None, "action": None, "capital": None, "execution_status": "SKIPPED", "message": "order not executed"},
        f"M2: empty entry dict -> all-None + SKIPPED; got {execution!r}",
    )

    result = _run([{"symbol": "BBCA", "action": "BUY", "capital": 100_000_000}])
    execution = result.output["executions"][0]
    check(execution["execution_status"] == "SKIPPED", f"M2: missing 'status' key -> SKIPPED; got {execution['execution_status']!r}")

    result = _run([{"status": "APPROVED"}])
    execution = result.output["executions"][0]
    check(execution["symbol"] is None, "M2: missing 'symbol' key -> symbol=None")
    check(execution["action"] is None, "M2: missing 'action' key -> action=None")
    check(execution["capital"] is None, "M2: missing 'capital' key -> capital=None")
    check(execution["execution_status"] == "EXECUTED", f"M2: status=APPROVED with missing other fields -> EXECUTED; got {execution['execution_status']!r}")


# ---------------------------------------------------------------------------
# E1-E4 -- empty/missing/malformed input
# ---------------------------------------------------------------------------
def scenario_empty_orders_list() -> None:
    result = _run([])
    check(result.output == {"executions": []}, f"E1: empty orders -> {{'executions': []}}; got {result.output!r}")
    check(result.success is True, "E1: success=True for empty orders")


def scenario_missing_orders_key_never_raises() -> None:
    skill = PaperTradingSkill()
    result = skill.execute(_FakeContext({}))
    check(result.output == {"executions": []}, f"E2: missing 'orders' key -> {{'executions': []}}; got {result.output!r}")


def scenario_non_list_orders_never_raises() -> None:
    skill = PaperTradingSkill()
    for bad_orders in (None, "not-a-list", 42, {"a": 1}):
        result = skill.execute(_FakeContext({"orders": bad_orders}))
        check(result.output == {"executions": []}, f"E3: non-list orders {bad_orders!r} -> {{'executions': []}}; got {result.output!r}")


def scenario_non_mapping_parameters_never_raises() -> None:
    skill = PaperTradingSkill()
    for bad_parameters in (None, "not-a-mapping", 42, ["a", "list"]):
        result = skill.execute(_FakeContext(bad_parameters))
        check(result.output == {"executions": []}, f"E4: non-Mapping parameters {bad_parameters!r} -> {{'executions': []}}; got {result.output!r}")
        check(result.success is True, f"E4: success=True for non-Mapping parameters {bad_parameters!r}")


# ---------------------------------------------------------------------------
# S1-S5 -- output shape
# ---------------------------------------------------------------------------
def scenario_execution_entry_has_exactly_five_keys() -> None:
    result = _run([_order_entry("BBCA", "BUY", 100_000_000, "APPROVED")])
    execution = result.output["executions"][0]
    check(set(execution.keys()) == {"symbol", "action", "capital", "execution_status", "message"}, f"S1: exactly five keys; got {set(execution.keys())!r}")


def scenario_fields_are_raw_not_normalized() -> None:
    result = _run([_order_entry("bbca", "buy", 100_000_000, "approved")])
    execution = result.output["executions"][0]
    check(execution["symbol"] == "bbca", f"S2: symbol reported back unchanged; got {execution['symbol']!r}")
    check(execution["action"] == "buy", f"S2: action reported back unchanged (not normalized); got {execution['action']!r}")
    check(execution["execution_status"] == "SKIPPED", "S2: lowercase 'approved' does not match Rule 1's exact 'APPROVED' -> SKIPPED")


def scenario_skill_result_shape() -> None:
    result = _run([_order_entry("BBCA", "BUY", 1, "APPROVED")])
    check(result.success is True, "S3: success=True")
    check(result.error is None, "S3: error=None")
    check(dict(result.metadata) == {}, f"S3: metadata={{}}; got {dict(result.metadata)!r}")
    check(isinstance(result.output, dict) and "executions" in result.output, "S3: output is a dict with an 'executions' key")


def scenario_original_input_order_preserved() -> None:
    orders = [
        _order_entry("AAA", "BUY", 100, "APPROVED"),
        _order_entry("BBB", "WAIT", 0, "HOLD"),
        _order_entry("CCC", "SELL", 50, "EXIT"),
        _order_entry("DDD", "SHORT", 10, "REJECTED"),
    ]
    result = _run(orders)
    symbols = [e["symbol"] for e in result.output["executions"]]
    check(symbols == ["AAA", "BBB", "CCC", "DDD"], f"S4: original order preserved; got {symbols!r}")


def scenario_prompt_worked_examples_match_exactly() -> None:
    cases = [
        (_order_entry("BBCA", "BUY", 100_000_000, "APPROVED"), "EXECUTED", "paper trade executed"),
        (_order_entry("BBCA", "WAIT", 0, "HOLD"), "PENDING", "waiting for market confirmation"),
        (_order_entry("BBCA", "SELL", 100_000_000, "EXIT"), "CLOSED", "paper position closed"),
        (_order_entry("BBCA", "SHORT", 100_000_000, "REJECTED"), "SKIPPED", "order not executed"),
    ]
    for entry, expected_execution_status, expected_message in cases:
        result = _run([entry])
        execution = result.output["executions"][0]
        check(execution["execution_status"] == expected_execution_status, f"S5: {entry['status']!r} -> {expected_execution_status}; got {execution['execution_status']!r}")
        check(execution["message"] == expected_message, f"S5: {entry['status']!r} message -> {expected_message!r}; got {execution['message']!r}")


# ---------------------------------------------------------------------------
# D1 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    orders = [
        _order_entry("AAA", "BUY", 100, "APPROVED"),
        _order_entry("BBB", "WAIT", 0, "HOLD"),
        _order_entry("CCC", "SELL", 50, "EXIT"),
        _order_entry(None, None, None, None),
    ]
    first = _run(orders)
    second = _run(orders)
    check(first == second, f"D1: repeated execute() calls are deterministic; got {first!r} vs {second!r}")


# ---------------------------------------------------------------------------
# A1-A7 -- AST / structural verification
# ---------------------------------------------------------------------------
def scenario_exactly_one_skill_result_construction() -> None:
    import Orchestration.paper_trading_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")


def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.paper_trading_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_fragments = (
        "Engine", "Manager", "Strategy", "Planner", "Workflow",
        "Coordinator", "Factory", "Registry", "Helper", "Simulator",
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
    check(class_names == {"PaperTradingSkill"}, f"A3: module defines exactly one class; got {class_names!r}")


def scenario_class_subclasses_base_skill_only() -> None:
    check(issubclass(PaperTradingSkill, BaseSkill), "A3: PaperTradingSkill subclasses BaseSkill")
    check(PaperTradingSkill.__bases__ == (BaseSkill,), f"A3: PaperTradingSkill has exactly one base class, BaseSkill; got {PaperTradingSkill.__bases__!r}")


def scenario_no_init_no_instance_state() -> None:
    check("__init__" not in PaperTradingSkill.__dict__, "A4: PaperTradingSkill defines no __init__ of its own")
    skill = PaperTradingSkill()
    check(skill.__dict__ == {}, f"A4: PaperTradingSkill instances carry no instance state; got {skill.__dict__!r}")


def scenario_execute_has_no_nested_function() -> None:
    source = inspect.getsource(PaperTradingSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A5: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")


def scenario_no_tool_calls_anywhere() -> None:
    import Orchestration.paper_trading_skill as module

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
        "Orchestration.trading_decision_agent", "Orchestration.executor",
        "ToolResolver", "ToolRegistry", "ToolContext",
        "requests", "websocket", "asyncio", "threading",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"A6: module never imports {forbidden!r}")


def scenario_no_extra_public_or_private_methods() -> None:
    required_members = {"name", "description", "execute"}
    for attr_name, attr_value in PaperTradingSkill.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A7: no additional method/property defined on PaperTradingSkill beyond name/description/execute; found {attr_name!r}",
        )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_approved_is_executed,
        scenario_hold_is_pending,
        scenario_exit_is_closed,
        scenario_rejected_and_unrecognized_status_is_skipped,
        scenario_malformed_entry_yields_skipped_never_raises,
        scenario_missing_fields_never_raise,
        scenario_empty_orders_list,
        scenario_missing_orders_key_never_raises,
        scenario_non_list_orders_never_raises,
        scenario_non_mapping_parameters_never_raises,
        scenario_execution_entry_has_exactly_five_keys,
        scenario_fields_are_raw_not_normalized,
        scenario_skill_result_shape,
        scenario_original_input_order_preserved,
        scenario_prompt_worked_examples_match_exactly,
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