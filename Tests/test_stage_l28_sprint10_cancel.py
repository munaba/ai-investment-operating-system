"""
Phase 2 Sprint 10 proof suite -- AutonomousAgent lifecycle termination
(``stop()``).

Naming note: the project's existing ``AutonomousAgentStatus`` enum
(Sprint 1) already declares a ``STOPPED`` terminal member, unused
until this sprint. Per this sprint's own instructions ("choose the
name that best matches the current codebase"), Sprint 10 reuses that
existing member and names the new method ``stop()`` to match, rather
than introducing a parallel "cancel()"/"CANCELLED" vocabulary
alongside an already-declared, differently-named terminal state. Every
behavior the parent prompt describes for "cancel()"/"CANCELLED" is
implemented here as ``stop()``/``AutonomousAgentStatus.STOPPED``.

Scope: dedicated regression suite for
``Orchestration.autonomous_agent.AutonomousAgent.stop`` only, plus the
minimal additive guards it required in ``step()`` (refuses while
``STOPPED``, before touching the injected ``RuntimeAnalysisPipeline``)
and ``run()`` (fails immediately when already ``STOPPED``, without
overwriting ``STOPPED`` with ``ERROR``). Constructor/validation/
lifecycle-state-shape behavior for the ten L18-L27 dependencies plus
the Sprint 3 constructor-injected ``runtime_analysis_pipeline`` is
already covered by ``Tests/test_stage_l28_autonomous_agent.py``,
``step()``'s own dedicated behavior by
``Tests/test_stage_l28_sprint2_step.py``, ``run()``'s own dedicated
behavior by ``Tests/test_stage_l28_sprint4_run.py``, goal ownership by
``Tests/test_stage_l28_sprint5_goal.py``, session metadata by
``Tests/test_stage_l28_sprint6_session.py``, GoalPlanner
delegation/injection by ``Tests/test_stage_l28_sprint7_goalplanner.py``,
ExecutionPlan ownership by
``Tests/test_stage_l28_sprint8_execution_plan.py``, and pause/resume by
``Tests/test_stage_l28_sprint9_pause_resume.py`` -- none of that is
re-verified here beyond what stop() itself needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, constructor-
injected exactly like the ten L18-L27 dependencies (same convention as
every prior Sprint suite). Because ``RUNNING`` is otherwise only ever
a transient, synchronous, in-``step()`` state, some scenarios set up
the ``RUNNING`` precondition directly via the private ``_status``
attribute -- test-setup only, mirroring the same precedent already
established in ``Tests/test_stage_l28_sprint9_pause_resume.py``.
``PAUSED`` is instead reached the fully public way, via
``agent.pause()``, since Sprint 9 already makes that a supported
transition. No scheduler, no background worker, no threading, no
ExecutionPlan execution, no automatic cleanup (goal/plan/session are
never cleared by stop()) -- all explicitly out of scope for Sprint 10.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    C1  -- stop() from RUNNING transitions status to STOPPED.
    C2  -- stop() from PAUSED transitions status to STOPPED.
    C3  -- stop() from IDLE transitions status to STOPPED.
    C4  -- stop() called twice in a row is idempotent (no error;
           status remains STOPPED).
    C5  -- stop() preserves goal.
    C6  -- stop() preserves current_plan.
    C7  -- stop() preserves session_id/session_started_at.
    C8  -- stop() preserves last_cycle_at (timestamps).
    C9  -- stop() preserves iteration_count.
    C10 -- step() after stop() raises AutonomousAgentError before the
           injected RuntimeAnalysisPipeline.run() is ever called.
    C11 -- run() after stop() raises AutonomousAgentError immediately
           (no pipeline calls), and status remains STOPPED (not
           overwritten to ERROR).
    C12 -- pause() after stop() raises AutonomousAgentError.
    C13 -- resume() after stop() raises AutonomousAgentError.
    C14 -- stop() from ERROR raises AutonomousAgentError, and status
           remains ERROR.
    C15 -- stop()/step()-after-stop/run()-after-stop never call the
           injected RuntimeAnalysisPipeline's run() or the injected
           GoalPlanner's build_plan().
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
    Neither stop(), pause(), resume(), step(), nor run() ever touches
    these."""

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
    """Stand-in for Orchestration.planner.GoalPlanner. stop() must
    never reach this."""

    def __init__(self) -> None:
        self.build_plan_calls: List[object] = []

    def build_plan(self, goal: object) -> _FakePlan:
        self.build_plan_calls.append(goal)
        return _FakePlan(f"plan-{len(self.build_plan_calls)}")


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call --
    used here to prove stop() never reaches it, and that step()/run()
    called after stop() never reach it either."""

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


def _make_agent_and_collaborators():
    pipeline = _FakeRuntimeAnalysisPipeline()
    goal_planner = _FakeGoalPlanner()
    agent = _make_agent(pipeline, goal_planner)
    return agent, pipeline, goal_planner


def _force_running(agent: AutonomousAgent) -> None:
    """Test-setup helper only: RUNNING is otherwise a transient state
    that only exists synchronously inside step(). Same precedent as
    Tests/test_stage_l28_sprint9_pause_resume.py."""
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
# C1 -- stop() from RUNNING
# ---------------------------------------------------------------------------
def scenario_stop_from_running() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    _force_running(agent)

    agent.stop()

    check(
        agent.status is AutonomousAgentStatus.STOPPED,
        "C1: stop() from RUNNING transitions status to STOPPED",
    )


# ---------------------------------------------------------------------------
# C2 -- stop() from PAUSED
# ---------------------------------------------------------------------------
def scenario_stop_from_paused() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    _force_running(agent)
    agent.pause()
    check(agent.status is AutonomousAgentStatus.PAUSED, "C2 precondition: agent is PAUSED")

    agent.stop()

    check(
        agent.status is AutonomousAgentStatus.STOPPED,
        "C2: stop() from PAUSED transitions status to STOPPED",
    )


# ---------------------------------------------------------------------------
# C3 -- stop() from IDLE
# ---------------------------------------------------------------------------
def scenario_stop_from_idle() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    check(agent.status is AutonomousAgentStatus.IDLE, "C3 precondition: agent is IDLE")

    agent.stop()

    check(
        agent.status is AutonomousAgentStatus.STOPPED,
        "C3: stop() from IDLE transitions status to STOPPED",
    )


# ---------------------------------------------------------------------------
# C4 -- stop() twice is idempotent
# ---------------------------------------------------------------------------
def scenario_stop_twice_is_idempotent() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.stop()

    raised = False
    try:
        agent.stop()
    except AutonomousAgentError:
        raised = True

    check(not raised, "C4: calling stop() a second time is not an error")
    check(
        agent.status is AutonomousAgentStatus.STOPPED,
        "C4: status remains STOPPED after a second stop() call",
    )


# ---------------------------------------------------------------------------
# C5 -- stop() preserves goal
# ---------------------------------------------------------------------------
def scenario_stop_preserves_goal() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    goal = _FakeGoal("monitor-bbca")
    agent.set_goal(goal)

    agent.stop()

    check(agent.goal is goal, "C5: stop() preserves goal")


# ---------------------------------------------------------------------------
# C6 -- stop() preserves current_plan
# ---------------------------------------------------------------------------
def scenario_stop_preserves_current_plan() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))
    plan = agent.plan_goal()

    agent.stop()

    check(agent.current_plan is plan, "C6: stop() preserves current_plan")


# ---------------------------------------------------------------------------
# C7 -- stop() preserves session
# ---------------------------------------------------------------------------
def scenario_stop_preserves_session() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    session_id = agent.start_session()
    started_at = agent.session_started_at

    agent.stop()

    check(agent.session_id == session_id, "C7: stop() preserves session_id")
    check(
        agent.session_started_at == started_at,
        "C7: stop() preserves session_started_at",
    )


# ---------------------------------------------------------------------------
# C8 -- stop() preserves timestamps (last_cycle_at)
# ---------------------------------------------------------------------------
def scenario_stop_preserves_last_cycle_at() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.step(_FakeContext("c8"))
    last_cycle_at = agent.last_cycle_at
    check(last_cycle_at is not None, "C8 precondition: last_cycle_at was set")

    agent.stop()

    check(
        agent.last_cycle_at == last_cycle_at,
        "C8: stop() preserves last_cycle_at",
    )


# ---------------------------------------------------------------------------
# C9 -- stop() preserves iteration_count
# ---------------------------------------------------------------------------
def scenario_stop_preserves_iteration_count() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.step(_FakeContext("c9-a"))
    agent.step(_FakeContext("c9-b"))
    check(agent.iteration_count == 2, "C9 precondition: two successful steps")

    agent.stop()

    check(agent.iteration_count == 2, "C9: stop() preserves iteration_count")


# ---------------------------------------------------------------------------
# C10 -- step() after stop() raises before reaching the pipeline
# ---------------------------------------------------------------------------
def scenario_step_after_stop_raises_before_pipeline() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    agent.stop()

    raised = False
    try:
        agent.step(_FakeContext("c10"))
    except AutonomousAgentError:
        raised = True

    check(raised, "C10: step() after stop() raises AutonomousAgentError")
    check(
        pipeline.calls == [],
        "C10: the refused step() call never reached the injected "
        "RuntimeAnalysisPipeline's run()",
    )
    check(
        agent.status is AutonomousAgentStatus.STOPPED,
        "C10: status remains STOPPED after the refused step() call",
    )


# ---------------------------------------------------------------------------
# C11 -- run() after stop() raises immediately, status stays STOPPED
# ---------------------------------------------------------------------------
def scenario_run_after_stop_raises_immediately() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    agent.stop()

    raised = False
    try:
        agent.run(_FakeContext("c11"), max_iterations=3)
    except AutonomousAgentError:
        raised = True

    check(raised, "C11: run() after stop() raises AutonomousAgentError")
    check(
        pipeline.calls == [],
        "C11: the refused run() call never reached the injected "
        "RuntimeAnalysisPipeline's run()",
    )
    check(
        agent.status is AutonomousAgentStatus.STOPPED,
        "C11: status remains STOPPED after the refused run() call "
        "(not overwritten to ERROR)",
    )


# ---------------------------------------------------------------------------
# C12 -- pause() after stop() raises
# ---------------------------------------------------------------------------
def scenario_pause_after_stop_raises() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.stop()

    raised = False
    try:
        agent.pause()
    except AutonomousAgentError:
        raised = True

    check(raised, "C12: pause() after stop() raises AutonomousAgentError")
    check(
        agent.status is AutonomousAgentStatus.STOPPED,
        "C12: status remains STOPPED after the refused pause() call",
    )


# ---------------------------------------------------------------------------
# C13 -- resume() after stop() raises
# ---------------------------------------------------------------------------
def scenario_resume_after_stop_raises() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.stop()

    raised = False
    try:
        agent.resume()
    except AutonomousAgentError:
        raised = True

    check(raised, "C13: resume() after stop() raises AutonomousAgentError")
    check(
        agent.status is AutonomousAgentStatus.STOPPED,
        "C13: status remains STOPPED after the refused resume() call",
    )


# ---------------------------------------------------------------------------
# C14 -- stop() from ERROR raises
# ---------------------------------------------------------------------------
def scenario_stop_from_error_raises() -> None:
    err_agent = _force_error(_make_agent_and_collaborators()[0])

    raised = False
    try:
        err_agent.stop()
    except AutonomousAgentError:
        raised = True

    check(raised, "C14: stop() from ERROR raises AutonomousAgentError")
    check(
        err_agent.status is AutonomousAgentStatus.ERROR,
        "C14: status remains ERROR after the refused stop() call",
    )


# ---------------------------------------------------------------------------
# C15 -- stop()/step()-after-stop/run()-after-stop never call
# RuntimeAnalysisPipeline or GoalPlanner
# ---------------------------------------------------------------------------
def scenario_stop_never_calls_pipeline_or_goal_planner() -> None:
    agent, pipeline, goal_planner = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))
    agent.plan_goal()
    goal_planner.build_plan_calls.clear()

    agent.stop()

    try:
        agent.step(_FakeContext("c15-step"))
    except AutonomousAgentError:
        pass
    try:
        agent.run(_FakeContext("c15-run"), max_iterations=2)
    except AutonomousAgentError:
        pass

    check(
        pipeline.calls == [],
        "C15: stop() and the refused step()/run() calls after it "
        "never reach the injected RuntimeAnalysisPipeline's run()",
    )
    check(
        goal_planner.build_plan_calls == [],
        "C15: stop() and the refused step()/run() calls after it "
        "never reach the injected GoalPlanner's build_plan()",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_stop_from_running,
        scenario_stop_from_paused,
        scenario_stop_from_idle,
        scenario_stop_twice_is_idempotent,
        scenario_stop_preserves_goal,
        scenario_stop_preserves_current_plan,
        scenario_stop_preserves_session,
        scenario_stop_preserves_last_cycle_at,
        scenario_stop_preserves_iteration_count,
        scenario_step_after_stop_raises_before_pipeline,
        scenario_run_after_stop_raises_immediately,
        scenario_pause_after_stop_raises,
        scenario_resume_after_stop_raises,
        scenario_stop_from_error_raises,
        scenario_stop_never_calls_pipeline_or_goal_planner,
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
    print(f"PHASE 2 SPRINT 10 STOP/CANCEL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())