"""
Phase 2 Sprint 5 proof suite -- AutonomousAgent goal ownership
(set_goal()/clear_goal()).

Scope: dedicated regression suite for
``Orchestration.autonomous_agent.AutonomousAgent.set_goal`` and
``AutonomousAgent.clear_goal`` only. Constructor/validation/
lifecycle-state-shape behavior for the ten L18-L27 dependencies plus
the Sprint 3 constructor-injected ``runtime_analysis_pipeline`` is
already covered by ``Tests/test_stage_l28_autonomous_agent.py``,
``step()``'s own dedicated behavior by
``Tests/test_stage_l28_sprint2_step.py``, and ``run()``'s own
dedicated behavior by ``Tests/test_stage_l28_sprint4_run.py`` --
none of that is re-verified here beyond what goal ownership itself
needs. No real ``RuntimeAnalysisPipeline`` is built -- a plain fake
object exposing ``run(context)`` stands in for it, constructor-
injected exactly like the ten L18-L27 dependencies. No planning, no
automatic goal generation, no GoalPlanner integration of any kind --
all explicitly out of scope for Sprint 5.

Follows the same scenario-based, no-pytest, no-external-mocks style
as the other Stage L1x-L2x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    G1  -- goal is None by default on a freshly constructed agent.
    G2  -- set_goal("Monitor BBCA") makes the goal property return
           exactly "Monitor BBCA".
    G3  -- calling set_goal() again with a different value replaces
           the previous goal (no accumulation, no history kept).
    G4  -- clear_goal() resets goal back to None.
    G5  -- calling clear_goal() twice in a row is not an error and
           leaves goal as None both times (idempotent).
    G6  -- set_goal(None) raises AutonomousAgentError and leaves the
           previously-set goal unchanged.
    G7  -- clear_goal() on a freshly constructed agent (goal already
           None) is not an error.
    G8  -- set_goal()/clear_goal() never change status.
    G9  -- set_goal()/clear_goal() never change iteration_count.
    G10 -- set_goal()/clear_goal() never change last_cycle_at.
    G11 -- set_goal()/clear_goal() never call the injected
           RuntimeAnalysisPipeline's run().
    G12 -- run() still works normally after set_goal()/clear_goal()
           have been called, and the goal value is unaffected by
           run() itself.
    G13 -- step() still works normally after set_goal()/clear_goal()
           have been called, and the goal value is unaffected by
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
    Neither step(), run(), set_goal(), nor clear_goal() ever touches
    these."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeContext:
    """Stand-in for a ServiceContext. Treated as opaque and passed
    through unchanged."""

    def __init__(self, tag: str = "ctx") -> None:
        self.tag = tag


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call --
    never itself runs AnalysisPipeline or any real stage. Used here
    only to prove set_goal()/clear_goal() never reach it, and that
    run()/step() still work unchanged after goal mutation."""

    def __init__(self) -> None:
        self.calls: List[object] = []

    def run(self, context: object) -> str:
        self.calls.append(context)
        return "ok"


def _make_agent(pipeline: _FakeRuntimeAnalysisPipeline) -> AutonomousAgent:
    return AutonomousAgent(
        runtime_analysis_pipeline=pipeline,
        # Phase 2, Sprint 7: goal_planner is now a required 12th
        # constructor argument. set_goal()/clear_goal() never touch
        # it -- see Tests/test_stage_l28_sprint7_goalplanner.py.
        goal_planner=_FakeComponent("goal_planner"),
        **{name: _FakeComponent(name) for name in _FIELD_NAMES},
    )


def _make_agent_and_pipeline():
    pipeline = _FakeRuntimeAnalysisPipeline()
    agent = _make_agent(pipeline)
    return agent, pipeline


# ---------------------------------------------------------------------------
# G1 -- default goal is None
# ---------------------------------------------------------------------------
def scenario_default_goal_is_none() -> None:
    agent, _ = _make_agent_and_pipeline()
    check(agent.goal is None, "G1: goal is None on a freshly constructed agent")


# ---------------------------------------------------------------------------
# G2 -- set_goal() stores the value
# ---------------------------------------------------------------------------
def scenario_set_goal_stores_value() -> None:
    agent, _ = _make_agent_and_pipeline()
    agent.set_goal("Monitor BBCA")
    check(
        agent.goal == "Monitor BBCA",
        "G2: set_goal('Monitor BBCA') makes goal return 'Monitor BBCA'",
    )


# ---------------------------------------------------------------------------
# G3 -- set_goal() replaces the previous goal
# ---------------------------------------------------------------------------
def scenario_set_goal_replaces_previous_goal() -> None:
    agent, _ = _make_agent_and_pipeline()
    agent.set_goal("Monitor BBCA")
    agent.set_goal("Monitor TLKM")
    check(
        agent.goal == "Monitor TLKM",
        "G3: a second set_goal() call replaces the previous goal "
        "entirely (no accumulation)",
    )


# ---------------------------------------------------------------------------
# G4 -- clear_goal() resets to None
# ---------------------------------------------------------------------------
def scenario_clear_goal_resets_to_none() -> None:
    agent, _ = _make_agent_and_pipeline()
    agent.set_goal("Monitor BBCA")
    agent.clear_goal()
    check(agent.goal is None, "G4: clear_goal() resets goal back to None")


# ---------------------------------------------------------------------------
# G5 -- clear_goal() is idempotent
# ---------------------------------------------------------------------------
def scenario_clear_goal_twice_is_idempotent() -> None:
    agent, _ = _make_agent_and_pipeline()
    agent.set_goal("Monitor BBCA")
    agent.clear_goal()
    raised = False
    try:
        agent.clear_goal()
    except Exception:  # noqa: BLE001
        raised = True
    check(not raised, "G5: calling clear_goal() twice does not raise")
    check(agent.goal is None, "G5: goal is still None after clearing twice")


# ---------------------------------------------------------------------------
# G6 -- set_goal(None) raises and leaves goal unchanged
# ---------------------------------------------------------------------------
def scenario_set_goal_none_raises() -> None:
    agent, _ = _make_agent_and_pipeline()
    agent.set_goal("Monitor BBCA")

    raised = False
    try:
        agent.set_goal(None)
    except AutonomousAgentError:
        raised = True
    except Exception:  # noqa: BLE001
        raised = False

    check(raised, "G6: set_goal(None) raises AutonomousAgentError")
    check(
        agent.goal == "Monitor BBCA",
        "G6: the previously-set goal is unchanged after a rejected "
        "set_goal(None) call",
    )


# ---------------------------------------------------------------------------
# G7 -- clear_goal() on a fresh agent is not an error
# ---------------------------------------------------------------------------
def scenario_clear_goal_on_fresh_agent() -> None:
    agent, _ = _make_agent_and_pipeline()
    raised = False
    try:
        agent.clear_goal()
    except Exception:  # noqa: BLE001
        raised = True
    check(
        not raised,
        "G7: clear_goal() on a freshly constructed agent (goal "
        "already None) does not raise",
    )
    check(agent.goal is None, "G7: goal remains None")


# ---------------------------------------------------------------------------
# G8/G9/G10 -- status/iteration_count/last_cycle_at untouched
# ---------------------------------------------------------------------------
def scenario_goal_mutation_leaves_other_state_untouched() -> None:
    agent, _ = _make_agent_and_pipeline()

    status_before = agent.status
    iteration_before = agent.iteration_count
    last_cycle_before = agent.last_cycle_at

    agent.set_goal("Monitor BBCA")
    check(
        agent.status == status_before,
        "G8: status is unchanged immediately after set_goal()",
    )
    check(
        agent.iteration_count == iteration_before,
        "G9: iteration_count is unchanged immediately after set_goal()",
    )
    check(
        agent.last_cycle_at == last_cycle_before,
        "G10: last_cycle_at is unchanged immediately after set_goal()",
    )

    agent.clear_goal()
    check(
        agent.status == status_before,
        "G8: status is unchanged immediately after clear_goal()",
    )
    check(
        agent.iteration_count == iteration_before,
        "G9: iteration_count is unchanged immediately after clear_goal()",
    )
    check(
        agent.last_cycle_at == last_cycle_before,
        "G10: last_cycle_at is unchanged immediately after clear_goal()",
    )
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "G8: status remains the initial IDLE value throughout",
    )


# ---------------------------------------------------------------------------
# G11 -- pipeline is never called by set_goal()/clear_goal()
# ---------------------------------------------------------------------------
def scenario_goal_mutation_never_calls_pipeline() -> None:
    agent, pipeline = _make_agent_and_pipeline()

    agent.set_goal("Monitor BBCA")
    agent.set_goal("Monitor TLKM")
    agent.clear_goal()
    agent.clear_goal()
    try:
        agent.set_goal(None)
    except AutonomousAgentError:
        pass

    check(
        pipeline.calls == [],
        "G11: set_goal()/clear_goal() never call the injected "
        "RuntimeAnalysisPipeline's run()",
    )


# ---------------------------------------------------------------------------
# G12 -- run() still works after goal mutation, and is unaffected by it
# ---------------------------------------------------------------------------
def scenario_run_still_works_after_goal_mutation() -> None:
    agent, pipeline = _make_agent_and_pipeline()

    agent.set_goal("Monitor BBCA")
    results = agent.run(_FakeContext("g12"), max_iterations=2)

    check(
        len(results) == 2 and all(r.success for r in results),
        "G12: run() still completes normally after set_goal() was "
        "called earlier",
    )
    check(
        agent.goal == "Monitor BBCA",
        "G12: run() does not modify the goal value",
    )
    check(
        len(pipeline.calls) == 2,
        "G12: run() still delegates to the injected pipeline exactly "
        "as before",
    )

    agent.clear_goal()
    check(
        agent.goal is None,
        "G12: clear_goal() after run() still clears the goal normally",
    )


# ---------------------------------------------------------------------------
# G13 -- step() still works after goal mutation, and is unaffected by it
# ---------------------------------------------------------------------------
def scenario_step_still_works_after_goal_mutation() -> None:
    agent, pipeline = _make_agent_and_pipeline()

    agent.set_goal("Monitor BBCA")
    result = agent.step(_FakeContext("g13"))

    check(result.success is True, "G13: step() still succeeds after set_goal()")
    check(
        agent.goal == "Monitor BBCA",
        "G13: step() does not modify the goal value",
    )
    check(
        agent.iteration_count == 1,
        "G13: step() still increments iteration_count normally",
    )

    agent.clear_goal()
    result2 = agent.step(_FakeContext("g13-b"))
    check(
        result2.success is True,
        "G13: step() still succeeds after clear_goal()",
    )
    check(
        agent.goal is None,
        "G13: goal remains None after a further successful step()",
    )
    check(
        len(pipeline.calls) == 2,
        "G13: both step() calls reached the injected pipeline",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_default_goal_is_none,
        scenario_set_goal_stores_value,
        scenario_set_goal_replaces_previous_goal,
        scenario_clear_goal_resets_to_none,
        scenario_clear_goal_twice_is_idempotent,
        scenario_set_goal_none_raises,
        scenario_clear_goal_on_fresh_agent,
        scenario_goal_mutation_leaves_other_state_untouched,
        scenario_goal_mutation_never_calls_pipeline,
        scenario_run_still_works_after_goal_mutation,
        scenario_step_still_works_after_goal_mutation,
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
    print(f"PHASE 2 SPRINT 5 GOAL OWNERSHIP RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())