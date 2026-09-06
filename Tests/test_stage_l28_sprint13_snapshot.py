"""
Phase 3 Sprint 13 proof suite -- AutonomousAgent persistent-state
snapshot (``AutonomousAgentSnapshot`` / ``AutonomousAgent.snapshot()``).

Scope: dedicated regression suite for
``Orchestration.autonomous_agent.AutonomousAgentSnapshot`` and
``AutonomousAgent.snapshot()`` only. Constructor/validation/
lifecycle-state-shape behavior for the ten L18-L27 dependencies plus
the constructor-injected ``runtime_analysis_pipeline``/``goal_planner``
is already covered by ``Tests/test_stage_l28_autonomous_agent.py``;
``step()``/``run()`` by their own Sprint 2/4 suites; goal ownership by
Sprint 5; session metadata by Sprint 6; GoalPlanner delegation by
Sprint 7; ExecutionPlan ownership by Sprint 8; pause/resume by Sprint
9; stop by Sprint 10; the ExecutionPlan -> AutonomousAgent ->
RuntimeAnalysisPipeline chain by Sprint 11; and AutonomousHost by
Sprint 12 -- none of that is re-verified here beyond what ``snapshot()``
itself needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, constructor-
injected exactly like the ten L18-L27 dependencies (same convention as
every prior Sprint suite). No persistence backend of any kind (no
files, no database, no network) is exercised or expected -- this
sprint defines the snapshot object only.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    S1  -- snapshot() returns an AutonomousAgentSnapshot instance.
    S2  -- the returned snapshot is immutable (frozen dataclass --
           attribute assignment raises FrozenInstanceError/
           dataclasses.FrozenInstanceError).
    S3  -- snapshot() reflects the agent's current lifecycle status.
    S4  -- snapshot() reflects the agent's current goal.
    S5  -- snapshot() reflects the agent's current_plan.
    S6  -- snapshot() reflects the agent's session_id.
    S7  -- snapshot() reflects the agent's session_started_at and
           last_cycle_at timestamps.
    S8  -- snapshot() does not mutate the agent (status,
           iteration_count, last_cycle_at, goal, current_plan,
           session_id, session_started_at all unchanged after the
           call).
    S9  -- snapshot() never invokes the injected
           RuntimeAnalysisPipeline's run().
    S10 -- snapshot() never invokes the injected GoalPlanner's
           build_plan().
    S11 -- repeated snapshot() calls return independent objects (not
           the same instance, and mutating agent state between calls
           does not retroactively change an earlier snapshot).
    S12 -- snapshot() survives pause()/resume()/stop(): each still
           produces a correctly-populated snapshot, and status
           reflects the lifecycle transition.
    S13 -- snapshot() after run() reflects the updated iteration_count
           and last_cycle_at.
    S14 -- AutonomousAgentSnapshot excludes the ten L18-L27
           collaborators, RuntimeAnalysisPipeline, and GoalPlanner --
           only the seven documented session-state fields exist on
           it.
"""

from __future__ import annotations

import dataclasses
import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.autonomous_agent import (
    AutonomousAgent,
    AutonomousAgentError,
    AutonomousAgentSnapshot,
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
    snapshot() never touches these."""

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
    """Stand-in for Orchestration.planner.GoalPlanner. snapshot() must
    never reach this."""

    def __init__(self) -> None:
        self.build_plan_calls: List[object] = []

    def build_plan(self, goal: object) -> _FakePlan:
        self.build_plan_calls.append(goal)
        return _FakePlan(f"plan-{len(self.build_plan_calls)}")


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call --
    used here to prove snapshot() never reaches it."""

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


# ---------------------------------------------------------------------------
# S1 -- snapshot() returns an AutonomousAgentSnapshot
# ---------------------------------------------------------------------------
def scenario_snapshot_returns_snapshot_type() -> None:
    agent, _, _ = _make_agent_and_collaborators()

    snap = agent.snapshot()

    check(
        isinstance(snap, AutonomousAgentSnapshot),
        "S1: snapshot() returns an AutonomousAgentSnapshot instance",
    )


# ---------------------------------------------------------------------------
# S2 -- snapshot is immutable
# ---------------------------------------------------------------------------
def scenario_snapshot_is_immutable() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    snap = agent.snapshot()

    raised = False
    try:
        snap.iteration_count = 999  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        raised = True

    check(
        raised,
        "S2: snapshot is immutable (attribute assignment raises "
        "FrozenInstanceError)",
    )


# ---------------------------------------------------------------------------
# S3 -- snapshot reflects current lifecycle status
# ---------------------------------------------------------------------------
def scenario_snapshot_reflects_status() -> None:
    agent, _, _ = _make_agent_and_collaborators()

    snap = agent.snapshot()

    check(
        snap.status is AutonomousAgentStatus.IDLE,
        "S3: snapshot() reflects current lifecycle status (IDLE)",
    )


# ---------------------------------------------------------------------------
# S4 -- snapshot reflects goal
# ---------------------------------------------------------------------------
def scenario_snapshot_reflects_goal() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    goal = _FakeGoal("monitor-bbca")
    agent.set_goal(goal)

    snap = agent.snapshot()

    check(snap.goal is goal, "S4: snapshot() reflects the agent's current goal")


# ---------------------------------------------------------------------------
# S5 -- snapshot reflects current_plan
# ---------------------------------------------------------------------------
def scenario_snapshot_reflects_current_plan() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))
    plan = agent.plan_goal()

    snap = agent.snapshot()

    check(
        snap.current_plan is plan,
        "S5: snapshot() reflects the agent's current_plan",
    )


# ---------------------------------------------------------------------------
# S6 -- snapshot reflects session_id
# ---------------------------------------------------------------------------
def scenario_snapshot_reflects_session_id() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    session_id = agent.start_session()

    snap = agent.snapshot()

    check(
        snap.session_id == session_id,
        "S6: snapshot() reflects the agent's session_id",
    )


# ---------------------------------------------------------------------------
# S7 -- snapshot reflects session_started_at and last_cycle_at
# ---------------------------------------------------------------------------
def scenario_snapshot_reflects_timestamps() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.start_session()
    started_at = agent.session_started_at
    agent.step(_FakeContext("s7"))
    last_cycle_at = agent.last_cycle_at

    snap = agent.snapshot()

    check(
        snap.session_started_at == started_at,
        "S7: snapshot() reflects session_started_at",
    )
    check(
        snap.last_cycle_at == last_cycle_at,
        "S7: snapshot() reflects last_cycle_at",
    )


# ---------------------------------------------------------------------------
# S8 -- snapshot() does not mutate the agent
# ---------------------------------------------------------------------------
def scenario_snapshot_does_not_mutate_agent() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))
    agent.plan_goal()
    agent.start_session()
    agent.step(_FakeContext("s8"))

    status_before = agent.status
    iteration_before = agent.iteration_count
    last_cycle_before = agent.last_cycle_at
    goal_before = agent.goal
    plan_before = agent.current_plan
    session_id_before = agent.session_id
    session_started_before = agent.session_started_at

    agent.snapshot()

    check(agent.status is status_before, "S8: snapshot() preserves status")
    check(
        agent.iteration_count == iteration_before,
        "S8: snapshot() preserves iteration_count",
    )
    check(
        agent.last_cycle_at == last_cycle_before,
        "S8: snapshot() preserves last_cycle_at",
    )
    check(agent.goal is goal_before, "S8: snapshot() preserves goal")
    check(
        agent.current_plan is plan_before,
        "S8: snapshot() preserves current_plan",
    )
    check(
        agent.session_id == session_id_before,
        "S8: snapshot() preserves session_id",
    )
    check(
        agent.session_started_at == session_started_before,
        "S8: snapshot() preserves session_started_at",
    )


# ---------------------------------------------------------------------------
# S9 -- snapshot() never invokes RuntimeAnalysisPipeline
# ---------------------------------------------------------------------------
def scenario_snapshot_never_calls_pipeline() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))

    agent.snapshot()

    check(
        pipeline.calls == [],
        "S9: snapshot() never calls the injected "
        "RuntimeAnalysisPipeline's run()",
    )


# ---------------------------------------------------------------------------
# S10 -- snapshot() never invokes GoalPlanner
# ---------------------------------------------------------------------------
def scenario_snapshot_never_calls_goal_planner() -> None:
    agent, _, goal_planner = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))

    agent.snapshot()

    check(
        goal_planner.build_plan_calls == [],
        "S10: snapshot() never calls the injected GoalPlanner's "
        "build_plan()",
    )


# ---------------------------------------------------------------------------
# S11 -- repeated snapshot() calls return independent objects
# ---------------------------------------------------------------------------
def scenario_repeated_snapshots_are_independent() -> None:
    agent, _, _ = _make_agent_and_collaborators()

    snap1 = agent.snapshot()
    agent.step(_FakeContext("s11"))
    snap2 = agent.snapshot()

    check(snap1 is not snap2, "S11: repeated snapshot() calls return distinct objects")
    check(
        snap1.iteration_count == 0,
        "S11: an earlier snapshot is unaffected by later agent state changes",
    )
    check(
        snap2.iteration_count == 1,
        "S11: a later snapshot reflects the agent's state at that later time",
    )


# ---------------------------------------------------------------------------
# S12 -- snapshot() survives pause()/resume()/stop()
# ---------------------------------------------------------------------------
def scenario_snapshot_survives_pause_resume_stop() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent._status = AutonomousAgentStatus.RUNNING  # test-setup only, RUNNING
    # is otherwise a transient in-step() state (same precedent as the
    # Sprint 9 pause/resume suite).

    agent.pause()
    snap_paused = agent.snapshot()
    check(
        snap_paused.status is AutonomousAgentStatus.PAUSED,
        "S12: snapshot() after pause() reflects PAUSED",
    )

    agent.resume()
    snap_resumed = agent.snapshot()
    check(
        snap_resumed.status is AutonomousAgentStatus.RUNNING,
        "S12: snapshot() after resume() reflects RUNNING",
    )

    agent.stop()
    snap_stopped = agent.snapshot()
    check(
        snap_stopped.status is AutonomousAgentStatus.STOPPED,
        "S12: snapshot() after stop() reflects STOPPED",
    )


# ---------------------------------------------------------------------------
# S13 -- snapshot() after run() reflects updated iteration_count
# ---------------------------------------------------------------------------
def scenario_snapshot_after_run_reflects_iteration_count() -> None:
    agent, _, _ = _make_agent_and_collaborators()

    agent.run(_FakeContext("s13"), max_iterations=3)
    snap = agent.snapshot()

    check(
        snap.iteration_count == 3,
        "S13: snapshot() after run() reflects updated iteration_count",
    )
    check(
        snap.last_cycle_at == agent.last_cycle_at,
        "S13: snapshot() after run() reflects updated last_cycle_at",
    )
    check(
        snap.status is AutonomousAgentStatus.IDLE,
        "S13: snapshot() after a successful run() reflects IDLE",
    )


# ---------------------------------------------------------------------------
# S14 -- AutonomousAgentSnapshot excludes collaborators
# ---------------------------------------------------------------------------
def scenario_snapshot_excludes_collaborators() -> None:
    field_names = {f.name for f in dataclasses.fields(AutonomousAgentSnapshot)}
    expected = {
        "status",
        "iteration_count",
        "last_cycle_at",
        "goal",
        "current_plan",
        "session_id",
        "session_started_at",
    }

    check(
        field_names == expected,
        "S14: AutonomousAgentSnapshot exposes exactly the seven "
        "documented session-state fields, and nothing else "
        f"(got {sorted(field_names)})",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_snapshot_returns_snapshot_type,
        scenario_snapshot_is_immutable,
        scenario_snapshot_reflects_status,
        scenario_snapshot_reflects_goal,
        scenario_snapshot_reflects_current_plan,
        scenario_snapshot_reflects_session_id,
        scenario_snapshot_reflects_timestamps,
        scenario_snapshot_does_not_mutate_agent,
        scenario_snapshot_never_calls_pipeline,
        scenario_snapshot_never_calls_goal_planner,
        scenario_repeated_snapshots_are_independent,
        scenario_snapshot_survives_pause_resume_stop,
        scenario_snapshot_after_run_reflects_iteration_count,
        scenario_snapshot_excludes_collaborators,
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
    print(f"PHASE 3 SPRINT 13 SNAPSHOT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())