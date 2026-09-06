"""
Phase 5 Sprint 50 proof suite -- the ``BaseTool`` contract.

Scope: dedicated regression suite for
``Orchestration.base_tool.BaseTool`` only. Nothing else exists in this
module to test -- no concrete Tool, no ``ToolRegistry``, no
``ToolResolver``, no execution engine, no wiring into
``Orchestration.base_skill.BaseSkill``, ``Orchestration.
file_system_skill.FileSystemSkill``, ``Orchestration.
text_analysis_skill.TextAnalysisSkill``, ``Orchestration.
skill_context.SkillContext``, ``Orchestration.skill_result.
SkillResult``, ``Orchestration.skill_registry.SkillRegistry``,
``Orchestration.skill_resolver.SkillResolver``, or ``Orchestration.
executor.Executor``. Mirrors ``Tests/test_stage_l46_base_skill.py`` in
style and structure, one layer down the architecture (Planner -> Skill
-> Tool -> Services/Repository/API).

``BaseTool`` is a pure, minimal ``abc.ABC`` interface: exactly three
abstract members (``name`` property, ``description`` property,
``execute(context)`` method), no constructor of its own, no default
implementation for any of them, and no additional public surface of
any kind. This suite proves the *absence* of that extra surface area
as much as it proves the presence of the three documented members.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    U1  -- BaseTool is abstract: it subclasses abc.ABC, and its
           __abstractmethods__ set is exactly {'name', 'description',
           'execute'} -- no more, no fewer.
    U2  -- BaseTool cannot be instantiated -- BaseTool() raises
           TypeError.
    U3  -- a subclass that implements only 1 or 2 of the 3 abstract
           members still cannot be instantiated -- TypeError in every
           partial-implementation case.
    U4  -- a minimal concrete subclass implementing all 3 members
           constructs successfully and is not itself abstract.
    U5  -- the concrete subclass's `name` property returns the exact
           str it was implemented to return.
    U6  -- the concrete subclass's `description` property returns the
           exact str it was implemented to return.
    U7  -- execute has no default behavior: BaseTool.execute is
           marked abstract, name/description getters are marked
           abstract, and calling BaseTool.execute(self, ...) directly
           (bypassing instantiation) raises NotImplementedError --
           proving there is no pass-through/default body.
    U8  -- the concrete subclass's execute(context) is called with
           the exact context object (by identity) and returns
           whatever the implementation returns, unmodified.
    U9  -- public surface exact: BaseTool's only public members are
           'name', 'description', 'execute' -- nothing else.
    U10 -- no constructor: BaseTool defines no __init__ of its own --
           it inherits object's -- and a concrete subclass with no
           extra state constructs with zero arguments.
    U11 -- no helper methods / no mixins: BaseTool defines no method
           beyond the three abstract members and no attribute of any
           kind for metadata, priority, tags, category, permissions,
           config, schema, validate, validation, registry, tool_id,
           aliases, requirements, dependencies, execute_async,
           capability, timeout, retry.
    U12 -- forbidden imports absent: Orchestration/base_tool.py
           contains no reference to BaseSkill, SkillContext,
           SkillResult, FileSystemSkill, TextAnalysisSkill,
           SkillRegistry, SkillResolver, Executor, WorkflowRuntime,
           WorkflowEngine, WorkflowExecutionCoordinator, Planner,
           Memory, LearningLoop, Reflection, AutonomousScheduler,
           AutonomousHost, AutonomousAgent, EventBus, or
           composition_root.
    U13 -- forbidden symbols absent from the module's own namespace.
    U14 -- namespace clean: isinstance/issubclass relationships hold
           as expected (isinstance(concrete, BaseTool) is True;
           BaseTool is not a subclass of a concrete subclass).
    U15 -- zero runtime behavior / no execution logic: neither the
           class nor an instance carries any runtime-, workflow-,
           executor-, scheduler-, or event-shaped attribute.
    U16 -- no filesystem access: constructing a concrete BaseTool
           subclass and calling its execute() creates no file or
           directory as a side effect (for a minimal implementation
           with no filesystem logic of its own).
    U17 -- no networking: no network-related attribute (session,
           socket, connection, client) exists on the class or an
           instance.
    U18 -- no provider/service/repository dependency: neither the
           class nor an instance carries a provider/service/
           repository/database attribute.
    U19 -- no workflow/scheduler dependency: neither the class nor an
           instance carries a workflow/scheduler attribute (covered
           together with U15 for completeness).
    U20 -- no memory/planner dependency: neither the class nor an
           instance carries a memory/planner/reflection/learning
           attribute.
    U21 -- two independently defined concrete subclasses are fully
           independent -- an instance of one is not an instance of
           the other, and each returns its own name/description/
           execute results without cross-contamination.
"""

from __future__ import annotations

import os
import sys
import traceback
from abc import ABC
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.base_tool import BaseTool

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
class MinimalTool(BaseTool):
    """The smallest possible concrete BaseTool -- implements exactly
    the three required abstract members and nothing else."""

    def __init__(self, name: str, description: str, execute_result: Any = None) -> None:
        self._name = name
        self._description = description
        self._execute_result = execute_result
        self.execute_calls: List[Any] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def execute(self, context: Any) -> Any:
        self.execute_calls.append(context)
        return self._execute_result


class OnlyNameTool(BaseTool):
    """Implements only `name` -- deliberately incomplete."""

    @property
    def name(self) -> str:
        return "only-name"


class OnlyNameAndDescriptionTool(BaseTool):
    """Implements `name` and `description` but not `execute` --
    deliberately incomplete."""

    @property
    def name(self) -> str:
        return "only-name-and-description"

    @property
    def description(self) -> str:
        return "still missing execute"


class OnlyExecuteTool(BaseTool):
    """Implements only `execute` -- deliberately incomplete."""

    def execute(self, context: Any) -> Any:
        return context


# ---------------------------------------------------------------------------
# U1 -- abstract class, exact abstract member set
# ---------------------------------------------------------------------------
def scenario_base_tool_is_abstract_with_exact_members() -> None:
    check(
        issubclass(BaseTool, ABC),
        "U1: BaseTool subclasses abc.ABC",
    )
    check(
        set(BaseTool.__abstractmethods__) == {"name", "description", "execute"},
        f"U1: BaseTool.__abstractmethods__ is exactly "
        f"{{'name', 'description', 'execute'}}; got "
        f"{set(BaseTool.__abstractmethods__)!r}",
    )


# ---------------------------------------------------------------------------
# U2 -- cannot instantiate directly
# ---------------------------------------------------------------------------
def scenario_cannot_instantiate_base_tool_directly() -> None:
    raised = False
    try:
        BaseTool()  # type: ignore[abstract]
    except TypeError:
        raised = True

    check(raised, "U2: BaseTool() raises TypeError")


# ---------------------------------------------------------------------------
# U3 -- partial implementations still cannot be instantiated
# ---------------------------------------------------------------------------
def scenario_partial_implementations_cannot_instantiate() -> None:
    for cls, label in (
        (OnlyNameTool, "OnlyNameTool (implements only 'name')"),
        (
            OnlyNameAndDescriptionTool,
            "OnlyNameAndDescriptionTool (implements 'name' and "
            "'description' but not 'execute')",
        ),
        (OnlyExecuteTool, "OnlyExecuteTool (implements only 'execute')"),
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
    tool = MinimalTool(name="n", description="d", execute_result="r")

    check(
        isinstance(tool, MinimalTool),
        "U4: a fully-implemented concrete BaseTool subclass "
        "constructs successfully",
    )
    check(
        len(MinimalTool.__abstractmethods__) == 0,
        "U4: MinimalTool itself has no remaining abstract methods",
    )


# ---------------------------------------------------------------------------
# U5/U6 -- name / description properties
# ---------------------------------------------------------------------------
def scenario_name_property_returns_exact_value() -> None:
    tool = MinimalTool(name="price-fetcher", description="d")
    check(
        tool.name == "price-fetcher",
        "U5: tool.name returns the exact str the subclass implements "
        "it to return",
    )


def scenario_description_property_returns_exact_value() -> None:
    tool = MinimalTool(name="n", description="Fetches raw price data.")
    check(
        tool.description == "Fetches raw price data.",
        "U6: tool.description returns the exact str the subclass "
        "implements it to return",
    )


# ---------------------------------------------------------------------------
# U7 -- execute is genuinely abstract, no default behavior
# ---------------------------------------------------------------------------
def scenario_execute_has_no_default_implementation() -> None:
    check(
        getattr(BaseTool.execute, "__isabstractmethod__", False) is True,
        "U7: BaseTool.execute is marked as an abstractmethod",
    )
    check(
        getattr(
            BaseTool.__dict__["name"].fget, "__isabstractmethod__", False
        )
        is True,
        "U7: BaseTool.name's getter is marked as an abstractmethod",
    )
    check(
        getattr(
            BaseTool.__dict__["description"].fget,
            "__isabstractmethod__",
            False,
        )
        is True,
        "U7: BaseTool.description's getter is marked as an "
        "abstractmethod",
    )

    class _Bare:
        pass

    raised_not_implemented = False
    try:
        BaseTool.execute(_Bare(), "ctx")
    except NotImplementedError:
        raised_not_implemented = True

    check(
        raised_not_implemented,
        "U7: calling BaseTool.execute(self, context) directly raises "
        "NotImplementedError -- no default/pass-through body",
    )


# ---------------------------------------------------------------------------
# U8 -- execute(context)
# ---------------------------------------------------------------------------
def scenario_execute_receives_context_and_returns_result() -> None:
    sentinel_context = {"ticker": "AAPL"}
    sentinel_result = object()
    tool = MinimalTool(name="n", description="d", execute_result=sentinel_result)

    result = tool.execute(sentinel_context)

    check(
        len(tool.execute_calls) == 1 and tool.execute_calls[0] is sentinel_context,
        "U8: execute() receives the exact context object passed in, "
        "by identity",
    )
    check(
        result is sentinel_result,
        "U8: execute() returns exactly what the concrete "
        "implementation returns, unmodified",
    )


# ---------------------------------------------------------------------------
# U9 -- public surface exact
# ---------------------------------------------------------------------------
def scenario_public_surface_exact() -> None:
    public_members = {
        attr for attr in dir(BaseTool) if not attr.startswith("_")
    }
    check(
        public_members == {"name", "description", "execute"},
        f"U9: BaseTool's only public members are 'name', "
        f"'description', 'execute'; got {sorted(public_members)!r}",
    )


# ---------------------------------------------------------------------------
# U10 -- no constructor
# ---------------------------------------------------------------------------
def scenario_no_constructor() -> None:
    check(
        BaseTool.__init__ is object.__init__,
        "U10: BaseTool does not define its own __init__ -- it "
        "inherits object's",
    )

    class NoInitTool(BaseTool):
        @property
        def name(self) -> str:
            return "no-init"

        @property
        def description(self) -> str:
            return "has no __init__ override either"

        def execute(self, context: Any) -> Any:
            return None

    tool = NoInitTool()
    check(
        isinstance(tool, BaseTool),
        "U10: a concrete subclass with no __init__ of its own still "
        "constructs with zero arguments",
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
        "tool_id",
        "aliases",
        "requirements",
        "dependencies",
        "execute_async",
        "capability",
        "capabilities",
        "timeout",
        "retry",
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
    ]
    for attr in forbidden_attrs:
        check(
            not hasattr(BaseTool, attr),
            f"U11: BaseTool has no '{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# U12 / U13 -- forbidden imports / forbidden symbols in module namespace
# ---------------------------------------------------------------------------
def scenario_no_forbidden_imports() -> None:
    import Orchestration.base_tool as base_tool_module

    source = Path(base_tool_module.__file__).read_text(encoding="utf-8")

    forbidden_symbols = [
        "BaseSkill",
        "SkillContext",
        "SkillResult",
        "FileSystemSkill",
        "TextAnalysisSkill",
        "SkillRegistry",
        "SkillResolver",
        "Executor",
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "Planner",
        "Workflow",
        "Task",
        "Memory",
        "LearningLoop",
        "Reflection",
        "AutonomousScheduler",
        "AutonomousHost",
        "AutonomousAgent",
        "EventBus",
        "composition_root",
    ]
    for symbol in forbidden_symbols:
        check(
            f"import {symbol}" not in source and f"{symbol}(" not in source,
            f"U12: Orchestration/base_tool.py contains no reference "
            f"to '{symbol}'",
        )

    for symbol in (
        "BaseSkill",
        "SkillRegistry",
        "SkillResolver",
        "Executor",
        "Planner",
    ):
        check(
            not hasattr(base_tool_module, symbol),
            f"U13: Orchestration.base_tool's module namespace does "
            f"not contain a '{symbol}' symbol",
        )


# ---------------------------------------------------------------------------
# U14 -- isinstance / issubclass relationships
# ---------------------------------------------------------------------------
def scenario_isinstance_issubclass_relationships() -> None:
    tool = MinimalTool(name="n", description="d")

    check(
        isinstance(tool, BaseTool),
        "U14: isinstance(concrete_tool, BaseTool) is True",
    )
    check(
        not isinstance(object(), BaseTool),
        "U14: isinstance(plain_object, BaseTool) is False for an "
        "unrelated object",
    )
    check(
        not isinstance("not-a-tool", BaseTool),
        "U14: isinstance(str, BaseTool) is False",
    )
    check(
        issubclass(MinimalTool, BaseTool),
        "U14: issubclass(MinimalTool, BaseTool) is True",
    )
    check(
        not issubclass(BaseTool, MinimalTool),
        "U14: issubclass(BaseTool, MinimalTool) is False -- the "
        "relationship is not symmetric",
    )


# ---------------------------------------------------------------------------
# U15 -- zero runtime behavior / no execution logic
# ---------------------------------------------------------------------------
def scenario_zero_runtime_behavior() -> None:
    tool = MinimalTool(name="n", description="d")

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
            not hasattr(BaseTool, attr) and not hasattr(tool, attr),
            f"U15: neither BaseTool nor a concrete instance carries "
            f"a '{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# U16 -- no filesystem access
# ---------------------------------------------------------------------------
def scenario_no_filesystem_side_effects() -> None:
    before = set(os.listdir("."))

    tool = MinimalTool(name="n", description="d", execute_result=None)
    tool.execute("anything")

    after = set(os.listdir("."))
    check(
        before == after,
        "U16: constructing a minimal BaseTool subclass and calling "
        "its execute() creates no file or directory as a side effect",
    )


# ---------------------------------------------------------------------------
# U17 -- no networking
# ---------------------------------------------------------------------------
def scenario_no_networking() -> None:
    tool = MinimalTool(name="n", description="d")

    for attr in ("session", "socket", "connection", "client", "request"):
        check(
            not hasattr(BaseTool, attr) and not hasattr(tool, attr),
            f"U17: neither BaseTool nor a concrete instance carries "
            f"a '{attr}' networking attribute",
        )


# ---------------------------------------------------------------------------
# U18 -- no provider/service/repository dependency
# ---------------------------------------------------------------------------
def scenario_no_provider_service_repository_dependency() -> None:
    tool = MinimalTool(name="n", description="d")

    for attr in ("provider", "service", "repository", "database"):
        check(
            not hasattr(BaseTool, attr) and not hasattr(tool, attr),
            f"U18: neither BaseTool nor a concrete instance carries "
            f"a '{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# U19 -- no workflow/scheduler dependency (completeness check alongside U15)
# ---------------------------------------------------------------------------
def scenario_no_workflow_scheduler_dependency() -> None:
    tool = MinimalTool(name="n", description="d")

    for attr in ("workflow", "scheduler"):
        check(
            not hasattr(BaseTool, attr) and not hasattr(tool, attr),
            f"U19: neither BaseTool nor a concrete instance carries "
            f"a '{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# U20 -- no memory/planner dependency
# ---------------------------------------------------------------------------
def scenario_no_memory_planner_dependency() -> None:
    tool = MinimalTool(name="n", description="d")

    for attr in ("memory", "planner", "reflection", "learning"):
        check(
            not hasattr(BaseTool, attr) and not hasattr(tool, attr),
            f"U20: neither BaseTool nor a concrete instance carries "
            f"a '{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# U21 -- independence between concrete subclasses
# ---------------------------------------------------------------------------
class AlphaTool(BaseTool):
    @property
    def name(self) -> str:
        return "alpha-tool"

    @property
    def description(self) -> str:
        return "the alpha tool"

    def execute(self, context: Any) -> Any:
        return f"alpha-ran-with-{context}"


class BetaTool(BaseTool):
    @property
    def name(self) -> str:
        return "beta-tool"

    @property
    def description(self) -> str:
        return "the beta tool"

    def execute(self, context: Any) -> Any:
        return f"beta-ran-with-{context}"


def scenario_independent_concrete_subclasses() -> None:
    alpha = AlphaTool()
    beta = BetaTool()

    check(
        not isinstance(alpha, BetaTool) and not isinstance(beta, AlphaTool),
        "U21: an instance of one concrete subclass is not an "
        "instance of an unrelated concrete subclass",
    )
    check(
        alpha.name == "alpha-tool" and beta.name == "beta-tool",
        "U21: each subclass's name property is independent",
    )
    check(
        alpha.description == "the alpha tool"
        and beta.description == "the beta tool",
        "U21: each subclass's description property is independent",
    )
    check(
        alpha.execute("x") == "alpha-ran-with-x"
        and beta.execute("x") == "beta-ran-with-x",
        "U21: each subclass's execute() is independent -- no "
        "cross-contamination",
    )
    check(
        isinstance(alpha, BaseTool) and isinstance(beta, BaseTool),
        "U21: both remain valid BaseTool instances",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_base_tool_is_abstract_with_exact_members,
        scenario_cannot_instantiate_base_tool_directly,
        scenario_partial_implementations_cannot_instantiate,
        scenario_minimal_concrete_implementation_constructs,
        scenario_name_property_returns_exact_value,
        scenario_description_property_returns_exact_value,
        scenario_execute_has_no_default_implementation,
        scenario_execute_receives_context_and_returns_result,
        scenario_public_surface_exact,
        scenario_no_constructor,
        scenario_no_helper_methods_or_forbidden_attrs,
        scenario_no_forbidden_imports,
        scenario_isinstance_issubclass_relationships,
        scenario_zero_runtime_behavior,
        scenario_no_filesystem_side_effects,
        scenario_no_networking,
        scenario_no_provider_service_repository_dependency,
        scenario_no_workflow_scheduler_dependency,
        scenario_no_memory_planner_dependency,
        scenario_independent_concrete_subclasses,
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
    print(f"PHASE 5 SPRINT 50 BASE TOOL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())