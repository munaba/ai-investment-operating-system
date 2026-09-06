"""Phase 11 Sprint 140 proof suite -- the ``GeminiVisionProvider``
contract.

Scope: dedicated regression suite for
``Providers.gemini_vision_provider.GeminiVisionProvider`` only.
Nothing else exists in this module to test -- no real Gemini call,
no Ollama, no Qwen, no InternVL, no MiniCPM, no factory, no
registry, no manager, no coordinator, no workflow, no pipeline, no
service, no repository. Mirrors
``Tests/test_stage_l139_base_vision_provider.py`` in style: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

``GeminiVisionProvider`` is the first concrete
``BaseVisionProvider`` (Sprint 139): its ``name`` is ``"gemini"``,
its ``description`` is ``"Gemini Vision Provider"``, and its
``analyze(vision_prompt)`` forwards ``symbol``/``timeframe``/
``chart_path``/``status``/``analysis_status``/``prompt_status``
unchanged while unconditionally attaching ``result_status =
"WAITING"`` and the fixed, all-``None`` ``result`` object from
Sprint 138.

Invariant coverage:
    G1  -- GeminiVisionProvider is a BaseVisionProvider subclass and
           constructs with zero arguments.
    G2  -- isinstance/issubclass relationships hold as expected.
    G3  -- name returns exactly "gemini", every call, no arguments.
    G4  -- description returns exactly "Gemini Vision Provider",
           every call.
    G5  -- analyze() on a well-formed vision_prompt forwards all six
           carry-through fields unchanged, by value.
    G6  -- analyze() output has result_status == "WAITING"
           unconditionally, regardless of the input's own
           prompt_status value.
    G7  -- analyze() output's result object has exactly the eight
           locked keys, every value None.
    G8  -- malformed input (None, str, int, list, empty dict) never
           raises and yields all six carry-through fields as None,
           with result_status/result unchanged from the locked
           fixture.
    G9  -- a vision_prompt Mapping missing some keys yields None for
           just the missing keys, others forwarded normally.
    G10 -- deterministic behavior: two calls with equal input
           produce equal (but independently-constructed) output
           dicts; the provider carries no instance state to leak
           between calls.
    G11 -- no instance state: vars(provider) == {} (no __init__ of
           its own).
    G12 -- exactly one abstract method resolved / zero remaining
           abstractmethods.
    G13 -- AST sanity check: module defines exactly one top-level
           class (GeminiVisionProvider), no __init__ method in the
           AST, and analyze/name/description are the only methods
           defined on the class.
    G14 -- structural sanity check: the module imports no
           networking/filesystem/Gemini-SDK modules, and its source
           contains no reference to a real Gemini call, Ollama,
           Qwen, InternVL, MiniCPM, Factory, Registry, Manager,
           Coordinator, Workflow, Pipeline, Service, or Repository.
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Providers.base_vision_provider import BaseVisionProvider
from Providers.gemini_vision_provider import GeminiVisionProvider

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


_FIXED_RESULT = {
    "trend": None,
    "support": None,
    "resistance": None,
    "candlestick_pattern": None,
    "volume_signal": None,
    "rsi_signal": None,
    "macd_signal": None,
    "confidence": None,
}

_SAMPLE_VISION_PROMPT = {
    "symbol": "AAPL",
    "timeframe": "1D",
    "chart_path": "/charts/aapl.png",
    "status": "OK",
    "analysis_status": "PENDING",
    "prompt_status": "READY",
    "prompt": "Analyze this stock chart.",
}


# ---------------------------------------------------------------------------
# G1 -- subclass + zero-arg construction
# ---------------------------------------------------------------------------
def scenario_subclass_and_construction() -> None:
    check(
        issubclass(GeminiVisionProvider, BaseVisionProvider),
        "G1: GeminiVisionProvider subclasses BaseVisionProvider",
    )
    provider = GeminiVisionProvider()
    check(
        isinstance(provider, GeminiVisionProvider),
        "G1: GeminiVisionProvider() constructs with zero arguments",
    )


# ---------------------------------------------------------------------------
# G2 -- isinstance/issubclass relationships
# ---------------------------------------------------------------------------
def scenario_isinstance_issubclass_relationships() -> None:
    provider = GeminiVisionProvider()
    check(
        isinstance(provider, BaseVisionProvider),
        "G2: isinstance(provider, BaseVisionProvider) is True",
    )
    check(
        not isinstance(object(), GeminiVisionProvider),
        "G2: isinstance(plain_object, GeminiVisionProvider) is False",
    )
    check(
        not isinstance("gemini", GeminiVisionProvider),
        "G2: isinstance(str, GeminiVisionProvider) is False",
    )
    check(
        issubclass(GeminiVisionProvider, BaseVisionProvider)
        and not issubclass(BaseVisionProvider, GeminiVisionProvider),
        "G2: the subclass relationship is not symmetric",
    )


# ---------------------------------------------------------------------------
# G3 / G4 -- name / description
# ---------------------------------------------------------------------------
def scenario_name_is_gemini() -> None:
    provider = GeminiVisionProvider()
    check(provider.name == "gemini", "G3: provider.name == 'gemini'")
    check(
        provider.name == "gemini",
        "G3: provider.name is stable across repeated reads",
    )


def scenario_description_is_exact() -> None:
    provider = GeminiVisionProvider()
    check(
        provider.description == "Gemini Vision Provider",
        "G4: provider.description == 'Gemini Vision Provider'",
    )
    check(
        provider.description == "Gemini Vision Provider",
        "G4: provider.description is stable across repeated reads",
    )


# ---------------------------------------------------------------------------
# G5 / G6 / G7 -- analyze() output contract on well-formed input
# ---------------------------------------------------------------------------
def scenario_analyze_forwards_fields_unchanged() -> None:
    provider = GeminiVisionProvider()
    result = provider.analyze(_SAMPLE_VISION_PROMPT)

    check(isinstance(result, dict), "G5: analyze() returns a dict")
    check(
        result["symbol"] == "AAPL",
        "G5: analyze() forwards 'symbol' unchanged",
    )
    check(
        result["timeframe"] == "1D",
        "G5: analyze() forwards 'timeframe' unchanged",
    )
    check(
        result["chart_path"] == "/charts/aapl.png",
        "G5: analyze() forwards 'chart_path' unchanged",
    )
    check(
        result["status"] == "OK",
        "G5: analyze() forwards 'status' unchanged",
    )
    check(
        result["analysis_status"] == "PENDING",
        "G5: analyze() forwards 'analysis_status' unchanged",
    )
    check(
        result["prompt_status"] == "READY",
        "G5: analyze() forwards 'prompt_status' unchanged",
    )


def scenario_result_status_unconditionally_waiting() -> None:
    provider = GeminiVisionProvider()

    for prompt_status in ("READY", "INVALID", "UNKNOWN", "anything-else", None):
        vision_prompt = dict(_SAMPLE_VISION_PROMPT)
        vision_prompt["prompt_status"] = prompt_status
        result = provider.analyze(vision_prompt)
        check(
            result["result_status"] == "WAITING",
            f"G6: analyze() yields result_status == 'WAITING' "
            f"regardless of prompt_status={prompt_status!r}",
        )


def scenario_result_object_shape_exact() -> None:
    provider = GeminiVisionProvider()
    result = provider.analyze(_SAMPLE_VISION_PROMPT)

    check(
        result["result"] == _FIXED_RESULT,
        "G7: analyze() result object matches the fixed, all-None "
        "Sprint 138 shape exactly",
    )
    check(
        set(result["result"].keys())
        == {
            "trend",
            "support",
            "resistance",
            "candlestick_pattern",
            "volume_signal",
            "rsi_signal",
            "macd_signal",
            "confidence",
        },
        "G7: analyze() result object has exactly the eight locked keys",
    )
    check(
        all(v is None for v in result["result"].values()),
        "G7: every value in analyze()'s result object is None",
    )
    check(
        set(result.keys())
        == {
            "symbol",
            "timeframe",
            "chart_path",
            "status",
            "analysis_status",
            "prompt_status",
            "result_status",
            "result",
        },
        "G7: analyze() output has exactly the eight VisionResult keys",
    )


# ---------------------------------------------------------------------------
# G8 -- malformed input never raises
# ---------------------------------------------------------------------------
def scenario_malformed_input_never_raises() -> None:
    provider = GeminiVisionProvider()

    for label, bad_input in (
        ("None", None),
        ("str", "not-a-mapping"),
        ("int", 42),
        ("list", ["symbol", "AAPL"]),
        ("empty dict", {}),
    ):
        raised = False
        result = None
        try:
            result = provider.analyze(bad_input)
        except Exception:  # noqa: BLE001
            raised = True

        check(not raised, f"G8: analyze({label}) never raises")
        check(
            result is not None
            and all(
                result[field] is None
                for field in (
                    "symbol",
                    "timeframe",
                    "chart_path",
                    "status",
                    "analysis_status",
                    "prompt_status",
                )
            ),
            f"G8: analyze({label}) yields None for every "
            f"carry-through field",
        )
        check(
            result is not None and result["result_status"] == "WAITING",
            f"G8: analyze({label}) still yields result_status == 'WAITING'",
        )
        check(
            result is not None and result["result"] == _FIXED_RESULT,
            f"G8: analyze({label}) still yields the fixed result object",
        )


# ---------------------------------------------------------------------------
# G9 -- partial Mapping input
# ---------------------------------------------------------------------------
def scenario_partial_mapping_input() -> None:
    provider = GeminiVisionProvider()
    partial = {"symbol": "TSLA", "prompt_status": "INVALID"}
    result = provider.analyze(partial)

    check(
        result["symbol"] == "TSLA",
        "G9: analyze() forwards a present field ('symbol') from a "
        "partial mapping",
    )
    check(
        result["prompt_status"] == "INVALID",
        "G9: analyze() forwards a present field ('prompt_status') "
        "from a partial mapping",
    )
    check(
        result["timeframe"] is None
        and result["chart_path"] is None
        and result["status"] is None
        and result["analysis_status"] is None,
        "G9: analyze() yields None for every field absent from a "
        "partial mapping",
    )
    check(
        result["result_status"] == "WAITING",
        "G9: analyze() on a partial mapping still yields "
        "result_status == 'WAITING'",
    )


# ---------------------------------------------------------------------------
# G10 -- deterministic behavior, no leaked state
# ---------------------------------------------------------------------------
def scenario_deterministic_no_leaked_state() -> None:
    provider = GeminiVisionProvider()

    result_a = provider.analyze(_SAMPLE_VISION_PROMPT)
    result_b = provider.analyze(dict(_SAMPLE_VISION_PROMPT))

    check(
        result_a == result_b,
        "G10: two calls with equal input produce equal output",
    )
    check(
        result_a is not result_b,
        "G10: two calls produce independently-constructed dicts "
        "(not the same object)",
    )
    check(
        result_a["result"] is not result_b["result"],
        "G10: the nested result object is freshly constructed per call",
    )

    other_prompt = {"symbol": "MSFT", "prompt_status": "READY"}
    result_c = provider.analyze(other_prompt)
    check(
        result_c["symbol"] == "MSFT" and result_a["symbol"] == "AAPL",
        "G10: successive analyze() calls with different input do "
        "not cross-contaminate each other's output",
    )


# ---------------------------------------------------------------------------
# G11 -- no instance state
# ---------------------------------------------------------------------------
def scenario_no_instance_state() -> None:
    provider = GeminiVisionProvider()
    check(
        vars(provider) == {},
        "G11: GeminiVisionProvider() carries no instance state "
        "(__dict__ is empty)",
    )
    provider.analyze(_SAMPLE_VISION_PROMPT)
    check(
        vars(provider) == {},
        "G11: calling analyze() does not add any instance state "
        "afterward",
    )


# ---------------------------------------------------------------------------
# G12 -- fully resolved abstract interface
# ---------------------------------------------------------------------------
def scenario_no_remaining_abstractmethods() -> None:
    check(
        len(GeminiVisionProvider.__abstractmethods__) == 0,
        "G12: GeminiVisionProvider has zero remaining abstractmethods",
    )


# ---------------------------------------------------------------------------
# G13 -- AST sanity check
# ---------------------------------------------------------------------------
def scenario_ast_sanity_check() -> None:
    import Providers.gemini_vision_provider as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    module_level_classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef)
    ]
    check(
        len(module_level_classes) == 1
        and module_level_classes[0].name == "GeminiVisionProvider",
        f"G13: the module defines exactly one top-level class, "
        f"'GeminiVisionProvider'; got "
        f"{[c.name for c in module_level_classes]!r}",
    )

    cls_node = module_level_classes[0]
    method_names = [
        node.name
        for node in cls_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    check(
        set(method_names) == {"name", "description", "analyze"},
        f"G13: GeminiVisionProvider defines exactly the methods "
        f"'name', 'description', 'analyze' at the AST level; got "
        f"{sorted(method_names)!r}",
    )
    check(
        "__init__" not in method_names,
        "G13: GeminiVisionProvider defines no __init__ method in the AST",
    )


# ---------------------------------------------------------------------------
# G14 -- structural sanity check: imports + forbidden references
# ---------------------------------------------------------------------------
def scenario_structural_sanity_check() -> None:
    import Providers.gemini_vision_provider as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])

    forbidden_modules = {
        "socket",
        "requests",
        "urllib",
        "http",
        "os",
        "pathlib",
        "io",
        "aiohttp",
        "httpx",
        "websocket",
        "asyncio",
        "threading",
        "sqlite3",
        "json",
        "PIL",
        "cv2",
        "matplotlib",
        "pandas",
        "numpy",
        "genai",
        "google",
        "ollama",
    }
    check(
        imported_modules.isdisjoint(forbidden_modules),
        f"G14: the module imports no networking/filesystem/Gemini-SDK "
        f"modules; imports found: {sorted(imported_modules)!r}",
    )
    check(
        imported_modules == {"__future__", "collections", "typing", "Orchestration"},
        f"G14: the module imports exactly the expected set -- got "
        f"{sorted(imported_modules)!r}",
    )

    # Forbidden architectural/vendor names, checked as real code usage
    # (class names and call targets) rather than raw substrings of
    # prose/docstrings, since the docstring legitimately *discusses*
    # several of these names in its "does NOT import" disclosure.
    class_names = [
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ]
    call_names = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    for forbidden_word in (
        "Ollama",
        "Qwen",
        "InternVL",
        "MiniCPM",
        "Factory",
        "Registry",
        "Manager",
        "Coordinator",
        "Workflow",
        "Pipeline",
        "Service",
        "Repository",
    ):
        check(
            not any(forbidden_word in cls_name for cls_name in class_names),
            f"G14: no class defined in the module has '{forbidden_word}' "
            f"in its name",
        )
        check(
            not any(forbidden_word in call_name for call_name in call_names),
            f"G14: no call expression in the module invokes anything "
            f"with '{forbidden_word}' in its name",
        )

    check(
        not hasattr(module, "genai") and not hasattr(module, "google"),
        "G14: the module's namespace contains no 'genai' or 'google' symbol",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_subclass_and_construction,
        scenario_isinstance_issubclass_relationships,
        scenario_name_is_gemini,
        scenario_description_is_exact,
        scenario_analyze_forwards_fields_unchanged,
        scenario_result_status_unconditionally_waiting,
        scenario_result_object_shape_exact,
        scenario_malformed_input_never_raises,
        scenario_partial_mapping_input,
        scenario_deterministic_no_leaked_state,
        scenario_no_instance_state,
        scenario_no_remaining_abstractmethods,
        scenario_ast_sanity_check,
        scenario_structural_sanity_check,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(
        f"PHASE 11 SPRINT 140 GEMINI VISION PROVIDER RESULTS: "
        f"{_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})"
    )
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())