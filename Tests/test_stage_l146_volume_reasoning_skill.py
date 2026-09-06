"""Phase 13 Sprint 146 proof suite -- VolumeReasoningSkill.

``VolumeReasoningSkill`` reads ``context.parameters
["vision_analysis"]`` (Sprint 143's ``VisionResponseParserSkill``
output) and produces a single, deterministic ``{"volume_reasoning":
{...}}`` output by matching the free-text ``volume_signal`` field
against a fixed, case-insensitive, whitespace-tolerant substring rule
table. Reasoning only -- no trading decision, no recommendation, no
scoring.

Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l145_momentum_reasoning_skill.py``.

Coverage: N1-N2 strong via Increasing/High; N3-N4 weak via
Decreasing/Low; N5 case/whitespace tolerance; N6 forwarded fields;
M1 unknown volume; M2 missing volume_signal; M3 non-str
volume_signal; M4 missing/non-Mapping vision_analysis; M5 non-Mapping
parameters; S1-S2 output/SkillResult shape; D1 determinism; F1 no
forbidden trading vocabulary in code; A1 AST/structural verification.
"""

from __future__ import annotations

import ast
import inspect
import re
import sys
import textwrap
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult
from Orchestration.volume_reasoning_skill import VolumeReasoningSkill

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
    return VolumeReasoningSkill().execute(_FakeContext(parameters))

def _vision_analysis(volume_signal: Any, **overrides: Any) -> dict:
    base = {"symbol": "BBCA", "timeframe": "1D", "volume_signal": volume_signal}
    base.update(overrides)
    return base

_STRONG_ROW = {
    "volume_state": "STRONG", "volume_strength": "HIGH",
    "volume_reason": "Strong buying participation", "evidence": "HIGH_VOLUME",
}
_WEAK_ROW = {
    "volume_state": "WEAK", "volume_strength": "LOW",
    "volume_reason": "Weak market participation", "evidence": "LOW_VOLUME",
}
_UNKNOWN_ROW = {
    "volume_state": "UNKNOWN", "volume_strength": None,
    "volume_reason": None, "evidence": "UNKNOWN",
}

def _check_row(vr: dict, expected: dict, tag: str) -> None:
    for key, value in expected.items():
        check(vr[key] == value, f"{tag}: {key}={value!r}; got {vr[key]!r}")

# N1-N6 -- normal rule-table paths
def scenario_strong_via_increasing() -> None:
    vr = _run({"vision_analysis": _vision_analysis("Increasing")}).output["volume_reasoning"]
    _check_row(vr, _STRONG_ROW, "N1")

def scenario_strong_via_high() -> None:
    vr = _run({"vision_analysis": _vision_analysis("High Volume Spike")}).output["volume_reasoning"]
    _check_row(vr, _STRONG_ROW, "N2")

def scenario_weak_via_decreasing() -> None:
    vr = _run({"vision_analysis": _vision_analysis("Decreasing")}).output["volume_reasoning"]
    _check_row(vr, _WEAK_ROW, "N3")

def scenario_weak_via_low() -> None:
    vr = _run({"vision_analysis": _vision_analysis("Low Participation")}).output["volume_reasoning"]
    _check_row(vr, _WEAK_ROW, "N4")

def scenario_case_insensitive_and_whitespace_tolerant() -> None:
    for signal in ("INCREASING", "  increasing  ", "IncreaSing"):
        vr = _run({"vision_analysis": _vision_analysis(signal)}).output["volume_reasoning"]
        check(vr["volume_state"] == "STRONG", f"N5: case/whitespace-tolerant match for {signal!r}; got {vr['volume_state']!r}")
    for signal in ("LOW", "  low  ", "LoW"):
        vr = _run({"vision_analysis": _vision_analysis(signal)}).output["volume_reasoning"]
        check(vr["volume_state"] == "WEAK", f"N5: case/whitespace-tolerant match for {signal!r}; got {vr['volume_state']!r}")

def scenario_forwarded_fields_unchanged() -> None:
    vr = _run({"vision_analysis": _vision_analysis("Increasing", symbol="BBRI", timeframe="4H")}).output["volume_reasoning"]
    check(vr["symbol"] == "BBRI", "N6: symbol forwarded unchanged")
    check(vr["timeframe"] == "4H", "N6: timeframe forwarded unchanged")
    check(vr["volume_signal"] == "Increasing", "N6: volume_signal forwarded unchanged")

# M1-M5 -- missing / malformed input
def scenario_unmatched_signal_unknown() -> None:
    vr = _run({"vision_analysis": _vision_analysis("Neutral")}).output["volume_reasoning"]
    _check_row(vr, _UNKNOWN_ROW, "M1: unmatched volume_signal -> UNKNOWN")

def scenario_missing_volume_signal() -> None:
    va = _vision_analysis(None)
    del va["volume_signal"]
    vr = _run({"vision_analysis": va}).output["volume_reasoning"]
    check(vr["volume_signal"] is None, "M2: volume_signal is None when missing")
    _check_row(vr, _UNKNOWN_ROW, "M2: missing volume_signal -> UNKNOWN")

def scenario_non_str_signal() -> None:
    for bad in (42, ["Increasing"], True):
        vr = _run({"vision_analysis": _vision_analysis(bad)}).output["volume_reasoning"]
        check(vr["volume_signal"] == bad, f"M3: non-str volume_signal {bad!r} forwarded unchanged")
        check(vr["volume_state"] == "UNKNOWN", f"M3: non-str volume_signal {bad!r} -> UNKNOWN")

def scenario_vision_analysis_missing_or_not_mapping() -> None:
    vr = _run({}).output["volume_reasoning"]
    check(vr["symbol"] is None, "M4: symbol None when vision_analysis missing")
    _check_row(vr, _UNKNOWN_ROW, "M4: missing vision_analysis")

    for bad_value in ("a string", 42, None):
        vr = _run({"vision_analysis": bad_value}).output["volume_reasoning"]
        check(vr["symbol"] is None, f"M4: non-Mapping vision_analysis {bad_value!r} -> symbol None, never raising")
        check(vr["volume_state"] == "UNKNOWN", f"M4: non-Mapping vision_analysis {bad_value!r} -> UNKNOWN")

def scenario_non_mapping_parameters_never_raises() -> None:
    for bad_parameters in ("a string", None, 42):
        vr = _run(bad_parameters).output["volume_reasoning"]
        check(vr["volume_state"] == "UNKNOWN", f"M5: non-Mapping context.parameters {bad_parameters!r}, never raising")

# S1-S2 -- output / SkillResult shape
def scenario_output_and_skill_result_shape() -> None:
    result = _run({"vision_analysis": _vision_analysis("Increasing")})
    check(set(result.output.keys()) == {"volume_reasoning"}, f"S1: exactly one top-level key; got {set(result.output.keys())!r}")
    expected_keys = {
        "symbol", "timeframe", "volume_signal", "volume_state",
        "volume_strength", "volume_reason", "evidence",
    }
    got_keys = set(result.output["volume_reasoning"].keys())
    check(got_keys == expected_keys, f"S1: volume_reasoning has exactly seven keys; got {got_keys!r}")
    check(result.success is True, "S2: success=True")
    check(result.error is None, "S2: error=None")
    check(dict(result.metadata) == {}, "S2: metadata={}")

# D1 -- determinism
def scenario_repeated_execution_is_deterministic() -> None:
    params = {"vision_analysis": _vision_analysis("Increasing")}
    result_a = _run(params)
    result_b = _run(params)
    check(result_a.output == result_b.output, "D1: repeated execution produces identical output")
    check(result_a.success == result_b.success, "D1: repeated execution produces identical success")
    check(result_a.error == result_b.error, "D1: repeated execution produces identical error")

# F1 -- forbidden trading vocabulary
def scenario_no_forbidden_trading_vocabulary() -> None:
    """Scans code only, not docstrings, for trading vocabulary."""
    import Orchestration.volume_reasoning_skill as module

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
    upper_source = code_only_source.upper()
    all_absent = all(
        re.search(r"\b" + re.escape(term) + r"\b", upper_source) is None
        for term in forbidden_terms
    )
    check(all_absent, f"F1: no forbidden trading vocabulary {forbidden_terms!r} in module code (excluding docstrings, word-boundary match so 'buying' doesn't false-positive on 'BUY')")

# A1 -- AST / structural verification
def scenario_ast_structural_verification() -> None:
    import Orchestration.volume_reasoning_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"VolumeReasoningSkill"}, f"A1: module defines exactly one class; got {class_names!r}")
    check(VolumeReasoningSkill.__bases__ == (BaseSkill,), f"A1: subclasses exactly BaseSkill; got {VolumeReasoningSkill.__bases__!r}")

    check("__init__" not in VolumeReasoningSkill.__dict__, "A1: no __init__ defined")
    check(VolumeReasoningSkill().__dict__ == {}, "A1: instances carry no instance state")

    exec_tree = ast.parse(textwrap.dedent(inspect.getsource(VolumeReasoningSkill.execute)))
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
        attr_name for attr_name, attr_value in VolumeReasoningSkill.__dict__.items()
        if attr_name not in required_members
        and not (attr_name.startswith("__") and attr_name.endswith("__"))
        and (callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property)))
    ]
    check(extra_members == [], f"A1: no extra public/private method beyond name/description/execute; found {extra_members!r}")

# main
def main() -> int:
    scenarios = [
        scenario_strong_via_increasing,
        scenario_strong_via_high,
        scenario_weak_via_decreasing,
        scenario_weak_via_low,
        scenario_case_insensitive_and_whitespace_tolerant,
        scenario_forwarded_fields_unchanged,
        scenario_unmatched_signal_unknown,
        scenario_missing_volume_signal,
        scenario_non_str_signal,
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