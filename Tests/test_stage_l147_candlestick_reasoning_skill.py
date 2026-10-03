"""Phase 13 Sprint 147 proof suite -- CandlestickReasoningSkill.

``CandlestickReasoningSkill`` reads ``context.parameters
["vision_analysis"]`` (Sprint 143's ``VisionResponseParserSkill``
output) and produces a single, deterministic ``{"candlestick_reasoning":
{...}}`` output by matching the free-text ``candlestick_pattern`` field
against a fixed, case-insensitive, whitespace-tolerant substring rule
table. Reasoning only -- no trading decision, no recommendation, no
scoring.

Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l145_momentum_reasoning_skill.py``.

Coverage: N1-N5 Hammer/Morning/Shooting/Evening/unknown; N6 CASE 1
priority; N7 case/whitespace tolerance; N8 forwarded fields; M1 missing
pattern -> UNKNOWN; M2 non-str pattern -> UNKNOWN; M3-M4 missing/
non-Mapping vision_analysis/parameters -> UNKNOWN, never raising; S1-S2
output/SkillResult shape; D1 determinism; F1 no forbidden trading
vocabulary in code; A1 AST/structural verification.
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
from Orchestration.candlestick_reasoning_skill import CandlestickReasoningSkill

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
    return CandlestickReasoningSkill().execute(_FakeContext(parameters))

def _vision_analysis(candlestick_pattern: Any, **overrides: Any) -> dict:
    base = {"symbol": "BBCA", "timeframe": "1D", "candlestick_pattern": candlestick_pattern}
    base.update(overrides)
    return base

_BULLISH_ROW = {
    "pattern_bias": "BULLISH", "pattern_strength": "STRONG",
    "pattern_reason": "Bullish reversal pattern", "evidence": "BULLISH_PATTERN",
}
_BEARISH_ROW = {
    "pattern_bias": "BEARISH", "pattern_strength": "STRONG",
    "pattern_reason": "Bearish reversal pattern", "evidence": "BEARISH_PATTERN",
}
_UNKNOWN_ROW = {
    "pattern_bias": "UNKNOWN", "pattern_strength": None,
    "pattern_reason": None, "evidence": "UNKNOWN",
}

def _check_row(cr: dict, expected: dict, tag: str) -> None:
    for key, value in expected.items():
        check(cr[key] == value, f"{tag}: {key}={value!r}; got {cr[key]!r}")

# N1-N8 -- normal rule-table paths
def scenario_bullish_via_hammer() -> None:
    cr = _run({"vision_analysis": _vision_analysis("Hammer")}).output["candlestick_reasoning"]
    _check_row(cr, _BULLISH_ROW, "N1")

def scenario_bullish_via_morning_star() -> None:
    cr = _run({"vision_analysis": _vision_analysis("Morning Star")}).output["candlestick_reasoning"]
    _check_row(cr, _BULLISH_ROW, "N2")

def scenario_bearish_via_shooting_star() -> None:
    cr = _run({"vision_analysis": _vision_analysis("Shooting Star")}).output["candlestick_reasoning"]
    _check_row(cr, _BEARISH_ROW, "N3")

def scenario_bearish_via_evening_star() -> None:
    cr = _run({"vision_analysis": _vision_analysis("Evening Star")}).output["candlestick_reasoning"]
    _check_row(cr, _BEARISH_ROW, "N4")

def scenario_unknown_pattern() -> None:
    for pattern in ("Doji", "Spinning Top", "Marubozu"):
        cr = _run({"vision_analysis": _vision_analysis(pattern)}).output["candlestick_reasoning"]
        _check_row(cr, _UNKNOWN_ROW, f"N5: unmatched pattern {pattern!r}")

def scenario_case1_priority_over_case2() -> None:
    cr = _run({"vision_analysis": _vision_analysis("Hammer near Shooting Star zone")}).output["candlestick_reasoning"]
    _check_row(cr, _BULLISH_ROW, "N6: CASE 1 wins when both Hammer and Shooting substrings present")

def scenario_case_insensitive_and_whitespace_tolerant() -> None:
    for pattern in ("HAMMER", "  hammer  ", "HamMer", "MORNING star", "  Morning  "):
        cr = _run({"vision_analysis": _vision_analysis(pattern)}).output["candlestick_reasoning"]
        check(cr["pattern_bias"] == "BULLISH", f"N7: case/whitespace-tolerant match for {pattern!r}; got {cr['pattern_bias']!r}")
    for pattern in ("SHOOTING", "  shooting star  ", "EVENING Star"):
        cr = _run({"vision_analysis": _vision_analysis(pattern)}).output["candlestick_reasoning"]
        check(cr["pattern_bias"] == "BEARISH", f"N7: case/whitespace-tolerant match for {pattern!r}; got {cr['pattern_bias']!r}")

def scenario_forwarded_fields_unchanged() -> None:
    cr = _run({"vision_analysis": _vision_analysis("Hammer", symbol="BBRI", timeframe="4H")}).output["candlestick_reasoning"]
    check(cr["symbol"] == "BBRI", "N8: symbol forwarded unchanged")
    check(cr["timeframe"] == "4H", "N8: timeframe forwarded unchanged")
    check(cr["candlestick_pattern"] == "Hammer", "N8: candlestick_pattern forwarded unchanged")

# M1-M4 -- missing / malformed input
def scenario_missing_pattern_unknown() -> None:
    va = _vision_analysis(None)
    del va["candlestick_pattern"]
    cr = _run({"vision_analysis": va}).output["candlestick_reasoning"]
    check(cr["candlestick_pattern"] is None, "M1: candlestick_pattern is None when missing")
    _check_row(cr, _UNKNOWN_ROW, "M1: missing candlestick_pattern -> UNKNOWN")

def scenario_non_str_pattern() -> None:
    for bad in (42, ["Hammer"], True, 3.14):
        cr = _run({"vision_analysis": _vision_analysis(bad)}).output["candlestick_reasoning"]
        check(cr["candlestick_pattern"] == bad, f"M2: non-str candlestick_pattern {bad!r} forwarded unchanged")
        check(cr["pattern_bias"] == "UNKNOWN", f"M2: non-str candlestick_pattern {bad!r} -> pattern_bias=UNKNOWN")

def scenario_vision_analysis_missing_or_not_mapping() -> None:
    cr = _run({}).output["candlestick_reasoning"]
    check(cr["symbol"] is None, "M3: symbol None when vision_analysis missing")
    _check_row(cr, _UNKNOWN_ROW, "M3: missing vision_analysis")

    for bad_value in ("a string", 42, None):
        cr = _run({"vision_analysis": bad_value}).output["candlestick_reasoning"]
        check(cr["symbol"] is None, f"M3: non-Mapping vision_analysis {bad_value!r} -> symbol None, never raising")
        check(cr["pattern_bias"] == "UNKNOWN", f"M3: non-Mapping vision_analysis {bad_value!r} -> UNKNOWN")

def scenario_non_mapping_parameters_never_raises() -> None:
    for bad_parameters in ("a string", None, 42):
        cr = _run(bad_parameters).output["candlestick_reasoning"]
        check(cr["pattern_bias"] == "UNKNOWN", f"M4: non-Mapping context.parameters {bad_parameters!r}, never raising")

# S1-S2 -- output / SkillResult shape
def scenario_output_and_skill_result_shape() -> None:
    result = _run({"vision_analysis": _vision_analysis("Hammer")})
    check(set(result.output.keys()) == {"candlestick_reasoning"}, f"S1: exactly one top-level key; got {set(result.output.keys())!r}")
    expected_keys = {
        "symbol", "timeframe", "candlestick_pattern", "pattern_bias",
        "pattern_strength", "pattern_reason", "evidence",
    }
    got_keys = set(result.output["candlestick_reasoning"].keys())
    check(got_keys == expected_keys, f"S1: candlestick_reasoning has exactly seven keys; got {got_keys!r}")
    check(result.success is True, "S2: success=True")
    check(result.error is None, "S2: error=None")
    check(dict(result.metadata) == {}, "S2: metadata={}")

# D1 -- determinism
def scenario_repeated_execution_is_deterministic() -> None:
    params = {"vision_analysis": _vision_analysis("Hammer near Shooting Star zone")}
    result_a = _run(params)
    result_b = _run(params)
    check(result_a.output == result_b.output, "D1: repeated execution produces identical output")
    check(result_a.success == result_b.success, "D1: repeated execution produces identical success")
    check(result_a.error == result_b.error, "D1: repeated execution produces identical error")

# F1 -- forbidden trading vocabulary
def scenario_no_forbidden_trading_vocabulary() -> None:
    """Scans code only, not docstrings, for trading vocabulary."""
    import Orchestration.candlestick_reasoning_skill as module

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
    import Orchestration.candlestick_reasoning_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"CandlestickReasoningSkill"}, f"A1: module defines exactly one class; got {class_names!r}")
    check(CandlestickReasoningSkill.__bases__ == (BaseSkill,), f"A1: subclasses exactly BaseSkill; got {CandlestickReasoningSkill.__bases__!r}")

    check("__init__" not in CandlestickReasoningSkill.__dict__, "A1: no __init__ defined")
    check(CandlestickReasoningSkill().__dict__ == {}, "A1: instances carry no instance state")

    exec_tree = ast.parse(textwrap.dedent(inspect.getsource(CandlestickReasoningSkill.execute)))
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
        attr_name for attr_name, attr_value in CandlestickReasoningSkill.__dict__.items()
        if attr_name not in required_members
        and not (attr_name.startswith("__") and attr_name.endswith("__"))
        and (callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property)))
    ]
    check(extra_members == [], f"A1: no extra public/private method beyond name/description/execute; found {extra_members!r}")

# main
def main() -> int:
    scenarios = [
        scenario_bullish_via_hammer,
        scenario_bullish_via_morning_star,
        scenario_bearish_via_shooting_star,
        scenario_bearish_via_evening_star,
        scenario_unknown_pattern,
        scenario_case1_priority_over_case2,
        scenario_case_insensitive_and_whitespace_tolerant,
        scenario_forwarded_fields_unchanged,
        scenario_missing_pattern_unknown,
        scenario_non_str_pattern,
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