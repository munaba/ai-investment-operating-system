from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from typing import List, Optional, Tuple

from Core.exceptions import AgentError


class AutonomousAgentError(AgentError):
    """Raised when AutonomousAgent construction is given an invalid
    (missing/None) component reference.

    Mirrors the existing exception hierarchy (AgentError) used elsewhere
    in the codebase (ReflectionError, DecisionEngineError,
    DecisionPolicyError, PolicyGuardError, ExecutionIntentError,
    ExecutionPlannerError, ExecutionCoordinatorError,
    PortfolioEngineError, PortfolioRiskError, LearningLoopError),
    rather than deriving from the bare Exception class.
    """
    pass


class AutonomousAgentStatus(Enum):
    """Internal lifecycle status for AutonomousAgent (Phase 2, Sprint 1).

    This is a dedicated lifecycle enum for the autonomous run loop that
    a *future* sprint will build on top of AutonomousAgent. It is
    intentionally separate from ``Agents.state.AgentState``:
    ``AgentState`` models the per-turn call state of a single agent
    invocation (IDLE/THINKING/CALLING_TOOL/WAITING_PROVIDER/
    RESPONDING/ERROR) and is locked by its own regression suite
    (Tests/test_stage8_6_baseagent_taxonomy.py asserts it has exactly
    six members and gains no new ones). Adding RUNNING/PAUSED/STOPPED
    to that enum would both violate that lock and conflate two
    different concepts. No existing enum in the project models an
    autonomous run-loop lifecycle, so a new one is introduced here
    rather than duplicating/overloading ``AgentState``.

    Sprint 1 only *declares* this state; nothing transitions it yet
    (no run/step/pause/resume/cancel exists in this sprint).
    """

    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPED = auto()
    ERROR = auto()


@dataclass(frozen=True)
class AutonomousCycleResult:
    """Immutable summary of exactly one ``AutonomousAgent.step()`` cycle
    (Phase 2, Sprint 2).

    Deliberately minimal, following the same additive-result-object
    convention as ``LearningLoopResult``/``PortfolioRiskResult``/etc.
    elsewhere in Orchestration: it reports only whether the cycle
    succeeded, when it happened, and which iteration number it was.
    It never exposes DecisionEngine, DecisionPolicy, PortfolioEngine,
    or LearningLoop internals -- those remain
    ``RuntimeAnalysisPipeline``'s (and its aggregated stages') own
    concern, not part of ``AutonomousAgent``'s public surface.

    Attributes:
        success: whether the delegated
            ``RuntimeAnalysisPipeline.run()`` call completed without
            raising.
        timestamp: wall-clock ``time.time()`` epoch seconds at which
            this cycle finished (same convention as
            ``Orchestration.memory``/``Orchestration.observation``
            ``recorded_at`` fields).
        iteration: the agent's ``iteration_count`` as of this result
            (post-increment on success; unchanged on failure).
    """

    success: bool
    timestamp: float
    iteration: int


@dataclass(frozen=True)
class AutonomousAgentSnapshot:
    """Immutable, point-in-time export of ``AutonomousAgent``'s own
    session state (Phase 3, Sprint 13).

    Following the same additive-result/value-object convention as
    ``AutonomousCycleResult`` elsewhere in this file (and
    ``LearningLoopResult``/``PortfolioRiskResult``/etc. across
    Orchestration): a frozen dataclass that reports state, and nothing
    but state. It never references ``RuntimeAnalysisPipeline``,
    ``GoalPlanner``, or any of the ten aggregated L18-L27 stage
    components -- those remain collaborators of ``AutonomousAgent``
    itself, not part of the autonomous *session*'s own state, and are
    therefore excluded from the snapshot entirely (see
    ``AutonomousAgent.snapshot()`` for the rest of the rationale).

    This is a snapshot of state only -- it carries no behavior of its
    own (no methods beyond the ones ``@dataclass(frozen=True)``
    generates), performs no execution, and is not a mechanism for
    restoring, reloading, or resuming an ``AutonomousAgent`` from. No
    ``save()``/``load()``/``restore()``/``serialize()``/
    ``deserialize()`` method exists here or anywhere else in this
    file -- persistence of any kind (files, databases, network) is
    explicitly out of scope for Sprint 13.

    Attributes:
        status: the agent's ``AutonomousAgentStatus`` at the moment
            ``snapshot()`` was called.
        iteration_count: the agent's ``iteration_count`` at that
            moment.
        last_cycle_at: the agent's ``last_cycle_at`` at that moment,
            or ``None`` if no cycle had completed yet.
        goal: the agent's ``goal`` reference at that moment, or
            ``None`` if no goal was set. Held exactly as-is (same
            object reference, unwrapped/uncopied) -- like every other
            duck-typed goal/plan/context reference in this file, this
            class never imports or type-checks against a specific
            goal type.
        current_plan: the agent's ``current_plan`` reference at that
            moment, or ``None`` if no plan was built. Held exactly
            as-is, same convention as ``goal`` above.
        session_id: the agent's ``session_id`` at that moment, or
            ``None`` if no session was active.
        session_started_at: the agent's ``session_started_at`` at
            that moment, or ``None`` if no session was active.
    """

    status: AutonomousAgentStatus
    iteration_count: int
    last_cycle_at: Optional[float]
    goal: Optional[object]
    current_plan: Optional[object]
    session_id: Optional[str]
    session_started_at: Optional[datetime]


class AutonomousAgent:
    """Stage L28A -- AutonomousAgent Foundation (Phase 2, Sprint 1 & 2).

    Aggregates references to the ten existing, already-built Decision
    Pipeline / Learning stages (L18-L27) so that a future stage can
    address them as a single unit. It still does not call, invoke, or
    otherwise exercise any of those ten aggregated components itself
    -- ``step()`` (Sprint 2) delegates a full analysis cycle to a
    caller-supplied ``RuntimeAnalysisPipeline`` instead, which is what
    already exercises Reflection/DecisionEngine/.../LearningLoop
    end-to-end (see ``Orchestration.runtime_analysis_pipeline``).

    Sprint 1 change (Phase 2):
        AutonomousAgent is no longer a frozen dataclass. It is now a
        normal, mutable class so that a future sprint can evolve its
        lifecycle state over time. The ten-component constructor
        signature, keyword-argument shape, and None-validation
        behavior are unchanged from Stage L28A.

    Sprint 2 change (Phase 2):
        Added exactly one public method, ``step()``: one deterministic
        autonomous cycle, delegated to a ``RuntimeAnalysisPipeline``.
        No loop, no scheduling, no threads/async, no retry, no
        recovery. Still no ``execute``, ``start``, ``pause``,
        ``resume``, or ``cancel`` method of any kind -- those remain
        out of scope for future sprints.

    Sprint 3 change (Phase 2, Dependency Injection Cleanup):
        ``RuntimeAnalysisPipeline`` is now supplied via constructor
        injection (an 11th constructor argument, validated non-None
        like the other ten) and held privately as
        ``self._runtime_analysis_pipeline``, instead of Sprint 2's
        per-call method injection. ``step()``'s call shape changes
        from ``step(runtime_analysis_pipeline, context)`` to
        ``step(context)`` accordingly -- see ``step()``'s own
        docstring for the full rationale. No other behavior changes.

    Sprint 4 change (Phase 2):
        Added exactly one public method, ``run()``: a deterministic
        driver that calls ``step(context)`` exactly ``max_iterations``
        times and returns a ``tuple`` of the collected
        ``AutonomousCycleResult`` instances. ``run()`` introduces no
        behavior of its own beyond input validation, looping, and
        result collection -- every status transition, iteration-count
        update, and pipeline delegation is still performed exclusively
        by ``step()``. No loop, no scheduling, no threads/async, no
        retry, no approval handling, no pause/resume/cancel of any
        kind. Still no ``execute``, ``start``, ``pause``, ``resume``,
        or ``cancel`` method -- those remain out of scope for future
        sprints.

    Sprint 5 change (Phase 2, Goal Ownership):
        Added exactly two public methods, ``set_goal(goal)`` and
        ``clear_goal()``, giving the previously read-only ``goal``
        placeholder (Sprint 1) a way to be mutated. Goal storage only
        -- no planning, no automatic goal generation, no GoalPlanner
        integration of any kind. Setting or clearing the goal is pure
        in-memory state mutation: it never calls
        ``RuntimeAnalysisPipeline``, ``step()``, ``run()``,
        Reflection, DecisionEngine, or GoalPlanner, and never changes
        ``status``, ``iteration_count``, or ``last_cycle_at``.

    Sprint 6 change (Phase 2, Session Metadata):
        Added exactly two public methods, ``start_session()`` and
        ``end_session()``, plus two read-only properties,
        ``session_id`` and ``session_started_at``, giving every
        autonomous session a lightweight identity. Session metadata
        only -- no persistence (the id/timestamp live purely as
        in-memory instance attributes), no scheduling, and no
        GoalPlanner integration of any kind. Starting or ending a
        session is pure in-memory state mutation: it never calls
        ``RuntimeAnalysisPipeline``, ``step()``, or ``run()``, and
        never changes ``goal``, ``status``, ``iteration_count``, or
        ``last_cycle_at``.

    Sprint 7 change (Phase 2, GoalPlanner Integration):
        ``GoalPlanner`` (the existing ``Orchestration.planner.
        GoalPlanner``, unmodified) is now supplied via constructor
        injection (a 12th constructor argument, validated non-None
        exactly like the other eleven) and held privately as
        ``self._goal_planner`` -- the same pattern Sprint 3 already
        established for ``runtime_analysis_pipeline``. Added exactly
        one public method, ``plan_goal()``: requires a goal to already
        be set, then delegates to
        ``self._goal_planner.build_plan(self.goal)`` and returns its
        result unchanged. Planning remains explicit -- ``set_goal()``
        (Sprint 5) still only stores the goal and never triggers
        planning on its own. ``plan_goal()`` never executes the
        resulting plan, never touches ``RuntimeAnalysisPipeline``,
        ``step()``, or ``run()``, and never changes ``goal``,
        ``status``, ``iteration_count``, ``last_cycle_at``,
        ``session_id``, or ``session_started_at``.

    Sprint 8 change (Phase 2, ExecutionPlan Ownership):
        ``plan_goal()`` (Sprint 7) now additionally stores the
        ``ExecutionPlan`` it receives from the injected
        ``GoalPlanner`` as ``self._current_plan``, exposed read-only
        via the new ``current_plan`` property -- still returning that
        exact same object to the caller, unwrapped and uncopied. Added
        exactly one further public method, ``clear_plan()``, resetting
        ``current_plan`` back to ``None`` (idempotent, storage only).
        GoalPlanner still owns all plan *creation* logic
        (``build_plan()`` is not reimplemented or duplicated here);
        AutonomousAgent only remembers the most recent result. Plan
        ownership has zero execution side effects: nothing here calls
        ``GoalPlanner.execute_plan()``, ``RuntimeAnalysisPipeline``,
        ``step()``, or ``run()``, and nothing changes ``goal``,
        ``status``, ``iteration_count``, ``last_cycle_at``,
        ``session_id``, or ``session_started_at``.

    Sprint 13 change (Phase 3, Persistent Autonomous State -- Snapshot
    Only):
        Added exactly one public method, ``snapshot()``, returning a
        new immutable ``AutonomousAgentSnapshot`` (a frozen dataclass,
        defined just above this class) that exports only the state
        already owned by ``AutonomousAgent`` -- ``status``,
        ``iteration_count``, ``last_cycle_at``, ``goal``,
        ``current_plan``, ``session_id``, and ``session_started_at``.
        Pure read-only export: no execution, no planning, no lifecycle
        transition, no logging, no new timestamp/UUID generation, and
        no persistence of any kind (no save/load/restore/serialize/
        deserialize method exists anywhere in this file). ``snapshot()``
        never touches ``RuntimeAnalysisPipeline`` or ``GoalPlanner``,
        and calling it has no effect on ``run()``, ``step()``,
        ``pause()``, ``resume()``, ``stop()``, or any other existing
        method's behavior.

    Design constraints (unchanged from Stage L28A unless noted above):
        - Deterministic construction: constructing an AutonomousAgent
          from the same ten references always yields an object
          referencing the same ten components; there is no internal
          randomness, clock, or I/O performed on construction.
        - Pure Python: no threads, no async tasks, no event loop, no
          background/autonomous behaviour of any kind is started by
          this class -- despite the name, "Autonomous" describes what
          a *future* stage may build on top of this foundation, not
          anything this class does itself.
        - No Runtime dependency, no Executor dependency, no Provider
          dependency, no Database dependency, no Service dependency,
          no LLM calls.
        - No imports from any other Orchestration module -- every
          component reference is accepted and held purely by duck
          typing, never imported or type-checked against a specific
          class.
        - Not wired into StockAgent or RuntimeAnalysisPipeline, and
          does not modify either.

    Beyond construction/validation, read-only lifecycle-state access,
    ``step()``, and ``run()``, this class defines no other methods --
    specifically, it exposes no ``execute``, ``start``, ``pause``,
    ``resume``, or ``cancel`` method. Reading a component reference off
    an AutonomousAgent instance (e.g. ``agent.decision_engine``) never
    calls into that component; it is a plain attribute access. Note
    that ``step()`` itself never touches these ten attributes either --
    it delegates entirely to the ``RuntimeAnalysisPipeline`` passed
    into it. ``run()`` in turn never touches these ten attributes or
    the pipeline directly -- it delegates entirely to ``step()``.

    Attributes:
        reflection: the L18 Reflection-stage component reference.
        decision_engine: the L19 DecisionEngine component reference.
        decision_policy: the L20 DecisionPolicy component reference.
        policy_guard: the L21 PolicyGuard component reference.
        execution_intent: the L22 ExecutionIntent component reference.
        execution_planner: the L23 ExecutionPlanner component reference.
        execution_coordinator: the L24 ExecutionCoordinator component
            reference.
        portfolio_engine: the L25 PortfolioEngine component reference.
        portfolio_risk: the L26 PortfolioRisk component reference.
        learning_loop: the L27 LearningLoop component reference.

    Internal lifecycle state (Sprint 1, additive):
        status: current AutonomousAgentStatus (starts at IDLE).
        iteration_count: number of completed autonomous cycles so far
            (starts at 0; nothing increments it in Sprint 1).
        last_cycle_at: timestamp of the last completed cycle, or
            ``None`` if no cycle has run yet (nothing sets it in
            Sprint 1).
        goal: placeholder reference to the agent's current goal, or
            ``None`` if none is set (nothing sets it in Sprint 1).
    """

    def __init__(
        self,
        reflection: object,
        decision_engine: object,
        decision_policy: object,
        policy_guard: object,
        execution_intent: object,
        execution_planner: object,
        execution_coordinator: object,
        portfolio_engine: object,
        portfolio_risk: object,
        learning_loop: object,
        runtime_analysis_pipeline: object,
        goal_planner: object,
    ) -> None:
        for field_name, value in (
            ("reflection", reflection),
            ("decision_engine", decision_engine),
            ("decision_policy", decision_policy),
            ("policy_guard", policy_guard),
            ("execution_intent", execution_intent),
            ("execution_planner", execution_planner),
            ("execution_coordinator", execution_coordinator),
            ("portfolio_engine", portfolio_engine),
            ("portfolio_risk", portfolio_risk),
            ("learning_loop", learning_loop),
            ("runtime_analysis_pipeline", runtime_analysis_pipeline),
            ("goal_planner", goal_planner),
        ):
            if value is None:
                raise AutonomousAgentError(
                    f"AutonomousAgent requires a non-None '{field_name}' "
                    f"component reference"
                )

        self.reflection = reflection
        self.decision_engine = decision_engine
        self.decision_policy = decision_policy
        self.policy_guard = policy_guard
        self.execution_intent = execution_intent
        self.execution_planner = execution_planner
        self.execution_coordinator = execution_coordinator
        self.portfolio_engine = portfolio_engine
        self.portfolio_risk = portfolio_risk
        self.learning_loop = learning_loop

        # Phase 2, Sprint 3: constructor-injected, held privately (not
        # a public dependency attribute like the ten L18-L27 stage
        # references above) since it is step()'s own collaborator, not
        # part of the aggregated-stage surface. See step() docstring
        # for why this is now constructor injection rather than the
        # Sprint 2 method-injection approach.
        self._runtime_analysis_pipeline = runtime_analysis_pipeline

        # Phase 2, Sprint 7: constructor-injected, held privately
        # exactly like runtime_analysis_pipeline above -- it is
        # plan_goal()'s own collaborator, not part of the
        # aggregated-stage public surface. The already-built
        # GoalPlanner singleton (Core.composition_root's
        # _build_goal_planner()) is reused as-is; no second
        # GoalPlanner is ever constructed here.
        self._goal_planner = goal_planner

        # -- Internal lifecycle state (Phase 2, Sprint 1) --------------
        # Minimal state only. No autonomous logic, looping, scheduling,
        # or execution reads/writes any of this in Sprint 1.
        self._status: AutonomousAgentStatus = AutonomousAgentStatus.IDLE
        self._iteration_count: int = 0
        self._last_cycle_at: Optional[float] = None
        self._goal: Optional[object] = None

        # -- Session metadata (Phase 2, Sprint 6) -----------------------
        # Lightweight session identity only. No persistence, no
        # scheduling, no GoalPlanner integration -- see
        # start_session()/end_session() docstrings.
        self._session_id: Optional[str] = None
        self._session_started_at: Optional[datetime] = None

        # -- Plan ownership (Phase 2, Sprint 8) -------------------------
        # Storage only. No execution, no scheduling -- see
        # plan_goal()/clear_plan() docstrings.
        self._current_plan: Optional[object] = None

    @property
    def status(self) -> AutonomousAgentStatus:
        """Current lifecycle status. Read-only in Sprint 1."""
        return self._status

    @property
    def iteration_count(self) -> int:
        """Number of completed autonomous cycles. Read-only in Sprint 1."""
        return self._iteration_count

    @property
    def last_cycle_at(self) -> Optional[float]:
        """Timestamp of the last completed cycle, if any. Read-only in
        Sprint 1."""
        return self._last_cycle_at

    @property
    def goal(self) -> Optional[object]:
        """Placeholder reference to the agent's current goal, if any.
        Mutable via ``set_goal()``/``clear_goal()`` as of Sprint 5 --
        see those methods' docstrings."""
        return self._goal

    def set_goal(self, goal: object) -> None:
        """Replace the agent's current goal (Phase 2, Sprint 5).

        Goal ownership only: this method does nothing beyond storing
        ``goal`` on the instance. It never calls
        ``RuntimeAnalysisPipeline``, ``step()``, ``run()``,
        Reflection, DecisionEngine, or GoalPlanner (GoalPlanner
        integration is explicitly out of scope for this sprint), and
        it never reads or writes ``status``, ``iteration_count``, or
        ``last_cycle_at`` -- those remain exclusively ``step()``'s
        concern.

        Args:
            goal: the new goal value. Accepted as a plain ``object``
                (duck-typed, like the ten L18-L27 dependencies and
                ``context``) -- this class never imports or
                type-checks against any specific goal/GoalPlanner
                type.

        Raises:
            AutonomousAgentError: if ``goal`` is ``None``. Use
                ``clear_goal()`` to reset the goal instead.
        """
        if goal is None:
            raise AutonomousAgentError(
                "AutonomousAgent.set_goal() requires a non-None 'goal' "
                "-- use clear_goal() to reset the goal instead"
            )
        self._goal = goal

    def clear_goal(self) -> None:
        """Reset the agent's current goal back to ``None`` (Phase 2,
        Sprint 5).

        Idempotent: calling this when ``goal`` is already ``None``
        (whether because no goal was ever set, or because it was
        already cleared) is not an error and simply leaves ``goal``
        as ``None``. Like ``set_goal()``, this never touches
        ``status``, ``iteration_count``, ``last_cycle_at``, or the
        constructor-injected ``RuntimeAnalysisPipeline``.
        """
        self._goal = None

    def plan_goal(self) -> object:
        """Build a plan for the current goal via the injected
        ``GoalPlanner`` (Phase 2, Sprint 7; now also stores the result
        as of Sprint 8).

        Planning only: this delegates to
        ``self._goal_planner.build_plan(self.goal)``, stores the
        returned ``ExecutionPlan`` as ``self._current_plan`` (Phase 2,
        Sprint 8), and returns that exact same object -- no wrapping,
        no copying, no transformation. It never executes the
        resulting plan (``GoalPlanner.execute_plan`` is not called
        here), never calls ``RuntimeAnalysisPipeline``, ``step()``,
        or ``run()``, and never changes ``goal``, ``status``,
        ``iteration_count``, ``last_cycle_at``, ``session_id``, or
        ``session_started_at`` -- those remain exclusively their own
        methods' concern. No second ``GoalPlanner`` is constructed:
        this reuses the exact singleton instance supplied to
        ``__init__``.

        Planning is explicit, not automatic: ``set_goal()`` (Sprint 5)
        only ever stores the goal; nothing calls ``plan_goal()`` on
        the caller's behalf, here or anywhere else in this class.

        Calling this again (e.g. after the goal changes) simply
        replaces ``self._current_plan`` with the new result -- no
        history of prior plans is kept.

        Returns:
            Whatever ``self._goal_planner.build_plan(self.goal)``
            returns (e.g. an ``Orchestration.planner.ExecutionPlan``
            for the real ``GoalPlanner``) -- passed straight through,
            and simultaneously stored as ``self.current_plan``.

        Raises:
            AutonomousAgentError: if no goal is currently set
                (``self.goal is None``). Call ``set_goal(...)`` first.
                ``self._current_plan`` is left unchanged when this is
                raised (no build_plan() call was made).
        """
        if self._goal is None:
            raise AutonomousAgentError(
                "AutonomousAgent.plan_goal() requires a goal to be set "
                "first -- call set_goal(...) before plan_goal()"
            )
        plan = self._goal_planner.build_plan(self._goal)
        self._current_plan = plan
        return plan

    @property
    def current_plan(self) -> Optional[object]:
        """The most recently built ``ExecutionPlan``, if any (Phase 2,
        Sprint 8). ``None`` until ``plan_goal()`` has been called
        successfully at least once, or after ``clear_plan()``.
        Mutable via ``plan_goal()``/``clear_plan()`` only -- read-only
        here."""
        return self._current_plan

    def clear_plan(self) -> None:
        """Reset the agent's current plan back to ``None`` (Phase 2,
        Sprint 8).

        Idempotent: calling this when ``current_plan`` is already
        ``None`` (whether because ``plan_goal()`` was never called, or
        because the plan was already cleared) is not an error and
        simply leaves ``current_plan`` as ``None``. Storage only: this
        never calls the injected ``GoalPlanner`` or
        ``RuntimeAnalysisPipeline``, and never changes ``goal``,
        ``status``, ``iteration_count``, ``last_cycle_at``,
        ``session_id``, or ``session_started_at``.
        """
        self._current_plan = None

    def advance_plan(self, context: object) -> object:
        """Advance the currently stored ``current_plan`` by exactly
        one logical step (Phase 2, Sprint 11).

        Execution-chain connector only: this owns no planning logic
        of its own. It never calls the injected ``GoalPlanner``, never
        rebuilds or mutates ``current_plan`` in any way (no plan step
        is marked complete, no progress is tracked -- that mutation
        semantics is explicitly out of scope for this sprint), and
        never creates a new goal. It simply proves the
        ``ExecutionPlan -> AutonomousAgent -> RuntimeAnalysisPipeline``
        chain is connected by delegating one cycle to the same
        constructor-injected ``RuntimeAnalysisPipeline`` singleton
        ``step()`` already uses -- reused exactly as-is, never
        duplicated or reimplemented here.

        Called directly (not via ``step()``), this is a thin
        precondition-checked delegate only: it never touches
        ``goal``, ``session_id``, ``session_started_at``,
        ``iteration_count``, ``last_cycle_at``, or ``status`` --
        those remain exclusively ``step()``'s own concern. When
        ``step()`` instead calls this internally (see ``step()``'s
        own docstring), ``step()``'s surrounding bookkeeping -- the
        ``RUNNING`` transition, the post-cycle ``iteration_count``/
        ``last_cycle_at`` update, and the final ``IDLE``/``ERROR``
        transition -- still applies exactly as before; nothing here
        duplicates or replaces that.

        Args:
            context: the ``ServiceContext``-shaped object to run this
                cycle for, passed straight through to
                ``self._runtime_analysis_pipeline.run(context)``
                unchanged.

        Returns:
            Whatever ``self._runtime_analysis_pipeline.run(context)``
            returns, passed straight through, unwrapped and uncopied.

        Raises:
            AutonomousAgentError: if ``current_plan`` is ``None`` (no
                plan to advance -- call ``plan_goal()`` first), or if
                ``status`` is ``STOPPED``, ``PAUSED``, or ``ERROR``.
                In every one of those cases, the injected
                ``RuntimeAnalysisPipeline`` is never reached.
        """
        if self._current_plan is None:
            raise AutonomousAgentError(
                "AutonomousAgent.advance_plan() requires a current_plan "
                "to be set -- call plan_goal() first"
            )
        if self._status is AutonomousAgentStatus.STOPPED:
            raise AutonomousAgentError(
                "AutonomousAgent.advance_plan() refused: agent status "
                "is STOPPED, this is a terminal lifecycle state"
            )
        if self._status is AutonomousAgentStatus.PAUSED:
            raise AutonomousAgentError(
                "AutonomousAgent.advance_plan() refused: agent status "
                "is PAUSED (call resume() first)"
            )
        if self._status is AutonomousAgentStatus.ERROR:
            raise AutonomousAgentError(
                "AutonomousAgent.advance_plan() refused: agent status "
                "is ERROR, no retry/recovery implemented"
            )
        return self._runtime_analysis_pipeline.run(context)

    @property
    def session_id(self) -> Optional[str]:
        """Identity of the current autonomous session, if any (Phase
        2, Sprint 6). ``None`` when no session is active. Mutable via
        ``start_session()``/``end_session()`` only -- read-only
        here."""
        return self._session_id

    @property
    def session_started_at(self) -> Optional[datetime]:
        """UTC ``datetime`` at which the current session was started,
        if any (Phase 2, Sprint 6). ``None`` when no session is
        active. Mutable via ``start_session()``/``end_session()``
        only -- read-only here."""
        return self._session_started_at

    def start_session(self) -> str:
        """Begin a new autonomous session (Phase 2, Sprint 6).

        Session metadata only: this generates and stores an identity
        for the session, nothing more. It never calls
        ``RuntimeAnalysisPipeline``, ``step()``, or ``run()``, and it
        never reads or writes ``goal``, ``status``,
        ``iteration_count``, or ``last_cycle_at`` -- those remain
        exclusively their own methods' concern. No persistence (the
        session id/timestamp are held only as in-memory attributes on
        this instance) and no scheduling of any kind.

        Behavior:
            1. Generates a new session id via ``uuid.uuid4()`` and
               stores its string form as ``self._session_id``.
            2. Records ``self._session_started_at`` as the current
               UTC ``datetime`` (timezone-aware, via
               ``datetime.now(timezone.utc)``).
            3. Returns the newly generated session id.

        Returns:
            The newly generated session id (``str``).

        Raises:
            AutonomousAgentError: if a session is already active
                (``session_id`` is not ``None``). Call
                ``end_session()`` first.
        """
        if self._session_id is not None:
            raise AutonomousAgentError(
                "AutonomousAgent.start_session() refused: a session "
                f"({self._session_id!r}) is already active -- call "
                "end_session() first"
            )
        self._session_id = str(uuid.uuid4())
        self._session_started_at = datetime.now(timezone.utc)
        return self._session_id

    def end_session(self) -> None:
        """End the current autonomous session, if any (Phase 2,
        Sprint 6).

        Idempotent: calling this when no session is active (whether
        because ``start_session()`` was never called, or because the
        session was already ended) is not an error and simply leaves
        ``session_id``/``session_started_at`` as ``None``. Like
        ``start_session()``, this never touches ``goal``, ``status``,
        ``iteration_count``, ``last_cycle_at``, or the
        constructor-injected ``RuntimeAnalysisPipeline``.

        Behavior:
            Clears both ``self._session_id`` and
            ``self._session_started_at`` back to ``None``.
        """
        self._session_id = None
        self._session_started_at = None

    def pause(self) -> None:
        """Pause the agent's lifecycle while a cycle is in progress
        (Phase 2, Sprint 9).

        Lifecycle control only: this changes ``status`` from
        ``RUNNING`` to ``PAUSED`` and nothing else. It never calls
        ``RuntimeAnalysisPipeline``, ``step()``, or ``run()``, and it
        never touches ``goal``, ``current_plan``, ``session_id``,
        ``session_started_at``, ``iteration_count``, or
        ``last_cycle_at`` -- every one of those is preserved exactly
        as it was the instant before ``pause()`` was called.

        Allowed transition:
            RUNNING -> PAUSED

        Behavior:
            Sets ``self._status`` to ``AutonomousAgentStatus.PAUSED``.
            Nothing else is read or written.

        Raises:
            AutonomousAgentError: if ``status`` is not currently
                ``RUNNING`` (e.g. it is ``IDLE``, already ``PAUSED``,
                ``STOPPED``, or ``ERROR``). There is no forced/partial
                pause -- the agent must actually be mid-cycle.
        """
        if self._status is not AutonomousAgentStatus.RUNNING:
            raise AutonomousAgentError(
                "AutonomousAgent.pause() refused: agent status is "
                f"{self._status.name}, only allowed while RUNNING"
            )
        self._status = AutonomousAgentStatus.PAUSED

    def resume(self) -> None:
        """Resume the agent's lifecycle after a ``pause()`` (Phase 2,
        Sprint 9).

        Lifecycle control only: this changes ``status`` from
        ``PAUSED`` back to ``RUNNING`` and nothing else. It never
        calls ``RuntimeAnalysisPipeline``, ``step()``, or ``run()``,
        and it never touches ``goal``, ``current_plan``,
        ``session_id``, ``session_started_at``, ``iteration_count``,
        or ``last_cycle_at`` -- none of those are read or modified by
        this method.

        Allowed transition:
            PAUSED -> RUNNING

        Behavior:
            Sets ``self._status`` to
            ``AutonomousAgentStatus.RUNNING``. Nothing else is read or
            written -- in particular, timestamps and
            ``iteration_count`` are left exactly as ``pause()`` left
            them.

        Raises:
            AutonomousAgentError: if ``status`` is not currently
                ``PAUSED`` (e.g. it is ``IDLE``, already ``RUNNING``,
                ``STOPPED``, or ``ERROR``).
        """
        if self._status is not AutonomousAgentStatus.PAUSED:
            raise AutonomousAgentError(
                "AutonomousAgent.resume() refused: agent status is "
                f"{self._status.name}, only allowed while PAUSED"
            )
        self._status = AutonomousAgentStatus.RUNNING

    def stop(self) -> None:
        """Terminate the agent's lifecycle (Phase 2, Sprint 10).

        Lifecycle control only: this changes ``status`` to
        ``STOPPED`` and nothing else. It never calls
        ``RuntimeAnalysisPipeline``, ``GoalPlanner``, ``step()``, or
        ``run()``, and it never touches ``goal``, ``current_plan``,
        ``session_id``, ``session_started_at``, ``iteration_count``,
        or ``last_cycle_at`` -- every one of those is preserved
        exactly as it was the instant before ``stop()`` was called.
        There is no automatic cleanup of any kind: the goal is not
        cleared, the plan is not cleared, and the session is not
        ended -- ``clear_goal()``/``clear_plan()``/``end_session()``
        remain separate, explicit calls a caller may make on its own,
        before or after ``stop()``.

        Naming note: this project's existing
        ``AutonomousAgentStatus`` enum (Sprint 1) already declares a
        ``STOPPED`` terminal member -- unused until now. Sprint 10
        reuses that existing member (and names this method to match,
        ``stop()``) rather than introducing a second, parallel
        "cancelled" vocabulary alongside it.

        Allowed transitions:
            IDLE -> STOPPED
            RUNNING -> STOPPED
            PAUSED -> STOPPED

        Idempotent:
            STOPPED -> STOPPED is a no-op (calling ``stop()`` again
            once already stopped simply leaves ``status`` as
            ``STOPPED``; it is not an error).

        Forbidden:
            ERROR -> STOPPED raises ``AutonomousAgentError`` (a
            failed cycle has no clean way to be "terminated" -- it is
            already terminal in its own right, and this class still
            implements no error-recovery path). Once ``stop()`` has
            succeeded, ``pause()``/``resume()`` are also refused from
            ``STOPPED`` by their own existing RUNNING/PAUSED-only
            guards -- no separate check is needed here for that.

        Raises:
            AutonomousAgentError: if ``status`` is currently
                ``ERROR``.
        """
        if self._status is AutonomousAgentStatus.STOPPED:
            return
        if self._status is AutonomousAgentStatus.ERROR:
            raise AutonomousAgentError(
                "AutonomousAgent.stop() refused: agent status is "
                "ERROR, a failed cycle cannot be terminated (no "
                "error-recovery path exists)"
            )
        self._status = AutonomousAgentStatus.STOPPED

    def snapshot(self) -> AutonomousAgentSnapshot:
        """Export a point-in-time, immutable snapshot of the agent's
        own session state (Phase 3, Sprint 13).

        Pure read-only export: this method performs no execution, no
        planning, no lifecycle transition, and no logging. It never
        calls ``RuntimeAnalysisPipeline``, ``GoalPlanner``, ``step()``,
        ``run()``, or any of the ten aggregated L18-L27 stage
        components, and it never generates a new timestamp or UUID of
        its own -- every value returned is read directly off this
        instance's existing state, exactly as it stood the instant
        ``snapshot()`` was called.

        Only state already owned by ``AutonomousAgent`` is included --
        ``status``, ``iteration_count``, ``last_cycle_at``, ``goal``,
        ``current_plan``, ``session_id``, and ``session_started_at``.
        No new field is invented, and no value is derived or computed
        beyond what those seven properties already expose.

        Calling this repeatedly returns a fresh, independent
        ``AutonomousAgentSnapshot`` object each time -- never the same
        instance twice, and never a live view back onto this agent.
        Since ``AutonomousAgentSnapshot`` is itself a frozen dataclass,
        the returned object cannot be used to mutate this agent's
        state.

        Returns:
            A new ``AutonomousAgentSnapshot`` reflecting this agent's
            current ``status``, ``iteration_count``, ``last_cycle_at``,
            ``goal``, ``current_plan``, ``session_id``, and
            ``session_started_at``.
        """
        return AutonomousAgentSnapshot(
            status=self._status,
            iteration_count=self._iteration_count,
            last_cycle_at=self._last_cycle_at,
            goal=self._goal,
            current_plan=self._current_plan,
            session_id=self._session_id,
            session_started_at=self._session_started_at,
        )

    def restore(self, snapshot: AutonomousAgentSnapshot) -> None:
        """Restore this agent's own session state from a previously
        exported ``AutonomousAgentSnapshot`` (Phase 3, Sprint 14).

        The mirror image of ``snapshot()``: where ``snapshot()`` reads
        this instance's seven session-state fields out into a fresh,
        immutable ``AutonomousAgentSnapshot``, ``restore()`` copies
        those same seven fields (``status``, ``iteration_count``,
        ``last_cycle_at``, ``goal``, ``current_plan``, ``session_id``,
        ``session_started_at``) from a given snapshot back onto this
        instance, in place. It mutates ``self`` directly rather than
        constructing a new ``AutonomousAgent`` -- there is no
        alternate constructor here, the ten L18-L27 collaborators and
        the injected ``RuntimeAnalysisPipeline``/``GoalPlanner`` are
        never touched, and the Composition Root that originally wired
        this agent together is completely uninvolved.

        Pure state restoration: this method performs no execution, no
        planning, no derivation, and no reconstruction. It never calls
        ``RuntimeAnalysisPipeline``, ``GoalPlanner``, ``step()``,
        ``run()``, ``advance_plan()``, or any of the ten aggregated
        L18-L27 stage components, and it never generates a new
        timestamp or UUID of its own -- every value written is taken
        directly from ``snapshot``, exactly as it was captured.

        The supplied ``snapshot`` is only ever read from, never
        written to -- as a frozen dataclass it could not be mutated
        even if this method tried, and it isn't retained by reference
        anywhere on ``self`` afterward either.

        Args:
            snapshot: an ``AutonomousAgentSnapshot`` previously
                produced by this (or any) ``AutonomousAgent``'s
                ``snapshot()`` call.

        Raises:
            AutonomousAgentError: if ``snapshot`` is ``None``, or is
                any object that is not an instance of
                ``AutonomousAgentSnapshot`` (e.g. a plain object, a
                dict, or a snapshot-shaped duck-typed stand-in --
                unlike every other duck-typed reference elsewhere in
                this file, ``restore()`` deliberately requires the
                exact, immutable Sprint 13 snapshot type).
        """
        if snapshot is None:
            raise AutonomousAgentError(
                "AutonomousAgent.restore() requires a non-None "
                "'snapshot'"
            )
        if not isinstance(snapshot, AutonomousAgentSnapshot):
            raise AutonomousAgentError(
                "AutonomousAgent.restore() requires an "
                "AutonomousAgentSnapshot instance, got "
                f"{type(snapshot).__name__!r}"
            )

        self._status = snapshot.status
        self._iteration_count = snapshot.iteration_count
        self._last_cycle_at = snapshot.last_cycle_at
        self._goal = snapshot.goal
        self._current_plan = snapshot.current_plan
        self._session_id = snapshot.session_id
        self._session_started_at = snapshot.session_started_at

    def step(
        self,
        context: object,
    ) -> AutonomousCycleResult:
        """Perform exactly ONE deterministic autonomous cycle (Phase 2,
        Sprint 2; call shape updated in Sprint 3).

        One invocation == one cycle. This method never loops, sleeps,
        retries, schedules, spawns threads, uses async, calls itself,
        or calls a ``run()`` method (none exists on this class) --
        every one of those is out of scope and belongs to a future
        sprint's autonomous loop, built on top of this single cycle
        primitive.

        Constructor injection, not method injection (Phase 2, Sprint 3):
            ``RuntimeAnalysisPipeline`` is now supplied once, at
            construction time (see ``__init__``'s
            ``runtime_analysis_pipeline`` parameter), and held as
            ``self._runtime_analysis_pipeline``. Sprint 2 originally
            accepted it as a ``step()`` argument instead; Sprint 3
            moves it to the constructor so every caller of ``step()``
            -- ``ApplicationGraph``, a future scheduler, etc. -- only
            has to supply ``context``, matching the target dependency
            direction ``ApplicationGraph -> AutonomousAgent ->
            RuntimeAnalysisPipeline``. The dependency direction is
            still strictly AutonomousAgent -> RuntimeAnalysisPipeline,
            never the reverse: this class only ever calls
            ``self._runtime_analysis_pipeline.run(context)``, and
            ``RuntimeAnalysisPipeline`` has no knowledge of
            ``AutonomousAgent`` at all.

        Duck-typed, like the ten aggregated-stage dependencies:
            ``runtime_analysis_pipeline`` (constructor arg) and
            ``context`` are accepted as plain ``object`` (not
            imported/type-checked against
            ``Orchestration.runtime_analysis_pipeline
            .RuntimeAnalysisPipeline`` or
            ``Services.service_context.ServiceContext``), preserving
            this module's existing constraint of importing nothing
            else from Orchestration or Services. The only requirement
            is that it expose a ``run(context)`` method, exactly
            ``RuntimeAnalysisPipeline.run`` -- reused exactly as-is,
            never reimplemented, redesigned, or duplicated here.

        Lifecycle:
            1. Verifies the agent is allowed to execute: raises
               ``AutonomousAgentError`` if ``status`` is already
               ``RUNNING`` (a cycle is already in progress) or
               ``ERROR`` (a prior cycle failed; no retry/recovery
               exists yet, so a fresh ``AutonomousAgent`` -- or a
               future sprint's explicit recovery step -- is required
               before stepping again), or if ``context`` is ``None``.
            2. Transitions ``status`` to ``RUNNING`` for the duration
               of the delegated call.
            3. On success, advances ``iteration_count`` by exactly 1.
            4. On success, records ``last_cycle_at`` as the
               ``time.time()`` epoch timestamp of completion.
            5. Delegates the actual analysis work to
               ``self._runtime_analysis_pipeline.run(context)`` -- the
               existing, unmodified 11-step ``AnalysisPipeline`` (plus
               whatever of Reflection/DecisionEngine/.../LearningLoop
               that pipeline instance was wired with), exactly as
               ``StockAgent`` already calls it. Nothing about
               ``RuntimeAnalysisPipeline`` is duplicated or
               reimplemented here.

        Plan-aware delegation (Phase 2, Sprint 11):
            When ``current_plan`` is not ``None``, step 5 above routes
            through ``self.advance_plan(context)`` instead of calling
            ``self._runtime_analysis_pipeline.run(context)`` directly
            -- ``advance_plan()`` itself just delegates straight
            through to that same injected singleton, so the call
            target and its effect are identical either way. When
            ``current_plan`` is ``None``, behavior is byte-for-byte
            unchanged from before Sprint 11. Every other step above
            (the RUNNING transition, the ERROR/IDLE outcome, the
            ``iteration_count``/``last_cycle_at`` update) is performed
            by ``step()`` itself exactly as before -- ``advance_plan()``
            never duplicates any of that bookkeeping.

        Args:
            context: the ``ServiceContext``-shaped object to run this
                cycle for, built exactly as any other
                ``RuntimeAnalysisPipeline.run`` caller already builds
                one.

        Returns:
            An ``AutonomousCycleResult`` summarizing only
            success/failure, the completion timestamp, and the
            iteration number -- never the underlying Decision/
            DecisionPolicy/PortfolioEngine/LearningLoop result objects
            ``runtime_analysis_pipeline`` may have produced internally.

        Raises:
            AutonomousAgentError: if the agent is not currently allowed
                to execute a cycle (see step 1 above), or if
                ``context`` is ``None``. Note this is distinct from a
                *failed* cycle (an exception from
                ``runtime_analysis_pipeline.run`` itself): that case is
                caught and reported through the returned
                ``AutonomousCycleResult`` (``success=False``) and the
                ``ERROR`` status, not re-raised.
        """
        if context is None:
            raise AutonomousAgentError(
                "AutonomousAgent.step() requires a non-None 'context'"
            )
        if self._status is AutonomousAgentStatus.STOPPED:
            # Phase 2, Sprint 10: checked first, and before touching
            # self._runtime_analysis_pipeline at all -- a stopped
            # agent must never reach the pipeline, and this is a
            # terminal state with no retry/recovery of any kind.
            raise AutonomousAgentError(
                "AutonomousAgent.step() refused: agent status is "
                "STOPPED, this is a terminal lifecycle state -- a "
                "new AutonomousAgent is required to run further cycles"
            )
        if self._status is AutonomousAgentStatus.PAUSED:
            # Phase 2, Sprint 9: checked first, and before touching
            # self._runtime_analysis_pipeline at all -- a paused agent
            # must never reach the pipeline. See pause()/resume()
            # docstrings for the rest of the lifecycle rules.
            raise AutonomousAgentError(
                "AutonomousAgent.step() refused: agent status is "
                f"{self._status.name}, not allowed to start a new "
                "cycle while paused (call resume() first)"
            )
        if self._status in (
            AutonomousAgentStatus.RUNNING,
            AutonomousAgentStatus.ERROR,
        ):
            raise AutonomousAgentError(
                "AutonomousAgent.step() refused: agent status is "
                f"{self._status.name}, not allowed to start a new "
                "cycle (no retry/recovery implemented)"
            )

        self._status = AutonomousAgentStatus.RUNNING

        try:
            if self._current_plan is not None:
                # Phase 2, Sprint 11: route through advance_plan()
                # when a plan is stored, so the ExecutionPlan ->
                # AutonomousAgent -> RuntimeAnalysisPipeline chain is
                # exercised. advance_plan() delegates to the exact
                # same injected pipeline singleton this branch always
                # called directly -- behavior is otherwise identical,
                # and every surrounding bookkeeping step below is
                # unchanged either way.
                self.advance_plan(context)
            else:
                self._runtime_analysis_pipeline.run(context)
        except Exception:  # noqa: BLE001 -- any pipeline failure -> ERROR
            self._status = AutonomousAgentStatus.ERROR
            return AutonomousCycleResult(
                success=False,
                timestamp=time.time(),
                iteration=self._iteration_count,
            )

        self._iteration_count += 1
        self._last_cycle_at = time.time()
        self._status = AutonomousAgentStatus.IDLE

        return AutonomousCycleResult(
            success=True,
            timestamp=self._last_cycle_at,
            iteration=self._iteration_count,
        )

    def run(
        self,
        context: object,
        max_iterations: int,
    ) -> Tuple[AutonomousCycleResult, ...]:
        """Perform ``max_iterations`` deterministic autonomous cycles
        (Phase 2, Sprint 4).

        ``run()`` is nothing more than a deterministic driver around
        repeated ``step(context)`` calls -- it introduces no behavior
        of its own beyond input validation and result collection.
        Every status transition (IDLE -> RUNNING -> IDLE on success,
        or -> ERROR on failure), every ``iteration_count``/
        ``last_cycle_at`` update, and every delegation to the
        constructor-injected ``RuntimeAnalysisPipeline`` is still
        performed exclusively by ``step()``, exactly as it already was
        -- none of that logic is duplicated or reimplemented here.

        No loop-internal sleep, retry, scheduling, threads, async, or
        approval handling of any kind is introduced. One invocation of
        ``run()`` performs exactly ``max_iterations`` sequential,
        synchronous calls to ``step()`` and nothing else.

        Args:
            context: the ``ServiceContext``-shaped object passed
                unchanged to every ``step(context)`` call in this run.
            max_iterations: how many times to call ``step(context)``.
                Must be an ``int`` >= 1.

        Returns:
            A ``tuple`` (not a ``list``) of exactly ``max_iterations``
            ``AutonomousCycleResult`` instances, one per ``step()``
            call, in call order -- immutable, matching
            ``AutonomousCycleResult``'s own frozen-dataclass
            convention and the existing tuple-typed attributes
            elsewhere in this file.

        Raises:
            AutonomousAgentError: if ``context`` is ``None``, if
                ``max_iterations`` is not an ``int`` or is < 1, or if
                any delegated ``step(context)`` call itself raises
                ``AutonomousAgentError`` (e.g. because a prior
                iteration in this same run already left ``status`` as
                ``ERROR``, per ``step()``'s own no-retry guard). In
                that last case, ``status`` is (re-)confirmed as
                ``ERROR`` and the original exception is re-raised
                unchanged -- never swallowed, never replaced.
        """
        if context is None:
            raise AutonomousAgentError(
                "AutonomousAgent.run() requires a non-None 'context'"
            )
        if not isinstance(max_iterations, int) or isinstance(
            max_iterations, bool
        ) or max_iterations < 1:
            raise AutonomousAgentError(
                "AutonomousAgent.run() requires 'max_iterations' to be "
                "an int >= 1"
            )
        if self._status is AutonomousAgentStatus.STOPPED:
            # Phase 2, Sprint 10: fail immediately, before the loop
            # and before the try/except below -- so status is left
            # as STOPPED rather than being overwritten to ERROR by
            # the generic exception handler further down. STOPPED is
            # a terminal state distinct from a failed cycle.
            raise AutonomousAgentError(
                "AutonomousAgent.run() refused: agent status is "
                "STOPPED, this is a terminal lifecycle state -- a "
                "new AutonomousAgent is required to run further cycles"
            )

        results: List[AutonomousCycleResult] = []
        try:
            for _ in range(max_iterations):
                results.append(self.step(context))
        except Exception:  # noqa: BLE001 -- propagate, never swallow
            self._status = AutonomousAgentStatus.ERROR
            raise

        return tuple(results)