"""Phase 11 Sprint 136 proof suite -- VisionAnalysisSkill.

``VisionAnalysisSkill`` consumes the output of Sprint 135's
``ChartVisionSkill``: it reads ``context.parameters
["vision_request"]`` and produces a single, deterministic
``{"vision_analysis": {"symbol": ..., "timeframe": ..., "chart_path":
..., "status": ..., "analysis_status": ...}}`` output. This Skill
never calls Gemini, never calls Ollama, and never performs any image
inference -- it only derives ``analysis_status`` from ``status``, in
memory.

Scope: dedicated proof suite for
``Orchestration.vision_analysis_skill.VisionAnalysisSkill`` only.
Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l135_chart_vision_skill.py``.

Invariant coverage:
    N1  -- status="READY" -> analysis_status="PENDING".
    N2  -- symbol/timeframe/chart_path/status are preserved exactly
           as received on the READY path.
    N3  -- status="INVALID" -> analysis_status="INVALID".
    M1  -- status="SOMETHING_ELSE" -> analysis_status="UNKNOWN".
    M2  -- status missing entirely -> analysis_status="UNKNOWN".
    M3  -- status=None -> analysis_status="UNKNOWN".
    M4  -- vision_request missing entirely -> UNKNOWN object
           (symbol/timeframe/chart_path/status all None,
           analysis_status="UNKNOWN"), never raising.
    M5  -- vision_request not a Mapping (e.g. a list, a string, an
           int, None) -> UNKNOWN object, never raising.
    M6  -- non-Mapping context.parameters (e.g. a list, a string,
           None) -> UNKNOWN object, never raising.
    S1  -- output shape: exactly one top-level key
           "vision_analysis", whose value has exactly the five keys
           symbol/timeframe/chart_path/status/analysis_status,
           nothing more.
    S2  -- SkillResult shape: success=True, error=None, metadata={}.
    D1  -- repeated execute() calls with the same input are
           deterministic (field-equal SkillResults).
    A1  -- AST: exactly one SkillResult(...) construction.
    A2  -- AST: no forbidden-name symbol (VisionEngine, VisionManager,
           VisionProvider, Gemini, Ollama, Qwen, InternVL, Factory,
           Registry, Pipeline, Workflow, Coordinator, Helper,
           Repository, Service) anywhere in the module namespace.
    A3  -- AST: the module defines exactly one class,
           VisionAnalysisSkill, subclassing BaseSkill only.
    A4  -- class shape: no __init__ defined on VisionAnalysisSkill
           itself; no instance state after construction.
    A5  -- AST: execute() defines no nested function/lambda.
    A6  -- AST: no execute_tool()/execute_tool_result() call anywhere
           in the module; VisionAnalysisSkill never calls a Tool;
           module never imports Tool/image/inference/HTTP/filesystem
           machinery.
    A7  -- AST: no private (leading single-underscore, non-dunder)
           method, and no extra public method, defined on
           VisionAnalysisSkill beyond the three BaseSkill-required
           members.
    A8  -- AST: no os.path.exists() call, no file-open call, no
           requests-style HTTP call anywhere in the module.
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
from Orchestration.vision_analysis_skill import VisionAnalysisSkill

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
    to prove VisionAnalysisSkill never touches any other attribute."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _run(parameters: Any) -> SkillResult:
    skill = VisionAnalysisSkill()
    return skill.execute(_FakeContext(parameters))


# ---------------------------------------------------------------------------
# N1-N3 -- normal READY/INVALID paths
# ---------------------------------------------------------------------------
def scenario_ready_path() -> None:
    result = _run({
        "vision_request": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
        }
    })
    expected = {
        "vision_analysis": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
            "analysis_status": "PENDING",
        }
    }
    check(result.output == expected, f"N1: status=READY -> analysis_status=PENDING; got {result.output!r}")


def scenario_fields_preserved_exactly() -> None:
    result = _run({
        "vision_request": {
            "symbol": "BBRI",
            "timeframe": "4H",
            "chart_path": "charts/bbri.png",
            "status": "READY",
        }
    })
    vision_analysis = result.output["vision_analysis"]
    check(vision_analysis["symbol"] == "BBRI", "N2: symbol preserved exactly")
    check(vision_analysis["timeframe"] == "4H", "N2: timeframe preserved exactly")
    check(vision_analysis["chart_path"] == "charts/bbri.png", "N2: chart_path preserved exactly")
    check(vision_analysis["status"] == "READY", "N2: status preserved exactly")


def scenario_invalid_path() -> None:
    result = _run({
        "vision_request": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "",
            "status": "INVALID",
        }
    })
    check(
        result.output["vision_analysis"]["analysis_status"] == "INVALID",
        "N3: status=INVALID -> analysis_status=INVALID",
    )


# ---------------------------------------------------------------------------
# M1-M6 -- UNKNOWN paths, never raising
# ---------------------------------------------------------------------------
def scenario_unrecognized_status() -> None:
    result = _run({
        "vision_request": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "SOMETHING_ELSE",
        }
    })
    check(
        result.output["vision_analysis"]["analysis_status"] == "UNKNOWN",
        "M1: unrecognized status -> analysis_status=UNKNOWN",
    )


def scenario_missing_status() -> None:
    result = _run({
        "vision_request": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
        }
    })
    check(
        result.output["vision_analysis"]["analysis_status"] == "UNKNOWN",
        "M2: missing status -> analysis_status=UNKNOWN",
    )


def scenario_none_status() -> None:
    result = _run({
        "vision_request": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": None,
        }
    })
    check(
        result.output["vision_analysis"]["analysis_status"] == "UNKNOWN",
        "M3: status=None -> analysis_status=UNKNOWN",
    )


def scenario_missing_vision_request_entirely() -> None:
    result = _run({})
    vision_analysis = result.output["vision_analysis"]
    check(vision_analysis["analysis_status"] == "UNKNOWN", "M4: missing vision_request -> UNKNOWN")
    check(vision_analysis["symbol"] is None, "M4: missing vision_request -> symbol=None")
    check(vision_analysis["timeframe"] is None, "M4: missing vision_request -> timeframe=None")
    check(vision_analysis["chart_path"] is None, "M4: missing vision_request -> chart_path=None")
    check(vision_analysis["status"] is None, "M4: missing vision_request -> status=None")


def scenario_non_mapping_vision_request_never_raises() -> None:
    for bad_vision_request in (None, "not-a-mapping", 42, [1, 2, 3], object(), True):
        try:
            result = _run({"vision_request": bad_vision_request})
            raised = False
        except Exception:  # pragma: no cover - proving it never raises
            raised = True
            result = None
        check(not raised, f"M5: non-Mapping vision_request {bad_vision_request!r} never raises")
        if result is not None:
            vision_analysis = result.output["vision_analysis"]
            check(
                vision_analysis["analysis_status"] == "UNKNOWN",
                f"M5: non-Mapping vision_request {bad_vision_request!r} -> UNKNOWN",
            )
            check(
                vision_analysis["symbol"] is None
                and vision_analysis["timeframe"] is None
                and vision_analysis["chart_path"] is None
                and vision_analysis["status"] is None,
                f"M5: non-Mapping vision_request {bad_vision_request!r} -> all fields None",
            )


def scenario_non_mapping_parameters_never_raises() -> None:
    for bad_parameters in (None, "not-a-mapping", 42, [1, 2, 3], object()):
        try:
            result = _run(bad_parameters)
            raised = False
        except Exception:  # pragma: no cover - proving it never raises
            raised = True
            result = None
        check(not raised, f"M6: non-Mapping parameters {bad_parameters!r} never raises")
        if result is not None:
            check(
                result.output["vision_analysis"]["analysis_status"] == "UNKNOWN",
                f"M6: non-Mapping parameters {bad_parameters!r} -> UNKNOWN",
            )


# ---------------------------------------------------------------------------
# S1-S2 -- output/result shape
# ---------------------------------------------------------------------------
def scenario_output_shape_exact_keys() -> None:
    result = _run({
        "vision_request": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
        }
    })
    check(set(result.output.keys()) == {"vision_analysis"}, f"S1: exactly one top-level key; got {set(result.output.keys())!r}")
    vision_analysis = result.output["vision_analysis"]
    check(
        set(vision_analysis.keys()) == {"symbol", "timeframe", "chart_path", "status", "analysis_status"},
        f"S1: vision_analysis has exactly five keys; got {set(vision_analysis.keys())!r}",
    )


def scenario_skill_result_shape() -> None:
    result = _run({
        "vision_request": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
        }
    })
    check(result.success is True, "S2: success=True")
    check(result.error is None, "S2: error=None")
    check(dict(result.metadata) == {}, "S2: metadata={}")


# ---------------------------------------------------------------------------
# D1 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    parameters = {
        "vision_request": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
        }
    }
    result_a = _run(parameters)
    result_b = _run(parameters)
    check(result_a.output == result_b.output, "D1: repeated execution produces identical output")
    check(result_a.success == result_b.success, "D1: repeated execution produces identical success")
    check(result_a.error == result_b.error, "D1: repeated execution produces identical error")


# ---------------------------------------------------------------------------
# A1-A8 -- structural / AST verification
# ---------------------------------------------------------------------------
def scenario_exactly_one_skill_result_construction() -> None:
    import Orchestration.vision_analysis_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")


def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.vision_analysis_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_fragments = (
        "VisionEngine", "VisionManager", "VisionProvider", "Gemini",
        "Ollama", "Qwen", "InternVL", "Factory", "Registry", "Pipeline",
        "Workflow", "Coordinator", "Helper", "Repository", "Service",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A2: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )

    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = {n.name for n in class_defs}
    check(class_names == {"VisionAnalysisSkill"}, f"A3: module defines exactly one class; got {class_names!r}")


def scenario_class_subclasses_base_skill_only() -> None:
    check(issubclass(VisionAnalysisSkill, BaseSkill), "A3: VisionAnalysisSkill subclasses BaseSkill")
    check(VisionAnalysisSkill.__bases__ == (BaseSkill,), f"A3: VisionAnalysisSkill has exactly one base class, BaseSkill; got {VisionAnalysisSkill.__bases__!r}")


def scenario_no_init_no_instance_state() -> None:
    check("__init__" not in VisionAnalysisSkill.__dict__, "A4: VisionAnalysisSkill defines no __init__ of its own")
    skill = VisionAnalysisSkill()
    check(skill.__dict__ == {}, f"A4: VisionAnalysisSkill instances carry no instance state; got {skill.__dict__!r}")


def scenario_execute_has_no_nested_function() -> None:
    source = inspect.getsource(VisionAnalysisSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A5: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")


def scenario_no_tool_calls_anywhere() -> None:
    import Orchestration.vision_analysis_skill as module

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
        "google.generativeai", "genai", "ollama",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"A6: module never imports {forbidden!r}")


def scenario_no_extra_public_or_private_methods() -> None:
    required_members = {"name", "description", "execute"}
    for attr_name, attr_value in VisionAnalysisSkill.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A7: no additional method/property defined on VisionAnalysisSkill beyond name/description/execute; found {attr_name!r}",
        )


def scenario_no_filesystem_or_http_calls() -> None:
    import Orchestration.vision_analysis_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

    forbidden_direct_names = {"open"}
    direct_forbidden_calls = [
        c for c in calls
        if isinstance(c.func, ast.Name) and c.func.id in forbidden_direct_names
    ]
    check(len(direct_forbidden_calls) == 0, f"A8: no open() call; got {len(direct_forbidden_calls)}")

    forbidden_attr_names = {"exists"}
    forbidden_attr_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr in forbidden_attr_names
    ]
    check(len(forbidden_attr_calls) == 0, f"A8: no os.path.exists()-style call; got {len(forbidden_attr_calls)}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_ready_path,
        scenario_fields_preserved_exactly,
        scenario_invalid_path,
        scenario_unrecognized_status,
        scenario_missing_status,
        scenario_none_status,
        scenario_missing_vision_request_entirely,
        scenario_non_mapping_vision_request_never_raises,
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
        scenario_no_filesystem_or_http_calls,
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