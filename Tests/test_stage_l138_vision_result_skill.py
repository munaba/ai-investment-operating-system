"""Phase 11 Sprint 138 proof suite -- VisionResultSkill.

``VisionResultSkill`` consumes the output of Sprint 137's
``VisionPromptSkill``: it reads ``context.parameters
["vision_prompt"]`` and produces a single, deterministic
``{"vision_result": {"symbol": ..., "timeframe": ..., "chart_path":
..., "status": ..., "analysis_status": ..., "prompt_status": ...,
"result_status": ..., "result": {...}}}`` output. This Skill never
calls Gemini, never calls Ollama, and never performs any image
inference -- it only derives ``result_status`` from ``prompt_status``
and attaches a fixed, all-``None`` ``result`` object, in memory.

Scope: dedicated proof suite for
``Orchestration.vision_result_skill.VisionResultSkill`` only. Mirrors
the compact, table-driven, no-pytest, global-counter-plus-``main()``
style already used by
``Tests/test_stage_l137_vision_prompt_skill.py``.

Invariant coverage:
    N1  -- prompt_status="READY" -> result_status="WAITING".
    N2  -- symbol/timeframe/chart_path/status/analysis_status/
           prompt_status are preserved exactly as received on the
           WAITING path.
    N3  -- prompt_status="INVALID" -> result_status="INVALID".
    N4  -- result object is byte-for-byte identical to the locked
           all-None, eight-key shape.
    M1  -- prompt_status="SOMETHING_ELSE" -> result_status="UNKNOWN".
    M2  -- prompt_status missing entirely -> result_status="UNKNOWN".
    M3  -- prompt_status=None -> result_status="UNKNOWN".
    M4  -- vision_prompt missing entirely -> UNKNOWN object
           (symbol/timeframe/chart_path/status/analysis_status/
           prompt_status all None, result_status="UNKNOWN"), never
           raising; result object still attached unchanged.
    M5  -- vision_prompt not a Mapping (e.g. a list, a string, an
           int, None) -> UNKNOWN object, never raising.
    M6  -- non-Mapping context.parameters (e.g. a list, a string,
           None) -> UNKNOWN object, never raising.
    S1  -- output shape: exactly one top-level key "vision_result",
           whose value has exactly the eight keys symbol/timeframe/
           chart_path/status/analysis_status/prompt_status/
           result_status/result, nothing more.
    S2  -- result object shape: exactly the eight keys trend/support/
           resistance/candlestick_pattern/volume_signal/rsi_signal/
           macd_signal/confidence, every value None, nothing more.
    S3  -- SkillResult shape: success=True, error=None, metadata={}.
    D1  -- repeated execute() calls with the same input are
           deterministic (field-equal SkillResults).
    D2  -- result object is identical across differing inputs
           (WAITING vs. INVALID vs. UNKNOWN paths).
    A1  -- AST: exactly one SkillResult(...) construction.
    A2  -- AST: no forbidden-name symbol (Gemini, Ollama, Qwen,
           InternVL, MiniCPM, Llama, VisionProvider, PromptBuilder,
           PromptEngine, Factory, Registry, Pipeline, Workflow,
           Coordinator, Helper, Repository, Service) anywhere in the
           module namespace.
    A3  -- AST: the module defines exactly one class,
           VisionResultSkill, subclassing BaseSkill only.
    A4  -- class shape: no __init__ defined on VisionResultSkill
           itself; no instance state after construction.
    A5  -- AST: execute() defines no nested function/lambda.
    A6  -- AST: no execute_tool()/execute_tool_result() call anywhere
           in the module; VisionResultSkill never calls a Tool;
           module never imports Tool/image/inference/HTTP/filesystem
           machinery.
    A7  -- AST: no private (leading single-underscore, non-dunder)
           method, and no extra public method, defined on
           VisionResultSkill beyond the three BaseSkill-required
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
from Orchestration.vision_result_skill import VisionResultSkill

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []

_EXPECTED_RESULT = {
    "trend": None,
    "support": None,
    "resistance": None,
    "candlestick_pattern": None,
    "volume_signal": None,
    "rsi_signal": None,
    "macd_signal": None,
    "confidence": None,
}


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
    to prove VisionResultSkill never touches any other attribute."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _run(parameters: Any) -> SkillResult:
    skill = VisionResultSkill()
    return skill.execute(_FakeContext(parameters))


# ---------------------------------------------------------------------------
# N1-N4 -- normal WAITING/INVALID paths
# ---------------------------------------------------------------------------
def scenario_waiting_path() -> None:
    result = _run({
        "vision_prompt": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
            "analysis_status": "PENDING",
            "prompt_status": "READY",
        }
    })
    expected = {
        "vision_result": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
            "analysis_status": "PENDING",
            "prompt_status": "READY",
            "result_status": "WAITING",
            "result": _EXPECTED_RESULT,
        }
    }
    check(result.output == expected, f"N1: prompt_status=READY -> result_status=WAITING; got {result.output!r}")


def scenario_fields_preserved_exactly() -> None:
    result = _run({
        "vision_prompt": {
            "symbol": "BBRI",
            "timeframe": "4H",
            "chart_path": "charts/bbri.png",
            "status": "READY",
            "analysis_status": "PENDING",
            "prompt_status": "READY",
        }
    })
    vision_result = result.output["vision_result"]
    check(vision_result["symbol"] == "BBRI", "N2: symbol preserved exactly")
    check(vision_result["timeframe"] == "4H", "N2: timeframe preserved exactly")
    check(vision_result["chart_path"] == "charts/bbri.png", "N2: chart_path preserved exactly")
    check(vision_result["status"] == "READY", "N2: status preserved exactly")
    check(vision_result["analysis_status"] == "PENDING", "N2: analysis_status preserved exactly")
    check(vision_result["prompt_status"] == "READY", "N2: prompt_status preserved exactly")


def scenario_invalid_path() -> None:
    result = _run({
        "vision_prompt": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "",
            "status": "INVALID",
            "analysis_status": "INVALID",
            "prompt_status": "INVALID",
        }
    })
    check(
        result.output["vision_result"]["result_status"] == "INVALID",
        "N3: prompt_status=INVALID -> result_status=INVALID",
    )


def scenario_result_object_is_byte_for_byte_identical() -> None:
    result = _run({
        "vision_prompt": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
            "analysis_status": "PENDING",
            "prompt_status": "READY",
        }
    })
    check(
        result.output["vision_result"]["result"] == _EXPECTED_RESULT,
        "N4: result object is byte-for-byte identical to the locked spec shape",
    )


# ---------------------------------------------------------------------------
# M1-M6 -- malformed / missing input
# ---------------------------------------------------------------------------
def scenario_unrecognized_prompt_status() -> None:
    result = _run({
        "vision_prompt": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
            "analysis_status": "PENDING",
            "prompt_status": "SOMETHING_ELSE",
        }
    })
    check(
        result.output["vision_result"]["result_status"] == "UNKNOWN",
        "M1: unrecognized prompt_status -> result_status=UNKNOWN",
    )


def scenario_missing_prompt_status() -> None:
    result = _run({
        "vision_prompt": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
            "analysis_status": "PENDING",
        }
    })
    check(
        result.output["vision_result"]["result_status"] == "UNKNOWN",
        "M2: missing prompt_status -> result_status=UNKNOWN",
    )


def scenario_none_prompt_status() -> None:
    result = _run({
        "vision_prompt": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
            "analysis_status": "PENDING",
            "prompt_status": None,
        }
    })
    check(
        result.output["vision_result"]["result_status"] == "UNKNOWN",
        "M3: prompt_status=None -> result_status=UNKNOWN",
    )


def scenario_missing_vision_prompt_entirely() -> None:
    result = _run({})
    vision_result = result.output["vision_result"]
    check(vision_result["symbol"] is None, "M4: symbol is None when vision_prompt missing")
    check(vision_result["timeframe"] is None, "M4: timeframe is None when vision_prompt missing")
    check(vision_result["chart_path"] is None, "M4: chart_path is None when vision_prompt missing")
    check(vision_result["status"] is None, "M4: status is None when vision_prompt missing")
    check(vision_result["analysis_status"] is None, "M4: analysis_status is None when vision_prompt missing")
    check(vision_result["prompt_status"] is None, "M4: prompt_status is None when vision_prompt missing")
    check(vision_result["result_status"] == "UNKNOWN", "M4: result_status=UNKNOWN when vision_prompt missing")
    check(vision_result["result"] == _EXPECTED_RESULT, "M4: result object still attached unchanged")


def scenario_non_mapping_vision_prompt_never_raises() -> None:
    for bad_value in (["a", "list"], "a string", 42, None, 3.14, True):
        result = _run({"vision_prompt": bad_value})
        vision_result = result.output["vision_result"]
        check(
            vision_result["result_status"] == "UNKNOWN",
            f"M5: non-Mapping vision_prompt {bad_value!r} -> result_status=UNKNOWN, never raising",
        )
        check(
            vision_result["symbol"] is None,
            f"M5: non-Mapping vision_prompt {bad_value!r} -> symbol=None",
        )


def scenario_non_mapping_parameters_never_raises() -> None:
    for bad_parameters in (["a", "list"], "a string", None, 42, 3.14):
        result = _run(bad_parameters)
        vision_result = result.output["vision_result"]
        check(
            vision_result["result_status"] == "UNKNOWN",
            f"M6: non-Mapping context.parameters {bad_parameters!r} -> result_status=UNKNOWN, never raising",
        )
        check(
            vision_result["result"] == _EXPECTED_RESULT,
            f"M6: non-Mapping context.parameters {bad_parameters!r} -> result object still attached unchanged",
        )


# ---------------------------------------------------------------------------
# S1-S3 -- output / SkillResult shape
# ---------------------------------------------------------------------------
def scenario_output_shape_exact_keys() -> None:
    result = _run({
        "vision_prompt": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
            "analysis_status": "PENDING",
            "prompt_status": "READY",
        }
    })
    check(set(result.output.keys()) == {"vision_result"}, f"S1: exactly one top-level key 'vision_result'; got {set(result.output.keys())!r}")
    vision_result_keys = set(result.output["vision_result"].keys())
    expected_keys = {
        "symbol", "timeframe", "chart_path", "status", "analysis_status",
        "prompt_status", "result_status", "result",
    }
    check(vision_result_keys == expected_keys, f"S1: vision_result has exactly the eight expected keys; got {vision_result_keys!r}")


def scenario_result_object_shape_exact_keys() -> None:
    result = _run({
        "vision_prompt": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
            "analysis_status": "PENDING",
            "prompt_status": "READY",
        }
    })
    result_obj = result.output["vision_result"]["result"]
    expected_keys = {
        "trend", "support", "resistance", "candlestick_pattern",
        "volume_signal", "rsi_signal", "macd_signal", "confidence",
    }
    check(set(result_obj.keys()) == expected_keys, f"S2: result object has exactly the eight expected keys; got {set(result_obj.keys())!r}")
    check(all(value is None for value in result_obj.values()), "S2: every value in the result object is None")


def scenario_skill_result_shape() -> None:
    result = _run({
        "vision_prompt": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
            "analysis_status": "PENDING",
            "prompt_status": "READY",
        }
    })
    check(result.success is True, "S3: success is True")
    check(result.error is None, "S3: error is None")
    check(dict(result.metadata) == {}, "S3: metadata is empty")


# ---------------------------------------------------------------------------
# D1-D2 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    parameters = {
        "vision_prompt": {
            "symbol": "BBCA",
            "timeframe": "1D",
            "chart_path": "charts/bbca.png",
            "status": "READY",
            "analysis_status": "PENDING",
            "prompt_status": "READY",
        }
    }
    result_a = _run(parameters)
    result_b = _run(parameters)
    check(result_a.output == result_b.output, "D1: repeated execution produces identical output")
    check(result_a.success == result_b.success, "D1: repeated execution produces identical success")
    check(result_a.error == result_b.error, "D1: repeated execution produces identical error")


def scenario_result_identical_across_differing_inputs() -> None:
    waiting = _run({
        "vision_prompt": {
            "symbol": "BBCA", "timeframe": "1D", "chart_path": "charts/bbca.png",
            "status": "READY", "analysis_status": "PENDING", "prompt_status": "READY",
        }
    })
    invalid = _run({
        "vision_prompt": {
            "symbol": "BBRI", "timeframe": "4H", "chart_path": "",
            "status": "INVALID", "analysis_status": "INVALID", "prompt_status": "INVALID",
        }
    })
    unknown = _run({})
    check(
        waiting.output["vision_result"]["result"]
        == invalid.output["vision_result"]["result"]
        == unknown.output["vision_result"]["result"]
        == _EXPECTED_RESULT,
        "D2: result object is identical across WAITING/INVALID/UNKNOWN paths",
    )


# ---------------------------------------------------------------------------
# A1-A8 -- structural / AST verification
# ---------------------------------------------------------------------------
def scenario_exactly_one_skill_result_construction() -> None:
    import Orchestration.vision_result_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")


def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.vision_result_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    forbidden_fragments = (
        "Gemini", "Ollama", "Qwen", "InternVL", "MiniCPM", "Llama",
        "VisionProvider", "VisionEngine", "PromptBuilder", "PromptEngine",
        "Factory", "Registry", "Pipeline", "Workflow", "Coordinator",
        "Helper", "Repository", "Service",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A2: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )

    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = {n.name for n in class_defs}
    check(class_names == {"VisionResultSkill"}, f"A3: module defines exactly one class; got {class_names!r}")


def scenario_class_subclasses_base_skill_only() -> None:
    check(issubclass(VisionResultSkill, BaseSkill), "A3: VisionResultSkill subclasses BaseSkill")
    check(VisionResultSkill.__bases__ == (BaseSkill,), f"A3: VisionResultSkill has exactly one base class, BaseSkill; got {VisionResultSkill.__bases__!r}")


def scenario_no_init_no_instance_state() -> None:
    check("__init__" not in VisionResultSkill.__dict__, "A4: VisionResultSkill defines no __init__ of its own")
    skill = VisionResultSkill()
    check(skill.__dict__ == {}, f"A4: VisionResultSkill instances carry no instance state; got {skill.__dict__!r}")


def scenario_execute_has_no_nested_function() -> None:
    source = inspect.getsource(VisionResultSkill.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A5: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")


def scenario_no_tool_calls_anywhere() -> None:
    import Orchestration.vision_result_skill as module

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
        "websocket", "asyncio", "threading", "json",
        "google.generativeai", "genai", "ollama",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"A6: module never imports {forbidden!r}")


def scenario_no_extra_public_or_private_methods() -> None:
    required_members = {"name", "description", "execute"}
    for attr_name, attr_value in VisionResultSkill.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A7: no additional method/property defined on VisionResultSkill beyond name/description/execute; found {attr_name!r}",
        )


def scenario_no_filesystem_or_http_calls() -> None:
    import Orchestration.vision_result_skill as module

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
        scenario_waiting_path,
        scenario_fields_preserved_exactly,
        scenario_invalid_path,
        scenario_result_object_is_byte_for_byte_identical,
        scenario_unrecognized_prompt_status,
        scenario_missing_prompt_status,
        scenario_none_prompt_status,
        scenario_missing_vision_prompt_entirely,
        scenario_non_mapping_vision_prompt_never_raises,
        scenario_non_mapping_parameters_never_raises,
        scenario_output_shape_exact_keys,
        scenario_result_object_shape_exact_keys,
        scenario_skill_result_shape,
        scenario_repeated_execution_is_deterministic,
        scenario_result_identical_across_differing_inputs,
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