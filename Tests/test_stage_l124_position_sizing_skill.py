"""Phase 10 Sprint 124 proof suite -- PositionSizingSkill.

``PositionSizingSkill`` is the project's first position-sizing layer:
it reads a list of already-planned entries (each carrying an
``"action"``/``"risk"``/``"plan"`` triple, in the same shape
``TradePlanSkill.execute()`` already produces) and attaches a single,
deterministic ``position_size`` label to every one, via one fixed
nine-row lookup table keyed on ``(action, risk)`` --
``FULL``/``HALF``/``SMALL``/``WATCH``/``EXIT``/``UNKNOWN``.

Scope: dedicated proof suite for
``Orchestration.position_sizing_skill.PositionSizingSkill`` only.
Mirrors the compact, table-driven, no-pytest,
global-counter-plus-``main()`` style already used by
``Tests/test_stage_l122_trade_plan_skill.py``.

Invariant coverage:
    D1-D9 -- all nine decision-table rows produce the exact LOCKED
             position size.
    U1    -- an unrecognized (action, risk) combination yields
             "UNKNOWN".
    U2    -- a missing "action" and/or "risk" key yields "UNKNOWN".
    U3    -- a malformed (non-dict) entry yields "UNKNOWN" and
             symbol=None, action=None, risk=None, plan=None, never
             raising.
    E1    -- an empty "plans" list yields {"positions": []},
             success=True.
    E2    -- a missing "plans" key yields {"positions": []}, never
             raising.
    E3    -- a non-list "plans" value yields {"positions": []},
             never raising.
    E4    -- parameters that are not a Mapping at all never raises.
    S1    -- output shape: each position entry has exactly the five
             keys symbol/action/risk/plan/position_size, nothing
             more.
    S2    -- action/risk/plan on the output entry are the exact raw
             values read from input, never normalized.
    S3    -- SkillResult shape: success=True, error=None,
             metadata={}, output={"positions": [...]}.
    S4    -- original input order is preserved.
    R1    -- repeated execute() calls with the same input are
             deterministic (field-equal SkillResults).
    A1    -- AST: exactly one SkillResult(...) construction.
    A2    -- AST: exactly one dict literal lookup table.
    A3    -- AST: no forbidden-name symbol (PositionSizingEngine,
             PositionCalculator, RiskCalculator, MoneyManagement,
             Manager, Planner, Strategy, Factory, Registry,
             Coordinator, Workflow, Service, Repository, Helper,
             Utility, Formatter) anywhere in the module namespace.
    A4    -- AST: the module defines exactly one class,
             PositionSizingSkill, subclassing BaseSkill only.
    A5    -- class shape: no __init__ defined on PositionSizingSkill
             itself; no instance state after construction.
    A6    -- AST: execute() defines no nested function/lambda.
    A7    -- AST: no execute_tool()/execute_tool_result() call
             anywhere in the module; PositionSizingSkill never calls
             a Tool; module never imports Tool machinery.
    A8    -- AST: no private (leading single-underscore, non-dunder)
             method, and no extra public method, defined on
             PositionSizingSkill beyond the three BaseSkill-required
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
from Orchestration.position_sizing_skill import PositionSizingSkill
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
    to prove PositionSizingSkill never touches any other attribute."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _plan_entry(symbol: Any, action: Any, risk: Any, plan: Any) -> dict:
    return {"symbol": symbol, "action": action, "risk": risk, "plan": plan}


def _run(plans: Any) -> SkillResult:
    skill = PositionSizingSkill()
    return skill.execute(_FakeContext({"plans": plans}))


# ---------------------------------------------------------------------------
# D1-D9 -- all nine decision-table rows
# ---------------------------------------------------------------------------
_DECISION_TABLE_ROWS = [
    ("BUY", "LOW", "FULL"),
    ("BUY", "MEDIUM", "HALF"),
    ("BUY", "HIGH", "SMALL"),
    ("WAIT", "LOW", "WATCH"),
    ("WAIT", "MEDIUM", "WATCH"),
    ("WAIT", "HIGH", "WATCH"),
    ("SELL", "LOW", "EXIT"),
    ("SELL", "MEDIUM", "EXIT"),
    ("SELL", "HIGH", "EXIT"),
]


def scenario_all_nine_decision_table_rows() -> None:
    for action, risk, expected_size in _DECISION_TABLE_ROWS:
        result = _run([_plan_entry("SYM", action, risk, "SOME_PLAN")])
        entry = result.output["positions"][0]
        check(entry["position_size"] == expected_size, f"D: ({action}, {risk}) -> {expected_size}; got {entry['position_size']!r}")


def scenario_prompt_example_matches_exactly() -> None:
    plans = [{"symbol": "BBCA", "action": "BUY", "risk": "LOW", "plan": "ACCUMULATE"}]
    result = _run(plans)
    entry = result.output["positions"][0]
    check(
        entry == {"symbol": "BBCA", "action": "BUY", "risk": "LOW", "plan": "ACCUMULATE", "position_size": "FULL"},
        f"D1: BBCA BUY/LOW/ACCUMULATE -> FULL; got {entry!r}",
    )


# ---------------------------------------------------------------------------
# U1-U3 -- unknown / malformed input
# ---------------------------------------------------------------------------
def scenario_unrecognized_combination_yields_unknown() -> None:
    combos = [
        ("BUY", "UNKNOWN"), ("WAIT", "NONE"), ("SELL", ""),
        ("HOLD", "LOW"), ("buy", "low"), ("", ""),
    ]
    for action, risk in combos:
        result = _run([_plan_entry("XXX", action, risk, "P")])
        entry = result.output["positions"][0]
        check(entry["position_size"] == "UNKNOWN", f"U1: unrecognized ({action!r}, {risk!r}) -> UNKNOWN; got {entry['position_size']!r}")
        check(entry["action"] == action and entry["risk"] == risk, f"U1: action/risk reported back unchanged; got {entry!r}")


def scenario_missing_action_or_risk_key_yields_unknown() -> None:
    result = _run([{"symbol": "XXX", "risk": "LOW", "plan": "P"}])
    entry = result.output["positions"][0]
    check(entry["position_size"] == "UNKNOWN", f"U2: missing 'action' key -> UNKNOWN; got {entry['position_size']!r}")
    check(entry["action"] is None, f"U2: missing 'action' -> action is None; got {entry['action']!r}")
    check(entry["risk"] == "LOW", f"U2: risk still read correctly; got {entry['risk']!r}")

    result2 = _run([{"symbol": "YYY", "action": "BUY", "plan": "P"}])
    entry2 = result2.output["positions"][0]
    check(entry2["position_size"] == "UNKNOWN", f"U2: missing 'risk' key -> UNKNOWN; got {entry2['position_size']!r}")
    check(entry2["risk"] is None, f"U2: missing 'risk' -> risk is None; got {entry2['risk']!r}")
    check(entry2["action"] == "BUY", f"U2: action still read correctly; got {entry2['action']!r}")

    result3 = _run([{"symbol": "ZZZ"}])
    entry3 = result3.output["positions"][0]
    check(entry3["position_size"] == "UNKNOWN", f"U2: missing all keys -> UNKNOWN; got {entry3['position_size']!r}")
    check(entry3["action"] is None and entry3["risk"] is None and entry3["plan"] is None, f"U2: all missing fields are None; got {entry3!r}")


def scenario_malformed_entry_yields_unknown_never_raises() -> None:
    exc = _catch(lambda: _run(["not a dict", None, 42, ["nested", "list"], 3.14]))
    check(exc is None, f"U3: malformed entries never raise; got {exc!r}")

    result = _run(["not a dict", None, 42])
    for entry in result.output["positions"]:
        check(entry["symbol"] is None, f"U3: malformed entry -> symbol=None; got {entry['symbol']!r}")
        check(entry["action"] is None, f"U3: malformed entry -> action=None; got {entry['action']!r}")
        check(entry["risk"] is None, f"U3: malformed entry -> risk=None; got {entry['risk']!r}")
        check(entry["plan"] is None, f"U3: malformed entry -> plan=None; got {entry['plan']!r}")
        check(entry["position_size"] == "UNKNOWN", f"U3: malformed entry -> position_size=UNKNOWN; got {entry['position_size']!r}")
    check(len(result.output["positions"]) == 3, f"U3: one position entry per malformed input item; got {len(result.output['positions'])}")


# ---------------------------------------------------------------------------
# E1-E4 -- empty / missing / malformed 'plans'
# ---------------------------------------------------------------------------
def scenario_empty_plans_list() -> None:
    result = _run([])
    check(result.output == {"positions": []}, f"E1: empty plans list yields {{'positions': []}}; got {result.output!r}")
    check(result.success is True, "E1: success is True for an empty plans list")


def scenario_missing_plans_key_never_raises() -> None:
    skill = PositionSizingSkill()
    exc = _catch(lambda: skill.execute(_FakeContext({})))
    check(exc is None, f"E2: missing 'plans' key never raises; got {exc!r}")
    result = skill.execute(_FakeContext({}))
    check(result.output == {"positions": []}, f"E2: missing 'plans' key yields {{'positions': []}}; got {result.output!r}")


def scenario_non_list_plans_never_raises() -> None:
    skill = PositionSizingSkill()
    exc = _catch(lambda: skill.execute(_FakeContext({"plans": "not a list"})))
    check(exc is None, f"E3: non-list 'plans' value never raises; got {exc!r}")
    result = skill.execute(_FakeContext({"plans": "not a list"}))
    check(result.output == {"positions": []}, f"E3: non-list 'plans' value yields {{'positions': []}}; got {result.output!r}")


def scenario_non_mapping_parameters_never_raises() -> None:
    skill = PositionSizingSkill()
    exc1 = _catch(lambda: skill.execute(_FakeContext("not a mapping")))
    check(exc1 is None, f"E4: non-Mapping parameters never raises; got {exc1!r}")
    exc2 = _catch(lambda: skill.execute(_FakeContext(None)))
    check(exc2 is None, f"E4: parameters=None never raises; got {exc2!r}")
    exc3 = _catch(lambda: skill.execute(object()))
    check(exc3 is None, f"E4: a context-like object with no .parameters attribute never raises; got {exc3!r}")


# ---------------------------------------------------------------------------
# S1-S4 -- output shape
# ---------------------------------------------------------------------------
def scenario_position_entry_has_exactly_five_keys() -> None:
    result = _run([_plan_entry("BBCA", "BUY", "LOW", "ACCUMULATE")])
    entry = result.output["positions"][0]
    check(set(entry.keys()) == {"symbol", "action", "risk", "plan", "position_size"}, f"S1: position entry has exactly symbol/action/risk/plan/position_size; got {set(entry.keys())!r}")


def scenario_action_risk_plan_are_raw_not_normalized() -> None:
    result = _run([_plan_entry("XXX", "buy", "low", "accumulate")])
    entry = result.output["positions"][0]
    check(entry["action"] == "buy", f"S2: action is the exact raw input value, never normalized; got {entry['action']!r}")
    check(entry["risk"] == "low", f"S2: risk is the exact raw input value, never normalized; got {entry['risk']!r}")
    check(entry["plan"] == "accumulate", f"S2: plan is the exact raw input value, never normalized; got {entry['plan']!r}")
    check(entry["position_size"] == "UNKNOWN", f"S2: lowercase pair is not in the table -> UNKNOWN; got {entry['position_size']!r}")


def scenario_skill_result_shape() -> None:
    result = _run([_plan_entry("BBCA", "BUY", "LOW", "ACCUMULATE")])
    check(result.success is True, "S3: success is unconditionally True")
    check(result.error is None, "S3: error is unconditionally None")
    check(dict(result.metadata) == {}, f"S3: metadata is unconditionally empty; got {dict(result.metadata)!r}")
    check(isinstance(result.output, dict) and list(result.output.keys()) == ["positions"], f"S3: output has exactly the 'positions' top-level key; got {result.output!r}")


def scenario_original_input_order_preserved() -> None:
    plans = [
        _plan_entry("A", "BUY", "LOW", "P1"),
        _plan_entry("B", "SELL", "MEDIUM", "P2"),
        _plan_entry("C", "WAIT", "HIGH", "P3"),
        _plan_entry("D", "HOLD", "EXTREME", "P4"),
    ]
    result = _run(plans)
    symbols_in_order = [entry["symbol"] for entry in result.output["positions"]]
    check(symbols_in_order == ["A", "B", "C", "D"], f"S4: original input order preserved; got {symbols_in_order!r}")


# ---------------------------------------------------------------------------
# R1 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    plans = [
        _plan_entry("BBCA", "BUY", "LOW", "ACCUMULATE"),
        _plan_entry("BBRI", "WAIT", "MEDIUM", "HOLD"),
        _plan_entry("ASII", "SELL", "HIGH", "REDUCE"),
    ]
    result1 = _run(plans)
    result2 = _run(plans)
    check(result1 == result2, "R1: repeated execute() calls with the same input are field-equal (deterministic)")
    check(result1.output == result2.output, "R1: output is identical across repeated runs")


# ---------------------------------------------------------------------------
# A1-A8 -- AST / namespace verification
# ---------------------------------------------------------------------------
def scenario_exactly_one_skill_result_construction() -> None:
    source = inspect.getsource(PositionSizingSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    skill_result_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillResult"]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")


def scenario_exactly_one_dict_lookup_table() -> None:
    source = inspect.getsource(PositionSizingSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    dict_literals = [n for n in ast.walk(top_level_def) if isinstance(n, ast.Dict)]
    # The single lookup-table dict literal is the only ast.Dict node in
    # execute(); each per-entry output dict is built via a dict literal
    # too (the `positions.append({...})` call), so we isolate the
    # lookup table specifically by requiring keys to be ast.Tuple nodes
    # (the "(action, risk)" tuple keys), which no output entry uses.
    tuple_keyed_dicts = [
        d for d in dict_literals
        if d.keys and all(isinstance(k, ast.Tuple) for k in d.keys)
    ]
    check(len(tuple_keyed_dicts) == 1, f"A2: exactly one tuple-keyed dict literal lookup table; got {len(tuple_keyed_dicts)}")

    # Distinguish the single *table* lookup (`position_size_table.get(...)`)
    # from the several defensive `entry.get("symbol")`-style reads --
    # both are AST-identical `ast.Attribute` calls with `.attr == "get"`,
    # so the table lookup is isolated by requiring its receiver to be the
    # same name the lookup-table dict literal was assigned to.
    assign_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.Assign)]
    table_names = {
        t.id
        for a in assign_nodes
        if isinstance(a.value, ast.Dict) and a.value.keys and all(isinstance(k, ast.Tuple) for k in a.value.keys)
        for t in a.targets
        if isinstance(t, ast.Name)
    }
    get_calls = [
        c for c in ast.walk(top_level_def)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "get"
    ]
    table_get_calls = [
        c for c in get_calls
        if isinstance(c.func.value, ast.Name) and c.func.value.id in table_names
    ]
    check(len(table_get_calls) == 1, f"A2: exactly one dict.get(...) lookup call on the lookup table; got {len(table_get_calls)}")


def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.position_sizing_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_fragments = (
        "PositionSizingEngine", "PositionCalculator", "RiskCalculator",
        "MoneyManagement", "Manager", "Planner", "Strategy", "Factory",
        "Registry", "Coordinator", "Workflow", "Service", "Repository",
        "Helper", "Utility", "Formatter",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A3: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )

    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = {n.name for n in class_defs}
    check(class_names == {"PositionSizingSkill"}, f"A4: module defines exactly one class; got {class_names!r}")


def scenario_class_subclasses_base_skill_only() -> None:
    check(issubclass(PositionSizingSkill, BaseSkill), "A4: PositionSizingSkill subclasses BaseSkill")
    check(PositionSizingSkill.__bases__ == (BaseSkill,), f"A4: PositionSizingSkill has exactly one base class, BaseSkill; got {PositionSizingSkill.__bases__!r}")


def scenario_no_init_no_instance_state() -> None:
    check("__init__" not in PositionSizingSkill.__dict__, "A5: PositionSizingSkill defines no __init__ of its own")
    skill = PositionSizingSkill()
    check(skill.__dict__ == {}, f"A5: PositionSizingSkill instances carry no instance state; got {skill.__dict__!r}")


def scenario_execute_has_no_nested_function() -> None:
    source = inspect.getsource(PositionSizingSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A6: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")


def scenario_no_tool_calls_anywhere() -> None:
    import Orchestration.position_sizing_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    forbidden_tool_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr in ("execute_tool", "execute_tool_result")
    ]
    check(len(forbidden_tool_calls) == 0, f"A7: module never calls execute_tool()/execute_tool_result(); got {len(forbidden_tool_calls)}")

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
        "Orchestration.trade_plan_skill", "Orchestration.trading_decision_agent",
        "Orchestration.executor",
        "ToolResolver", "ToolRegistry", "ToolContext",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"A7: module never imports {forbidden!r}")


def scenario_no_extra_public_or_private_methods() -> None:
    required_members = {"name", "description", "execute"}
    for attr_name, attr_value in PositionSizingSkill.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A8: no additional method/property defined on PositionSizingSkill beyond name/description/execute; found {attr_name!r}",
        )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_all_nine_decision_table_rows,
        scenario_prompt_example_matches_exactly,
        scenario_unrecognized_combination_yields_unknown,
        scenario_missing_action_or_risk_key_yields_unknown,
        scenario_malformed_entry_yields_unknown_never_raises,
        scenario_empty_plans_list,
        scenario_missing_plans_key_never_raises,
        scenario_non_list_plans_never_raises,
        scenario_non_mapping_parameters_never_raises,
        scenario_position_entry_has_exactly_five_keys,
        scenario_action_risk_plan_are_raw_not_normalized,
        scenario_skill_result_shape,
        scenario_original_input_order_preserved,
        scenario_repeated_execution_is_deterministic,
        scenario_exactly_one_skill_result_construction,
        scenario_exactly_one_dict_lookup_table,
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