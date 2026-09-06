"""
Phase 2 Sprint 7 proof suite -- AutonomousAgent GoalPlanner
integration (constructor-injected ``goal_planner`` + ``plan_goal()``).

Scope: dedicated regression suite for the Sprint 7 ``goal_planner``
constructor argument and ``AutonomousAgent.plan_goal`` only.
Constructor/validation/lifecycle-state-shape behavior for the ten
L18-L27 dependencies plus the Sprint 3 constructor-injected
``runtime_analysis_pipeline`` is already covered by
``Tests/test_stage_l28_autonomous_agent.py``, ``step()``'s own
dedicated behavior by ``Tests/test_stage_l28_sprint2_step.py``,
``run()``'s own dedicated behavior by
``Tests/test_stage_l28_sprint4_run.py``, goal storage by
``Tests/test_stage_l28_sprint5_goal.py``, and session metadata by
``Tests/test_stage_l28_sprint6_session.py`` -- none of that is
re-verified here beyond what GoalPlanner integration itself needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, constructor-
injected exactly like the ten L18-L27 dependencies (same convention
as every prior Sprint suite). The real
``Orchestration.planner.GoalPlanner`` is reused unmodified in
production (see ``Core.composition_root._build_autonomous_agent``);
this suite only proves ``AutonomousAgent`` delegates to whatever
``build_plan`` its injected collaborator exposes, without wrapping,
transforming, or otherwise re-implementing GoalPlanner's own logic.
No plan is ever executed here (``execute_plan`` is never called by
``plan_goal()``), no scheduler, no pause/resume/cancel -- all
explicitly out of scope for Sprint 7.

Follows the same scenario-based, no-pytest, no-external-mocks style
as the other Stage L1x-L2x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    P1  -- a freshly constructed agent's injected goal_planner is the
           exact same object instance passed into the constructor
           (identity check).
    P2  -- constructing with goal_planner=None raises
           AutonomousAgentError.
    P3  -- plan_goal() with no goal set (goal is None) raises
           AutonomousAgentError, without calling the injected
           GoalPlanner.
    P4  -- plan_goal() with a goal set delegates to
           goal_planner.build_plan(goal).
    P5  -- goal_planner.build_plan() is called exactly once per
           plan_goal() call.
    P6  -- plan_goal()'s return value is exactly the object
           goal_planner.build_plan() returned -- unwrapped,
           untransformed, identity-equal.
    P7  -- the goal passed to goal_planner.build_plan() is exactly
           the same object set via set_goal() -- identity-equal, not
           copied.
    P8  -- goal is unchanged (still the same value) after plan_goal()
           completes.
    P9  -- status is unchanged by plan_goal().
    P10 -- session_id/session_started_at are unchanged by
           plan_goal() (across both "no active session" and "active
           session" cases).
    P11 -- iteration_count is unchanged by plan_goal().
    P12 -- the injected RuntimeAnalysisPipeline's run() is never
           called by plan_goal().
    P13 -- step() still works normally after plan_goal() has been
           called, and step() never touches goal_planner.
    P14 -- run() still works normally after plan_goal() has been
           called, and run() never touches goal_planner.
    P15 -- calling plan_goal() twice for the same goal calls
           goal_planner.build_plan() twice (no caching/memoization
           assumed or required).
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
    Neither step(), run(), nor plan_goal() ever touches these."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeContext:
    """Stand-in for a ServiceContext. Treated as opaque and passed
    through unchanged."""

    def __init__(self, tag: str = "ctx") -> None:
        self.tag = tag


class _FakeGoal:
    """Stand-in for an Orchestration.planner.Goal. plan_goal() treats
    the stored goal as an opaque object -- it never inspects it, only
    forwards it to build_plan()."""

    def __init__(self, label: str) -> None:
        self.label = label


class _FakePlan:
    """Stand-in for an Orchestration.planner.ExecutionPlan. Only used
    to prove plan_goal() returns build_plan()'s result unchanged."""

    def __init__(self, label: str) -> None:
        self.label = label


class _FakeGoalPlanner:
    """Stand-in for Orchestration.planner.GoalPlanner. Records every
    build_plan() call (including the exact goal object received) and
    returns a fixed sentinel plan -- never itself does forward-chaining
    or touches a real ServiceSkill registry. execute_plan() is
    deliberately NOT implemented -- plan_goal() must never call it."""

    def __init__(self) -> None:
        self.build_plan_calls: List[object] = []
        self._plan = _FakePlan("plan-for-goal")

    def build_plan(self, goal: object) -> _FakePlan:
        self.build_plan_calls.append(goal)
        return self._plan


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call --
    never itself runs AnalysisPipeline or any real stage. Used here
    only to prove plan_goal() never reaches it, and that run()/step()
    still work unchanged after plan_goal() is used."""

    def __init__(self) -> None:
        self.calls: List[object] = []

    def run(self, context: object) -> str:
        self.calls.append(context)
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


# ---------------------------------------------------------------------------
# P1 -- goal_planner injected, identity preserved
# ---------------------------------------------------------------------------
def scenario_goal_planner_injected_identity() -> None:
    agent, _, goal_planner = _make_agent_and_collaborators()
    check(
        agent._goal_planner is goal_planner,
        "P1: the agent's held goal_planner reference is the exact "
        "same object passed into the constructor",
    )


# ---------------------------------------------------------------------------
# P2 -- goal_planner=None rejected
# ---------------------------------------------------------------------------
def scenario_goal_planner_none_rejected() -> None:
    pipeline = _FakeRuntimeAnalysisPipeline()
    raised = False
    try:
        AutonomousAgent(
            runtime_analysis_pipeline=pipeline,
            goal_planner=None,
            **{name: _FakeComponent(name) for name in _FIELD_NAMES},
        )
    except AutonomousAgentError:
        raised = True
    except Exception:  # noqa: BLE001
        raised = False
    check(raised, "P2: constructing with goal_planner=None raises AutonomousAgentError")


# ---------------------------------------------------------------------------
# P3 -- no goal set raises, planner never called
# ---------------------------------------------------------------------------
def scenario_plan_goal_without_goal_raises() -> None:
    agent, _, goal_planner = _make_agent_and_collaborators()
    check(agent.goal is None, "P3 precondition: no goal is set on a fresh agent")

    raised = False
    try:
        agent.plan_goal()
    except AutonomousAgentError:
        raised = True
    except Exception:  # noqa: BLE001
        raised = False

    check(raised, "P3: plan_goal() with no goal set raises AutonomousAgentError")
    check(
        goal_planner.build_plan_calls == [],
        "P3: the rejected plan_goal() call never reached the "
        "injected GoalPlanner's build_plan()",
    )


# ---------------------------------------------------------------------------
# P4/P5/P7 -- valid goal delegates to GoalPlanner, called once, exact object
# ---------------------------------------------------------------------------
def scenario_plan_goal_delegates_to_goal_planner() -> None:
    agent, _, goal_planner = _make_agent_and_collaborators()
    goal = _FakeGoal("monitor-bbca")
    agent.set_goal(goal)

    agent.plan_goal()

    check(
        len(goal_planner.build_plan_calls) == 1,
        "P5: goal_planner.build_plan() is called exactly once per "
        "plan_goal() call",
    )
    check(
        goal_planner.build_plan_calls[0] is goal,
        "P4/P7: the goal passed to build_plan() is the exact same "
        "object set via set_goal() -- not copied, not wrapped",
    )


# ---------------------------------------------------------------------------
# P6 -- return value passed through unchanged
# ---------------------------------------------------------------------------
def scenario_plan_goal_returns_build_plan_result_unchanged() -> None:
    agent, _, goal_planner = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))

    result = agent.plan_goal()

    check(
        result is goal_planner._plan,
        "P6: plan_goal()'s return value is exactly the object "
        "goal_planner.build_plan() returned -- unwrapped, "
        "untransformed",
    )


# ---------------------------------------------------------------------------
# P8 -- goal unchanged after planning
# ---------------------------------------------------------------------------
def scenario_goal_unchanged_after_plan_goal() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    goal = _FakeGoal("monitor-bbca")
    agent.set_goal(goal)

    agent.plan_goal()

    check(
        agent.goal is goal,
        "P8: goal is unchanged (still the exact same object) after "
        "plan_goal() completes",
    )


# ---------------------------------------------------------------------------
# P9/P10/P11 -- status/session/iteration_count untouched
# ---------------------------------------------------------------------------
def scenario_plan_goal_leaves_other_state_untouched() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))

    status_before = agent.status
    iteration_before = agent.iteration_count

    # Case 1: no active session.
    agent.plan_goal()
    check(agent.status == status_before, "P9: status unchanged by plan_goal() (no session)")
    check(
        agent.iteration_count == iteration_before,
        "P11: iteration_count unchanged by plan_goal() (no session)",
    )
    check(
        agent.session_id is None and agent.session_started_at is None,
        "P10: session_id/session_started_at remain None after "
        "plan_goal() when no session was active",
    )

    # Case 2: active session.
    session_id = agent.start_session()
    started_at = agent.session_started_at
    agent.plan_goal()
    check(
        agent.session_id == session_id and agent.session_started_at == started_at,
        "P10: an active session's session_id/session_started_at are "
        "unchanged by plan_goal()",
    )
    check(agent.status == status_before, "P9: status unchanged by plan_goal() (active session)")
    check(
        agent.iteration_count == iteration_before,
        "P11: iteration_count unchanged by plan_goal() (active session)",
    )
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "P9: status remains the initial IDLE value throughout",
    )


# ---------------------------------------------------------------------------
# P12 -- pipeline never called by plan_goal()
# ---------------------------------------------------------------------------
def scenario_plan_goal_never_calls_pipeline() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))

    agent.plan_goal()
    agent.plan_goal()

    check(
        pipeline.calls == [],
        "P12: plan_goal() never calls the injected "
        "RuntimeAnalysisPipeline's run()",
    )


# ---------------------------------------------------------------------------
# P13 -- step() still works after plan_goal(), and never touches goal_planner
# ---------------------------------------------------------------------------
def scenario_step_still_works_after_plan_goal() -> None:
    agent, pipeline, goal_planner = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))
    agent.plan_goal()

    result = agent.step(_FakeContext("p13"))

    check(result.success is True, "P13: step() still succeeds after plan_goal()")
    check(
        agent.iteration_count == 1,
        "P13: step() still increments iteration_count normally",
    )
    check(
        len(goal_planner.build_plan_calls) == 1,
        "P13: step() itself never calls the injected GoalPlanner's "
        "build_plan() (still exactly the one call from plan_goal())",
    )
    check(len(pipeline.calls) == 1, "P13: step() still delegates to the pipeline exactly once")


# ---------------------------------------------------------------------------
# P14 -- run() still works after plan_goal(), and never touches goal_planner
# ---------------------------------------------------------------------------
def scenario_run_still_works_after_plan_goal() -> None:
    agent, pipeline, goal_planner = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))
    agent.plan_goal()

    results = agent.run(_FakeContext("p14"), max_iterations=3)

    check(
        len(results) == 3 and all(r.success for r in results),
        "P14: run() still completes normally after plan_goal() was "
        "called earlier",
    )
    check(
        len(goal_planner.build_plan_calls) == 1,
        "P14: run() itself never calls the injected GoalPlanner's "
        "build_plan() (still exactly the one call from plan_goal())",
    )
    check(len(pipeline.calls) == 3, "P14: run() still delegates to the pipeline exactly 3 times")


# ---------------------------------------------------------------------------
# P15 -- repeated plan_goal() calls the planner again each time
# ---------------------------------------------------------------------------
def scenario_repeated_plan_goal_calls_planner_again() -> None:
    agent, _, goal_planner = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))

    agent.plan_goal()
    agent.plan_goal()

    check(
        len(goal_planner.build_plan_calls) == 2,
        "P15: calling plan_goal() twice for the same goal calls "
        "build_plan() twice -- no caching/memoization",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_goal_planner_injected_identity,
        scenario_goal_planner_none_rejected,
        scenario_plan_goal_without_goal_raises,
        scenario_plan_goal_delegates_to_goal_planner,
        scenario_plan_goal_returns_build_plan_result_unchanged,
        scenario_goal_unchanged_after_plan_goal,
        scenario_plan_goal_leaves_other_state_untouched,
        scenario_plan_goal_never_calls_pipeline,
        scenario_step_still_works_after_plan_goal,
        scenario_run_still_works_after_plan_goal,
        scenario_repeated_plan_goal_calls_planner_again,
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
    print(f"PHASE 2 SPRINT 7 GOALPLANNER INTEGRATION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())