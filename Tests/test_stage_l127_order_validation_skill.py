"""Phase 11 Sprint 127 proof suite -- OrderValidationSkill.

``OrderValidationSkill`` is the project's first order-validation
layer: it reads a list of already-allocated entries (each carrying
``"action"`` and ``"capital"`` values, in the same shape
``CapitalAllocationSkill.execute()`` already produces) and attaches a
single, deterministic ``status``/``reason`` verdict to every one, via
one fixed, ordered rule chain -- BUY+capital>0 -> APPROVED,
WAIT -> HOLD, SELL -> EXIT, everything else -> REJECTED. This Skill
never executes an order -- it only validates.

Scope: dedicated proof suite for
``Orchestration.order_validation_skill.OrderValidationSkill`` only.
Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l125_capital_allocation_skill.py``.

Invariant coverage:
    R1  -- BUY with positive capital -> APPROVED / "ready for execution".
    R2  -- WAIT -> HOLD / "waiting for better opportunity".
    R3  -- SELL -> EXIT / "exit position".
    R4  -- unrecognized action -> REJECTED / "invalid order".
    R5  -- BUY with capital == 0 -> REJECTED (Rule 1 fails, falls to
           Rule 4, not Rule 2/3).
    R6  -- BUY with negative capital -> REJECTED.
    R7  -- BUY with non-numeric capital (str/None/bool) -> REJECTED.
    M1  -- a malformed (non-dict) allocation entry yields
           symbol=None, action=None, capital=None, status=REJECTED,
           never raising.
    M2  -- an entry missing "action"/"capital"/"symbol" keys behaves
           per the None-valued rule chain, never raising.
    E1  -- an empty "allocations" list yields {"orders": []},
           success=True.
    E2  -- a missing "allocations" key yields {"orders": []}, never
           raising.
    E3  -- a non-list "allocations" value yields {"orders": []},
           never raising.
    E4  -- parameters that are not a Mapping at all never raises.
    S1  -- output shape: each order entry has exactly the five keys
           symbol/action/capital/status/reason, nothing more.
    S2  -- symbol/action/capital on the output entry are the exact
           raw values read from input, never normalized.
    S3  -- SkillResult shape: success=True, error=None, metadata={},
           output={"orders": [...]}.
    S4  -- original input order is preserved.
    S5  -- the prompt's own worked examples for all four rules match
           exactly.
    D1  -- repeated execute() calls with the same input are
           deterministic (field-equal SkillResults).
    A1  -- AST: exactly one SkillResult(...) construction.
    A2  -- AST: no forbidden-name symbol (Engine, Manager, Strategy,
           Planner, Workflow, Coordinator, Factory, Registry, Helper,
           Validator, Provider, Repository, Service) anywhere in the
           module namespace.
    A3  -- AST: the module defines exactly one class,
           OrderValidationSkill, subclassing BaseSkill only.
    A4  -- class shape: no __init__ defined on OrderValidationSkill
           itself; no instance state after construction.
    A5  -- AST: execute() defines no nested function/lambda.
    A6  -- AST: no execute_tool()/execute_tool_result() call anywhere
           in the module; OrderValidationSkill never calls a Tool;
           module never imports Tool machinery.
    A7  -- AST: no private (leading single-underscore, non-dunder)
           method, and no extra public method, defined on
           OrderValidationSkill beyond the three BaseSkill-required
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
from Orchestration.order_validation_skill import OrderValidationSkill
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
    to prove OrderValidationSkill never touches any other
    attribute."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _allocation_entry(symbol: Any, action: Any, capital: Any) -> dict:
    return {"symbol": symbol, "action": action, "capital": capital}


def _run(allocations: Any) -> SkillResult:
    skill = OrderValidationSkill()
    return skill.execute(_FakeContext({"allocations": allocations}))


# ---------------------------------------------------------------------------
# R1-R7 -- the four rules and their edge cases
# ---------------------------------------------------------------------------
def scenario_buy_with_positive_capital_is_approved() -> None:
    result = _run([_allocation_entry("BBCA", "BUY", 100_000_000)])
    order = result.output["orders"][0]
    check(order["status"] == "APPROVED", f"R1: BUY+capital>0 -> APPROVED; got {order['status']!r}")
    check(order["reason"] == "ready for execution", f"R1: reason -> 'ready for execution'; got {order['reason']!r}")


def scenario_wait_is_hold() -> None:
    result = _run([_allocation_entry("BBCA", "WAIT", 0)])
    order = result.output["orders"][0]
    check(order["status"] == "HOLD", f"R2: WAIT -> HOLD; got {order['status']!r}")
    check(order["reason"] == "waiting for better opportunity", f"R2: reason -> 'waiting for better opportunity'; got {order['reason']!r}")


def scenario_sell_is_exit() -> None:
    result = _run([_allocation_entry("BBCA", "SELL", 50_000_000)])
    order = result.output["orders"][0]
    check(order["status"] == "EXIT", f"R3: SELL -> EXIT; got {order['status']!r}")
    check(order["reason"] == "exit position", f"R3: reason -> 'exit position'; got {order['reason']!r}")


def scenario_unrecognized_action_is_rejected() -> None:
    for action in ("HOLD", "buy", "SHORT", "", None):
        result = _run([_allocation_entry("XXX", action, 100_000_000)])
        order = result.output["orders"][0]
        check(order["status"] == "REJECTED", f"R4: unrecognized action {action!r} -> REJECTED; got {order['status']!r}")
        check(order["reason"] == "invalid order", f"R4: reason -> 'invalid order'; got {order['reason']!r}")


def scenario_buy_with_zero_capital_is_rejected() -> None:
    result = _run([_allocation_entry("BBCA", "BUY", 0)])
    order = result.output["orders"][0]
    check(order["status"] == "REJECTED", f"R5: BUY+capital==0 -> REJECTED (not HOLD/EXIT); got {order['status']!r}")
    check(order["reason"] == "invalid order", f"R5: reason -> 'invalid order'; got {order['reason']!r}")


def scenario_buy_with_negative_capital_is_rejected() -> None:
    result = _run([_allocation_entry("BBCA", "BUY", -100_000_000)])
    order = result.output["orders"][0]
    check(order["status"] == "REJECTED", f"R6: BUY+capital<0 -> REJECTED; got {order['status']!r}")


def scenario_buy_with_non_numeric_capital_is_rejected() -> None:
    for capital in ("100000000", None, True, False, [], {}):
        result = _run([_allocation_entry("BBCA", "BUY", capital)])
        order = result.output["orders"][0]
        check(order["status"] == "REJECTED", f"R7: BUY+capital={capital!r} (non-numeric) -> REJECTED; got {order['status']!r}")


# ---------------------------------------------------------------------------
# M1-M2 -- malformed entries
# ---------------------------------------------------------------------------
def scenario_malformed_entry_yields_rejected_never_raises() -> None:
    for entry in (None, "not-a-dict", 42, [1, 2, 3]):
        result = _run([entry])
        order = result.output["orders"][0]
        check(order["symbol"] is None, f"M1: malformed entry {entry!r} -> symbol=None; got {order['symbol']!r}")
        check(order["action"] is None, f"M1: malformed entry {entry!r} -> action=None; got {order['action']!r}")
        check(order["capital"] is None, f"M1: malformed entry {entry!r} -> capital=None; got {order['capital']!r}")
        check(order["status"] == "REJECTED", f"M1: malformed entry {entry!r} -> status=REJECTED; got {order['status']!r}")


def scenario_missing_fields_never_raise() -> None:
    result = _run([{}])
    order = result.output["orders"][0]
    check(order == {"symbol": None, "action": None, "capital": None, "status": "REJECTED", "reason": "invalid order"}, f"M2: empty entry dict -> all-None + REJECTED; got {order!r}")

    result = _run([{"symbol": "BBCA", "action": "BUY"}])
    order = result.output["orders"][0]
    check(order["capital"] is None, "M2: missing 'capital' key -> capital=None")
    check(order["status"] == "REJECTED", f"M2: BUY with missing capital -> REJECTED; got {order['status']!r}")

    result = _run([{"symbol": "BBCA", "capital": 100_000_000}])
    order = result.output["orders"][0]
    check(order["action"] is None, "M2: missing 'action' key -> action=None")
    check(order["status"] == "REJECTED", f"M2: missing action -> REJECTED; got {order['status']!r}")


# ---------------------------------------------------------------------------
# E1-E4 -- empty/missing/malformed input
# ---------------------------------------------------------------------------
def scenario_empty_allocations_list() -> None:
    result = _run([])
    check(result.output == {"orders": []}, f"E1: empty allocations -> {{'orders': []}}; got {result.output!r}")
    check(result.success is True, "E1: success=True for empty allocations")


def scenario_missing_allocations_key_never_raises() -> None:
    skill = OrderValidationSkill()
    result = skill.execute(_FakeContext({}))
    check(result.output == {"orders": []}, f"E2: missing 'allocations' key -> {{'orders': []}}; got {result.output!r}")


def scenario_non_list_allocations_never_raises() -> None:
    skill = OrderValidationSkill()
    for bad_allocations in (None, "not-a-list", 42, {"a": 1}):
        result = skill.execute(_FakeContext({"allocations": bad_allocations}))
        check(result.output == {"orders": []}, f"E3: non-list allocations {bad_allocations!r} -> {{'orders': []}}; got {result.output!r}")


def scenario_non_mapping_parameters_never_raises() -> None:
    skill = OrderValidationSkill()
    for bad_parameters in (None, "not-a-mapping", 42, ["a", "list"]):
        result = skill.execute(_FakeContext(bad_parameters))
        check(result.output == {"orders": []}, f"E4: non-Mapping parameters {bad_parameters!r} -> {{'orders': []}}; got {result.output!r}")
        check(result.success is True, f"E4: success=True for non-Mapping parameters {bad_parameters!r}")


# ---------------------------------------------------------------------------
# S1-S5 -- output shape
# ---------------------------------------------------------------------------
def scenario_order_entry_has_exactly_five_keys() -> None:
    result = _run([_allocation_entry("BBCA", "BUY", 100_000_000)])
    order = result.output["orders"][0]
    check(set(order.keys()) == {"symbol", "action", "capital", "status", "reason"}, f"S1: exactly five keys; got {set(order.keys())!r}")


def scenario_fields_are_raw_not_normalized() -> None:
    result = _run([_allocation_entry("bbca", "buy", 100_000_000)])
    order = result.output["orders"][0]
    check(order["symbol"] == "bbca", f"S2: symbol reported back unchanged; got {order['symbol']!r}")
    check(order["action"] == "buy", f"S2: action reported back unchanged (not normalized); got {order['action']!r}")
    check(order["status"] == "REJECTED", "S2: lowercase 'buy' does not match Rule 1's exact 'BUY' -> REJECTED")


def scenario_skill_result_shape() -> None:
    result = _run([_allocation_entry("BBCA", "BUY", 1)])
    check(result.success is True, "S3: success=True")
    check(result.error is None, "S3: error=None")
    check(dict(result.metadata) == {}, f"S3: metadata={{}}; got {dict(result.metadata)!r}")
    check(isinstance(result.output, dict) and "orders" in result.output, "S3: output is a dict with an 'orders' key")


def scenario_original_input_order_preserved() -> None:
    allocations = [
        _allocation_entry("AAA", "BUY", 100),
        _allocation_entry("BBB", "WAIT", 0),
        _allocation_entry("CCC", "SELL", 50),
        _allocation_entry("DDD", "SHORT", 10),
    ]
    result = _run(allocations)
    symbols = [o["symbol"] for o in result.output["orders"]]
    check(symbols == ["AAA", "BBB", "CCC", "DDD"], f"S4: original order preserved; got {symbols!r}")


def scenario_prompt_worked_examples_match_exactly() -> None:
    cases = [
        (_allocation_entry("BBCA", "BUY", 100_000_000), "APPROVED", "ready for execution"),
        (_allocation_entry("BBCA", "WAIT", 0), "HOLD", "waiting for better opportunity"),
        (_allocation_entry("BBCA", "SELL", 100_000_000), "EXIT", "exit position"),
        (_allocation_entry("BBCA", "SHORT", 100_000_000), "REJECTED", "invalid order"),
    ]
    for entry, expected_status, expected_reason in cases:
        result = _run([entry])
        order = result.output["orders"][0]
        check(order["status"] == expected_status, f"S5: {entry['action']!r} -> {expected_status}; got {order['status']!r}")
        check(order["reason"] == expected_reason, f"S5: {entry['action']!r} reason -> {expected_reason!r}; got {order['reason']!r}")


# ---------------------------------------------------------------------------
# D1 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    allocations = [
        _allocation_entry("AAA", "BUY", 100),
        _allocation_entry("BBB", "WAIT", 0),
        _allocation_entry("CCC", "SELL", 50),
        _allocation_entry(None, None, None),
    ]
    first = _run(allocations)
    second = _run(allocations)
    check(first == second, f"D1: repeated execute() calls are deterministic; got {first!r} vs {second!r}")


# ---------------------------------------------------------------------------
# A1-A7 -- AST / structural verification
# ---------------------------------------------------------------------------
def scenario_exactly_one_skill_result_construction() -> None:
    import Orchestration.order_validation_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")


def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.order_validation_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_fragments = (
        "Engine", "Manager", "Strategy", "Planner", "Workflow",
        "Coordinator", "Factory", "Registry", "Helper", "Validator",
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
    check(class_names == {"OrderValidationSkill"}, f"A3: module defines exactly one class; got {class_names!r}")


def scenario_class_subclasses_base_skill_only() -> None:
    check(issubclass(OrderValidationSkill, BaseSkill), "A3: OrderValidationSkill subclasses BaseSkill")
    check(OrderValidationSkill.__bases__ == (BaseSkill,), f"A3: OrderValidationSkill has exactly one base class, BaseSkill; got {OrderValidationSkill.__bases__!r}")


def scenario_no_init_no_instance_state() -> None:
    check("__init__" not in OrderValidationSkill.__dict__, "A4: OrderValidationSkill defines no __init__ of its own")
    skill = OrderValidationSkill()
    check(skill.__dict__ == {}, f"A4: OrderValidationSkill instances carry no instance state; got {skill.__dict__!r}")


def scenario_execute_has_no_nested_function() -> None:
    source = inspect.getsource(OrderValidationSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A5: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")


def scenario_no_tool_calls_anywhere() -> None:
    import Orchestration.order_validation_skill as module

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
        "Orchestration.capital_allocation_skill", "Orchestration.trading_decision_agent",
        "Orchestration.executor", "ToolResolver", "ToolRegistry", "ToolContext",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"A6: module never imports {forbidden!r}")


def scenario_no_extra_public_or_private_methods() -> None:
    required_members = {"name", "description", "execute"}
    for attr_name, attr_value in OrderValidationSkill.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A7: no additional method/property defined on OrderValidationSkill beyond name/description/execute; found {attr_name!r}",
        )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_buy_with_positive_capital_is_approved,
        scenario_wait_is_hold,
        scenario_sell_is_exit,
        scenario_unrecognized_action_is_rejected,
        scenario_buy_with_zero_capital_is_rejected,
        scenario_buy_with_negative_capital_is_rejected,
        scenario_buy_with_non_numeric_capital_is_rejected,
        scenario_malformed_entry_yields_rejected_never_raises,
        scenario_missing_fields_never_raise,
        scenario_empty_allocations_list,
        scenario_missing_allocations_key_never_raises,
        scenario_non_list_allocations_never_raises,
        scenario_non_mapping_parameters_never_raises,
        scenario_order_entry_has_exactly_five_keys,
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