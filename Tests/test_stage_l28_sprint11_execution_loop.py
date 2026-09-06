"""
Phase 2 Sprint 11 proof suite -- AutonomousAgent execution loop
(``advance_plan()``).

Scope: dedicated regression suite for
``Orchestration.autonomous_agent.AutonomousAgent.advance_plan`` only,
plus the minimal additive change to ``step()`` (routes through
``advance_plan()`` when ``current_plan`` is set, otherwise identical
to its pre-Sprint-11 direct-pipeline-call behavior). Constructor/
validation/lifecycle-state-shape behavior for the ten L18-L27
dependencies plus the Sprint 3 constructor-injected
``runtime_analysis_pipeline`` is already covered by
``Tests/test_stage_l28_autonomous_agent.py``, ``step()``'s own
dedicated behavior by ``Tests/test_stage_l28_sprint2_step.py``,
``run()``'s own dedicated behavior by
``Tests/test_stage_l28_sprint4_run.py``, goal ownership by
``Tests/test_stage_l28_sprint5_goal.py``, session metadata by
``Tests/test_stage_l28_sprint6_session.py``, GoalPlanner
delegation/injection by ``Tests/test_stage_l28_sprint7_goalplanner.py``,
ExecutionPlan ownership by
``Tests/test_stage_l28_sprint8_execution_plan.py``, pause/resume by
``Tests/test_stage_l28_sprint9_pause_resume.py``, and stop/cancel by
``Tests/test_stage_l28_sprint10_cancel.py`` -- none of that is
re-verified here beyond what the execution loop itself needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, constructor-
injected exactly like the ten L18-L27 dependencies (same convention as
every prior Sprint suite). ``advance_plan()`` owns no planning logic
of its own: it never calls the injected ``GoalPlanner``, never
mutates ``current_plan`` in any way, and never creates a new goal --
this suite only proves it delegates exactly one cycle to the already-
injected ``RuntimeAnalysisPipeline`` singleton, under the documented
preconditions. No scheduler, no background worker, no threading, no
broker/exchange/portfolio execution, no automatic plan completion or
replanning -- all explicitly out of scope for Sprint 11.

Because ``RUNNING`` is otherwise only ever a transient, synchronous,
in-``step()`` state, one scenario sets up that precondition directly
via the private ``_status`` attribute -- test-setup only, mirroring
the same precedent already established in
``Tests/test_stage_l28_sprint9_pause_resume.py`` and
``Tests/test_stage_l28_sprint10_cancel.py``. ``PAUSED``/``STOPPED``
are instead reached the fully public way, via ``agent.pause()``/
``agent.stop()``.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    L1  -- advance_plan() with no current_plan raises
           AutonomousAgentError, and the injected pipeline is never
           reached.
    L2  -- advance_plan() while PAUSED raises AutonomousAgentError,
           and the injected pipeline is never reached.
    L3  -- advance_plan() while STOPPED raises AutonomousAgentError,
           and the injected pipeline is never reached.
    L4  -- advance_plan() while ERROR raises AutonomousAgentError,
           and the injected pipeline is never reached.
    L5  -- a successful advance_plan() call delegates to the injected
           RuntimeAnalysisPipeline's run() exactly once.
    L6  -- advance_plan() uses the exact same constructor-injected
           pipeline singleton step()/run() already use (identity, not
           a second instance).
    L7  -- advance_plan() never changes goal.
    L8  -- advance_plan() never changes session_id/session_started_at.
    L9  -- advance_plan() never changes last_cycle_at (timestamps) or
           iteration_count when called directly (not via step()).
    L10 -- advance_plan() never mutates current_plan (no plan-step
           completion/progress tracking of any kind).
    L11 -- run()'s behavior is unchanged: with a current_plan set, a
           normal run() still performs exactly max_iterations cycles,
           still succeeds, and iteration_count/status end up exactly
           as they would without a plan.
    L12 -- step()'s behavior is unchanged in shape: with a
           current_plan set, a successful step() still increments
           iteration_count by 1, still records last_cycle_at, still
           ends IDLE, and still reaches the pipeline exactly once --
           now via advance_plan() internally, but the observable
           result is identical to the no-plan case.
    L13 -- step() without a current_plan is byte-for-byte unchanged:
           it still calls the injected pipeline directly (proved via
           the same success/failure/iteration/timestamp assertions
           Sprint 2's own suite already makes), advance_plan() is not
           invoked in that path.
    L14 -- advance_plan() never calls the injected GoalPlanner's
           build_plan() (no rebuilding plans, no automatic
           replanning).
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.autonomous_agent import (
    AutonomousAgent,
    AutonomousAgentError,
    AutonomousAgentStatus,
)

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []

_FIELD_NAMES = (
    "reflection",
    "decision_engine",
    "decision_policy",
    "policy_guard",
    "execution_intent",
    "execution_planner",
    "execution_coordinator",
    "portfolio_engine",
    "portfolio_risk",
    "learning_loop",
)


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


class _FakeComponent:
    """Stand-in for one of the ten L18-L27 constructor dependencies.
    Neither advance_plan(), step(), nor run() ever touches these."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeContext:
    """Stand-in for a ServiceContext. Treated as opaque and passed
    through unchanged."""

    def __init__(self, tag: str = "ctx") -> None:
        self.tag = tag


class _FakeGoal:
    """Stand-in for an Orchestration.planner.Goal."""

    def __init__(self, label: str) -> None:
        self.label = label


class _FakePlan:
    """Stand-in for an Orchestration.planner.ExecutionPlan."""

    def __init__(self, label: str) -> None:
        self.label = label


class _FakeGoalPlanner:
    """Stand-in for Orchestration.planner.GoalPlanner. advance_plan()
    must never reach this."""

    def __init__(self) -> None:
        self.build_plan_calls: List[object] = []

    def build_plan(self, goal: object) -> _FakePlan:
        self.build_plan_calls.append(goal)
        return _FakePlan(f"plan-{len(self.build_plan_calls)}")


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call --
    used here to prove advance_plan()/step() reach it exactly the
    expected number of times, and that refused calls never do."""

    def __init__(self, should_fail: bool = False) -> None:
        self.calls: List[object] = []
        self.should_fail = should_fail

    def run(self, context: object) -> str:
        self.calls.append(context)
        if self.should_fail:
            raise RuntimeError("simulated pipeline failure")
        return "ok"


def _make_agent(
    pipeline: _FakeRuntimeAnalysisPipeline,
    goal_planner: object,
) -> AutonomousAgent:
    return AutonomousAgent(
        runtime_analysis_pipeline=pipeline,
        goal_planner=goal_planner,
        **{name: _FakeComponent(name) for name in _FIELD_NAMES},
    )


def _make_agent_and_collaborators(should_fail: bool = False):
    pipeline = _FakeRuntimeAnalysisPipeline(should_fail=should_fail)
    goal_planner = _FakeGoalPlanner()
    agent = _make_agent(pipeline, goal_planner)
    return agent, pipeline, goal_planner


def _make_agent_with_plan(should_fail: bool = False):
    agent, pipeline, goal_planner = _make_agent_and_collaborators(should_fail=should_fail)
    agent.set_goal(_FakeGoal("monitor-bbca"))
    plan = agent.plan_goal()
    return agent, pipeline, goal_planner, plan


def _force_running(agent: AutonomousAgent) -> None:
    """Test-setup helper only: RUNNING is otherwise a transient state
    that only exists synchronously inside step(). Same precedent as
    Tests/test_stage_l28_sprint9_pause_resume.py and
    Tests/test_stage_l28_sprint10_cancel.py."""
    agent._status = AutonomousAgentStatus.RUNNING


def _force_error(agent: AutonomousAgent) -> None:
    """Test-setup helper only: drives the agent into ERROR the
    supported way -- via a genuinely failing step() -- rather than by
    poking the enum value directly."""
    agent.step(_FakeContext("force-error"))
    assert agent.status is AutonomousAgentStatus.ERROR


# ---------------------------------------------------------------------------
# L1 -- advance_plan() with no current_plan raises
# ---------------------------------------------------------------------------
def scenario_advance_plan_without_plan_raises() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    check(agent.current_plan is None, "L1 precondition: current_plan is None")

    raised = False
    try:
        agent.advance_plan(_FakeContext("l1"))
    except AutonomousAgentError:
        raised = True

    check(raised, "L1: advance_plan() without a current_plan raises AutonomousAgentError")
    check(pipeline.calls == [], "L1: the refused call never reached the injected pipeline")


# ---------------------------------------------------------------------------
# L2 -- advance_plan() while PAUSED raises
# ---------------------------------------------------------------------------
def scenario_advance_plan_while_paused_raises() -> None:
    agent, pipeline, _, _ = _make_agent_with_plan()
    _force_running(agent)
    agent.pause()
    check(agent.status is AutonomousAgentStatus.PAUSED, "L2 precondition: agent is PAUSED")
    pipeline.calls.clear()

    raised = False
    try:
        agent.advance_plan(_FakeContext("l2"))
    except AutonomousAgentError:
        raised = True

    check(raised, "L2: advance_plan() while PAUSED raises AutonomousAgentError")
    check(pipeline.calls == [], "L2: the refused call never reached the injected pipeline")


# ---------------------------------------------------------------------------
# L3 -- advance_plan() while STOPPED raises
# ---------------------------------------------------------------------------
def scenario_advance_plan_while_stopped_raises() -> None:
    agent, pipeline, _, _ = _make_agent_with_plan()
    agent.stop()
    check(agent.status is AutonomousAgentStatus.STOPPED, "L3 precondition: agent is STOPPED")
    pipeline.calls.clear()

    raised = False
    try:
        agent.advance_plan(_FakeContext("l3"))
    except AutonomousAgentError:
        raised = True

    check(raised, "L3: advance_plan() while STOPPED raises AutonomousAgentError")
    check(pipeline.calls == [], "L3: the refused call never reached the injected pipeline")


# ---------------------------------------------------------------------------
# L4 -- advance_plan() while ERROR raises
# ---------------------------------------------------------------------------
def scenario_advance_plan_while_error_raises() -> None:
    agent, pipeline, _, _ = _make_agent_with_plan(should_fail=True)
    _force_error(agent)
    check(agent.status is AutonomousAgentStatus.ERROR, "L4 precondition: agent is ERROR")
    pipeline.calls.clear()

    raised = False
    try:
        agent.advance_plan(_FakeContext("l4"))
    except AutonomousAgentError:
        raised = True

    check(raised, "L4: advance_plan() while ERROR raises AutonomousAgentError")
    check(pipeline.calls == [], "L4: the refused call never reached the injected pipeline")


# ---------------------------------------------------------------------------
# L5/L6 -- successful delegation, exactly once, to the injected singleton
# ---------------------------------------------------------------------------
def scenario_advance_plan_delegates_once_to_injected_singleton() -> None:
    agent, pipeline, _, _ = _make_agent_with_plan()

    result = agent.advance_plan(_FakeContext("l5"))

    check(len(pipeline.calls) == 1, "L5: advance_plan() delegates to the pipeline exactly once")
    check(
        agent._runtime_analysis_pipeline is pipeline,
        "L6: advance_plan() uses the exact same constructor-injected "
        "pipeline singleton (identity)",
    )
    check(result == "ok", "L5: advance_plan() returns the pipeline's result unchanged")


# ---------------------------------------------------------------------------
# L7 -- goal unchanged
# ---------------------------------------------------------------------------
def scenario_advance_plan_leaves_goal_unchanged() -> None:
    agent, _, _, _ = _make_agent_with_plan()
    goal_before = agent.goal

    agent.advance_plan(_FakeContext("l7"))

    check(agent.goal is goal_before, "L7: advance_plan() never changes goal")


# ---------------------------------------------------------------------------
# L8 -- session unchanged
# ---------------------------------------------------------------------------
def scenario_advance_plan_leaves_session_unchanged() -> None:
    agent, _, _, _ = _make_agent_with_plan()
    session_id = agent.start_session()
    started_at = agent.session_started_at

    agent.advance_plan(_FakeContext("l8"))

    check(agent.session_id == session_id, "L8: advance_plan() never changes session_id")
    check(
        agent.session_started_at == started_at,
        "L8: advance_plan() never changes session_started_at",
    )


# ---------------------------------------------------------------------------
# L9 -- timestamps/iteration_count unchanged when called directly
# ---------------------------------------------------------------------------
def scenario_advance_plan_leaves_timestamps_and_iteration_unchanged() -> None:
    agent, _, _, _ = _make_agent_with_plan()
    iteration_before = agent.iteration_count
    last_cycle_before = agent.last_cycle_at

    agent.advance_plan(_FakeContext("l9"))

    check(
        agent.iteration_count == iteration_before,
        "L9: advance_plan() called directly never changes iteration_count",
    )
    check(
        agent.last_cycle_at == last_cycle_before,
        "L9: advance_plan() called directly never changes last_cycle_at",
    )


# ---------------------------------------------------------------------------
# L10 -- current_plan preserved (no mutation semantics invented)
# ---------------------------------------------------------------------------
def scenario_advance_plan_never_mutates_current_plan() -> None:
    agent, _, _, plan = _make_agent_with_plan()

    agent.advance_plan(_FakeContext("l10-a"))
    agent.advance_plan(_FakeContext("l10-b"))

    check(
        agent.current_plan is plan,
        "L10: advance_plan() never mutates or replaces current_plan",
    )


# ---------------------------------------------------------------------------
# L11 -- run() behavior unchanged with a plan set
# ---------------------------------------------------------------------------
def scenario_run_behavior_unchanged_with_plan() -> None:
    agent, pipeline, _, _ = _make_agent_with_plan()

    results = agent.run(_FakeContext("l11"), max_iterations=3)

    check(len(results) == 3, "L11: run() still performs exactly max_iterations cycles")
    check(all(r.success for r in results), "L11: run() still succeeds normally with a plan set")
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "L11: run() still leaves status as IDLE on success",
    )
    check(agent.iteration_count == 3, "L11: run() still increments iteration_count normally")
    check(
        len(pipeline.calls) == 3,
        "L11: run() still reaches the injected pipeline exactly once per iteration",
    )


# ---------------------------------------------------------------------------
# L12 -- step() behavior unchanged in shape, with a plan set
# ---------------------------------------------------------------------------
def scenario_step_behavior_unchanged_with_plan() -> None:
    agent, pipeline, _, _ = _make_agent_with_plan()

    result = agent.step(_FakeContext("l12"))

    check(result.success is True, "L12: step() still succeeds with a plan set")
    check(agent.iteration_count == 1, "L12: step() still increments iteration_count by 1")
    check(agent.last_cycle_at is not None, "L12: step() still records last_cycle_at")
    check(agent.status is AutonomousAgentStatus.IDLE, "L12: step() still ends IDLE on success")
    check(
        len(pipeline.calls) == 1,
        "L12: step() still reaches the injected pipeline exactly once (via advance_plan())",
    )


# ---------------------------------------------------------------------------
# L13 -- step() unchanged without a plan
# ---------------------------------------------------------------------------
def scenario_step_unchanged_without_plan() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    check(agent.current_plan is None, "L13 precondition: no plan is set")

    result = agent.step(_FakeContext("l13"))

    check(result.success is True, "L13: step() still succeeds without a plan")
    check(agent.iteration_count == 1, "L13: step() still increments iteration_count by 1")
    check(agent.status is AutonomousAgentStatus.IDLE, "L13: step() still ends IDLE on success")
    check(
        len(pipeline.calls) == 1,
        "L13: step() without a plan still reaches the injected pipeline exactly once, "
        "directly (advance_plan() is not invoked in this path)",
    )


# ---------------------------------------------------------------------------
# L14 -- advance_plan() never calls GoalPlanner
# ---------------------------------------------------------------------------
def scenario_advance_plan_never_calls_goal_planner() -> None:
    agent, _, goal_planner, _ = _make_agent_with_plan()
    goal_planner.build_plan_calls.clear()

    agent.advance_plan(_FakeContext("l14"))

    check(
        goal_planner.build_plan_calls == [],
        "L14: advance_plan() never calls the injected GoalPlanner's build_plan()",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_advance_plan_without_plan_raises,
        scenario_advance_plan_while_paused_raises,
        scenario_advance_plan_while_stopped_raises,
        scenario_advance_plan_while_error_raises,
        scenario_advance_plan_delegates_once_to_injected_singleton,
        scenario_advance_plan_leaves_goal_unchanged,
        scenario_advance_plan_leaves_session_unchanged,
        scenario_advance_plan_leaves_timestamps_and_iteration_unchanged,
        scenario_advance_plan_never_mutates_current_plan,
        scenario_run_behavior_unchanged_with_plan,
        scenario_step_behavior_unchanged_with_plan,
        scenario_step_unchanged_without_plan,
        scenario_advance_plan_never_calls_goal_planner,
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
    print(f"PHASE 2 SPRINT 11 EXECUTION LOOP RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())