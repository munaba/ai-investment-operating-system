"""Phase 13 Sprint 148 proof suite -- SupportResistanceReasoningSkill.

``SupportResistanceReasoningSkill`` reads ``context.parameters[
"vision_analysis"]`` (Sprint 143's ``VisionResponseParserSkill``
output) and produces a single, deterministic ``{
"support_resistance_reasoning": {...}}`` output by checking the
free-text ``support``/``resistance`` fields for mere non-empty-string
presence -- no numeric parsing, no float conversion, no validation of
contents. Reasoning only -- no trading decision, no recommendation, no
scoring.

Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l147_candlestick_reasoning_skill.py``.

Coverage: N1 both present; N2 support missing; N3 resistance missing;
N4 both missing; N5 empty strings; N6 whitespace-only strings; N7
non-string values; N8 forwarded fields; M1 malformed vision_analysis;
M2 non-Mapping parameters; D1 determinism; S1-S2 output/SkillResult
shape; F1 no forbidden trading vocabulary; A1 AST/structural
verification.
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
from Orchestration.support_resistance_reasoning_skill import SupportResistanceReasoningSkill

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
    return SupportResistanceReasoningSkill().execute(_FakeContext(parameters))

def _vision_analysis(support: Any, resistance: Any, **overrides: Any) -> dict:
    base = {
        "symbol": "BBCA", "timeframe": "1D",
        "support": support, "resistance": resistance,
    }
    base.update(overrides)
    return base

_DEFINED_ROW = {
    "level_state": "DEFINED", "level_strength": "KNOWN",
    "level_reason": "Support and resistance identified", "evidence": "LEVELS_PRESENT",
}
_UNKNOWN_ROW = {
    "level_state": "UNKNOWN", "level_strength": None,
    "level_reason": None, "evidence": "UNKNOWN",
}

def _check_row(sr: dict, expected: dict, tag: str) -> None:
    for key, value in expected.items():
        check(sr[key] == value, f"{tag}: {key}={value!r}; got {sr[key]!r}")

# N1-N8 -- normal rule-table paths
def scenario_both_present() -> None:
    sr = _run({"vision_analysis": _vision_analysis("15000", "15500")}).output["support_resistance_reasoning"]
    _check_row(sr, _DEFINED_ROW, "N1")

def scenario_support_missing() -> None:
    va = _vision_analysis(None, "15500")
    del va["support"]
    sr = _run({"vision_analysis": va}).output["support_resistance_reasoning"]
    check(sr["support"] is None, "N2: support is None when missing")
    _check_row(sr, _UNKNOWN_ROW, "N2: missing support -> UNKNOWN")

def scenario_resistance_missing() -> None:
    va = _vision_analysis("15000", None)
    del va["resistance"]
    sr = _run({"vision_analysis": va}).output["support_resistance_reasoning"]
    check(sr["resistance"] is None, "N3: resistance is None when missing")
    _check_row(sr, _UNKNOWN_ROW, "N3: missing resistance -> UNKNOWN")

def scenario_both_missing() -> None:
    va = _vision_analysis(None, None)
    del va["support"]
    del va["resistance"]
    sr = _run({"vision_analysis": va}).output["support_resistance_reasoning"]
    check(sr["support"] is None, "N4: support is None when missing")
    check(sr["resistance"] is None, "N4: resistance is None when missing")
    _check_row(sr, _UNKNOWN_ROW, "N4: both missing -> UNKNOWN")

def scenario_empty_strings() -> None:
    for support, resistance in (("", "15500"), ("15000", "")):
        sr = _run({"vision_analysis": _vision_analysis(support, resistance)}).output["support_resistance_reasoning"]
        _check_row(sr, _UNKNOWN_ROW, f"N5: empty string(s) support={support!r} resistance={resistance!r} -> UNKNOWN")

def scenario_whitespace_only_strings() -> None:
    for support, resistance in (("   ", "15500"), ("15000", "\t\n")):
        sr = _run({"vision_analysis": _vision_analysis(support, resistance)}).output["support_resistance_reasoning"]
        _check_row(sr, _UNKNOWN_ROW, f"N6: whitespace-only support={support!r} resistance={resistance!r} -> UNKNOWN")

def scenario_non_string_values() -> None:
    for bad in (42, ["15000"]):
        sr = _run({"vision_analysis": _vision_analysis(bad, "15500")}).output["support_resistance_reasoning"]
        check(sr["support"] == bad, f"N7: non-str support {bad!r} forwarded unchanged")
        _check_row(sr, _UNKNOWN_ROW, f"N7: non-str support {bad!r} -> UNKNOWN")

        sr = _run({"vision_analysis": _vision_analysis("15000", bad)}).output["support_resistance_reasoning"]
        check(sr["resistance"] == bad, f"N7: non-str resistance {bad!r} forwarded unchanged")
        _check_row(sr, _UNKNOWN_ROW, f"N7: non-str resistance {bad!r} -> UNKNOWN")

def scenario_forwarded_fields_unchanged() -> None:
    sr = _run({"vision_analysis": _vision_analysis("15000", "15500", symbol="BBRI", timeframe="4H")}).output["support_resistance_reasoning"]
    check(sr["symbol"] == "BBRI", "N8: symbol forwarded unchanged")
    check(sr["timeframe"] == "4H", "N8: timeframe forwarded unchanged")
    check(sr["support"] == "15000", "N8: support forwarded unchanged")
    check(sr["resistance"] == "15500", "N8: resistance forwarded unchanged")

# M1-M2 -- malformed input
def scenario_vision_analysis_missing_or_not_mapping() -> None:
    sr = _run({}).output["support_resistance_reasoning"]
    check(sr["symbol"] is None, "M1: symbol None when vision_analysis missing")
    _check_row(sr, _UNKNOWN_ROW, "M1: missing vision_analysis -> UNKNOWN")

    for bad_value in ("a string", 42):
        sr = _run({"vision_analysis": bad_value}).output["support_resistance_reasoning"]
        check(sr["symbol"] is None, f"M1: non-Mapping vision_analysis {bad_value!r} -> symbol None, never raising")
        _check_row(sr, _UNKNOWN_ROW, f"M1: non-Mapping vision_analysis {bad_value!r} -> UNKNOWN")

def scenario_non_mapping_parameters_never_raises() -> None:
    for bad_parameters in ("a string", None):
        sr = _run(bad_parameters).output["support_resistance_reasoning"]
        _check_row(sr, _UNKNOWN_ROW, f"M2: non-Mapping context.parameters {bad_parameters!r}, never raising")

# S1-S2 -- output / SkillResult shape
def scenario_output_and_skill_result_shape() -> None:
    result = _run({"vision_analysis": _vision_analysis("15000", "15500")})
    check(set(result.output.keys()) == {"support_resistance_reasoning"}, f"S1: exactly one top-level key; got {set(result.output.keys())!r}")
    expected_keys = {
        "symbol", "timeframe", "support", "resistance", "level_state",
        "level_strength", "level_reason", "evidence",
    }
    got_keys = set(result.output["support_resistance_reasoning"].keys())
    check(got_keys == expected_keys, f"S1: support_resistance_reasoning has exactly eight keys; got {got_keys!r}")
    check(result.success is True, "S2: success=True")
    check(result.error is None, "S2: error=None")
    check(dict(result.metadata) == {}, "S2: metadata={}")

# D1 -- determinism
def scenario_repeated_execution_is_deterministic() -> None:
    params = {"vision_analysis": _vision_analysis("15000", "15500")}
    result_a = _run(params)
    result_b = _run(params)
    check(result_a.output == result_b.output, "D1: repeated execution produces identical output")
    check(result_a.success == result_b.success, "D1: repeated execution produces identical success")
    check(result_a.error == result_b.error, "D1: repeated execution produces identical error")

# F1 -- forbidden trading vocabulary
def scenario_no_forbidden_trading_vocabulary() -> None:
    """Scans code only, not docstrings, for trading vocabulary."""
    import Orchestration.support_resistance_reasoning_skill as module

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
        "POSITION SIZE", "CAPITAL", "PORTFOLIO", "ORDER", "RISK",
        "MARKET PREDICTION", "SCORE",
    )
    all_absent = all(term not in code_only_source.upper() for term in forbidden_terms)
    check(all_absent, f"F1: no forbidden trading vocabulary {forbidden_terms!r} in module code (excluding docstrings)")

# A1 -- AST / structural verification
def scenario_ast_structural_verification() -> None:
    import Orchestration.support_resistance_reasoning_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"SupportResistanceReasoningSkill"}, f"A1: module defines exactly one class; got {class_names!r}")
    check(SupportResistanceReasoningSkill.__bases__ == (BaseSkill,), f"A1: subclasses exactly BaseSkill; got {SupportResistanceReasoningSkill.__bases__!r}")

    check("__init__" not in SupportResistanceReasoningSkill.__dict__, "A1: no __init__ defined")
    check(SupportResistanceReasoningSkill().__dict__ == {}, "A1: instances carry no instance state")

    exec_tree = ast.parse(textwrap.dedent(inspect.getsource(SupportResistanceReasoningSkill.execute)))
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
    check(imported_names.isdisjoint(forbidden_imports), f"A1: no forbidden import; overlap {imported_names & set(forbidden_imports)!r}")

    required_members = {"name", "description", "execute"}
    extra_members = [
        attr_name for attr_name, attr_value in SupportResistanceReasoningSkill.__dict__.items()
        if attr_name not in required_members
        and not (attr_name.startswith("__") and attr_name.endswith("__"))
        and (callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property)))
    ]
    check(extra_members == [], f"A1: no extra public/private method beyond name/description/execute; found {extra_members!r}")

# main
def main() -> int:
    scenarios = [
        scenario_both_present,
        scenario_support_missing,
        scenario_resistance_missing,
        scenario_both_missing,
        scenario_empty_strings,
        scenario_whitespace_only_strings,
        scenario_non_string_values,
        scenario_forwarded_fields_unchanged,
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