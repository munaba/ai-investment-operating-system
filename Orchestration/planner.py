"""GoalPlanner -- metadata-driven planning over ``ServiceSkill``s (Stage
L15, Phase 1: Planner gains the *capability* to turn a ``Goal`` into an
``ExecutionPlan`` over the L13 ``ServiceSkill`` registry, and to run that
plan).

Scope note (LOCKED baseline, approved Diff-Level Plan FINAL): Phase 1
Steps 1-6 only. This module:

  1. Defines ``GoalPlannerError`` and the ``GoalPlanner`` skeleton
     (constructor-only, dependency-injected with the same
     ``Dict[str, ServiceSkill]`` shape ``Core.composition_root`` already
     builds for L13 -- no second construction of any ``ServiceSkill``).
  2. Defines three immutable value objects -- ``Goal``, ``PlanStep``,
     ``ExecutionPlan`` -- and four interface methods on ``GoalPlanner``
     (``build_plan``, ``execute_plan``, ``translate_metadata``,
     ``accumulate_context``). All four now have bodies (``build_plan``
     Step 3, ``execute_plan`` Step 4, ``accumulate_context`` Step 5,
     ``translate_metadata`` Step 6).
  3. Implements ``build_plan`` as a pure, metadata-driven forward-chaining
     fixed-point closure over ``SkillMetadata.required_inputs`` /
     ``SkillMetadata.produced_outputs`` (the same declarative metadata
     ``Orchestration.service_skill`` already carries for every
     registered ``ServiceSkill``). It never executes a ``ServiceSkill``,
     never talks to Runtime, Observation, Memory, or Reflection, and
     never special-cases a service by name -- the only per-skill logic is
     "are this skill's ``required_inputs`` already available?".
  4. Implements ``execute_plan`` as a plain, in-order walk over an
     already-built ``ExecutionPlan.steps``: resolve each step's
     ``ServiceSkill`` by ``service_name``, translate the running context
     for that step (see #6), call ``.execute(...)``, collect the
     returned ``ServiceResult``, then fold it into the running context
     (see #5). No retry, no skip policy, no branching, no replanning, no
     dependency-order changes (the order is whatever ``build_plan``
     already produced), no Observation, no Memory, no Reflection, no
     DAG/parallel execution.
  5. Implements ``accumulate_context`` as a pure, side-effect-free dict
     merge: after each step, its ``ServiceResult`` is folded into a
     running context (a successful, dict-``data`` result's keys
     overwrite same-named earlier keys; a failed result or non-dict
     ``data`` leaves the context unchanged), and every subsequent step
     receives that running context as its own ``metadata`` -- so a later
     step can see an earlier step's output, never the reverse. The
     incoming context dict is never mutated.
  6. Implements ``translate_metadata`` as a pure, step-aware dict copy:
     by default it returns ``dict(accumulated_context)`` unchanged
     except for the one explicit, already-documented rule (see its own
     docstring) -- ``risk_management_service`` gets ``PRICE`` copied to
     ``ENTRY_PRICE`` when the latter is absent. No general translation
     engine, no mapping registry, no pattern matching, no inference. The
     translated dict is only ever passed to that one step's
     ``ServiceSkill.execute(...)`` call -- ``accumulate_context`` keeps
     folding from the untranslated running context, so a translation
     never leaks into what later steps see as their own starting point.

This module does not touch, import from, or get imported by
``Orchestration.runtime_analysis_pipeline``,
``Orchestration.analysis_pipeline_adapter``, or any Runtime/Agent code --
it is additive-only, constructed and used solely by whatever future stage
wires a ``GoalPlanner`` up (not this stage). It imports
``Orchestration.service_skill.ServiceSkill`` (constructor dependency),
``Services.metadata_keys.MetadataKeys`` (``translate_metadata``'s one
translation rule), and ``Services.service_result.ServiceResult``
(``execute_plan``'s return element type, and ``accumulate_context``'s
second argument type) only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from Core.exceptions import AgentError
from Core.logger import LoggerFactory
from Orchestration.capability_manager import CapabilityManager
from Orchestration.service_skill import ServiceSkill
from Orchestration.skill_execution_plan import SkillExecutionPlan
from Orchestration.skill_resolver import SkillResolver
from Orchestration.skill_tool_registry import SkillToolRegistry
from Orchestration.task import Task
from Orchestration.workflow import Workflow
from Services.metadata_keys import MetadataKeys
from Services.service_result import ServiceResult

logger = LoggerFactory().get_logger(__name__)


class GoalPlannerError(AgentError):
    """Raised by ``GoalPlanner`` for planner-level failures.

    Not raised by ``build_plan`` (unsatisfiable skills are excluded and
    logged, not treated as an error), ``accumulate_context`` (a failed
    or non-dict-``data`` result is silently a no-op, not an error), or
    ``translate_metadata`` (its one rule either applies or doesn't --
    never an error) -- see each method's own docstring. Raised by
    ``execute_plan`` for a missing ``ServiceSkill`` or an unexpected
    exception during a skill call. Raised by ``build_workflow``
    (Sprint 34) for an invalid ``name``, ``description``, ``tasks``,
    or ``metadata`` argument.
    """


@dataclass(frozen=True)
class Goal(object):
    """A single planning request, expressed purely as available metadata.

    Intentionally minimal (LOCKED baseline, decision #2 -- see module
    docstring): a ``Goal`` is nothing more than the ``ServiceContext.metadata``
    keys/values already available before planning starts. It carries no
    notion of "intent", "task type", or natural-language description --
    that translation, if ever needed, is out of scope for this stage (see
    :meth:`GoalPlanner.translate_metadata`).

    Attributes:
        metadata: The metadata already available up front (e.g. whatever
            the caller already knows -- a ticker, a period, ...). Used by
            :meth:`GoalPlanner.build_plan` as the starting point of its
            forward-chaining closure (``available = set(goal.metadata)``).
    """

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanStep(object):
    """One step of an ``ExecutionPlan`` -- a single ``ServiceSkill`` to run.

    Attributes:
        service_name: The ``ServiceSkill``'s own ``SkillMetadata.service_name``
            (also the key into ``GoalPlanner``'s ``service_skills`` dict).
        inputs: The metadata keys this step requires, copied verbatim
            from the skill's own ``SkillMetadata.required_inputs`` at
            planning time. Not resolved or merged here at planning time
            -- ``GoalPlanner.execute_plan`` resolves the actual metadata
            a step receives at run time, via
            :meth:`GoalPlanner.translate_metadata` and
            :meth:`GoalPlanner.accumulate_context`.
    """

    service_name: str
    inputs: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExecutionPlan(object):
    """An ordered, already-built plan of ``PlanStep``s for one ``Goal``.

    Attributes:
        goal: The ``Goal`` this plan was built for.
        steps: The ordered ``PlanStep``s produced by
            :meth:`GoalPlanner.build_plan`, in deterministic
            (fixed-point-round, then service_name) order. Immutable
            (``Tuple``, not ``List``) -- a plan, once built, does not
            change shape in Phase 1.
    """

    goal: Goal
    steps: Tuple[PlanStep, ...] = field(default_factory=tuple)


class GoalPlanner:
    """Builds and executes plans over a fixed set of ``ServiceSkill``s.

    Phase 1 Steps 1-6: constructor, ``build_plan``, ``execute_plan``,
    ``accumulate_context``, and ``translate_metadata`` are all
    implemented. The LOCKED interface's four methods are now complete
    for Phase 1 -- no further method is left declared-but-unimplemented
    on this class.

    Phase 4 Sprint 34 (Planner -> Workflow Integration) adds a fifth,
    independent method: ``build_workflow``. It is purely additive and
    does not touch ``build_plan``/``execute_plan``/
    ``translate_metadata``/``accumulate_context`` or the ``Goal``/
    ``PlanStep``/``ExecutionPlan`` value objects at all -- ``Workflow``
    construction and ``ExecutionPlan`` construction remain two
    unrelated capabilities of this class, sharing nothing but the
    ``GoalPlanner`` namespace and its ``GoalPlannerError`` exception
    type. ``build_workflow`` only ever constructs and returns a
    ``Workflow`` value object -- it never calls
    ``Orchestration.workflow_engine.WorkflowEngine``,
    ``Orchestration.workflow_execution_coordinator.
    WorkflowExecutionCoordinator``, ``Orchestration.executor.Executor``,
    or ``Orchestration.autonomous_host.AutonomousHost``; this class
    does not import any of them. Planning (this class) and workflow
    preparation/orchestration/execution (those other, unmodified
    classes) remain strictly separate concerns.

    Phase 4 Sprint 42 (Planner <- Memory Integration -- Closed Learning
    Loop) adds a sixth, independent capability: an optional ``memory``
    constructor argument plus the read-only :meth:`recall` method. Like
    ``build_workflow`` before it, this is purely additive -- it touches
    nothing about ``build_plan``/``execute_plan``/``translate_metadata``/
    ``accumulate_context``/``build_workflow`` themselves. ``memory`` is
    accepted by duck typing only (must expose a callable ``list``),
    exactly mirroring how ``Orchestration.learning_loop.LearningLoop``
    already accepts its own optional ``memory`` collaborator (Sprint
    41) -- this class never imports ``Orchestration.memory`` or any
    symbol from it. This class also never imports
    ``Orchestration.reflection`` or ``Orchestration.learning_loop``
    themselves, and never imports ``Core.runtime.WorkflowRuntime`` or
    ``Orchestration.executor.Executor`` -- Planner knows only that a
    memory collaborator can be listed, nothing about how experience
    reaches it in the first place.

    Phase 5 Sprint 68 (Planner -> Capability Resolution, discovery
    only) adds an eighth, independent capability: an optional
    ``capability_manager`` constructor argument plus the read-only
    :meth:`resolve_capabilities` method. Like ``recall`` before it,
    this is purely additive -- it touches nothing about
    ``build_plan``/``execute_plan``/``translate_metadata``/
    ``accumulate_context``/``build_workflow``/``recall`` themselves.
    ``capability_manager``, when given, must be an
    ``Orchestration.capability_manager.CapabilityManager`` instance
    (validated by ``isinstance``, not duck typing) and is stored by
    identity only -- never constructed here. This class never
    resolves Skills or Tools, never touches ``SkillRegistry``,
    ``SkillResolver``, ``ToolRegistry``, ``ToolResolver``, or
    ``ToolManager``, and never calls ``Executor`` -- Planner knows
    only that a capability name can be resolved to a tuple of skill
    names, nothing about what those skill names are or how to run
    them.

    Phase 5 Sprint 69 (Planner -> Skill Resolution, discovery only)
    adds a ninth, independent capability: an optional
    ``skill_resolver`` constructor argument plus the read-only
    :meth:`resolve_skills` method. Like ``resolve_capabilities``
    before it, this is purely additive -- it touches nothing about
    ``build_plan``/``execute_plan``/``translate_metadata``/
    ``accumulate_context``/``build_workflow``/``recall``/
    ``resolve_capabilities`` themselves. ``skill_resolver``, when
    given, must be an ``Orchestration.skill_resolver.SkillResolver``
    instance (validated by ``isinstance``, not duck typing) and is
    stored by identity only -- never constructed here. This class
    still never resolves Tool objects, never touches ``ToolRegistry``,
    ``ToolResolver``, or ``ToolManager``, and never calls
    ``Executor`` -- Planner knows only that a resolved skill name can
    be turned into a skill object, nothing about what that object is
    or how to run it.

    Phase 5 Sprint 70 (Planner -> Tool Discovery, discovery only) adds
    a tenth, independent capability: an optional
    ``skill_tool_registry`` constructor argument plus the read-only
    :meth:`discover_tools` method. Like ``resolve_skills`` before it,
    this is purely additive -- it touches nothing about
    ``build_plan``/``execute_plan``/``translate_metadata``/
    ``accumulate_context``/``build_workflow``/``recall``/
    ``resolve_capabilities``/``resolve_skills`` themselves.
    ``skill_tool_registry``, when given, must be an
    ``Orchestration.skill_tool_registry.SkillToolRegistry`` instance
    (validated by ``isinstance``, not duck typing) and is stored by
    identity only -- never constructed here. This class still never
    resolves Tool objects, never touches ``ToolRegistry``,
    ``ToolResolver``, or ``ToolManager``, and never calls
    ``Executor`` -- Planner knows only that a resolved skill's
    ``.name`` can be looked up in a ``SkillToolRegistry`` to get a
    tuple of tool names, nothing about what those tool names are or
    how to run them.
    """

    def __init__(
        self,
        service_skills: Dict[str, ServiceSkill],
        memory: Optional[Any] = None,
        capability_manager: Optional[CapabilityManager] = None,
        skill_resolver: Optional[SkillResolver] = None,
        skill_tool_registry: Optional[SkillToolRegistry] = None,
    ) -> None:
        """Wire up the planner via dependency injection only.

        Args:
            service_skills: The already-constructed ``ServiceSkill``
                registry, keyed by ``service_name`` -- the same dict
                ``Core.composition_root`` builds for L13. Never
                constructed here, and no ``ServiceSkill`` is ever
                instantiated a second time by this class.
            memory: Optional (Phase 4 Sprint 42 -- Planner <- Memory
                Integration). Any object exposing a callable ``list``
                attribute (e.g. an ``Orchestration.memory.MemoryStore``
                instance) -- accepted purely by duck typing, mirroring
                ``Orchestration.learning_loop.LearningLoop``'s own
                ``memory=`` parameter (Sprint 41): this class never
                imports, constructs, or references ``MemoryStore`` or
                ``MemoryRecorder`` themselves. When given, only
                :meth:`recall` ever reads from it (via ``memory.list()``)
                -- never ``build_plan``, ``execute_plan``, or any other
                method on this class. When omitted (the default,
                ``None``), :meth:`recall` simply returns an empty tuple
                -- every other method's behavior is completely
                unaffected, exactly as before this parameter existed.
            capability_manager: Optional (Phase 5 Sprint 68 -- Planner
                -> Capability Resolution, discovery only). When given,
                must be an ``Orchestration.capability_manager.
                CapabilityManager`` instance -- stored by identity,
                never copied, never constructed here. Only
                :meth:`resolve_capabilities` ever reads from it (via
                ``capability_manager.resolve(...)``) -- never
                ``build_plan``, ``execute_plan``, or any other method
                on this class. When omitted (the default, ``None``),
                :meth:`resolve_capabilities` simply returns an empty
                tuple -- every other method's behavior is completely
                unaffected, exactly as before this parameter existed.
            skill_resolver: Optional (Phase 5 Sprint 69 -- Planner ->
                Skill Resolution, discovery only). When given, must be
                an ``Orchestration.skill_resolver.SkillResolver``
                instance -- stored by identity, never copied, never
                constructed here. Only :meth:`resolve_skills` ever
                reads from it (via ``skill_resolver.resolve(...)``) --
                never ``build_plan``, ``execute_plan``, or any other
                method on this class. When omitted (the default,
                ``None``), :meth:`resolve_skills` simply returns an
                empty tuple -- every other method's behavior is
                completely unaffected, exactly as before this
                parameter existed.
            skill_tool_registry: Optional (Phase 5 Sprint 70 --
                Planner -> Tool Discovery, discovery only). When
                given, must be an ``Orchestration.skill_tool_registry.
                SkillToolRegistry`` instance -- stored by identity,
                never copied, never constructed here. Only
                :meth:`discover_tools` ever reads from it (via
                ``skill_tool_registry.get(...)``) -- never
                ``build_plan``, ``execute_plan``, or any other method
                on this class. When omitted (the default, ``None``),
                :meth:`discover_tools` simply returns an empty tuple
                -- every other method's behavior is completely
                unaffected, exactly as before this parameter existed.

        Raises:
            GoalPlannerError: if ``memory`` is given but does not expose
                a callable ``list`` attribute; if ``capability_manager``
                is given but is not a ``CapabilityManager`` instance;
                if ``skill_resolver`` is given but is not a
                ``SkillResolver`` instance; or if
                ``skill_tool_registry`` is given but is not a
                ``SkillToolRegistry`` instance.
        """
        self._service_skills = service_skills

        if memory is not None and not callable(getattr(memory, "list", None)):
            raise GoalPlannerError(
                f"GoalPlanner()'s memory argument must expose a callable "
                f"'list' method; got {memory!r}"
            )
        self._memory = memory

        if capability_manager is not None and not isinstance(
            capability_manager, CapabilityManager
        ):
            raise GoalPlannerError(
                f"GoalPlanner()'s capability_manager argument must be a "
                f"CapabilityManager instance; got {capability_manager!r}"
            )
        self._capability_manager = capability_manager

        if skill_resolver is not None and not isinstance(
            skill_resolver, SkillResolver
        ):
            raise GoalPlannerError(
                f"GoalPlanner()'s skill_resolver argument must be a "
                f"SkillResolver instance; got {skill_resolver!r}"
            )
        self._skill_resolver = skill_resolver

        if skill_tool_registry is not None and not isinstance(
            skill_tool_registry, SkillToolRegistry
        ):
            raise GoalPlannerError(
                f"GoalPlanner()'s skill_tool_registry argument must be "
                f"a SkillToolRegistry instance; got {skill_tool_registry!r}"
            )
        self._skill_tool_registry = skill_tool_registry

    def recall(self, goal: Goal) -> Tuple[Dict[str, Any], ...]:
        """Read-only retrieval of past experience relevant to ``goal``
        from the optional Memory collaborator (Phase 4 Sprint 42,
        Planner <- Memory Integration -- Closed Learning Loop).

        Purely additive and read-only (LOCKED scope for this sprint):
        this method only ever calls ``self._memory.list()`` -- it never
        calls ``add`` or any other mutating method, and never writes,
        clears, or otherwise changes anything the memory collaborator
        holds. ``build_plan``/``execute_plan``/``translate_metadata``/
        ``accumulate_context``/``build_workflow`` are all completely
        untouched by this addition; ``recall`` is a fifth, independent,
        read-only capability, exactly as ``build_workflow`` (Sprint 34)
        was a purely additive fourth one.

        The object returned by ``memory.list()`` (and each item within
        it) is only ever inspected via ``getattr`` -- this module never
        imports, and does not need to know about,
        ``Orchestration.observation.Observation`` or
        ``Orchestration.memory.MemoryRecord`` to do this; it only
        assumes each item may expose an ``observation`` attribute which
        may in turn expose ``goal_metadata``/``aggregated_outputs``
        attributes shaped like plain ``dict``s. Anything that does not
        match that shape is silently skipped -- never raised.

        A past record is considered relevant to ``goal`` when at least
        one ``(key, value)`` pair in ``goal.metadata`` also appears,
        identically, in that record's own ``goal_metadata`` -- the
        simplest possible overlap test, with no ranking, scoring,
        similarity metric, or embedding of any kind.

        Args:
            goal: The ``Goal`` to recall past experience for. Only
                ``goal.metadata`` is read.

        Returns:
            A ``Tuple[Dict[str, Any], ...]`` of every relevant past
            record's ``aggregated_outputs`` (each a fresh ``dict`` copy,
            never a live reference into the memory collaborator's own
            storage), in the order ``memory.list()`` returned them.
            Always ``()`` when no ``memory`` was supplied at
            construction time, or when nothing relevant is found --
            never ``None``, never raised.
        """
        if self._memory is None:
            return ()

        records = self._memory.list()

        relevant: List[Dict[str, Any]] = []
        for record in records:
            observation = getattr(record, "observation", None)
            recorded_metadata = getattr(observation, "goal_metadata", None)
            aggregated_outputs = getattr(observation, "aggregated_outputs", None)

            if not isinstance(recorded_metadata, dict) or not isinstance(
                aggregated_outputs, dict
            ):
                continue

            overlaps = any(
                key in recorded_metadata and recorded_metadata[key] == value
                for key, value in goal.metadata.items()
            )
            if overlaps:
                relevant.append(dict(aggregated_outputs))

        return tuple(relevant)

    def resolve_capabilities(self, goal: Goal) -> Tuple[str, ...]:
        """Resolve ``goal``'s declared capability into candidate skill
        names via the optional ``CapabilityManager`` collaborator
        (Phase 5 Sprint 68, Planner -> Capability Resolution --
        discovery only).

        Purely additive and read-only (LOCKED scope for this sprint):
        this method only ever reads ``goal.metadata`` and calls
        ``self._capability_manager.resolve(...)`` -- it never resolves
        a ``Skill`` object, never touches ``SkillRegistry``,
        ``SkillResolver``, ``ToolRegistry``, ``ToolResolver``, or
        ``ToolManager``, never executes anything, and never calls
        ``Executor``. ``build_plan``/``execute_plan``/
        ``translate_metadata``/``accumulate_context``/
        ``build_workflow``/``recall`` are all completely untouched by
        this addition; ``resolve_capabilities`` is a seventh,
        independent, read-only capability, exactly as ``recall``
        (Sprint 42) was a purely additive fifth one.

        No normalization, no lowercasing, no stripping/trimming, no
        fallback, no inference, no ranking, no scoring, and no
        caching -- the returned tuple is exactly whatever
        ``CapabilityManager.resolve`` returns, unmodified and
        unwrapped.

        Args:
            goal: The ``Goal`` to resolve capabilities for. Only
                ``goal.metadata["capability"]`` is read.

        Returns:
            ``()`` when no ``capability_manager`` was supplied at
            construction time, or when ``goal.metadata`` has no
            ``"capability"`` key. Otherwise, exactly the
            ``Tuple[str, ...]`` returned by
            ``self._capability_manager.resolve(goal.metadata["capability"])``.

        Raises:
            Whatever ``CapabilityManager.resolve`` itself raises for
            an invalid or unknown capability value -- propagated
            unmodified, never caught or wrapped here.
        """
        if self._capability_manager is None:
            return ()

        if "capability" not in goal.metadata:
            return ()

        return self._capability_manager.resolve(goal.metadata["capability"])

    def resolve_skills(self, goal: Goal) -> Tuple[Any, ...]:
        """Resolve ``goal`` all the way from a declared capability into
        actual (opaque) skill objects via the optional ``SkillResolver``
        collaborator (Phase 5 Sprint 69, Planner -> Skill Resolution --
        discovery only).

        Purely additive and read-only (LOCKED scope for this sprint):
        this method only ever calls :meth:`resolve_capabilities` (to
        get the candidate skill names) and then
        ``self._skill_resolver.resolve(skill_name)`` once per resolved
        skill name -- it never touches ``SkillRegistry``,
        ``ToolRegistry``, ``ToolResolver``, or ``ToolManager``, never
        executes anything it resolves, never calls ``Executor``, and
        never constructs a ``Task``. ``build_plan``/``execute_plan``/
        ``translate_metadata``/``accumulate_context``/
        ``build_workflow``/``recall``/``resolve_capabilities`` are all
        completely untouched by this addition; ``resolve_skills`` is
        an eighth, independent, read-only capability, exactly as
        ``resolve_capabilities`` (Sprint 68) was a purely additive
        seventh one.

        No normalization, no deduplication, no sorting, no fallback,
        no inference, no ranking, no scoring, and no caching -- each
        skill name returned by :meth:`resolve_capabilities` is passed,
        unmodified, to ``self._skill_resolver.resolve(...)`` in the
        same order, and the resolved objects are collected into a
        tuple in that same order.

        Args:
            goal: The ``Goal`` to resolve skills for. Only read via
                :meth:`resolve_capabilities` -- no additional
                ``goal.metadata`` keys are consulted here.

        Returns:
            ``()`` when no ``skill_resolver`` was supplied at
            construction time, or when :meth:`resolve_capabilities`
            itself returns ``()``. Otherwise, a ``Tuple[Any, ...]`` of
            exactly the objects returned by
            ``self._skill_resolver.resolve(skill_name)``, one per
            resolved skill name, in resolved order -- unmodified,
            unwrapped, identity preserved.

        Raises:
            Whatever :meth:`resolve_capabilities` itself raises for an
            unknown or invalid capability value, and whatever
            ``SkillResolver.resolve`` itself raises for an
            unresolvable skill name -- both propagated unmodified,
            never caught or wrapped here.
        """
        if self._skill_resolver is None:
            return ()

        skill_names = self.resolve_capabilities(goal)
        if not skill_names:
            return ()

        return tuple(
            self._skill_resolver.resolve(Task(name=skill_name, description=""))
            for skill_name in skill_names
        )

    def discover_tools(self, goal: Goal) -> Tuple[str, ...]:
        """Discover which Tool names belong to ``goal``'s resolved
        Skills via the optional ``SkillToolRegistry`` collaborator
        (Phase 5 Sprint 70, Planner -> Tool Discovery -- discovery
        only).

        Purely additive and read-only (LOCKED scope for this sprint):
        this method only ever calls :meth:`resolve_skills` (to get the
        resolved Skill objects), reads each resolved skill's own
        ``.name`` attribute, and calls
        ``self._skill_tool_registry.get(skill.name)`` once per
        resolved skill -- it never resolves a Tool object, never calls
        ``ToolResolver``, ``ToolManager``, or ``Executor``, never
        executes a Skill or a Tool, never creates a ``Task``, and
        never touches ``Runtime``. ``build_plan``/``execute_plan``/
        ``translate_metadata``/``accumulate_context``/
        ``build_workflow``/``recall``/``resolve_capabilities``/
        ``resolve_skills`` are all completely untouched by this
        addition; ``discover_tools`` is a ninth, independent,
        read-only capability, exactly as ``resolve_skills`` (Sprint
        69) was a purely additive eighth one.

        No sorting, no deduplication, no normalization, no
        lowercasing, no trimming, no inference, and no caching -- the
        tool names registered under each resolved skill's ``.name``
        are concatenated, in resolved-skill order and in registry
        order, into the returned tuple exactly as
        ``SkillToolRegistry.get`` returns them.

        Only ``skill.name`` is ever read on a resolved skill object --
        no ``description``, ``metadata``, ``capabilities``, methods,
        or ``execute`` are ever inspected.

        Args:
            goal: The ``Goal`` to discover tools for. Only read via
                :meth:`resolve_skills` -- no additional
                ``goal.metadata`` keys are consulted here.

        Returns:
            ``()`` when no ``skill_resolver`` collaborator is
            attached (so :meth:`resolve_skills` itself returns
            ``()``), when no ``skill_tool_registry`` was supplied at
            construction time, or when :meth:`resolve_skills` returns
            no skills for ``goal``. Otherwise, a ``Tuple[str, ...]``
            of every tool name registered under each resolved skill's
            ``.name``, merged in order, preserving duplicates.

        Raises:
            Whatever :meth:`resolve_skills` itself raises (including
            whatever :meth:`resolve_capabilities` or
            ``SkillResolver.resolve`` raise), and whatever
            ``SkillToolRegistry.get`` itself raises for an
            unregistered skill name -- both propagated unmodified,
            never caught or wrapped here.
        """
        if self._skill_tool_registry is None:
            return ()

        skills = self.resolve_skills(goal)
        if not skills:
            return ()

        tool_names: List[str] = []
        for skill in skills:
            tool_names.extend(self._skill_tool_registry.get(skill.name))

        return tuple(tool_names)

    def build_skill_execution_plan(self, goal: Goal) -> SkillExecutionPlan:
        """Package ``goal``'s discovery result into an immutable
        ``SkillExecutionPlan`` (Phase 6 Sprint 71, Skill Execution
        Pipeline -- Discovery -> Execution Boundary).

        Purely additive and read-only (LOCKED scope for this sprint):
        this method only ever calls :meth:`resolve_skills` (to get
        the resolved skill objects) and :meth:`discover_tools` (to
        get the discovered tool names), then hands both straight to a
        new ``SkillExecutionPlan`` alongside an empty ``metadata``
        dict -- it never executes a skill or a tool, never
        instantiates ``Executor``, never calls ``Runtime``,
        ``Workflow``, or ``EventBus``, never inspects ``BaseSkill`` or
        ``BaseTool``, and never normalizes, caches, ranks, reorders,
        or deduplicates anything. ``build_plan``/``execute_plan``/
        ``translate_metadata``/``accumulate_context``/
        ``build_workflow``/``recall``/``resolve_capabilities``/
        ``resolve_skills``/``discover_tools`` are all completely
        untouched by this addition; ``build_skill_execution_plan`` is
        an eleventh, independent, read-only capability, exactly as
        ``discover_tools`` (Sprint 70) was a purely additive tenth
        one.

        Args:
            goal: The ``Goal`` to build a ``SkillExecutionPlan`` for.
                Only read via :meth:`resolve_skills` and
                :meth:`discover_tools` -- no additional
                ``goal.metadata`` keys are consulted here.

        Returns:
            A new ``SkillExecutionPlan`` whose ``skills`` is exactly
            ``self.resolve_skills(goal)``, whose ``tools`` is exactly
            ``self.discover_tools(goal)``, and whose ``metadata`` is
            an empty mapping.

        Raises:
            Whatever :meth:`resolve_skills` or :meth:`discover_tools`
            themselves raise -- propagated unmodified, never caught
            or wrapped here. ``SkillExecutionPlanError`` propagates
            unmodified as well, should ``SkillExecutionPlan``'s own
            validation ever reject the packaged values.
        """
        skills = self.resolve_skills(goal)
        tools = self.discover_tools(goal)

        return SkillExecutionPlan(skills=skills, tools=tools, metadata={})

    def build_plan(self, goal: Goal) -> ExecutionPlan:
        """Build an ``ExecutionPlan`` for ``goal`` via forward-chaining
        fixed-point closure over declarative ``SkillMetadata``.

        Pure and metadata-driven only (LOCKED baseline, decision #3 --
        see module docstring): the only question ever asked of a skill is
        "are all of this skill's ``required_inputs`` already in
        ``available``?" -- there is no service-specific branching and no
        hardcoded ordering. Nothing is executed; no ``ServiceSkill.execute``
        call is ever made here.

        Algorithm:
            1. ``available`` starts as ``set(goal.metadata.keys())``.
            2. Repeatedly scan every not-yet-included skill; a skill is
               *satisfied* this round if every one of its
               ``required_inputs`` is already in ``available``.
            3. Add all skills satisfied this round, in deterministic
               ``service_name`` sort order, as ``PlanStep``s -- then union
               all of their ``produced_outputs`` into ``available``.
            4. Repeat steps 2-3 until a round adds no new skill (fixed
               point reached).
            5. Any skill still not included when the fixed point is
               reached is *unsatisfied*: it is excluded from the plan and
               the reason (its still-missing ``required_inputs``) is
               logged -- never raised, never fabricated, never executed.

        Args:
            goal: The ``Goal`` to plan for. Only ``goal.metadata.keys()``
                is read -- values are never inspected or validated here.

        Returns:
            An ``ExecutionPlan`` holding ``goal`` and the deterministic,
            ordered list of satisfied ``PlanStep``s. Unsatisfied skills
            are simply absent from ``steps`` -- there is no separate
            "blocked steps" field in Phase 1.

            # TODO(L15, future stage): preserve unsatisfied/blocked
            # skills on the ``ExecutionPlan`` itself (e.g. a
            # ``blocked_steps`` field with the missing-inputs reason)
            # instead of only logging them, so a future Reflection/
            # replanning stage can inspect *why* a skill was excluded
            # without re-running this closure.
        """
        available: set = set(goal.metadata.keys())
        remaining: set = set(self._service_skills.keys())
        ordered_steps: List[PlanStep] = []

        while True:
            satisfied_this_round = sorted(
                service_name
                for service_name in remaining
                if set(self._service_skills[service_name].metadata.required_inputs)
                <= available
            )

            if not satisfied_this_round:
                break

            for service_name in satisfied_this_round:
                skill = self._service_skills[service_name]
                ordered_steps.append(
                    PlanStep(
                        service_name=service_name,
                        inputs=skill.metadata.required_inputs,
                    )
                )
                available |= set(skill.metadata.produced_outputs)
                remaining.discard(service_name)

        # Fixed point reached: anything left in `remaining` could never
        # have its required_inputs satisfied from goal.metadata plus
        # whatever every other included skill produces. Excluded, not
        # raised (LOCKED baseline, decision #3) -- just logged with the
        # specific missing keys for diagnosis.
        #
        # TODO(L15, future stage): see the `blocked_steps` TODO above --
        # this is where that preservation would be populated instead of
        # only logging.
        for service_name in sorted(remaining):
            skill = self._service_skills[service_name]
            missing = sorted(set(skill.metadata.required_inputs) - available)
            logger.warning(
                "build_plan: excluding unsatisfied skill '%s' -- missing "
                "required_inputs=%s (available=%s)",
                service_name,
                missing,
                sorted(available),
            )

        return ExecutionPlan(goal=goal, steps=tuple(ordered_steps))

    def execute_plan(self, plan: ExecutionPlan) -> List[ServiceResult]:
        """Execute an already-built ``ExecutionPlan``, in step order.

        Pure execution lifecycle only (LOCKED baseline, decision #4 --
        see module docstring): for each ``PlanStep``, resolve its
        ``ServiceSkill`` by ``service_name`` and call ``.execute(...)``,
        then collect the ``ServiceResult`` it returns. Nothing else.

        Context accumulation (Step 5): the first step is called with
        ``dict(plan.goal.metadata)``. After each step's
        ``ServiceSkill.execute(...)`` call returns, its ``ServiceResult``
        is folded into the running context via :meth:`accumulate_context`
        (a successful, dict-``data`` result's keys are merged in, later
        keys overwriting earlier ones; a failed result or a non-dict
        ``data`` leaves the context unchanged -- see
        :meth:`accumulate_context`'s own docstring for the exact rules).
        Every subsequent step receives that running context as its own
        ``metadata`` argument -- so a later step can see an earlier
        step's output, but never the reverse.

        Metadata translation (Step 6): immediately before each step's
        ``ServiceSkill.execute(...)`` call, the running context is passed
        through :meth:`translate_metadata` (``step``-aware, e.g. the
        documented ``PRICE`` -> ``ENTRY_PRICE`` copy for
        ``risk_management_service``); only the *translated* copy is
        passed as that step's ``metadata`` argument. The running context
        itself (``current_context``) is untouched by translation --
        :meth:`accumulate_context` keeps folding based on
        ``current_context`` and the step's ``ServiceResult``, exactly as
        in Step 5, so a per-step translation never leaks into what later
        steps see as their starting context.

        No retry, no skip policy, no branching, no replanning, no
        dependency-order changes, no Observation, no Memory, no
        Reflection, no DAG/parallel execution -- the steps are walked
        strictly in the order ``plan.steps`` (as produced by
        :meth:`build_plan`) already lists them.

        Args:
            plan: The already-built ``ExecutionPlan`` to run.

        Returns:
            The ``ServiceResult`` returned by each step's
            ``ServiceSkill.execute(...)`` call, in the same order as
            ``plan.steps``. A business failure (``ServiceResult.fail()``)
            is collected exactly like a success -- it is not retried and
            does not abort the remaining steps.

        Raises:
            GoalPlannerError: If a ``PlanStep.service_name`` has no
                corresponding entry in ``self._service_skills``, or if
                calling ``ServiceSkill.execute(...)`` itself raises an
                unexpected exception (wrapped here, not left to
                propagate raw).
        """
        results: List[ServiceResult] = []
        current_context: Dict[str, Any] = dict(plan.goal.metadata)

        for step in plan.steps:
            skill = self._service_skills.get(step.service_name)
            if skill is None:
                raise GoalPlannerError(
                    f"execute_plan: no ServiceSkill registered for "
                    f"service_name='{step.service_name}'",
                    details={"service_name": step.service_name},
                )

            translated_metadata = self.translate_metadata(step, current_context)

            try:
                result = skill.execute(
                    user_input="",
                    metadata=translated_metadata,
                    agent_name="GoalPlanner",
                    provider_name="planner",
                    request_id="",
                )
            except Exception as exc:  # noqa: BLE001 -- deliberately broad,
                # wrapped per Step 4 error-handling contract: any
                # unexpected exception from a ServiceSkill call becomes a
                # GoalPlannerError, not a raw propagation.
                raise GoalPlannerError(
                    f"execute_plan: unexpected exception executing "
                    f"service_name='{step.service_name}': {exc}",
                    details={"service_name": step.service_name},
                ) from exc

            # Business failure (ServiceResult.fail()) is collected as-is
            # -- not retried, not treated as abort. See module docstring
            # decision #4.
            results.append(result)

            # Step 5: fold this step's output into the running context so
            # later steps (not this one) can see it. Unchanged by Step 6
            # -- folds `current_context` (pre-translation) + `result`,
            # exactly as before; `translated_metadata` is never folded
            # back in.
            current_context = self.accumulate_context(current_context, result)

        return results

    def translate_metadata(
        self,
        step: PlanStep,
        accumulated_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Translate the running context into what one step's
        ``ServiceSkill`` should receive as its ``metadata`` argument.

        Pure, side-effect-free, step-aware only (LOCKED baseline, Step
        6): never mutates ``accumulated_context`` -- always returns a
        new dict. Default behavior is a plain copy
        (``dict(accumulated_context)``); the only deviation is the one
        explicit rule below, already documented at the L11/L13 layer
        (see ``Core.analysis_pipeline.AnalysisPipeline.
        _prepare_risk_management_context``'s own ``PRICE`` ->
        ``ENTRY_PRICE`` copy, which this reproduces for the
        ``risk_management_service`` step only -- not that method's other
        four simulation-default fields, which are out of scope here).

        Translation rule (the only one implemented):
            If ``step.service_name == "risk_management_service"`` and
            ``MetadataKeys.PRICE`` is present in ``accumulated_context``
            with a non-``None`` value, and ``MetadataKeys.ENTRY_PRICE``
            is not already present, copy the ``PRICE`` value to
            ``ENTRY_PRICE`` in the returned dict. ``PRICE`` itself is
            left untouched (both keys are present in the result). An
            already-present ``ENTRY_PRICE`` is never overwritten.

        No general translation engine, no mapping registry, no pattern
        matching, no inference, no validation -- one ``if``, nothing
        else.

        Args:
            step: The ``PlanStep`` about to be executed. Only
                ``step.service_name`` is consulted.
            accumulated_context: The running context so far (as
                maintained by :meth:`execute_plan`, via
                :meth:`accumulate_context`). Never mutated.

        Returns:
            A new ``dict``: a copy of ``accumulated_context``, with the
            ``PRICE`` -> ``ENTRY_PRICE`` copy applied when the rule
            above matches.
        """
        translated = dict(accumulated_context)

        if step.service_name == "risk_management_service":
            price = accumulated_context.get(MetadataKeys.PRICE)
            if price is not None and MetadataKeys.ENTRY_PRICE not in accumulated_context:
                translated[MetadataKeys.ENTRY_PRICE] = price

        return translated

    def accumulate_context(
        self,
        accumulated_context: Dict[str, Any],
        result: ServiceResult,
    ) -> Dict[str, Any]:
        """Fold one step's ``ServiceResult`` into the running context.

        Pure, side-effect-free merge only (LOCKED baseline, Step 5):
        never mutates ``accumulated_context`` -- always returns a new
        dict. Called by :meth:`execute_plan` after each step's
        ``ServiceSkill.execute(...)`` returns, so later steps can see
        earlier steps' output; it does not resolve, validate, translate,
        or reorder anything (that is :meth:`translate_metadata`, a
        future stage).

        Rules:
            1. ``result.success is False`` -> return
               ``accumulated_context`` unchanged (a business failure
               contributes nothing).
            2. ``result.data`` is not a ``dict`` -> return
               ``accumulated_context`` unchanged (nothing to merge).
            3. Otherwise -> return a new dict equivalent to
               ``{**accumulated_context, **result.data}`` -- keys from
               ``result.data`` overwrite same-named keys already in
               ``accumulated_context``.

        Args:
            accumulated_context: The context accumulated so far. Never
                mutated.
            result: The ``ServiceResult`` just returned by a step's
                ``ServiceSkill.execute(...)`` call.

        Returns:
            A new ``dict`` -- either an unchanged copy-equivalent of
            ``accumulated_context`` (cases 1-2 above; the same object is
            returned since it is never mutated and nothing changes) or
            the merged result (case 3).
        """
        if not result.success:
            return accumulated_context

        if not isinstance(result.data, dict):
            return accumulated_context

        return {**accumulated_context, **result.data}

    def build_workflow(
        self,
        name: str,
        description: str,
        tasks: Iterable[Task],
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Workflow:
        """Construct and return a ``Workflow`` value object from
        already-built ``Task`` instances.

        Phase 4 Sprint 34 (Planner -> Workflow Integration): the first
        connection between ``GoalPlanner`` (planning) and
        ``Orchestration.workflow.Workflow`` (an isolated subsystem
        until now). This method does nothing beyond validating its
        four arguments -- with the same validation philosophy already
        used by ``Orchestration.task.Task`` and
        ``Orchestration.workflow.Workflow`` themselves (explicit
        ``isinstance``/emptiness checks, one descriptive error per
        rejected argument) -- and then constructing a ``Workflow``
        from them. It performs no execution, no scheduling, no
        preparation, and no orchestration of any kind:
        ``WorkflowEngine.prepare()``, ``WorkflowExecutionCoordinator.
        execute_workflow()``, and ``Executor.execute()`` are never
        called, and this module never imports any of those three
        classes (or ``AutonomousHost``/``AutonomousScheduler``).

        ``tasks`` is consumed exactly once, in the order the caller
        supplies it, into a fresh ``tuple`` -- mirroring ``Workflow``'s
        own "preserve order, allow duplicates, never deduplicate"
        contract exactly (see ``Orchestration.workflow.Workflow``'s
        own docstring); duplicate ``Task`` instances (by value, by
        ``task_id``, or the exact same object referenced more than
        once) are all accepted unchanged. ``metadata`` is copied into
        a brand-new ``dict`` before being handed to ``Workflow`` (or
        defaulted to a brand-new empty ``dict`` when ``None``) so that
        the caller's original mapping can be freely mutated afterward
        with no effect on the returned ``Workflow`` -- on top of
        ``Workflow.__post_init__``'s own independent
        ``MappingProxyType`` freeze, which still applies exactly as it
        always has.

        Each call to this method builds and returns a brand-new,
        independent ``Workflow`` -- this method holds no state of its
        own (it reads and writes nothing on ``self``), so two calls
        with identical arguments still produce two distinct
        ``Workflow`` instances, each with its own auto-minted
        ``workflow_id`` (via ``Workflow``'s own ``uuid4``
        ``default_factory``, unchanged and untouched here).

        Args:
            name: A short, human-readable label for the workflow. Must
                be a non-empty ``str`` (whitespace-only is rejected,
                mirroring ``Task``/``Workflow``'s own ``name`` check).
            description: A longer, human-readable description of the
                workflow. Must be a ``str`` (may be empty).
            tasks: The ordered group of already-built ``Task``
                instances this workflow should describe. Must be a
                non-string iterable of ``Task`` instances -- may be
                empty (an empty ``Workflow`` is valid, exactly as
                ``Orchestration.workflow.Workflow`` itself already
                allows via its own ``tasks`` default).
            metadata: Optional workflow-specific data. Must be a
                ``Mapping`` if supplied; ``None`` (the default) is
                treated as an empty mapping.

        Returns:
            A new, fully-validated ``Workflow`` instance wrapping
            ``name``, ``description``, the materialized ``tasks``
            tuple, and a defensive copy of ``metadata``.

        Raises:
            GoalPlannerError: if ``name`` is not a non-empty ``str``;
                if ``description`` is not a ``str``; if ``tasks`` is
                not a non-string iterable, or contains any item that
                is not a ``Task`` instance; or if ``metadata`` is
                neither ``None`` nor a ``Mapping``. Wraps (rather than
                lets propagate raw) any ``Orchestration.workflow.
                WorkflowError`` ``Workflow.__post_init__`` itself would
                otherwise raise, so every rejection surfaces through
                this method's own ``GoalPlannerError``, consistently.
        """
        if not isinstance(name, str) or not name.strip():
            raise GoalPlannerError(
                f"build_workflow requires a non-empty str 'name'; got "
                f"{name!r}"
            )

        if not isinstance(description, str):
            raise GoalPlannerError(
                f"build_workflow requires 'description' to be a str; "
                f"got {description!r}"
            )

        if isinstance(tasks, (str, bytes)) or not hasattr(tasks, "__iter__"):
            raise GoalPlannerError(
                f"build_workflow requires 'tasks' to be an iterable of "
                f"Task instances; got {tasks!r}"
            )

        materialized_tasks = tuple(tasks)
        for item in materialized_tasks:
            if not isinstance(item, Task):
                raise GoalPlannerError(
                    f"build_workflow requires every item in 'tasks' to "
                    f"be a Task instance; got {item!r}"
                )

        if metadata is None:
            materialized_metadata: Dict[str, Any] = {}
        elif isinstance(metadata, Mapping):
            materialized_metadata = dict(metadata)
        else:
            raise GoalPlannerError(
                f"build_workflow requires 'metadata' to be a Mapping "
                f"or None; got {metadata!r}"
            )

        try:
            return Workflow(
                name=name,
                description=description,
                tasks=materialized_tasks,
                metadata=materialized_metadata,
            )
        except Exception as exc:  # noqa: BLE001 -- deliberately broad,
            # matches the same wrap-not-propagate contract already
            # used by execute_plan() above: every rejection surfaces
            # through GoalPlannerError, never a raw WorkflowError (or
            # any other unexpected exception).
            raise GoalPlannerError(
                f"build_workflow: Workflow construction failed: {exc}"
            ) from exc