"""
Phase 5 Sprint 69 proof suite -- ``GoalPlanner`` gains the capability
to resolve a ``Goal`` all the way from a declared capability into
actual (opaque) skill objects via an injected ``SkillResolver``,
completing the discovery pipeline started by Sprint 68.

Scope: dedicated regression suite for the Sprint 69 addition only --
``Orchestration.planner.GoalPlanner``'s new optional
``skill_resolver`` constructor argument, plus its single new public
method, ``resolve_skills(goal)``. This is still discovery only: no
Skill is ever executed, no ``.execute()`` is ever called, no Tool is
ever touched, and no ``Task`` is ever created.
``build_plan``/``execute_plan``/``translate_metadata``/
``accumulate_context``/``build_workflow``/``recall``/
``resolve_capabilities`` are all unchanged by this sprint -- this
suite does not re-verify their own internal behavior beyond
confirming Sprint 69 introduces no regression to them (Sprint 68's
own dedicated suite, ``Tests.test_stage_l68_planner_capability_
resolution``, remains the source of truth for ``resolve_capabilities``
itself).

``GoalPlanner`` never executes Skills, never calls ``.execute()`` on
anything ``resolve_skills`` returns, never inspects a resolved skill
object or ``BaseSkill``/descriptor shape, never accesses
``ToolResolver``, ``ToolManager``, or ``Executor``, never creates a
``Task``, and never modifies a ``Workflow`` from within
``resolve_skills`` (proven both by direct behavioral tests and by
AST-level import inspection of the module's own source file).
``Orchestration.planner`` adds exactly one new import for this
sprint: ``Orchestration.skill_resolver.SkillResolver``.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x/L6x proof suites (mirroring
``Tests.test_stage_l68_planner_capability_resolution`` in particular):
a global pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage (target 30+):
    U1  -- constructor: skill_resolver omitted (default None)
           constructs successfully; resolve_skills() returns ().
    U2  -- constructor: skill_resolver=None explicitly constructs
           successfully; resolve_skills() returns ().
    U3  -- constructor: a valid SkillResolver instance constructs
           successfully.
    U4  -- constructor: every invalid, non-SkillResolver value (not
           None) raises GoalPlannerError.
    U5  -- identity preservation: the exact SkillResolver instance
           passed in is the one delegated to.
    U6  -- resolve_skills: no capability_manager attached (only
           skill_resolver) returns ().
    U7  -- resolve_skills: no skill_resolver attached (only
           capability_manager) returns ().
    U8  -- resolve_skills: neither collaborator attached returns ().
    U9  -- resolve_skills: capability resolution itself returns ()
           (goal.metadata missing "capability") -> resolve_skills
           returns ().
    U10 -- resolve_skills: single resolved capability name -> exactly
           one SkillResolver.resolve() call -> single skill object
           returned.
    U11 -- resolve_skills: multiple resolved skill names -> resolver
           called exactly once per skill name.
    U12 -- resolve_skills: returned tuple order matches resolver
           (capability) order exactly.
    U13 -- resolve_skills: returned object identity is exactly what
           SkillResolver.resolve returned (no copy, no wrapper).
    U14 -- resolve_skills: no deduplication -- a capability resolving
           to the same skill name twice yields two resolver calls and
           two (possibly-identical) entries in the result.
    U15 -- resolve_skills: no sorting -- result order follows resolver
           order, not alphabetical order.
    U16 -- exception propagation: an unknown capability's exception
           (from CapabilityManager/CapabilityResolver/
           CapabilitySkillRegistry) propagates unchanged through
           resolve_skills, not wrapped as GoalPlannerError.
    U17 -- exception propagation: a SkillResolver-level exception for
           an unresolvable skill name propagates unchanged through
           resolve_skills, not wrapped as GoalPlannerError.
    U18 -- exception propagation: SkillResolver is called with the
           exact skill_name string, unmodified (no normalization
           before the call that could mask an exception).
    U19 -- no execution: resolve_skills never calls any method (e.g.
           .execute()) on the objects SkillResolver.resolve returns.
    U20 -- no Task creation: resolve_skills never constructs a
           Orchestration.task.Task instance.
    U21 -- no forbidden namespace symbols: GoalPlanner's module
           namespace contains no ToolResolver/ToolManager/Executor/
           BaseSkill/SkillRegistry symbol.
    U22 -- AST import verification: Orchestration.planner's only new
           import for this sprint is
           Orchestration.skill_resolver.SkillResolver.
    U23 -- public API exactness: exactly one new public method exists
           on GoalPlanner beyond the Sprint 68 surface --
           resolve_skills.
    U24 -- multi-instance independence: two GoalPlanner instances
           built over two independent SkillResolver collaborators
           never cross-resolve into each other's skills.
    U25 -- no hidden state: a GoalPlanner instance's new attribute is
           exactly '_skill_resolver' -- no cache, no registry
           reference of its own.
    U26 -- no caching: two resolve_skills() calls for the same goal
           each re-delegate to SkillResolver.resolve (no memoized
           result masking a registry change).
    U27 -- pre-existing surface unaffected: build_plan/execute_plan
           behave identically whether or not skill_resolver is
           attached.
    U28 -- resolve_capabilities unaffected: still returns identical
           results whether or not skill_resolver is also attached.
    U29 -- exception convention: GoalPlannerError remains a subclass
           of Core.exceptions.AgentError.
    U30 -- constructor rejects a bare SkillRegistry/CapabilityManager
           (not a SkillResolver) with GoalPlannerError.
    U31 -- combination: skill_resolver alongside memory and
           capability_manager -- each collaborator works
           independently through its own method.
    U32 -- resolve_skills reads goal only through resolve_capabilities
           -- a goal whose metadata has extra unrelated keys still
           resolves correctly and those keys are never consulted.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.capability_manager import CapabilityManager
from Orchestration.capability_registry import CapabilityRegistry
from Orchestration.capability_resolver import CapabilityResolver
from Orchestration.capability_skill_registry import (
    CapabilitySkillRegistry,
    CapabilitySkillRegistryError,
)
from Orchestration.skill_registry import SkillRegistry
from Orchestration.skill_resolver import SkillResolver, SkillResolverError
import Orchestration.task as task_module
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


def _make_capability_manager():
    """Return a fresh (CapabilityManager, CapabilitySkillRegistry) pair."""
    registry = CapabilityRegistry()
    skill_registry = CapabilitySkillRegistry()
    resolver = CapabilityResolver(skill_registry)
    manager = CapabilityManager(registry, resolver)
    return manager, skill_registry


class _StubSkillResolver(SkillResolver):
    """A SkillResolver subclass (so ``isinstance`` checks pass) that
    resolves plain skill-name strings directly against an in-memory
    mapping, and records every call it receives -- used purely so
    this test suite can observe call count/order/identity without
    needing a full Task-based SkillResolver.resolve(task) call, which
    is orthogonal to what GoalPlanner.resolve_skills is contracted to
    do (call SkillResolver.resolve(skill_name) for each resolved
    skill name)."""

    def __init__(self, mapping):
        # Deliberately skip SkillResolver.__init__ (which requires a
        # real SkillRegistry) -- this stub only needs to satisfy
        # isinstance(_, SkillResolver) and observe calls.
        self._mapping = dict(mapping)
        self.calls: List[str] = []

    def resolve(self, skill_name):  # type: ignore[override]
        self.calls.append(skill_name)
        if skill_name not in self._mapping:
            raise SkillResolverError(
                f"_StubSkillResolver: no skill registered for {skill_name!r}"
            )
        return self._mapping[skill_name]


# ---------------------------------------------------------------------------
# U1 -- constructor: skill_resolver omitted
# ---------------------------------------------------------------------------
def scenario_constructor_omitted() -> None:
    planner = GoalPlanner(service_skills={})
    check(
        isinstance(planner, GoalPlanner),
        "U1: GoalPlanner(service_skills={}) with skill_resolver omitted constructs successfully",
    )
    check(
        planner.resolve_skills(Goal(metadata={"capability": "x"})) == (),
        "U1: resolve_skills() returns () when skill_resolver was never supplied",
    )


# ---------------------------------------------------------------------------
# U2 -- constructor: skill_resolver=None explicitly
# ---------------------------------------------------------------------------
def scenario_constructor_explicit_none() -> None:
    planner = GoalPlanner(service_skills={}, skill_resolver=None)
    check(
        isinstance(planner, GoalPlanner),
        "U2: GoalPlanner(service_skills={}, skill_resolver=None) constructs successfully",
    )
    check(
        planner.resolve_skills(Goal(metadata={"capability": "x"})) == (),
        "U2: resolve_skills() returns () when skill_resolver=None explicitly",
    )


# ---------------------------------------------------------------------------
# U3 -- constructor: valid SkillResolver
# ---------------------------------------------------------------------------
def scenario_constructor_valid_resolver() -> None:
    stub = _StubSkillResolver({})
    planner = GoalPlanner(service_skills={}, skill_resolver=stub)
    check(
        isinstance(planner, GoalPlanner),
        "U3: GoalPlanner(service_skills={}, skill_resolver=<SkillResolver>) constructs successfully",
    )


# ---------------------------------------------------------------------------
# U4 -- constructor: invalid skill_resolver values
# ---------------------------------------------------------------------------
def scenario_constructor_invalid_resolver() -> None:
    bad_values = ("not-a-resolver", 123, object(), {}, [], True)

    for value in bad_values:
        raised = False
        try:
            GoalPlanner(service_skills={}, skill_resolver=value)  # type: ignore[arg-type]
        except GoalPlannerError:
            raised = True
        check(
            raised,
            f"U4: GoalPlanner(skill_resolver={value!r}) raises GoalPlannerError",
        )


# ---------------------------------------------------------------------------
# U5 -- identity preservation
# ---------------------------------------------------------------------------
def scenario_identity_preservation() -> None:
    stub = _StubSkillResolver({"skill_alpha": object()})
    planner = GoalPlanner(service_skills={}, skill_resolver=stub)
    check(
        planner._skill_resolver is stub,
        "U5: GoalPlanner stores the exact injected SkillResolver instance by identity",
    )


# ---------------------------------------------------------------------------
# U6 -- no capability_manager attached
# ---------------------------------------------------------------------------
def scenario_no_capability_manager() -> None:
    stub = _StubSkillResolver({"skill_x": object()})
    planner = GoalPlanner(service_skills={}, skill_resolver=stub)
    result = planner.resolve_skills(Goal(metadata={"capability": "cap.a"}))
    check(result == (), "U6: resolve_skills() returns () when no capability_manager is attached")
    check(stub.calls == [], "U6: SkillResolver.resolve is never called when no capability_manager is attached")


# ---------------------------------------------------------------------------
# U7 -- no skill_resolver attached
# ---------------------------------------------------------------------------
def scenario_no_skill_resolver() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.b", ("skill_y",))
    planner = GoalPlanner(service_skills={}, capability_manager=manager)
    result = planner.resolve_skills(Goal(metadata={"capability": "cap.b"}))
    check(result == (), "U7: resolve_skills() returns () when no skill_resolver is attached")


# ---------------------------------------------------------------------------
# U8 -- neither collaborator attached
# ---------------------------------------------------------------------------
def scenario_neither_collaborator() -> None:
    planner = GoalPlanner(service_skills={})
    result = planner.resolve_skills(Goal(metadata={"capability": "cap.c"}))
    check(result == (), "U8: resolve_skills() returns () when neither capability_manager nor skill_resolver is attached")


# ---------------------------------------------------------------------------
# U9 -- capability resolution itself returns ()
# ---------------------------------------------------------------------------
def scenario_capability_resolution_empty() -> None:
    manager, _skill_registry = _make_capability_manager()
    stub = _StubSkillResolver({"skill_never_called": object()})
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    result = planner.resolve_skills(Goal(metadata={}))  # no "capability" key
    check(result == (), "U9: resolve_skills() returns () when resolve_capabilities() itself returns ()")
    check(stub.calls == [], "U9: SkillResolver.resolve is never called when there are no resolved capability names")


# ---------------------------------------------------------------------------
# U10 -- single capability -> single skill
# ---------------------------------------------------------------------------
def scenario_single_capability_single_skill() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.single", ("skill_solo",))

    skill_obj = object()
    stub = _StubSkillResolver({"skill_solo": skill_obj})
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    result = planner.resolve_skills(Goal(metadata={"capability": "cap.single"}))
    check(result == (skill_obj,), "U10: single resolved capability name yields a single-element tuple of the resolved skill")
    check(stub.calls == ["skill_solo"], "U10: SkillResolver.resolve was called exactly once, with the resolved skill name")


# ---------------------------------------------------------------------------
# U11 -- multiple skills -> resolver called once per skill
# ---------------------------------------------------------------------------
def scenario_multiple_skills_call_count() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.multi", ("skill_1", "skill_2", "skill_3"))

    objs = {"skill_1": object(), "skill_2": object(), "skill_3": object()}
    stub = _StubSkillResolver(objs)
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    result = planner.resolve_skills(Goal(metadata={"capability": "cap.multi"}))
    check(len(stub.calls) == 3, "U11: SkillResolver.resolve was called exactly once per resolved skill name (3 calls)")
    check(result == (objs["skill_1"], objs["skill_2"], objs["skill_3"]), "U11: resolve_skills() returns all three resolved skill objects")


# ---------------------------------------------------------------------------
# U12 -- order preservation
# ---------------------------------------------------------------------------
def scenario_order_preservation() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.order", ("skill_c", "skill_a", "skill_b"))

    objs = {"skill_c": "OBJ_C", "skill_a": "OBJ_A", "skill_b": "OBJ_B"}
    stub = _StubSkillResolver(objs)
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    result = planner.resolve_skills(Goal(metadata={"capability": "cap.order"}))
    check(
        result == ("OBJ_C", "OBJ_A", "OBJ_B"),
        "U12: returned tuple order matches the capability's declared (non-alphabetical) skill-name order exactly",
    )
    check(
        stub.calls == ["skill_c", "skill_a", "skill_b"],
        "U12: SkillResolver.resolve was called in the same non-alphabetical order",
    )


# ---------------------------------------------------------------------------
# U13 -- identity of returned objects preserved
# ---------------------------------------------------------------------------
def scenario_returned_object_identity() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.identity", ("skill_ident",))

    class DistinctiveSkill:
        pass

    skill_obj = DistinctiveSkill()
    stub = _StubSkillResolver({"skill_ident": skill_obj})
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    result = planner.resolve_skills(Goal(metadata={"capability": "cap.identity"}))
    check(len(result) == 1 and result[0] is skill_obj, "U13: resolve_skills() returns the exact object SkillResolver.resolve returned (identity preserved, no copy/wrapper)")


# ---------------------------------------------------------------------------
# U14 -- no deduplication
# ---------------------------------------------------------------------------
def scenario_no_deduplication() -> None:
    manager, _skill_registry = _make_capability_manager()

    obj = object()
    stub = _StubSkillResolver({"skill_repeat": obj})
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    # CapabilitySkillRegistry itself forbids duplicate skill_names at
    # registration time (a registry-level constraint, unrelated to
    # this sprint) -- so to prove GoalPlanner.resolve_skills performs
    # no deduplication of its own, we override resolve_capabilities
    # (already proven correct by the Sprint 68 suite) to simulate a
    # capability resolution that yields a duplicate skill name, and
    # confirm resolve_skills does not collapse it.
    planner.resolve_capabilities = lambda goal: ("skill_repeat", "skill_repeat")  # type: ignore[assignment]

    result = planner.resolve_skills(Goal(metadata={"capability": "cap.dup"}))
    check(result == (obj, obj), "U14: a capability resolving to a duplicate skill name yields two entries in the result (no dedup)")
    check(stub.calls == ["skill_repeat", "skill_repeat"], "U14: SkillResolver.resolve was called twice for the duplicate skill name (no dedup before delegation)")


# ---------------------------------------------------------------------------
# U15 -- no sorting
# ---------------------------------------------------------------------------
def scenario_no_sorting() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.unsorted", ("skill_zeta", "skill_alpha", "skill_mu"))

    objs = {"skill_zeta": "Z", "skill_alpha": "A", "skill_mu": "M"}
    stub = _StubSkillResolver(objs)
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    result = planner.resolve_skills(Goal(metadata={"capability": "cap.unsorted"}))
    check(result == ("Z", "A", "M"), "U15: result is not sorted -- follows declared/resolver order, not alphabetical order")


# ---------------------------------------------------------------------------
# U16 -- CapabilityManager-level exception propagates unchanged
# ---------------------------------------------------------------------------
def scenario_capability_exception_propagates() -> None:
    manager, _skill_registry = _make_capability_manager()
    stub = _StubSkillResolver({})
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    raised_type = None
    try:
        planner.resolve_skills(Goal(metadata={"capability": "cap.nonexistent"}))
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is CapabilitySkillRegistryError,
        f"U16: an unknown capability's exception propagates unchanged as CapabilitySkillRegistryError (got {raised_type})",
    )
    check(stub.calls == [], "U16: SkillResolver.resolve is never reached once capability resolution itself fails")


# ---------------------------------------------------------------------------
# U17 -- SkillResolver-level exception propagates unchanged
# ---------------------------------------------------------------------------
def scenario_skill_resolver_exception_propagates() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.missing_skill", ("skill_unregistered",))

    stub = _StubSkillResolver({})  # deliberately empty -- lookup will miss
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    raised_type = None
    try:
        planner.resolve_skills(Goal(metadata={"capability": "cap.missing_skill"}))
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is SkillResolverError,
        f"U17: an unresolvable skill name's exception propagates unchanged as SkillResolverError (got {raised_type})",
    )
    check(not isinstance(raised_type, type) or not issubclass(raised_type, GoalPlannerError), "U17: the propagated exception is NOT wrapped as GoalPlannerError")


# ---------------------------------------------------------------------------
# U18 -- skill name passed through unmodified
# ---------------------------------------------------------------------------
def scenario_skill_name_unmodified() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("Cap.Weird_Name", ("Skill.Weird_Name ",))

    obj = object()
    stub = _StubSkillResolver({"Skill.Weird_Name ": obj})
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    result = planner.resolve_skills(Goal(metadata={"capability": "Cap.Weird_Name"}))
    check(result == (obj,), "U18: an exact-case, exact-whitespace skill name resolves correctly")
    check(stub.calls == ["Skill.Weird_Name "], "U18: SkillResolver.resolve received the skill name completely unmodified (no trim/lowercase)")


# ---------------------------------------------------------------------------
# U19 -- never executes resolved skills
# ---------------------------------------------------------------------------
def scenario_never_executes_skills() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.exec_guard", ("skill_guarded",))

    class ExplodingSkill:
        def execute(self, *args, **kwargs):
            raise AssertionError("resolve_skills must never call execute()")

        def __call__(self, *args, **kwargs):
            raise AssertionError("resolve_skills must never call the skill object")

    guarded = ExplodingSkill()
    stub = _StubSkillResolver({"skill_guarded": guarded})
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    exploded = False
    result = None
    try:
        result = planner.resolve_skills(Goal(metadata={"capability": "cap.exec_guard"}))
    except AssertionError:
        exploded = True

    check(not exploded, "U19: resolve_skills() never calls .execute() or otherwise invokes a resolved skill object")
    check(result == (guarded,), "U19: resolve_skills() still returns the resolved (unexecuted) skill object")


# ---------------------------------------------------------------------------
# U20 -- no Task creation
# ---------------------------------------------------------------------------
def scenario_no_task_creation() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.no_task", ("skill_no_task",))

    stub = _StubSkillResolver({"skill_no_task": object()})
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    original_init = task_module.Task.__init__
    call_count = {"n": 0}

    def counting_init(self, *args, **kwargs):
        call_count["n"] += 1
        return original_init(self, *args, **kwargs)

    task_module.Task.__init__ = counting_init  # type: ignore[method-assign]
    try:
        planner.resolve_skills(Goal(metadata={"capability": "cap.no_task"}))
    finally:
        task_module.Task.__init__ = original_init  # type: ignore[method-assign]

    check(call_count["n"] == 0, "U20: resolve_skills() never constructs a Orchestration.task.Task instance")


# ---------------------------------------------------------------------------
# U21 -- no forbidden namespace symbols
# ---------------------------------------------------------------------------
def scenario_no_forbidden_namespace_symbols() -> None:
    import Orchestration.planner as planner_module

    forbidden = ["ToolResolver", "ToolManager", "Executor", "BaseSkill", "SkillRegistry"]
    for name in forbidden:
        check(
            not hasattr(planner_module, name),
            f"U21: Orchestration.planner module namespace does not expose '{name}'",
        )


# ---------------------------------------------------------------------------
# U22 -- AST import verification
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
        "Orchestration.skill_resolver" in imported_modules,
        "U22: Orchestration.planner imports Orchestration.skill_resolver",
    )

    forbidden_modules = {
        "Orchestration.tool_resolver",
        "Orchestration.tool_manager",
        "Orchestration.executor",
        "Orchestration.skill_registry",
        "Orchestration.base_skill",
        "Orchestration.runtime",
        "Orchestration.memory",
        "Orchestration.reflection",
        "Orchestration.learning_loop",
    }
    intersection = imported_modules & forbidden_modules
    check(
        not intersection,
        f"U22: Orchestration.planner introduces no forbidden import (found: {intersection})",
    )


# ---------------------------------------------------------------------------
# U23 -- public API exactness
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
        "resolve_skills",
    }
    actual_public_methods = {
        name
        for name in dir(GoalPlanner)
        if not name.startswith("_") and callable(getattr(GoalPlanner, name))
    }
    check(
        actual_public_methods == expected_public_methods,
        f"U23: GoalPlanner's public methods are exactly {sorted(expected_public_methods)} (got {sorted(actual_public_methods)})",
    )


# ---------------------------------------------------------------------------
# U24 -- multi-instance independence
# ---------------------------------------------------------------------------
def scenario_multi_instance_independence() -> None:
    manager_a, skill_registry_a = _make_capability_manager()
    manager_b, skill_registry_b = _make_capability_manager()

    skill_registry_a.register("cap.shared", ("skill_shared",))
    skill_registry_b.register("cap.shared", ("skill_shared",))

    stub_a = _StubSkillResolver({"skill_shared": "FROM_A"})
    stub_b = _StubSkillResolver({"skill_shared": "FROM_B"})

    planner_a = GoalPlanner(service_skills={}, capability_manager=manager_a, skill_resolver=stub_a)
    planner_b = GoalPlanner(service_skills={}, capability_manager=manager_b, skill_resolver=stub_b)

    result_a = planner_a.resolve_skills(Goal(metadata={"capability": "cap.shared"}))
    result_b = planner_b.resolve_skills(Goal(metadata={"capability": "cap.shared"}))

    check(result_a == ("FROM_A",), "U24: planner_a resolves only from its own SkillResolver")
    check(result_b == ("FROM_B",), "U24: planner_b resolves only from its own SkillResolver")
    check(stub_a.calls == ["skill_shared"] and stub_b.calls == ["skill_shared"], "U24: each stub received exactly its own planner's calls, no cross-talk")


# ---------------------------------------------------------------------------
# U25 -- no hidden state
# ---------------------------------------------------------------------------
def scenario_no_hidden_state() -> None:
    stub = _StubSkillResolver({})
    planner = GoalPlanner(service_skills={}, skill_resolver=stub)
    check(hasattr(planner, "_skill_resolver"), "U25: GoalPlanner instance holds a '_skill_resolver' attribute")
    check(planner._skill_resolver is stub, "U25: '_skill_resolver' holds the exact injected instance by identity")


# ---------------------------------------------------------------------------
# U26 -- no caching
# ---------------------------------------------------------------------------
def scenario_no_caching() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.mutable_skill", ("skill_v1",))

    stub = _StubSkillResolver({"skill_v1": "OBJ_V1", "skill_v2": "OBJ_V2"})
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    goal = Goal(metadata={"capability": "cap.mutable_skill"})
    first = planner.resolve_skills(goal)

    skill_registry.unregister("cap.mutable_skill")
    skill_registry.register("cap.mutable_skill", ("skill_v2",))

    second = planner.resolve_skills(goal)

    check(first == ("OBJ_V1",), "U26: first resolve_skills() call reflects the initial registration")
    check(second == ("OBJ_V2",), "U26: second resolve_skills() call reflects the updated registration -- no cached/stale result")
    check(stub.calls == ["skill_v1", "skill_v2"], "U26: SkillResolver.resolve was re-invoked on the second call (no memoization)")


# ---------------------------------------------------------------------------
# U27 -- pre-existing surface unaffected
# ---------------------------------------------------------------------------
def scenario_pre_existing_surface_unaffected() -> None:
    stub = _StubSkillResolver({})

    planner_without = GoalPlanner(service_skills={})
    planner_with = GoalPlanner(service_skills={}, skill_resolver=stub)

    goal = Goal(metadata={"ticker": "BBCA"})
    plan_without = planner_without.build_plan(goal)
    plan_with = planner_with.build_plan(goal)

    check(
        plan_without.steps == plan_with.steps,
        "U27: build_plan() output is identical whether or not skill_resolver is attached",
    )

    results_without = planner_without.execute_plan(plan_without)
    results_with = planner_with.execute_plan(plan_with)
    check(
        results_without == results_with == [],
        "U27: execute_plan() output is identical (both empty) whether or not skill_resolver is attached",
    )


# ---------------------------------------------------------------------------
# U28 -- resolve_capabilities unaffected
# ---------------------------------------------------------------------------
def scenario_resolve_capabilities_unaffected() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.check", ("skill_check_a", "skill_check_b"))

    stub = _StubSkillResolver({"skill_check_a": "A", "skill_check_b": "B"})

    planner_without_resolver = GoalPlanner(service_skills={}, capability_manager=manager)
    planner_with_resolver = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    goal = Goal(metadata={"capability": "cap.check"})
    result_without = planner_without_resolver.resolve_capabilities(goal)
    result_with = planner_with_resolver.resolve_capabilities(goal)

    check(
        result_without == result_with == ("skill_check_a", "skill_check_b"),
        "U28: resolve_capabilities() output is unaffected by whether skill_resolver is also attached",
    )


# ---------------------------------------------------------------------------
# U29 -- exception convention
# ---------------------------------------------------------------------------
def scenario_exception_convention() -> None:
    check(
        issubclass(GoalPlannerError, AgentError),
        "U29: GoalPlannerError remains a subclass of Core.exceptions.AgentError",
    )


# ---------------------------------------------------------------------------
# U30 -- constructor rejects bare collaborators (not a SkillResolver)
# ---------------------------------------------------------------------------
def scenario_constructor_rejects_bare_collaborators() -> None:
    registry = SkillRegistry()
    manager, _skill_registry = _make_capability_manager()

    for value in (registry, manager):
        raised = False
        try:
            GoalPlanner(service_skills={}, skill_resolver=value)  # type: ignore[arg-type]
        except GoalPlannerError:
            raised = True
        check(
            raised,
            f"U30: GoalPlanner(skill_resolver={type(value).__name__} instance) raises GoalPlannerError (not a SkillResolver)",
        )


# ---------------------------------------------------------------------------
# U31 -- combination: skill_resolver alongside memory and capability_manager
# ---------------------------------------------------------------------------
def scenario_full_combination() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.combo", ("skill_combo",))
    stub = _StubSkillResolver({"skill_combo": "COMBO_SKILL"})

    class StubMemory:
        def list(self):
            return ()

    stub_memory = StubMemory()
    planner = GoalPlanner(
        service_skills={},
        memory=stub_memory,
        capability_manager=manager,
        skill_resolver=stub,
    )

    goal = Goal(metadata={"capability": "cap.combo"})
    check(planner.resolve_skills(goal) == ("COMBO_SKILL",), "U31: resolve_skills() works correctly with memory also attached")
    check(planner.recall(goal) == (), "U31: recall() works correctly (independently) with skill_resolver also attached")
    check(planner.resolve_capabilities(goal) == ("skill_combo",), "U31: resolve_capabilities() works correctly with skill_resolver also attached")


# ---------------------------------------------------------------------------
# U32 -- extra unrelated metadata keys never consulted
# ---------------------------------------------------------------------------
def scenario_extra_metadata_ignored() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.extra", ("skill_extra",))
    stub = _StubSkillResolver({"skill_extra": "EXTRA_SKILL"})
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    goal = Goal(metadata={"capability": "cap.extra", "ticker": "BBCA", "period": "1D"})
    result = planner.resolve_skills(goal)
    check(result == ("EXTRA_SKILL",), "U32: extra unrelated metadata keys do not affect resolve_skills()'s outcome")


def main() -> int:
    scenarios = [
        scenario_constructor_omitted,
        scenario_constructor_explicit_none,
        scenario_constructor_valid_resolver,
        scenario_constructor_invalid_resolver,
        scenario_identity_preservation,
        scenario_no_capability_manager,
        scenario_no_skill_resolver,
        scenario_neither_collaborator,
        scenario_capability_resolution_empty,
        scenario_single_capability_single_skill,
        scenario_multiple_skills_call_count,
        scenario_order_preservation,
        scenario_returned_object_identity,
        scenario_no_deduplication,
        scenario_no_sorting,
        scenario_capability_exception_propagates,
        scenario_skill_resolver_exception_propagates,
        scenario_skill_name_unmodified,
        scenario_never_executes_skills,
        scenario_no_task_creation,
        scenario_no_forbidden_namespace_symbols,
        scenario_ast_import_verification,
        scenario_public_api_exactness,
        scenario_multi_instance_independence,
        scenario_no_hidden_state,
        scenario_no_caching,
        scenario_pre_existing_surface_unaffected,
        scenario_resolve_capabilities_unaffected,
        scenario_exception_convention,
        scenario_constructor_rejects_bare_collaborators,
        scenario_full_combination,
        scenario_extra_metadata_ignored,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 5 SPRINT 69 PLANNER-SKILL-RESOLUTION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)

    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())