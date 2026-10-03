"""Phase 11 Sprint 135 proof suite -- ChartVisionSkill.

``ChartVisionSkill`` is the project's first AI Vision capability
foundation: it reads ``context.parameters["symbol"]``,
``context.parameters["timeframe"]``, and ``context.parameters
["chart_path"]`` and produces a single, deterministic
``{"vision_request": {"symbol": ..., "timeframe": ..., "chart_path":
..., "status": ...}}`` output. This Skill never calls an LLM, never
performs AI inference, and never reads, opens, or decodes any image
file -- it only validates the input contract, in memory.

Scope: dedicated proof suite for
``Orchestration.chart_vision_skill.ChartVisionSkill`` only. Mirrors
the compact, table-driven, no-pytest, global-counter-plus-``main()``
style already used by
``Tests/test_stage_l134_portfolio_report_skill.py``.

Invariant coverage:
    N1  -- a well-formed, non-empty string chart_path ->
           status="READY".
    N2  -- symbol/timeframe/chart_path are preserved exactly as
           received on the READY path.
    M1  -- a missing chart_path -> status="INVALID", never raising.
    M2  -- an empty-string chart_path -> status="INVALID".
    M3  -- chart_path=None -> status="INVALID".
    M4  -- chart_path=True (bool) -> status="INVALID".
    M5  -- chart_path=123 (int) -> status="INVALID".
    M6  -- chart_path=[] (list) -> status="INVALID".
    M7  -- missing parameters entirely (empty dict) ->
           status="INVALID", symbol/timeframe=None, never raising.
    M8  -- non-Mapping parameters (e.g. a list, a string, None) ->
           status="INVALID", never raising.
    S1  -- output shape: exactly one top-level key
           "vision_request", whose value has exactly the four keys
           symbol/timeframe/chart_path/status, nothing more.
    S2  -- SkillResult shape: success=True, error=None, metadata={}.
    D1  -- repeated execute() calls with the same input are
           deterministic (field-equal SkillResults).
    A1  -- AST: exactly one SkillResult(...) construction.
    A2  -- AST: no forbidden-name symbol (VisionEngine, VisionManager,
           ChartLoader, ImageLoader, ImageReader, Pipeline, Workflow,
           Coordinator, Provider, Repository, Service, Factory,
           Registry, Helper) anywhere in the module namespace.
    A3  -- AST: the module defines exactly one class,
           ChartVisionSkill, subclassing BaseSkill only.
    A4  -- class shape: no __init__ defined on ChartVisionSkill
           itself; no instance state after construction.
    A5  -- AST: execute() defines no nested function/lambda.
    A6  -- AST: no execute_tool()/execute_tool_result() call anywhere
           in the module; ChartVisionSkill never calls a Tool; module
           never imports Tool/image/inference machinery.
    A7  -- AST: no private (leading single-underscore, non-dunder)
           method, and no extra public method, defined on
           ChartVisionSkill beyond the three BaseSkill-required
           members.
    A8  -- AST: no os.path.exists() call, no file-open call anywhere
           in the module.
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
from Orchestration.chart_vision_skill import ChartVisionSkill

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
    to prove ChartVisionSkill never touches any other attribute."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _run(parameters: Any) -> SkillResult:
    skill = ChartVisionSkill()
    return skill.execute(_FakeContext(parameters))


# ---------------------------------------------------------------------------
# N1-N2 -- normal READY path
# ---------------------------------------------------------------------------
def scenario_ready_path() -> None:
    result = _run({"symbol": "BBCA", "timeframe": "1D", "chart_path": "charts/bbca.png"})
    expected = {
        "vision_request": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
        }
    }
    check(result.output == expected, f"N1: valid chart_path -> READY; got {result.output!r}")


def scenario_fields_preserved_exactly() -> None:
    result = _run({"symbol": "BBRI", "timeframe": "4H", "chart_path": "charts/bbri.png"})
    vision_request = result.output["vision_request"]
    check(vision_request["symbol"] == "BBRI", "N2: symbol preserved exactly")
    check(vision_request["timeframe"] == "4H", "N2: timeframe preserved exactly")
    check(vision_request["chart_path"] == "charts/bbri.png", "N2: chart_path preserved exactly")


# ---------------------------------------------------------------------------
# M1-M8 -- INVALID paths, never raising
# ---------------------------------------------------------------------------
def scenario_missing_chart_path() -> None:
    result = _run({"symbol": "BBCA", "timeframe": "1D"})
    check(result.output["vision_request"]["status"] == "INVALID", "M1: missing chart_path -> INVALID")


def scenario_empty_string_chart_path() -> None:
    result = _run({"symbol": "BBCA", "timeframe": "1D", "chart_path": ""})
    check(result.output["vision_request"]["status"] == "INVALID", "M2: empty string chart_path -> INVALID")


def scenario_none_chart_path() -> None:
    result = _run({"symbol": "BBCA", "timeframe": "1D", "chart_path": None})
    check(result.output["vision_request"]["status"] == "INVALID", "M3: None chart_path -> INVALID")


def scenario_bool_chart_path() -> None:
    result = _run({"symbol": "BBCA", "timeframe": "1D", "chart_path": True})
    check(result.output["vision_request"]["status"] == "INVALID", "M4: bool chart_path -> INVALID")


def scenario_int_chart_path() -> None:
    result = _run({"symbol": "BBCA", "timeframe": "1D", "chart_path": 123})
    check(result.output["vision_request"]["status"] == "INVALID", "M5: int chart_path -> INVALID")


def scenario_list_chart_path() -> None:
    result = _run({"symbol": "BBCA", "timeframe": "1D", "chart_path": []})
    check(result.output["vision_request"]["status"] == "INVALID", "M6: list chart_path -> INVALID")


def scenario_missing_parameters_entirely() -> None:
    result = _run({})
    vision_request = result.output["vision_request"]
    check(vision_request["status"] == "INVALID", "M7: empty parameters -> INVALID")
    check(vision_request["symbol"] is None, "M7: missing symbol -> None")
    check(vision_request["timeframe"] is None, "M7: missing timeframe -> None")
    check(vision_request["chart_path"] is None, "M7: missing chart_path -> None")


def scenario_non_mapping_parameters_never_raises() -> None:
    for bad_parameters in (None, "not-a-mapping", 42, [1, 2, 3], object()):
        try:
            result = _run(bad_parameters)
            raised = False
        except Exception as exc:  # pragma: no cover - proving it never raises
            raised = True
            result = None
        check(not raised, f"M8: non-Mapping parameters {bad_parameters!r} never raises")
        if result is not None:
            check(
                result.output["vision_request"]["status"] == "INVALID",
                f"M8: non-Mapping parameters {bad_parameters!r} -> INVALID",
            )


# ---------------------------------------------------------------------------
# S1-S2 -- output/result shape
# ---------------------------------------------------------------------------
def scenario_output_shape_exact_keys() -> None:
    result = _run({"symbol": "BBCA", "timeframe": "1D", "chart_path": "charts/bbca.png"})
    check(set(result.output.keys()) == {"vision_request"}, f"S1: exactly one top-level key; got {set(result.output.keys())!r}")
    vision_request = result.output["vision_request"]
    check(
        set(vision_request.keys()) == {"symbol", "timeframe", "chart_path", "status"},
        f"S1: vision_request has exactly four keys; got {set(vision_request.keys())!r}",
    )


def scenario_skill_result_shape() -> None:
    result = _run({"symbol": "BBCA", "timeframe": "1D", "chart_path": "charts/bbca.png"})
    check(result.success is True, "S2: success=True")
    check(result.error is None, "S2: error=None")
    check(dict(result.metadata) == {}, "S2: metadata={}")


# ---------------------------------------------------------------------------
# D1 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    parameters = {"symbol": "BBCA", "timeframe": "1D", "chart_path": "charts/bbca.png"}
    result_a = _run(parameters)
    result_b = _run(parameters)
    check(result_a.output == result_b.output, "D1: repeated execution produces identical output")
    check(result_a.success == result_b.success, "D1: repeated execution produces identical success")
    check(result_a.error == result_b.error, "D1: repeated execution produces identical error")


# ---------------------------------------------------------------------------
# A1-A8 -- structural / AST verification
# ---------------------------------------------------------------------------
def scenario_exactly_one_skill_result_construction() -> None:
    import Orchestration.chart_vision_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")


def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.chart_vision_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_fragments = (
        "VisionEngine", "VisionManager", "ChartLoader", "ImageLoader",
        "ImageReader", "Pipeline", "Workflow", "Coordinator", "Provider",
        "Repository", "Service", "Factory", "Registry", "Helper",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A2: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )

    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = {n.name for n in class_defs}
    check(class_names == {"ChartVisionSkill"}, f"A3: module defines exactly one class; got {class_names!r}")


def scenario_class_subclasses_base_skill_only() -> None:
    check(issubclass(ChartVisionSkill, BaseSkill), "A3: ChartVisionSkill subclasses BaseSkill")
    check(ChartVisionSkill.__bases__ == (BaseSkill,), f"A3: ChartVisionSkill has exactly one base class, BaseSkill; got {ChartVisionSkill.__bases__!r}")


def scenario_no_init_no_instance_state() -> None:
    check("__init__" not in ChartVisionSkill.__dict__, "A4: ChartVisionSkill defines no __init__ of its own")
    skill = ChartVisionSkill()
    check(skill.__dict__ == {}, f"A4: ChartVisionSkill instances carry no instance state; got {skill.__dict__!r}")


def scenario_execute_has_no_nested_function() -> None:
    source = inspect.getsource(ChartVisionSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A5: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")


def scenario_no_tool_calls_anywhere() -> None:
    import Orchestration.chart_vision_skill as module

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
        "Orchestration.executor",
        "ToolResolver", "ToolRegistry", "ToolContext",
        "os", "os.path", "pathlib", "PIL", "cv2", "matplotlib",
        "requests", "sqlite3", "pandas", "numpy", "yfinance",
        "websocket", "asyncio", "threading",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"A6: module never imports {forbidden!r}")


def scenario_no_extra_public_or_private_methods() -> None:
    required_members = {"name", "description", "execute"}
    for attr_name, attr_value in ChartVisionSkill.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A7: no additional method/property defined on ChartVisionSkill beyond name/description/execute; found {attr_name!r}",
        )


def scenario_no_filesystem_or_file_open_calls() -> None:
    import Orchestration.chart_vision_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

    forbidden_direct_names = {"open"}
    direct_forbidden_calls = [
        c for c in calls
        if isinstance(c.func, ast.Name) and c.func.id in forbidden_direct_names
    ]
    check(len(direct_forbidden_calls) == 0, f"A8: no open() call; got {len(direct_forbidden_calls)}")

    forbidden_attr_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr == "exists"
    ]
    check(len(forbidden_attr_calls) == 0, f"A8: no os.path.exists()-style call; got {len(forbidden_attr_calls)}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_ready_path,
        scenario_fields_preserved_exactly,
        scenario_missing_chart_path,
        scenario_empty_string_chart_path,
        scenario_none_chart_path,
        scenario_bool_chart_path,
        scenario_int_chart_path,
        scenario_list_chart_path,
        scenario_missing_parameters_entirely,
        scenario_non_mapping_parameters_never_raises,
        scenario_output_shape_exact_keys,
        scenario_skill_result_shape,
        scenario_repeated_execution_is_deterministic,
        scenario_exactly_one_skill_result_construction,
        scenario_no_forbidden_abstractions,
        scenario_class_subclasses_base_skill_only,
        scenario_no_init_no_instance_state,
        scenario_execute_has_no_nested_function,
        scenario_no_tool_calls_anywhere,
        scenario_no_extra_public_or_private_methods,
        scenario_no_filesystem_or_file_open_calls,
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