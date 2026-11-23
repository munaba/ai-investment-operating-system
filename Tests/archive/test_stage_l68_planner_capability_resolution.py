"""
Phase 5 Sprint 68 proof suite -- ``GoalPlanner`` gains the capability
to resolve a ``Goal`` into candidate skill names via an injected
``CapabilityManager``.

Scope: dedicated regression suite for the Sprint 68 addition only --
``Orchestration.planner.GoalPlanner``'s new optional
``capability_manager`` constructor argument, plus its single new
public method, ``resolve_capabilities(goal)``. This is discovery
only: no Skill is ever resolved, no Tool is ever touched, and nothing
is ever executed. ``build_plan``/``execute_plan``/
``translate_metadata``/``accumulate_context``/``build_workflow``/
``recall`` are all unchanged by this sprint -- this suite does not
re-verify their own internal behavior beyond confirming Sprint 68
introduces no regression to them.

``GoalPlanner`` never resolves Skills, never accesses
``SkillRegistry``, ``SkillResolver``, ``ToolRegistry``,
``ToolResolver``, or ``ToolManager``, never executes Skills or Tools,
never calls ``Executor``, never creates ``Task``s, never modifies
``Workflow``, never publishes events, and never uses ``Memory``,
``Reflection``, ``LearningLoop``, or ``Runtime`` from within
``resolve_capabilities`` (proven both by direct behavioral tests and
by AST-level import inspection of the module's own source file).
``Orchestration.planner`` adds exactly one new import for this
sprint: ``Orchestration.capability_manager.CapabilityManager``.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x/L6x proof suites (mirroring
``Tests.test_stage_l67_capability_manager_resolver`` in particular): a
global pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage (target 25-30):
    T1  -- constructor: capability_manager omitted (default None)
           constructs successfully; resolve_capabilities() returns ().
    T2  -- constructor: capability_manager=None explicitly constructs
           successfully; resolve_capabilities() returns ().
    T3  -- constructor: a valid CapabilityManager instance constructs
           successfully.
    T4  -- constructor: every invalid, non-CapabilityManager value
           (not None) raises GoalPlannerError.
    T5  -- identity preservation: the exact CapabilityManager instance
           passed in is the one delegated to -- resolving through the
           planner reaches that exact object, not a copy.
    T6  -- resolve_capabilities: goal with no metadata at all (empty
           dict) returns ().
    T7  -- resolve_capabilities: goal.metadata present but without a
           "capability" key returns ().
    T8  -- resolve_capabilities: goal.metadata with a "capability" key
           delegates exactly once to CapabilityManager.resolve with
           that exact value.
    T9  -- resolve_capabilities: returns exactly what
           CapabilityManager.resolve returns (identity of the tuple).
    T10 -- resolve_capabilities: unknown/invalid capability value
           propagates the CapabilityManager's exception unchanged
           (not wrapped as GoalPlannerError).
    T11 -- resolve_capabilities: capability_manager is None (never
           supplied) always returns () regardless of goal.metadata
           contents -- no AttributeError, no exception.
    T12 -- no business logic: no normalization/lowercasing/
           stripping/trimming is ever applied to the capability value
           before delegation.
    T13 -- no caching: two calls to resolve_capabilities with the same
           goal each delegate to CapabilityManager.resolve again (no
           memoized/cached result masking a registry change).
    T14 -- public API exactness: exactly one new public method exists
           on GoalPlanner beyond the Sprint 42/34/... surface --
           resolve_capabilities.
    T15 -- forbidden behavior: resolve_capabilities never touches
           self._service_skills or self._memory.
    T16 -- no Skill/Tool resolution: GoalPlanner's module namespace
           contains no SkillRegistry/SkillResolver/ToolRegistry/
           ToolResolver/ToolManager/Executor symbol.
    T17 -- AST import verification: Orchestration.planner's own
           source file's only *new* import for this sprint is
           Orchestration.capability_manager.CapabilityManager -- no
           other forbidden import was introduced.
    T18 -- namespace verification: Orchestration.planner's module
           namespace contains no CapabilityRegistry/CapabilityResolver/
           CapabilitySkillRegistry/Capability symbol (only
           CapabilityManager, imported for typing/isinstance use).
    T19 -- multi-instance independence: two GoalPlanner instances
           built over two independent CapabilityManager collaborators
           never cross-resolve into each other's capabilities.
    T20 -- no hidden state: a GoalPlanner instance's new attribute is
           exactly '_capability_manager' -- no cache, no registry, no
           resolver reference of its own.
    T21 -- pre-existing surface unaffected: build_plan/execute_plan/
           translate_metadata/accumulate_context/build_workflow/recall
           behave identically whether or not capability_manager is
           attached.
    T22 -- exception convention: GoalPlannerError remains a subclass
           of Core.exceptions.AgentError.
    T23 -- constructor: capability_manager rejects a bare
           CapabilityRegistry/CapabilityResolver (not a
           CapabilityManager) with GoalPlannerError.
    T24 -- resolve_capabilities: a goal.metadata dict with
           "capability" mapped to a non-str value is still passed
           through verbatim (no type-checking performed by Planner
           itself -- CapabilityManager/CapabilityResolver's own
           validation is what raises, propagated unchanged).
    T25 -- resolve_capabilities returns a tuple type (or delegates to
           whatever type CapabilityManager.resolve returns) without
           ever coercing list/other iterables itself.
    T26 -- combination: capability_manager alongside memory (both
           supplied) -- resolve_capabilities and recall each work off
           their own collaborator independently.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.capability_manager import CapabilityManager, CapabilityManagerError
from Orchestration.capability_registry import CapabilityRegistry
from Orchestration.capability_resolver import CapabilityResolver, CapabilityResolverError
from Orchestration.capability_skill_registry import (
    CapabilitySkillRegistry,
    CapabilitySkillRegistryError,
)
from Orchestration.planner import Goal, GoalPlanner, GoalPlannerError

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


def _make_manager() -> CapabilityManager:
    """Return a fresh, independent CapabilityManager wired over its
    own fresh CapabilityRegistry/CapabilitySkillRegistry/
    CapabilityResolver stack."""
    registry = CapabilityRegistry()
    skill_registry = CapabilitySkillRegistry()
    resolver = CapabilityResolver(skill_registry)
    manager = CapabilityManager(registry, resolver)
    return manager, skill_registry


# ---------------------------------------------------------------------------
# T1 -- constructor: capability_manager omitted
# ---------------------------------------------------------------------------
def scenario_constructor_omitted() -> None:
    planner = GoalPlanner(service_skills={})
    check(
        isinstance(planner, GoalPlanner),
        "T1: GoalPlanner(service_skills={}) with capability_manager omitted constructs successfully",
    )
    check(
        planner.resolve_capabilities(Goal(metadata={"capability": "x"})) == (),
        "T1: resolve_capabilities() returns () when capability_manager was never supplied",
    )


# ---------------------------------------------------------------------------
# T2 -- constructor: capability_manager=None explicitly
# ---------------------------------------------------------------------------
def scenario_constructor_explicit_none() -> None:
    planner = GoalPlanner(service_skills={}, capability_manager=None)
    check(
        isinstance(planner, GoalPlanner),
        "T2: GoalPlanner(service_skills={}, capability_manager=None) constructs successfully",
    )
    check(
        planner.resolve_capabilities(Goal(metadata={"capability": "x"})) == (),
        "T2: resolve_capabilities() returns () when capability_manager=None explicitly",
    )


# ---------------------------------------------------------------------------
# T3 -- constructor: valid CapabilityManager
# ---------------------------------------------------------------------------
def scenario_constructor_valid_manager() -> None:
    manager, _skill_registry = _make_manager()
    planner = GoalPlanner(service_skills={}, capability_manager=manager)
    check(
        isinstance(planner, GoalPlanner),
        "T3: GoalPlanner(service_skills={}, capability_manager=<CapabilityManager>) constructs successfully",
    )


# ---------------------------------------------------------------------------
# T4 -- constructor: invalid capability_manager values
# ---------------------------------------------------------------------------
def scenario_constructor_invalid_manager() -> None:
    bad_values = ("not-a-manager", 123, object(), {}, [], True)

    for value in bad_values:
        raised = False
        try:
            GoalPlanner(service_skills={}, capability_manager=value)  # type: ignore[arg-type]
        except GoalPlannerError:
            raised = True
        check(
            raised,
            f"T4: GoalPlanner(capability_manager={value!r}) raises GoalPlannerError",
        )


# ---------------------------------------------------------------------------
# T5 -- identity preservation
# ---------------------------------------------------------------------------
def scenario_identity_preservation() -> None:
    manager, skill_registry = _make_manager()
    skill_registry.register("cap.identity", ("skill_a", "skill_b"))

    planner = GoalPlanner(service_skills={}, capability_manager=manager)
    result = planner.resolve_capabilities(Goal(metadata={"capability": "cap.identity"}))
    check(
        result == manager.resolve("cap.identity"),
        "T5: resolve_capabilities() reaches the exact injected CapabilityManager instance",
    )


# ---------------------------------------------------------------------------
# T6 -- goal with empty metadata
# ---------------------------------------------------------------------------
def scenario_goal_empty_metadata() -> None:
    manager, _skill_registry = _make_manager()
    planner = GoalPlanner(service_skills={}, capability_manager=manager)
    result = planner.resolve_capabilities(Goal(metadata={}))
    check(result == (), "T6: resolve_capabilities() returns () for a Goal with empty metadata")


# ---------------------------------------------------------------------------
# T7 -- goal.metadata present but no "capability" key
# ---------------------------------------------------------------------------
def scenario_goal_missing_capability_key() -> None:
    manager, _skill_registry = _make_manager()
    planner = GoalPlanner(service_skills={}, capability_manager=manager)
    result = planner.resolve_capabilities(Goal(metadata={"ticker": "BBCA"}))
    check(
        result == (),
        "T7: resolve_capabilities() returns () when goal.metadata has no 'capability' key",
    )


# ---------------------------------------------------------------------------
# T8 -- delegates exactly once with the exact value
# ---------------------------------------------------------------------------
def scenario_delegates_exactly_once() -> None:
    manager, skill_registry = _make_manager()
    skill_registry.register("cap.count", ("skill_x",))

    call_count = {"n": 0}
    original_resolve = manager.resolve

    def counting_resolve(capability_name):
        call_count["n"] += 1
        return original_resolve(capability_name)

    manager.resolve = counting_resolve  # type: ignore[assignment]

    planner = GoalPlanner(service_skills={}, capability_manager=manager)
    planner.resolve_capabilities(Goal(metadata={"capability": "cap.count"}))

    check(call_count["n"] == 1, "T8: resolve_capabilities() delegates to CapabilityManager.resolve exactly once")


# ---------------------------------------------------------------------------
# T9 -- returns exactly what CapabilityManager.resolve returns
# ---------------------------------------------------------------------------
def scenario_returns_exact_tuple() -> None:
    manager, skill_registry = _make_manager()
    skill_registry.register("cap.exact", ("skill_1", "skill_2", "skill_3"))

    planner = GoalPlanner(service_skills={}, capability_manager=manager)
    result = planner.resolve_capabilities(Goal(metadata={"capability": "cap.exact"}))
    expected = manager.resolve("cap.exact")
    check(result == expected, "T9: resolve_capabilities() returns exactly what CapabilityManager.resolve returns")
    check(isinstance(result, tuple), "T9: resolve_capabilities() return value is a tuple")


# ---------------------------------------------------------------------------
# T10 -- unknown capability propagates unchanged
# ---------------------------------------------------------------------------
def scenario_unknown_capability_propagates() -> None:
    manager, _skill_registry = _make_manager()
    planner = GoalPlanner(service_skills={}, capability_manager=manager)

    raised_type = None
    try:
        planner.resolve_capabilities(Goal(metadata={"capability": "cap.nonexistent"}))
    except CapabilitySkillRegistryError:
        raised_type = CapabilitySkillRegistryError
    except GoalPlannerError:
        raised_type = GoalPlannerError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is CapabilitySkillRegistryError,
        f"T10: unknown capability propagates CapabilitySkillRegistryError unchanged (got {raised_type})",
    )


def scenario_invalid_capability_value_propagates() -> None:
    manager, _skill_registry = _make_manager()
    planner = GoalPlanner(service_skills={}, capability_manager=manager)

    raised_type = None
    try:
        planner.resolve_capabilities(Goal(metadata={"capability": ""}))
    except CapabilityResolverError:
        raised_type = CapabilityResolverError
    except GoalPlannerError:
        raised_type = GoalPlannerError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is CapabilityResolverError,
        f"T10b: an empty-string capability value propagates CapabilityResolverError unchanged (got {raised_type})",
    )


# ---------------------------------------------------------------------------
# T11 -- capability_manager None never raises regardless of metadata
# ---------------------------------------------------------------------------
def scenario_none_manager_never_raises() -> None:
    planner = GoalPlanner(service_skills={})
    goals = [
        Goal(metadata={}),
        Goal(metadata={"capability": "anything"}),
        Goal(metadata={"capability": ""}),
        Goal(metadata={"capability": None}),
        Goal(metadata={"capability": 123}),
    ]
    all_ok = True
    for goal in goals:
        try:
            result = planner.resolve_capabilities(goal)
            if result != ():
                all_ok = False
        except Exception:
            all_ok = False
    check(all_ok, "T11: resolve_capabilities() always returns () and never raises when capability_manager is None")


# ---------------------------------------------------------------------------
# T12 -- no normalization
# ---------------------------------------------------------------------------
def scenario_no_normalization() -> None:
    manager, skill_registry = _make_manager()
    skill_registry.register("Cap.Mixed_Case ", ("skill_z",))

    planner = GoalPlanner(service_skills={}, capability_manager=manager)

    # Exact registered key works.
    result = planner.resolve_capabilities(Goal(metadata={"capability": "Cap.Mixed_Case "}))
    check(result == ("skill_z",), "T12: exact-case, exact-whitespace capability value resolves correctly")

    # A lowercased/stripped variant should NOT resolve (proves no normalization).
    raised = False
    try:
        planner.resolve_capabilities(Goal(metadata={"capability": "cap.mixed_case"}))
    except CapabilitySkillRegistryError:
        raised = True
    check(
        raised,
        "T12: a lowercased/stripped variant of the capability value does not silently resolve (no normalization performed)",
    )


# ---------------------------------------------------------------------------
# T13 -- no caching
# ---------------------------------------------------------------------------
def scenario_no_caching() -> None:
    manager, skill_registry = _make_manager()
    skill_registry.register("cap.mutable", ("skill_v1",))

    planner = GoalPlanner(service_skills={}, capability_manager=manager)
    first = planner.resolve_capabilities(Goal(metadata={"capability": "cap.mutable"}))

    skill_registry.unregister("cap.mutable")
    skill_registry.register("cap.mutable", ("skill_v2", "skill_v3"))

    second = planner.resolve_capabilities(Goal(metadata={"capability": "cap.mutable"}))

    check(first == ("skill_v1",), "T13: first resolve_capabilities() call reflects the initial registration")
    check(
        second == ("skill_v2", "skill_v3"),
        "T13: second resolve_capabilities() call reflects the updated registration -- no cached/stale result",
    )


# ---------------------------------------------------------------------------
# T14 -- public API exactness
# ---------------------------------------------------------------------------
def scenario_public_api_exactness() -> None:
    expected_public_methods = {
        "recall",
        "build_plan",
        "execute_plan",
        "translate_metadata",
        "accumulate_context",
        "build_workflow",
        "resolve_capabilities",
    }
    actual_public_methods = {
        name
        for name in dir(GoalPlanner)
        if not name.startswith("_") and callable(getattr(GoalPlanner, name))
    }
    check(
        actual_public_methods == expected_public_methods,
        f"T14: GoalPlanner's public methods are exactly {sorted(expected_public_methods)} (got {sorted(actual_public_methods)})",
    )


# ---------------------------------------------------------------------------
# T15 -- resolve_capabilities never touches service_skills/memory
# ---------------------------------------------------------------------------
def scenario_no_touch_other_collaborators() -> None:
    manager, skill_registry = _make_manager()
    skill_registry.register("cap.isolated", ("skill_only",))

    class ExplodingDict(dict):
        def __getitem__(self, key):
            raise AssertionError("service_skills was touched by resolve_capabilities")

        def get(self, *args, **kwargs):
            raise AssertionError("service_skills was touched by resolve_capabilities")

    class ExplodingMemory:
        def list(self):
            raise AssertionError("memory was touched by resolve_capabilities")

    planner = GoalPlanner(
        service_skills=ExplodingDict(),
        memory=ExplodingMemory(),
        capability_manager=manager,
    )

    result = None
    exploded = False
    try:
        result = planner.resolve_capabilities(Goal(metadata={"capability": "cap.isolated"}))
    except AssertionError:
        exploded = True

    check(not exploded, "T15: resolve_capabilities() never touches service_skills or memory collaborators")
    check(result == ("skill_only",), "T15: resolve_capabilities() still resolves correctly despite exploding collaborators")


# ---------------------------------------------------------------------------
# T16 -- no Skill/Tool resolution symbols in module namespace
# ---------------------------------------------------------------------------
def scenario_no_forbidden_namespace_symbols() -> None:
    import Orchestration.planner as planner_module

    forbidden = [
        "SkillRegistry",
        "SkillResolver",
        "ToolRegistry",
        "ToolResolver",
        "ToolManager",
        "Executor",
        "CapabilityRegistry",
        "CapabilityResolver",
        "CapabilitySkillRegistry",
    ]
    for name in forbidden:
        check(
            not hasattr(planner_module, name),
            f"T16/T18: Orchestration.planner module namespace does not expose '{name}'",
        )


# ---------------------------------------------------------------------------
# T17 -- AST import verification
# ---------------------------------------------------------------------------
def scenario_ast_import_verification() -> None:
    source_path = ROOT / "Orchestration" / "planner.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)

    check(
        "Orchestration.capability_manager" in imported_modules,
        "T17: Orchestration.planner imports Orchestration.capability_manager",
    )

    forbidden_modules = {
        "Orchestration.skill_registry",
        "Orchestration.skill_resolver",
        "Orchestration.tool_registry",
        "Orchestration.tool_resolver",
        "Orchestration.tool_manager",
        "Orchestration.executor",
        "Orchestration.capability_registry",
        "Orchestration.capability_resolver",
        "Orchestration.capability_skill_registry",
        "Orchestration.runtime",
        "Orchestration.memory",
        "Orchestration.reflection",
        "Orchestration.learning_loop",
    }
    intersection = imported_modules & forbidden_modules
    check(
        not intersection,
        f"T17: Orchestration.planner introduces no forbidden import (found: {intersection})",
    )


# ---------------------------------------------------------------------------
# T19 -- multi-instance independence
# ---------------------------------------------------------------------------
def scenario_multi_instance_independence() -> None:
    manager_a, skill_registry_a = _make_manager()
    manager_b, skill_registry_b = _make_manager()

    skill_registry_a.register("cap.shared_name", ("skill_from_a",))
    skill_registry_b.register("cap.shared_name", ("skill_from_b",))

    planner_a = GoalPlanner(service_skills={}, capability_manager=manager_a)
    planner_b = GoalPlanner(service_skills={}, capability_manager=manager_b)

    result_a = planner_a.resolve_capabilities(Goal(metadata={"capability": "cap.shared_name"}))
    result_b = planner_b.resolve_capabilities(Goal(metadata={"capability": "cap.shared_name"}))

    check(result_a == ("skill_from_a",), "T19: planner_a resolves only from its own CapabilityManager")
    check(result_b == ("skill_from_b",), "T19: planner_b resolves only from its own CapabilityManager")
    check(result_a != result_b, "T19: two planners over independent CapabilityManagers never cross-resolve")


# ---------------------------------------------------------------------------
# T20 -- no hidden state
# ---------------------------------------------------------------------------
def scenario_no_hidden_state() -> None:
    manager, _skill_registry = _make_manager()
    planner = GoalPlanner(service_skills={}, capability_manager=manager)
    check(
        hasattr(planner, "_capability_manager"),
        "T20: GoalPlanner instance holds a '_capability_manager' attribute",
    )
    check(
        planner._capability_manager is manager,
        "T20: '_capability_manager' holds the exact injected instance by identity",
    )


# ---------------------------------------------------------------------------
# T21 -- pre-existing surface unaffected
# ---------------------------------------------------------------------------
def scenario_pre_existing_surface_unaffected() -> None:
    manager, _skill_registry = _make_manager()

    planner_without = GoalPlanner(service_skills={})
    planner_with = GoalPlanner(service_skills={}, capability_manager=manager)

    goal = Goal(metadata={"ticker": "BBCA"})
    plan_without = planner_without.build_plan(goal)
    plan_with = planner_with.build_plan(goal)

    check(
        plan_without.steps == plan_with.steps,
        "T21: build_plan() output is identical whether or not capability_manager is attached",
    )

    results_without = planner_without.execute_plan(plan_without)
    results_with = planner_with.execute_plan(plan_with)
    check(
        results_without == results_with == [],
        "T21: execute_plan() output is identical (both empty) whether or not capability_manager is attached",
    )


# ---------------------------------------------------------------------------
# T22 -- exception convention
# ---------------------------------------------------------------------------
def scenario_exception_convention() -> None:
    check(
        issubclass(GoalPlannerError, AgentError),
        "T22: GoalPlannerError remains a subclass of Core.exceptions.AgentError",
    )


# ---------------------------------------------------------------------------
# T23 -- constructor rejects bare registry/resolver (not a manager)
# ---------------------------------------------------------------------------
def scenario_constructor_rejects_bare_collaborators() -> None:
    registry = CapabilityRegistry()
    skill_registry = CapabilitySkillRegistry()
    resolver = CapabilityResolver(skill_registry)

    for value in (registry, resolver, skill_registry):
        raised = False
        try:
            GoalPlanner(service_skills={}, capability_manager=value)  # type: ignore[arg-type]
        except GoalPlannerError:
            raised = True
        check(
            raised,
            f"T23: GoalPlanner(capability_manager={type(value).__name__} instance) raises GoalPlannerError (not a CapabilityManager)",
        )


# ---------------------------------------------------------------------------
# T24 -- non-str capability value passed through verbatim
# ---------------------------------------------------------------------------
def scenario_non_str_capability_value_passthrough() -> None:
    manager, _skill_registry = _make_manager()
    planner = GoalPlanner(service_skills={}, capability_manager=manager)

    raised_type = None
    try:
        planner.resolve_capabilities(Goal(metadata={"capability": 12345}))
    except CapabilityResolverError:
        raised_type = CapabilityResolverError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is CapabilityResolverError,
        f"T24: a non-str capability value is passed through verbatim to CapabilityManager.resolve, which raises CapabilityResolverError (got {raised_type})",
    )


# ---------------------------------------------------------------------------
# T25 -- return type is exactly a tuple, never coerced by Planner
# ---------------------------------------------------------------------------
def scenario_return_type_tuple() -> None:
    manager, skill_registry = _make_manager()
    skill_registry.register("cap.tupletype", ("a", "b"))
    planner = GoalPlanner(service_skills={}, capability_manager=manager)

    result = planner.resolve_capabilities(Goal(metadata={"capability": "cap.tupletype"}))
    check(type(result) is tuple, "T25: resolve_capabilities() return value type is exactly tuple")
    check(result == ("a", "b"), "T25: resolve_capabilities() return value contents match registration")


# ---------------------------------------------------------------------------
# T26 -- capability_manager alongside memory, independent collaborators
# ---------------------------------------------------------------------------
def scenario_capability_manager_alongside_memory() -> None:
    manager, skill_registry = _make_manager()
    skill_registry.register("cap.combo", ("skill_combo",))

    class StubMemory:
        def list(self):
            return ()

    stub_memory = StubMemory()
    planner = GoalPlanner(service_skills={}, memory=stub_memory, capability_manager=manager)

    goal = Goal(metadata={"capability": "cap.combo"})
    cap_result = planner.resolve_capabilities(goal)
    recall_result = planner.recall(goal)

    check(cap_result == ("skill_combo",), "T26: resolve_capabilities() works correctly when memory is also attached")
    check(recall_result == (), "T26: recall() works correctly (independently) when capability_manager is also attached")


def main() -> int:
    scenarios = [
        scenario_constructor_omitted,
        scenario_constructor_explicit_none,
        scenario_constructor_valid_manager,
        scenario_constructor_invalid_manager,
        scenario_identity_preservation,
        scenario_goal_empty_metadata,
        scenario_goal_missing_capability_key,
        scenario_delegates_exactly_once,
        scenario_returns_exact_tuple,
        scenario_unknown_capability_propagates,
        scenario_invalid_capability_value_propagates,
        scenario_none_manager_never_raises,
        scenario_no_normalization,
        scenario_no_caching,
        scenario_public_api_exactness,
        scenario_no_touch_other_collaborators,
        scenario_no_forbidden_namespace_symbols,
        scenario_ast_import_verification,
        scenario_multi_instance_independence,
        scenario_no_hidden_state,
        scenario_pre_existing_surface_unaffected,
        scenario_exception_convention,
        scenario_constructor_rejects_bare_collaborators,
        scenario_non_str_capability_value_passthrough,
        scenario_return_type_tuple,
        scenario_capability_manager_alongside_memory,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 5 SPRINT 68 PLANNER-CAPABILITY-RESOLUTION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)

    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())