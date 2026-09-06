"""
Phase 11 Sprint 139 proof suite -- the ``BaseVisionProvider``
contract.

Scope: dedicated regression suite for
``Providers.base_vision_provider.BaseVisionProvider`` only. Nothing
else exists in this module to test -- no concrete Vision Provider
(no Gemini, no Ollama, no Qwen, no InternVL, no MiniCPM, no Llama),
no registry, no factory, no manager, no coordinator, no workflow, no
pipeline, no service, no repository, and no wiring into
``Orchestration.base_skill.BaseSkill``, ``Orchestration.base_tool.
BaseTool``, ``Orchestration.vision_prompt_skill.VisionPromptSkill``,
or ``Orchestration.vision_result_skill.VisionResultSkill``. Mirrors
``Tests/test_stage_l50_base_tool.py`` in style and structure, applied
one layer over: this is the base interface every future Vision
Provider must implement.

``BaseVisionProvider`` is a pure, minimal ``abc.ABC`` interface:
exactly three abstract members (``name`` property, ``description``
property, ``analyze(vision_prompt)`` method), no constructor of its
own, no default implementation for any of them, and no additional
public surface of any kind. This suite proves the *absence* of that
extra surface area as much as it proves the presence of the three
documented members.

Follows the same scenario-based, no-pytest, no-external-mocks style
as the other Stage L4x/L5x/L138 proof suites: a global pass/fail
counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    U1  -- BaseVisionProvider is abstract: it subclasses abc.ABC, and
           its __abstractmethods__ set is exactly {'name',
           'description', 'analyze'} -- no more, no fewer.
    U2  -- BaseVisionProvider cannot be instantiated --
           BaseVisionProvider() raises TypeError.
    U3  -- a subclass that implements only 1 or 2 of the 3 abstract
           members still cannot be instantiated -- TypeError in every
           partial-implementation case.
    U4  -- a minimal concrete subclass implementing all 3 members
           constructs successfully and is not itself abstract.
    U5  -- the concrete subclass's `name` property returns the exact
           str it was implemented to return.
    U6  -- the concrete subclass's `description` property returns the
           exact str it was implemented to return.
    U7  -- analyze has no default behavior: BaseVisionProvider.analyze
           is marked abstract, name/description getters are marked
           abstract, and calling BaseVisionProvider.analyze(self, ...)
           directly (bypassing instantiation) raises
           NotImplementedError -- proving there is no
           pass-through/default body.
    U8  -- the concrete subclass's analyze(vision_prompt) is called
           with the exact vision_prompt object (by identity) and
           returns whatever the implementation returns, unmodified --
           including a VisionResult-shaped mapping.
    U9  -- public surface exact: BaseVisionProvider's only public
           members are 'name', 'description', 'analyze' -- nothing
           else.
    U10 -- no constructor: BaseVisionProvider defines no __init__ of
           its own -- it inherits object's -- and a concrete subclass
           with no extra state constructs with zero arguments.
    U11 -- no helper methods / no mixins: BaseVisionProvider defines
           no method beyond the three abstract members and no
           attribute of any kind for metadata, priority, tags,
           category, permissions, config, schema, validate,
           validation, registry, provider_id, aliases, requirements,
           dependencies, analyze_async, capability, timeout, retry,
           cache, factory, manager, coordinator, workflow, pipeline,
           service, repository.
    U12 -- forbidden imports absent: Providers/base_vision_provider.py
           contains no reference to Gemini, Ollama, InternVL, Qwen,
           MiniCPM, Llama, VisionEngine, VisionManager, VisionFactory,
           VisionRegistry, VisionPipeline, VisionWorkflow,
           VisionCoordinator, VisionService, VisionRepository,
           BaseSkill, BaseTool, VisionPromptSkill, VisionResultSkill,
           Executor, ToolResolver, ToolRegistry, ProviderManager,
           ProviderSelector, Factory, Registry, Manager, Coordinator,
           Workflow, Pipeline, Service, Repository.
    U13 -- forbidden symbols absent from the module's own namespace.
    U14 -- isinstance / issubclass relationships hold as expected.
    U15 -- zero runtime behavior / no execution logic: neither the
           class nor an instance carries any runtime-, workflow-,
           executor-, scheduler-, or event-shaped attribute.
    U16 -- no filesystem access: constructing a concrete
           BaseVisionProvider subclass and calling its analyze()
           creates no file or directory as a side effect (for a
           minimal implementation with no filesystem logic of its
           own).
    U17 -- no networking: no network-related attribute (session,
           socket, connection, client) exists on the class or an
           instance, and the module source contains no networking or
           filesystem import (socket, requests, urllib, http, os,
           pathlib, io).
    U18 -- no provider/service/repository dependency: neither the
           class nor an instance carries a provider/service/
           repository/database attribute.
    U19 -- no memory/planner dependency: neither the class nor an
           instance carries a memory/planner/reflection/learning
           attribute.
    U20 -- two independently defined concrete subclasses are fully
           independent -- an instance of one is not an instance of
           the other, and each returns its own name/description/
           analyze results without cross-contamination.
    U21 -- AST verification: the module defines exactly one class
           (BaseVisionProvider), it has no __init__ method defined in
           the AST, and every function body inside the class is
           either a single `raise` statement or a docstring followed
           by a single `raise` statement -- i.e. no real logic exists
           anywhere in the module.
    U22 -- inheritance shape: BaseVisionProvider's only base is
           abc.ABC (object is reached only through ABC).
"""

from __future__ import annotations

import ast
import os
import sys
import traceback
from abc import ABC
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Providers.base_vision_provider import BaseVisionProvider

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
_SAMPLE_VISION_RESULT = {
    "symbol": "AAPL",
    "timeframe": "1D",
    "chart_path": "/charts/aapl.png",
    "status": "OK",
    "analysis_status": "OK",
    "prompt_status": "READY",
    "result_status": "WAITING",
    "result": {
        "trend": None,
        "support": None,
        "resistance": None,
        "candlestick_pattern": None,
        "volume_signal": None,
        "rsi_signal": None,
        "macd_signal": None,
        "confidence": None,
    },
}


class MinimalVisionProvider(BaseVisionProvider):
    """The smallest possible concrete BaseVisionProvider -- implements
    exactly the three required abstract members and nothing else."""

    def __init__(self, name: str, description: str, analyze_result: Any = None) -> None:
        self._name = name
        self._description = description
        self._analyze_result = analyze_result
        self.analyze_calls: List[Any] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def analyze(self, vision_prompt: Any) -> Any:
        self.analyze_calls.append(vision_prompt)
        return self._analyze_result


class OnlyNameProvider(BaseVisionProvider):
    """Implements only `name` -- deliberately incomplete."""

    @property
    def name(self) -> str:
        return "only-name"


class OnlyNameAndDescriptionProvider(BaseVisionProvider):
    """Implements `name` and `description` but not `analyze` --
    deliberately incomplete."""

    @property
    def name(self) -> str:
        return "only-name-and-description"

    @property
    def description(self) -> str:
        return "still missing analyze"


class OnlyAnalyzeProvider(BaseVisionProvider):
    """Implements only `analyze` -- deliberately incomplete."""

    def analyze(self, vision_prompt: Any) -> Any:
        return vision_prompt


# ---------------------------------------------------------------------------
# U1 -- abstract class, exact abstract member set
# ---------------------------------------------------------------------------
def scenario_base_vision_provider_is_abstract_with_exact_members() -> None:
    check(
        issubclass(BaseVisionProvider, ABC),
        "U1: BaseVisionProvider subclasses abc.ABC",
    )
    check(
        set(BaseVisionProvider.__abstractmethods__)
        == {"name", "description", "analyze"},
        f"U1: BaseVisionProvider.__abstractmethods__ is exactly "
        f"{{'name', 'description', 'analyze'}}; got "
        f"{set(BaseVisionProvider.__abstractmethods__)!r}",
    )


# ---------------------------------------------------------------------------
# U2 -- cannot instantiate directly
# ---------------------------------------------------------------------------
def scenario_cannot_instantiate_base_vision_provider_directly() -> None:
    raised = False
    try:
        BaseVisionProvider()  # type: ignore[abstract]
    except TypeError:
        raised = True

    check(raised, "U2: BaseVisionProvider() raises TypeError")


# ---------------------------------------------------------------------------
# U3 -- partial implementations still cannot be instantiated
# ---------------------------------------------------------------------------
def scenario_partial_implementations_cannot_instantiate() -> None:
    for cls, label in (
        (OnlyNameProvider, "OnlyNameProvider (implements only 'name')"),
        (
            OnlyNameAndDescriptionProvider,
            "OnlyNameAndDescriptionProvider (implements 'name' and "
            "'description' but not 'analyze')",
        ),
        (OnlyAnalyzeProvider, "OnlyAnalyzeProvider (implements only 'analyze')"),
    ):
        raised = False
        try:
            cls()  # type: ignore[abstract]
        except TypeError:
            raised = True

        check(raised, f"U3: {label} raises TypeError on instantiation")


# ---------------------------------------------------------------------------
# U4 -- minimal concrete implementation works
# ---------------------------------------------------------------------------
def scenario_minimal_concrete_implementation_constructs() -> None:
    provider = MinimalVisionProvider(name="n", description="d", analyze_result="r")

    check(
        isinstance(provider, MinimalVisionProvider),
        "U4: a fully-implemented concrete BaseVisionProvider "
        "subclass constructs successfully",
    )
    check(
        len(MinimalVisionProvider.__abstractmethods__) == 0,
        "U4: MinimalVisionProvider itself has no remaining abstract "
        "methods",
    )


# ---------------------------------------------------------------------------
# U5/U6 -- name / description properties
# ---------------------------------------------------------------------------
def scenario_name_property_returns_exact_value() -> None:
    provider = MinimalVisionProvider(name="chart-vision", description="d")
    check(
        provider.name == "chart-vision",
        "U5: provider.name returns the exact str the subclass "
        "implements it to return",
    )


def scenario_description_property_returns_exact_value() -> None:
    provider = MinimalVisionProvider(
        name="n", description="Analyzes chart images and returns a VisionResult."
    )
    check(
        provider.description
        == "Analyzes chart images and returns a VisionResult.",
        "U6: provider.description returns the exact str the "
        "subclass implements it to return",
    )


# ---------------------------------------------------------------------------
# U7 -- analyze is genuinely abstract, no default behavior
# ---------------------------------------------------------------------------
def scenario_analyze_has_no_default_implementation() -> None:
    check(
        getattr(BaseVisionProvider.analyze, "__isabstractmethod__", False) is True,
        "U7: BaseVisionProvider.analyze is marked as an abstractmethod",
    )
    check(
        getattr(
            BaseVisionProvider.__dict__["name"].fget, "__isabstractmethod__", False
        )
        is True,
        "U7: BaseVisionProvider.name's getter is marked as an "
        "abstractmethod",
    )
    check(
        getattr(
            BaseVisionProvider.__dict__["description"].fget,
            "__isabstractmethod__",
            False,
        )
        is True,
        "U7: BaseVisionProvider.description's getter is marked as an "
        "abstractmethod",
    )

    class _Bare:
        pass

    raised_not_implemented = False
    try:
        BaseVisionProvider.analyze(_Bare(), "vision_prompt")
    except NotImplementedError:
        raised_not_implemented = True

    check(
        raised_not_implemented,
        "U7: calling BaseVisionProvider.analyze(self, vision_prompt) "
        "directly raises NotImplementedError -- no default/"
        "pass-through body",
    )


# ---------------------------------------------------------------------------
# U8 -- analyze(vision_prompt)
# ---------------------------------------------------------------------------
def scenario_analyze_receives_vision_prompt_and_returns_result() -> None:
    sentinel_prompt = {"symbol": "AAPL", "timeframe": "1D", "prompt_status": "READY"}
    provider = MinimalVisionProvider(
        name="n", description="d", analyze_result=_SAMPLE_VISION_RESULT
    )

    result = provider.analyze(sentinel_prompt)

    check(
        len(provider.analyze_calls) == 1
        and provider.analyze_calls[0] is sentinel_prompt,
        "U8: analyze() receives the exact vision_prompt object passed "
        "in, by identity",
    )
    check(
        result is _SAMPLE_VISION_RESULT,
        "U8: analyze() returns exactly what the concrete "
        "implementation returns, unmodified",
    )
    check(
        result["result_status"] == "WAITING"
        and set(result["result"].keys())
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
        "U8: the VisionResult-shaped return value passes through "
        "with its Sprint 138 shape intact",
    )


# ---------------------------------------------------------------------------
# U9 -- public surface exact
# ---------------------------------------------------------------------------
def scenario_public_surface_exact() -> None:
    public_members = {
        attr for attr in dir(BaseVisionProvider) if not attr.startswith("_")
    }
    check(
        public_members == {"name", "description", "analyze"},
        f"U9: BaseVisionProvider's only public members are 'name', "
        f"'description', 'analyze'; got {sorted(public_members)!r}",
    )


# ---------------------------------------------------------------------------
# U10 -- no constructor
# ---------------------------------------------------------------------------
def scenario_no_constructor() -> None:
    check(
        BaseVisionProvider.__init__ is object.__init__,
        "U10: BaseVisionProvider does not define its own __init__ -- "
        "it inherits object's",
    )

    class NoInitProvider(BaseVisionProvider):
        @property
        def name(self) -> str:
            return "no-init"

        @property
        def description(self) -> str:
            return "has no __init__ override either"

        def analyze(self, vision_prompt: Any) -> Any:
            return None

    provider = NoInitProvider()
    check(
        isinstance(provider, BaseVisionProvider),
        "U10: a concrete subclass with no __init__ of its own still "
        "constructs with zero arguments",
    )
    check(
        vars(provider) == {},
        "U10: a concrete subclass with no __init__ of its own carries "
        "no instance state (__dict__ is empty)",
    )


# ---------------------------------------------------------------------------
# U11 -- no helper methods / no mixins / forbidden attributes
# ---------------------------------------------------------------------------
def scenario_no_helper_methods_or_forbidden_attrs() -> None:
    forbidden_attrs = [
        "metadata",
        "priority",
        "tags",
        "category",
        "permissions",
        "config",
        "schema",
        "validate",
        "validation",
        "registry",
        "provider_id",
        "aliases",
        "requirements",
        "dependencies",
        "analyze_async",
        "capability",
        "capabilities",
        "timeout",
        "retry",
        "cache",
        "events",
        "event_bus",
        "logging",
        "logger",
        "memory",
        "planning",
        "planner",
        "reflection",
        "learning",
        "scheduler",
        "runtime",
        "workflow",
        "executor",
        "host",
        "agent",
        "factory",
        "manager",
        "coordinator",
        "pipeline",
        "service",
        "repository",
    ]
    for attr in forbidden_attrs:
        check(
            not hasattr(BaseVisionProvider, attr),
            f"U11: BaseVisionProvider has no '{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# U12 / U13 -- forbidden imports / forbidden symbols in module namespace
# ---------------------------------------------------------------------------
def scenario_no_forbidden_imports() -> None:
    import Providers.base_vision_provider as base_vision_provider_module

    source = Path(base_vision_provider_module.__file__).read_text(encoding="utf-8")

    forbidden_symbols = [
        "Gemini",
        "Ollama",
        "InternVL",
        "Qwen",
        "MiniCPM",
        "Llama",
        "VisionEngine",
        "VisionManager",
        "VisionFactory",
        "VisionRegistry",
        "VisionPipeline",
        "VisionWorkflow",
        "VisionCoordinator",
        "VisionService",
        "VisionRepository",
        "BaseSkill",
        "BaseTool",
        "VisionPromptSkill",
        "VisionResultSkill",
        "Executor",
        "ToolResolver",
        "ToolRegistry",
        "ProviderManager",
        "ProviderSelector",
    ]
    for symbol in forbidden_symbols:
        check(
            f"import {symbol}" not in source and f"{symbol}(" not in source,
            f"U12: Providers/base_vision_provider.py contains no "
            f"reference to '{symbol}'",
        )

    # Forbidden architectural class-name suffixes/words, per the
    # sprint's FORBIDDEN list -- checked as real code usage (not as
    # substrings of prose/docstrings), via the class definition list.
    tree = ast.parse(source)
    class_names = [
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ]
    for forbidden_word in (
        "Factory",
        "Registry",
        "Manager",
        "Coordinator",
        "Workflow",
        "Pipeline",
        "Service",
        "Repository",
        "Gemini",
        "Ollama",
        "InternVL",
        "Qwen",
        "MiniCPM",
        "Llama",
    ):
        check(
            not any(forbidden_word in cls_name for cls_name in class_names),
            f"U12: no class defined in the module has '{forbidden_word}' "
            f"in its name; classes found: {class_names!r}",
        )

    for symbol in (
        "BaseSkill",
        "BaseTool",
        "VisionPromptSkill",
        "VisionResultSkill",
        "ProviderManager",
        "ProviderSelector",
    ):
        check(
            not hasattr(base_vision_provider_module, symbol),
            f"U13: Providers.base_vision_provider's module namespace "
            f"does not contain a '{symbol}' symbol",
        )


# ---------------------------------------------------------------------------
# U14 -- isinstance / issubclass relationships
# ---------------------------------------------------------------------------
def scenario_isinstance_issubclass_relationships() -> None:
    provider = MinimalVisionProvider(name="n", description="d")

    check(
        isinstance(provider, BaseVisionProvider),
        "U14: isinstance(concrete_provider, BaseVisionProvider) is True",
    )
    check(
        not isinstance(object(), BaseVisionProvider),
        "U14: isinstance(plain_object, BaseVisionProvider) is False "
        "for an unrelated object",
    )
    check(
        not isinstance("not-a-provider", BaseVisionProvider),
        "U14: isinstance(str, BaseVisionProvider) is False",
    )
    check(
        issubclass(MinimalVisionProvider, BaseVisionProvider),
        "U14: issubclass(MinimalVisionProvider, BaseVisionProvider) "
        "is True",
    )
    check(
        not issubclass(BaseVisionProvider, MinimalVisionProvider),
        "U14: issubclass(BaseVisionProvider, MinimalVisionProvider) "
        "is False -- the relationship is not symmetric",
    )


# ---------------------------------------------------------------------------
# U15 -- zero runtime behavior / no execution logic
# ---------------------------------------------------------------------------
def scenario_zero_runtime_behavior() -> None:
    provider = MinimalVisionProvider(name="n", description="d")

    for attr in (
        "runtime",
        "workflow",
        "workflow_engine",
        "scheduler",
        "event_bus",
        "events",
        "host",
        "executor",
        "agent",
    ):
        check(
            not hasattr(BaseVisionProvider, attr) and not hasattr(provider, attr),
            f"U15: neither BaseVisionProvider nor a concrete instance "
            f"carries a '{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# U16 -- no filesystem access
# ---------------------------------------------------------------------------
def scenario_no_filesystem_side_effects() -> None:
    before = set(os.listdir("."))

    provider = MinimalVisionProvider(name="n", description="d", analyze_result=None)
    provider.analyze("anything")

    after = set(os.listdir("."))
    check(
        before == after,
        "U16: constructing a minimal BaseVisionProvider subclass and "
        "calling its analyze() creates no file or directory as a "
        "side effect",
    )


# ---------------------------------------------------------------------------
# U17 -- no networking / no filesystem imports
# ---------------------------------------------------------------------------
def scenario_no_networking() -> None:
    provider = MinimalVisionProvider(name="n", description="d")

    for attr in ("session", "socket", "connection", "client", "request"):
        check(
            not hasattr(BaseVisionProvider, attr) and not hasattr(provider, attr),
            f"U17: neither BaseVisionProvider nor a concrete instance "
            f"carries a '{attr}' networking attribute",
        )

    import Providers.base_vision_provider as base_vision_provider_module

    tree = ast.parse(
        Path(base_vision_provider_module.__file__).read_text(encoding="utf-8")
    )
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
    }
    check(
        imported_modules.isdisjoint(forbidden_modules),
        f"U17: the module imports no networking/filesystem/inference "
        f"modules; imports found: {sorted(imported_modules)!r}",
    )
    check(
        imported_modules == {"__future__", "abc", "typing"},
        f"U17: the module imports exactly {{'__future__', 'abc', "
        f"'typing'}} -- got {sorted(imported_modules)!r}",
    )


# ---------------------------------------------------------------------------
# U18 -- no provider/service/repository dependency
# ---------------------------------------------------------------------------
def scenario_no_provider_service_repository_dependency() -> None:
    provider = MinimalVisionProvider(name="n", description="d")

    for attr in ("service", "repository", "database"):
        check(
            not hasattr(BaseVisionProvider, attr) and not hasattr(provider, attr),
            f"U18: neither BaseVisionProvider nor a concrete instance "
            f"carries a '{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# U19 -- no memory/planner dependency
# ---------------------------------------------------------------------------
def scenario_no_memory_planner_dependency() -> None:
    provider = MinimalVisionProvider(name="n", description="d")

    for attr in ("memory", "planner", "reflection", "learning"):
        check(
            not hasattr(BaseVisionProvider, attr) and not hasattr(provider, attr),
            f"U19: neither BaseVisionProvider nor a concrete instance "
            f"carries a '{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# U20 -- independence between concrete subclasses
# ---------------------------------------------------------------------------
class AlphaVisionProvider(BaseVisionProvider):
    @property
    def name(self) -> str:
        return "alpha-vision-provider"

    @property
    def description(self) -> str:
        return "the alpha vision provider"

    def analyze(self, vision_prompt: Any) -> Any:
        return f"alpha-analyzed-{vision_prompt}"


class BetaVisionProvider(BaseVisionProvider):
    @property
    def name(self) -> str:
        return "beta-vision-provider"

    @property
    def description(self) -> str:
        return "the beta vision provider"

    def analyze(self, vision_prompt: Any) -> Any:
        return f"beta-analyzed-{vision_prompt}"


def scenario_independent_concrete_subclasses() -> None:
    alpha = AlphaVisionProvider()
    beta = BetaVisionProvider()

    check(
        not isinstance(alpha, BetaVisionProvider)
        and not isinstance(beta, AlphaVisionProvider),
        "U20: an instance of one concrete subclass is not an "
        "instance of an unrelated concrete subclass",
    )
    check(
        alpha.name == "alpha-vision-provider"
        and beta.name == "beta-vision-provider",
        "U20: each subclass's name property is independent",
    )
    check(
        alpha.description == "the alpha vision provider"
        and beta.description == "the beta vision provider",
        "U20: each subclass's description property is independent",
    )
    check(
        alpha.analyze("x") == "alpha-analyzed-x"
        and beta.analyze("x") == "beta-analyzed-x",
        "U20: each subclass's analyze() is independent -- no "
        "cross-contamination",
    )
    check(
        isinstance(alpha, BaseVisionProvider) and isinstance(beta, BaseVisionProvider),
        "U20: both remain valid BaseVisionProvider instances",
    )


# ---------------------------------------------------------------------------
# U21 -- AST verification: exactly one class, no logic beyond raise
# ---------------------------------------------------------------------------
def scenario_ast_verification_no_logic() -> None:
    import Providers.base_vision_provider as base_vision_provider_module

    source = Path(base_vision_provider_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    module_level_classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef)
    ]
    check(
        len(module_level_classes) == 1
        and module_level_classes[0].name == "BaseVisionProvider",
        f"U21: the module defines exactly one top-level class, "
        f"'BaseVisionProvider'; got "
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
        f"U21: BaseVisionProvider defines exactly the methods "
        f"'name', 'description', 'analyze' at the AST level; got "
        f"{sorted(method_names)!r}",
    )
    check(
        "__init__" not in method_names,
        "U21: BaseVisionProvider defines no __init__ method in the AST",
    )

    for node in cls_node.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        # Strip a leading docstring, if present.
        if body and isinstance(body[0], ast.Expr) and isinstance(
            body[0].value, ast.Constant
        ):
            body = body[1:]
        check(
            len(body) == 1 and isinstance(body[0], ast.Raise),
            f"U21: method '{node.name}' contains no logic beyond a "
            f"single raise statement (after any docstring)",
        )


# ---------------------------------------------------------------------------
# U22 -- inheritance shape
# ---------------------------------------------------------------------------
def scenario_inheritance_shape() -> None:
    check(
        BaseVisionProvider.__bases__ == (ABC,),
        f"U22: BaseVisionProvider's only base class is abc.ABC; got "
        f"{BaseVisionProvider.__bases__!r}",
    )
    check(
        object in BaseVisionProvider.__mro__,
        "U22: object is reached in BaseVisionProvider's MRO (via ABC)",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_base_vision_provider_is_abstract_with_exact_members,
        scenario_cannot_instantiate_base_vision_provider_directly,
        scenario_partial_implementations_cannot_instantiate,
        scenario_minimal_concrete_implementation_constructs,
        scenario_name_property_returns_exact_value,
        scenario_description_property_returns_exact_value,
        scenario_analyze_has_no_default_implementation,
        scenario_analyze_receives_vision_prompt_and_returns_result,
        scenario_public_surface_exact,
        scenario_no_constructor,
        scenario_no_helper_methods_or_forbidden_attrs,
        scenario_no_forbidden_imports,
        scenario_isinstance_issubclass_relationships,
        scenario_zero_runtime_behavior,
        scenario_no_filesystem_side_effects,
        scenario_no_networking,
        scenario_no_provider_service_repository_dependency,
        scenario_no_memory_planner_dependency,
        scenario_independent_concrete_subclasses,
        scenario_ast_verification_no_logic,
        scenario_inheritance_shape,
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
        f"PHASE 11 SPRINT 139 BASE VISION PROVIDER RESULTS: "
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