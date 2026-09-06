"""
Phase 5 Sprint 70 proof suite -- ``GoalPlanner`` gains the capability
to discover which Tool names belong to a ``Goal``'s resolved Skills,
completing the discovery pipeline

    Goal -> Capability -> Skill Objects -> Tool Names

Scope: dedicated regression suite for the Sprint 70 addition only --
``Orchestration.planner.GoalPlanner``'s new optional
``skill_tool_registry`` constructor argument, plus its single new
public method, ``discover_tools(goal)``. This is still discovery
only: no Skill is ever executed, no ``.execute()`` is ever called, no
Tool is ever resolved or executed, and no ``Task`` is ever created.
``build_plan``/``execute_plan``/``translate_metadata``/
``accumulate_context``/``build_workflow``/``recall``/
``resolve_capabilities``/``resolve_skills`` are all unchanged by this
sprint -- this suite does not re-verify their own internal behavior
beyond confirming Sprint 70 introduces no regression to them.

``GoalPlanner`` never resolves Tool objects, never touches
``ToolRegistry``, ``ToolResolver``, or ``ToolManager``, never executes
Skills or Tools, never calls ``Executor`` or ``Runtime``, never
creates a ``Task``, never publishes events, and never uses ``Memory``,
``Reflection``, or ``LearningLoop`` from within ``discover_tools``
(proven both by direct behavioral tests and by AST-level import
inspection of the module's own source file). ``discover_tools`` reads
only ``skill.name`` on each resolved skill object -- never
``description``, ``metadata``, ``capabilities``, methods, or
``execute``. ``Orchestration.planner`` adds exactly one new import
for this sprint: ``Orchestration.skill_tool_registry.SkillToolRegistry``.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x/L6x proof suites (mirroring
``Tests.test_stage_l69_planner_skill_resolution`` in particular): a
global pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage (target 35+):
    V1  -- constructor: skill_tool_registry omitted (default None)
           constructs successfully; discover_tools() returns ().
    V2  -- constructor: skill_tool_registry=None explicitly constructs
           successfully; discover_tools() returns ().
    V3  -- constructor: a valid SkillToolRegistry instance constructs
           successfully.
    V4  -- constructor: every invalid, non-SkillToolRegistry value
           (not None) raises GoalPlannerError.
    V5  -- identity preservation: the exact SkillToolRegistry instance
           passed in is the one delegated to.
    V6  -- discover_tools: no skill_resolver attached (only
           capability_manager + skill_tool_registry) returns ().
    V7  -- discover_tools: no skill_tool_registry attached (only
           capability_manager + skill_resolver) returns ().
    V8  -- discover_tools: no resolved skills (goal.metadata missing
           "capability") returns ().
    V9  -- discover_tools: single resolved skill -> correct tool
           tuple, registry queried once with that skill's name.
    V10 -- discover_tools: multiple resolved skills -> merged tuple in
           resolved-skill order.
    V11 -- discover_tools: skill order (non-alphabetical) and each
           skill's own tool order are both preserved.
    V12 -- discover_tools: duplicate tool names across two different
           skills are preserved (no cross-skill dedup).
    V13 -- discover_tools: no sorting -- tool order follows registry
           registration order, not alphabetical order.
    V14 -- discover_tools: no normalization -- an exact-case,
           exact-whitespace skill name and tool name both round-trip
           unmodified (no trim/lowercase).
    V15 -- Planner behavior: discover_tools only ever reads
           skill.name -- never .description or .metadata.
    V16 -- Planner behavior: discover_tools never calls .execute() or
           otherwise invokes a resolved skill object.
    V17 -- no Tool resolution: the returned tuple's elements are all
           plain str (never a Tool object).
    V18 -- SkillToolRegistry.get is called with the exact resolved
           skill.name string, once per resolved skill.
    V19 -- exception propagation: a registry miss (SkillToolRegistryError)
           propagates unchanged through discover_tools, not wrapped as
           GoalPlannerError.
    V20 -- exception propagation: a SkillResolver-level exception
           propagates unchanged through discover_tools.
    V21 -- exception propagation: a CapabilityManager-level exception
           (unknown capability) propagates unchanged through
           discover_tools.
    V22 -- AST import verification: Orchestration.planner's only new
           import for this sprint is
           Orchestration.skill_tool_registry.SkillToolRegistry; no
           forbidden import is introduced.
    V23 -- namespace verification: GoalPlanner's module namespace
           contains no ToolResolver/ToolManager/Executor/
           WorkflowEngine/WorkflowExecutionCoordinator/
           AutonomousHost/AutonomousScheduler/EventBus symbol.
    V24 -- multi-instance independence: two GoalPlanner instances,
           each with its own SkillToolRegistry/SkillResolver pair,
           never cross-resolve into each other's tools.
    V25 -- no hidden state: a GoalPlanner instance's new attribute is
           exactly '_skill_tool_registry' -- no cache, no registry
           snapshot of its own.
    V26 -- no caching: two discover_tools() calls for the same goal,
           after the underlying SkillToolRegistry changes, each
           re-delegate (no memoized result masking a registry change).
    V27 -- no registry creation: discover_tools never constructs a
           SkillToolRegistry instance of its own.
    V28 -- pre-existing surface unaffected: build_plan/execute_plan
           behave identically whether or not skill_tool_registry is
           attached.
    V29 -- resolve_skills/resolve_capabilities unaffected: both still
           return identical results whether or not skill_tool_registry
           is also attached.
    V30 -- exception convention: GoalPlannerError remains a subclass
           of Core.exceptions.AgentError.
    V31 -- constructor rejects a bare SkillRegistry/CapabilityManager/
           SkillResolver (not a SkillToolRegistry) with
           GoalPlannerError.
    V32 -- combination: skill_tool_registry alongside memory,
           capability_manager, and skill_resolver -- each collaborator
           works independently through its own method.
    V33 -- public API exactness: exactly one new public method exists
           on GoalPlanner beyond the Sprint 69 surface -- discover_tools.
    V34 -- discover_tools reads goal only through resolve_skills -- a
           goal whose metadata has extra unrelated keys still
           discovers correctly and those keys are never consulted.
    V35 -- no Task creation: discover_tools never constructs a
           Orchestration.task.Task instance.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List, Tuple

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
from Orchestration.skill_tool_registry import SkillToolRegistry, SkillToolRegistryError
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


class _RecordingSkillToolRegistry(SkillToolRegistry):
    """A real SkillToolRegistry that also records every ``get()``
    call it receives, so tests can observe call count/order/args
    without needing to reimplement the catalog."""

    def __init__(self):
        super().__init__()
        self.calls: List[str] = []

    def get(self, skill_name):  # type: ignore[override]
        self.calls.append(skill_name)
        return super().get(skill_name)


class _GuardedSkill:
    """A skill stand-in that tolerates only ``.name`` access -- any
    other attribute access or invocation is a hard failure, proving
    ``discover_tools`` reads nothing else off a resolved skill."""

    def __init__(self, name):
        self._name = name

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        raise AssertionError("discover_tools must never access .description")

    @property
    def metadata(self):
        raise AssertionError("discover_tools must never access .metadata")

    def execute(self, *args, **kwargs):
        raise AssertionError("discover_tools must never call .execute()")

    def __call__(self, *args, **kwargs):
        raise AssertionError("discover_tools must never call a skill object")


# ---------------------------------------------------------------------------
# V1 -- constructor: skill_tool_registry omitted
# ---------------------------------------------------------------------------
def scenario_constructor_omitted() -> None:
    planner = GoalPlanner(service_skills={})
    check(
        isinstance(planner, GoalPlanner),
        "V1: GoalPlanner(service_skills={}) with skill_tool_registry omitted constructs successfully",
    )
    check(
        planner.discover_tools(Goal(metadata={"capability": "x"})) == (),
        "V1: discover_tools() returns () when skill_tool_registry was never supplied",
    )


# ---------------------------------------------------------------------------
# V2 -- constructor: skill_tool_registry=None explicitly
# ---------------------------------------------------------------------------
def scenario_constructor_explicit_none() -> None:
    planner = GoalPlanner(service_skills={}, skill_tool_registry=None)
    check(
        isinstance(planner, GoalPlanner),
        "V2: GoalPlanner(service_skills={}, skill_tool_registry=None) constructs successfully",
    )
    check(
        planner.discover_tools(Goal(metadata={"capability": "x"})) == (),
        "V2: discover_tools() returns () when skill_tool_registry=None explicitly",
    )


# ---------------------------------------------------------------------------
# V3 -- constructor: a valid SkillToolRegistry instance
# ---------------------------------------------------------------------------
def scenario_constructor_valid_registry() -> None:
    registry = SkillToolRegistry()
    planner = GoalPlanner(service_skills={}, skill_tool_registry=registry)
    check(
        isinstance(planner, GoalPlanner),
        "V3: GoalPlanner(skill_tool_registry=<SkillToolRegistry>) constructs successfully",
    )


# ---------------------------------------------------------------------------
# V4 -- constructor: invalid skill_tool_registry values
# ---------------------------------------------------------------------------
def scenario_constructor_invalid_registry() -> None:
    manager, _skill_registry = _make_capability_manager()
    stub_resolver = _StubSkillResolver({})

    invalid_values = [
        object(),
        "not-a-registry",
        123,
        [],
        {},
        SkillRegistry(),
        manager,
        stub_resolver,
    ]
    for value in invalid_values:
        raised = False
        try:
            GoalPlanner(service_skills={}, skill_tool_registry=value)  # type: ignore[arg-type]
        except GoalPlannerError:
            raised = True
        check(
            raised,
            f"V4: GoalPlanner(skill_tool_registry={type(value).__name__} instance) raises GoalPlannerError",
        )


# ---------------------------------------------------------------------------
# V5 -- identity preservation
# ---------------------------------------------------------------------------
def scenario_identity_preservation() -> None:
    registry = SkillToolRegistry()
    planner = GoalPlanner(service_skills={}, skill_tool_registry=registry)
    check(
        planner._skill_tool_registry is registry,
        "V5: the exact SkillToolRegistry instance passed in is the one stored/delegated to",
    )


# ---------------------------------------------------------------------------
# V6 -- no skill_resolver attached
# ---------------------------------------------------------------------------
def scenario_no_skill_resolver() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.a", ("skill_a",))

    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_a", ("tool1",))

    planner = GoalPlanner(
        service_skills={}, capability_manager=manager, skill_tool_registry=tool_registry
    )
    result = planner.discover_tools(Goal(metadata={"capability": "cap.a"}))
    check(result == (), "V6: discover_tools() returns () when no skill_resolver is attached")


# ---------------------------------------------------------------------------
# V7 -- no skill_tool_registry attached
# ---------------------------------------------------------------------------
def scenario_no_skill_tool_registry() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.b", ("skill_b",))

    stub = _StubSkillResolver({"skill_b": _GuardedSkill("skill_b")})
    planner = GoalPlanner(service_skills={}, capability_manager=manager, skill_resolver=stub)

    result = planner.discover_tools(Goal(metadata={"capability": "cap.b"}))
    check(result == (), "V7: discover_tools() returns () when no skill_tool_registry is attached")


# ---------------------------------------------------------------------------
# V8 -- no resolved skills
# ---------------------------------------------------------------------------
def scenario_no_resolved_skills() -> None:
    manager, _skill_registry = _make_capability_manager()
    stub = _StubSkillResolver({})
    tool_registry = SkillToolRegistry()

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )
    result = planner.discover_tools(Goal(metadata={}))  # no "capability" key
    check(result == (), "V8: discover_tools() returns () when resolve_skills() itself returns ()")
    check(stub.calls == [], "V8: SkillResolver.resolve is never called when no capability is declared")


# ---------------------------------------------------------------------------
# V9 -- single resolved skill
# ---------------------------------------------------------------------------
def scenario_single_skill() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.single", ("skill_solo",))

    skill_obj = _GuardedSkill("skill_solo")
    stub = _StubSkillResolver({"skill_solo": skill_obj})

    tool_registry = _RecordingSkillToolRegistry()
    tool_registry.register("skill_solo", ("tool_a", "tool_b"))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )
    result = planner.discover_tools(Goal(metadata={"capability": "cap.single"}))
    check(result == ("tool_a", "tool_b"), "V9: single resolved skill yields its exact tool tuple")
    check(tool_registry.calls == ["skill_solo"], "V9: SkillToolRegistry.get was called exactly once, with the skill's name")


# ---------------------------------------------------------------------------
# V10 -- multiple resolved skills, merged
# ---------------------------------------------------------------------------
def scenario_multiple_skills_merge() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.multi", ("skill_x", "skill_y"))

    stub = _StubSkillResolver(
        {"skill_x": _GuardedSkill("skill_x"), "skill_y": _GuardedSkill("skill_y")}
    )
    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_x", ("t1", "t2"))
    tool_registry.register("skill_y", ("t3",))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )
    result = planner.discover_tools(Goal(metadata={"capability": "cap.multi"}))
    check(result == ("t1", "t2", "t3"), "V10: multiple resolved skills merge into one ordered tuple")


# ---------------------------------------------------------------------------
# V11 -- skill order and per-skill tool order both preserved
# ---------------------------------------------------------------------------
def scenario_order_preserved() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.order", ("skill_z", "skill_a"))

    stub = _StubSkillResolver(
        {"skill_z": _GuardedSkill("skill_z"), "skill_a": _GuardedSkill("skill_a")}
    )
    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_z", ("tz1",))
    tool_registry.register("skill_a", ("ta1", "ta2"))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )
    result = planner.discover_tools(Goal(metadata={"capability": "cap.order"}))
    check(
        result == ("tz1", "ta1", "ta2"),
        "V11: result follows the resolved (non-alphabetical) skill order, and each skill's own tool order",
    )


# ---------------------------------------------------------------------------
# V12 -- duplicate tool names across different skills preserved
# ---------------------------------------------------------------------------
def scenario_duplicate_tool_names_preserved() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.dup", ("skill_p", "skill_q"))

    stub = _StubSkillResolver(
        {"skill_p": _GuardedSkill("skill_p"), "skill_q": _GuardedSkill("skill_q")}
    )
    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_p", ("shared_tool",))
    tool_registry.register("skill_q", ("shared_tool",))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )
    result = planner.discover_tools(Goal(metadata={"capability": "cap.dup"}))
    check(
        result == ("shared_tool", "shared_tool"),
        "V12: a tool name shared by two different skills appears twice -- no cross-skill dedup",
    )


# ---------------------------------------------------------------------------
# V13 -- no sorting
# ---------------------------------------------------------------------------
def scenario_no_sorting() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.letters", ("skill_letters",))

    stub = _StubSkillResolver({"skill_letters": _GuardedSkill("skill_letters")})
    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_letters", ("zeta", "alpha", "mu"))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )
    result = planner.discover_tools(Goal(metadata={"capability": "cap.letters"}))
    check(
        result == ("zeta", "alpha", "mu"),
        "V13: result is not sorted -- follows registry registration order, not alphabetical order",
    )


# ---------------------------------------------------------------------------
# V14 -- no normalization
# ---------------------------------------------------------------------------
def scenario_no_normalization() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("Cap.Weird", ("Skill.Weird ",))

    stub = _StubSkillResolver({"Skill.Weird ": _GuardedSkill("Skill.Weird ")})
    tool_registry = _RecordingSkillToolRegistry()
    tool_registry.register("Skill.Weird ", ("Tool.Weird ",))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )
    result = planner.discover_tools(Goal(metadata={"capability": "Cap.Weird"}))
    check(result == ("Tool.Weird ",), "V14: an exact-case, exact-whitespace tool name round-trips unmodified")
    check(
        tool_registry.calls == ["Skill.Weird "],
        "V14: SkillToolRegistry.get received the skill name completely unmodified (no trim/lowercase)",
    )


# ---------------------------------------------------------------------------
# V15 -- only .name is ever read on a resolved skill
# ---------------------------------------------------------------------------
def scenario_only_name_accessed() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.guard", ("skill_guard",))

    guarded = _GuardedSkill("skill_guard")
    stub = _StubSkillResolver({"skill_guard": guarded})
    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_guard", ("g_tool",))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )

    exploded = False
    result = None
    try:
        result = planner.discover_tools(Goal(metadata={"capability": "cap.guard"}))
    except AssertionError:
        exploded = True

    check(not exploded, "V15: discover_tools() never accesses skill.description or skill.metadata")
    check(result == ("g_tool",), "V15: discover_tools() still returns the correct tools, reading only skill.name")


# ---------------------------------------------------------------------------
# V16 -- never calls/executes a resolved skill
# ---------------------------------------------------------------------------
def scenario_never_executes_skill() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.exec_guard", ("skill_exec_guard",))

    guarded = _GuardedSkill("skill_exec_guard")
    stub = _StubSkillResolver({"skill_exec_guard": guarded})
    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_exec_guard", ("eg_tool",))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )

    exploded = False
    try:
        planner.discover_tools(Goal(metadata={"capability": "cap.exec_guard"}))
    except AssertionError:
        exploded = True

    check(not exploded, "V16: discover_tools() never calls .execute() or otherwise invokes a resolved skill")


# ---------------------------------------------------------------------------
# V17 -- no Tool resolution -- result elements are plain str
# ---------------------------------------------------------------------------
def scenario_result_is_tuple_of_str() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.strcheck", ("skill_strcheck",))

    stub = _StubSkillResolver({"skill_strcheck": _GuardedSkill("skill_strcheck")})
    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_strcheck", ("tool_one", "tool_two"))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )
    result = planner.discover_tools(Goal(metadata={"capability": "cap.strcheck"}))
    check(isinstance(result, tuple), "V17: discover_tools() returns a tuple")
    check(
        all(isinstance(item, str) for item in result),
        "V17: every element of the result is a plain str -- never a resolved Tool object",
    )


# ---------------------------------------------------------------------------
# V18 -- SkillToolRegistry.get called with exact resolved skill name
# ---------------------------------------------------------------------------
def scenario_registry_called_with_skill_name() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.callcheck", ("skill_call_a", "skill_call_b"))

    stub = _StubSkillResolver(
        {"skill_call_a": _GuardedSkill("skill_call_a"), "skill_call_b": _GuardedSkill("skill_call_b")}
    )
    tool_registry = _RecordingSkillToolRegistry()
    tool_registry.register("skill_call_a", ("a1",))
    tool_registry.register("skill_call_b", ("b1",))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )
    planner.discover_tools(Goal(metadata={"capability": "cap.callcheck"}))
    check(
        tool_registry.calls == ["skill_call_a", "skill_call_b"],
        "V18: SkillToolRegistry.get was called once per resolved skill, in resolved order, with each skill's exact name",
    )


# ---------------------------------------------------------------------------
# V19 -- registry miss propagates unchanged
# ---------------------------------------------------------------------------
def scenario_registry_miss_propagates() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.missing_tool", ("skill_no_tools",))

    stub = _StubSkillResolver({"skill_no_tools": _GuardedSkill("skill_no_tools")})
    tool_registry = SkillToolRegistry()  # deliberately empty -- lookup will miss

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )

    raised_type = None
    try:
        planner.discover_tools(Goal(metadata={"capability": "cap.missing_tool"}))
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is SkillToolRegistryError,
        f"V19: a registry miss propagates unchanged as SkillToolRegistryError (got {raised_type})",
    )
    check(
        not (isinstance(raised_type, type) and issubclass(raised_type, GoalPlannerError)),
        "V19: the propagated exception is NOT wrapped as GoalPlannerError",
    )


# ---------------------------------------------------------------------------
# V20 -- SkillResolver-level exception propagates unchanged
# ---------------------------------------------------------------------------
def scenario_resolver_exception_propagates() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.resolver_fail", ("skill_unresolvable",))

    stub = _StubSkillResolver({})  # deliberately empty -- lookup will miss
    tool_registry = SkillToolRegistry()

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )

    raised_type = None
    try:
        planner.discover_tools(Goal(metadata={"capability": "cap.resolver_fail"}))
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is SkillResolverError,
        f"V20: an unresolvable skill name propagates unchanged as SkillResolverError (got {raised_type})",
    )


# ---------------------------------------------------------------------------
# V21 -- CapabilityManager-level exception propagates unchanged
# ---------------------------------------------------------------------------
def scenario_capability_exception_propagates() -> None:
    manager, _skill_registry = _make_capability_manager()
    stub = _StubSkillResolver({})
    tool_registry = SkillToolRegistry()

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )

    raised_type = None
    try:
        planner.discover_tools(Goal(metadata={"capability": "cap.totally_unknown"}))
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is CapabilitySkillRegistryError,
        f"V21: an unknown capability propagates unchanged as CapabilitySkillRegistryError (got {raised_type})",
    )
    check(stub.calls == [], "V21: SkillResolver.resolve is never reached once capability resolution itself fails")


# ---------------------------------------------------------------------------
# V22 -- AST import verification
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
        "Orchestration.skill_tool_registry" in imported_modules,
        "V22: Orchestration.planner imports Orchestration.skill_tool_registry",
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
    }
    intersection = imported_modules & forbidden_modules
    check(
        not intersection,
        f"V22: Orchestration.planner introduces no forbidden import (found: {intersection})",
    )


# ---------------------------------------------------------------------------
# V23 -- no forbidden namespace symbols
# ---------------------------------------------------------------------------
def scenario_no_forbidden_namespace_symbols() -> None:
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
    ]
    for name in forbidden:
        check(
            not hasattr(planner_module, name),
            f"V23: Orchestration.planner module namespace does not expose '{name}'",
        )


# ---------------------------------------------------------------------------
# V24 -- multi-instance independence
# ---------------------------------------------------------------------------
def scenario_multi_instance_independence() -> None:
    manager_a, skill_registry_a = _make_capability_manager()
    manager_b, skill_registry_b = _make_capability_manager()

    skill_registry_a.register("cap.shared", ("skill_shared",))
    skill_registry_b.register("cap.shared", ("skill_shared",))

    stub_a = _StubSkillResolver({"skill_shared": _GuardedSkill("skill_shared")})
    stub_b = _StubSkillResolver({"skill_shared": _GuardedSkill("skill_shared")})

    tool_registry_a = SkillToolRegistry()
    tool_registry_a.register("skill_shared", ("tool_from_a",))
    tool_registry_b = SkillToolRegistry()
    tool_registry_b.register("skill_shared", ("tool_from_b",))

    planner_a = GoalPlanner(
        service_skills={},
        capability_manager=manager_a,
        skill_resolver=stub_a,
        skill_tool_registry=tool_registry_a,
    )
    planner_b = GoalPlanner(
        service_skills={},
        capability_manager=manager_b,
        skill_resolver=stub_b,
        skill_tool_registry=tool_registry_b,
    )

    result_a = planner_a.discover_tools(Goal(metadata={"capability": "cap.shared"}))
    result_b = planner_b.discover_tools(Goal(metadata={"capability": "cap.shared"}))

    check(result_a == ("tool_from_a",), "V24: planner_a discovers only from its own SkillToolRegistry")
    check(result_b == ("tool_from_b",), "V24: planner_b discovers only from its own SkillToolRegistry")


# ---------------------------------------------------------------------------
# V25 -- no hidden state
# ---------------------------------------------------------------------------
def scenario_no_hidden_state() -> None:
    registry = SkillToolRegistry()
    planner = GoalPlanner(service_skills={}, skill_tool_registry=registry)
    check(
        hasattr(planner, "_skill_tool_registry"),
        "V25: GoalPlanner instance holds a '_skill_tool_registry' attribute",
    )
    check(
        planner._skill_tool_registry is registry,
        "V25: '_skill_tool_registry' holds the exact injected instance by identity",
    )


# ---------------------------------------------------------------------------
# V26 -- no caching
# ---------------------------------------------------------------------------
def scenario_no_caching() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.mutable_skill", ("skill_mutable",))

    stub = _StubSkillResolver({"skill_mutable": _GuardedSkill("skill_mutable")})
    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_mutable", ("tool_v1",))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )

    goal = Goal(metadata={"capability": "cap.mutable_skill"})
    first = planner.discover_tools(goal)

    tool_registry.unregister("skill_mutable")
    tool_registry.register("skill_mutable", ("tool_v2",))

    second = planner.discover_tools(goal)

    check(first == ("tool_v1",), "V26: first discover_tools() call reflects the initial registration")
    check(
        second == ("tool_v2",),
        "V26: second discover_tools() call reflects the updated registration -- no cached/stale result",
    )


# ---------------------------------------------------------------------------
# V27 -- no registry creation
# ---------------------------------------------------------------------------
def scenario_no_registry_creation() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.no_new_registry", ("skill_no_new_registry",))

    stub = _StubSkillResolver({"skill_no_new_registry": _GuardedSkill("skill_no_new_registry")})
    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_no_new_registry", ("nn_tool",))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )

    original_init = SkillToolRegistry.__init__
    call_count = {"n": 0}

    def counting_init(self, *args, **kwargs):
        call_count["n"] += 1
        return original_init(self, *args, **kwargs)

    SkillToolRegistry.__init__ = counting_init  # type: ignore[method-assign]
    try:
        planner.discover_tools(Goal(metadata={"capability": "cap.no_new_registry"}))
    finally:
        SkillToolRegistry.__init__ = original_init  # type: ignore[method-assign]

    check(call_count["n"] == 0, "V27: discover_tools() never constructs a SkillToolRegistry instance of its own")


# ---------------------------------------------------------------------------
# V28 -- pre-existing surface unaffected
# ---------------------------------------------------------------------------
def scenario_pre_existing_surface_unaffected() -> None:
    tool_registry = SkillToolRegistry()

    planner_without = GoalPlanner(service_skills={})
    planner_with = GoalPlanner(service_skills={}, skill_tool_registry=tool_registry)

    goal = Goal(metadata={"ticker": "BBCA"})
    plan_without = planner_without.build_plan(goal)
    plan_with = planner_with.build_plan(goal)

    check(
        plan_without.steps == plan_with.steps,
        "V28: build_plan() output is identical whether or not skill_tool_registry is attached",
    )

    results_without = planner_without.execute_plan(plan_without)
    results_with = planner_with.execute_plan(plan_with)
    check(
        results_without == results_with == [],
        "V28: execute_plan() output is identical (both empty) whether or not skill_tool_registry is attached",
    )


# ---------------------------------------------------------------------------
# V29 -- resolve_skills/resolve_capabilities unaffected
# ---------------------------------------------------------------------------
def scenario_resolve_methods_unaffected() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.check", ("skill_check_a", "skill_check_b"))

    skill_a = _GuardedSkill("skill_check_a")
    skill_b = _GuardedSkill("skill_check_b")
    stub = _StubSkillResolver({"skill_check_a": skill_a, "skill_check_b": skill_b})

    planner_without_registry = GoalPlanner(
        service_skills={}, capability_manager=manager, skill_resolver=stub
    )
    planner_with_registry = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=SkillToolRegistry(),
    )

    goal = Goal(metadata={"capability": "cap.check"})

    caps_without = planner_without_registry.resolve_capabilities(goal)
    caps_with = planner_with_registry.resolve_capabilities(goal)
    check(
        caps_without == caps_with == ("skill_check_a", "skill_check_b"),
        "V29: resolve_capabilities() output is unaffected by whether skill_tool_registry is also attached",
    )

    skills_without = planner_without_registry.resolve_skills(goal)
    skills_with = planner_with_registry.resolve_skills(goal)
    check(
        skills_without == skills_with == (skill_a, skill_b),
        "V29: resolve_skills() output is unaffected by whether skill_tool_registry is also attached",
    )


# ---------------------------------------------------------------------------
# V30 -- exception convention
# ---------------------------------------------------------------------------
def scenario_exception_convention() -> None:
    check(
        issubclass(GoalPlannerError, AgentError),
        "V30: GoalPlannerError remains a subclass of Core.exceptions.AgentError",
    )


# ---------------------------------------------------------------------------
# V31 -- constructor rejects bare collaborators
# ---------------------------------------------------------------------------
def scenario_constructor_rejects_bare_collaborators() -> None:
    registry = SkillRegistry()
    manager, _skill_registry = _make_capability_manager()
    stub_resolver = _StubSkillResolver({})

    for value in (registry, manager, stub_resolver):
        raised = False
        try:
            GoalPlanner(service_skills={}, skill_tool_registry=value)  # type: ignore[arg-type]
        except GoalPlannerError:
            raised = True
        check(
            raised,
            f"V31: GoalPlanner(skill_tool_registry={type(value).__name__} instance) raises GoalPlannerError (not a SkillToolRegistry)",
        )


# ---------------------------------------------------------------------------
# V32 -- combination: skill_tool_registry alongside memory,
# capability_manager, and skill_resolver
# ---------------------------------------------------------------------------
def scenario_full_combination() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.combo", ("skill_combo",))
    skill_combo = _GuardedSkill("skill_combo")
    stub = _StubSkillResolver({"skill_combo": skill_combo})
    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_combo", ("combo_tool",))

    class StubMemory:
        def list(self):
            return ()

    stub_memory = StubMemory()
    planner = GoalPlanner(
        service_skills={},
        memory=stub_memory,
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )

    goal = Goal(metadata={"capability": "cap.combo"})
    check(
        planner.discover_tools(goal) == ("combo_tool",),
        "V32: discover_tools() works correctly with memory also attached",
    )
    check(planner.recall(goal) == (), "V32: recall() works correctly (independently) with skill_tool_registry also attached")
    check(
        planner.resolve_capabilities(goal) == ("skill_combo",),
        "V32: resolve_capabilities() works correctly with skill_tool_registry also attached",
    )
    check(
        planner.resolve_skills(goal) == (skill_combo,),
        "V32: resolve_skills() works correctly with skill_tool_registry also attached",
    )


# ---------------------------------------------------------------------------
# V33 -- public API exactness
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
        "discover_tools",
    }
    actual_public_methods = {
        name
        for name in dir(GoalPlanner)
        if not name.startswith("_") and callable(getattr(GoalPlanner, name))
    }
    check(
        actual_public_methods == expected_public_methods,
        f"V33: GoalPlanner's public methods are exactly {sorted(expected_public_methods)} (got {sorted(actual_public_methods)})",
    )


# ---------------------------------------------------------------------------
# V34 -- extra unrelated metadata keys never consulted
# ---------------------------------------------------------------------------
def scenario_extra_metadata_ignored() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.extra", ("skill_extra",))
    stub = _StubSkillResolver({"skill_extra": _GuardedSkill("skill_extra")})
    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_extra", ("extra_tool",))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )

    goal = Goal(metadata={"capability": "cap.extra", "ticker": "BBCA", "period": "1D"})
    result = planner.discover_tools(goal)
    check(result == ("extra_tool",), "V34: extra unrelated metadata keys do not affect discover_tools()'s outcome")


# ---------------------------------------------------------------------------
# V35 -- no Task creation
# ---------------------------------------------------------------------------
def scenario_no_task_creation() -> None:
    manager, skill_registry = _make_capability_manager()
    skill_registry.register("cap.no_task", ("skill_no_task",))

    stub = _StubSkillResolver({"skill_no_task": _GuardedSkill("skill_no_task")})
    tool_registry = SkillToolRegistry()
    tool_registry.register("skill_no_task", ("nt_tool",))

    planner = GoalPlanner(
        service_skills={},
        capability_manager=manager,
        skill_resolver=stub,
        skill_tool_registry=tool_registry,
    )

    original_init = task_module.Task.__init__
    call_count = {"n": 0}

    def counting_init(self, *args, **kwargs):
        call_count["n"] += 1
        return original_init(self, *args, **kwargs)

    task_module.Task.__init__ = counting_init  # type: ignore[method-assign]
    try:
        planner.discover_tools(Goal(metadata={"capability": "cap.no_task"}))
    finally:
        task_module.Task.__init__ = original_init  # type: ignore[method-assign]

    check(call_count["n"] == 0, "V35: discover_tools() never constructs a Orchestration.task.Task instance")


def main() -> int:
    scenarios = [
        scenario_constructor_omitted,
        scenario_constructor_explicit_none,
        scenario_constructor_valid_registry,
        scenario_constructor_invalid_registry,
        scenario_identity_preservation,
        scenario_no_skill_resolver,
        scenario_no_skill_tool_registry,
        scenario_no_resolved_skills,
        scenario_single_skill,
        scenario_multiple_skills_merge,
        scenario_order_preserved,
        scenario_duplicate_tool_names_preserved,
        scenario_no_sorting,
        scenario_no_normalization,
        scenario_only_name_accessed,
        scenario_never_executes_skill,
        scenario_result_is_tuple_of_str,
        scenario_registry_called_with_skill_name,
        scenario_registry_miss_propagates,
        scenario_resolver_exception_propagates,
        scenario_capability_exception_propagates,
        scenario_ast_import_verification,
        scenario_no_forbidden_namespace_symbols,
        scenario_multi_instance_independence,
        scenario_no_hidden_state,
        scenario_no_caching,
        scenario_no_registry_creation,
        scenario_pre_existing_surface_unaffected,
        scenario_resolve_methods_unaffected,
        scenario_exception_convention,
        scenario_constructor_rejects_bare_collaborators,
        scenario_full_combination,
        scenario_public_api_exactness,
        scenario_extra_metadata_ignored,
        scenario_no_task_creation,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 5 SPRINT 70 PLANNER-TOOL-DISCOVERY RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)

    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())