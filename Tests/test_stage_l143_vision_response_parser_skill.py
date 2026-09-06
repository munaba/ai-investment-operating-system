"""Phase 12 Sprint 143 proof suite -- VisionResponseParserSkill.

``VisionResponseParserSkill`` reads ``context.parameters
["vision_result"]`` (Sprint 142's ``GeminiVisionProvider`` output)
and produces a single, deterministic ``{"vision_analysis": {...,
"trend": ..., "support": ..., ...}}`` output by parsing
``vision_result["result"]["raw_response"]`` as plain ``"label:
value"`` text. Parsing only -- no trading decision, no scoring, no
recommendation, no reasoning.

Scope: dedicated proof suite for
``Orchestration.vision_response_parser_skill.
VisionResponseParserSkill`` only. Mirrors the compact, table-driven,
no-pytest, global-counter-plus-``main()`` style already used by
``Tests/test_stage_l138_vision_result_skill.py``.

Invariant coverage: N1 all eight fields extracted; N2 forwarded
fields unchanged; N3 label synonyms resolve; N4 noisy/case-varied
labels still match; N5 first occurrence wins; N6 unmatched lines
ignored; N7 quote/comma cleanup; M1 unmentioned field is None; M2
non-str/missing raw_response -> all None; M3 missing/non-Mapping
result -> all None; M4 missing/non-Mapping vision_result -> all
None; M5 non-Mapping parameters -> all None; M6 null-token values ->
None; M7 empty raw_response -> all None; S1 output shape; S2
SkillResult shape; D1 determinism; F1 no forbidden trading
vocabulary in code; A1 AST/structural verification (single
SkillResult() call, single class, no __init__/state, no nested
function, no Tool calls, no forbidden imports, no extra methods).
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
from Orchestration.vision_response_parser_skill import VisionResponseParserSkill

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
    return VisionResponseParserSkill().execute(_FakeContext(parameters))


def _vision_result(raw_response: Any, **overrides: Any) -> dict:
    base = {
        "symbol": "BBCA", "timeframe": "1D", "chart_path": "charts/bbca.png",
        "status": "READY", "analysis_status": "PENDING", "prompt_status": "READY",
        "result_status": "COMPLETED", "result": {"raw_response": raw_response},
    }
    base.update(overrides)
    return base


_FIELDS = (
    "trend", "support", "resistance", "candlestick_pattern",
    "volume_signal", "rsi_signal", "macd_signal", "confidence",
)


def _all_none(va: dict) -> bool:
    return all(va[f] is None for f in _FIELDS)


# ---------------------------------------------------------------------------
# N1-N7 -- normal parsing paths
# ---------------------------------------------------------------------------
def scenario_all_fields_extracted() -> None:
    raw = (
        "Trend: Bullish\nSupport: 8500\nResistance: 9200\n"
        "Candlestick Pattern: Hammer\nVolume Signal: Increasing\n"
        "RSI Signal: Overbought\nMACD Signal: Bullish Crossover\n"
        "Confidence: 85%"
    )
    va = _run({"vision_result": _vision_result(raw)}).output["vision_analysis"]
    expected = {
        "trend": "Bullish", "support": "8500", "resistance": "9200",
        "candlestick_pattern": "Hammer", "volume_signal": "Increasing",
        "rsi_signal": "Overbought", "macd_signal": "Bullish Crossover",
        "confidence": "85%",
    }
    for field, value in expected.items():
        check(va[field] == value, f"N1: {field} extracted; got {va[field]!r}")


def scenario_forwarded_fields_unchanged() -> None:
    va = _run({"vision_result": _vision_result("Trend: Bullish")}).output["vision_analysis"]
    check(va["symbol"] == "BBCA", "N2: symbol forwarded unchanged")
    check(va["timeframe"] == "1D", "N2: timeframe forwarded unchanged")
    check(va["chart_path"] == "charts/bbca.png", "N2: chart_path forwarded unchanged")
    check(va["status"] == "READY", "N2: status forwarded unchanged")
    check(va["analysis_status"] == "PENDING", "N2: analysis_status forwarded unchanged")
    check(va["prompt_status"] == "READY", "N2: prompt_status forwarded unchanged")
    check(va["result_status"] == "COMPLETED", "N2: result_status forwarded unchanged")


def scenario_label_synonyms_resolve() -> None:
    raw = "Candlestick: Doji\nVolume: High\nRSI: Neutral\nMACD: Bearish"
    va = _run({"vision_result": _vision_result(raw)}).output["vision_analysis"]
    check(va["candlestick_pattern"] == "Doji", f"N3: 'Candlestick' synonym; got {va['candlestick_pattern']!r}")
    check(va["volume_signal"] == "High", f"N3: 'Volume' synonym; got {va['volume_signal']!r}")
    check(va["rsi_signal"] == "Neutral", f"N3: 'RSI' synonym; got {va['rsi_signal']!r}")
    check(va["macd_signal"] == "Bearish", f"N3: 'MACD' synonym; got {va['macd_signal']!r}")


def scenario_noisy_labels_still_match() -> None:
    raw = "**Trend**: Bullish\n- Support: 100\nRSI_Signal: Overbought"
    va = _run({"vision_result": _vision_result(raw)}).output["vision_analysis"]
    check(va["trend"] == "Bullish", f"N4: markdown-wrapped label matches; got {va['trend']!r}")
    check(va["support"] == "100", f"N4: bullet-prefixed label matches; got {va['support']!r}")
    check(va["rsi_signal"] == "Overbought", f"N4: underscore label matches; got {va['rsi_signal']!r}")


def scenario_first_occurrence_wins_and_unmatched_ignored() -> None:
    raw = "Trend: Bullish\nTrend: Bearish\nSome preamble: ignore me"
    va = _run({"vision_result": _vision_result(raw)}).output["vision_analysis"]
    check(va["trend"] == "Bullish", f"N5: first occurrence wins; got {va['trend']!r}")
    check(va["support"] is None, "N6: unmatched line does not populate an unrelated field")


def scenario_value_cleanup() -> None:
    raw = 'Trend: "Bullish",\nSupport: \'8500\''
    va = _run({"vision_result": _vision_result(raw)}).output["vision_analysis"]
    check(va["trend"] == "Bullish", f"N7: trailing comma/quotes stripped; got {va['trend']!r}")
    check(va["support"] == "8500", f"N7: surrounding quotes stripped; got {va['support']!r}")


# ---------------------------------------------------------------------------
# M1-M7 -- missing / malformed input
# ---------------------------------------------------------------------------
def scenario_unmentioned_field_is_none() -> None:
    va = _run({"vision_result": _vision_result("Trend: Bullish")}).output["vision_analysis"]
    check(va["support"] is None, "M1: unmentioned field is None")
    check(va["confidence"] is None, "M1: unmentioned field is None")


def scenario_raw_response_missing_or_wrong_type() -> None:
    for bad in (42, ["Trend: Bullish"], {"trend": "Bullish"}, True, None):
        va = _run({"vision_result": _vision_result(bad)}).output["vision_analysis"]
        check(_all_none(va), f"M2: non-str raw_response {bad!r} -> all eight fields None")

    vr = _vision_result("placeholder")
    vr["result"] = {}
    va = _run({"vision_result": vr}).output["vision_analysis"]
    check(_all_none(va), "M2: missing raw_response key -> all eight fields None")


def scenario_result_missing_or_not_mapping() -> None:
    for bad_result in (None, "not a mapping", 42):
        vr = _vision_result("placeholder")
        vr["result"] = bad_result
        va = _run({"vision_result": vr}).output["vision_analysis"]
        check(_all_none(va), f"M3: non-Mapping result {bad_result!r} -> all eight fields None")

    vr = _vision_result("placeholder")
    del vr["result"]
    va = _run({"vision_result": vr}).output["vision_analysis"]
    check(_all_none(va), "M3: missing result key -> all eight fields None")


def scenario_vision_result_missing_or_not_mapping() -> None:
    va = _run({}).output["vision_analysis"]
    check(va["symbol"] is None, "M4: symbol None when vision_result missing")
    check(_all_none(va), "M4: all eight parsed fields None when vision_result missing")

    for bad_value in (["a", "list"], "a string", 42, None):
        va = _run({"vision_result": bad_value}).output["vision_analysis"]
        check(va["symbol"] is None, f"M4: non-Mapping vision_result {bad_value!r} -> symbol None, never raising")
        check(_all_none(va), f"M4: non-Mapping vision_result {bad_value!r} -> all eight fields None")


def scenario_non_mapping_parameters_never_raises() -> None:
    for bad_parameters in (["a", "list"], "a string", None, 42):
        va = _run(bad_parameters).output["vision_analysis"]
        check(_all_none(va), f"M5: non-Mapping context.parameters {bad_parameters!r} -> all None, never raising")


def scenario_null_token_values_become_none() -> None:
    raw = "Trend: null\nSupport: None\nResistance: N/A\nCandlestick Pattern: unknown\nVolume Signal: -"
    va = _run({"vision_result": _vision_result(raw)}).output["vision_analysis"]
    check(va["trend"] is None, "M6: 'null' token -> None")
    check(va["support"] is None, "M6: 'None' token -> None")
    check(va["resistance"] is None, "M6: 'N/A' token -> None")
    check(va["candlestick_pattern"] is None, "M6: 'unknown' token -> None")
    check(va["volume_signal"] is None, "M6: '-' token -> None")


def scenario_empty_raw_response() -> None:
    va = _run({"vision_result": _vision_result("")}).output["vision_analysis"]
    check(_all_none(va), "M7: empty raw_response -> all eight fields None")


# ---------------------------------------------------------------------------
# S1-S2 -- output / SkillResult shape
# ---------------------------------------------------------------------------
def scenario_output_and_skill_result_shape() -> None:
    result = _run({"vision_result": _vision_result("Trend: Bullish")})
    check(set(result.output.keys()) == {"vision_analysis"}, f"S1: exactly one top-level key; got {set(result.output.keys())!r}")
    expected_keys = {
        "symbol", "timeframe", "chart_path", "status", "analysis_status",
        "prompt_status", "result_status", *_FIELDS,
    }
    got_keys = set(result.output["vision_analysis"].keys())
    check(got_keys == expected_keys, f"S1: vision_analysis has exactly fifteen keys; got {got_keys!r}")
    check(result.success is True, "S2: success=True")
    check(result.error is None, "S2: error=None")
    check(dict(result.metadata) == {}, "S2: metadata={}")


# ---------------------------------------------------------------------------
# D1 -- determinism
# ---------------------------------------------------------------------------
def scenario_repeated_execution_is_deterministic() -> None:
    params = {"vision_result": _vision_result("Trend: Bullish\nSupport: 8500")}
    result_a = _run(params)
    result_b = _run(params)
    check(result_a.output == result_b.output, "D1: repeated execution produces identical output")
    check(result_a.success == result_b.success, "D1: repeated execution produces identical success")
    check(result_a.error == result_b.error, "D1: repeated execution produces identical error")


# ---------------------------------------------------------------------------
# F1 -- forbidden trading vocabulary
# ---------------------------------------------------------------------------
def scenario_no_forbidden_trading_vocabulary() -> None:
    """Scans the module's executable code (not its prose docstrings,
    which legitimately name these terms to document that they are
    forbidden) for BUY/SELL/HOLD-style trading vocabulary."""
    import Orchestration.vision_response_parser_skill as module

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
        "BUY", "SELL", "HOLD", "recommendation", "score", "probability",
        "prediction", "strategy", "PositionSizing", "CapitalAllocation",
        "TradingDecision",
    )
    all_absent = all(term not in code_only_source for term in forbidden_terms)
    check(all_absent, f"F1: no forbidden trading vocabulary {forbidden_terms!r} in module code (excluding docstrings)")


# ---------------------------------------------------------------------------
# A1 -- AST / structural verification
# ---------------------------------------------------------------------------
def scenario_ast_structural_verification() -> None:
    import Orchestration.vision_response_parser_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    skill_result_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "SkillResult"
    ]
    check(len(skill_result_calls) == 1, f"A1: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"VisionResponseParserSkill"}, f"A1: module defines exactly one class; got {class_names!r}")
    check(
        VisionResponseParserSkill.__bases__ == (BaseSkill,),
        f"A1: subclasses exactly BaseSkill; got {VisionResponseParserSkill.__bases__!r}",
    )

    check("__init__" not in VisionResponseParserSkill.__dict__, "A1: no __init__ defined")
    check(VisionResponseParserSkill().__dict__ == {}, "A1: instances carry no instance state")

    exec_tree = ast.parse(textwrap.dedent(inspect.getsource(VisionResponseParserSkill.execute)))
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
        attr_name for attr_name, attr_value in VisionResponseParserSkill.__dict__.items()
        if attr_name not in required_members
        and not (attr_name.startswith("__") and attr_name.endswith("__"))
        and (callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property)))
    ]
    check(extra_members == [], f"A1: no extra public/private method beyond name/description/execute; found {extra_members!r}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_all_fields_extracted,
        scenario_forwarded_fields_unchanged,
        scenario_label_synonyms_resolve,
        scenario_noisy_labels_still_match,
        scenario_first_occurrence_wins_and_unmatched_ignored,
        scenario_value_cleanup,
        scenario_unmentioned_field_is_none,
        scenario_raw_response_missing_or_wrong_type,
        scenario_result_missing_or_not_mapping,
        scenario_vision_result_missing_or_not_mapping,
        scenario_non_mapping_parameters_never_raises,
        scenario_null_token_values_become_none,
        scenario_empty_raw_response,
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