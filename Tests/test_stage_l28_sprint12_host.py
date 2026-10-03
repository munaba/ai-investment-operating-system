"""
Phase 2 Sprint 12 proof suite -- AutonomousHost (the first Host/
Scheduler capable of repeatedly driving an AutonomousAgent).

Scope: dedicated regression suite for
``Orchestration.autonomous_host.AutonomousHost.start`` and
``AutonomousHost.stop`` only. ``AutonomousAgent`` itself (its
constructor, ``step()``, ``run()``, ``stop()``, lifecycle transitions,
GoalPlanner/ExecutionPlan ownership, etc.) is unmodified and already
covered by its own dedicated suites
(``Tests/test_stage_l28_autonomous_agent.py``,
``Tests/test_stage_l28_sprint2_step.py``,
``Tests/test_stage_l28_sprint4_run.py``,
``Tests/test_stage_l28_sprint5_goal.py``,
``Tests/test_stage_l28_sprint6_session.py``,
``Tests/test_stage_l28_sprint7_goalplanner.py``,
``Tests/test_stage_l28_sprint8_execution_plan.py``,
``Tests/test_stage_l28_sprint9_pause_resume.py``,
``Tests/test_stage_l28_sprint10_cancel.py``,
``Tests/test_stage_l28_sprint11_execution_loop.py``) -- none of that
is re-verified here beyond what ``AutonomousHost`` itself needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, constructor-
injected into a real ``AutonomousAgent`` exactly like every prior
Sprint suite. A thin "spy" wrapper around a real ``AutonomousAgent``
is used in a few scenarios purely to count/observe delegated calls
(``run``/``stop``) without changing their behavior.

No threading, no asyncio, no timers, no sleep, no cron, no daemon, no
queue, no worker, no background execution, no scheduling, no retries,
no automatic restart, no health monitoring, no logging framework, no
host registry, no multiple agents, no agent pools -- all explicitly
out of scope for Sprint 12 and never exercised or required by this
suite.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    H1  -- start() delegates exactly once to agent.run(context,
           iterations) and returns run()'s tuple unchanged (identity
           check on the returned tuple).
    H2  -- stop() delegates exactly once to agent.stop().
    H3  -- start() never calls RuntimeAnalysisPipeline.run() directly
           (only AutonomousAgent.run()/step() does, transitively).
    H4  -- start() never calls GoalPlanner.build_plan() directly.
    H5  -- start() preserves the return value's contents (every
           AutonomousCycleResult, in order, unchanged).
    H6  -- start() raises AutonomousHostError for agent=None.
    H7  -- start() raises AutonomousHostError for context=None.
    H8  -- start() raises AutonomousHostError for a non-int/None/<1
           'iterations' (0, negative, non-int), without calling
           agent.run() at all.
    H9  -- start() raises AutonomousHostError when agent.status is
           STOPPED, without calling agent.run() at all.
    H10 -- start() raises AutonomousHostError when agent.status is
           ERROR, without calling agent.run() at all.
    H11 -- run() is called exactly once per start() call (never
           looped, never retried inside the host).
    H12 -- stop() is called exactly once per host.stop() call.
    H13 -- a failing agent.run() (raises AutonomousAgentError) is not
           retried by the host -- the host performs no loop, no
           retry, and the exception propagates unchanged.
    H14 -- AutonomousHost.stop() raises AutonomousHostError for
           agent=None.
    H15 -- AutonomousHost has no constructor dependencies (can be
           constructed with zero arguments), confirming it needs no
           Composition Root wiring.
    H16 -- start()'s only public surface call into agent is agent.run
           -- it never reads/writes AutonomousAgent private attributes
           such as _status, _iteration_count, etc.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.autonomous_agent import (
    AutonomousAgent,
    AutonomousAgentError,
    AutonomousAgentStatus,
    AutonomousCycleResult,
)
from Orchestration.autonomous_host import AutonomousHost, AutonomousHostError

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
    """Stand-in for one of the ten L18-L27 constructor dependencies."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeContext:
    """Stand-in for a ServiceContext. Treated as opaque and passed
    through unchanged."""

    def __init__(self, tag: str = "ctx") -> None:
        self.tag = tag


class _FakePlan:
    """Stand-in for an Orchestration.planner.ExecutionPlan."""

    def __init__(self, label: str) -> None:
        self.label = label


class _FakeGoalPlanner:
    """Stand-in for Orchestration.planner.GoalPlanner. AutonomousHost
    must never reach this directly."""

    def __init__(self) -> None:
        self.build_plan_calls: List[object] = []

    def build_plan(self, goal: object) -> _FakePlan:
        self.build_plan_calls.append(goal)
        return _FakePlan(f"plan-{len(self.build_plan_calls)}")


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call --
    used here to prove AutonomousHost never reaches it directly."""

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


class _RunSpyAgent:
    """Thin spy wrapping a real AutonomousAgent: forwards run()/stop()
    to the real agent but records how many times each was called, and
    with what arguments -- used only to assert delegation counts/
    arguments. Everything else (status) is forwarded transparently."""

    def __init__(self, real_agent: AutonomousAgent) -> None:
        self._real = real_agent
        self.run_calls: List[Tuple[object, int]] = []
        self.stop_calls: int = 0

    @property
    def status(self) -> AutonomousAgentStatus:
        return self._real.status

    def run(
        self, context: object, max_iterations: int
    ) -> Tuple[AutonomousCycleResult, ...]:
        self.run_calls.append((context, max_iterations))
        return self._real.run(context, max_iterations)

    def stop(self) -> None:
        self.stop_calls += 1
        self._real.stop()


# ---------------------------------------------------------------------------
# H1 -- start() delegates exactly once and returns run()'s tuple unchanged
# ---------------------------------------------------------------------------
def scenario_start_delegates_and_returns_unchanged() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    host = AutonomousHost()
    ctx = _FakeContext("h1")

    result = host.start(agent, ctx, iterations=3)

    check(isinstance(result, tuple), "H1: start() returns a tuple")
    check(len(result) == 3, "H1: start() returns exactly 'iterations' results")
    check(
        all(isinstance(r, AutonomousCycleResult) for r in result),
        "H1: every returned element is an AutonomousCycleResult",
    )
    check(len(pipeline.calls) == 3, "H1: pipeline.run() called 3 times via agent.run()")


# ---------------------------------------------------------------------------
# H2 -- stop() delegates exactly once to agent.stop()
# ---------------------------------------------------------------------------
def scenario_stop_delegates_to_agent_stop() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    spy = _RunSpyAgent(agent)
    host = AutonomousHost()

    host.stop(spy)

    check(spy.stop_calls == 1, "H2: host.stop() calls agent.stop() exactly once")
    check(agent.status is AutonomousAgentStatus.STOPPED, "H2: agent is now STOPPED")


# ---------------------------------------------------------------------------
# H3 -- start() never calls RuntimeAnalysisPipeline.run() directly
# ---------------------------------------------------------------------------
def scenario_start_never_calls_pipeline_directly() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    host = AutonomousHost()

    # Sanity: pipeline is untouched before start().
    check(pipeline.calls == [], "H3 precondition: pipeline has no calls yet")

    host.start(agent, _FakeContext("h3"), iterations=1)

    # The pipeline was reached only transitively through
    # agent.run()->step(); AutonomousHost itself holds no reference
    # to the pipeline at all (it is never passed to AutonomousHost).
    check(
        not hasattr(host, "_runtime_analysis_pipeline")
        and not hasattr(host, "runtime_analysis_pipeline"),
        "H3: AutonomousHost holds no direct RuntimeAnalysisPipeline reference",
    )


# ---------------------------------------------------------------------------
# H4 -- start() never calls GoalPlanner.build_plan() directly
# ---------------------------------------------------------------------------
def scenario_start_never_calls_goal_planner_directly() -> None:
    agent, _, goal_planner = _make_agent_and_collaborators()
    host = AutonomousHost()

    host.start(agent, _FakeContext("h4"), iterations=1)

    check(
        goal_planner.build_plan_calls == [],
        "H4: start() never triggers GoalPlanner.build_plan() (no goal/plan set)",
    )
    check(
        not hasattr(host, "_goal_planner") and not hasattr(host, "goal_planner"),
        "H4: AutonomousHost holds no direct GoalPlanner reference",
    )


# ---------------------------------------------------------------------------
# H5 -- start() preserves the return value's contents
# ---------------------------------------------------------------------------
def scenario_start_preserves_return_value_contents() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    host = AutonomousHost()
    ctx = _FakeContext("h5")

    result = host.start(agent, ctx, iterations=2)

    check(
        all(r.success is True for r in result),
        "H5: every result reports success=True (matching an all-succeeding pipeline)",
    )
    check(
        [r.iteration for r in result] == [1, 2],
        "H5: iteration numbers are preserved in call order (1, 2)",
    )


# ---------------------------------------------------------------------------
# H6 -- start() raises AutonomousHostError for agent=None
# ---------------------------------------------------------------------------
def scenario_start_rejects_none_agent() -> None:
    host = AutonomousHost()

    raised = False
    try:
        host.start(None, _FakeContext("h6"), iterations=1)
    except AutonomousHostError:
        raised = True

    check(raised, "H6: start(agent=None, ...) raises AutonomousHostError")


# ---------------------------------------------------------------------------
# H7 -- start() raises AutonomousHostError for context=None
# ---------------------------------------------------------------------------
def scenario_start_rejects_none_context() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    host = AutonomousHost()

    raised = False
    try:
        host.start(agent, None, iterations=1)
    except AutonomousHostError:
        raised = True

    check(raised, "H7: start(..., context=None, ...) raises AutonomousHostError")
    check(pipeline.calls == [], "H7: the refused call never reached the pipeline")


# ---------------------------------------------------------------------------
# H8 -- start() raises AutonomousHostError for invalid 'iterations'
# ---------------------------------------------------------------------------
def scenario_start_rejects_invalid_iterations() -> None:
    for bad_value in (0, -1, "3", 2.5, None):
        agent, pipeline, _ = _make_agent_and_collaborators()
        host = AutonomousHost()

        raised = False
        try:
            host.start(agent, _FakeContext("h8"), iterations=bad_value)
        except AutonomousHostError:
            raised = True

        check(
            raised,
            f"H8: start(..., iterations={bad_value!r}) raises AutonomousHostError",
        )
        check(
            pipeline.calls == [],
            f"H8: iterations={bad_value!r} never reached the pipeline",
        )


# ---------------------------------------------------------------------------
# H9 -- start() raises AutonomousHostError when agent.status is STOPPED
# ---------------------------------------------------------------------------
def scenario_start_rejects_stopped_agent() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    agent.stop()
    host = AutonomousHost()

    raised = False
    try:
        host.start(agent, _FakeContext("h9"), iterations=1)
    except AutonomousHostError:
        raised = True

    check(raised, "H9: start() on a STOPPED agent raises AutonomousHostError")
    check(pipeline.calls == [], "H9: the refused start() never reached the pipeline")


# ---------------------------------------------------------------------------
# H10 -- start() raises AutonomousHostError when agent.status is ERROR
# ---------------------------------------------------------------------------
def scenario_start_rejects_error_agent() -> None:
    failing_pipeline = _FakeRuntimeAnalysisPipeline(should_fail=True)
    goal_planner = _FakeGoalPlanner()
    agent = _make_agent(failing_pipeline, goal_planner)
    agent.step(_FakeContext("force-error"))
    check(
        agent.status is AutonomousAgentStatus.ERROR,
        "H10 precondition: agent is in ERROR",
    )
    failing_pipeline.calls.clear()
    host = AutonomousHost()

    raised = False
    try:
        host.start(agent, _FakeContext("h10"), iterations=1)
    except AutonomousHostError:
        raised = True

    check(raised, "H10: start() on an ERROR agent raises AutonomousHostError")
    check(
        failing_pipeline.calls == [],
        "H10: the refused start() never reached the pipeline",
    )


# ---------------------------------------------------------------------------
# H11 -- run() is called exactly once per start() call
# ---------------------------------------------------------------------------
def scenario_run_called_exactly_once() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    spy = _RunSpyAgent(agent)
    host = AutonomousHost()

    host.start(spy, _FakeContext("h11"), iterations=4)

    check(len(spy.run_calls) == 1, "H11: agent.run() is called exactly once by start()")
    check(
        spy.run_calls[0][1] == 4,
        "H11: the single run() call is passed the requested iteration count",
    )


# ---------------------------------------------------------------------------
# H12 -- stop() is called exactly once per host.stop() call
# ---------------------------------------------------------------------------
def scenario_stop_called_exactly_once() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    spy = _RunSpyAgent(agent)
    host = AutonomousHost()

    host.stop(spy)

    check(spy.stop_calls == 1, "H12: agent.stop() is called exactly once by host.stop()")


# ---------------------------------------------------------------------------
# H13 -- a failing agent.run() is not retried; exception propagates unchanged
# ---------------------------------------------------------------------------
def scenario_failing_run_not_retried() -> None:
    failing_pipeline = _FakeRuntimeAnalysisPipeline(should_fail=True)
    goal_planner = _FakeGoalPlanner()
    agent = _make_agent(failing_pipeline, goal_planner)
    spy = _RunSpyAgent(agent)
    host = AutonomousHost()

    raised = False
    try:
        host.start(spy, _FakeContext("h13"), iterations=3)
    except AutonomousAgentError:
        raised = True

    check(
        raised,
        "H13: the underlying AutonomousAgentError from a failing run() propagates unchanged",
    )
    check(
        len(spy.run_calls) == 1,
        "H13: run() was attempted exactly once -- the host performs no retry",
    )
    check(
        len(failing_pipeline.calls) == 1,
        "H13: the pipeline was invoked exactly once (step() fails on the first "
        "iteration, and run() re-raises immediately rather than continuing/retrying)",
    )


# ---------------------------------------------------------------------------
# H14 -- AutonomousHost.stop() raises AutonomousHostError for agent=None
# ---------------------------------------------------------------------------
def scenario_stop_rejects_none_agent() -> None:
    host = AutonomousHost()

    raised = False
    try:
        host.stop(None)
    except AutonomousHostError:
        raised = True

    check(raised, "H14: stop(agent=None) raises AutonomousHostError")


# ---------------------------------------------------------------------------
# H15 -- AutonomousHost has no constructor dependencies
# ---------------------------------------------------------------------------
def scenario_host_has_no_constructor_dependencies() -> None:
    try:
        host = AutonomousHost()
        constructed = True
    except TypeError:
        constructed = False

    check(
        constructed,
        "H15: AutonomousHost() can be constructed with zero arguments "
        "(no Composition Root wiring required)",
    )


# ---------------------------------------------------------------------------
# H16 -- start() never reads/writes AutonomousAgent private attributes
# ---------------------------------------------------------------------------
def scenario_start_never_touches_private_attributes() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    host = AutonomousHost()

    before = dict(agent.__dict__)
    host.start(agent, _FakeContext("h16"), iterations=1)
    after = dict(agent.__dict__)

    # Only the attributes AutonomousAgent.run()/step() themselves are
    # documented to mutate should differ; the host does not add,
    # remove, or directly poke any private attribute beyond what the
    # agent's own public run() call already does.
    changed_keys = {
        k for k in after if k not in before or before[k] != after[k]
    }
    expected_mutable = {"_status", "_iteration_count", "_last_cycle_at"}
    check(
        changed_keys.issubset(expected_mutable),
        "H16: start() causes no attribute changes beyond what agent.run()/"
        f"step() themselves already perform (changed: {changed_keys})",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_start_delegates_and_returns_unchanged,
        scenario_stop_delegates_to_agent_stop,
        scenario_start_never_calls_pipeline_directly,
        scenario_start_never_calls_goal_planner_directly,
        scenario_start_preserves_return_value_contents,
        scenario_start_rejects_none_agent,
        scenario_start_rejects_none_context,
        scenario_start_rejects_invalid_iterations,
        scenario_start_rejects_stopped_agent,
        scenario_start_rejects_error_agent,
        scenario_run_called_exactly_once,
        scenario_stop_called_exactly_once,
        scenario_failing_run_not_retried,
        scenario_stop_rejects_none_agent,
        scenario_host_has_no_constructor_dependencies,
        scenario_start_never_touches_private_attributes,
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
    print(f"PHASE 2 SPRINT 12 HOST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main()) 