"""Phase 10 Sprint 125 proof suite -- CapitalAllocationSkill.

``CapitalAllocationSkill`` is the project's first capital-allocation
layer: it reads a list of already-sized entries (each carrying a
``"position_size"`` value, in the same shape
``PositionSizingSkill.execute()`` already produces) plus a total
``"capital"`` figure, and attaches a single, deterministic
``allocated_capital`` amount to every one, via one fixed five-row
percentage lookup table keyed on ``position_size`` --
``FULL``/``HALF``/``SMALL``/``AVOID``/``UNKNOWN``.

Scope: dedicated proof suite for
``Orchestration.capital_allocation_skill.CapitalAllocationSkill``
only. Mirrors the compact, table-driven, no-pytest,
global-counter-plus-``main()`` style already used by
``Tests/test_stage_l124_position_sizing_skill.py``.

Invariant coverage:
    D1-D5 -- all five percentage-table rows produce the exact LOCKED
             allocated capital.
    U1    -- an unrecognized position_size yields allocated_capital=0,
             while forwarding the raw position_size unchanged.
    U2    -- a missing "position_size" key yields allocated_capital=0.
    U3    -- a malformed (non-dict) plan entry yields
             allocated_capital=0 and symbol=None, action=None,
             risk=None, plan=None, position_size=None, never raising.
    C1    -- invalid capital (None, str, bool, negative) behaves
             exactly like capital=0, never raising.
    C2    -- a missing "capital" key behaves exactly like capital=0.
    E1    -- an empty "plans" list yields {"allocations": []},
             success=True.
    E2    -- a missing "plans" key yields {"allocations": []}, never
             raising.
    E3    -- a non-list "plans" value yields {"allocations": []},
             never raising.
    E4    -- parameters that are not a Mapping at all never raises.
    S1    -- output shape: each allocation entry has exactly the six
             keys symbol/action/risk/plan/position_size/
             allocated_capital, nothing more.
    S2    -- action/risk/plan/position_size on the output entry are
             the exact raw values read from input, never normalized.
    S3    -- SkillResult shape: success=True, error=None,
             metadata={}, output={"allocations": [...]}.
    S4    -- original input order is preserved.
    S5    -- the prompt's own worked examples (FULL/HALF/SMALL/AVOID
             against capital=100_000_000) match exactly.
    R1    -- repeated execute() calls with the same input are
             deterministic (field-equal SkillResults).
    A1    -- AST: exactly one SkillResult(...) construction.
    A2    -- AST: exactly one dict literal percentage lookup table,
             looked up via exactly one dict.get(...) call.
    A3    -- AST: no forbidden-name symbol (CapitalAllocator,
             AllocationEngine, MoneyManager, PortfolioOptimizer,
             Manager, Coordinator, Planner, Strategy, Factory,
             Registry, Workflow, Service, Repository, Provider,
             Helper, Utility) anywhere in the module namespace.
    A4    -- AST: the module defines exactly one class,
             CapitalAllocationSkill, subclassing BaseSkill only.
    A5    -- class shape: no __init__ defined on
             CapitalAllocationSkill itself; no instance state after
             construction.
    A6    -- AST: execute() defines no nested function/lambda.
    A7    -- AST: no execute_tool()/execute_tool_result() call
             anywhere in the module; CapitalAllocationSkill never
             calls a Tool; module never imports Tool machinery.
    A8    -- AST: no private (leading single-underscore, non-dunder)
             method, and no extra public method, defined on
             CapitalAllocationSkill beyond the three BaseSkill-
             required members.
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
from Orchestration.capital_allocation_skill import CapitalAllocationSkill
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
    to prove CapitalAllocationSkill never touches any other
    attribute."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _plan_entry(symbol: Any, action: Any, risk: Any, plan: Any, position_size: Any) -> dict:
    return {"symbol": symbol, "action": action, "risk": risk, "plan": plan, "position_size": position_size}


def _run(plans: Any, capital: Any = 100_000_000) -> SkillResult:
    skill = CapitalAllocationSkill()
    return skill.execute(_FakeContext({"plans": plans, "capital": capital}))


# ---------------------------------------------------------------------------
# D1-D5 -- all five percentage-table rows
# ---------------------------------------------------------------------------
_PERCENTAGE_TABLE_ROWS = [
    ("FULL", 100_000_000),
    ("HALF", 50_000_000),
    ("SMALL", 25_000_000),
    ("AVOID", 0),
    ("UNKNOWN", 0),
]


def scenario_all_five_percentage_table_rows() -> None:
    for position_size, expected_capital in _PERCENTAGE_TABLE_ROWS:
        result = _run([_plan_entry("SYM", "BUY", "LOW", "SOME_PLAN", position_size)], capital=100_000_000)
        entry = result.output["allocations"][0]
        check(entry["allocated_capital"] == expected_capital, f"D: {position_size} against 100M -> {expected_capital}; got {entry['allocated_capital']!r}")


def scenario_prompt_worked_examples_match_exactly() -> None:
    for position_size, expected_capital in _PERCENTAGE_TABLE_ROWS:
        result = _run([_plan_entry("BBCA", "BUY", "LOW", "LONG_TERM", position_size)], capital=100_000_000)
        entry = result.output["allocations"][0]
        check(entry["allocated_capital"] == expected_capital, f"S5: {position_size} of 100 juta -> {expected_capital}; got {entry['allocated_capital']!r}")


def scenario_prompt_example_matches_exactly() -> None:
    plans = [{"symbol": "BBCA", "action": "BUY", "risk": "LOW", "plan": "LONG_TERM", "position_size": "FULL"}]
    result = _run(plans, capital=100_000_000)
    entry = result.output["allocations"][0]
    check(
        entry == {"symbol": "BBCA", "action": "BUY", "risk": "LOW", "plan": "LONG_TERM", "position_size": "FULL", "allocated_capital": 100_000_000},
        f"D1: BBCA FULL against 100M -> 100000000; got {entry!r}",
    )


# ---------------------------------------------------------------------------
# U1-U3 -- unknown / malformed input
# ---------------------------------------------------------------------------
def scenario_unrecognized_position_size_yields_zero() -> None:
    for position_size in ("HOLD", "full", "", "MAX", None):
        result = _run([_plan_entry("XXX", "BUY", "LOW", "P", position_size)])
        entry = result.output["allocations"][0]
        check(entry["allocated_capital"] == 0, f"U1: unrecognized position_size {position_size!r} -> 0; got {entry['allocated_capital']!r}")
        check(entry["position_size"] == position_size, f"U1: position_size reported back unchanged; got {entry['position_size']!r}")


def scenario_missing_position_size_key_yields_zero() -> None:
    result = _run([{"symbol": "XXX", "action": "BUY", "risk": "LOW", "plan": "P"}])
    entry = result.output["allocations"][0]
    check(entry["allocated_capital"] == 0, f"U2: missing 'position_size' key -> 0; got {entry['allocated_capital']!r}")
    check(entry["position_size"] is None, f"U2: missing 'position_size' -> position_size is None; got {entry['position_size']!r}")
    check(entry["action"] == "BUY", f"U2: action still read correctly; got {entry['action']!r}")


def scenario_malformed_entry_yields_zero_never_raises() -> None:
    exc = _catch(lambda: _run(["not a dict", None, 42, ["nested", "list"], 3.14]))
    check(exc is None, f"U3: malformed entries never raise; got {exc!r}")

    result = _run(["not a dict", None, 42])
    for entry in result.output["allocations"]:
        check(entry["symbol"] is None, f"U3: malformed entry -> symbol=None; got {entry['symbol']!r}")
        check(entry["action"] is None, f"U3: malformed entry -> action=None; got {entry['action']!r}")
        check(entry["risk"] is None, f"U3: malformed entry -> risk=None; got {entry['risk']!r}")
        check(entry["plan"] is None, f"U3: malformed entry -> plan=None; got {entry['plan']!r}")
        check(entry["position_size"] is None, f"U3: malformed entry -> position_size=None; got {entry['position_size']!r}")
        check(entry["allocated_capital"] == 0, f"U3: malformed entry -> allocated_capital=0; got {entry['allocated_capital']!r}")
    check(len(result.output["allocations"]) == 3, f"U3: one allocation entry per malformed input item; got {len(result.output['allocations'])}")


# ---------------------------------------------------------------------------
# C1-C2 -- invalid / missing capital
# ---------------------------------------------------------------------------
def scenario_invalid_capital_behaves_like_zero() -> None:
    for bad_capital in (None, "100000000", True, False, -1, -100_000_000):
        result = _run([_plan_entry("XXX", "BUY", "LOW", "P", "FULL")], capital=bad_capital)
        entry = result.output["allocations"][0]
        check(entry["allocated_capital"] == 0, f"C1: invalid capital {bad_capital!r} behaves like capital=0; got {entry['allocated_capital']!r}")


def scenario_invalid_capital_never_raises() -> None:
    for bad_capital in (None, "not a number", True, False, [], {}, object()):
        exc = _catch(lambda bad_capital=bad_capital: _run([_plan_entry("XXX", "BUY", "LOW", "P", "FULL")], capital=bad_capital))
        check(exc is None, f"C1: invalid capital {bad_capital!r} never raises; got {exc!r}")


def scenario_missing_capital_key_behaves_like_zero() -> None:
    skill = CapitalAllocationSkill()
    plans = [_plan_entry("XXX", "BUY", "LOW", "P", "FULL")]
    result = skill.execute(_FakeContext({"plans": plans}))
    entry = result.output["allocations"][0]
    check(entry["allocated_capital"] == 0, f"C2: missing 'capital' key behaves like capital=0; got {entry['allocated_capital']!r}")


def scenario_valid_float_capital_is_accepted() -> None:
    result = _run([_plan_entry("XXX", "BUY", "LOW", "P", "HALF")], capital=100_000_000.0)
    entry = result.output["allocations"][0]
    check(entry["allocated_capital"] == 50_000_000, f"C1: a valid float capital is accepted; got {entry['allocated_capital']!r}")

    result_zero = _run([_plan_entry("XXX", "BUY", "LOW", "P", "FULL")], capital=0)
    entry_zero = result_zero.output["allocations"][0]
    check(entry_zero["allocated_capital"] == 0, f"C1: capital=0 (int) yields allocated_capital=0; got {entry_zero['allocated_capital']!r}")


# ---------------------------------------------------------------------------
# E1-E4 -- empty / missing / malformed 'plans'
# ---------------------------------------------------------------------------
def scenario_empty_plans_list() -> None:
    result = _run([])
    check(result.output == {"allocations": []}, f"E1: empty plans list yields {{'allocations': []}}; got {result.output!r}")
    check(result.success is True, "E1: success is True for an empty plans list")


def scenario_missing_plans_key_never_raises() -> None:
    skill = CapitalAllocationSkill()
    exc = _catch(lambda: skill.execute(_FakeContext({"capital": 100_000_000})))
    check(exc is None, f"E2: missing 'plans' key never raises; got {exc!r}")
    result = skill.execute(_FakeContext({"capital": 100_000_000}))
    check(result.output == {"allocations": []}, f"E2: missing 'plans' key yields {{'allocations': []}}; got {result.output!r}")


def scenario_non_list_plans_never_raises() -> None:
    skill = CapitalAllocationSkill()
    exc = _catch(lambda: skill.execute(_FakeContext({"plans": "not a list", "capital": 100_000_000})))
    check(exc is None, f"E3: non-list 'plans' value never raises; got {exc!r}")
    result = skill.execute(_FakeContext({"plans": "not a list", "capital": 100_000_000}))
    check(result.output == {"allocations": []}, f"E3: non-list 'plans' value yields {{'allocations': []}}; got {result.output!r}")


def scenario_non_mapping_parameters_never_raises() -> None:
    skill = CapitalAllocationSkill()
    exc1 = _catch(lambda: skill.execute(_FakeContext("not a mapping")))
    check(exc1 is None, f"E4: non-Mapping parameters never raises; got {exc1!r}")
    exc2 = _catch(lambda: skill.execute(_FakeContext(None)))
    check(exc2 is None, f"E4: parameters=None never raises; got {exc2!r}")
    exc3 = _catch(lambda: skill.execute(object()))
    check(exc3 is None, f"E4: a context-like object with no .parameters attribute never raises; got {exc3!r}")
    result = skill.execute(_FakeContext("not a mapping"))
    check(result.output == {"allocations": []}, f"E4: non-Mapping parameters yields {{'allocations': []}}; got {result.output!r}")


# ---------------------------------------------------------------------------
# S1-S4 -- output shape
# ---------------------------------------------------------------------------
def scenario_allocation_entry_has_exactly_six_keys() -> None:
    result = _run([_plan_entry("BBCA", "BUY", "LOW", "LONG_TERM", "FULL")])
    entry = result.output["allocations"][0]
    check(
        set(entry.keys()) == {"symbol", "action", "risk", "plan", "position_size", "allocated_capital"},
        f"S1: allocation entry has exactly symbol/action/risk/plan/position_size/allocated_capital; got {set(entry.keys())!r}",
    )


def scenario_fields_are_raw_not_normalized() -> None:
    result = _run([_plan_entry("XXX", "buy", "low", "accumulate", "full")])
    entry = result.output["allocations"][0]
    check(entry["action"] == "buy", f"S2: action is the exact raw input value, never normalized; got {entry['action']!r}")
    check(entry["risk"] == "low", f"S2: risk is the exact raw input value, never normalized; got {entry['risk']!r}")
    check(entry["plan"] == "accumulate", f"S2: plan is the exact raw input value, never normalized; got {entry['plan']!r}")
    check(entry["position_size"] == "full", f"S2: position_size is the exact raw input value, never normalized; got {entry['position_size']!r}")
    check(entry["allocated_capital"] == 0, f"S2: lowercase 'full' is not in the table -> 0; got {entry['allocated_capital']!r}")


def scenario_skill_result_shape() -> None:
    result = _run([_plan_entry("BBCA", "BUY", "LOW", "LONG_TERM", "FULL")])
    check(result.success is True, "S3: success is unconditionally True")
    check(result.error is None, "S3: error is unconditionally None")
    check(dict(result.metadata) == {}, f"S3: metadata is unconditionally empty; got {dict(result.metadata)!r}")
    check(isinstance(result.output, dict) and list(result.output.keys()) == ["allocations"], f"S3: output has exactly the 'allocations' top-level key; got {result.output!r}")


def scenario_original_input_order_preserved() -> None:
    plans = [
        _plan_entry("A", "BUY", "LOW", "P1", "FULL"),
        _plan_entry("B", "SELL", "MEDIUM", "P2", "AVOID"),
        _plan_entry("C", "WAIT", "HIGH", "P3", "HALF"),
        _plan_entry("D", "HOLD", "EXTREME", "P4", "SMALL"),
    ]
    result = _run(plans)
    symbols_in_order = [entry["symbol"] for entry in result.output["allocations"]]
    check(symbols_in_order == ["A", "B", "C", "D"], f"S4: original input order preserved; got {symbols_in_order!r}")


# ---------------------------------------------------------------------------
# R1 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    plans = [
        _plan_entry("BBCA", "BUY", "LOW", "LONG_TERM", "FULL"),
        _plan_entry("BBRI", "WAIT", "MEDIUM", "HOLD", "WATCH"),
        _plan_entry("ASII", "SELL", "HIGH", "REDUCE", "AVOID"),
    ]
    result1 = _run(plans)
    result2 = _run(plans)
    check(result1 == result2, "R1: repeated execute() calls with the same input are field-equal (deterministic)")
    check(result1.output == result2.output, "R1: output is identical across repeated runs")


# ---------------------------------------------------------------------------
# A1-A8 -- AST / namespace verification
# ---------------------------------------------------------------------------
def scenario_exactly_one_skill_result_construction() -> None:
    source = inspect.getsource(CapitalAllocationSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    skill_result_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillResult"]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")


def scenario_exactly_one_dict_lookup_table() -> None:
    source = inspect.getsource(CapitalAllocationSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]

    assign_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.Assign)]
    table_names = {
        t.id
        for a in assign_nodes
        if isinstance(a.value, ast.Dict) and a.value.keys and all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in a.value.keys)
        for t in a.targets
        if isinstance(t, ast.Name)
    }
    check(len(table_names) == 1, f"A2: exactly one string-keyed dict literal lookup table; got {len(table_names)}")

    # Distinguish the single *table* lookup (`percentage_table.get(...)`)
    # from any other `.get(...)` calls (the defensive
    # `entry.get("symbol")`-style reads and `parameters.get(...)`
    # reads) -- all are AST-identical `ast.Attribute` calls with
    # `.attr == "get"`, so the table lookup is isolated by requiring
    # its receiver to be the same name the lookup-table dict literal
    # was assigned to.
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
    import Orchestration.capital_allocation_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_fragments = (
        "CapitalAllocator", "AllocationEngine", "MoneyManager",
        "PortfolioOptimizer", "Manager", "Coordinator", "Planner",
        "Strategy", "Factory", "Registry", "Workflow", "Service",
        "Repository", "Provider", "Helper", "Utility",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A3: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )

    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = {n.name for n in class_defs}
    check(class_names == {"CapitalAllocationSkill"}, f"A4: module defines exactly one class; got {class_names!r}")


def scenario_class_subclasses_base_skill_only() -> None:
    check(issubclass(CapitalAllocationSkill, BaseSkill), "A4: CapitalAllocationSkill subclasses BaseSkill")
    check(CapitalAllocationSkill.__bases__ == (BaseSkill,), f"A4: CapitalAllocationSkill has exactly one base class, BaseSkill; got {CapitalAllocationSkill.__bases__!r}")


def scenario_no_init_no_instance_state() -> None:
    check("__init__" not in CapitalAllocationSkill.__dict__, "A5: CapitalAllocationSkill defines no __init__ of its own")
    skill = CapitalAllocationSkill()
    check(skill.__dict__ == {}, f"A5: CapitalAllocationSkill instances carry no instance state; got {skill.__dict__!r}")


def scenario_execute_has_no_nested_function() -> None:
    source = inspect.getsource(CapitalAllocationSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A6: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")


def scenario_no_tool_calls_anywhere() -> None:
    import Orchestration.capital_allocation_skill as module

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
        "Orchestration.trade_plan_skill", "Orchestration.position_sizing_skill",
        "Orchestration.trading_decision_agent", "Orchestration.executor",
        "ToolResolver", "ToolRegistry", "ToolContext",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"A7: module never imports {forbidden!r}")


def scenario_no_extra_public_or_private_methods() -> None:
    required_members = {"name", "description", "execute"}
    for attr_name, attr_value in CapitalAllocationSkill.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A8: no additional method/property defined on CapitalAllocationSkill beyond name/description/execute; found {attr_name!r}",
        )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_all_five_percentage_table_rows,
        scenario_prompt_worked_examples_match_exactly,
        scenario_prompt_example_matches_exactly,
        scenario_unrecognized_position_size_yields_zero,
        scenario_missing_position_size_key_yields_zero,
        scenario_malformed_entry_yields_zero_never_raises,
        scenario_invalid_capital_behaves_like_zero,
        scenario_invalid_capital_never_raises,
        scenario_missing_capital_key_behaves_like_zero,
        scenario_valid_float_capital_is_accepted,
        scenario_empty_plans_list,
        scenario_missing_plans_key_never_raises,
        scenario_non_list_plans_never_raises,
        scenario_non_mapping_parameters_never_raises,
        scenario_allocation_entry_has_exactly_six_keys,
        scenario_fields_are_raw_not_normalized,
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