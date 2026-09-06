"""Phase 13 Sprint 149 proof suite -- EvidenceFusionSkill.

``EvidenceFusionSkill`` reads ``context.parameters``' five
``*_reasoning`` values (Sprints 144-148's reasoning Skills) and
produces a single, deterministic ``{"market_consensus": {...}}``
output by extracting each object's own ``"evidence"`` field as a
``*_bias`` value and applying the locked three-case rule table. Pure
consensus reporting only -- no trading decision, no recommendation,
no scoring.

Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l148_support_resistance_reasoning_skill.py``.

Coverage: N1 full evidence; N2 partial evidence (single UNKNOWN); N3
partial evidence (multiple UNKNOWN); N4 missing reasoning object(s);
N5 non-Mapping reasoning object(s); N6 non-Mapping parameters; N7
forwarded fields; S1-S2 output/SkillResult shape; D1 determinism; F1
no forbidden trading vocabulary; A1 AST/structural verification.
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
from Orchestration.evidence_fusion_skill import EvidenceFusionSkill

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
    return EvidenceFusionSkill().execute(_FakeContext(parameters))

def _reasoning(evidence: Any, **overrides: Any) -> dict:
    base = {"symbol": "BBCA", "timeframe": "1D", "evidence": evidence}
    base.update(overrides)
    return base

def _full_params(
    trend="BULLISH", momentum="BULLISH", volume="HIGH_VOLUME",
    pattern="BULLISH_PATTERN", level="LEVELS_PRESENT",
) -> dict:
    return {
        "trend_reasoning": _reasoning(trend),
        "momentum_reasoning": _reasoning(momentum),
        "volume_reasoning": _reasoning(volume),
        "candlestick_reasoning": _reasoning(pattern),
        "support_resistance_reasoning": _reasoning(level),
    }

_FULL_ROW = {"agreement": "FULL", "conflict": False, "confidence": "HIGH", "summary": "All evidence available"}
_PARTIAL_ROW = {"agreement": "PARTIAL", "conflict": False, "confidence": "MEDIUM", "summary": "Partial evidence available"}
_LOW_ROW = {"agreement": "LOW", "conflict": True, "confidence": "LOW", "summary": "Insufficient evidence"}

def _check_row(mc: dict, expected: dict, tag: str) -> None:
    for key, value in expected.items():
        check(mc[key] == value, f"{tag}: {key}={value!r}; got {mc[key]!r}")

# N1 -- full evidence
def scenario_full_evidence() -> None:
    mc = _run(_full_params()).output["market_consensus"]
    _check_row(mc, _FULL_ROW, "N1")
    check(mc["trend_bias"] == "BULLISH", "N1: trend_bias forwarded")
    check(mc["momentum_bias"] == "BULLISH", "N1: momentum_bias forwarded")
    check(mc["volume_bias"] == "HIGH_VOLUME", "N1: volume_bias forwarded")
    check(mc["pattern_bias"] == "BULLISH_PATTERN", "N1: pattern_bias forwarded")
    check(mc["level_bias"] == "LEVELS_PRESENT", "N1: level_bias forwarded")

# N2 -- partial evidence, single UNKNOWN
def scenario_partial_evidence_single_unknown() -> None:
    for field in ("trend", "momentum", "volume", "pattern", "level"):
        kwargs = {
            "trend": "BULLISH", "momentum": "BULLISH", "volume": "HIGH_VOLUME",
            "pattern": "BULLISH_PATTERN", "level": "LEVELS_PRESENT",
        }
        kwargs[field] = "UNKNOWN"
        mc = _run(_full_params(**kwargs)).output["market_consensus"]
        _check_row(mc, _PARTIAL_ROW, f"N2: single UNKNOWN in {field}")

# N3 -- partial evidence, multiple UNKNOWN
def scenario_partial_evidence_multiple_unknown() -> None:
    mc = _run(_full_params(trend="UNKNOWN", volume="UNKNOWN")).output["market_consensus"]
    _check_row(mc, _PARTIAL_ROW, "N3: multiple UNKNOWN")

    mc_all_unknown = _run(
        _full_params(trend="UNKNOWN", momentum="UNKNOWN", volume="UNKNOWN", pattern="UNKNOWN", level="UNKNOWN")
    ).output["market_consensus"]
    _check_row(mc_all_unknown, _PARTIAL_ROW, "N3: all five UNKNOWN, still all present -> PARTIAL not LOW")

# N4 -- missing reasoning object(s)
def scenario_missing_reasoning_objects() -> None:
    for missing in (
        "trend_reasoning", "momentum_reasoning", "volume_reasoning",
        "candlestick_reasoning", "support_resistance_reasoning",
    ):
        params = _full_params()
        del params[missing]
        mc = _run(params).output["market_consensus"]
        _check_row(mc, _LOW_ROW, f"N4: missing {missing} -> LOW")

    mc_empty = _run({}).output["market_consensus"]
    _check_row(mc_empty, _LOW_ROW, "N4: all missing -> LOW")
    check(mc_empty["trend_bias"] is None, "N4: trend_bias None when trend_reasoning missing")
    check(mc_empty["symbol"] is None, "N4: symbol None when trend_reasoning missing")

# N5 -- non-Mapping reasoning object(s)
def scenario_non_mapping_reasoning_objects() -> None:
    for bad_value in ("a string", 42, ["evidence"], None):
        params = _full_params()
        params["momentum_reasoning"] = bad_value
        mc = _run(params).output["market_consensus"]
        _check_row(mc, _LOW_ROW, f"N5: non-Mapping momentum_reasoning {bad_value!r} -> LOW")
        check(mc["momentum_bias"] is None, f"N5: momentum_bias None for non-Mapping {bad_value!r}")

    params = _full_params()
    params["trend_reasoning"] = "not a mapping"
    mc = _run(params).output["market_consensus"]
    _check_row(mc, _LOW_ROW, "N5: non-Mapping trend_reasoning -> LOW")
    check(mc["symbol"] is None, "N5: symbol None when trend_reasoning is non-Mapping")
    check(mc["timeframe"] is None, "N5: timeframe None when trend_reasoning is non-Mapping")

# N6 -- non-Mapping parameters, never raises
def scenario_non_mapping_parameters_never_raises() -> None:
    for bad_parameters in ("a string", None, 42, ["x"]):
        result = _run(bad_parameters)
        check(result.success is True, f"N6: non-Mapping parameters {bad_parameters!r} -> success True")
        mc = result.output["market_consensus"]
        _check_row(mc, _LOW_ROW, f"N6: non-Mapping parameters {bad_parameters!r} -> LOW")

# N7 -- forwarded fields
def scenario_forwarded_fields() -> None:
    params = _full_params()
    params["trend_reasoning"] = _reasoning("BEARISH", symbol="BBRI", timeframe="4H")
    mc = _run(params).output["market_consensus"]
    check(mc["symbol"] == "BBRI", "N7: symbol forwarded from trend_reasoning")
    check(mc["timeframe"] == "4H", "N7: timeframe forwarded from trend_reasoning")
    check(mc["trend_bias"] == "BEARISH", "N7: trend_bias forwarded from trend_reasoning evidence")

    # symbol/timeframe on other reasoning objects are ignored
    params2 = _full_params()
    params2["momentum_reasoning"] = _reasoning("BULLISH", symbol="IGNORED", timeframe="IGNORED")
    mc2 = _run(params2).output["market_consensus"]
    check(mc2["symbol"] == "BBCA", "N7: symbol comes from trend_reasoning only, not momentum_reasoning")
    check(mc2["timeframe"] == "1D", "N7: timeframe comes from trend_reasoning only, not momentum_reasoning")

# S1-S2 -- output / SkillResult shape
def scenario_output_and_skill_result_shape() -> None:
    result = _run(_full_params())
    check(set(result.output.keys()) == {"market_consensus"}, f"S1: exactly one top-level key; got {set(result.output.keys())!r}")
    expected_keys = {
        "symbol", "timeframe", "trend_bias", "momentum_bias", "volume_bias",
        "pattern_bias", "level_bias", "agreement", "conflict", "confidence",
        "summary",
    }
    got_keys = set(result.output["market_consensus"].keys())
    check(got_keys == expected_keys, f"S1: market_consensus has exactly eleven keys; got {got_keys!r}")
    check(result.success is True, "S2: success=True")
    check(result.error is None, "S2: error=None")
    check(dict(result.metadata) == {}, "S2: metadata={}")

# D1 -- determinism
def scenario_repeated_execution_is_deterministic() -> None:
    params = _full_params()
    result_a = _run(params)
    result_b = _run(params)
    check(result_a.output == result_b.output, "D1: repeated execution produces identical output")
    check(result_a.success == result_b.success, "D1: repeated execution produces identical success")
    check(result_a.error == result_b.error, "D1: repeated execution produces identical error")

    params_low = {}
    result_c = _run(params_low)
    result_d = _run(params_low)
    check(result_c.output == result_d.output, "D1: repeated execution (LOW case) produces identical output")

# F1 -- forbidden trading vocabulary
def scenario_no_forbidden_trading_vocabulary() -> None:
    """Scans code only, not docstrings, for trading vocabulary."""
    import Orchestration.evidence_fusion_skill as module

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
        "BUY", "SELL", "WAIT", "LONG", "SHORT", "ENTRY", "EXIT",
        "STOP LOSS", "TAKE PROFIT", "POSITION SIZE", "CAPITAL",
        "PORTFOLIO", "ORDER", "RISK", "MARKET PREDICTION", "SCORE",
        "PROBABILITY", "RECOMMENDATION", "SIGNAL",
    )
    all_absent = all(term not in code_only_source.upper() for term in forbidden_terms)
    check(all_absent, f"F1: no forbidden trading vocabulary {forbidden_terms!r} in module code (excluding docstrings)")

# A1 -- AST / structural verification
def scenario_ast_structural_verification() -> None:
    import Orchestration.evidence_fusion_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"EvidenceFusionSkill"}, f"A1: module defines exactly one class; got {class_names!r}")
    check(EvidenceFusionSkill.__bases__ == (BaseSkill,), f"A1: subclasses exactly BaseSkill; got {EvidenceFusionSkill.__bases__!r}")

    check("__init__" not in EvidenceFusionSkill.__dict__, "A1: no __init__ defined")
    check(EvidenceFusionSkill().__dict__ == {}, "A1: instances carry no instance state")

    exec_tree = ast.parse(textwrap.dedent(inspect.getsource(EvidenceFusionSkill.execute)))
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
        attr_name for attr_name, attr_value in EvidenceFusionSkill.__dict__.items()
        if attr_name not in required_members
        and not (attr_name.startswith("__") and attr_name.endswith("__"))
        and (callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property)))
    ]
    check(extra_members == [], f"A1: no extra public/private method beyond name/description/execute; found {extra_members!r}")

# main
def main() -> int:
    scenarios = [
        scenario_full_evidence,
        scenario_partial_evidence_single_unknown,
        scenario_partial_evidence_multiple_unknown,
        scenario_missing_reasoning_objects,
        scenario_non_mapping_reasoning_objects,
        scenario_non_mapping_parameters_never_raises,
        scenario_forwarded_fields,
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