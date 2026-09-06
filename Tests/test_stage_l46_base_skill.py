"""
Phase 5 Sprint 46 proof suite -- the ``BaseSkill`` contract.

Scope: dedicated regression suite for
``Orchestration.base_skill.BaseSkill`` only. Nothing else exists in
this module to test -- no ``SkillManager``, no ``SkillRuntime``, no
plugin system, no execution engine. ``Orchestration.skill_registry.
SkillRegistry`` (covered by ``Tests/test_stage_l43_skill_registry.
py``), ``Orchestration.skill_resolver.SkillResolver`` (covered by
``Tests/test_stage_l44_skill_resolver.py``), and
``Orchestration.executor.Executor`` (covered by
``Tests/test_stage_l28_sprint30_executor.py`` and
``Tests/test_stage_l45_executor_skill_resolution.py``) are all
untouched by this sprint and are not exercised here.

``BaseSkill`` is a pure, minimal ``abc.ABC`` interface: exactly three
abstract members (``name`` property, ``description`` property,
``execute(context)`` method), no ``__init__`` of its own, no default
implementation for any of them, and no additional public surface of
any kind. This suite proves the *absence* of that extra surface area
as much as it proves the presence of the three documented members.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x proof suites: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Invariant coverage:
    B1  -- BaseSkill is an abstract class: it subclasses abc.ABC, and
           its __abstractmethods__ set is exactly
           {'name', 'description', 'execute'} -- no more, no fewer.
    B2  -- BaseSkill cannot be instantiated directly -- BaseSkill()
           raises TypeError.
    B3  -- a subclass that implements only 1 or 2 of the 3 abstract
           members still cannot be instantiated -- TypeError in every
           partial-implementation case.
    B4  -- a minimal concrete subclass implementing all 3 members
           constructs successfully and is not itself abstract.
    B5  -- the concrete subclass's `name` property returns the exact
           str it was implemented to return.
    B6  -- the concrete subclass's `description` property returns the
           exact str it was implemented to return.
    B7  -- the concrete subclass's execute(context) is called with the
           exact context object (by identity) and returns whatever the
           implementation returns, unmodified.
    B8  -- isinstance(instance, BaseSkill) is True for a concrete
           subclass instance, and False for an unrelated plain object.
    B9  -- issubclass(ConcreteSkill, BaseSkill) is True; BaseSkill is
           not a subclass of the concrete class (relationship is not
           symmetric).
    B10 -- BaseSkill defines no public methods/properties beyond the
           three documented abstract members -- no metadata, priority,
           tags, category, permissions, config, schema, validation,
           registry id, aliases, requirements, dependencies, events,
           logging, memory, planning, reflection, learning, scheduler,
           runtime, workflow, executor, host, or agent attribute
           anywhere on the class.
    B11 -- BaseSkill.execute is genuinely abstract -- it has no
           implementation body beyond raising NotImplementedError, and
           calling BaseSkill.execute(self, ...) directly (bypassing
           instantiation) raises NotImplementedError, proving there is
           no pass-through/default behavior.
    B12 -- Orchestration.base_skill imports nothing beyond the stdlib
           abc/typing modules -- no import of SkillRegistry,
           SkillResolver, Executor, WorkflowRuntime, WorkflowEngine,
           WorkflowExecutionCoordinator, Planner, Workflow, Task,
           Memory, Learning, Reflection, AutonomousScheduler,
           AutonomousHost, AutonomousAgent, EventBus, or the
           Composition Root (no runtime/workflow/scheduler/event
           knowledge of any kind).
    B13 -- BaseSkill has no __init__ of its own beyond object's --
           constructing a concrete subclass with no extra state works
           with zero arguments beyond self.
    B14 -- two independently defined concrete subclasses are fully
           independent -- an instance of one is not an instance of the
           other, and each returns its own name/description/execute
           results without cross-contamination.
"""

from __future__ import annotations

import sys
import traceback
from abc import ABC
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.base_skill import BaseSkill

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
class MinimalSkill(BaseSkill):
    """The smallest possible concrete BaseSkill -- implements exactly
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


class OnlyNameSkill(BaseSkill):
    """Implements only `name` -- deliberately incomplete."""

    @property
    def name(self) -> str:
        return "only-name"


class OnlyNameAndDescriptionSkill(BaseSkill):
    """Implements `name` and `description` but not `execute` --
    deliberately incomplete."""

    @property
    def name(self) -> str:
        return "only-name-and-description"

    @property
    def description(self) -> str:
        return "still missing execute"


class OnlyExecuteSkill(BaseSkill):
    """Implements only `execute` -- deliberately incomplete."""

    def execute(self, context: Any) -> Any:
        return context


# ---------------------------------------------------------------------------
# B1 -- abstract class, exact abstract member set
# ---------------------------------------------------------------------------
def scenario_base_skill_is_abstract_with_exact_members() -> None:
    check(
        issubclass(BaseSkill, ABC),
        "B1: BaseSkill subclasses abc.ABC",
    )
    check(
        set(BaseSkill.__abstractmethods__) == {"name", "description", "execute"},
        f"B1: BaseSkill.__abstractmethods__ is exactly "
        f"{{'name', 'description', 'execute'}}; got "
        f"{set(BaseSkill.__abstractmethods__)!r}",
    )


# ---------------------------------------------------------------------------
# B2 -- cannot instantiate directly
# ---------------------------------------------------------------------------
def scenario_cannot_instantiate_base_skill_directly() -> None:
    raised = False
    try:
        BaseSkill()  # type: ignore[abstract]
    except TypeError:
        raised = True

    check(raised, "B2: BaseSkill() raises TypeError")


# ---------------------------------------------------------------------------
# B3 -- partial implementations still cannot be instantiated
# ---------------------------------------------------------------------------
def scenario_partial_implementations_cannot_instantiate() -> None:
    for cls, label in (
        (OnlyNameSkill, "OnlyNameSkill (implements only 'name')"),
        (
            OnlyNameAndDescriptionSkill,
            "OnlyNameAndDescriptionSkill (implements 'name' and "
            "'description' but not 'execute')",
        ),
        (OnlyExecuteSkill, "OnlyExecuteSkill (implements only 'execute')"),
    ):
        raised = False
        try:
            cls()  # type: ignore[abstract]
        except TypeError:
            raised = True

        check(raised, f"B3: {label} raises TypeError on instantiation")


# ---------------------------------------------------------------------------
# B4 -- minimal concrete implementation works
# ---------------------------------------------------------------------------
def scenario_minimal_concrete_implementation_constructs() -> None:
    skill = MinimalSkill(name="n", description="d", execute_result="r")

    check(
        isinstance(skill, MinimalSkill),
        "B4: a fully-implemented concrete BaseSkill subclass "
        "constructs successfully",
    )
    check(
        len(MinimalSkill.__abstractmethods__) == 0,
        "B4: MinimalSkill itself has no remaining abstract methods",
    )


# ---------------------------------------------------------------------------
# B5/B6 -- name / description properties
# ---------------------------------------------------------------------------
def scenario_name_property_returns_exact_value() -> None:
    skill = MinimalSkill(name="stock-analysis", description="d")
    check(
        skill.name == "stock-analysis",
        "B5: skill.name returns the exact str the subclass implements "
        "it to return",
    )


def scenario_description_property_returns_exact_value() -> None:
    skill = MinimalSkill(name="n", description="Analyzes stock data.")
    check(
        skill.description == "Analyzes stock data.",
        "B6: skill.description returns the exact str the subclass "
        "implements it to return",
    )


# ---------------------------------------------------------------------------
# B7 -- execute(context)
# ---------------------------------------------------------------------------
def scenario_execute_receives_context_and_returns_result() -> None:
    sentinel_context = {"ticker": "AAPL"}
    sentinel_result = object()
    skill = MinimalSkill(name="n", description="d", execute_result=sentinel_result)

    result = skill.execute(sentinel_context)

    check(
        len(skill.execute_calls) == 1 and skill.execute_calls[0] is sentinel_context,
        "B7: execute() receives the exact context object passed in, "
        "by identity",
    )
    check(
        result is sentinel_result,
        "B7: execute() returns exactly what the concrete "
        "implementation returns, unmodified",
    )


# ---------------------------------------------------------------------------
# B8 -- isinstance()
# ---------------------------------------------------------------------------
def scenario_isinstance_checks() -> None:
    skill = MinimalSkill(name="n", description="d")

    check(
        isinstance(skill, BaseSkill),
        "B8: isinstance(concrete_skill, BaseSkill) is True",
    )
    check(
        not isinstance(object(), BaseSkill),
        "B8: isinstance(plain_object, BaseSkill) is False for an "
        "unrelated object",
    )
    check(
        not isinstance("not-a-skill", BaseSkill),
        "B8: isinstance(str, BaseSkill) is False",
    )


# ---------------------------------------------------------------------------
# B9 -- subclass relationship
# ---------------------------------------------------------------------------
def scenario_subclass_relationship() -> None:
    check(
        issubclass(MinimalSkill, BaseSkill),
        "B9: issubclass(MinimalSkill, BaseSkill) is True",
    )
    check(
        not issubclass(BaseSkill, MinimalSkill),
        "B9: issubclass(BaseSkill, MinimalSkill) is False -- the "
        "relationship is not symmetric",
    )


# ---------------------------------------------------------------------------
# B10 -- no extra public methods / forbidden attributes
# ---------------------------------------------------------------------------
def scenario_no_extra_public_surface() -> None:
    public_members = {
        attr for attr in dir(BaseSkill) if not attr.startswith("_")
    }
    check(
        public_members == {"name", "description", "execute"},
        f"B10: BaseSkill's only public members are 'name', "
        f"'description', 'execute'; got {sorted(public_members)!r}",
    )

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
            not hasattr(BaseSkill, attr),
            f"B10: BaseSkill has no '{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# B11 -- execute is genuinely abstract, no default behavior
# ---------------------------------------------------------------------------
def scenario_execute_has_no_default_implementation() -> None:
    check(
        getattr(BaseSkill.execute, "__isabstractmethod__", False) is True,
        "B11: BaseSkill.execute is marked as an abstractmethod",
    )
    check(
        getattr(
            BaseSkill.__dict__["name"].fget, "__isabstractmethod__", False
        )
        is True,
        "B11: BaseSkill.name's getter is marked as an abstractmethod",
    )
    check(
        getattr(
            BaseSkill.__dict__["description"].fget,
            "__isabstractmethod__",
            False,
        )
        is True,
        "B11: BaseSkill.description's getter is marked as an "
        "abstractmethod",
    )

    # Calling the unbound abstract execute() directly (bypassing
    # instantiation entirely) must still raise NotImplementedError --
    # proving there is no pass-through/default body.
    class _Bare:
        pass

    raised_not_implemented = False
    try:
        BaseSkill.execute(_Bare(), "ctx")
    except NotImplementedError:
        raised_not_implemented = True

    check(
        raised_not_implemented,
        "B11: calling BaseSkill.execute(self, context) directly raises "
        "NotImplementedError -- no default/pass-through body",
    )


# ---------------------------------------------------------------------------
# B12 -- no forbidden imports / no runtime, workflow, scheduler, event
# knowledge
# ---------------------------------------------------------------------------
def scenario_no_forbidden_imports() -> None:
    import Orchestration.base_skill as base_skill_module

    source = Path(base_skill_module.__file__).read_text(encoding="utf-8")

    forbidden_symbols = [
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
            f"B12: Orchestration/base_skill.py contains no reference "
            f"to '{symbol}'",
        )

    check(
        not hasattr(base_skill_module, "SkillRegistry"),
        "B12: Orchestration.base_skill's module namespace does not "
        "contain a 'SkillRegistry' symbol",
    )
    check(
        not hasattr(base_skill_module, "SkillResolver"),
        "B12: Orchestration.base_skill's module namespace does not "
        "contain a 'SkillResolver' symbol",
    )
    check(
        not hasattr(base_skill_module, "Executor"),
        "B12: Orchestration.base_skill's module namespace does not "
        "contain an 'Executor' symbol",
    )


def scenario_no_runtime_workflow_scheduler_event_knowledge() -> None:
    skill = MinimalSkill(name="n", description="d")

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
            not hasattr(BaseSkill, attr) and not hasattr(skill, attr),
            f"B12: neither BaseSkill nor a concrete instance carries "
            f"a '{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# B13 -- no __init__ of its own
# ---------------------------------------------------------------------------
def scenario_no_init_of_its_own() -> None:
    check(
        BaseSkill.__init__ is object.__init__,
        "B13: BaseSkill does not define its own __init__ -- it "
        "inherits object's",
    )

    class NoInitSkill(BaseSkill):
        @property
        def name(self) -> str:
            return "no-init"

        @property
        def description(self) -> str:
            return "has no __init__ override either"

        def execute(self, context: Any) -> Any:
            return None

    skill = NoInitSkill()
    check(
        isinstance(skill, BaseSkill),
        "B13: a concrete subclass with no __init__ of its own still "
        "constructs with zero arguments",
    )


# ---------------------------------------------------------------------------
# B14 -- independence between concrete subclasses
# ---------------------------------------------------------------------------
class AlphaSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "alpha"

    @property
    def description(self) -> str:
        return "the alpha skill"

    def execute(self, context: Any) -> Any:
        return f"alpha-ran-with-{context}"


class BetaSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "beta"

    @property
    def description(self) -> str:
        return "the beta skill"

    def execute(self, context: Any) -> Any:
        return f"beta-ran-with-{context}"


def scenario_independent_concrete_subclasses() -> None:
    alpha = AlphaSkill()
    beta = BetaSkill()

    check(
        not isinstance(alpha, BetaSkill) and not isinstance(beta, AlphaSkill),
        "B14: an instance of one concrete subclass is not an instance "
        "of an unrelated concrete subclass",
    )
    check(
        alpha.name == "alpha" and beta.name == "beta",
        "B14: each subclass's name property is independent",
    )
    check(
        alpha.description == "the alpha skill"
        and beta.description == "the beta skill",
        "B14: each subclass's description property is independent",
    )
    check(
        alpha.execute("x") == "alpha-ran-with-x"
        and beta.execute("x") == "beta-ran-with-x",
        "B14: each subclass's execute() is independent -- no "
        "cross-contamination",
    )
    check(
        isinstance(alpha, BaseSkill) and isinstance(beta, BaseSkill),
        "B14: both remain valid BaseSkill instances",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_base_skill_is_abstract_with_exact_members,
        scenario_cannot_instantiate_base_skill_directly,
        scenario_partial_implementations_cannot_instantiate,
        scenario_minimal_concrete_implementation_constructs,
        scenario_name_property_returns_exact_value,
        scenario_description_property_returns_exact_value,
        scenario_execute_receives_context_and_returns_result,
        scenario_isinstance_checks,
        scenario_subclass_relationship,
        scenario_no_extra_public_surface,
        scenario_execute_has_no_default_implementation,
        scenario_no_forbidden_imports,
        scenario_no_runtime_workflow_scheduler_event_knowledge,
        scenario_no_init_of_its_own,
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
    print(f"PHASE 5 SPRINT 46 BASE SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())