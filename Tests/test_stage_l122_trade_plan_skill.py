"""Phase 10 Sprint 122 proof suite -- TradePlanSkill.

``TradePlanSkill`` is the project's first trade-plan layer: it reads
a list of already-risk-scored entries (each carrying an
``"action"``/``"risk"`` pair, in the same shape
``PositionRiskSkill.execute()`` already produces) and attaches a
single, deterministic ``plan`` label to every one, via one fixed
three-row lookup table keyed on ``(action, risk)`` --
``ENTER``/``MONITOR``/``EXIT``/``UNKNOWN``.

Scope: dedicated proof suite for
``Orchestration.trade_plan_skill.TradePlanSkill`` only. Mirrors the
compact, table-driven, no-pytest, global-counter-plus-``main()``
style already used by
``Tests/test_stage_l121_position_risk_skill.py``.

Invariant coverage:
    D1-D3 -- all three decision-table rows (BUY/NORMAL, WAIT/LOW,
             SELL/NONE) produce the exact LOCKED plan.
    U1    -- an unrecognized (action, risk) combination yields
             "UNKNOWN".
    U2    -- a missing "action" and/or "risk" key yields "UNKNOWN".
    U3    -- a malformed (non-dict) entry yields "UNKNOWN" and
             symbol=None, action=None, risk=None, never raising.
    E1    -- an empty "risk" list yields {"plans": []}, success=True.
    E2    -- a missing "risk" key yields {"plans": []}, never
             raising.
    E3    -- a non-list "risk" value yields {"plans": []}, never
             raising.
    E4    -- parameters that are not a Mapping at all never raises.
    S1    -- output shape: each plan entry has exactly the four keys
             symbol/action/risk/plan, nothing more.
    S2    -- action and risk on the output entry are the exact raw
             values read from input, never normalized.
    S3    -- SkillResult shape: success=True, error=None,
             metadata={}, output={"plans": [...]}.
    S4    -- original input order is preserved.
    R1    -- repeated execute() calls with the same input are
             deterministic (field-equal SkillResults).
    A1    -- AST: exactly one SkillResult(...) construction.
    A2    -- AST: no forbidden-name symbol (RuleEngine,
             PositionSizer, TradeEngine, Strategy, Manager,
             Coordinator, Planner, Workflow, Service, Repository,
             Provider, Factory, Helper, Utility, Engine) anywhere in
             the module namespace.
    A3    -- AST: the module defines exactly one class,
             TradePlanSkill, subclassing BaseSkill only.
    A4    -- class shape: no __init__ defined on TradePlanSkill
             itself; no instance state after construction.
    A5    -- AST: execute() defines no nested function/lambda.
    A6    -- AST: no execute_tool()/execute_tool_result() call
             anywhere in the module; TradePlanSkill never calls a
             Tool; module never imports Tool machinery.
    A7    -- AST: no private (leading single-underscore, non-dunder)
             method, and no extra public method, defined on
             TradePlanSkill beyond the three BaseSkill-required
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
from Orchestration.trade_plan_skill import TradePlanSkill
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


class _FakeContext:
    """A minimal context-like object exposing only ``.parameters``,
    to prove TradePlanSkill never touches any other attribute."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _risk_entry(symbol: Any, action: Any, risk: Any) -> dict:
    return {"symbol": symbol, "action": action, "risk": risk}


def _run(risk: Any) -> SkillResult:
    skill = TradePlanSkill()
    return skill.execute(_FakeContext({"risk": risk}))


# ---------------------------------------------------------------------------
# D1-D3 -- all three decision-table rows
# ---------------------------------------------------------------------------
_DECISION_TABLE_ROWS = [
    ("BUY", "NORMAL", "ENTER"),
    ("WAIT", "LOW", "MONITOR"),
    ("SELL", "NONE", "EXIT"),
]


def scenario_all_three_decision_table_rows() -> None:
    for action, risk, expected_plan in _DECISION_TABLE_ROWS:
        result = _run([_risk_entry("SYM", action, risk)])
        entry = result.output["plans"][0]
        check(entry["plan"] == expected_plan, f"D: ({action}, {risk}) -> {expected_plan}; got {entry['plan']!r}")


def scenario_prompt_example_matches_exactly() -> None:
    risk = [
        {"symbol": "BBCA", "action": "BUY", "risk": "NORMAL"},
        {"symbol": "BBRI", "action": "WAIT", "risk": "LOW"},
        {"symbol": "ASII", "action": "SELL", "risk": "NONE"},
    ]
    result = _run(risk)
    plans = result.output["plans"]
    check(plans[0] == {"symbol": "BBCA", "action": "BUY", "risk": "NORMAL", "plan": "ENTER"}, f"D1: BBCA BUY/NORMAL -> ENTER; got {plans[0]!r}")
    check(plans[1] == {"symbol": "BBRI", "action": "WAIT", "risk": "LOW", "plan": "MONITOR"}, f"D2: BBRI WAIT/LOW -> MONITOR; got {plans[1]!r}")
    check(plans[2] == {"symbol": "ASII", "action": "SELL", "risk": "NONE", "plan": "EXIT"}, f"D3: ASII SELL/NONE -> EXIT; got {plans[2]!r}")


# ---------------------------------------------------------------------------
# U1-U3 -- unknown / malformed input
# ---------------------------------------------------------------------------
def scenario_unrecognized_combination_yields_unknown() -> None:
    combos = [
        ("BUY", "LOW"), ("BUY", "NONE"), ("BUY", "UNKNOWN"),
        ("WAIT", "NORMAL"), ("WAIT", "NONE"),
        ("SELL", "NORMAL"), ("SELL", "LOW"),
        ("HOLD", "NORMAL"), ("buy", "normal"), ("", ""),
    ]
    for action, risk in combos:
        result = _run([_risk_entry("XXX", action, risk)])
        entry = result.output["plans"][0]
        check(entry["plan"] == "UNKNOWN", f"U1: unrecognized ({action!r}, {risk!r}) -> UNKNOWN; got {entry['plan']!r}")
        check(entry["action"] == action and entry["risk"] == risk, f"U1: action/risk reported back unchanged; got {entry!r}")


def scenario_missing_action_or_risk_key_yields_unknown() -> None:
    result = _run([{"symbol": "XXX", "risk": "NORMAL"}])
    entry = result.output["plans"][0]
    check(entry["plan"] == "UNKNOWN", f"U2: missing 'action' key -> UNKNOWN; got {entry['plan']!r}")
    check(entry["action"] is None, f"U2: missing 'action' -> action is None; got {entry['action']!r}")
    check(entry["risk"] == "NORMAL", f"U2: risk still read correctly; got {entry['risk']!r}")

    result2 = _run([{"symbol": "YYY", "action": "BUY"}])
    entry2 = result2.output["plans"][0]
    check(entry2["plan"] == "UNKNOWN", f"U2: missing 'risk' key -> UNKNOWN; got {entry2['plan']!r}")
    check(entry2["risk"] is None, f"U2: missing 'risk' -> risk is None; got {entry2['risk']!r}")
    check(entry2["action"] == "BUY", f"U2: action still read correctly; got {entry2['action']!r}")

    result3 = _run([{"symbol": "ZZZ"}])
    entry3 = result3.output["plans"][0]
    check(entry3["plan"] == "UNKNOWN", f"U2: missing both keys -> UNKNOWN; got {entry3['plan']!r}")
    check(entry3["action"] is None and entry3["risk"] is None, f"U2: both are None; got {entry3!r}")


def scenario_malformed_entry_yields_unknown_never_raises() -> None:
    exc = _catch(lambda: _run(["not a dict", None, 42, ["nested", "list"], 3.14]))
    check(exc is None, f"U3: malformed entries never raise; got {exc!r}")

    result = _run(["not a dict", None, 42])
    for entry in result.output["plans"]:
        check(entry["symbol"] is None, f"U3: malformed entry -> symbol=None; got {entry['symbol']!r}")
        check(entry["action"] is None, f"U3: malformed entry -> action=None; got {entry['action']!r}")
        check(entry["risk"] is None, f"U3: malformed entry -> risk=None; got {entry['risk']!r}")
        check(entry["plan"] == "UNKNOWN", f"U3: malformed entry -> plan=UNKNOWN; got {entry['plan']!r}")
    check(len(result.output["plans"]) == 3, f"U3: one plan entry per malformed input item; got {len(result.output['plans'])}")


# ---------------------------------------------------------------------------
# E1-E4 -- empty / missing / malformed 'risk'
# ---------------------------------------------------------------------------
def scenario_empty_risk_list() -> None:
    result = _run([])
    check(result.output == {"plans": []}, f"E1: empty risk list yields {{'plans': []}}; got {result.output!r}")
    check(result.success is True, "E1: success is True for an empty risk list")


def scenario_missing_risk_key_never_raises() -> None:
    skill = TradePlanSkill()
    exc = _catch(lambda: skill.execute(_FakeContext({})))
    check(exc is None, f"E2: missing 'risk' key never raises; got {exc!r}")
    result = skill.execute(_FakeContext({}))
    check(result.output == {"plans": []}, f"E2: missing 'risk' key yields {{'plans': []}}; got {result.output!r}")


def scenario_non_list_risk_never_raises() -> None:
    skill = TradePlanSkill()
    exc = _catch(lambda: skill.execute(_FakeContext({"risk": "not a list"})))
    check(exc is None, f"E3: non-list 'risk' value never raises; got {exc!r}")
    result = skill.execute(_FakeContext({"risk": "not a list"}))
    check(result.output == {"plans": []}, f"E3: non-list 'risk' value yields {{'plans': []}}; got {result.output!r}")


def scenario_non_mapping_parameters_never_raises() -> None:
    skill = TradePlanSkill()
    exc1 = _catch(lambda: skill.execute(_FakeContext("not a mapping")))
    check(exc1 is None, f"E4: non-Mapping parameters never raises; got {exc1!r}")
    exc2 = _catch(lambda: skill.execute(_FakeContext(None)))
    check(exc2 is None, f"E4: parameters=None never raises; got {exc2!r}")
    exc3 = _catch(lambda: skill.execute(object()))
    check(exc3 is None, f"E4: a context-like object with no .parameters attribute never raises; got {exc3!r}")


# ---------------------------------------------------------------------------
# S1-S4 -- output shape
# ---------------------------------------------------------------------------
def scenario_plan_entry_has_exactly_four_keys() -> None:
    result = _run([_risk_entry("BBCA", "BUY", "NORMAL")])
    entry = result.output["plans"][0]
    check(set(entry.keys()) == {"symbol", "action", "risk", "plan"}, f"S1: plan entry has exactly symbol/action/risk/plan; got {set(entry.keys())!r}")


def scenario_action_and_risk_are_raw_not_normalized() -> None:
    result = _run([_risk_entry("XXX", "buy", "normal")])
    entry = result.output["plans"][0]
    check(entry["action"] == "buy", f"S2: action is the exact raw input value, never normalized; got {entry['action']!r}")
    check(entry["risk"] == "normal", f"S2: risk is the exact raw input value, never normalized; got {entry['risk']!r}")
    check(entry["plan"] == "UNKNOWN", f"S2: lowercase pair is not in the table -> UNKNOWN; got {entry['plan']!r}")


def scenario_skill_result_shape() -> None:
    result = _run([_risk_entry("BBCA", "BUY", "NORMAL")])
    check(result.success is True, "S3: success is unconditionally True")
    check(result.error is None, "S3: error is unconditionally None")
    check(dict(result.metadata) == {}, f"S3: metadata is unconditionally empty; got {dict(result.metadata)!r}")
    check(isinstance(result.output, dict) and list(result.output.keys()) == ["plans"], f"S3: output has exactly the 'plans' top-level key; got {result.output!r}")


def scenario_original_input_order_preserved() -> None:
    risk = [
        _risk_entry("A", "BUY", "NORMAL"),
        _risk_entry("B", "SELL", "NONE"),
        _risk_entry("C", "WAIT", "LOW"),
        _risk_entry("D", "HOLD", "HIGH"),
    ]
    result = _run(risk)
    symbols_in_order = [entry["symbol"] for entry in result.output["plans"]]
    check(symbols_in_order == ["A", "B", "C", "D"], f"S4: original input order preserved; got {symbols_in_order!r}")


# ---------------------------------------------------------------------------
# R1 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    risk = [
        _risk_entry("BBCA", "BUY", "NORMAL"),
        _risk_entry("BBRI", "WAIT", "LOW"),
        _risk_entry("ASII", "SELL", "NONE"),
    ]
    result1 = _run(risk)
    result2 = _run(risk)
    check(result1 == result2, "R1: repeated execute() calls with the same input are field-equal (deterministic)")
    check(result1.output == result2.output, "R1: output is identical across repeated runs")


# ---------------------------------------------------------------------------
# A1-A7 -- AST / namespace verification
# ---------------------------------------------------------------------------
def scenario_exactly_one_skill_result_construction() -> None:
    source = inspect.getsource(TradePlanSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    skill_result_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillResult"]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")


def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.trade_plan_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_fragments = (
        "RuleEngine", "PositionSizer", "TradeEngine", "Strategy",
        "Manager", "Coordinator", "Planner", "Workflow", "Service",
        "Repository", "Provider", "Factory", "Helper", "Utility",
        "Engine",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A2: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )

    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = {n.name for n in class_defs}
    check(class_names == {"TradePlanSkill"}, f"A3: module defines exactly one class; got {class_names!r}")


def scenario_class_subclasses_base_skill_only() -> None:
    check(issubclass(TradePlanSkill, BaseSkill), "A3: TradePlanSkill subclasses BaseSkill")
    check(TradePlanSkill.__bases__ == (BaseSkill,), f"A3: TradePlanSkill has exactly one base class, BaseSkill; got {TradePlanSkill.__bases__!r}")


def scenario_no_init_no_instance_state() -> None:
    check("__init__" not in TradePlanSkill.__dict__, "A4: TradePlanSkill defines no __init__ of its own")
    skill = TradePlanSkill()
    check(skill.__dict__ == {}, f"A4: TradePlanSkill instances carry no instance state; got {skill.__dict__!r}")


def scenario_execute_has_no_nested_function() -> None:
    source = inspect.getsource(TradePlanSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A5: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")


def scenario_no_tool_calls_anywhere() -> None:
    import Orchestration.trade_plan_skill as module

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
        "Orchestration.executor",
        "ToolResolver", "ToolRegistry", "ToolContext",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"A6: module never imports {forbidden!r}")


def scenario_no_extra_public_or_private_methods() -> None:
    required_members = {"name", "description", "execute"}
    for attr_name, attr_value in TradePlanSkill.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A7: no additional method/property defined on TradePlanSkill beyond name/description/execute; found {attr_name!r}",
        )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_all_three_decision_table_rows,
        scenario_prompt_example_matches_exactly,
        scenario_unrecognized_combination_yields_unknown,
        scenario_missing_action_or_risk_key_yields_unknown,
        scenario_malformed_entry_yields_unknown_never_raises,
        scenario_empty_risk_list,
        scenario_missing_risk_key_never_raises,
        scenario_non_list_risk_never_raises,
        scenario_non_mapping_parameters_never_raises,
        scenario_plan_entry_has_exactly_four_keys,
        scenario_action_and_risk_are_raw_not_normalized,
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