"""
Phase 6 Sprint 71 proof suite -- ``SkillExecutionPlan`` (a new,
standalone immutable value object) and ``GoalPlanner``'s single new
method, ``build_skill_execution_plan(goal)``, which packages a
discovery result into that value object, completing the boundary

    Goal -> resolve_skills(goal) -> discover_tools(goal) -> SkillExecutionPlan

Scope: dedicated regression suite for the Sprint 71 addition only.
The Planner still does NOT execute anything -- this sprint only
connects the Discovery Layer to the Execution Layer via a value
object. ``build_plan``/``execute_plan``/``translate_metadata``/
``accumulate_context``/``build_workflow``/``recall``/
``resolve_capabilities``/``resolve_skills``/``discover_tools`` are all
unchanged by this sprint -- this suite does not re-verify their own
internal behavior beyond confirming Sprint 71 introduces no
regression to them.

``SkillExecutionPlan`` never executes a skill or a tool, is never
wired into ``Executor``, ``Runtime``, ``Workflow``, or ``EventBus``,
and never inspects ``BaseSkill`` or ``BaseTool`` (proven both by
direct behavioral tests and by AST-level import inspection of both
module source files). ``GoalPlanner.build_skill_execution_plan`` reads
only what :meth:`resolve_skills` and :meth:`discover_tools` already
return -- it performs no normalization, caching, ranking, reordering,
or deduplication of its own.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x/L6x/L7x proof suites (mirroring
``Tests.test_stage_l70_planner_tool_discovery`` in particular): a
global pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage (target 40+):
    V1  -- construction: valid tuple/tuple/Mapping succeeds.
    V2  -- construction: skills=list (not tuple) raises
           SkillExecutionPlanError.
    V3  -- construction: tools=list (not tuple) raises
           SkillExecutionPlanError.
    V4  -- construction: metadata=not-a-Mapping raises
           SkillExecutionPlanError.
    V5  -- construction: metadata=None raises SkillExecutionPlanError.
    V6  -- construction: skills=generator (not tuple) raises
           SkillExecutionPlanError.
    V7  -- construction: tools=set (not tuple) raises
           SkillExecutionPlanError.
    V8  -- construction: empty skills=() and tools=() with metadata={}
           is valid.
    V9  -- immutability: reassigning any of the three fields raises
           dataclasses.FrozenInstanceError.
    V10 -- metadata freezing: plan.metadata is a MappingProxyType
           instance after construction.
    V11 -- metadata freezing: mutating the original dict passed in
           after construction has no effect on plan.metadata.
    V12 -- metadata freezing: item assignment on plan.metadata itself
           raises TypeError.
    V13 -- hash: SkillExecutionPlan.__hash__() == hash(id(plan.skills)).
    V14 -- hash: two distinct plans sharing the same skills tuple
           object share the same hash.
    V15 -- hash: two distinct plans holding two distinct (but
           value-equal) skills tuples do NOT share the same hash
           (identity, not value, is hashed).
    V16 -- equality: two plans built from the exact same skills/tools
           tuple objects and equal metadata dicts compare equal.
    V17 -- equality/hash contract: two plans sharing skills identity
           but differing tools are not equal, yet still share a hash
           (permitted by Python's hash/eq contract).
    V18 -- tuple preservation: skills elements preserved by identity,
           in order, no copying.
    V19 -- tuple preservation: tools elements preserved verbatim, in
           order, with duplicates intact.
    V20 -- order preservation: skills order exactly matches input
           order (non-alphabetical input round-trips unmodified).
    V21 -- exactly three dataclass fields exist: skills, tools,
           metadata -- nothing else.
    V22 -- only __post_init__ and __hash__ are defined on the class
           beyond dataclass-generated machinery.
    V23 -- SkillExecutionPlanError subclasses Core.exceptions.AgentError.
    V24 -- metadata accepts a plain empty dict and freezes it.
    V25 -- metadata dict with entries is copied and frozen correctly.
    V26 -- SkillExecutionPlan is not hashable-by-content: two
           instances with equal-by-value but distinct skills tuple
           objects hash differently, confirming id()-based hashing.
    V27 -- Planner: build_skill_execution_plan returns a
           SkillExecutionPlan instance.
    V28 -- Planner: plan.skills == self.resolve_skills(goal) exactly.
    V29 -- Planner: plan.tools == self.discover_tools(goal) exactly.
    V30 -- Planner: plan.metadata == {} always (empty mapping).
    V31 -- Planner: skill order in the plan matches resolve_skills
           order (non-alphabetical capability order preserved).
    V32 -- Planner: duplicate tool names across skills are preserved
           in plan.tools (no dedup).
    V33 -- Planner: no collaborators attached -> plan is
           SkillExecutionPlan(skills=(), tools=(), metadata={}).
    V34 -- Planner: build_skill_execution_plan never calls
           .execute() on any resolved skill.
    V35 -- Planner: build_skill_execution_plan never mutates the
           input Goal.
    V36 -- Planner: calling build_skill_execution_plan twice with an
           unchanged registry yields value-equal (not identical)
           plans -- no hidden caching of the SkillExecutionPlan itself.
    V37 -- Planner: updating the underlying SkillToolRegistry between
           two calls changes the second plan's tools -- proving no
           stale cache.
    V38 -- exception propagation: a SkillResolver-level exception
           propagates unchanged through build_skill_execution_plan.
    V39 -- exception propagation: a SkillToolRegistry miss propagates
           unchanged through build_skill_execution_plan.
    V40 -- AST import verification: Orchestration.planner imports
           Orchestration.skill_execution_plan and introduces no
           forbidden collaborator import.
    V41 -- AST import verification: Orchestration.skill_execution_plan
           itself imports only the allowed dependency set.
    V42 -- namespace verification: Orchestration.planner module does
           not expose Executor/Runtime/WorkflowEngine/EventBus/etc.
    V43 -- namespace verification: Orchestration.skill_execution_plan
           module does not expose Executor/Runtime/Workflow/EventBus/
           BaseSkill/BaseTool.
    V44 -- multi-instance independence: two GoalPlanner instances with
           independent collaborators build independent plans (no
           shared/singleton state).
    V45 -- pre-existing Planner surface (build_plan/execute_plan/
           resolve_skills/discover_tools) is completely unaffected by
           this addition.
    V46 -- public API exactness: GoalPlanner exposes exactly one new
           public method, build_skill_execution_plan.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from types import MappingProxyType
from typing import List

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
from Orchestration.skill_resolver import SkillResolver, SkillResolverError
from Orchestration.skill_tool_registry import SkillToolRegistry, SkillToolRegistryError
from Orchestration.skill_execution_plan import (
    SkillExecutionPlan,
    SkillExecutionPlanError,
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
    mapping, and records every call it receives."""

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


class _GuardedSkill:
    """A skill stand-in that tolerates only ``.name`` access -- any
    other attribute access or invocation is a hard failure, proving
    ``build_skill_execution_plan`` never executes a resolved skill."""

    def __init__(self, name):
        self._name = name

    @property
    def name(self):
        return self._name

    def execute(self, *args, **kwargs):
        raise AssertionError(
            "build_skill_execution_plan must never call .execute()"
        )

    def __call__(self, *args, **kwargs):
        raise AssertionError(
            "build_skill_execution_plan must never call a skill object"
        )


def _full_planner(skill_map, tool_map):
    """Build a fully-wired GoalPlanner (capability_manager +
    skill_resolver + skill_tool_registry) from
    {capability_name: (skill_name, ...)} and {skill_name: (tool_name, ...)}
    mappings. Returns (planner, capability_skill_registry, skill_tool_registry).
    """
    manager, capability_skill_registry = _make_capability_manager()
    for capability_name, skill_names in skill_map.items():
        capability_skill_registry.register(capability_name, skill_names)

    resolver_mapping = {}
    for skill_names in skill_map.values():
        for skill_name in skill_names:
            resolver_mapping[skill_name] = _GuardedSkill(skill_name)
    stub_resolver = _StubSkillResolver(resolver_mapping)

    tool_registry = SkillToolRegistry()
    for skill_name, tool_names in tool_map.items():
        tool_registry.register(skill_name, tool_names)

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub_resolver,
        skill_tool_registry=tool_registry,
    )
    return planner, capability_skill_registry, tool_registry


# ---------------------------------------------------------------------------
# V1 -- construction: valid inputs
# ---------------------------------------------------------------------------
def scenario_construction_valid() -> None:
    plan = SkillExecutionPlan(skills=("a", "b"), tools=("t1",), metadata={"k": "v"})
    check(isinstance(plan, SkillExecutionPlan), "V1: valid construction succeeds")
    check(plan.skills == ("a", "b"), "V1: skills stored as given")
    check(plan.tools == ("t1",), "V1: tools stored as given")
    check(dict(plan.metadata) == {"k": "v"}, "V1: metadata stored as given")


# ---------------------------------------------------------------------------
# V2 -- construction: skills not a tuple
# ---------------------------------------------------------------------------
def scenario_construction_skills_not_tuple() -> None:
    raised = False
    try:
        SkillExecutionPlan(skills=["a", "b"], tools=(), metadata={})  # type: ignore[arg-type]
    except SkillExecutionPlanError:
        raised = True
    check(raised, "V2: skills=list raises SkillExecutionPlanError")


# ---------------------------------------------------------------------------
# V3 -- construction: tools not a tuple
# ---------------------------------------------------------------------------
def scenario_construction_tools_not_tuple() -> None:
    raised = False
    try:
        SkillExecutionPlan(skills=(), tools=["t1"], metadata={})  # type: ignore[arg-type]
    except SkillExecutionPlanError:
        raised = True
    check(raised, "V3: tools=list raises SkillExecutionPlanError")


# ---------------------------------------------------------------------------
# V4 -- construction: metadata not a Mapping
# ---------------------------------------------------------------------------
def scenario_construction_metadata_not_mapping() -> None:
    raised = False
    try:
        SkillExecutionPlan(skills=(), tools=(), metadata=["not", "a", "mapping"])  # type: ignore[arg-type]
    except SkillExecutionPlanError:
        raised = True
    check(raised, "V4: metadata=list raises SkillExecutionPlanError")


# ---------------------------------------------------------------------------
# V5 -- construction: metadata=None
# ---------------------------------------------------------------------------
def scenario_construction_metadata_none() -> None:
    raised = False
    try:
        SkillExecutionPlan(skills=(), tools=(), metadata=None)  # type: ignore[arg-type]
    except SkillExecutionPlanError:
        raised = True
    check(raised, "V5: metadata=None raises SkillExecutionPlanError")


# ---------------------------------------------------------------------------
# V6 -- construction: skills as generator
# ---------------------------------------------------------------------------
def scenario_construction_skills_generator() -> None:
    raised = False
    try:
        SkillExecutionPlan(skills=(x for x in "ab"), tools=(), metadata={})  # type: ignore[arg-type]
    except SkillExecutionPlanError:
        raised = True
    check(raised, "V6: skills=generator raises SkillExecutionPlanError")


# ---------------------------------------------------------------------------
# V7 -- construction: tools as set
# ---------------------------------------------------------------------------
def scenario_construction_tools_set() -> None:
    raised = False
    try:
        SkillExecutionPlan(skills=(), tools={"t1", "t2"}, metadata={})  # type: ignore[arg-type]
    except SkillExecutionPlanError:
        raised = True
    check(raised, "V7: tools=set raises SkillExecutionPlanError")


# ---------------------------------------------------------------------------
# V8 -- construction: empty tuples valid
# ---------------------------------------------------------------------------
def scenario_construction_empty_valid() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    check(plan.skills == (), "V8: empty skills=() is valid")
    check(plan.tools == (), "V8: empty tools=() is valid")
    check(dict(plan.metadata) == {}, "V8: empty metadata={} is valid")


# ---------------------------------------------------------------------------
# V9 -- immutability: reassignment raises FrozenInstanceError
# ---------------------------------------------------------------------------
def scenario_immutability() -> None:
    plan = SkillExecutionPlan(skills=("a",), tools=("t",), metadata={})
    for field_name, value in (
        ("skills", ("z",)),
        ("tools", ("z",)),
        ("metadata", {}),
    ):
        raised = False
        try:
            setattr(plan, field_name, value)
        except FrozenInstanceError:
            raised = True
        check(raised, f"V9: reassigning '{field_name}' raises FrozenInstanceError")


# ---------------------------------------------------------------------------
# V10 -- metadata freezing: MappingProxyType
# ---------------------------------------------------------------------------
def scenario_metadata_is_mapping_proxy() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={"a": 1})
    check(
        isinstance(plan.metadata, MappingProxyType),
        "V10: plan.metadata is a MappingProxyType instance",
    )


# ---------------------------------------------------------------------------
# V11 -- metadata freezing: original dict mutation has no effect
# ---------------------------------------------------------------------------
def scenario_metadata_independent_of_source() -> None:
    source = {"a": 1}
    plan = SkillExecutionPlan(skills=(), tools=(), metadata=source)
    source["a"] = 999
    source["b"] = 2
    check(
        dict(plan.metadata) == {"a": 1},
        "V11: mutating the original dict after construction does not affect plan.metadata",
    )


# ---------------------------------------------------------------------------
# V12 -- metadata freezing: item assignment raises TypeError
# ---------------------------------------------------------------------------
def scenario_metadata_item_assignment_raises() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={"a": 1})
    raised = False
    try:
        plan.metadata["a"] = 2  # type: ignore[index]
    except TypeError:
        raised = True
    check(raised, "V12: plan.metadata['a'] = 2 raises TypeError")


# ---------------------------------------------------------------------------
# V13 -- hash: matches hash(id(skills))
# ---------------------------------------------------------------------------
def scenario_hash_matches_id_of_skills() -> None:
    skills_tuple = ("a", "b")
    plan = SkillExecutionPlan(skills=skills_tuple, tools=(), metadata={})
    check(
        hash(plan) == hash(id(skills_tuple)),
        "V13: hash(plan) == hash(id(plan.skills))",
    )


# ---------------------------------------------------------------------------
# V14 -- hash: shared skills tuple object -> shared hash
# ---------------------------------------------------------------------------
def scenario_hash_shared_skills_identity() -> None:
    shared_skills = ("x", "y")
    plan_a = SkillExecutionPlan(skills=shared_skills, tools=("t1",), metadata={})
    plan_b = SkillExecutionPlan(skills=shared_skills, tools=("t2",), metadata={"m": 1})
    check(
        hash(plan_a) == hash(plan_b),
        "V14: two plans sharing the same skills tuple object share the same hash",
    )


# ---------------------------------------------------------------------------
# V15 -- hash: distinct (value-equal) skills tuples -> distinct hash
# ---------------------------------------------------------------------------
def scenario_hash_distinct_skills_identity() -> None:
    # Built via list() -> tuple() to defeat CPython's compile-time
    # constant-folding of identical tuple literals within one code
    # object, which would otherwise make two "equal" literal tuples
    # the very same object (same id()).
    skills_a = tuple(list(("x", "y")))
    skills_b = tuple(list(("x", "y")))
    plan_a = SkillExecutionPlan(skills=skills_a, tools=(), metadata={})
    plan_b = SkillExecutionPlan(skills=skills_b, tools=(), metadata={})
    check(
        hash(plan_a) != hash(plan_b),
        "V15: two plans with value-equal but distinct skills tuple objects hash differently",
    )


# ---------------------------------------------------------------------------
# V16 -- equality: identical tuple objects + equal metadata -> equal
# ---------------------------------------------------------------------------
def scenario_equality_identical_fields() -> None:
    shared_skills = ("x",)
    shared_tools = ("t",)
    plan_a = SkillExecutionPlan(skills=shared_skills, tools=shared_tools, metadata={"k": 1})
    plan_b = SkillExecutionPlan(skills=shared_skills, tools=shared_tools, metadata={"k": 1})
    check(plan_a == plan_b, "V16: plans with equal fields compare equal")


# ---------------------------------------------------------------------------
# V17 -- equality/hash contract: shared skills identity, differing tools
# ---------------------------------------------------------------------------
def scenario_equality_hash_contract() -> None:
    shared_skills = ("x",)
    plan_a = SkillExecutionPlan(skills=shared_skills, tools=("t1",), metadata={})
    plan_b = SkillExecutionPlan(skills=shared_skills, tools=("t2",), metadata={})
    check(plan_a != plan_b, "V17: differing tools -> not equal")
    check(
        hash(plan_a) == hash(plan_b),
        "V17: still share a hash despite not being equal (permitted by hash/eq contract)",
    )


# ---------------------------------------------------------------------------
# V18 -- tuple preservation: skills identity + order
# ---------------------------------------------------------------------------
def scenario_skills_identity_preserved() -> None:
    s1, s2 = _GuardedSkill("s1"), _GuardedSkill("s2")
    plan = SkillExecutionPlan(skills=(s1, s2), tools=(), metadata={})
    check(plan.skills[0] is s1, "V18: first skill preserved by identity")
    check(plan.skills[1] is s2, "V18: second skill preserved by identity")
    check(len(plan.skills) == 2, "V18: no skills dropped or added")


# ---------------------------------------------------------------------------
# V19 -- tuple preservation: tools verbatim with duplicates
# ---------------------------------------------------------------------------
def scenario_tools_duplicates_preserved() -> None:
    plan = SkillExecutionPlan(skills=(), tools=("dup", "other", "dup"), metadata={})
    check(
        plan.tools == ("dup", "other", "dup"),
        "V19: duplicate tool names preserved verbatim in order",
    )


# ---------------------------------------------------------------------------
# V20 -- order preservation: non-alphabetical input round-trips
# ---------------------------------------------------------------------------
def scenario_order_preservation() -> None:
    plan = SkillExecutionPlan(skills=("zeta", "alpha", "mu"), tools=(), metadata={})
    check(
        plan.skills == ("zeta", "alpha", "mu"),
        "V20: non-alphabetical skills order preserved exactly",
    )


# ---------------------------------------------------------------------------
# V21 -- exactly three dataclass fields
# ---------------------------------------------------------------------------
def scenario_exactly_three_fields() -> None:
    field_names = {f.name for f in fields(SkillExecutionPlan)}
    check(
        field_names == {"skills", "tools", "metadata"},
        f"V21: SkillExecutionPlan has exactly fields {{'skills', 'tools', 'metadata'}} (got {field_names})",
    )


# ---------------------------------------------------------------------------
# V22 -- only __post_init__ and __hash__ beyond dataclass machinery
# ---------------------------------------------------------------------------
def scenario_only_allowed_methods() -> None:
    dataclass_generated = {
        "__init__",
        "__repr__",
        "__eq__",
        "__hash__",
        "__setattr__",
        "__delattr__",
        "__dataclass_fields__",
        "__dataclass_params__",
        "__match_args__",
    }
    # Plain-class bookkeeping attributes every normal Python class
    # carries regardless of whether it is a dataclass (not "methods"
    # in any meaningful sense here) -- excluded from the check.
    class_bookkeeping = {
        "__module__",
        "__doc__",
        "__dict__",
        "__weakref__",
        "__annotations__",
    }
    extra = {
        name
        for name in SkillExecutionPlan.__dict__
        if name not in dataclass_generated
        and name not in class_bookkeeping
        and name != "__post_init__"
    }
    check(
        extra == set(),
        f"V22: no methods beyond __post_init__/__hash__/dataclass machinery (found extra: {extra})",
    )
    check(
        "__post_init__" in SkillExecutionPlan.__dict__,
        "V22: __post_init__ is defined",
    )
    check(
        "__hash__" in SkillExecutionPlan.__dict__,
        "V22: __hash__ is defined",
    )


# ---------------------------------------------------------------------------
# V23 -- SkillExecutionPlanError subclasses AgentError
# ---------------------------------------------------------------------------
def scenario_error_subclasses_agent_error() -> None:
    check(
        issubclass(SkillExecutionPlanError, AgentError),
        "V23: SkillExecutionPlanError subclasses Core.exceptions.AgentError",
    )


# ---------------------------------------------------------------------------
# V24/V25 -- metadata dict handling
# ---------------------------------------------------------------------------
def scenario_metadata_dict_handling() -> None:
    plan_empty = SkillExecutionPlan(skills=(), tools=(), metadata={})
    check(dict(plan_empty.metadata) == {}, "V24: empty dict metadata accepted and frozen")

    plan_populated = SkillExecutionPlan(skills=(), tools=(), metadata={"x": 1, "y": 2})
    check(
        dict(plan_populated.metadata) == {"x": 1, "y": 2},
        "V25: populated dict metadata copied and frozen correctly",
    )


# ---------------------------------------------------------------------------
# V26 -- id()-based hashing confirmed via distinct equal-value tuples
# ---------------------------------------------------------------------------
def scenario_id_based_hashing_confirmed() -> None:
    tuple_a = tuple(["same", "values"])
    tuple_b = tuple(["same", "values"])
    check(tuple_a == tuple_b, "V26: sanity -- the two tuples are value-equal")
    check(id(tuple_a) != id(tuple_b), "V26: sanity -- the two tuples are distinct objects")
    plan_a = SkillExecutionPlan(skills=tuple_a, tools=(), metadata={})
    plan_b = SkillExecutionPlan(skills=tuple_b, tools=(), metadata={})
    check(
        hash(plan_a) != hash(plan_b),
        "V26: value-equal but distinct skills tuples hash differently (id-based, not content-based)",
    )


# ---------------------------------------------------------------------------
# V27-V30 -- Planner: basic plan generation
# ---------------------------------------------------------------------------
def scenario_planner_basic_generation() -> None:
    planner, _cap_registry, _tool_registry = _full_planner(
        skill_map={"cap.demo": ("skill_one",)},
        tool_map={"skill_one": ("tool_a", "tool_b")},
    )
    goal = Goal(metadata={"capability": "cap.demo"})

    plan = planner.build_skill_execution_plan(goal)

    check(isinstance(plan, SkillExecutionPlan), "V27: build_skill_execution_plan returns a SkillExecutionPlan")
    check(plan.skills == planner.resolve_skills(goal), "V28: plan.skills matches resolve_skills(goal) exactly")
    check(plan.tools == planner.discover_tools(goal), "V29: plan.tools matches discover_tools(goal) exactly")
    check(dict(plan.metadata) == {}, "V30: plan.metadata is exactly empty")


# ---------------------------------------------------------------------------
# V31 -- Planner: skill order preserved (non-alphabetical)
# ---------------------------------------------------------------------------
def scenario_planner_order_preserved() -> None:
    planner, _cap_registry, _tool_registry = _full_planner(
        skill_map={"cap.order": ("skill_zeta", "skill_alpha")},
        tool_map={"skill_zeta": ("tz",), "skill_alpha": ("ta",)},
    )
    goal = Goal(metadata={"capability": "cap.order"})
    plan = planner.build_skill_execution_plan(goal)

    skill_names = tuple(s.name for s in plan.skills)
    check(
        skill_names == ("skill_zeta", "skill_alpha"),
        f"V31: skill order preserved exactly as registered (got {skill_names})",
    )


# ---------------------------------------------------------------------------
# V32 -- Planner: duplicate tool names preserved
# ---------------------------------------------------------------------------
def scenario_planner_duplicate_tools_preserved() -> None:
    planner, _cap_registry, _tool_registry = _full_planner(
        skill_map={"cap.dup": ("skill_a", "skill_b")},
        tool_map={"skill_a": ("shared_tool",), "skill_b": ("shared_tool",)},
    )
    goal = Goal(metadata={"capability": "cap.dup"})
    plan = planner.build_skill_execution_plan(goal)

    check(
        plan.tools == ("shared_tool", "shared_tool"),
        f"V32: duplicate tool names across skills preserved (got {plan.tools})",
    )


# ---------------------------------------------------------------------------
# V33 -- Planner: no collaborators attached -> empty plan
# ---------------------------------------------------------------------------
def scenario_planner_no_collaborators() -> None:
    planner = GoalPlanner(service_skills={})
    goal = Goal(metadata={"capability": "cap.anything"})
    plan = planner.build_skill_execution_plan(goal)

    check(plan.skills == (), "V33: skills is () with no collaborators attached")
    check(plan.tools == (), "V33: tools is () with no collaborators attached")
    check(dict(plan.metadata) == {}, "V33: metadata is {} with no collaborators attached")


# ---------------------------------------------------------------------------
# V34 -- Planner: never executes a resolved skill
# ---------------------------------------------------------------------------
def scenario_planner_never_executes() -> None:
    planner, _cap_registry, _tool_registry = _full_planner(
        skill_map={"cap.guard": ("skill_guarded",)},
        tool_map={"skill_guarded": ("tool_g",)},
    )
    goal = Goal(metadata={"capability": "cap.guard"})
    # _GuardedSkill raises AssertionError on .execute()/__call__ -- if
    # build_skill_execution_plan ever touched either, this call itself
    # would raise and fail the scenario.
    plan = planner.build_skill_execution_plan(goal)
    check(
        isinstance(plan, SkillExecutionPlan),
        "V34: build_skill_execution_plan completes without ever executing the guarded skill",
    )


# ---------------------------------------------------------------------------
# V35 -- Planner: never mutates the input Goal
# ---------------------------------------------------------------------------
def scenario_planner_never_mutates_goal() -> None:
    planner, _cap_registry, _tool_registry = _full_planner(
        skill_map={"cap.immutable_goal": ("skill_one",)},
        tool_map={"skill_one": ("tool_one",)},
    )
    goal = Goal(metadata={"capability": "cap.immutable_goal"})
    original_metadata = dict(goal.metadata)

    planner.build_skill_execution_plan(goal)

    check(
        dict(goal.metadata) == original_metadata,
        "V35: goal.metadata is unchanged after build_skill_execution_plan",
    )


# ---------------------------------------------------------------------------
# V36 -- Planner: no hidden caching of the returned SkillExecutionPlan
# ---------------------------------------------------------------------------
def scenario_planner_no_plan_caching() -> None:
    planner, _cap_registry, _tool_registry = _full_planner(
        skill_map={"cap.cache_check": ("skill_one",)},
        tool_map={"skill_one": ("tool_one",)},
    )
    goal = Goal(metadata={"capability": "cap.cache_check"})

    plan_first = planner.build_skill_execution_plan(goal)
    plan_second = planner.build_skill_execution_plan(goal)

    check(plan_first == plan_second, "V36: two calls with unchanged registry produce value-equal plans")
    check(
        plan_first is not plan_second,
        "V36: two calls with unchanged registry produce two distinct instances (no caching)",
    )


# ---------------------------------------------------------------------------
# V37 -- Planner: registry update between calls changes the second plan
# ---------------------------------------------------------------------------
def scenario_planner_reflects_registry_updates() -> None:
    planner, _cap_registry, tool_registry = _full_planner(
        skill_map={"cap.live": ("skill_live",)},
        tool_map={"skill_live": ("tool_v1",)},
    )
    goal = Goal(metadata={"capability": "cap.live"})

    plan_first = planner.build_skill_execution_plan(goal)
    tool_registry.unregister("skill_live")
    tool_registry.register("skill_live", ("tool_v2",))
    plan_second = planner.build_skill_execution_plan(goal)

    check(plan_first.tools == ("tool_v1",), "V37: first plan reflects the initial registration")
    check(
        plan_second.tools == ("tool_v2",),
        "V37: second plan reflects the updated registration -- no stale cache",
    )


# ---------------------------------------------------------------------------
# V38 -- exception propagation: SkillResolver-level exception
# ---------------------------------------------------------------------------
def scenario_planner_resolver_exception_propagates() -> None:
    manager, capability_skill_registry = _make_capability_manager()
    capability_skill_registry.register("cap.missing_skill", ("skill_ghost",))
    stub = _StubSkillResolver({})  # skill_ghost is not registered here
    tool_registry = SkillToolRegistry()

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )

    raised_type = None
    try:
        planner.build_skill_execution_plan(Goal(metadata={"capability": "cap.missing_skill"}))
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is SkillResolverError,
        f"V38: an unresolvable skill name propagates unchanged as SkillResolverError (got {raised_type})",
    )


# ---------------------------------------------------------------------------
# V39 -- exception propagation: SkillToolRegistry miss
# ---------------------------------------------------------------------------
def scenario_planner_registry_miss_propagates() -> None:
    manager, capability_skill_registry = _make_capability_manager()
    capability_skill_registry.register("cap.no_tools", ("skill_no_tools",))
    stub = _StubSkillResolver({"skill_no_tools": _GuardedSkill("skill_no_tools")})
    empty_tool_registry = SkillToolRegistry()  # skill_no_tools never registered

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=empty_tool_registry,
    )

    raised_type = None
    try:
        planner.build_skill_execution_plan(Goal(metadata={"capability": "cap.no_tools"}))
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is SkillToolRegistryError,
        f"V39: a SkillToolRegistry miss propagates unchanged as SkillToolRegistryError (got {raised_type})",
    )


# ---------------------------------------------------------------------------
# V40 -- AST import verification: Orchestration.planner
# ---------------------------------------------------------------------------
def scenario_ast_import_verification_planner() -> None:
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
        "Orchestration.skill_execution_plan" in imported_modules,
        "V40: Orchestration.planner imports Orchestration.skill_execution_plan",
    )

    forbidden_modules = {
        "Orchestration.tool_registry",
        "Orchestration.tool_resolver",
        "Orchestration.tool_manager",
        "Orchestration.executor",
        "Orchestration.runtime",
        "Orchestration.memory",
        "Orchestration.reflection",
        "Orchestration.learning_loop",
        "Orchestration.workflow_engine",
        "Orchestration.workflow_execution_coordinator",
        "Orchestration.autonomous_host",
        "Orchestration.autonomous_scheduler",
        "Orchestration.event_bus",
        "Orchestration.base_skill",
        "Orchestration.base_tool",
    }
    intersection = imported_modules & forbidden_modules
    check(
        not intersection,
        f"V40: Orchestration.planner introduces no forbidden import (found: {intersection})",
    )


# ---------------------------------------------------------------------------
# V41 -- AST import verification: Orchestration.skill_execution_plan
# ---------------------------------------------------------------------------
def scenario_ast_import_verification_value_object() -> None:
    source_path = ROOT / "Orchestration" / "skill_execution_plan.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)

    allowed_modules = {
        "__future__",
        "dataclasses",
        "types",
        "typing",
        "Core.exceptions",
    }
    disallowed = imported_modules - allowed_modules
    check(
        not disallowed,
        f"V41: Orchestration.skill_execution_plan imports only the allowed dependency set (found extra: {disallowed})",
    )
    check(
        "Core.exceptions" in imported_modules,
        "V41: Orchestration.skill_execution_plan imports Core.exceptions",
    )


# ---------------------------------------------------------------------------
# V42 -- namespace verification: Orchestration.planner
# ---------------------------------------------------------------------------
def scenario_namespace_verification_planner() -> None:
    import Orchestration.planner as planner_module

    forbidden = [
        "ToolResolver",
        "ToolManager",
        "Executor",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "AutonomousHost",
        "AutonomousScheduler",
        "EventBus",
        "BaseSkill",
        "BaseTool",
    ]
    for name in forbidden:
        check(
            not hasattr(planner_module, name),
            f"V42: Orchestration.planner module namespace does not expose '{name}'",
        )


# ---------------------------------------------------------------------------
# V43 -- namespace verification: Orchestration.skill_execution_plan
# ---------------------------------------------------------------------------
def scenario_namespace_verification_value_object() -> None:
    import Orchestration.skill_execution_plan as sep_module

    forbidden = [
        "Executor",
        "Runtime",
        "Workflow",
        "EventBus",
        "BaseSkill",
        "BaseTool",
    ]
    for name in forbidden:
        check(
            not hasattr(sep_module, name),
            f"V43: Orchestration.skill_execution_plan module namespace does not expose '{name}'",
        )


# ---------------------------------------------------------------------------
# V44 -- multi-instance independence
# ---------------------------------------------------------------------------
def scenario_multi_instance_independence() -> None:
    planner_a, _cap_a, tool_registry_a = _full_planner(
        skill_map={"cap.shared": ("skill_shared",)},
        tool_map={"skill_shared": ("tool_from_a",)},
    )
    planner_b, _cap_b, tool_registry_b = _full_planner(
        skill_map={"cap.shared": ("skill_shared",)},
        tool_map={"skill_shared": ("tool_from_b",)},
    )

    plan_a = planner_a.build_skill_execution_plan(Goal(metadata={"capability": "cap.shared"}))
    plan_b = planner_b.build_skill_execution_plan(Goal(metadata={"capability": "cap.shared"}))

    check(plan_a.tools == ("tool_from_a",), "V44: planner_a builds a plan only from its own collaborators")
    check(plan_b.tools == ("tool_from_b",), "V44: planner_b builds a plan only from its own collaborators")


# ---------------------------------------------------------------------------
# V45 -- pre-existing Planner surface unaffected
# ---------------------------------------------------------------------------
def scenario_pre_existing_surface_unaffected() -> None:
    planner = GoalPlanner(service_skills={})
    goal = Goal(metadata={"x": 1})

    plan_result = planner.build_plan(goal)
    check(plan_result.goal is goal, "V45: build_plan still works and returns an ExecutionPlan wrapping goal")
    check(planner.resolve_skills(goal) == (), "V45: resolve_skills still works unaffected")
    check(planner.discover_tools(goal) == (), "V45: discover_tools still works unaffected")
    check(planner.resolve_capabilities(goal) == (), "V45: resolve_capabilities still works unaffected")
    check(planner.recall(goal) == (), "V45: recall still works unaffected")


# ---------------------------------------------------------------------------
# V46 -- public API exactness
# ---------------------------------------------------------------------------
def scenario_public_api_exactness() -> None:
    expected_public_methods = {
        "recall",
        "resolve_capabilities",
        "resolve_skills",
        "discover_tools",
        "build_skill_execution_plan",
        "build_plan",
        "execute_plan",
        "translate_metadata",
        "accumulate_context",
        "build_workflow",
    }
    actual_public_methods = {
        name
        for name in vars(GoalPlanner)
        if not name.startswith("_") and callable(getattr(GoalPlanner, name))
    }
    check(
        actual_public_methods == expected_public_methods,
        f"V46: GoalPlanner exposes exactly the expected public methods (got {actual_public_methods})",
    )


def main() -> int:
    scenarios = [
        scenario_construction_valid,
        scenario_construction_skills_not_tuple,
        scenario_construction_tools_not_tuple,
        scenario_construction_metadata_not_mapping,
        scenario_construction_metadata_none,
        scenario_construction_skills_generator,
        scenario_construction_tools_set,
        scenario_construction_empty_valid,
        scenario_immutability,
        scenario_metadata_is_mapping_proxy,
        scenario_metadata_independent_of_source,
        scenario_metadata_item_assignment_raises,
        scenario_hash_matches_id_of_skills,
        scenario_hash_shared_skills_identity,
        scenario_hash_distinct_skills_identity,
        scenario_equality_identical_fields,
        scenario_equality_hash_contract,
        scenario_skills_identity_preserved,
        scenario_tools_duplicates_preserved,
        scenario_order_preservation,
        scenario_exactly_three_fields,
        scenario_only_allowed_methods,
        scenario_error_subclasses_agent_error,
        scenario_metadata_dict_handling,
        scenario_id_based_hashing_confirmed,
        scenario_planner_basic_generation,
        scenario_planner_order_preserved,
        scenario_planner_duplicate_tools_preserved,
        scenario_planner_no_collaborators,
        scenario_planner_never_executes,
        scenario_planner_never_mutates_goal,
        scenario_planner_no_plan_caching,
        scenario_planner_reflects_registry_updates,
        scenario_planner_resolver_exception_propagates,
        scenario_planner_registry_miss_propagates,
        scenario_ast_import_verification_planner,
        scenario_ast_import_verification_value_object,
        scenario_namespace_verification_planner,
        scenario_namespace_verification_value_object,
        scenario_multi_instance_independence,
        scenario_pre_existing_surface_unaffected,
        scenario_public_api_exactness,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 6 SPRINT 71 SKILL-EXECUTION-PLAN RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)

    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())