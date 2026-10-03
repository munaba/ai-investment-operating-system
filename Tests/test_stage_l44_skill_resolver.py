"""
Phase 5 Sprint 44 proof suite -- ``SkillResolver`` (Task -> Skill
resolution).

Scope: dedicated regression suite for the Sprint 44 addition only --
``Orchestration.skill_resolver.SkillResolver``, a single-method class
that resolves a ``Task`` to a registered skill via exact
``task.name`` -> ``SkillRegistry`` key match, plus its own
``SkillResolverError`` exception type. This is resolution only: no
execution, no routing engine, no fuzzy/alias/metadata/scoring/
embedding matching, no Planner integration, no AI, and no wiring into
Executor, WorkflowRuntime, WorkflowEngine,
WorkflowExecutionCoordinator, GoalPlanner, Memory, Reflection,
LearningLoop, AutonomousScheduler, AutonomousHost, AutonomousAgent, or
EventBus. ``Orchestration.skill_registry.SkillRegistry`` (Stage 43,
exercised in full by ``Tests/test_stage_l43_skill_registry.py``) and
``Orchestration.task.Task`` (Sprint 24) are both unchanged by this
sprint -- this suite does not re-verify their own behavior beyond
confirming Sprint 44 introduces no regression to them.

SkillResolver never imports, constructs, or references Executor,
Workflow/WorkflowEngine/WorkflowRuntime/WorkflowExecutionCoordinator,
GoalPlanner, Memory, Reflection, LearningLoop, AutonomousScheduler,
AutonomousHost, AutonomousAgent, or EventBus (proven both by
module-namespace inspection and by AST-level import inspection of the
module's own source file). ``Orchestration.skill_resolver`` imports
only ``Core.exceptions.AgentError``, ``Orchestration.task.Task``,
``Orchestration.skill_registry.SkillRegistry``, and the stdlib
``typing`` module.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L4x / Sprint 1x-43 proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    S1  -- constructor validation: SkillResolver(None) and
           SkillResolver(<non-registry>) both raise
           SkillResolverError; SkillResolver(SkillRegistry()) succeeds.
    S2  -- resolve success: resolve(task) returns the skill registered
           under task.name.
    S3  -- resolve returns identical object: the returned object is
           the exact same instance (identity) that was registered,
           never a copy or wrapper.
    S4  -- multiple skills: distinct tasks resolve to their own
           distinct, correctly matched skills out of a registry
           holding several.
    S5  -- duplicate registry isolation: two SkillResolver instances
           built over two independent SkillRegistry instances never
           cross-resolve into each other's skills.
    S6  -- registry miss propagation: resolve(task) for a name not in
           the registry raises SkillRegistryError (not
           SkillResolverError), unmodified/unwrapped from
           SkillRegistry.get().
    S7  -- invalid task: resolve(<non-Task>) raises
           SkillResolverError for a variety of non-Task objects.
    S8  -- None task: resolve(None) raises SkillResolverError.
    S9  -- exact matching only: a name differing by case, whitespace,
           or partial substring does not resolve -- it raises
           SkillRegistryError exactly like any other miss (no fuzzy
           matching).
    S10 -- metadata ignored: two tasks with the same name but
           different metadata resolve to the exact same skill --
           metadata plays no role in resolution.
    S11 -- description ignored: two tasks with the same name but
           different descriptions resolve to the exact same skill.
    S12 -- insertion order irrelevant: registering skills in a
           different order does not change which skill a given
           task.name resolves to.
    S13 -- forbidden imports: Orchestration.skill_resolver's own
           source file imports only Core.exceptions, Orchestration.task,
           Orchestration.skill_registry, and typing (AST-level import
           inspection) -- no Executor/Workflow*/Planner/Memory/
           Reflection/LearningLoop/Scheduler/Host/Agent/EventBus
           import anywhere in the file.
    S14 -- forbidden execution surface: a SkillResolver instance
           exposes no call/execute/run/invoke/dispatch-shaped method
           -- resolve() is its only public method.
    S15 -- repr stability: repr() of a SkillResolverError is stable
           across repeated calls and mentions the class name.
    S16 -- error hierarchy: SkillResolverError subclasses
           Core.exceptions.AgentError, which subclasses Exception.
    S17 -- no planner knowledge: Orchestration.skill_resolver's module
           namespace contains no GoalPlanner/Planner symbol.
    S18 -- no workflow knowledge: Orchestration.skill_resolver's
           module namespace contains no Workflow/WorkflowEngine/
           WorkflowRuntime/WorkflowExecutionCoordinator symbol.
    S19 -- no runtime knowledge: Orchestration.skill_resolver's module
           namespace contains no Executor symbol, and a SkillResolver
           instance is never given (and exposes no attribute holding)
           an Executor-shaped object.
    S20 -- no scheduler knowledge: Orchestration.skill_resolver's
           module namespace contains no AutonomousScheduler/Scheduler/
           AutonomousHost symbol.
    S21 -- no EventBus knowledge: Orchestration.skill_resolver's
           module namespace contains no EventBus/Event symbol; a
           SkillResolver instance exposes no publish/subscribe/attach-
           shaped method.
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.skill_registry import SkillRegistry, SkillRegistryError
from Orchestration.skill_resolver import SkillResolver, SkillResolverError
from Orchestration.task import Task

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


class _Skill:
    """A plain, arbitrary Python object used as a stand-in skill --
    the resolver does not care about its shape at all."""

    def __init__(self, label: str) -> None:
        self.label = label

    def __repr__(self) -> str:
        return f"_Skill({self.label!r})"


def _task(name: str, description: str = "", metadata=None) -> Task:
    return Task(name=name, description=description, metadata=metadata or {})


# ---------------------------------------------------------------------------
# S1 -- constructor validation
# ---------------------------------------------------------------------------
def scenario_constructor_validation() -> None:
    raised = False
    try:
        SkillResolver(None)  # type: ignore[arg-type]
    except SkillResolverError:
        raised = True
    check(raised, "S1: SkillResolver(None) raises SkillResolverError")

    for bad in ("not-a-registry", 123, object(), [], {}, Task(name="x", description="")):
        raised = False
        try:
            SkillResolver(bad)  # type: ignore[arg-type]
        except SkillResolverError:
            raised = True
        check(
            raised,
            f"S1: SkillResolver({bad!r}) raises SkillResolverError "
            f"when not a SkillRegistry instance",
        )

    resolver = SkillResolver(SkillRegistry())
    check(
        isinstance(resolver, SkillResolver),
        "S1: SkillResolver(SkillRegistry()) constructs successfully",
    )


# ---------------------------------------------------------------------------
# S2 -- resolve success
# ---------------------------------------------------------------------------
def scenario_resolve_success() -> None:
    registry = SkillRegistry()
    skill = _Skill("browser")
    registry.register("browser", skill)

    resolver = SkillResolver(registry)
    resolved = resolver.resolve(_task("browser"))

    check(resolved is skill, "S2: resolve(task) returns the skill registered under task.name")


# ---------------------------------------------------------------------------
# S3 -- resolve returns identical object
# ---------------------------------------------------------------------------
def scenario_resolve_returns_identical_object() -> None:
    registry = SkillRegistry()
    skill = _Skill("python")
    registry.register("python", skill)
    resolver = SkillResolver(registry)

    first = resolver.resolve(_task("python"))
    second = resolver.resolve(_task("python"))

    check(first is skill and second is skill, "S3: resolve() always returns the exact same object (identity)")
    check(first is second, "S3: repeated resolve() calls return the identical object")


# ---------------------------------------------------------------------------
# S4 -- multiple skills
# ---------------------------------------------------------------------------
def scenario_multiple_skills() -> None:
    registry = SkillRegistry()
    browser_skill = _Skill("browser")
    python_skill = _Skill("python")
    sql_skill = _Skill("sql")
    registry.register("browser", browser_skill)
    registry.register("python", python_skill)
    registry.register("sql", sql_skill)

    resolver = SkillResolver(registry)

    check(
        resolver.resolve(_task("browser")) is browser_skill,
        "S4: 'browser' task resolves to the browser skill",
    )
    check(
        resolver.resolve(_task("python")) is python_skill,
        "S4: 'python' task resolves to the python skill",
    )
    check(
        resolver.resolve(_task("sql")) is sql_skill,
        "S4: 'sql' task resolves to the sql skill",
    )


# ---------------------------------------------------------------------------
# S5 -- duplicate registry isolation
# ---------------------------------------------------------------------------
def scenario_duplicate_registry_isolation() -> None:
    registry1 = SkillRegistry()
    registry2 = SkillRegistry()
    skill1 = _Skill("registry1-browser")
    skill2 = _Skill("registry2-browser")
    registry1.register("browser", skill1)
    registry2.register("browser", skill2)

    resolver1 = SkillResolver(registry1)
    resolver2 = SkillResolver(registry2)

    check(
        resolver1.resolve(_task("browser")) is skill1,
        "S5: resolver1 resolves only from its own registry (skill1)",
    )
    check(
        resolver2.resolve(_task("browser")) is skill2,
        "S5: resolver2 resolves only from its own registry (skill2)",
    )
    check(
        resolver1.resolve(_task("browser")) is not skill2,
        "S5: resolver1 never resolves into registry2's skill",
    )


# ---------------------------------------------------------------------------
# S6 -- registry miss propagation
# ---------------------------------------------------------------------------
def scenario_registry_miss_propagation() -> None:
    registry = SkillRegistry()
    resolver = SkillResolver(registry)

    raised_registry_error = False
    raised_resolver_error = False
    try:
        resolver.resolve(_task("nonexistent"))
    except SkillRegistryError:
        raised_registry_error = True
    except SkillResolverError:
        raised_resolver_error = True

    check(
        raised_registry_error,
        "S6: resolve() on a name absent from the registry raises "
        "SkillRegistryError, unmodified from SkillRegistry.get()",
    )
    check(
        not raised_resolver_error,
        "S6: a registry miss is never wrapped into a SkillResolverError",
    )


# ---------------------------------------------------------------------------
# S7 -- invalid task
# ---------------------------------------------------------------------------
def scenario_invalid_task() -> None:
    registry = SkillRegistry()
    registry.register("browser", _Skill("browser"))
    resolver = SkillResolver(registry)

    for bad in ("browser", 123, object(), [], {}, ("browser",)):
        raised = False
        try:
            resolver.resolve(bad)  # type: ignore[arg-type]
        except SkillResolverError:
            raised = True
        check(
            raised,
            f"S7: resolve({bad!r}) raises SkillResolverError when "
            f"task is not a Task instance",
        )


# ---------------------------------------------------------------------------
# S8 -- None task
# ---------------------------------------------------------------------------
def scenario_none_task() -> None:
    registry = SkillRegistry()
    resolver = SkillResolver(registry)

    raised = False
    try:
        resolver.resolve(None)  # type: ignore[arg-type]
    except SkillResolverError:
        raised = True
    check(raised, "S8: resolve(None) raises SkillResolverError")


# ---------------------------------------------------------------------------
# S9 -- exact matching only
# ---------------------------------------------------------------------------
def scenario_exact_matching_only() -> None:
    registry = SkillRegistry()
    registry.register("browser", _Skill("browser"))
    resolver = SkillResolver(registry)

    for near_miss in ("Browser", "BROWSER", " browser", "browser ", "brows", "browserx"):
        raised_registry_error = False
        try:
            resolver.resolve(_task(near_miss))
        except SkillRegistryError:
            raised_registry_error = True
        check(
            raised_registry_error,
            f"S9: task.name={near_miss!r} does not fuzzy-match "
            f"'browser' -- it misses exactly like any other miss",
        )


# ---------------------------------------------------------------------------
# S10 -- metadata ignored
# ---------------------------------------------------------------------------
def scenario_metadata_ignored() -> None:
    registry = SkillRegistry()
    skill = _Skill("terminal")
    registry.register("terminal", skill)
    resolver = SkillResolver(registry)

    resolved_a = resolver.resolve(_task("terminal", metadata={"foo": "bar"}))
    resolved_b = resolver.resolve(_task("terminal", metadata={"totally": "different", "shape": 1}))

    check(
        resolved_a is skill and resolved_b is skill,
        "S10: differing task.metadata never changes which skill is resolved",
    )


# ---------------------------------------------------------------------------
# S11 -- description ignored
# ---------------------------------------------------------------------------
def scenario_description_ignored() -> None:
    registry = SkillRegistry()
    skill = _Skill("vision")
    registry.register("vision", skill)
    resolver = SkillResolver(registry)

    resolved_a = resolver.resolve(_task("vision", description="analyze an image"))
    resolved_b = resolver.resolve(_task("vision", description="completely unrelated text"))

    check(
        resolved_a is skill and resolved_b is skill,
        "S11: differing task.description never changes which skill is resolved",
    )


# ---------------------------------------------------------------------------
# S12 -- insertion order irrelevant
# ---------------------------------------------------------------------------
def scenario_insertion_order_irrelevant() -> None:
    registry_a = SkillRegistry()
    skill_x = _Skill("x")
    skill_y = _Skill("y")
    registry_a.register("x", skill_x)
    registry_a.register("y", skill_y)

    registry_b = SkillRegistry()
    registry_b.register("y", skill_y)
    registry_b.register("x", skill_x)

    resolver_a = SkillResolver(registry_a)
    resolver_b = SkillResolver(registry_b)

    check(
        resolver_a.resolve(_task("x")) is skill_x
        and resolver_b.resolve(_task("x")) is skill_x,
        "S12: registration order does not change what 'x' resolves to",
    )
    check(
        resolver_a.resolve(_task("y")) is skill_y
        and resolver_b.resolve(_task("y")) is skill_y,
        "S12: registration order does not change what 'y' resolves to",
    )


# ---------------------------------------------------------------------------
# S13 -- forbidden imports (AST-level, on the module's own source file)
# ---------------------------------------------------------------------------
def scenario_forbidden_imports() -> None:
    module_path = ROOT / "Orchestration" / "skill_resolver.py"
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))

    imported_names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported_names.append(module)
            for alias in node.names:
                imported_names.append(f"{module}.{alias.name}")

    allowed_prefixes = (
        "Core.exceptions",
        "Orchestration.task",
        "Orchestration.skill_registry",
        "typing",
        "__future__",
    )
    for name in imported_names:
        check(
            any(name == p or name.startswith(p + ".") for p in allowed_prefixes),
            f"S13: import {name!r} is one of the allowed imports "
            f"(Core.exceptions, Orchestration.task, "
            f"Orchestration.skill_registry, typing, __future__)",
        )

    forbidden_terms = (
        "Executor",
        "Workflow",
        "Planner",
        "Memory",
        "Reflection",
        "LearningLoop",
        "Scheduler",
        "Host",
        "EventBus",
        "Agent",
    )
    # The allowed imports themselves legitimately contain some of these
    # substrings (Core.exceptions.AgentError contains "Agent";
    # Orchestration.skill_registry / SkillRegistry contain nothing
    # forbidden, but excluded here defensively all the same) -- scan
    # only names outside the already-whitelisted allowed imports.
    allowlisted_exact = {
        "Core.exceptions.AgentError",
    }
    scan_names = [name for name in imported_names if name not in allowlisted_exact]
    for term in forbidden_terms:
        check(
            not any(term in name for name in scan_names),
            f"S13: no import statement in skill_resolver.py references {term!r}",
        )


# ---------------------------------------------------------------------------
# S14 -- forbidden execution surface
# ---------------------------------------------------------------------------
def scenario_forbidden_execution_surface() -> None:
    resolver = SkillResolver(SkillRegistry())
    public_methods = sorted(
        name
        for name in dir(resolver)
        if not name.startswith("_") and callable(getattr(resolver, name))
    )
    check(
        public_methods == ["resolve"],
        f"S14: SkillResolver exposes exactly resolve() as its only "
        f"public method -- got {public_methods}",
    )

    for forbidden in ("call", "execute", "run", "invoke", "dispatch"):
        check(
            not hasattr(resolver, forbidden),
            f"S14: SkillResolver exposes no {forbidden!r}-shaped method",
        )


# ---------------------------------------------------------------------------
# S15 -- repr stability
# ---------------------------------------------------------------------------
def scenario_repr_stability() -> None:
    error = SkillResolverError("something went wrong", details={"name": "x"})
    first = repr(error)
    second = repr(error)
    check(first == second, "S15: repr(SkillResolverError) is stable across calls")
    check(
        "SkillResolverError" in first,
        "S15: repr(SkillResolverError) mentions the class name",
    )


# ---------------------------------------------------------------------------
# S16 -- error hierarchy
# ---------------------------------------------------------------------------
def scenario_error_hierarchy() -> None:
    check(
        issubclass(SkillResolverError, AgentError),
        "S16: SkillResolverError subclasses Core.exceptions.AgentError",
    )
    check(
        issubclass(AgentError, Exception),
        "S16: Core.exceptions.AgentError subclasses Exception",
    )


# ---------------------------------------------------------------------------
# S17 -- no planner knowledge
# ---------------------------------------------------------------------------
def scenario_no_planner_knowledge() -> None:
    import Orchestration.skill_resolver as module

    for forbidden in ("GoalPlanner", "Planner"):
        check(
            forbidden not in vars(module),
            f"S17: Orchestration.skill_resolver's module namespace "
            f"does not contain a {forbidden!r} symbol",
        )


# ---------------------------------------------------------------------------
# S18 -- no workflow knowledge
# ---------------------------------------------------------------------------
def scenario_no_workflow_knowledge() -> None:
    import Orchestration.skill_resolver as module

    for forbidden in (
        "Workflow",
        "WorkflowEngine",
        "WorkflowRuntime",
        "WorkflowExecutionCoordinator",
    ):
        check(
            forbidden not in vars(module),
            f"S18: Orchestration.skill_resolver's module namespace "
            f"does not contain a {forbidden!r} symbol",
        )


# ---------------------------------------------------------------------------
# S19 -- no runtime knowledge
# ---------------------------------------------------------------------------
def scenario_no_runtime_knowledge() -> None:
    import Orchestration.skill_resolver as module

    check(
        "Executor" not in vars(module),
        "S19: Orchestration.skill_resolver's module namespace does "
        "not contain an 'Executor' symbol",
    )

    resolver = SkillResolver(SkillRegistry())
    check(
        not hasattr(resolver, "executor") and not hasattr(resolver, "_executor"),
        "S19: a SkillResolver instance holds no executor-shaped attribute",
    )


# ---------------------------------------------------------------------------
# S20 -- no scheduler knowledge
# ---------------------------------------------------------------------------
def scenario_no_scheduler_knowledge() -> None:
    import Orchestration.skill_resolver as module

    for forbidden in ("AutonomousScheduler", "Scheduler", "AutonomousHost"):
        check(
            forbidden not in vars(module),
            f"S20: Orchestration.skill_resolver's module namespace "
            f"does not contain a {forbidden!r} symbol",
        )


# ---------------------------------------------------------------------------
# S21 -- no EventBus knowledge
# ---------------------------------------------------------------------------
def scenario_no_eventbus_knowledge() -> None:
    import Orchestration.skill_resolver as module

    for forbidden in ("EventBus", "Event"):
        check(
            forbidden not in vars(module),
            f"S21: Orchestration.skill_resolver's module namespace "
            f"does not contain a {forbidden!r} symbol",
        )

    resolver = SkillResolver(SkillRegistry())
    check(
        not hasattr(resolver, "publish")
        and not hasattr(resolver, "subscribe")
        and not hasattr(resolver, "attach"),
        "S21: a SkillResolver instance exposes no publish/subscribe/"
        "attach-shaped method",
    )


SCENARIOS = [
    scenario_constructor_validation,
    scenario_resolve_success,
    scenario_resolve_returns_identical_object,
    scenario_multiple_skills,
    scenario_duplicate_registry_isolation,
    scenario_registry_miss_propagation,
    scenario_invalid_task,
    scenario_none_task,
    scenario_exact_matching_only,
    scenario_metadata_ignored,
    scenario_description_ignored,
    scenario_insertion_order_irrelevant,
    scenario_forbidden_imports,
    scenario_forbidden_execution_surface,
    scenario_repr_stability,
    scenario_error_hierarchy,
    scenario_no_planner_knowledge,
    scenario_no_workflow_knowledge,
    scenario_no_runtime_knowledge,
    scenario_no_scheduler_knowledge,
    scenario_no_eventbus_knowledge,
]


def main() -> int:
    for scenario in SCENARIOS:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001 -- a scenario crashing is a FAIL, not a suite abort
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__}: raised unexpectedly")
            print(f"  FAIL - {scenario.__name__}: raised unexpectedly")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(
        f"PHASE 5 SPRINT 44 SKILL RESOLVER RESULTS: {_PASS} PASS / "
        f"{_FAIL} FAIL (total {_PASS + _FAIL})"
    )
    print("=" * 60)

    if _FAIL:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())