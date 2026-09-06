"""
Phase 3 Sprint 14 proof suite -- AutonomousAgent snapshot restoration
(``AutonomousAgent.restore()``).

Scope: dedicated regression suite for
``Orchestration.autonomous_agent.AutonomousAgent.restore()`` only.
Construction/validation/lifecycle-state-shape behavior for the ten
L18-L27 dependencies plus the constructor-injected
``runtime_analysis_pipeline``/``goal_planner`` is already covered by
``Tests/test_stage_l28_autonomous_agent.py``; ``step()``/``run()`` by
their own Sprint 2/4 suites; goal ownership by Sprint 5; session
metadata by Sprint 6; GoalPlanner delegation by Sprint 7; ExecutionPlan
ownership by Sprint 8; pause/resume by Sprint 9; stop by Sprint 10; the
ExecutionPlan -> AutonomousAgent -> RuntimeAnalysisPipeline chain by
Sprint 11; AutonomousHost by Sprint 12; and ``AutonomousAgentSnapshot``/
``snapshot()`` by Sprint 13 -- none of that is re-verified here beyond
what ``restore()`` itself needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, constructor-
injected exactly like the ten L18-L27 dependencies (same convention as
every prior Sprint suite). No persistence backend of any kind (no
files, no database, no network) is exercised or expected -- this
sprint restores from an already-existing, in-memory
``AutonomousAgentSnapshot`` only.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    R1  -- restore(None) raises AutonomousAgentError.
    R2  -- restore(invalid object) raises AutonomousAgentError.
    R3  -- restore(snapshot) restores status.
    R4  -- restore(snapshot) restores iteration_count.
    R5  -- restore(snapshot) restores last_cycle_at.
    R6  -- restore(snapshot) restores goal.
    R7  -- restore(snapshot) restores current_plan.
    R8  -- restore(snapshot) restores session_id.
    R9  -- restore(snapshot) restores session_started_at.
    R10 -- restore(snapshot) never mutates the snapshot itself.
    R11 -- restore(snapshot) never invokes the injected
           RuntimeAnalysisPipeline's run().
    R12 -- restore(snapshot) never invokes the injected GoalPlanner's
           build_plan().
    R13 -- restore(snapshot) works after stop() (both restoring a
           STOPPED snapshot onto a fresh agent, and restoring a
           non-STOPPED snapshot onto a stopped agent).
    R14 -- restore(snapshot) works after pause() (both restoring a
           PAUSED snapshot onto a fresh agent, and restoring an
           IDLE/RUNNING snapshot onto a paused agent).
    R15 -- snapshot() -> restore() -> snapshot() round-trip equality:
           the second snapshot equals the first, field for field.
    R16 -- restore() returns None (mutates in place, does not
           construct or return a new AutonomousAgent).
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
    restore() never touches these."""

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
    """Stand-in for Orchestration.planner.GoalPlanner. restore() must
    never reach this."""

    def __init__(self) -> None:
        self.build_plan_calls: List[object] = []

    def build_plan(self, goal: object) -> _FakePlan:
        self.build_plan_calls.append(goal)
        return _FakePlan(f"plan-{len(self.build_plan_calls)}")


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call --
    used here to prove restore() never reaches it."""

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


def _make_full_snapshot() -> AutonomousAgentSnapshot:
    """A snapshot with every field populated to a distinctive,
    non-default value -- built directly, not via a real agent, so
    each restore scenario is self-contained."""
    return AutonomousAgentSnapshot(
        status=AutonomousAgentStatus.IDLE,
        iteration_count=7,
        last_cycle_at=1234.5,
        goal=_FakeGoal("restored-goal"),
        current_plan=_FakePlan("restored-plan"),
        session_id="restored-session-id",
        session_started_at="restored-started-at",  # opaque, duck-typed
    )


# ---------------------------------------------------------------------------
# R1 -- restore(None) raises AutonomousAgentError
# ---------------------------------------------------------------------------
def scenario_restore_none_raises() -> None:
    agent, _, _ = _make_agent_and_collaborators()

    raised = False
    try:
        agent.restore(None)
    except AutonomousAgentError:
        raised = True

    check(raised, "R1: restore(None) raises AutonomousAgentError")


# ---------------------------------------------------------------------------
# R2 -- restore(invalid object) raises AutonomousAgentError
# ---------------------------------------------------------------------------
def scenario_restore_invalid_object_raises() -> None:
    agent, _, _ = _make_agent_and_collaborators()

    for bad in (
        "not-a-snapshot",
        123,
        {"status": AutonomousAgentStatus.IDLE},
        _FakeComponent("not-a-snapshot"),
        object(),
    ):
        raised = False
        try:
            agent.restore(bad)  # type: ignore[arg-type]
        except AutonomousAgentError:
            raised = True

        check(
            raised,
            "R2: restore(invalid object) raises AutonomousAgentError "
            f"(got {type(bad).__name__!r})",
        )


# ---------------------------------------------------------------------------
# R3-R9 -- restore(snapshot) restores every documented field
# ---------------------------------------------------------------------------
def scenario_restore_restores_all_fields() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    snap = _make_full_snapshot()

    agent.restore(snap)

    check(agent.status is snap.status, "R3: restore() restores status")
    check(
        agent.iteration_count == snap.iteration_count,
        "R4: restore() restores iteration_count",
    )
    check(
        agent.last_cycle_at == snap.last_cycle_at,
        "R5: restore() restores last_cycle_at",
    )
    check(agent.goal is snap.goal, "R6: restore() restores goal")
    check(
        agent.current_plan is snap.current_plan,
        "R7: restore() restores current_plan",
    )
    check(
        agent.session_id == snap.session_id,
        "R8: restore() restores session_id",
    )
    check(
        agent.session_started_at == snap.session_started_at,
        "R9: restore() restores session_started_at",
    )


# ---------------------------------------------------------------------------
# R10 -- restore() never mutates the snapshot itself
# ---------------------------------------------------------------------------
def scenario_restore_does_not_mutate_snapshot() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    snap = _make_full_snapshot()

    status_before = snap.status
    iteration_before = snap.iteration_count
    last_cycle_before = snap.last_cycle_at
    goal_before = snap.goal
    plan_before = snap.current_plan
    session_id_before = snap.session_id
    session_started_before = snap.session_started_at

    agent.restore(snap)
    # Mutate the agent further afterward -- the earlier snapshot must
    # remain untouched regardless.
    agent.pause() if agent.status is AutonomousAgentStatus.RUNNING else None

    check(snap.status is status_before, "R10: restore() preserves snapshot.status")
    check(
        snap.iteration_count == iteration_before,
        "R10: restore() preserves snapshot.iteration_count",
    )
    check(
        snap.last_cycle_at == last_cycle_before,
        "R10: restore() preserves snapshot.last_cycle_at",
    )
    check(snap.goal is goal_before, "R10: restore() preserves snapshot.goal")
    check(
        snap.current_plan is plan_before,
        "R10: restore() preserves snapshot.current_plan",
    )
    check(
        snap.session_id == session_id_before,
        "R10: restore() preserves snapshot.session_id",
    )
    check(
        snap.session_started_at == session_started_before,
        "R10: restore() preserves snapshot.session_started_at",
    )


# ---------------------------------------------------------------------------
# R11 -- restore() never invokes RuntimeAnalysisPipeline
# ---------------------------------------------------------------------------
def scenario_restore_never_calls_pipeline() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    snap = _make_full_snapshot()

    agent.restore(snap)

    check(
        pipeline.calls == [],
        "R11: restore() never calls the injected "
        "RuntimeAnalysisPipeline's run()",
    )


# ---------------------------------------------------------------------------
# R12 -- restore() never invokes GoalPlanner
# ---------------------------------------------------------------------------
def scenario_restore_never_calls_goal_planner() -> None:
    agent, _, goal_planner = _make_agent_and_collaborators()
    snap = _make_full_snapshot()

    agent.restore(snap)

    check(
        goal_planner.build_plan_calls == [],
        "R12: restore() never calls the injected GoalPlanner's "
        "build_plan()",
    )


# ---------------------------------------------------------------------------
# R13 -- restore() works after stop()
# ---------------------------------------------------------------------------
def scenario_restore_after_stop() -> None:
    # (a) restoring a STOPPED snapshot onto a fresh agent.
    agent_a, _, _ = _make_agent_and_collaborators()
    stopped_snap = AutonomousAgentSnapshot(
        status=AutonomousAgentStatus.STOPPED,
        iteration_count=3,
        last_cycle_at=999.0,
        goal=_FakeGoal("g"),
        current_plan=_FakePlan("p"),
        session_id="sess-a",
        session_started_at="started-a",
    )
    agent_a.restore(stopped_snap)
    check(
        agent_a.status is AutonomousAgentStatus.STOPPED,
        "R13a: restore() can set an agent's status to STOPPED via a "
        "STOPPED snapshot",
    )
    check(
        agent_a.iteration_count == 3,
        "R13a: restore() restores iteration_count alongside a "
        "STOPPED status",
    )

    # (b) restoring a non-STOPPED snapshot onto an agent that has
    # actually been stop()-ped -- restore() is pure state assignment,
    # so it must succeed and overwrite STOPPED just like any other
    # field value, with no special-casing.
    agent_b, pipeline_b, _ = _make_agent_and_collaborators()
    agent_b.start_session()
    agent_b.step(_FakeContext("pre-stop"))
    agent_b.stop()
    check(
        agent_b.status is AutonomousAgentStatus.STOPPED,
        "R13b: precondition -- agent_b is actually STOPPED",
    )

    idle_snap = agent_b.snapshot()
    idle_snap = AutonomousAgentSnapshot(
        status=AutonomousAgentStatus.IDLE,
        iteration_count=idle_snap.iteration_count,
        last_cycle_at=idle_snap.last_cycle_at,
        goal=idle_snap.goal,
        current_plan=idle_snap.current_plan,
        session_id=idle_snap.session_id,
        session_started_at=idle_snap.session_started_at,
    )
    pipeline_calls_before_restore = len(pipeline_b.calls)
    agent_b.restore(idle_snap)
    check(
        agent_b.status is AutonomousAgentStatus.IDLE,
        "R13b: restore() overwrites a STOPPED agent's status with "
        "the snapshot's status (pure assignment, no special-casing)",
    )
    check(
        len(pipeline_b.calls) == pipeline_calls_before_restore,
        "R13b: restore() itself never calls the pipeline (call count "
        "unchanged by restore(); the one existing call was from the "
        "earlier step(), not restore())",
    )


# ---------------------------------------------------------------------------
# R14 -- restore() works after pause()
# ---------------------------------------------------------------------------
def scenario_restore_after_pause() -> None:
    # (a) restoring a PAUSED snapshot onto a fresh agent.
    agent_a, _, _ = _make_agent_and_collaborators()
    paused_snap = AutonomousAgentSnapshot(
        status=AutonomousAgentStatus.PAUSED,
        iteration_count=2,
        last_cycle_at=111.0,
        goal=_FakeGoal("g"),
        current_plan=_FakePlan("p"),
        session_id="sess-b",
        session_started_at="started-b",
    )
    agent_a.restore(paused_snap)
    check(
        agent_a.status is AutonomousAgentStatus.PAUSED,
        "R14a: restore() can set an agent's status to PAUSED via a "
        "PAUSED snapshot",
    )

    # (b) restoring a snapshot onto an agent that has actually been
    # pause()-d.
    agent_b, _, _ = _make_agent_and_collaborators()
    agent_b.start_session()
    agent_b.step(_FakeContext("pre-pause"))
    # step() leaves status IDLE after success; force RUNNING then pause.
    agent_b._status = AutonomousAgentStatus.RUNNING  # type: ignore[attr-defined]
    agent_b.pause()
    check(
        agent_b.status is AutonomousAgentStatus.PAUSED,
        "R14b: precondition -- agent_b is actually PAUSED",
    )

    running_snap = AutonomousAgentSnapshot(
        status=AutonomousAgentStatus.RUNNING,
        iteration_count=agent_b.iteration_count,
        last_cycle_at=agent_b.last_cycle_at,
        goal=agent_b.goal,
        current_plan=agent_b.current_plan,
        session_id=agent_b.session_id,
        session_started_at=agent_b.session_started_at,
    )
    agent_b.restore(running_snap)
    check(
        agent_b.status is AutonomousAgentStatus.RUNNING,
        "R14b: restore() overwrites a PAUSED agent's status with the "
        "snapshot's status",
    )


# ---------------------------------------------------------------------------
# R15 -- snapshot() -> restore() -> snapshot() round-trip equality
# ---------------------------------------------------------------------------
def scenario_round_trip_equality() -> None:
    source_agent, _, _ = _make_agent_and_collaborators()
    source_agent.set_goal(_FakeGoal("monitor-bbca"))
    source_agent.plan_goal()
    source_agent.start_session()
    source_agent.step(_FakeContext("r15"))

    snap1 = source_agent.snapshot()

    target_agent, _, _ = _make_agent_and_collaborators()
    target_agent.restore(snap1)
    snap2 = target_agent.snapshot()

    check(
        snap2 == snap1,
        "R15: snapshot() -> restore() -> snapshot() round-trip "
        "produces an equal snapshot",
    )
    check(
        snap2 is not snap1,
        "R15: the round-trip snapshot is a distinct object, not the "
        "same instance",
    )


# ---------------------------------------------------------------------------
# R16 -- restore() returns None
# ---------------------------------------------------------------------------
def scenario_restore_returns_none() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    snap = _make_full_snapshot()

    result = agent.restore(snap)

    check(
        result is None,
        "R16: restore() returns None (mutates self in place, does "
        "not construct/return a new AutonomousAgent)",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_restore_none_raises,
        scenario_restore_invalid_object_raises,
        scenario_restore_restores_all_fields,
        scenario_restore_does_not_mutate_snapshot,
        scenario_restore_never_calls_pipeline,
        scenario_restore_never_calls_goal_planner,
        scenario_restore_after_stop,
        scenario_restore_after_pause,
        scenario_round_trip_equality,
        scenario_restore_returns_none,
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
    print(f"PHASE 3 SPRINT 14 RESTORE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())