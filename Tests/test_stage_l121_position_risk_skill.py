"""Phase 10 Sprint 121 proof suite -- PositionRiskSkill.

``PositionRiskSkill`` is the project's first risk-level layer: it
reads a list of already-decided actions (each carrying an
``"action"`` value, in the same shape ``RecommendationSkill.execute()``
already produces) and attaches a single, deterministic ``risk`` label
to every one, via one fixed three-row lookup table --
``NORMAL``/``LOW``/``NONE``/``UNKNOWN``.

Scope: dedicated proof suite for
``Orchestration.position_risk_skill.PositionRiskSkill`` only. Mirrors
the compact, table-driven, no-pytest, global-counter-plus-``main()``
style already used by
``Tests/test_stage_l120_recommendation_skill.py``.

Invariant coverage:
    D1-D3 -- all three decision-table rows (BUY, WAIT, SELL) produce
             the exact LOCKED risk level.
    U1    -- an unrecognized action value yields "UNKNOWN" (including
             RecommendationSkill's own "UNKNOWN"/"WATCH"/"IGNORE"/
             "EXIT" actions, which are not in this table at all).
    U2    -- a missing "action" key yields "UNKNOWN".
    U3    -- a malformed (non-dict) entry yields "UNKNOWN" and
             symbol=None, action=None, never raising.
    E1    -- an empty "actions" list yields {"risk": []}, success=True.
    E2    -- a missing "actions" key yields {"risk": []}, never
             raising.
    E3    -- a non-list "actions" value yields {"risk": []}, never
             raising.
    E4    -- parameters that are not a Mapping at all never raises.
    S1    -- output shape: each risk entry has exactly the three keys
             symbol/action/risk, nothing more.
    S2    -- action on the output entry is the exact raw value read
             from input, never normalized.
    S3    -- SkillResult shape: success=True, error=None,
             metadata={}, output={"risk": [...]}.
    S4    -- original input order is preserved.
    R1    -- repeated execute() calls with the same input are
             deterministic (field-equal SkillResults).
    A1    -- AST: exactly one SkillResult(...) construction.
    A2    -- AST: no forbidden-name symbol (RuleEngine,
             PositionSizer, RiskEngine, Strategy, Manager,
             Coordinator, Planner, Workflow, Service, Repository,
             Provider, Factory, Helper, Utility, Engine) anywhere in
             the module namespace.
    A3    -- AST: the module defines exactly one class,
             PositionRiskSkill, subclassing BaseSkill only.
    A4    -- class shape: no __init__ defined on PositionRiskSkill
             itself; no instance state after construction.
    A5    -- AST: execute() defines no nested function/lambda.
    A6    -- AST: no execute_tool()/execute_tool_result() call
             anywhere in the module; PositionRiskSkill never calls a
             Tool; module never imports Tool machinery.
    A7    -- AST: no private (leading single-underscore, non-dunder)
             method, and no extra public method, defined on
             PositionRiskSkill beyond the three BaseSkill-required
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
from Orchestration.position_risk_skill import PositionRiskSkill
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
    to prove PositionRiskSkill never touches any other attribute."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _action(symbol: Any, action: Any) -> dict:
    return {"symbol": symbol, "action": action}


def _run(actions: Any) -> SkillResult:
    skill = PositionRiskSkill()
    return skill.execute(_FakeContext({"actions": actions}))


# ---------------------------------------------------------------------------
# D1-D3 -- all three decision-table rows
# ---------------------------------------------------------------------------
_DECISION_TABLE_ROWS = [
    ("BUY", "NORMAL"),
    ("WAIT", "LOW"),
    ("SELL", "NONE"),
]


def scenario_all_three_decision_table_rows() -> None:
    for action, expected_risk in _DECISION_TABLE_ROWS:
        result = _run([_action("SYM", action)])
        entry = result.output["risk"][0]
        check(entry["risk"] == expected_risk, f"D: {action} -> {expected_risk}; got {entry['risk']!r}")


def scenario_readme_example_matches_exactly() -> None:
    actions = [
        {"symbol": "BBCA", "action": "BUY"},
        {"symbol": "BBRI", "action": "WAIT"},
        {"symbol": "ASII", "action": "SELL"},
    ]
    result = _run(actions)
    risk = result.output["risk"]
    check(risk[0] == {"symbol": "BBCA", "action": "BUY", "risk": "NORMAL"}, f"D1: BBCA BUY -> NORMAL; got {risk[0]!r}")
    check(risk[1] == {"symbol": "BBRI", "action": "WAIT", "risk": "LOW"}, f"D2: BBRI WAIT -> LOW; got {risk[1]!r}")
    check(risk[2] == {"symbol": "ASII", "action": "SELL", "risk": "NONE"}, f"D3: ASII SELL -> NONE; got {risk[2]!r}")


# ---------------------------------------------------------------------------
# U1-U3 -- unknown / malformed input
# ---------------------------------------------------------------------------
def scenario_unrecognized_action_yields_unknown() -> None:
    for action in ("HOLD", "WATCH", "IGNORE", "EXIT", "UNKNOWN", "buy", ""):
        result = _run([_action("XXX", action)])
        entry = result.output["risk"][0]
        check(entry["risk"] == "UNKNOWN", f"U1: unrecognized action {action!r} -> UNKNOWN; got {entry['risk']!r}")
        check(entry["action"] == action, f"U1: action is reported back unchanged; got {entry['action']!r}")


def scenario_missing_action_key_yields_unknown() -> None:
    result = _run([{"symbol": "XXX"}])
    entry = result.output["risk"][0]
    check(entry["risk"] == "UNKNOWN", f"U2: missing 'action' key -> UNKNOWN; got {entry['risk']!r}")
    check(entry["action"] is None, f"U2: missing 'action' -> action is None; got {entry['action']!r}")
    check(entry["symbol"] == "XXX", f"U2: symbol is still read correctly; got {entry['symbol']!r}")


def scenario_malformed_entry_yields_unknown_never_raises() -> None:
    exc = _catch(lambda: _run(["not a dict", None, 42, ["nested", "list"], 3.14]))
    check(exc is None, f"U3: malformed entries never raise; got {exc!r}")

    result = _run(["not a dict", None, 42])
    for entry in result.output["risk"]:
        check(entry["symbol"] is None, f"U3: malformed entry -> symbol=None; got {entry['symbol']!r}")
        check(entry["action"] is None, f"U3: malformed entry -> action=None; got {entry['action']!r}")
        check(entry["risk"] == "UNKNOWN", f"U3: malformed entry -> risk=UNKNOWN; got {entry['risk']!r}")
    check(len(result.output["risk"]) == 3, f"U3: one risk entry per malformed input item; got {len(result.output['risk'])}")


# ---------------------------------------------------------------------------
# E1-E4 -- empty / missing / malformed 'actions'
# ---------------------------------------------------------------------------
def scenario_empty_actions_list() -> None:
    result = _run([])
    check(result.output == {"risk": []}, f"E1: empty actions list yields {{'risk': []}}; got {result.output!r}")
    check(result.success is True, "E1: success is True for an empty actions list")


def scenario_missing_actions_key_never_raises() -> None:
    skill = PositionRiskSkill()
    exc = _catch(lambda: skill.execute(_FakeContext({})))
    check(exc is None, f"E2: missing 'actions' key never raises; got {exc!r}")
    result = skill.execute(_FakeContext({}))
    check(result.output == {"risk": []}, f"E2: missing 'actions' key yields {{'risk': []}}; got {result.output!r}")


def scenario_non_list_actions_never_raises() -> None:
    skill = PositionRiskSkill()
    exc = _catch(lambda: skill.execute(_FakeContext({"actions": "not a list"})))
    check(exc is None, f"E3: non-list 'actions' value never raises; got {exc!r}")
    result = skill.execute(_FakeContext({"actions": "not a list"}))
    check(result.output == {"risk": []}, f"E3: non-list 'actions' value yields {{'risk': []}}; got {result.output!r}")


def scenario_non_mapping_parameters_never_raises() -> None:
    skill = PositionRiskSkill()
    exc1 = _catch(lambda: skill.execute(_FakeContext("not a mapping")))
    check(exc1 is None, f"E4: non-Mapping parameters never raises; got {exc1!r}")
    exc2 = _catch(lambda: skill.execute(_FakeContext(None)))
    check(exc2 is None, f"E4: parameters=None never raises; got {exc2!r}")
    exc3 = _catch(lambda: skill.execute(object()))
    check(exc3 is None, f"E4: a context-like object with no .parameters attribute never raises; got {exc3!r}")


# ---------------------------------------------------------------------------
# S1-S4 -- output shape
# ---------------------------------------------------------------------------
def scenario_risk_entry_has_exactly_three_keys() -> None:
    result = _run([_action("BBCA", "BUY")])
    entry = result.output["risk"][0]
    check(set(entry.keys()) == {"symbol", "action", "risk"}, f"S1: risk entry has exactly symbol/action/risk; got {set(entry.keys())!r}")


def scenario_action_is_raw_not_normalized() -> None:
    result = _run([_action("XXX", "hold")])
    entry = result.output["risk"][0]
    check(entry["action"] == "hold", f"S2: action is the exact raw input value, never normalized; got {entry['action']!r}")
    check(entry["risk"] == "UNKNOWN", f"S2: lowercase 'hold' is not in the table -> UNKNOWN; got {entry['risk']!r}")


def scenario_skill_result_shape() -> None:
    result = _run([_action("BBCA", "BUY")])
    check(result.success is True, "S3: success is unconditionally True")
    check(result.error is None, "S3: error is unconditionally None")
    check(dict(result.metadata) == {}, f"S3: metadata is unconditionally empty; got {dict(result.metadata)!r}")
    check(isinstance(result.output, dict) and list(result.output.keys()) == ["risk"], f"S3: output has exactly the 'risk' top-level key; got {result.output!r}")


def scenario_original_input_order_preserved() -> None:
    actions = [_action("A", "BUY"), _action("B", "SELL"), _action("C", "WAIT"), _action("D", "HOLD")]
    result = _run(actions)
    symbols_in_order = [entry["symbol"] for entry in result.output["risk"]]
    check(symbols_in_order == ["A", "B", "C", "D"], f"S4: original input order preserved; got {symbols_in_order!r}")


# ---------------------------------------------------------------------------
# R1 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    actions = [_action("BBCA", "BUY"), _action("BBRI", "WAIT"), _action("ASII", "SELL")]
    result1 = _run(actions)
    result2 = _run(actions)
    check(result1 == result2, "R1: repeated execute() calls with the same input are field-equal (deterministic)")
    check(result1.output == result2.output, "R1: output is identical across repeated runs")


# ---------------------------------------------------------------------------
# A1-A7 -- AST / namespace verification
# ---------------------------------------------------------------------------
def scenario_exactly_one_skill_result_construction() -> None:
    source = inspect.getsource(PositionRiskSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    skill_result_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillResult"]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")


def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.position_risk_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_fragments = (
        "RuleEngine", "PositionSizer", "RiskEngine", "Strategy",
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
    check(class_names == {"PositionRiskSkill"}, f"A3: module defines exactly one class; got {class_names!r}")


def scenario_class_subclasses_base_skill_only() -> None:
    check(issubclass(PositionRiskSkill, BaseSkill), "A3: PositionRiskSkill subclasses BaseSkill")
    check(PositionRiskSkill.__bases__ == (BaseSkill,), f"A3: PositionRiskSkill has exactly one base class, BaseSkill; got {PositionRiskSkill.__bases__!r}")


def scenario_no_init_no_instance_state() -> None:
    check("__init__" not in PositionRiskSkill.__dict__, "A4: PositionRiskSkill defines no __init__ of its own")
    skill = PositionRiskSkill()
    check(skill.__dict__ == {}, f"A4: PositionRiskSkill instances carry no instance state; got {skill.__dict__!r}")


def scenario_execute_has_no_nested_function() -> None:
    source = inspect.getsource(PositionRiskSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A5: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")


def scenario_no_tool_calls_anywhere() -> None:
    import Orchestration.position_risk_skill as module

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
        "Orchestration.recommendation_skill", "Orchestration.executor",
        "ToolResolver", "ToolRegistry", "ToolContext",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"A6: module never imports {forbidden!r}")


def scenario_no_extra_public_or_private_methods() -> None:
    required_members = {"name", "description", "execute"}
    for attr_name, attr_value in PositionRiskSkill.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A7: no additional method/property defined on PositionRiskSkill beyond name/description/execute; found {attr_name!r}",
        )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_all_three_decision_table_rows,
        scenario_readme_example_matches_exactly,
        scenario_unrecognized_action_yields_unknown,
        scenario_missing_action_key_yields_unknown,
        scenario_malformed_entry_yields_unknown_never_raises,
        scenario_empty_actions_list,
        scenario_missing_actions_key_never_raises,
        scenario_non_list_actions_never_raises,
        scenario_non_mapping_parameters_never_raises,
        scenario_risk_entry_has_exactly_three_keys,
        scenario_action_is_raw_not_normalized,
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