"""
Phase 5 Sprint 43 proof suite -- ``SkillRegistry`` (Capability Catalog).

Scope: dedicated regression suite for the Sprint 43 addition only --
``Orchestration.skill_registry.SkillRegistry``, a pure in-memory
catalog mapping a name (``str``) to an opaque skill object, plus its
own ``SkillRegistryError`` exception type. This is a catalog only: no
execution, no routing, no selection, no manager/executor/resolver
built on top of it, no singleton, no global registry instance, and no
wiring into Executor, WorkflowRuntime, WorkflowEngine,
WorkflowExecutionCoordinator, GoalPlanner, Memory, LearningLoop,
Reflection, AutonomousScheduler, AutonomousHost, or AutonomousAgent.

SkillRegistry never imports, constructs, or references Executor,
WorkflowEngine, WorkflowRuntime, WorkflowSession, WorkflowManager,
GoalPlanner, Memory, Reflection, LearningLoop, AutonomousScheduler,
AutonomousHost, or AutonomousAgent (proven both by module-namespace
inspection and by AST-level import inspection of the module's own
source file). ``Orchestration.skill_registry`` imports only
``Core.exceptions.AgentError`` and the stdlib ``typing`` module.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L4x / Sprint 1x-42 proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    R1  -- empty registry: a fresh SkillRegistry() starts with
           list() == () and has(name) is False for any name.
    R2  -- register: register(name, skill) succeeds; has(name) becomes
           True and get(name) returns the exact object registered.
    R3  -- duplicate register: registering the same name twice raises
           SkillRegistryError; the original skill is left untouched.
    R4  -- unregister: unregister(name) removes a registered skill --
           has(name) becomes False and it disappears from list().
    R5  -- unregister missing: unregister(name) on a name never
           registered (or already removed) raises SkillRegistryError.
    R6  -- get: get(name) returns the exact same object (identity),
           never a copy or wrapper.
    R7  -- get missing: get(name) on an unregistered name raises
           SkillRegistryError.
    R8  -- has: has(name) returns True/False correctly and never
           raises, before and after register/unregister.
    R9  -- list snapshot immutable: list() returns a real tuple; item
           assignment on it raises TypeError.
    R10 -- list independent copy: mutating the registry after calling
           list() never changes the already-returned tuple, and two
           separate list() calls return independent tuple objects.
    R11 -- insertion order: list() preserves the order names were
           first registered, including after an unregister/re-register
           cycle.
    R12 -- invalid name: register(name=<bad>, skill=...) raises
           SkillRegistryError for None, "", whitespace-only, and
           non-str values.
    R13 -- invalid skill: register(name="x", skill=None) raises
           SkillRegistryError.
    R14 -- independent registries: two SkillRegistry instances never
           share state -- registering into one never affects the
           other.
    R15 -- repr stability: repr() of a SkillRegistryError is stable
           (same string) across repeated calls and mentions the class
           name.
    R16 -- error hierarchy: SkillRegistryError subclasses
           Core.exceptions.AgentError, which subclasses Exception.
    R17 -- forbidden imports: Orchestration.skill_registry's own
           source file imports only Core.exceptions and typing (AST-
           level import inspection) -- no Executor/WorkflowEngine/
           WorkflowRuntime/WorkflowSession/WorkflowManager/Planner/
           Memory/Reflection/LearningLoop/Scheduler/Host/Agent import
           anywhere in the file.
    R18 -- forbidden execution surface: a SkillRegistry instance
           exposes no run/execute/call/dispatch/invoke-shaped method
           -- register/unregister/get/has/list are its only five
           public methods.
    R19 -- no runtime knowledge: Orchestration.skill_registry's module
           namespace contains no WorkflowRuntime/WorkflowEngine/
           WorkflowExecutionCoordinator/Executor symbol.
    R20 -- no planner knowledge: Orchestration.skill_registry's module
           namespace contains no GoalPlanner/Planner symbol.
    R21 -- no scheduler knowledge: Orchestration.skill_registry's
           module namespace contains no AutonomousScheduler/Scheduler
           symbol.
    R22 -- no workflow knowledge: Orchestration.skill_registry's
           module namespace contains no Workflow/WorkflowManager/
           WorkflowSession symbol.
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
    the registry does not care about its shape at all."""

    def __init__(self, label: str) -> None:
        self.label = label

    def __repr__(self) -> str:
        return f"_Skill({self.label!r})"


# ---------------------------------------------------------------------------
# R1 -- empty registry
# ---------------------------------------------------------------------------
def scenario_empty_registry() -> None:
    registry = SkillRegistry()
    check(registry.list() == (), "R1: a fresh SkillRegistry() has list() == ()")
    check(
        registry.has("anything") is False,
        "R1: a fresh SkillRegistry() has has('anything') is False",
    )


# ---------------------------------------------------------------------------
# R2 -- register
# ---------------------------------------------------------------------------
def scenario_register() -> None:
    registry = SkillRegistry()
    skill = _Skill("browser")
    registry.register("browser", skill)

    check(registry.has("browser") is True, "R2: has('browser') is True after register")
    check(
        registry.get("browser") is skill,
        "R2: get('browser') returns the exact registered object",
    )
    check(registry.list() == ("browser",), "R2: list() contains the registered name")


# ---------------------------------------------------------------------------
# R3 -- duplicate register
# ---------------------------------------------------------------------------
def scenario_duplicate_register() -> None:
    registry = SkillRegistry()
    first = _Skill("first")
    second = _Skill("second")
    registry.register("dup", first)

    raised = False
    try:
        registry.register("dup", second)
    except SkillRegistryError:
        raised = True

    check(raised, "R3: registering a duplicate name raises SkillRegistryError")
    check(
        registry.get("dup") is first,
        "R3: the original registration is untouched after a rejected duplicate",
    )


# ---------------------------------------------------------------------------
# R4 -- unregister
# ---------------------------------------------------------------------------
def scenario_unregister() -> None:
    registry = SkillRegistry()
    registry.register("filesystem", _Skill("fs"))
    registry.unregister("filesystem")

    check(
        registry.has("filesystem") is False,
        "R4: has('filesystem') is False after unregister",
    )
    check(
        "filesystem" not in registry.list(),
        "R4: 'filesystem' no longer appears in list() after unregister",
    )


# ---------------------------------------------------------------------------
# R5 -- unregister missing
# ---------------------------------------------------------------------------
def scenario_unregister_missing() -> None:
    registry = SkillRegistry()

    raised = False
    try:
        registry.unregister("never-registered")
    except SkillRegistryError:
        raised = True
    check(
        raised,
        "R5: unregister() on a never-registered name raises SkillRegistryError",
    )

    registry.register("terminal", _Skill("term"))
    registry.unregister("terminal")
    raised_again = False
    try:
        registry.unregister("terminal")
    except SkillRegistryError:
        raised_again = True
    check(
        raised_again,
        "R5: unregister() on an already-removed name raises SkillRegistryError",
    )


# ---------------------------------------------------------------------------
# R6 -- get
# ---------------------------------------------------------------------------
def scenario_get() -> None:
    registry = SkillRegistry()
    skill = _Skill("sql")
    registry.register("sql", skill)
    check(registry.get("sql") is skill, "R6: get() returns the exact same object (identity)")
    check(
        registry.get("sql") is registry.get("sql"),
        "R6: repeated get() calls return the same object",
    )


# ---------------------------------------------------------------------------
# R7 -- get missing
# ---------------------------------------------------------------------------
def scenario_get_missing() -> None:
    registry = SkillRegistry()
    raised = False
    try:
        registry.get("nonexistent")
    except SkillRegistryError:
        raised = True
    check(raised, "R7: get() on an unregistered name raises SkillRegistryError")


# ---------------------------------------------------------------------------
# R8 -- has
# ---------------------------------------------------------------------------
def scenario_has() -> None:
    registry = SkillRegistry()
    check(registry.has("search") is False, "R8: has() is False before registration")

    registry.register("search", _Skill("search"))
    check(registry.has("search") is True, "R8: has() is True after registration")

    registry.unregister("search")
    check(registry.has("search") is False, "R8: has() is False again after unregister")

    raised = False
    try:
        registry.has("anything")
    except SkillRegistryError:
        raised = True
    check(not raised, "R8: has() never raises SkillRegistryError")


# ---------------------------------------------------------------------------
# R9 -- list snapshot immutable
# ---------------------------------------------------------------------------
def scenario_list_snapshot_immutable() -> None:
    registry = SkillRegistry()
    registry.register("vision", _Skill("vision"))
    snapshot = registry.list()

    check(isinstance(snapshot, tuple), "R9: list() returns a real tuple")

    raised = False
    try:
        snapshot[0] = "mutated"  # type: ignore[index]
    except TypeError:
        raised = True
    check(raised, "R9: item assignment on the returned tuple raises TypeError")


# ---------------------------------------------------------------------------
# R10 -- list independent copy
# ---------------------------------------------------------------------------
def scenario_list_independent_copy() -> None:
    registry = SkillRegistry()
    registry.register("python", _Skill("python"))
    snapshot_before = registry.list()

    registry.register("terminal2", _Skill("terminal2"))
    snapshot_after = registry.list()

    check(
        snapshot_before == ("python",),
        "R10: a tuple obtained before a later register() is unaffected by it",
    )
    check(
        snapshot_after == ("python", "terminal2"),
        "R10: a fresh list() call reflects the newly registered name",
    )
    check(
        snapshot_before is not snapshot_after,
        "R10: two list() calls return independent tuple objects",
    )


# ---------------------------------------------------------------------------
# R11 -- insertion order
# ---------------------------------------------------------------------------
def scenario_insertion_order() -> None:
    registry = SkillRegistry()
    registry.register("a", _Skill("a"))
    registry.register("b", _Skill("b"))
    registry.register("c", _Skill("c"))

    check(
        registry.list() == ("a", "b", "c"),
        "R11: list() preserves first-registration order",
    )

    registry.unregister("b")
    registry.register("d", _Skill("d"))
    check(
        registry.list() == ("a", "c", "d"),
        "R11: order after unregister/re-register reflects remaining "
        "names in their original order, plus the newly registered "
        "name appended at the end",
    )


# ---------------------------------------------------------------------------
# R12 -- invalid name
# ---------------------------------------------------------------------------
def scenario_invalid_name() -> None:
    registry = SkillRegistry()
    for bad_name in (None, "", "   ", 123, [], {}):
        raised = False
        try:
            registry.register(bad_name, _Skill("x"))  # type: ignore[arg-type]
        except SkillRegistryError:
            raised = True
        check(
            raised,
            f"R12: register(name={bad_name!r}, ...) raises SkillRegistryError",
        )


# ---------------------------------------------------------------------------
# R13 -- invalid skill
# ---------------------------------------------------------------------------
def scenario_invalid_skill() -> None:
    registry = SkillRegistry()
    raised = False
    try:
        registry.register("x", None)
    except SkillRegistryError:
        raised = True
    check(raised, "R13: register('x', None) raises SkillRegistryError")
    check(
        registry.has("x") is False,
        "R13: a rejected registration leaves no trace under 'x'",
    )


# ---------------------------------------------------------------------------
# R14 -- independent registries
# ---------------------------------------------------------------------------
def scenario_independent_registries() -> None:
    registry1 = SkillRegistry()
    registry2 = SkillRegistry()

    registry1.register("only-in-1", _Skill("one"))

    check(
        registry1.has("only-in-1") is True and registry2.has("only-in-1") is False,
        "R14: registering into one SkillRegistry instance never "
        "affects another",
    )
    check(
        registry2.list() == (),
        "R14: a second, independently constructed SkillRegistry starts empty",
    )


# ---------------------------------------------------------------------------
# R15 -- repr stability
# ---------------------------------------------------------------------------
def scenario_repr_stability() -> None:
    error = SkillRegistryError("something went wrong", details={"name": "x"})
    first = repr(error)
    second = repr(error)
    check(first == second, "R15: repr(SkillRegistryError) is stable across calls")
    check(
        "SkillRegistryError" in first,
        "R15: repr(SkillRegistryError) mentions the class name",
    )


# ---------------------------------------------------------------------------
# R16 -- error hierarchy
# ---------------------------------------------------------------------------
def scenario_error_hierarchy() -> None:
    check(
        issubclass(SkillRegistryError, AgentError),
        "R16: SkillRegistryError subclasses Core.exceptions.AgentError",
    )
    check(
        issubclass(AgentError, Exception),
        "R16: Core.exceptions.AgentError subclasses Exception",
    )


# ---------------------------------------------------------------------------
# R17 -- forbidden imports (AST-level, on the module's own source file)
# ---------------------------------------------------------------------------
def scenario_forbidden_imports() -> None:
    module_path = ROOT / "Orchestration" / "skill_registry.py"
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

    allowed_prefixes = ("Core.exceptions", "typing", "__future__")
    for name in imported_names:
        check(
            any(name == p or name.startswith(p + ".") for p in allowed_prefixes),
            f"R17: import {name!r} is one of the allowed imports "
            f"(Core.exceptions, typing, __future__)",
        )

    forbidden_terms = (
        "Executor",
        "WorkflowEngine",
        "WorkflowRuntime",
        "WorkflowSession",
        "WorkflowManager",
        "Planner",
        "Memory",
        "Reflection",
        "LearningLoop",
        "Scheduler",
        "Host",
        "Agent",
    )
    # Core.exceptions.AgentError is the one allowed import and legitimately
    # contains the substring "Agent" -- exclude only that exact, already
    # whitelisted name from the scan below, so the "Agent" check is really
    # testing for the Agents-framework classes (BaseAgent, AutonomousAgent,
    # etc.), not for the unrelated AgentError exception type.
    scan_names = [
        name for name in imported_names if name != "Core.exceptions.AgentError"
    ]
    for term in forbidden_terms:
        check(
            not any(term in name for name in scan_names),
            f"R17: no import statement in skill_registry.py references {term!r}",
        )


# ---------------------------------------------------------------------------
# R18 -- forbidden execution surface
# ---------------------------------------------------------------------------
def scenario_forbidden_execution_surface() -> None:
    registry = SkillRegistry()
    public_methods = sorted(
        name
        for name in dir(registry)
        if not name.startswith("_") and callable(getattr(registry, name))
    )
    check(
        public_methods == ["get", "has", "list", "register", "unregister"],
        f"R18: SkillRegistry exposes exactly register/unregister/get/"
        f"has/list as public methods -- got {public_methods}",
    )

    for forbidden in ("run", "execute", "call", "dispatch", "invoke"):
        check(
            not hasattr(registry, forbidden),
            f"R18: SkillRegistry exposes no {forbidden!r}-shaped method",
        )


# ---------------------------------------------------------------------------
# R19 -- no runtime knowledge
# ---------------------------------------------------------------------------
def scenario_no_runtime_knowledge() -> None:
    import Orchestration.skill_registry as module

    for forbidden in (
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "Executor",
    ):
        check(
            forbidden not in vars(module),
            f"R19: Orchestration.skill_registry's module namespace "
            f"does not contain a {forbidden!r} symbol",
        )


# ---------------------------------------------------------------------------
# R20 -- no planner knowledge
# ---------------------------------------------------------------------------
def scenario_no_planner_knowledge() -> None:
    import Orchestration.skill_registry as module

    for forbidden in ("GoalPlanner", "Planner"):
        check(
            forbidden not in vars(module),
            f"R20: Orchestration.skill_registry's module namespace "
            f"does not contain a {forbidden!r} symbol",
        )


# ---------------------------------------------------------------------------
# R21 -- no scheduler knowledge
# ---------------------------------------------------------------------------
def scenario_no_scheduler_knowledge() -> None:
    import Orchestration.skill_registry as module

    for forbidden in ("AutonomousScheduler", "Scheduler", "AutonomousHost"):
        check(
            forbidden not in vars(module),
            f"R21: Orchestration.skill_registry's module namespace "
            f"does not contain a {forbidden!r} symbol",
        )


# ---------------------------------------------------------------------------
# R22 -- no workflow knowledge
# ---------------------------------------------------------------------------
def scenario_no_workflow_knowledge() -> None:
    import Orchestration.skill_registry as module

    for forbidden in ("Workflow", "WorkflowManager", "WorkflowSession"):
        check(
            forbidden not in vars(module),
            f"R22: Orchestration.skill_registry's module namespace "
            f"does not contain a {forbidden!r} symbol",
        )


SCENARIOS = [
    scenario_empty_registry,
    scenario_register,
    scenario_duplicate_register,
    scenario_unregister,
    scenario_unregister_missing,
    scenario_get,
    scenario_get_missing,
    scenario_has,
    scenario_list_snapshot_immutable,
    scenario_list_independent_copy,
    scenario_insertion_order,
    scenario_invalid_name,
    scenario_invalid_skill,
    scenario_independent_registries,
    scenario_repr_stability,
    scenario_error_hierarchy,
    scenario_forbidden_imports,
    scenario_forbidden_execution_surface,
    scenario_no_runtime_knowledge,
    scenario_no_planner_knowledge,
    scenario_no_scheduler_knowledge,
    scenario_no_workflow_knowledge,
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
        f"PHASE 5 SPRINT 43 SKILL REGISTRY RESULTS: {_PASS} PASS / "
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