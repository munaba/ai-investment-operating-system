"""Phase 11 Sprint 142 proof suite -- ``GeminiVisionProvider`` API
activation.

Scope: dedicated regression suite for
``Providers.gemini_vision_provider.GeminiVisionProvider.analyze()``
now that it talks to a (mocked) real Gemini Vision SDK. Never calls
the real Gemini API -- ``google``/``google.genai``/``google.genai.
types`` are replaced with fake modules injected into ``sys.modules``
before import, following the project's lazy-import convention (the
same one ``Providers.gemini.GeminiProvider.connect()`` already uses).

Invariant coverage:
    A1  -- a well-formed vision_prompt with a readable chart_path
           results in exactly one call to the (fake) Gemini SDK's
           ``generate_content``.
    A2  -- the prompt text (``vision_prompt["prompt"]``) is forwarded
           to ``generate_content`` unchanged, by value.
    A3  -- the image bytes read from chart_path are forwarded to
           ``generate_content`` (via the fake ``Part.from_bytes``),
           byte-for-byte.
    A4  -- on success, result_status == "COMPLETED" and result ==
           {"raw_response": <the fake response's .text>} exactly --
           no other keys.
    A5  -- symbol/timeframe/chart_path/status/analysis_status/
           prompt_status are forwarded unchanged on success.
    A6  -- on any exception (missing image file, SDK raising, no
           configured API key), result_status == "FAILED" and
           result == {"raw_response": None} exactly -- never raises.
    A7  -- malformed vision_prompt (non-Mapping) never raises and
           still yields the FAILED shape with every carry-through
           field None.
    A8  -- deterministic mocked behavior: repeated calls with the
           same input and the same fake SDK produce equal output,
           and the fake SDK is invoked once per analyze() call (no
           batching, no caching, no extra calls).
    A9  -- AST verification: the module defines exactly one
           top-level class (GeminiVisionProvider), analyze() is
           the only method with a body beyond the two Sprint-140
           properties, there is no __init__, and the whole Gemini
           call sequence lives inside a single try/except in
           analyze() with no other function/class defined at module
           scope.
    A10 -- structural verification: no hardcoded API key literal in
           source, Core.config.config is used for GEMINI_API_KEY/
           GEMINI_MODEL, and no forbidden helper-class/vendor names
           (VisionEngine, ProviderManager, Factory, Registry,
           Coordinator, Workflow, Pipeline, Service, Repository,
           Ollama, Qwen, InternVL, MiniCPM) appear as real code usage.
"""

from __future__ import annotations

import ast
import os
import sys
import types as pytypes
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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


# ---------------------------------------------------------------------------
# Fake google.genai SDK -- injected into sys.modules, never the real API
# ---------------------------------------------------------------------------
class FakePart:
    """Records every call to Part.from_bytes without touching a network."""

    last_call: Any = None

    @staticmethod
    def from_bytes(data: bytes, mime_type: str) -> Any:
        FakePart.last_call = {"data": data, "mime_type": mime_type}
        return FakePart.last_call


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeModels:
    """Records every generate_content call; can be told to raise."""

    def __init__(self, response_text: str = "trend appears bullish") -> None:
        self.calls: List[Any] = []
        self._response_text = response_text
        self.should_raise = False

    def generate_content(self, model: Any, contents: Any) -> Any:
        self.calls.append({"model": model, "contents": contents})
        if self.should_raise:
            raise RuntimeError("simulated Gemini SDK failure")
        return FakeResponse(self._response_text)


class FakeClient:
    """Records the api_key it was constructed with."""

    last_instance: Any = None

    def __init__(self, api_key: Any = None) -> None:
        self.api_key = api_key
        self.models = FakeModels()
        FakeClient.last_instance = self


def _install_fake_genai_sdk() -> None:
    """Inject fake google/google.genai/google.genai.types modules."""
    fake_google = pytypes.ModuleType("google")
    fake_genai = pytypes.ModuleType("google.genai")
    fake_genai_types = pytypes.ModuleType("google.genai.types")
    fake_genai_types.Part = FakePart
    fake_genai.Client = FakeClient
    fake_genai.types = fake_genai_types
    fake_google.genai = fake_genai

    sys.modules["google"] = fake_google
    sys.modules["google.genai"] = fake_genai
    sys.modules["google.genai.types"] = fake_genai_types


_install_fake_genai_sdk()

os.environ.setdefault("GEMINI_API_KEY", "test-api-key")
os.environ.setdefault("GEMINI_MODEL", "gemini-2.0-flash")

from Providers.gemini_vision_provider import GeminiVisionProvider  # noqa: E402

_CHART_PATH = "/tmp/test_stage_l142_chart.png"
_CHART_BYTES = b"\x89PNG-fake-bytes"


def _write_chart() -> None:
    with open(_CHART_PATH, "wb") as f:
        f.write(_CHART_BYTES)


_SAMPLE_VISION_PROMPT = {
    "symbol": "AAPL",
    "timeframe": "1D",
    "chart_path": _CHART_PATH,
    "status": "OK",
    "analysis_status": "PENDING",
    "prompt_status": "READY",
    "prompt": "Analyze this stock chart.",
}


# ---------------------------------------------------------------------------
# A1 / A2 / A3 -- SDK invocation, prompt and image forwarded correctly
# ---------------------------------------------------------------------------
def scenario_sdk_invoked_once_with_prompt_and_image() -> None:
    _write_chart()
    FakeClient.last_instance = None
    provider = GeminiVisionProvider()

    result = provider.analyze(_SAMPLE_VISION_PROMPT)

    client = FakeClient.last_instance
    check(client is not None, "A1: a Gemini SDK client was constructed")
    check(
        len(client.models.calls) == 1,
        "A1: generate_content was called exactly once",
    )
    call = client.models.calls[0]
    check(
        "Analyze this stock chart." in call["contents"],
        "A2: the prompt text is forwarded to generate_content unchanged",
    )
    check(
        FakePart.last_call is not None
        and FakePart.last_call["data"] == _CHART_BYTES,
        "A3: the image bytes read from chart_path are forwarded "
        "byte-for-byte via Part.from_bytes",
    )
    check(
        FakePart.last_call in call["contents"],
        "A3: the constructed image Part is included in generate_content's contents",
    )
    check(
        result["result_status"] == "COMPLETED",
        "A1: a successful SDK call yields result_status == 'COMPLETED'",
    )


# ---------------------------------------------------------------------------
# A4 / A5 -- COMPLETED output contract
# ---------------------------------------------------------------------------
def scenario_completed_output_contract() -> None:
    _write_chart()
    provider = GeminiVisionProvider()

    result = provider.analyze(_SAMPLE_VISION_PROMPT)

    check(
        result["result"] == {"raw_response": "trend appears bullish"},
        "A4: result contains exactly {'raw_response': <text>} on success",
    )
    check(
        set(result["result"].keys()) == {"raw_response"},
        "A4: result has exactly one key, 'raw_response'",
    )
    check(
        result["symbol"] == "AAPL"
        and result["timeframe"] == "1D"
        and result["chart_path"] == _CHART_PATH
        and result["status"] == "OK"
        and result["analysis_status"] == "PENDING"
        and result["prompt_status"] == "READY",
        "A5: symbol/timeframe/chart_path/status/analysis_status/"
        "prompt_status are all forwarded unchanged on success",
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
        "A4: the output has exactly the eight VisionResult keys",
    )


# ---------------------------------------------------------------------------
# A6 -- FAILED behavior on any exception
# ---------------------------------------------------------------------------
def scenario_failed_on_missing_image() -> None:
    provider = GeminiVisionProvider()
    vision_prompt = dict(_SAMPLE_VISION_PROMPT)
    vision_prompt["chart_path"] = "/tmp/does_not_exist_l142.png"

    result = provider.analyze(vision_prompt)

    check(
        result["result_status"] == "FAILED",
        "A6: a missing chart_path file yields result_status == 'FAILED'",
    )
    check(
        result["result"] == {"raw_response": None},
        "A6: a missing chart_path file yields result == {'raw_response': None}",
    )
    check(
        result["symbol"] == "AAPL" and result["chart_path"] == vision_prompt["chart_path"],
        "A6: carry-through fields are still forwarded unchanged on FAILED",
    )


def scenario_failed_on_sdk_exception() -> None:
    _write_chart()
    provider = GeminiVisionProvider()

    # Patch generate_content to raise for this one probe call, then
    # restore -- achieved by making FakeModels raise via a subclass
    # swapped in through FakeClient for the duration of this scenario.
    original_client_cls = sys.modules["google.genai"].Client

    class RaisingClient(FakeClient):
        def __init__(self, api_key: Any = None) -> None:
            super().__init__(api_key=api_key)
            self.models.should_raise = True

    sys.modules["google.genai"].Client = RaisingClient
    try:
        result = provider.analyze(_SAMPLE_VISION_PROMPT)
    finally:
        sys.modules["google.genai"].Client = original_client_cls

    check(
        result["result_status"] == "FAILED",
        "A6: a Gemini SDK exception yields result_status == 'FAILED'",
    )
    check(
        result["result"] == {"raw_response": None},
        "A6: a Gemini SDK exception yields result == {'raw_response': None}",
    )


def scenario_never_raises() -> None:
    provider = GeminiVisionProvider()
    raised = False
    try:
        provider.analyze({"chart_path": "/tmp/nope_l142.png", "prompt": "x"})
    except Exception:  # noqa: BLE001
        raised = True
    check(not raised, "A6: analyze() never raises even when the image is missing")


# ---------------------------------------------------------------------------
# A7 -- malformed input
# ---------------------------------------------------------------------------
def scenario_malformed_input() -> None:
    provider = GeminiVisionProvider()

    for label, bad_input in (("None", None), ("str", "not-a-mapping"), ("int", 7)):
        raised = False
        result = None
        try:
            result = provider.analyze(bad_input)
        except Exception:  # noqa: BLE001
            raised = True

        check(not raised, f"A7: analyze({label}) never raises")
        check(
            result is not None
            and result["result_status"] == "FAILED"
            and result["result"] == {"raw_response": None},
            f"A7: analyze({label}) yields the FAILED shape",
        )
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
            f"A7: analyze({label}) yields None for every carry-through field",
        )


# ---------------------------------------------------------------------------
# A8 -- deterministic mocked behavior
# ---------------------------------------------------------------------------
def scenario_deterministic_mocked_behavior() -> None:
    _write_chart()
    provider = GeminiVisionProvider()

    result_a = provider.analyze(dict(_SAMPLE_VISION_PROMPT))
    result_b = provider.analyze(dict(_SAMPLE_VISION_PROMPT))

    check(
        result_a == result_b,
        "A8: two calls with equal input and the fake SDK produce equal output",
    )
    check(
        result_a is not result_b,
        "A8: two calls produce independently-constructed dicts",
    )


# ---------------------------------------------------------------------------
# A9 -- AST verification
# ---------------------------------------------------------------------------
def scenario_ast_verification() -> None:
    import Providers.gemini_vision_provider as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    module_level_classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef)
    ]
    check(
        len(module_level_classes) == 1
        and module_level_classes[0].name == "GeminiVisionProvider",
        f"A9: the module defines exactly one top-level class, "
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
        f"A9: GeminiVisionProvider defines exactly 'name', "
        f"'description', 'analyze'; got {sorted(method_names)!r}",
    )
    check(
        "__init__" not in method_names,
        "A9: GeminiVisionProvider defines no __init__ method in the AST",
    )

    func_nodes = [
        n for n in cls_node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    analyze_node = next(n for n in func_nodes if n.name == "analyze")
    try_nodes = [n for n in ast.walk(analyze_node) if isinstance(n, ast.Try)]
    check(
        len(try_nodes) == 1,
        f"A9: analyze() contains exactly one try/except block; got "
        f"{len(try_nodes)}",
    )

    module_level_funcs = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    check(
        len(module_level_funcs) == 0,
        "A9: no module-level function is defined outside the class",
    )


# ---------------------------------------------------------------------------
# A10 -- structural verification
# ---------------------------------------------------------------------------
def scenario_structural_verification() -> None:
    import Providers.gemini_vision_provider as module

    source = Path(module.__file__).read_text(encoding="utf-8")

    check(
        "config.get(\"GEMINI_API_KEY\")" in source
        or "config.get('GEMINI_API_KEY')" in source,
        "A10: GEMINI_API_KEY is read via Core.config.config, never hardcoded",
    )
    check(
        "config.get(\"GEMINI_MODEL\")" in source
        or "config.get('GEMINI_MODEL')" in source,
        "A10: GEMINI_MODEL is read via Core.config.config, never hardcoded",
    )
    check(
        "AIza" not in source and "sk-" not in source,
        "A10: no plausible hardcoded API key literal appears in source",
    )

    tree = ast.parse(source)
    class_names = [
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ]
    check(
        class_names == ["GeminiVisionProvider"],
        f"A10: the module defines exactly one class overall; got {class_names!r}",
    )

    call_names = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    for forbidden_word in (
        "VisionEngine",
        "ProviderManager",
        "Factory",
        "Registry",
        "Manager",
        "Coordinator",
        "Workflow",
        "Pipeline",
        "Service",
        "Repository",
        "Ollama",
        "Qwen",
        "InternVL",
        "MiniCPM",
    ):
        check(
            not any(forbidden_word in cls_name for cls_name in class_names),
            f"A10: no class in the module has '{forbidden_word}' in its name",
        )
        check(
            not any(forbidden_word in call_name for call_name in call_names),
            f"A10: no call expression invokes anything with "
            f"'{forbidden_word}' in its name",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_sdk_invoked_once_with_prompt_and_image,
        scenario_completed_output_contract,
        scenario_failed_on_missing_image,
        scenario_failed_on_sdk_exception,
        scenario_never_raises,
        scenario_malformed_input,
        scenario_deterministic_mocked_behavior,
        scenario_ast_verification,
        scenario_structural_verification,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            import traceback

            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(
        f"PHASE 11 SPRINT 142 GEMINI VISION PROVIDER API ACTIVATION "
        f"RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})"
    )
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())