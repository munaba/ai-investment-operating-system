"""
Phase 2 Sprint 8 proof suite -- AutonomousAgent ExecutionPlan
ownership (``current_plan`` / ``clear_plan()``, and ``plan_goal()``'s
new storage behavior).

Scope: dedicated regression suite for the Sprint 8 ``current_plan``
property, ``clear_plan()``, and ``plan_goal()``'s additional
plan-storage behavior only. Constructor/validation/lifecycle-state-
shape behavior for the ten L18-L27 dependencies plus the Sprint 3
constructor-injected ``runtime_analysis_pipeline`` is already covered
by ``Tests/test_stage_l28_autonomous_agent.py``, ``step()``'s own
dedicated behavior by ``Tests/test_stage_l28_sprint2_step.py``,
``run()``'s own dedicated behavior by
``Tests/test_stage_l28_sprint4_run.py``, goal storage by
``Tests/test_stage_l28_sprint5_goal.py``, session metadata by
``Tests/test_stage_l28_sprint6_session.py``, and GoalPlanner
delegation/injection by ``Tests/test_stage_l28_sprint7_goalplanner.py``
-- none of that is re-verified here beyond what plan ownership itself
needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, constructor-
injected exactly like the ten L18-L27 dependencies (same convention
as every prior Sprint suite). ``GoalPlanner`` still owns all plan
*creation* logic (``build_plan()``) -- this suite only proves
``AutonomousAgent`` remembers whatever it was handed, unmodified. No
plan is ever executed here (``execute_plan`` is never called), no
scheduler, no pause/resume/cancel -- all explicitly out of scope for
Sprint 8.

Follows the same scenario-based, no-pytest, no-external-mocks style
as the other Stage L1x-L2x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    E1  -- current_plan is None by default on a freshly constructed
           agent.
    E2  -- a successful plan_goal() call stores the resulting plan as
           current_plan.
    E3  -- plan_goal()'s returned object and the stored current_plan
           are the exact same object (identity, not equality).
    E4  -- calling plan_goal() a second time (e.g. after the goal
           changes) replaces current_plan with the new plan -- no
           history of the previous one is kept.
    E5  -- clear_plan() resets current_plan back to None.
    E6  -- clear_plan() called twice in a row is not an error.
    E7  -- a rejected plan_goal() call (no goal set) leaves
           current_plan unchanged.
    E8  -- goal is unchanged by plan_goal()/clear_plan().
    E9  -- session_id/session_started_at are unchanged by
           plan_goal()/clear_plan().
    E10 -- status is unchanged by plan_goal()/clear_plan().
    E11 -- iteration_count is unchanged by plan_goal()/clear_plan().
    E12 -- the injected RuntimeAnalysisPipeline's run() is never
           called by plan_goal() or clear_plan().
    E13 -- run() still works normally after plan_goal()/clear_plan()
           have been called, and current_plan is unaffected by run()
           itself.
    E14 -- step() still works normally after plan_goal()/clear_plan()
           have been called, and current_plan is unaffected by
           step() itself.
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
    Neither step(), run(), plan_goal(), nor clear_plan() ever touches
    these."""

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
    to prove plan_goal()/current_plan hold build_plan()'s result
    unchanged."""

    def __init__(self, label: str) -> None:
        self.label = label


class _FakeGoalPlanner:
    """Stand-in for Orchestration.planner.GoalPlanner. Records every
    build_plan() call and returns a fresh, distinct sentinel plan each
    time -- never itself does forward-chaining or touches a real
    ServiceSkill registry. execute_plan() is deliberately NOT
    implemented -- plan_goal()/clear_plan() must never call it."""

    def __init__(self) -> None:
        self.build_plan_calls: List[object] = []

    def build_plan(self, goal: object) -> _FakePlan:
        self.build_plan_calls.append(goal)
        return _FakePlan(f"plan-{len(self.build_plan_calls)}")


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call --
    never itself runs AnalysisPipeline or any real stage. Used here
    only to prove plan_goal()/clear_plan() never reach it, and that
    run()/step() still work unchanged after plan mutation."""

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
# E1 -- default current_plan is None
# ---------------------------------------------------------------------------
def scenario_default_current_plan_is_none() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    check(agent.current_plan is None, "E1: current_plan is None on a fresh agent")


# ---------------------------------------------------------------------------
# E2/E3 -- successful planning stores the plan, identity preserved
# ---------------------------------------------------------------------------
def scenario_plan_goal_stores_plan_with_identity() -> None:
    agent, _, goal_planner = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))

    returned = agent.plan_goal()

    check(
        agent.current_plan is not None,
        "E2: current_plan is populated after a successful plan_goal() call",
    )
    check(
        returned is agent.current_plan,
        "E3: plan_goal()'s returned object and the stored current_plan "
        "are the exact same object (identity)",
    )
    check(
        agent.current_plan.label == "plan-1",
        "E2: current_plan holds exactly the object build_plan() produced",
    )


# ---------------------------------------------------------------------------
# E4 -- planning twice replaces the previous plan
# ---------------------------------------------------------------------------
def scenario_plan_goal_twice_replaces_previous_plan() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))

    first_plan = agent.plan_goal()
    second_plan = agent.plan_goal()

    check(
        first_plan is not second_plan,
        "E4: a second plan_goal() call produces a distinct plan object",
    )
    check(
        agent.current_plan is second_plan,
        "E4: current_plan reflects only the most recent plan -- no "
        "history of the previous one is kept",
    )


# ---------------------------------------------------------------------------
# E5 -- clear_plan() resets to None
# ---------------------------------------------------------------------------
def scenario_clear_plan_resets_to_none() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))
    agent.plan_goal()

    agent.clear_plan()

    check(agent.current_plan is None, "E5: clear_plan() resets current_plan back to None")


# ---------------------------------------------------------------------------
# E6 -- clear_plan() is idempotent
# ---------------------------------------------------------------------------
def scenario_clear_plan_twice_is_idempotent() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))
    agent.plan_goal()
    agent.clear_plan()

    raised = False
    try:
        agent.clear_plan()
    except Exception:  # noqa: BLE001
        raised = True
    check(not raised, "E6: calling clear_plan() twice does not raise")
    check(agent.current_plan is None, "E6: current_plan is still None after clearing twice")


# ---------------------------------------------------------------------------
# E7 -- rejected plan_goal() leaves current_plan unchanged
# ---------------------------------------------------------------------------
def scenario_rejected_plan_goal_leaves_current_plan_unchanged() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))
    first_plan = agent.plan_goal()

    agent.clear_goal()
    raised = False
    try:
        agent.plan_goal()
    except AutonomousAgentError:
        raised = True

    check(raised, "E7 precondition: plan_goal() with no goal set raises")
    check(
        agent.current_plan is first_plan,
        "E7: a rejected plan_goal() call (no goal set) leaves "
        "current_plan unchanged from its prior value",
    )


# ---------------------------------------------------------------------------
# E8/E9/E10/E11 -- goal/session/status/iteration_count untouched
# ---------------------------------------------------------------------------
def scenario_plan_mutation_leaves_other_state_untouched() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    goal = _FakeGoal("monitor-bbca")
    agent.set_goal(goal)
    session_id = agent.start_session()
    started_at = agent.session_started_at

    status_before = agent.status
    iteration_before = agent.iteration_count

    agent.plan_goal()
    check(agent.goal is goal, "E8: goal unchanged immediately after plan_goal()")
    check(
        agent.session_id == session_id and agent.session_started_at == started_at,
        "E9: session_id/session_started_at unchanged immediately after plan_goal()",
    )
    check(agent.status == status_before, "E10: status unchanged immediately after plan_goal()")
    check(
        agent.iteration_count == iteration_before,
        "E11: iteration_count unchanged immediately after plan_goal()",
    )

    agent.clear_plan()
    check(agent.goal is goal, "E8: goal unchanged immediately after clear_plan()")
    check(
        agent.session_id == session_id and agent.session_started_at == started_at,
        "E9: session_id/session_started_at unchanged immediately after clear_plan()",
    )
    check(agent.status == status_before, "E10: status unchanged immediately after clear_plan()")
    check(
        agent.iteration_count == iteration_before,
        "E11: iteration_count unchanged immediately after clear_plan()",
    )
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "E10: status remains the initial IDLE value throughout",
    )


# ---------------------------------------------------------------------------
# E12 -- pipeline never called
# ---------------------------------------------------------------------------
def scenario_plan_mutation_never_calls_pipeline() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))

    agent.plan_goal()
    agent.plan_goal()
    agent.clear_plan()
    agent.clear_plan()

    check(
        pipeline.calls == [],
        "E12: plan_goal()/clear_plan() never call the injected "
        "RuntimeAnalysisPipeline's run()",
    )


# ---------------------------------------------------------------------------
# E13 -- run() still works after plan mutation, unaffected by it
# ---------------------------------------------------------------------------
def scenario_run_still_works_after_plan_mutation() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))
    plan = agent.plan_goal()

    results = agent.run(_FakeContext("e13"), max_iterations=2)

    check(
        len(results) == 2 and all(r.success for r in results),
        "E13: run() still completes normally after plan_goal() was "
        "called earlier",
    )
    check(agent.current_plan is plan, "E13: run() does not modify current_plan")
    check(len(pipeline.calls) == 2, "E13: run() still delegates to the pipeline exactly twice")

    agent.clear_plan()
    check(agent.current_plan is None, "E13: clear_plan() after run() still clears the plan normally")


# ---------------------------------------------------------------------------
# E14 -- step() still works after plan mutation, unaffected by it
# ---------------------------------------------------------------------------
def scenario_step_still_works_after_plan_mutation() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    agent.set_goal(_FakeGoal("monitor-bbca"))
    plan = agent.plan_goal()

    result = agent.step(_FakeContext("e14"))

    check(result.success is True, "E14: step() still succeeds after plan_goal()")
    check(agent.current_plan is plan, "E14: step() does not modify current_plan")
    check(agent.iteration_count == 1, "E14: step() still increments iteration_count normally")

    agent.clear_plan()
    result2 = agent.step(_FakeContext("e14-b"))
    check(result2.success is True, "E14: step() still succeeds after clear_plan()")
    check(agent.current_plan is None, "E14: current_plan remains None after a further successful step()")
    check(len(pipeline.calls) == 2, "E14: both step() calls reached the injected pipeline")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_default_current_plan_is_none,
        scenario_plan_goal_stores_plan_with_identity,
        scenario_plan_goal_twice_replaces_previous_plan,
        scenario_clear_plan_resets_to_none,
        scenario_clear_plan_twice_is_idempotent,
        scenario_rejected_plan_goal_leaves_current_plan_unchanged,
        scenario_plan_mutation_leaves_other_state_untouched,
        scenario_plan_mutation_never_calls_pipeline,
        scenario_run_still_works_after_plan_mutation,
        scenario_step_still_works_after_plan_mutation,
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
    print(f"PHASE 2 SPRINT 8 EXECUTIONPLAN OWNERSHIP RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())