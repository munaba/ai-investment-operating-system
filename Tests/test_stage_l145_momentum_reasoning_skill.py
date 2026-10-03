"""Phase 13 Sprint 145 proof suite -- MomentumReasoningSkill.

``MomentumReasoningSkill`` reads ``context.parameters
["vision_analysis"]`` (Sprint 143's ``VisionResponseParserSkill``
output) and produces a single, deterministic ``{"momentum_reasoning":
{...}}`` output by matching the free-text ``rsi_signal``/
``macd_signal`` fields against a fixed, case-insensitive,
whitespace-tolerant substring rule table. Reasoning only -- no
trading decision, no recommendation, no scoring.

Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l144_trend_reasoning_skill.py``.

Coverage: N1-N4 bearish/bullish via RSI/MACD; N5 CASE 1 priority; N6
case/whitespace tolerance; N7 forwarded fields; M1-M3 missing RSI/
MACD/both -> partial or UNKNOWN; M4 non-str signals -> UNKNOWN; M5-M6
missing/non-Mapping vision_analysis/parameters -> UNKNOWN, never
raising; S1-S2 output/SkillResult shape; D1 determinism; F1 no
forbidden trading vocabulary in code; A1 AST/structural verification.
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
from Orchestration.momentum_reasoning_skill import MomentumReasoningSkill

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
    return MomentumReasoningSkill().execute(_FakeContext(parameters))

def _vision_analysis(rsi_signal: Any, macd_signal: Any, **overrides: Any) -> dict:
    base = {"symbol": "BBCA", "timeframe": "1D", "rsi_signal": rsi_signal, "macd_signal": macd_signal}
    base.update(overrides)
    return base

_BEARISH_ROW = {
    "momentum_direction": "DOWN", "momentum_strength": "STRONG",
    "momentum_state": "BEARISH", "momentum_reason": "Negative momentum detected", "evidence": "BEARISH",
}
_BULLISH_ROW = {
    "momentum_direction": "UP", "momentum_strength": "STRONG",
    "momentum_state": "BULLISH", "momentum_reason": "Positive momentum detected", "evidence": "BULLISH",
}
_UNKNOWN_ROW = {
    "momentum_direction": None, "momentum_strength": None,
    "momentum_state": "UNKNOWN", "momentum_reason": None, "evidence": "UNKNOWN",
}

def _check_row(mr: dict, expected: dict, tag: str) -> None:
    for key, value in expected.items():
        check(mr[key] == value, f"{tag}: {key}={value!r}; got {mr[key]!r}")

# N1-N7 -- normal rule-table paths
def scenario_bearish_via_rsi_overbought() -> None:
    mr = _run({"vision_analysis": _vision_analysis("Overbought", "Neutral")}).output["momentum_reasoning"]
    _check_row(mr, _BEARISH_ROW, "N1")

def scenario_bearish_via_macd_bear() -> None:
    mr = _run({"vision_analysis": _vision_analysis("Neutral", "Bearish Crossover")}).output["momentum_reasoning"]
    _check_row(mr, _BEARISH_ROW, "N2")

def scenario_bullish_via_rsi_oversold() -> None:
    mr = _run({"vision_analysis": _vision_analysis("Oversold", "Neutral")}).output["momentum_reasoning"]
    _check_row(mr, _BULLISH_ROW, "N3")

def scenario_bullish_via_macd_bull() -> None:
    mr = _run({"vision_analysis": _vision_analysis("Neutral", "Bullish Crossover")}).output["momentum_reasoning"]
    _check_row(mr, _BULLISH_ROW, "N4")

def scenario_case1_priority_over_case2() -> None:
    mr = _run({"vision_analysis": _vision_analysis("Overbought", "Bullish Crossover")}).output["momentum_reasoning"]
    _check_row(mr, _BEARISH_ROW, "N5: CASE 1 wins when both RSI-overbought and MACD-bull present")

def scenario_case_insensitive_and_whitespace_tolerant() -> None:
    for rsi in ("OVERBOUGHT", "  overbought  ", "OverBought"):
        mr = _run({"vision_analysis": _vision_analysis(rsi, "Neutral")}).output["momentum_reasoning"]
        check(mr["momentum_state"] == "BEARISH", f"N6: case/whitespace-tolerant match for {rsi!r}; got {mr['momentum_state']!r}")

def scenario_forwarded_fields_unchanged() -> None:
    mr = _run({"vision_analysis": _vision_analysis("Overbought", "Neutral", symbol="BBRI", timeframe="4H")}).output["momentum_reasoning"]
    check(mr["symbol"] == "BBRI", "N7: symbol forwarded unchanged")
    check(mr["timeframe"] == "4H", "N7: timeframe forwarded unchanged")
    check(mr["rsi_signal"] == "Overbought", "N7: rsi_signal forwarded unchanged")
    check(mr["macd_signal"] == "Neutral", "N7: macd_signal forwarded unchanged")

# M1-M6 -- missing / malformed input
def scenario_missing_rsi_macd_only_case() -> None:
    va = _vision_analysis(None, "Bullish Crossover")
    del va["rsi_signal"]
    mr = _run({"vision_analysis": va}).output["momentum_reasoning"]
    check(mr["rsi_signal"] is None, "M1: rsi_signal is None when missing")
    _check_row(mr, _BULLISH_ROW, "M1: missing RSI, MACD-only bullish still resolves")

def scenario_missing_macd_rsi_only_case() -> None:
    va = _vision_analysis("Oversold", None)
    del va["macd_signal"]
    mr = _run({"vision_analysis": va}).output["momentum_reasoning"]
    check(mr["macd_signal"] is None, "M2: macd_signal is None when missing")
    _check_row(mr, _BULLISH_ROW, "M2: missing MACD, RSI-only bullish still resolves")

def scenario_both_missing_unknown() -> None:
    va = _vision_analysis(None, None)
    del va["rsi_signal"]
    del va["macd_signal"]
    mr = _run({"vision_analysis": va}).output["momentum_reasoning"]
    _check_row(mr, _UNKNOWN_ROW, "M3: both signals missing -> UNKNOWN")

def scenario_non_str_signals() -> None:
    for bad in (42, ["Overbought"], True):
        mr = _run({"vision_analysis": _vision_analysis(bad, bad)}).output["momentum_reasoning"]
        check(mr["rsi_signal"] == bad, f"M4: non-str rsi_signal {bad!r} forwarded unchanged")
        check(mr["momentum_state"] == "UNKNOWN", f"M4: non-str signals {bad!r} -> momentum_state=UNKNOWN")

def scenario_vision_analysis_missing_or_not_mapping() -> None:
    mr = _run({}).output["momentum_reasoning"]
    check(mr["symbol"] is None, "M5: symbol None when vision_analysis missing")
    _check_row(mr, _UNKNOWN_ROW, "M5: missing vision_analysis")

    for bad_value in ("a string", 42, None):
        mr = _run({"vision_analysis": bad_value}).output["momentum_reasoning"]
        check(mr["symbol"] is None, f"M5: non-Mapping vision_analysis {bad_value!r} -> symbol None, never raising")
        check(mr["momentum_state"] == "UNKNOWN", f"M5: non-Mapping vision_analysis {bad_value!r} -> UNKNOWN")

def scenario_non_mapping_parameters_never_raises() -> None:
    for bad_parameters in ("a string", None, 42):
        mr = _run(bad_parameters).output["momentum_reasoning"]
        check(mr["momentum_state"] == "UNKNOWN", f"M6: non-Mapping context.parameters {bad_parameters!r}, never raising")

# S1-S2 -- output / SkillResult shape
def scenario_output_and_skill_result_shape() -> None:
    result = _run({"vision_analysis": _vision_analysis("Overbought", "Neutral")})
    check(set(result.output.keys()) == {"momentum_reasoning"}, f"S1: exactly one top-level key; got {set(result.output.keys())!r}")
    expected_keys = {
        "symbol", "timeframe", "rsi_signal", "macd_signal", "momentum_direction",
        "momentum_strength", "momentum_state", "momentum_reason", "evidence",
    }
    got_keys = set(result.output["momentum_reasoning"].keys())
    check(got_keys == expected_keys, f"S1: momentum_reasoning has exactly nine keys; got {got_keys!r}")
    check(result.success is True, "S2: success=True")
    check(result.error is None, "S2: error=None")
    check(dict(result.metadata) == {}, "S2: metadata={}")

# D1 -- determinism
def scenario_repeated_execution_is_deterministic() -> None:
    params = {"vision_analysis": _vision_analysis("Overbought", "Bullish Crossover")}
    result_a = _run(params)
    result_b = _run(params)
    check(result_a.output == result_b.output, "D1: repeated execution produces identical output")
    check(result_a.success == result_b.success, "D1: repeated execution produces identical success")
    check(result_a.error == result_b.error, "D1: repeated execution produces identical error")

# F1 -- forbidden trading vocabulary
def scenario_no_forbidden_trading_vocabulary() -> None:
    """Scans code only, not docstrings, for trading vocabulary."""
    import Orchestration.momentum_reasoning_skill as module

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
    import Orchestration.momentum_reasoning_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"MomentumReasoningSkill"}, f"A1: module defines exactly one class; got {class_names!r}")
    check(MomentumReasoningSkill.__bases__ == (BaseSkill,), f"A1: subclasses exactly BaseSkill; got {MomentumReasoningSkill.__bases__!r}")

    check("__init__" not in MomentumReasoningSkill.__dict__, "A1: no __init__ defined")
    check(MomentumReasoningSkill().__dict__ == {}, "A1: instances carry no instance state")

    exec_tree = ast.parse(textwrap.dedent(inspect.getsource(MomentumReasoningSkill.execute)))
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
        attr_name for attr_name, attr_value in MomentumReasoningSkill.__dict__.items()
        if attr_name not in required_members
        and not (attr_name.startswith("__") and attr_name.endswith("__"))
        and (callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property)))
    ]
    check(extra_members == [], f"A1: no extra public/private method beyond name/description/execute; found {extra_members!r}")

# main
def main() -> int:
    scenarios = [
        scenario_bearish_via_rsi_overbought,
        scenario_bearish_via_macd_bear,
        scenario_bullish_via_rsi_oversold,
        scenario_bullish_via_macd_bull,
        scenario_case1_priority_over_case2,
        scenario_case_insensitive_and_whitespace_tolerant,
        scenario_forwarded_fields_unchanged,
        scenario_missing_rsi_macd_only_case,
        scenario_missing_macd_rsi_only_case,
        scenario_both_missing_unknown,
        scenario_non_str_signals,
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