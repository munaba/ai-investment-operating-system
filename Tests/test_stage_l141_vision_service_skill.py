"""Phase 11 Sprint 141 proof suite -- the ``VisionServiceSkill``
contract.

Scope: dedicated regression suite for
``Orchestration.vision_service_skill.VisionServiceSkill`` only.
Nothing else exists in this module to test -- no real Vision Provider
(no Gemini, no Ollama, no Qwen, no InternVL, no MiniCPM), no Tool, no
Service, no Repository, no registry, no factory, no manager, no
coordinator, no workflow, no pipeline, no provider resolver, and no
Provider selection/routing logic. Mirrors the existing Stage L13x/
L135-L140 proof suites in style: a global pass/fail counter, plain
fixtures, and a ``main()`` runner. Does not duplicate any invariant
already proven by ``Tests/test_stage_l46_base_skill.py``.

``VisionServiceSkill`` is a pure delegation boundary: its constructor
stores exactly one Vision Provider by identity, and its ``execute()``
reads ``context.parameters["vision_prompt"]`` defensively, calls
``vision_provider.analyze(vision_prompt)`` exactly once, and returns
whatever that call returns -- by identity, unwrapped.

Invariant coverage:
    V1  -- VisionServiceSkill is a BaseSkill subclass and constructs
           with exactly one positional argument.
    V2  -- the constructor stores the given vision_provider by
           identity on self._vision_provider -- no copy, no wrapping.
    V3  -- execute() calls vision_provider.analyze() exactly once per
           execute() call.
    V4  -- the VisionPrompt found at context.parameters["vision_prompt"]
           is forwarded to analyze() by identity, unchanged.
    V5  -- the provider's return value is returned by execute()
           exactly by identity -- not wrapped in a SkillResult, not
           rebuilt, not copied.
    V6  -- malformed context.parameters (non-Mapping, or missing
           entirely) never raises and results in analyze(None) being
           called.
    V7  -- a Mapping context.parameters missing the "vision_prompt"
           key also results in analyze(None).
    V8  -- deterministic behavior: repeated execute() calls with the
           same vision_prompt each call analyze() exactly once more
           and return that call's own result, with no cross-call
           state leaking through the Skill.
    V9  -- independence: two VisionServiceSkill instances wired to
           two different providers never call each other's provider.
    V10 -- AST verification: the module defines exactly one top-level
           class (VisionServiceSkill), its __init__ takes exactly one
           parameter beyond self, and execute()'s body contains
           exactly one call to a `.analyze(` attribute method with no
           other call expressions.
    V11 -- structural verification: the module imports no
           networking/filesystem/Tool/Service/Repository/vendor
           modules, and its source contains no reference to Gemini,
           Ollama, Qwen, InternVL, MiniCPM, Factory, Registry,
           Manager, Coordinator, Workflow, Pipeline, or
           ProviderResolver as real code usage.
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.base_skill import BaseSkill
from Orchestration.vision_service_skill import VisionServiceSkill

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
# Fixtures
# ---------------------------------------------------------------------------
class FakeVisionProvider:
    """A minimal test double recording every analyze() call."""

    def __init__(self, result: Any = None) -> None:
        self._result = result
        self.calls: List[Any] = []

    def analyze(self, vision_prompt: Any) -> Any:
        self.calls.append(vision_prompt)
        return self._result


class FakeContext:
    """A minimal object exposing only a `.parameters` attribute."""

    def __init__(self, parameters: Any) -> None:
        self.parameters = parameters


class NoParametersContext:
    """A context object with no `.parameters` attribute at all."""


_SAMPLE_VISION_PROMPT = {
    "symbol": "AAPL",
    "timeframe": "1D",
    "chart_path": "/charts/aapl.png",
    "status": "OK",
    "analysis_status": "PENDING",
    "prompt_status": "READY",
    "prompt": "Analyze this stock chart.",
}

_SAMPLE_VISION_RESULT = {
    "symbol": "AAPL",
    "result_status": "COMPLETED",
    "result": {"raw_response": "trend up"},
}


# ---------------------------------------------------------------------------
# V1 -- subclass + single-argument construction
# ---------------------------------------------------------------------------
def scenario_subclass_and_construction() -> None:
    provider = FakeVisionProvider()
    skill = VisionServiceSkill(provider)

    check(
        issubclass(VisionServiceSkill, BaseSkill),
        "V1: VisionServiceSkill subclasses BaseSkill",
    )
    check(
        isinstance(skill, VisionServiceSkill),
        "V1: VisionServiceSkill(vision_provider) constructs with "
        "exactly one positional argument",
    )
    check(
        len(VisionServiceSkill.__abstractmethods__) == 0,
        "V1: VisionServiceSkill has zero remaining abstractmethods",
    )


# ---------------------------------------------------------------------------
# V2 -- stored by identity
# ---------------------------------------------------------------------------
def scenario_stores_provider_by_identity() -> None:
    provider = FakeVisionProvider()
    skill = VisionServiceSkill(provider)

    check(
        skill._vision_provider is provider,
        "V2: the constructor stores vision_provider by identity on "
        "self._vision_provider",
    )

    other_provider = FakeVisionProvider()
    other_skill = VisionServiceSkill(other_provider)
    check(
        other_skill._vision_provider is other_provider
        and other_skill._vision_provider is not provider,
        "V2: a distinct instance stores its own distinct provider "
        "by identity",
    )


# ---------------------------------------------------------------------------
# V3 / V4 -- analyze() called exactly once, vision_prompt forwarded
# ---------------------------------------------------------------------------
def scenario_analyze_called_once_with_forwarded_prompt() -> None:
    provider = FakeVisionProvider(result=_SAMPLE_VISION_RESULT)
    skill = VisionServiceSkill(provider)

    skill.execute(FakeContext({"vision_prompt": _SAMPLE_VISION_PROMPT}))

    check(
        len(provider.calls) == 1,
        "V3: execute() calls vision_provider.analyze() exactly once",
    )
    check(
        provider.calls[0] is _SAMPLE_VISION_PROMPT,
        "V4: the vision_prompt found in context.parameters is "
        "forwarded to analyze() by identity, unchanged",
    )


# ---------------------------------------------------------------------------
# V5 -- return value by identity, unwrapped
# ---------------------------------------------------------------------------
def scenario_return_value_by_identity() -> None:
    provider = FakeVisionProvider(result=_SAMPLE_VISION_RESULT)
    skill = VisionServiceSkill(provider)

    result = skill.execute(FakeContext({"vision_prompt": _SAMPLE_VISION_PROMPT}))

    check(
        result is _SAMPLE_VISION_RESULT,
        "V5: execute() returns exactly what analyze() returned, by "
        "identity",
    )
    check(
        not hasattr(result, "success") and not hasattr(result, "output"),
        "V5: execute()'s return value is not wrapped in a SkillResult",
    )


def scenario_return_value_various_types() -> None:
    for label, sentinel in (
        ("None", None),
        ("string", "raw-gemini-text"),
        ("list", [1, 2, 3]),
    ):
        provider = FakeVisionProvider(result=sentinel)
        skill = VisionServiceSkill(provider)
        result = skill.execute(FakeContext({"vision_prompt": {}}))
        check(
            result is sentinel,
            f"V5: execute() forwards a provider result of type "
            f"{label} by identity, unmodified",
        )


# ---------------------------------------------------------------------------
# V6 -- malformed / missing parameters never raise
# ---------------------------------------------------------------------------
def scenario_malformed_parameters_never_raise() -> None:
    for label, bad_context in (
        ("non-Mapping parameters (str)", FakeContext("not-a-mapping")),
        ("non-Mapping parameters (int)", FakeContext(42)),
        ("non-Mapping parameters (list)", FakeContext([1, 2])),
        ("None parameters", FakeContext(None)),
        ("no .parameters attribute", NoParametersContext()),
    ):
        provider = FakeVisionProvider(result="ok")
        skill = VisionServiceSkill(provider)

        raised = False
        try:
            skill.execute(bad_context)
        except Exception:  # noqa: BLE001
            raised = True

        check(not raised, f"V6: execute() with {label} never raises")
        check(
            len(provider.calls) == 1 and provider.calls[0] is None,
            f"V6: execute() with {label} calls analyze(None)",
        )


# ---------------------------------------------------------------------------
# V7 -- Mapping missing "vision_prompt" key
# ---------------------------------------------------------------------------
def scenario_missing_vision_prompt_key() -> None:
    provider = FakeVisionProvider(result="ok")
    skill = VisionServiceSkill(provider)

    skill.execute(FakeContext({"some_other_key": "value"}))

    check(
        len(provider.calls) == 1 and provider.calls[0] is None,
        "V7: a Mapping parameters missing 'vision_prompt' results in "
        "analyze(None) being called",
    )


# ---------------------------------------------------------------------------
# V8 -- deterministic repeated calls, no cross-call state
# ---------------------------------------------------------------------------
def scenario_deterministic_repeated_calls() -> None:
    provider = FakeVisionProvider(result="stable-result")
    skill = VisionServiceSkill(provider)

    prompt_a = {"symbol": "AAPL"}
    prompt_b = {"symbol": "MSFT"}

    result_1 = skill.execute(FakeContext({"vision_prompt": prompt_a}))
    result_2 = skill.execute(FakeContext({"vision_prompt": prompt_b}))
    result_3 = skill.execute(FakeContext({"vision_prompt": prompt_a}))

    check(
        len(provider.calls) == 3,
        "V8: three execute() calls result in exactly three analyze() calls",
    )
    check(
        provider.calls == [prompt_a, prompt_b, prompt_a],
        "V8: each call forwards its own vision_prompt, in order, "
        "with no cross-call leakage",
    )
    check(
        result_1 == "stable-result"
        and result_2 == "stable-result"
        and result_3 == "stable-result",
        "V8: repeated calls with a stable provider yield stable results",
    )


# ---------------------------------------------------------------------------
# V9 -- independence between instances
# ---------------------------------------------------------------------------
def scenario_independent_instances() -> None:
    provider_alpha = FakeVisionProvider(result="alpha-result")
    provider_beta = FakeVisionProvider(result="beta-result")
    skill_alpha = VisionServiceSkill(provider_alpha)
    skill_beta = VisionServiceSkill(provider_beta)

    skill_alpha.execute(FakeContext({"vision_prompt": {"symbol": "A"}}))

    check(
        len(provider_alpha.calls) == 1 and len(provider_beta.calls) == 0,
        "V9: calling one VisionServiceSkill instance never invokes "
        "another instance's provider",
    )

    skill_beta.execute(FakeContext({"vision_prompt": {"symbol": "B"}}))
    check(
        len(provider_alpha.calls) == 1 and len(provider_beta.calls) == 1,
        "V9: each instance's provider call count is independent",
    )


# ---------------------------------------------------------------------------
# V10 -- AST verification
# ---------------------------------------------------------------------------
def scenario_ast_verification() -> None:
    import Orchestration.vision_service_skill as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    module_level_classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef)
    ]
    check(
        len(module_level_classes) == 1
        and module_level_classes[0].name == "VisionServiceSkill",
        f"V10: the module defines exactly one top-level class, "
        f"'VisionServiceSkill'; got "
        f"{[c.name for c in module_level_classes]!r}",
    )

    cls_node = module_level_classes[0]
    method_names = [
        node.name
        for node in cls_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    check(
        set(method_names) == {"__init__", "name", "description", "execute"},
        f"V10: VisionServiceSkill defines exactly '__init__', 'name', "
        f"'description', 'execute' at the AST level; got "
        f"{sorted(method_names)!r}",
    )

    func_nodes = [
        n for n in cls_node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    init_node = next(n for n in func_nodes if n.name == "__init__")
    init_params = [arg.arg for arg in init_node.args.args]
    check(
        init_params == ["self", "vision_provider"],
        f"V10: __init__ takes exactly one parameter beyond self "
        f"('vision_provider'); got {init_params!r}",
    )

    execute_node = next(n for n in func_nodes if n.name == "execute")
    call_attr_names = [
        node.func.attr
        for node in ast.walk(execute_node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    check(
        call_attr_names.count("analyze") == 1,
        f"V10: execute()'s body contains exactly one call to an "
        f"'.analyze(' attribute method; got {call_attr_names!r}",
    )
    check(
        set(call_attr_names) <= {"analyze", "get"},
        f"V10: execute() calls only '.analyze(' and defensive "
        f"'.get(' -- no other method calls; got {call_attr_names!r}",
    )


# ---------------------------------------------------------------------------
# V11 -- structural verification: imports + forbidden references
# ---------------------------------------------------------------------------
def scenario_structural_verification() -> None:
    import Orchestration.vision_service_skill as module

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
        "asyncio",
        "threading",
        "sqlite3",
        "json",
        "Providers",
        "Services",
        "Database",
        "Agents",
    }
    check(
        imported_modules.isdisjoint(forbidden_modules),
        f"V11: the module imports no networking/filesystem/Provider/"
        f"Service/Repository modules; imports found: "
        f"{sorted(imported_modules)!r}",
    )
    check(
        imported_modules == {"__future__", "collections", "typing", "Orchestration"},
        f"V11: the module imports exactly the expected set -- got "
        f"{sorted(imported_modules)!r}",
    )

    class_names = [
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ]
    call_names = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    for forbidden_word in (
        "Gemini",
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
        "ProviderResolver",
    ):
        check(
            not any(forbidden_word in cls_name for cls_name in class_names),
            f"V11: no class defined in the module has '{forbidden_word}' "
            f"in its name",
        )
        check(
            not any(forbidden_word in call_name for call_name in call_names),
            f"V11: no call expression in the module invokes anything "
            f"with '{forbidden_word}' in its name",
        )

    check(
        not hasattr(module, "execute_tool") and not hasattr(module, "ToolResolver"),
        "V11: the module namespace has no Tool-related symbol",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_subclass_and_construction,
        scenario_stores_provider_by_identity,
        scenario_analyze_called_once_with_forwarded_prompt,
        scenario_return_value_by_identity,
        scenario_return_value_various_types,
        scenario_malformed_parameters_never_raise,
        scenario_missing_vision_prompt_key,
        scenario_deterministic_repeated_calls,
        scenario_independent_instances,
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
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(
        f"PHASE 11 SPRINT 141 VISION SERVICE SKILL RESULTS: "
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