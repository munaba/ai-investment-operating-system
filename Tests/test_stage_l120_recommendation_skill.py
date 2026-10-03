"""Phase 11 Sprint 120 proof suite -- RecommendationSkill.

``RecommendationSkill`` is the project's first real decision layer:
it reads a list of already-analyzed stocks (each carrying a
``recommendation``/``confidence`` pair) and maps every one, via a
single fixed nine-row lookup table, to a concrete ``action`` --
``BUY``/``WATCH``/``IGNORE``/``EXIT``/``UNKNOWN``.

Scope: dedicated proof suite for
``Orchestration.recommendation_skill.RecommendationSkill`` only.
Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l119_market_analysis_agent_workflow.py``.

Invariant coverage:
    D1-D9 -- all nine decision-table rows produce the exact LOCKED
             action.
    U1    -- an unrecognized recommendation value yields "UNKNOWN".
    U2    -- an unrecognized confidence value yields "UNKNOWN".
    U3    -- a missing "analysis" key yields "UNKNOWN".
    U4    -- a non-dict "analysis" value yields "UNKNOWN".
    U5    -- a malformed (non-dict) stock entry yields "UNKNOWN" and
             symbol=None, never raising.
    E1    -- an empty "stocks" list yields {"actions": []},
             success=True.
    E2    -- a missing "stocks" key yields {"actions": []}, never
             raising.
    E3    -- a non-list "stocks" value yields {"actions": []}, never
             raising.
    E4    -- parameters that are not a Mapping at all never raises.
    S1    -- output shape: each action entry has exactly the four
             keys symbol/action/recommendation/confidence, nothing
             more.
    S2    -- recommendation/confidence on the output entry are the
             exact raw values read from input, never normalized.
    S3    -- SkillResult shape: success=True, error=None,
             metadata={}, output={"actions": [...]}.
    S4    -- original input order is preserved.
    R1    -- repeated execute() calls with the same input are
             deterministic (field-equal SkillResults).
    A1    -- AST: exactly one SkillResult(...) construction.
    A2    -- AST: no forbidden-name symbol (DecisionEngine,
             RecommendationEngine, SignalEngine, ActionPlanner,
             PortfolioOptimizer, Strategy, Manager, Coordinator,
             Analyzer, Pipeline, Workflow, Factory, Helper, Utility)
             anywhere in the module namespace.
    A3    -- AST: the module defines exactly one class,
             RecommendationSkill, subclassing BaseSkill only.
    A4    -- class shape: no __init__ defined on RecommendationSkill
             itself (inherits BaseSkill's implicit object.__init__);
             no instance state after construction.
    A5    -- AST: execute() defines no nested function/lambda.
    A6    -- AST: no execute_tool()/execute_tool_result() call
             anywhere in the module; RecommendationSkill never calls
             a Tool.
    A7    -- AST: no private (leading single-underscore, non-dunder)
             method defined on RecommendationSkill beyond the three
             BaseSkill-required members.
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
from Orchestration.recommendation_skill import RecommendationSkill
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
    to prove RecommendationSkill never touches any other attribute."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _stock(symbol: Any, recommendation: Any, confidence: Any) -> dict:
    return {"symbol": symbol, "analysis": {"recommendation": recommendation, "confidence": confidence}}


def _run(stocks: Any) -> SkillResult:
    skill = RecommendationSkill()
    return skill.execute(_FakeContext({"stocks": stocks}))


# ---------------------------------------------------------------------------
# D1-D9 -- all nine decision-table rows
# ---------------------------------------------------------------------------
_DECISION_TABLE_ROWS = [
    ("BUY", "HIGH", "BUY"),
    ("BUY", "MEDIUM", "BUY"),
    ("BUY", "LOW", "WATCH"),
    ("WAIT", "HIGH", "WATCH"),
    ("WAIT", "MEDIUM", "WATCH"),
    ("WAIT", "LOW", "IGNORE"),
    ("SELL", "HIGH", "EXIT"),
    ("SELL", "MEDIUM", "EXIT"),
    ("SELL", "LOW", "IGNORE"),
]


def scenario_all_nine_decision_table_rows() -> None:
    for recommendation, confidence, expected_action in _DECISION_TABLE_ROWS:
        result = _run([_stock("SYM", recommendation, confidence)])
        entry = result.output["actions"][0]
        check(
            entry["action"] == expected_action,
            f"D: ({recommendation}, {confidence}) -> {expected_action}; got {entry['action']!r}",
        )


def scenario_readme_example_matches_exactly() -> None:
    stocks = [
        {"symbol": "BBCA", "analysis": {"recommendation": "BUY", "confidence": "HIGH"}},
        {"symbol": "BBRI", "analysis": {"recommendation": "WAIT", "confidence": "MEDIUM"}},
        {"symbol": "ASII", "analysis": {"recommendation": "SELL", "confidence": "HIGH"}},
    ]
    result = _run(stocks)
    actions = result.output["actions"]
    check(actions[0]["symbol"] == "BBCA" and actions[0]["action"] == "BUY", f"D1: BBCA -> BUY; got {actions[0]!r}")
    check(actions[1]["symbol"] == "BBRI" and actions[1]["action"] == "WATCH", f"D4: BBRI -> WATCH; got {actions[1]!r}")
    check(actions[2]["symbol"] == "ASII" and actions[2]["action"] == "EXIT", f"D7: ASII -> EXIT; got {actions[2]!r}")


# ---------------------------------------------------------------------------
# U1-U5 -- unknown / malformed input
# ---------------------------------------------------------------------------
def scenario_unrecognized_recommendation_yields_unknown() -> None:
    result = _run([_stock("XXX", "HOLD", "HIGH")])
    check(result.output["actions"][0]["action"] == "UNKNOWN", f"U1: unrecognized recommendation -> UNKNOWN; got {result.output['actions'][0]['action']!r}")


def scenario_unrecognized_confidence_yields_unknown() -> None:
    result = _run([_stock("XXX", "BUY", "VERY_HIGH")])
    check(result.output["actions"][0]["action"] == "UNKNOWN", f"U2: unrecognized confidence -> UNKNOWN; got {result.output['actions'][0]['action']!r}")


def scenario_missing_analysis_key_yields_unknown() -> None:
    result = _run([{"symbol": "XXX"}])
    entry = result.output["actions"][0]
    check(entry["action"] == "UNKNOWN", f"U3: missing 'analysis' key -> UNKNOWN; got {entry['action']!r}")
    check(entry["recommendation"] is None and entry["confidence"] is None, f"U3: missing 'analysis' -> recommendation/confidence are None; got {entry!r}")
    check(entry["symbol"] == "XXX", f"U3: symbol is still read correctly; got {entry['symbol']!r}")


def scenario_non_dict_analysis_yields_unknown() -> None:
    result = _run([{"symbol": "XXX", "analysis": "not a dict"}])
    entry = result.output["actions"][0]
    check(entry["action"] == "UNKNOWN", f"U4: non-dict 'analysis' -> UNKNOWN; got {entry['action']!r}")
    check(entry["recommendation"] is None and entry["confidence"] is None, f"U4: non-dict 'analysis' -> recommendation/confidence are None; got {entry!r}")


def scenario_malformed_stock_entry_yields_unknown_never_raises() -> None:
    exc = _catch(lambda: _run(["not a dict", None, 42, ["nested", "list"]]))
    check(exc is None, f"U5: malformed stock entries never raise; got {exc!r}")

    result = _run(["not a dict", None, 42])
    for entry in result.output["actions"]:
        check(entry["symbol"] is None, f"U5: malformed stock entry -> symbol=None; got {entry['symbol']!r}")
        check(entry["action"] == "UNKNOWN", f"U5: malformed stock entry -> action=UNKNOWN; got {entry['action']!r}")
    check(len(result.output["actions"]) == 3, f"U5: one action entry per malformed input item, even malformed ones; got {len(result.output['actions'])}")


# ---------------------------------------------------------------------------
# E1-E4 -- empty / missing / malformed 'stocks'
# ---------------------------------------------------------------------------
def scenario_empty_stocks_list() -> None:
    result = _run([])
    check(result.output == {"actions": []}, f"E1: empty stocks list yields {{'actions': []}}; got {result.output!r}")
    check(result.success is True, "E1: success is True for an empty stocks list")


def scenario_missing_stocks_key_never_raises() -> None:
    skill = RecommendationSkill()
    exc = _catch(lambda: skill.execute(_FakeContext({})))
    check(exc is None, f"E2: missing 'stocks' key never raises; got {exc!r}")
    result = skill.execute(_FakeContext({}))
    check(result.output == {"actions": []}, f"E2: missing 'stocks' key yields {{'actions': []}}; got {result.output!r}")


def scenario_non_list_stocks_never_raises() -> None:
    skill = RecommendationSkill()
    exc = _catch(lambda: skill.execute(_FakeContext({"stocks": "not a list"})))
    check(exc is None, f"E3: non-list 'stocks' value never raises; got {exc!r}")
    result = skill.execute(_FakeContext({"stocks": "not a list"}))
    check(result.output == {"actions": []}, f"E3: non-list 'stocks' value yields {{'actions': []}}; got {result.output!r}")


def scenario_non_mapping_parameters_never_raises() -> None:
    skill = RecommendationSkill()
    exc1 = _catch(lambda: skill.execute(_FakeContext("not a mapping")))
    check(exc1 is None, f"E4: non-Mapping parameters never raises; got {exc1!r}")
    exc2 = _catch(lambda: skill.execute(_FakeContext(None)))
    check(exc2 is None, f"E4: parameters=None never raises; got {exc2!r}")
    exc3 = _catch(lambda: skill.execute(object()))
    check(exc3 is None, f"E4: a context-like object with no .parameters attribute never raises; got {exc3!r}")


# ---------------------------------------------------------------------------
# S1-S4 -- output shape
# ---------------------------------------------------------------------------
def scenario_action_entry_has_exactly_four_keys() -> None:
    result = _run([_stock("BBCA", "BUY", "HIGH")])
    entry = result.output["actions"][0]
    check(set(entry.keys()) == {"symbol", "action", "recommendation", "confidence"}, f"S1: action entry has exactly symbol/action/recommendation/confidence; got {set(entry.keys())!r}")


def scenario_recommendation_confidence_are_raw_not_normalized() -> None:
    result = _run([_stock("XXX", "HOLD", "VERY_HIGH")])
    entry = result.output["actions"][0]
    check(entry["recommendation"] == "HOLD", f"S2: recommendation is the exact raw input value, never normalized; got {entry['recommendation']!r}")
    check(entry["confidence"] == "VERY_HIGH", f"S2: confidence is the exact raw input value, never normalized; got {entry['confidence']!r}")


def scenario_skill_result_shape() -> None:
    result = _run([_stock("BBCA", "BUY", "HIGH")])
    check(result.success is True, "S3: success is unconditionally True")
    check(result.error is None, "S3: error is unconditionally None")
    check(dict(result.metadata) == {}, f"S3: metadata is unconditionally empty; got {dict(result.metadata)!r}")
    check(isinstance(result.output, dict) and list(result.output.keys()) == ["actions"], f"S3: output has exactly the 'actions' top-level key; got {result.output!r}")


def scenario_original_input_order_preserved() -> None:
    stocks = [_stock("A", "BUY", "HIGH"), _stock("B", "SELL", "LOW"), _stock("C", "WAIT", "MEDIUM")]
    result = _run(stocks)
    symbols_in_order = [entry["symbol"] for entry in result.output["actions"]]
    check(symbols_in_order == ["A", "B", "C"], f"S4: original input order preserved; got {symbols_in_order!r}")


# ---------------------------------------------------------------------------
# R1 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    stocks = [_stock("BBCA", "BUY", "HIGH"), _stock("BBRI", "WAIT", "MEDIUM"), _stock("ASII", "SELL", "HIGH")]
    result1 = _run(stocks)
    result2 = _run(stocks)
    check(result1 == result2, "R1: repeated execute() calls with the same input are field-equal (deterministic)")
    check(result1.output == result2.output, "R1: output is identical across repeated runs")


# ---------------------------------------------------------------------------
# A1-A7 -- AST / namespace verification
# ---------------------------------------------------------------------------
def scenario_exactly_one_skill_result_construction() -> None:
    source = inspect.getsource(RecommendationSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    skill_result_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillResult"]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")


def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.recommendation_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_fragments = (
        "DecisionEngine", "RecommendationEngine", "SignalEngine",
        "ActionPlanner", "PortfolioOptimizer", "Strategy", "Manager",
        "Coordinator", "Analyzer", "Pipeline", "Workflow", "Factory",
        "Helper", "Utility",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A2: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )

    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = {n.name for n in class_defs}
    check(class_names == {"RecommendationSkill"}, f"A3: module defines exactly one class; got {class_names!r}")


def scenario_class_subclasses_base_skill_only() -> None:
    check(issubclass(RecommendationSkill, BaseSkill), "A3: RecommendationSkill subclasses BaseSkill")
    check(RecommendationSkill.__bases__ == (BaseSkill,), f"A3: RecommendationSkill has exactly one base class, BaseSkill; got {RecommendationSkill.__bases__!r}")


def scenario_no_init_no_instance_state() -> None:
    check("__init__" not in RecommendationSkill.__dict__, "A4: RecommendationSkill defines no __init__ of its own")
    skill = RecommendationSkill()
    check(skill.__dict__ == {}, f"A4: RecommendationSkill instances carry no instance state; got {skill.__dict__!r}")


def scenario_execute_has_no_nested_function() -> None:
    source = inspect.getsource(RecommendationSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A5: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")


def scenario_no_tool_calls_anywhere() -> None:
    import Orchestration.recommendation_skill as module

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
        "Orchestration.executor", "ToolResolver", "ToolRegistry", "ToolContext",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"A6: module never imports {forbidden!r}")


def scenario_no_private_helper_methods() -> None:
    required_members = {"name", "description", "execute"}
    for attr_name, attr_value in RecommendationSkill.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A7: no additional method/property defined on RecommendationSkill beyond name/description/execute; found {attr_name!r}",
        )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_all_nine_decision_table_rows,
        scenario_readme_example_matches_exactly,
        scenario_unrecognized_recommendation_yields_unknown,
        scenario_unrecognized_confidence_yields_unknown,
        scenario_missing_analysis_key_yields_unknown,
        scenario_non_dict_analysis_yields_unknown,
        scenario_malformed_stock_entry_yields_unknown_never_raises,
        scenario_empty_stocks_list,
        scenario_missing_stocks_key_never_raises,
        scenario_non_list_stocks_never_raises,
        scenario_non_mapping_parameters_never_raises,
        scenario_action_entry_has_exactly_four_keys,
        scenario_recommendation_confidence_are_raw_not_normalized,
        scenario_skill_result_shape,
        scenario_original_input_order_preserved,
        scenario_repeated_execution_is_deterministic,
        scenario_exactly_one_skill_result_construction,
        scenario_no_forbidden_abstractions,
        scenario_class_subclasses_base_skill_only,
        scenario_no_init_no_instance_state,
        scenario_execute_has_no_nested_function,
        scenario_no_tool_calls_anywhere,
        scenario_no_private_helper_methods,
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