"""Phase 10 Sprint 133 proof suite -- PortfolioAlertSkill.

``PortfolioAlertSkill`` is the project's live-portfolio alert
formatter: it reads a list of already-produced portfolio-performance
entries (each carrying ``"symbol"``/``"capital"``/``"status"``/
``"monitor_status"``/``"performance"`` values, in the same shape
``PortfolioPerformanceSkill.execute()`` already produces) and converts
every entry, in order, into an ``{"alerts": [...]}`` output using the
locked rule table (``TRACKING -> "WATCH"``,
``COMPLETED -> "ARCHIVE"``, ``IDLE -> "HOLD"``,
``UNKNOWN -> "UNKNOWN"``, everything else -> ``"UNKNOWN"``). This
Skill never writes to a database, never persists anything to disk,
and never touches a network -- it only reads, in memory.

Scope: dedicated proof suite for
``Orchestration.portfolio_alert_skill.PortfolioAlertSkill`` only.
Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l132_portfolio_performance_skill.py``.

Invariant coverage:
    N1  -- TRACKING -> alert="WATCH".
    N2  -- COMPLETED -> alert="ARCHIVE".
    N3  -- IDLE -> alert="HOLD".
    N4  -- UNKNOWN -> alert="UNKNOWN".
    N5  -- an unrecognized performance value -> alert="UNKNOWN".
    N6  -- multiple entries are all converted, each exactly, in one
           pass.
    M1  -- a malformed (non-dict) performance entry yields
           symbol=None, capital=None, status=None,
           monitor_status=None, performance=None, alert="UNKNOWN",
           never raising.
    M2  -- an entry missing "performance" yields alert="UNKNOWN",
           never raising.
    E1  -- an empty "performance" list yields {"alerts": []},
           success=True.
    E2  -- a missing "performance" key yields {"alerts": []}, never
           raising.
    E3  -- a non-list "performance" value yields {"alerts": []},
           never raising.
    E4  -- parameters that are not a Mapping at all never raises,
           yields {"alerts": []}.
    S1  -- output shape: each alert entry has exactly the six keys
           symbol/capital/status/monitor_status/performance/alert,
           nothing more.
    S2  -- symbol/capital/status/monitor_status/performance values on
           the output entry are the exact raw values read from input,
           never normalized or transformed.
    S3  -- SkillResult shape: success=True, error=None, metadata={},
           output={"alerts": [...]}.
    S4  -- original input order is preserved.
    D1  -- repeated execute() calls with the same input are
           deterministic (field-equal SkillResults).
    A1  -- AST: exactly one SkillResult(...) construction.
    A2  -- AST: no forbidden-name symbol (Engine, Manager, Strategy,
           Planner, Workflow, Coordinator, Factory, Registry, Helper,
           Provider, Repository, Service, AlertEngine) anywhere in
           the module namespace.
    A3  -- AST: the module defines exactly one class,
           PortfolioAlertSkill, subclassing BaseSkill only.
    A4  -- class shape: no __init__ defined on PortfolioAlertSkill
           itself; no instance state after construction.
    A5  -- AST: execute() defines no nested function/lambda.
    A6  -- AST: no execute_tool()/execute_tool_result() call anywhere
           in the module; PortfolioAlertSkill never calls a Tool;
           module never imports Tool machinery or the legacy
           portfolio_engine module.
    A7  -- AST: no private (leading single-underscore, non-dunder)
           method, and no extra public method, defined on
           PortfolioAlertSkill beyond the three BaseSkill-required
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
from Orchestration.portfolio_alert_skill import PortfolioAlertSkill

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
    to prove PortfolioAlertSkill never touches any other
    attribute."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _performance_entry(symbol: Any, capital: Any, status: Any, monitor_status: Any, performance: Any) -> dict:
    return {
        "symbol": symbol,
        "capital": capital,
        "status": status,
        "monitor_status": monitor_status,
        "performance": performance,
    }


def _run(performance: Any) -> SkillResult:
    skill = PortfolioAlertSkill()
    return skill.execute(_FakeContext({"performance": performance}))


# ---------------------------------------------------------------------------
# N1-N6 -- rule table + normal conversion
# ---------------------------------------------------------------------------
def scenario_tracking_maps_to_watch() -> None:
    entry = _performance_entry("BBCA", 10_000_000, "OPEN", "ACTIVE", "TRACKING")
    result = _run([entry])
    alert_entry = result.output["alerts"][0]
    check(
        alert_entry == {"symbol": "BBCA", "capital": 10_000_000, "status": "OPEN", "monitor_status": "ACTIVE", "performance": "TRACKING", "alert": "WATCH"},
        f"N1: TRACKING -> WATCH; got {alert_entry!r}",
    )


def scenario_completed_maps_to_archive() -> None:
    entry = _performance_entry("BBCA", 50_000_000, "CLOSED", "FINISHED", "COMPLETED")
    result = _run([entry])
    alert_entry = result.output["alerts"][0]
    check(
        alert_entry == {"symbol": "BBCA", "capital": 50_000_000, "status": "CLOSED", "monitor_status": "FINISHED", "performance": "COMPLETED", "alert": "ARCHIVE"},
        f"N2: COMPLETED -> ARCHIVE; got {alert_entry!r}",
    )


def scenario_idle_maps_to_hold() -> None:
    entry = _performance_entry("BBB", 0, "NONE", "INACTIVE", "IDLE")
    result = _run([entry])
    alert_entry = result.output["alerts"][0]
    check(
        alert_entry == {"symbol": "BBB", "capital": 0, "status": "NONE", "monitor_status": "INACTIVE", "performance": "IDLE", "alert": "HOLD"},
        f"N3: IDLE -> HOLD; got {alert_entry!r}",
    )


def scenario_unknown_maps_to_unknown() -> None:
    entry = _performance_entry("CCC", 5, "SOMETHING", "WEIRD", "UNKNOWN")
    result = _run([entry])
    alert_entry = result.output["alerts"][0]
    check(
        alert_entry == {"symbol": "CCC", "capital": 5, "status": "SOMETHING", "monitor_status": "WEIRD", "performance": "UNKNOWN", "alert": "UNKNOWN"},
        f"N4: UNKNOWN -> UNKNOWN; got {alert_entry!r}",
    )


def scenario_unrecognized_performance_maps_to_unknown() -> None:
    entry = _performance_entry("DDD", 10, "SOMETHING_ELSE", "WEIRD_STATUS", "WHATEVER")
    result = _run([entry])
    alert_entry = result.output["alerts"][0]
    check(
        alert_entry == {"symbol": "DDD", "capital": 10, "status": "SOMETHING_ELSE", "monitor_status": "WEIRD_STATUS", "performance": "WHATEVER", "alert": "UNKNOWN"},
        f"N5: unrecognized performance -> UNKNOWN; got {alert_entry!r}",
    )


def scenario_multiple_entries_all_converted() -> None:
    entries = [
        _performance_entry("AAA", 100, "OPEN", "ACTIVE", "TRACKING"),
        _performance_entry("BBB", 0, "NONE", "INACTIVE", "IDLE"),
        _performance_entry("CCC", 50, "CLOSED", "FINISHED", "COMPLETED"),
        _performance_entry("DDD", 10, "WEIRD", "UNKNOWN", "UNKNOWN"),
        _performance_entry("EEE", 20, "WEIRD", "WEIRD", "SOMETHING_ELSE"),
    ]
    result = _run(entries)
    expected = [
        {"symbol": "AAA", "capital": 100, "status": "OPEN", "monitor_status": "ACTIVE", "performance": "TRACKING", "alert": "WATCH"},
        {"symbol": "BBB", "capital": 0, "status": "NONE", "monitor_status": "INACTIVE", "performance": "IDLE", "alert": "HOLD"},
        {"symbol": "CCC", "capital": 50, "status": "CLOSED", "monitor_status": "FINISHED", "performance": "COMPLETED", "alert": "ARCHIVE"},
        {"symbol": "DDD", "capital": 10, "status": "WEIRD", "monitor_status": "UNKNOWN", "performance": "UNKNOWN", "alert": "UNKNOWN"},
        {"symbol": "EEE", "capital": 20, "status": "WEIRD", "monitor_status": "WEIRD", "performance": "SOMETHING_ELSE", "alert": "UNKNOWN"},
    ]
    check(result.output["alerts"] == expected, f"N6: all entries converted exactly; got {result.output['alerts']!r}")


# ---------------------------------------------------------------------------
# M1-M2 -- malformed entries
# ---------------------------------------------------------------------------
def scenario_malformed_entry_yields_safe_default_never_raises() -> None:
    for entry in (None, "not-a-dict", 42, [1, 2, 3]):
        result = _run([entry])
        alert_entry = result.output["alerts"][0]
        check(
            alert_entry == {"symbol": None, "capital": None, "status": None, "monitor_status": None, "performance": None, "alert": "UNKNOWN"},
            f"M1: malformed entry {entry!r} -> safe default entry; got {alert_entry!r}",
        )


def scenario_missing_performance_never_raises() -> None:
    result = _run([{}])
    alert_entry = result.output["alerts"][0]
    check(
        alert_entry == {"symbol": None, "capital": None, "status": None, "monitor_status": None, "performance": None, "alert": "UNKNOWN"},
        f"M2: empty entry dict -> all-None entry with UNKNOWN; got {alert_entry!r}",
    )

    result = _run([{"symbol": "BBCA", "capital": 500, "status": "OPEN", "monitor_status": "ACTIVE"}])
    alert_entry = result.output["alerts"][0]
    check(alert_entry["symbol"] == "BBCA", "M2: present 'symbol' key preserved")
    check(alert_entry["capital"] == 500, "M2: present 'capital' key preserved")
    check(alert_entry["status"] == "OPEN", "M2: present 'status' key preserved")
    check(alert_entry["monitor_status"] == "ACTIVE", "M2: present 'monitor_status' key preserved")
    check(alert_entry["performance"] is None, "M2: missing 'performance' key -> None")
    check(alert_entry["alert"] == "UNKNOWN", "M2: missing 'performance' key -> alert UNKNOWN")


# ---------------------------------------------------------------------------
# E1-E4 -- empty/missing/malformed input
# ---------------------------------------------------------------------------
def scenario_empty_performance_list() -> None:
    result = _run([])
    check(result.output == {"alerts": []}, f"E1: empty performance -> {{'alerts': []}}; got {result.output!r}")
    check(result.success is True, "E1: success=True for empty performance")


def scenario_missing_performance_key_never_raises() -> None:
    skill = PortfolioAlertSkill()
    result = skill.execute(_FakeContext({}))
    check(result.output == {"alerts": []}, f"E2: missing 'performance' key -> {{'alerts': []}}; got {result.output!r}")


def scenario_non_list_performance_never_raises() -> None:
    skill = PortfolioAlertSkill()
    for bad_performance in (None, "not-a-list", 42, {"a": 1}):
        result = skill.execute(_FakeContext({"performance": bad_performance}))
        check(result.output == {"alerts": []}, f"E3: non-list performance {bad_performance!r} -> {{'alerts': []}}; got {result.output!r}")


def scenario_non_mapping_parameters_never_raises() -> None:
    skill = PortfolioAlertSkill()
    for bad_parameters in (None, "not-a-mapping", 42, ["a", "list"]):
        result = skill.execute(_FakeContext(bad_parameters))
        check(result.output == {"alerts": []}, f"E4: non-Mapping parameters {bad_parameters!r} -> {{'alerts': []}}; got {result.output!r}")
        check(result.success is True, f"E4: success=True for non-Mapping parameters {bad_parameters!r}")


# ---------------------------------------------------------------------------
# S1-S4 -- output shape
# ---------------------------------------------------------------------------
def scenario_alert_entry_has_exactly_six_keys() -> None:
    result = _run([_performance_entry("BBCA", 10_000_000, "OPEN", "ACTIVE", "TRACKING")])
    alert_entry = result.output["alerts"][0]
    check(
        set(alert_entry.keys()) == {"symbol", "capital", "status", "monitor_status", "performance", "alert"},
        f"S1: exactly six keys; got {set(alert_entry.keys())!r}",
    )


def scenario_fields_are_raw_not_normalized() -> None:
    entry = _performance_entry("bbca", 10_000_000, "open", "active", "tracking")
    result = _run([entry])
    alert_entry = result.output["alerts"][0]
    check(alert_entry["symbol"] == "bbca", f"S2: symbol unchanged; got {alert_entry['symbol']!r}")
    check(alert_entry["capital"] == 10_000_000, f"S2: capital unchanged; got {alert_entry['capital']!r}")
    check(alert_entry["status"] == "open", f"S2: status unchanged (raw, case-sensitive); got {alert_entry['status']!r}")
    check(alert_entry["monitor_status"] == "active", f"S2: monitor_status unchanged (raw, case-sensitive); got {alert_entry['monitor_status']!r}")
    check(alert_entry["performance"] == "tracking", f"S2: performance unchanged (raw, case-sensitive); got {alert_entry['performance']!r}")
    check(alert_entry["alert"] == "UNKNOWN", "S2: lowercase 'tracking' does not match rule table -> UNKNOWN")


def scenario_skill_result_shape() -> None:
    result = _run([_performance_entry("BBCA", 1, "OPEN", "ACTIVE", "TRACKING")])
    check(result.success is True, "S3: success=True")
    check(result.error is None, "S3: error=None")
    check(dict(result.metadata) == {}, f"S3: metadata={{}}; got {dict(result.metadata)!r}")
    check(isinstance(result.output, dict) and "alerts" in result.output, "S3: output is a dict with an 'alerts' key")


def scenario_original_input_order_preserved() -> None:
    entries = [
        _performance_entry("AAA", 100, "OPEN", "ACTIVE", "TRACKING"),
        _performance_entry("BBB", 0, "NONE", "INACTIVE", "IDLE"),
        _performance_entry("CCC", 50, "CLOSED", "FINISHED", "COMPLETED"),
        _performance_entry("DDD", 10, "WEIRD", "UNKNOWN", "UNKNOWN"),
    ]
    result = _run(entries)
    symbols = [e["symbol"] for e in result.output["alerts"]]
    check(symbols == ["AAA", "BBB", "CCC", "DDD"], f"S4: original order preserved; got {symbols!r}")


# ---------------------------------------------------------------------------
# D1 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    entries = [
        _performance_entry("AAA", 100, "OPEN", "ACTIVE", "TRACKING"),
        _performance_entry("BBB", 0, "NONE", "INACTIVE", "IDLE"),
        _performance_entry(None, None, None, None, None),
    ]
    first = _run(entries)
    second = _run(entries)
    check(first == second, f"D1: repeated execute() calls are deterministic; got {first!r} vs {second!r}")


# ---------------------------------------------------------------------------
# A1-A7 -- AST / structural verification
# ---------------------------------------------------------------------------
def scenario_exactly_one_skill_result_construction() -> None:
    import Orchestration.portfolio_alert_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")


def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.portfolio_alert_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_fragments = (
        "Engine", "Manager", "Strategy", "Planner", "Workflow",
        "Coordinator", "Factory", "Registry", "Helper",
        "Provider", "Repository", "Service", "AlertEngine",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A2: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )

    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = {n.name for n in class_defs}
    check(class_names == {"PortfolioAlertSkill"}, f"A3: module defines exactly one class; got {class_names!r}")


def scenario_class_subclasses_base_skill_only() -> None:
    check(issubclass(PortfolioAlertSkill, BaseSkill), "A3: PortfolioAlertSkill subclasses BaseSkill")
    check(PortfolioAlertSkill.__bases__ == (BaseSkill,), f"A3: PortfolioAlertSkill has exactly one base class, BaseSkill; got {PortfolioAlertSkill.__bases__!r}")


def scenario_no_init_no_instance_state() -> None:
    check("__init__" not in PortfolioAlertSkill.__dict__, "A4: PortfolioAlertSkill defines no __init__ of its own")
    skill = PortfolioAlertSkill()
    check(skill.__dict__ == {}, f"A4: PortfolioAlertSkill instances carry no instance state; got {skill.__dict__!r}")


def scenario_execute_has_no_nested_function() -> None:
    source = inspect.getsource(PortfolioAlertSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A5: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")


def scenario_no_tool_calls_anywhere() -> None:
    import Orchestration.portfolio_alert_skill as module

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
        "Orchestration.trade_history_skill", "Orchestration.portfolio_update_skill",
        "Orchestration.portfolio_monitor_skill", "Orchestration.portfolio_performance_skill",
        "Orchestration.portfolio_engine", "Orchestration.portfolio_analysis_skill",
        "Orchestration.portfolio_risk", "Orchestration.executor",
        "ToolResolver", "ToolRegistry", "ToolContext",
        "requests", "websocket", "asyncio", "threading",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"A6: module never imports {forbidden!r}")


def scenario_no_extra_public_or_private_methods() -> None:
    required_members = {"name", "description", "execute"}
    for attr_name, attr_value in PortfolioAlertSkill.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A7: no additional method/property defined on PortfolioAlertSkill beyond name/description/execute; found {attr_name!r}",
        )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_tracking_maps_to_watch,
        scenario_completed_maps_to_archive,
        scenario_idle_maps_to_hold,
        scenario_unknown_maps_to_unknown,
        scenario_unrecognized_performance_maps_to_unknown,
        scenario_multiple_entries_all_converted,
        scenario_malformed_entry_yields_safe_default_never_raises,
        scenario_missing_performance_never_raises,
        scenario_empty_performance_list,
        scenario_missing_performance_key_never_raises,
        scenario_non_list_performance_never_raises,
        scenario_non_mapping_parameters_never_raises,
        scenario_alert_entry_has_exactly_six_keys,
        scenario_fields_are_raw_not_normalized,
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