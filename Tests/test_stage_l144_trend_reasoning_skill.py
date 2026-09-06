"""Phase 13 Sprint 144 proof suite -- TrendReasoningSkill.

``TrendReasoningSkill`` reads ``context.parameters
["vision_analysis"]`` (Sprint 143's ``VisionResponseParserSkill``
output) and produces a single, deterministic ``{"trend_reasoning":
{...}}`` output by matching the free-text ``trend`` field against a
fixed, case-insensitive substring rule table. Reasoning only -- no
trading decision, no BUY/SELL/WAIT, no scoring, no probability.

Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l143_vision_response_parser_skill.py``.

Coverage: N1-N4 bullish/bearish/sideways/range rules; N5 case
insensitivity; N6 substring/priority matching; N7 forwarded fields;
M1-M3 unmatched/missing/non-str trend -> UNKNOWN row; M4-M5 missing/
non-Mapping vision_analysis/parameters -> UNKNOWN row, never raising;
S1-S2 output/SkillResult shape; D1 determinism; F1 no forbidden
trading vocabulary in code; A1 AST/structural verification.
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
from Orchestration.trend_reasoning_skill import TrendReasoningSkill

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
    """A minimal context-like object exposing only ``.parameters``."""

    def __init__(self, parameters: Any):
        self.parameters = parameters

def _run(parameters: Any) -> SkillResult:
    return TrendReasoningSkill().execute(_FakeContext(parameters))

def _vision_analysis(trend: Any, **overrides: Any) -> dict:
    base = {"symbol": "BBCA", "timeframe": "1D", "trend": trend}
    base.update(overrides)
    return base

_UNKNOWN_ROW = {"trend_direction": None, "trend_strength": None, "trend_state": "UNKNOWN", "trend_reason": None}

def _check_row(tr: dict, expected: dict, tag: str) -> None:
    for key, value in expected.items():
        check(tr[key] == value, f"{tag}: {key}={value!r}; got {tr[key]!r}")

# N1-N7 -- normal rule-table paths
def scenario_bullish_rule() -> None:
    tr = _run({"vision_analysis": _vision_analysis("Bullish")}).output["trend_reasoning"]
    _check_row(tr, {
        "trend_direction": "UP", "trend_strength": "STRONG",
        "trend_state": "TRENDING", "trend_reason": "Bullish trend detected",
    }, "N1")

def scenario_bearish_rule() -> None:
    tr = _run({"vision_analysis": _vision_analysis("Bearish")}).output["trend_reasoning"]
    _check_row(tr, {
        "trend_direction": "DOWN", "trend_strength": "STRONG",
        "trend_state": "TRENDING", "trend_reason": "Bearish trend detected",
    }, "N2")

def scenario_sideways_rule() -> None:
    tr = _run({"vision_analysis": _vision_analysis("Sideways")}).output["trend_reasoning"]
    _check_row(tr, {
        "trend_direction": "SIDEWAYS", "trend_strength": "WEAK",
        "trend_state": "RANGING", "trend_reason": "Sideways market",
    }, "N3")

def scenario_range_rule() -> None:
    tr = _run({"vision_analysis": _vision_analysis("Range-bound")}).output["trend_reasoning"]
    _check_row(tr, {
        "trend_direction": "SIDEWAYS", "trend_strength": "WEAK",
        "trend_state": "RANGING", "trend_reason": "Range market",
    }, "N4")

def scenario_case_insensitive_matching() -> None:
    for text in ("BULLISH", "bullish", "BuLLiSh"):
        tr = _run({"vision_analysis": _vision_analysis(text)}).output["trend_reasoning"]
        check(tr["trend_direction"] == "UP", f"N5: case-insensitive match for {text!r}; got {tr['trend_direction']!r}")

def scenario_substring_and_priority() -> None:
    tr = _run({"vision_analysis": _vision_analysis("Strong Bullish Momentum Detected")}).output["trend_reasoning"]
    check(tr["trend_direction"] == "UP", f"N6: substring-anywhere match; got {tr['trend_direction']!r}")
    tr2 = _run({"vision_analysis": _vision_analysis("Bullish")}).output["trend_reasoning"]
    check(tr2["trend_reason"] == "Bullish trend detected", "N6: 'Bull' row wins when only bull text present")

def scenario_forwarded_fields_unchanged() -> None:
    tr = _run({"vision_analysis": _vision_analysis("Bullish", symbol="BBRI", timeframe="4H")}).output["trend_reasoning"]
    check(tr["symbol"] == "BBRI", "N7: symbol forwarded unchanged")
    check(tr["timeframe"] == "4H", "N7: timeframe forwarded unchanged")
    check(tr["trend"] == "Bullish", "N7: trend forwarded unchanged")

# M1-M5 -- unmatched / missing / malformed input
def scenario_unmatched_trend_text() -> None:
    for text in ("Choppy", "Unclear", ""):
        tr = _run({"vision_analysis": _vision_analysis(text)}).output["trend_reasoning"]
        _check_row(tr, _UNKNOWN_ROW, f"M1: unmatched trend {text!r}")

def scenario_missing_trend() -> None:
    va = _vision_analysis("placeholder")
    del va["trend"]
    tr = _run({"vision_analysis": va}).output["trend_reasoning"]
    check(tr["trend"] is None, "M2: trend is None when missing")
    _check_row(tr, _UNKNOWN_ROW, "M2: missing trend")

def scenario_non_str_trend() -> None:
    for bad in (42, ["Bullish"], True):
        tr = _run({"vision_analysis": _vision_analysis(bad)}).output["trend_reasoning"]
        check(tr["trend"] == bad, f"M3: non-str trend {bad!r} forwarded unchanged")
        check(tr["trend_state"] == "UNKNOWN", f"M3: non-str trend {bad!r} -> trend_state=UNKNOWN")

def scenario_vision_analysis_missing_or_not_mapping() -> None:
    tr = _run({}).output["trend_reasoning"]
    check(tr["symbol"] is None, "M4: symbol None when vision_analysis missing")
    _check_row(tr, _UNKNOWN_ROW, "M4: missing vision_analysis")

    for bad_value in ("a string", 42, None):
        tr = _run({"vision_analysis": bad_value}).output["trend_reasoning"]
        check(tr["symbol"] is None, f"M4: non-Mapping vision_analysis {bad_value!r} -> symbol None, never raising")
        check(tr["trend_state"] == "UNKNOWN", f"M4: non-Mapping vision_analysis {bad_value!r} -> trend_state=UNKNOWN")

def scenario_non_mapping_parameters_never_raises() -> None:
    for bad_parameters in ("a string", None, 42):
        tr = _run(bad_parameters).output["trend_reasoning"]
        check(tr["trend_state"] == "UNKNOWN", f"M5: non-Mapping context.parameters {bad_parameters!r}, never raising")

# S1-S2 -- output / SkillResult shape
def scenario_output_and_skill_result_shape() -> None:
    result = _run({"vision_analysis": _vision_analysis("Bullish")})
    check(set(result.output.keys()) == {"trend_reasoning"}, f"S1: exactly one top-level key; got {set(result.output.keys())!r}")
    expected_keys = {"symbol", "timeframe", "trend", "trend_direction", "trend_strength", "trend_state", "trend_reason"}
    got_keys = set(result.output["trend_reasoning"].keys())
    check(got_keys == expected_keys, f"S1: trend_reasoning has exactly seven keys; got {got_keys!r}")
    check(result.success is True, "S2: success=True")
    check(result.error is None, "S2: error=None")
    check(dict(result.metadata) == {}, "S2: metadata={}")

# D1 -- determinism
def scenario_repeated_execution_is_deterministic() -> None:
    params = {"vision_analysis": _vision_analysis("Bearish")}
    result_a = _run(params)
    result_b = _run(params)
    check(result_a.output == result_b.output, "D1: repeated execution produces identical output")
    check(result_a.success == result_b.success, "D1: repeated execution produces identical success")
    check(result_a.error == result_b.error, "D1: repeated execution produces identical error")

# F1 -- forbidden trading vocabulary
def scenario_no_forbidden_trading_vocabulary() -> None:
    """Scans the module's executable code (not its prose docstrings,
    which legitimately name these terms to document that they are
    forbidden) for BUY/SELL-style trading vocabulary."""
    import Orchestration.trend_reasoning_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body[0].value = ast.Constant(value="")

    code_only_source = ast.unparse(tree)
    forbidden_terms = (
        "BUY", "SELL", "WAIT", "ENTRY", "EXIT", "STOP LOSS", "TAKE PROFIT",
        "POSITION SIZE", "CAPITAL", "ORDER", "PORTFOLIO",
    )
    all_absent = all(term not in code_only_source.upper() for term in forbidden_terms)
    check(all_absent, f"F1: no forbidden trading vocabulary {forbidden_terms!r} in module code (excluding docstrings)")

# A1 -- AST / structural verification
def scenario_ast_structural_verification() -> None:
    import Orchestration.trend_reasoning_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"TrendReasoningSkill"}, f"A1: module defines exactly one class; got {class_names!r}")
    check(
        TrendReasoningSkill.__bases__ == (BaseSkill,),
        f"A1: subclasses exactly BaseSkill; got {TrendReasoningSkill.__bases__!r}",
    )

    check("__init__" not in TrendReasoningSkill.__dict__, "A1: no __init__ defined")
    check(TrendReasoningSkill().__dict__ == {}, "A1: instances carry no instance state")

    exec_tree = ast.parse(textwrap.dedent(inspect.getsource(TrendReasoningSkill.execute)))
    top_level_def = exec_tree.body[0]
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A1: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    forbidden_tool_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr in ("execute_tool", "execute_tool_result")
    ]
    check(len(forbidden_tool_calls) == 0, "A1: module never calls execute_tool()/execute_tool_result()")

    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.add(node.module or "")
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
    forbidden_imports = (
        "json", "re", "os", "pathlib", "PIL", "cv2", "requests", "sqlite3",
        "pandas", "numpy", "genai", "ollama", "Orchestration.tool_resolver",
        "Orchestration.tool_registry", "Orchestration.base_tool", "Orchestration.executor",
    )
    check(
        imported_names.isdisjoint(forbidden_imports),
        f"A1: no forbidden import present; got overlap {imported_names & set(forbidden_imports)!r}",
    )

    required_members = {"name", "description", "execute"}
    extra_members = [
        attr_name for attr_name, attr_value in TrendReasoningSkill.__dict__.items()
        if attr_name not in required_members
        and not (attr_name.startswith("__") and attr_name.endswith("__"))
        and (callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property)))
    ]
    check(extra_members == [], f"A1: no extra public/private method beyond name/description/execute; found {extra_members!r}")

# main
def main() -> int:
    scenarios = [
        scenario_bullish_rule,
        scenario_bearish_rule,
        scenario_sideways_rule,
        scenario_range_rule,
        scenario_case_insensitive_matching,
        scenario_substring_and_priority,
        scenario_forwarded_fields_unchanged,
        scenario_unmatched_trend_text,
        scenario_missing_trend,
        scenario_non_str_trend,
        scenario_vision_analysis_missing_or_not_mapping,
        scenario_non_mapping_parameters_never_raises,
        scenario_output_and_skill_result_shape,
        scenario_repeated_execution_is_deterministic,
        scenario_no_forbidden_trading_vocabulary,
        scenario_ast_structural_verification,
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