"""Phase 13 Sprint 150 proof suite -- MarketStateSkill.

``MarketStateSkill`` reads ``context.parameters["market_consensus"]``
(Sprint 149's ``EvidenceFusionSkill`` output) and produces a single,
deterministic ``{"market_state": {...}}`` output by reading
``agreement``/``confidence`` and applying the locked three-case rule
table. Pure market-condition reporting only -- no trading decision.

Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l149_evidence_fusion_skill.py``.

Coverage: N1 CONFIRMED; N2 DEVELOPING; N3 UNCERTAIN (mismatched/other
agreement+confidence combos); N4 missing market_consensus; N5 missing
agreement/confidence; N6 non-Mapping market_consensus; N7 non-Mapping
parameters; N8 forwarded fields; S1-S2 output/SkillResult shape; D1
determinism; F1 no forbidden trading vocabulary; A1 AST/structural
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
from Orchestration.market_state_skill import MarketStateSkill

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
    return MarketStateSkill().execute(_FakeContext(parameters))

def _consensus(agreement: Any, confidence: Any, **overrides: Any) -> dict:
    base = {
        "symbol": "BBCA", "timeframe": "1D", "agreement": agreement,
        "confidence": confidence, "summary": "All evidence available",
    }
    base.update(overrides)
    return base

def _params(agreement: Any, confidence: Any, **overrides: Any) -> dict:
    return {"market_consensus": _consensus(agreement, confidence, **overrides)}

_CONFIRMED_ROW = {"market_state": "CONFIRMED", "state_strength": "HIGH", "state_reason": "Evidence strongly aligned"}
_DEVELOPING_ROW = {"market_state": "DEVELOPING", "state_strength": "MEDIUM", "state_reason": "Evidence partially aligned"}
_UNCERTAIN_ROW = {"market_state": "UNCERTAIN", "state_strength": "LOW", "state_reason": "Evidence incomplete"}

def _check_row(ms: dict, expected: dict, tag: str) -> None:
    for key, value in expected.items():
        check(ms[key] == value, f"{tag}: {key}={value!r}; got {ms[key]!r}")

# N1 -- CONFIRMED
def scenario_confirmed() -> None:
    ms = _run(_params("FULL", "HIGH")).output["market_state"]
    _check_row(ms, _CONFIRMED_ROW, "N1")
    check(ms["agreement"] == "FULL", "N1: agreement forwarded")
    check(ms["confidence"] == "HIGH", "N1: confidence forwarded")

# N2 -- DEVELOPING
def scenario_developing() -> None:
    for confidence in ("HIGH", "MEDIUM", None):
        ms = _run(_params("PARTIAL", confidence)).output["market_state"]
        _check_row(ms, _DEVELOPING_ROW, f"N2: PARTIAL agreement, confidence={confidence!r}")
        check(ms["agreement"] == "PARTIAL", f"N2: agreement forwarded, confidence={confidence!r}")

# N3 -- UNCERTAIN via mismatched/other agreement+confidence combos
def scenario_uncertain_other_combinations() -> None:
    combos = [
        ("FULL", "MEDIUM"), ("FULL", None),
        ("LOW", "HIGH"), ("OTHER", "HIGH"), (None, None),
    ]
    for agreement, confidence in combos:
        ms = _run(_params(agreement, confidence)).output["market_state"]
        _check_row(ms, _UNCERTAIN_ROW, f"N3: agreement={agreement!r}, confidence={confidence!r}")

# N4 -- missing market_consensus
def scenario_missing_market_consensus() -> None:
    ms = _run({}).output["market_state"]
    _check_row(ms, _UNCERTAIN_ROW, "N4: missing market_consensus -> UNCERTAIN")
    check(ms["symbol"] is None, "N4: symbol None when market_consensus missing")
    check(ms["timeframe"] is None, "N4: timeframe None when market_consensus missing")
    check(ms["agreement"] is None, "N4: agreement None when market_consensus missing")
    check(ms["confidence"] is None, "N4: confidence None when market_consensus missing")
    check(ms["summary"] is None, "N4: summary None when market_consensus missing")

# N5 -- missing agreement/confidence within a present market_consensus
def scenario_missing_agreement_or_confidence() -> None:
    consensus_no_agreement = _consensus("FULL", "HIGH")
    del consensus_no_agreement["agreement"]
    ms = _run({"market_consensus": consensus_no_agreement}).output["market_state"]
    _check_row(ms, _UNCERTAIN_ROW, "N5: missing agreement -> UNCERTAIN")
    check(ms["agreement"] is None, "N5: agreement None when missing from market_consensus")
    check(ms["confidence"] == "HIGH", "N5: confidence still forwarded when agreement missing")

    consensus_no_confidence = _consensus("FULL", "HIGH")
    del consensus_no_confidence["confidence"]
    ms2 = _run({"market_consensus": consensus_no_confidence}).output["market_state"]
    _check_row(ms2, _UNCERTAIN_ROW, "N5: missing confidence -> UNCERTAIN")
    check(ms2["confidence"] is None, "N5: confidence None when missing from market_consensus")
    check(ms2["agreement"] == "FULL", "N5: agreement still forwarded when confidence missing")

# N6 -- non-Mapping market_consensus
def scenario_non_mapping_market_consensus() -> None:
    for bad_value in ("a string", 42, None):
        result = _run({"market_consensus": bad_value})
        check(result.success is True, f"N6: non-Mapping market_consensus {bad_value!r} -> success True")
        ms = result.output["market_state"]
        _check_row(ms, _UNCERTAIN_ROW, f"N6: non-Mapping market_consensus {bad_value!r} -> UNCERTAIN")
        check(ms["symbol"] is None, f"N6: symbol None for non-Mapping {bad_value!r}")

# N7 -- non-Mapping parameters, never raises
def scenario_non_mapping_parameters_never_raises() -> None:
    for bad_parameters in ("a string", None, 42):
        result = _run(bad_parameters)
        check(result.success is True, f"N7: non-Mapping parameters {bad_parameters!r} -> success True")
        ms = result.output["market_state"]
        _check_row(ms, _UNCERTAIN_ROW, f"N7: non-Mapping parameters {bad_parameters!r} -> UNCERTAIN")

# N8 -- forwarded fields
def scenario_forwarded_fields() -> None:
    params = _params("FULL", "HIGH", symbol="BBRI", timeframe="4H", summary="Custom summary")
    ms = _run(params).output["market_state"]
    check(ms["symbol"] == "BBRI", "N8: symbol forwarded from market_consensus")
    check(ms["timeframe"] == "4H", "N8: timeframe forwarded from market_consensus")
    check(ms["summary"] == "Custom summary", "N8: summary forwarded from market_consensus")
    check(ms["agreement"] == "FULL", "N8: agreement forwarded from market_consensus")
    check(ms["confidence"] == "HIGH", "N8: confidence forwarded from market_consensus")

# S1-S2 -- output / SkillResult shape
def scenario_output_and_skill_result_shape() -> None:
    result = _run(_params("FULL", "HIGH"))
    check(set(result.output.keys()) == {"market_state"}, f"S1: exactly one top-level key; got {set(result.output.keys())!r}")
    expected_keys = {
        "symbol", "timeframe", "market_state", "state_strength",
        "state_reason", "confidence", "agreement", "summary",
    }
    got_keys = set(result.output["market_state"].keys())
    check(got_keys == expected_keys, f"S1: market_state has exactly eight keys; got {got_keys!r}")
    check(result.success is True, "S2: success=True")
    check(result.error is None, "S2: error=None")
    check(dict(result.metadata) == {}, "S2: metadata={}")

# D1 -- determinism
def scenario_repeated_execution_is_deterministic() -> None:
    params = _params("FULL", "HIGH")
    result_a = _run(params)
    result_b = _run(params)
    check(result_a.output == result_b.output, "D1: repeated execution produces identical output")
    check(result_a.success == result_b.success, "D1: repeated execution produces identical success")
    check(result_a.error == result_b.error, "D1: repeated execution produces identical error")

    params_uncertain = {}
    result_c = _run(params_uncertain)
    result_d = _run(params_uncertain)
    check(result_c.output == result_d.output, "D1: repeated execution (UNCERTAIN case) produces identical output")

# F1 -- forbidden trading vocabulary
def scenario_no_forbidden_trading_vocabulary() -> None:
    """Scans code only, not docstrings, for trading vocabulary."""
    import Orchestration.market_state_skill as module

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
        "BUY", "SELL", "WAIT", "ENTRY", "EXIT", "LONG", "SHORT",
        "POSITION", "CAPITAL", "PORTFOLIO", "ORDER", "RISK",
        "RECOMMENDATION", "SIGNAL",
    )
    all_absent = all(term not in code_only_source.upper() for term in forbidden_terms)
    check(all_absent, f"F1: no forbidden trading vocabulary {forbidden_terms!r} in module code (excluding docstrings)")

# A1 -- AST / structural verification
def scenario_ast_structural_verification() -> None:
    import Orchestration.market_state_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"MarketStateSkill"}, f"A1: module defines exactly one class; got {class_names!r}")
    check(MarketStateSkill.__bases__ == (BaseSkill,), f"A1: subclasses exactly BaseSkill; got {MarketStateSkill.__bases__!r}")

    check("__init__" not in MarketStateSkill.__dict__, "A1: no __init__ defined")
    check(MarketStateSkill().__dict__ == {}, "A1: instances carry no instance state")

    exec_tree = ast.parse(textwrap.dedent(inspect.getsource(MarketStateSkill.execute)))
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
        attr_name for attr_name, attr_value in MarketStateSkill.__dict__.items()
        if attr_name not in required_members
        and not (attr_name.startswith("__") and attr_name.endswith("__"))
        and (callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property)))
    ]
    check(extra_members == [], f"A1: no extra public/private method beyond name/description/execute; found {extra_members!r}")

# main
def main() -> int:
    scenarios = [
        scenario_confirmed,
        scenario_developing,
        scenario_uncertain_other_combinations,
        scenario_missing_market_consensus,
        scenario_missing_agreement_or_confidence,
        scenario_non_mapping_market_consensus,
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