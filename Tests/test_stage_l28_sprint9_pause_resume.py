"""
Phase 2 Sprint 9 proof suite -- AutonomousAgent pause/resume lifecycle
control (``pause()`` / ``resume()``).

Scope: dedicated regression suite for
``Orchestration.autonomous_agent.AutonomousAgent.pause`` and
``AutonomousAgent.resume`` only, plus the minimal additive
``step()`` guard (refuses while ``PAUSED``, before touching the
injected ``RuntimeAnalysisPipeline``). Constructor/validation/
lifecycle-state-shape behavior for the ten L18-L27 dependencies plus
the Sprint 3 constructor-injected ``runtime_analysis_pipeline`` is
already covered by ``Tests/test_stage_l28_autonomous_agent.py``,
``step()``'s own dedicated behavior by
``Tests/test_stage_l28_sprint2_step.py``, ``run()``'s own dedicated
behavior by ``Tests/test_stage_l28_sprint4_run.py``, goal ownership by
``Tests/test_stage_l28_sprint5_goal.py``, session metadata by
``Tests/test_stage_l28_sprint6_session.py``, GoalPlanner
delegation/injection by ``Tests/test_stage_l28_sprint7_goalplanner.py``,
and ExecutionPlan ownership by
``Tests/test_stage_l28_sprint8_execution_plan.py`` -- none of that is
re-verified here beyond what pause/resume itself needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, constructor-
injected exactly like the ten L18-L27 dependencies (same convention as
every prior Sprint suite). Because ``RUNNING`` is otherwise only ever
a transient, synchronous, in-``step()`` state, some scenarios set up
the ``RUNNING`` precondition directly via the private ``_status``
attribute -- this is test-setup only (mirroring the existing precedent
of reading private constructor-injected collaborators, e.g.
``agent._runtime_analysis_pipeline``, in
``Tests/test_stage_l28_sprint4_run.py``) and never how ``pause()``/
``resume()`` themselves are expected to be driven by real callers. No
scheduler, no cancel(), no ExecutionPlan execution, no threads/async
of any kind -- all explicitly out of scope for Sprint 9.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    P1  -- pause() from RUNNING transitions status to PAUSED.
    P2  -- resume() from PAUSED transitions status back to RUNNING.
    P3  -- pause() preserves goal.
    P4  -- pause() preserves current_plan.
    P5  -- pause() preserves session_id/session_started_at.
    P6  -- pause() preserves iteration_count.
    P7  -- pause() preserves last_cycle_at.
    P8  -- pause() called twice in a row raises AutonomousAgentError
           (PAUSED -> PAUSED is forbidden), and status stays PAUSED.
    P9  -- resume() called twice in a row raises AutonomousAgentError
           (RUNNING -> RUNNING via a second resume() is forbidden),
           and status stays RUNNING.
    P10 -- resume() from IDLE raises AutonomousAgentError.
    P11 -- pause() from IDLE raises AutonomousAgentError.
    P12 -- pause() from ERROR raises AutonomousAgentError.
    P13 -- resume() from ERROR raises AutonomousAgentError.
    P14 -- step() while PAUSED raises AutonomousAgentError before the
           injected RuntimeAnalysisPipeline.run() is ever called.
    P15 -- run()'s behavior is unchanged: a normal run() still
           transitions RUNNING (transiently) -> IDLE per iteration,
           never leaves status as PAUSED, and succeeds exactly as
           before.
    P16 -- resume() never modifies iteration_count or last_cycle_at.
    P17 -- pause()/resume() never call the injected
           RuntimeAnalysisPipeline's run().
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
    Neither pause(), resume(), step(), nor run() ever touches these."""

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
    """Stand-in for Orchestration.planner.GoalPlanner. pause()/
    resume() must never reach this."""

    def __init__(self) -> None:
        self.build_plan_calls: List[object] = []

    def build_plan(self, goal: object) -> _FakePlan:
        self.build_plan_calls.append(goal)
        return _FakePlan(f"plan-{len(self.build_plan_calls)}")


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call --
    used here to prove pause()/resume() never reach it, and that
    step()/run() still behave as before around pause/resume."""

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


def _force_running(agent: AutonomousAgent) -> None:
    """Test-setup helper only: RUNNING is otherwise a transient state
    that only exists synchronously inside step(). See module
    docstring for why this is acceptable here."""
    agent._status = AutonomousAgentStatus.RUNNING


def _force_error(agent: AutonomousAgent) -> None:
    """Test-setup helper only: drives the agent into ERROR the
    supported way -- via a genuinely failing step() -- rather than by
    poking the enum value directly."""
    failing_pipeline = _FakeRuntimeAnalysisPipeline(should_fail=True)
    goal_planner = _FakeGoalPlanner()
    err_agent = _make_agent(failing_pipeline, goal_planner)
    err_agent.step(_FakeContext("force-error"))
    assert err_agent.status is AutonomousAgentStatus.ERROR
    return err_agent


# ---------------------------------------------------------------------------
# P1 -- pause() from RUNNING
# ---------------------------------------------------------------------------
def scenario_pause_from_running() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    _force_running(agent)

    agent.pause()

    check(
        agent.status is AutonomousAgentStatus.PAUSED,
        "P1: pause() from RUNNING transitions status to PAUSED",
    )


# ---------------------------------------------------------------------------
# P2 -- resume() from PAUSED
# ---------------------------------------------------------------------------
def scenario_resume_from_paused() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    _force_running(agent)
    agent.pause()

    agent.resume()

    check(
        agent.status is AutonomousAgentStatus.RUNNING,
        "P2: resume() from PAUSED transitions status back to RUNNING",
    )


# ---------------------------------------------------------------------------
# P3 -- pause() preserves goal
# ---------------------------------------------------------------------------
def scenario_pause_preserves_goal() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    goal = _FakeGoal("monitor-bbca")
    agent.set_goal(goal)
    _force_running(agent)

    agent.pause()

    check(agent.goal is goal, "P3: pause() preserves goal")


# ---------------------------------------------------------------------------
# P4 -- pause() preserves current_plan
# ---------------------------------------------------------------------------
def scenario_pause_preserves_current_plan() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))
    plan = agent.plan_goal()
    _force_running(agent)

    agent.pause()

    check(agent.current_plan is plan, "P4: pause() preserves current_plan")


# ---------------------------------------------------------------------------
# P5 -- pause() preserves session_id/session_started_at
# ---------------------------------------------------------------------------
def scenario_pause_preserves_session() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    session_id = agent.start_session()
    started_at = agent.session_started_at
    _force_running(agent)

    agent.pause()

    check(agent.session_id == session_id, "P5: pause() preserves session_id")
    check(
        agent.session_started_at == started_at,
        "P5: pause() preserves session_started_at",
    )


# ---------------------------------------------------------------------------
# P6 -- pause() preserves iteration_count
# ---------------------------------------------------------------------------
def scenario_pause_preserves_iteration_count() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.step(_FakeContext("p6-a"))
    agent.step(_FakeContext("p6-b"))
    check(agent.iteration_count == 2, "P6 precondition: two successful steps")
    _force_running(agent)

    agent.pause()

    check(agent.iteration_count == 2, "P6: pause() preserves iteration_count")


# ---------------------------------------------------------------------------
# P7 -- pause() preserves last_cycle_at
# ---------------------------------------------------------------------------
def scenario_pause_preserves_last_cycle_at() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.step(_FakeContext("p7"))
    last_cycle_at = agent.last_cycle_at
    check(last_cycle_at is not None, "P7 precondition: last_cycle_at was set")
    _force_running(agent)

    agent.pause()

    check(
        agent.last_cycle_at == last_cycle_at,
        "P7: pause() preserves last_cycle_at",
    )


# ---------------------------------------------------------------------------
# P8 -- pause() twice raises
# ---------------------------------------------------------------------------
def scenario_pause_twice_raises() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    _force_running(agent)
    agent.pause()

    raised = False
    try:
        agent.pause()
    except AutonomousAgentError:
        raised = True

    check(raised, "P8: calling pause() a second time raises AutonomousAgentError")
    check(
        agent.status is AutonomousAgentStatus.PAUSED,
        "P8: status remains PAUSED after the refused second pause() call",
    )


# ---------------------------------------------------------------------------
# P9 -- resume() twice raises
# ---------------------------------------------------------------------------
def scenario_resume_twice_raises() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    _force_running(agent)
    agent.pause()
    agent.resume()

    raised = False
    try:
        agent.resume()
    except AutonomousAgentError:
        raised = True

    check(raised, "P9: calling resume() a second time raises AutonomousAgentError")
    check(
        agent.status is AutonomousAgentStatus.RUNNING,
        "P9: status remains RUNNING after the refused second resume() call",
    )


# ---------------------------------------------------------------------------
# P10 -- resume() from IDLE raises
# ---------------------------------------------------------------------------
def scenario_resume_from_idle_raises() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    check(agent.status is AutonomousAgentStatus.IDLE, "P10 precondition: agent is IDLE")

    raised = False
    try:
        agent.resume()
    except AutonomousAgentError:
        raised = True

    check(raised, "P10: resume() from IDLE raises AutonomousAgentError")
    check(agent.status is AutonomousAgentStatus.IDLE, "P10: status remains IDLE")


# ---------------------------------------------------------------------------
# P11 -- pause() from IDLE raises
# ---------------------------------------------------------------------------
def scenario_pause_from_idle_raises() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    check(agent.status is AutonomousAgentStatus.IDLE, "P11 precondition: agent is IDLE")

    raised = False
    try:
        agent.pause()
    except AutonomousAgentError:
        raised = True

    check(raised, "P11: pause() from IDLE raises AutonomousAgentError")
    check(agent.status is AutonomousAgentStatus.IDLE, "P11: status remains IDLE")


# ---------------------------------------------------------------------------
# P12 -- pause() from ERROR raises
# ---------------------------------------------------------------------------
def scenario_pause_from_error_raises() -> None:
    err_agent = _force_error(_make_agent_and_collaborators()[0])

    raised = False
    try:
        err_agent.pause()
    except AutonomousAgentError:
        raised = True

    check(raised, "P12: pause() from ERROR raises AutonomousAgentError")
    check(
        err_agent.status is AutonomousAgentStatus.ERROR,
        "P12: status remains ERROR after the refused pause() call",
    )


# ---------------------------------------------------------------------------
# P13 -- resume() from ERROR raises
# ---------------------------------------------------------------------------
def scenario_resume_from_error_raises() -> None:
    err_agent = _force_error(_make_agent_and_collaborators()[0])

    raised = False
    try:
        err_agent.resume()
    except AutonomousAgentError:
        raised = True

    check(raised, "P13: resume() from ERROR raises AutonomousAgentError")
    check(
        err_agent.status is AutonomousAgentStatus.ERROR,
        "P13: status remains ERROR after the refused resume() call",
    )


# ---------------------------------------------------------------------------
# P14 -- step() while PAUSED raises before reaching the pipeline
# ---------------------------------------------------------------------------
def scenario_step_while_paused_raises_before_pipeline() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    _force_running(agent)
    agent.pause()

    raised = False
    try:
        agent.step(_FakeContext("p14"))
    except AutonomousAgentError:
        raised = True

    check(raised, "P14: step() while PAUSED raises AutonomousAgentError")
    check(
        pipeline.calls == [],
        "P14: the refused step() call never reached the injected "
        "RuntimeAnalysisPipeline's run()",
    )
    check(
        agent.status is AutonomousAgentStatus.PAUSED,
        "P14: status remains PAUSED after the refused step() call",
    )


# ---------------------------------------------------------------------------
# P15 -- run() behavior is unchanged
# ---------------------------------------------------------------------------
def scenario_run_behavior_unchanged() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()

    results = agent.run(_FakeContext("p15"), max_iterations=3)

    check(len(results) == 3, "P15: run() still performs exactly max_iterations cycles")
    check(all(r.success for r in results), "P15: run() still succeeds normally")
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "P15: run() still leaves status as IDLE on success (never PAUSED)",
    )
    check(
        agent.iteration_count == 3,
        "P15: run() still increments iteration_count normally",
    )
    check(
        len(pipeline.calls) == 3,
        "P15: run() still delegates every iteration to the injected pipeline",
    )


# ---------------------------------------------------------------------------
# P16 -- resume() never modifies iteration_count/last_cycle_at
# ---------------------------------------------------------------------------
def scenario_resume_preserves_iteration_and_timestamp() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.step(_FakeContext("p16"))
    iteration_before = agent.iteration_count
    last_cycle_before = agent.last_cycle_at
    _force_running(agent)
    agent.pause()

    agent.resume()

    check(
        agent.iteration_count == iteration_before,
        "P16: resume() does not modify iteration_count",
    )
    check(
        agent.last_cycle_at == last_cycle_before,
        "P16: resume() does not modify last_cycle_at",
    )


# ---------------------------------------------------------------------------
# P17 -- pause()/resume() never call the injected pipeline
# ---------------------------------------------------------------------------
def scenario_pause_resume_never_call_pipeline() -> None:
    agent, pipeline, goal_planner = _make_agent_and_collaborators()
    _force_running(agent)

    agent.pause()
    agent.resume()

    check(
        pipeline.calls == [],
        "P17: pause()/resume() never call the injected "
        "RuntimeAnalysisPipeline's run()",
    )
    check(
        goal_planner.build_plan_calls == [],
        "P17: pause()/resume() never call the injected GoalPlanner's "
        "build_plan()",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_pause_from_running,
        scenario_resume_from_paused,
        scenario_pause_preserves_goal,
        scenario_pause_preserves_current_plan,
        scenario_pause_preserves_session,
        scenario_pause_preserves_iteration_count,
        scenario_pause_preserves_last_cycle_at,
        scenario_pause_twice_raises,
        scenario_resume_twice_raises,
        scenario_resume_from_idle_raises,
        scenario_pause_from_idle_raises,
        scenario_pause_from_error_raises,
        scenario_resume_from_error_raises,
        scenario_step_while_paused_raises_before_pipeline,
        scenario_run_behavior_unchanged,
        scenario_resume_preserves_iteration_and_timestamp,
        scenario_pause_resume_never_call_pipeline,
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
    print(f"PHASE 2 SPRINT 9 PAUSE/RESUME RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())