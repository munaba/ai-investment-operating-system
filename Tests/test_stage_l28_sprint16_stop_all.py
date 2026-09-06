"""
Phase 3 Sprint 16 proof suite -- AutonomousHost.stop_all (sequential
multi-agent shutdown).

Scope: dedicated regression suite for
``Orchestration.autonomous_host.AutonomousHost.stop_all`` only.
``AutonomousHost.start``/``start_all``/``stop`` are unmodified and
already covered by their own dedicated suites
(``Tests/test_stage_l28_sprint12_host.py``,
``Tests/test_stage_l28_sprint15_multi_host.py``); ``AutonomousAgent``
itself is unmodified and covered by
``Tests/test_stage_l28_autonomous_agent.py`` and its sibling Sprint
suites -- none of that is re-verified here beyond what ``stop_all()``
itself needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, constructor-
injected into real ``AutonomousAgent`` instances exactly like every
prior Sprint suite. A thin "spy" wrapper around a real
``AutonomousAgent`` is used in a few scenarios purely to count/observe
delegated calls (``stop``) without changing their behavior.

No threading, no asyncio, no timers, no sleep, no cron, no daemon, no
queue, no worker, no background execution, no scheduler, no retries,
no automatic restart, no health monitoring -- all explicitly out of
scope for Sprint 16 and never exercised or required by this suite.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Invariant coverage:
    N1  -- stop_all() with one agent behaves like a single stop().
    N2  -- stop_all() with multiple agents calls agent.stop() exactly
           once per agent, in order.
    N3  -- every agent's status becomes STOPPED.
    N4  -- empty iterable raises AutonomousHostError, no agent stopped.
    N5  -- None iterable raises AutonomousHostError.
    N6  -- an invalid (non-agent-shaped) entry raises
           AutonomousHostError, no agent stopped at all (all-or-nothing
           validation).
    N7  -- duplicate agents (the same instance listed twice) are both
           stopped -- no deduplication (second call is a no-op via
           AutonomousAgent.stop()'s own idempotence).
    N8  -- an exception raised by one agent's stop() propagates
           unchanged, and agents listed after the failing one are
           never stopped.
    N9  -- AutonomousHost remains stateless: no instance attributes
           are added/mutated by stop_all(), and it needs zero
           constructor arguments.
    N10 -- repeated stop_all() calls on the same host instance are
           independent (no leaked/cached state between calls).
    N11 -- stop_all() returns None.
    N12 -- stop_all() never calls RuntimeAnalysisPipeline or
           GoalPlanner directly.
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


class _FakeGoalPlanner:
    """Stand-in for Orchestration.planner.GoalPlanner. AutonomousHost
    must never reach this directly."""

    def __init__(self) -> None:
        self.build_plan_calls: List[object] = []


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call --
    used here to prove AutonomousHost never reaches it directly."""

    def __init__(self) -> None:
        self.calls: List[object] = []


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


class _StopSpyAgent:
    """Thin spy wrapping a real AutonomousAgent: forwards stop() to
    the real agent but records how many times it was called -- used
    only to assert delegation counts/order. Everything else (status)
    is forwarded transparently."""

    def __init__(self, real_agent: AutonomousAgent, label: str = "") -> None:
        self._real = real_agent
        self.label = label
        self.stop_calls = 0

    @property
    def status(self) -> AutonomousAgentStatus:
        return self._real.status

    def stop(self) -> None:
        self.stop_calls += 1
        self._real.stop()


class _FailingStopAgent:
    """Stand-in agent whose stop() always raises -- used to exercise
    the propagate-and-halt-batch behavior (N8)."""

    def __init__(self) -> None:
        self.status = AutonomousAgentStatus.RUNNING
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1
        raise AutonomousAgentError("simulated stop failure")


# ---------------------------------------------------------------------------
# N1 -- one agent behaves like a single stop()
# ---------------------------------------------------------------------------
def scenario_single_agent_matches_stop() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    host = AutonomousHost()

    result = host.stop_all([agent])

    check(result is None, "N1: stop_all() returns None")
    check(
        agent.status is AutonomousAgentStatus.STOPPED,
        "N1: the single agent's status is STOPPED",
    )


# ---------------------------------------------------------------------------
# N2/N3 -- multiple agents, stopped exactly once each, in order
# ---------------------------------------------------------------------------
def scenario_multiple_agents_stopped_once_in_order() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    a3, _, _ = _make_agent_and_collaborators()
    spy1, spy2, spy3 = (
        _StopSpyAgent(a1, "a1"),
        _StopSpyAgent(a2, "a2"),
        _StopSpyAgent(a3, "a3"),
    )
    host = AutonomousHost()

    host.stop_all([spy1, spy2, spy3])

    check(
        spy1.stop_calls == 1 and spy2.stop_calls == 1 and spy3.stop_calls == 1,
        "N2: each agent's stop() is called exactly once",
    )
    check(
        a1.status is AutonomousAgentStatus.STOPPED
        and a2.status is AutonomousAgentStatus.STOPPED
        and a3.status is AutonomousAgentStatus.STOPPED,
        "N3: every agent's status becomes STOPPED",
    )


# ---------------------------------------------------------------------------
# N4 -- empty iterable raises AutonomousHostError, no agent stopped
# ---------------------------------------------------------------------------
def scenario_empty_iterable_rejected() -> None:
    host = AutonomousHost()

    raised = False
    try:
        host.stop_all([])
    except AutonomousHostError:
        raised = True

    check(raised, "N4: stop_all([]) raises AutonomousHostError")


# ---------------------------------------------------------------------------
# N5 -- None iterable raises AutonomousHostError
# ---------------------------------------------------------------------------
def scenario_none_iterable_rejected() -> None:
    host = AutonomousHost()

    raised = False
    try:
        host.stop_all(None)
    except AutonomousHostError:
        raised = True

    check(raised, "N5: stop_all(None) raises AutonomousHostError")


# ---------------------------------------------------------------------------
# N6 -- invalid (non-agent-shaped) entry rejected, all-or-nothing
# ---------------------------------------------------------------------------
def scenario_invalid_entry_rejected() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    spy1 = _StopSpyAgent(a1, "a1")
    host = AutonomousHost()

    for bad_entry in (None, "not-an-agent", 42, object()):
        spy1.stop_calls = 0
        raised = False
        try:
            host.stop_all([spy1, bad_entry])
        except AutonomousHostError:
            raised = True

        check(
            raised,
            f"N6: an invalid entry ({bad_entry!r}) in 'agents' raises "
            "AutonomousHostError",
        )
        check(
            spy1.stop_calls == 0,
            f"N6: with invalid entry {bad_entry!r} present, no agent "
            "(including valid ones before it) was stopped -- "
            "all-or-nothing validation",
        )


# ---------------------------------------------------------------------------
# N7 -- duplicate agents (same instance twice) both stopped
# ---------------------------------------------------------------------------
def scenario_duplicate_agents_both_stopped() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    spy1 = _StopSpyAgent(a1, "dup")
    host = AutonomousHost()

    host.stop_all([spy1, spy1])

    check(
        spy1.stop_calls == 2,
        "N7: the same agent instance's stop() was called twice",
    )
    check(
        a1.status is AutonomousAgentStatus.STOPPED,
        "N7: the agent ends up STOPPED (second call is a no-op)",
    )


# ---------------------------------------------------------------------------
# N8 -- a failing agent stops the batch; later agents never stopped
# ---------------------------------------------------------------------------
def scenario_failing_agent_stops_batch() -> None:
    good_agent, _, _ = _make_agent_and_collaborators()
    good_spy = _StopSpyAgent(good_agent, "good")

    failing_agent = _FailingStopAgent()

    never_agent, _, _ = _make_agent_and_collaborators()
    never_spy = _StopSpyAgent(never_agent, "never")

    host = AutonomousHost()

    raised = False
    try:
        host.stop_all([good_spy, failing_agent, never_spy])
    except AutonomousAgentError:
        raised = True

    check(
        raised,
        "N8: the underlying AutonomousAgentError from a failing agent's "
        "stop() propagates unchanged",
    )
    check(good_spy.stop_calls == 1, "N8: the good agent before it was stopped")
    check(
        failing_agent.stop_calls == 1,
        "N8: the failing agent was attempted exactly once (no retry)",
    )
    check(
        never_spy.stop_calls == 0,
        "N8: the agent listed after the failing one was never stopped",
    )


# ---------------------------------------------------------------------------
# N9 -- AutonomousHost remains stateless
# ---------------------------------------------------------------------------
def scenario_host_remains_stateless() -> None:
    host = AutonomousHost()
    a1, _, _ = _make_agent_and_collaborators()

    before = dict(host.__dict__)
    host.stop_all([a1])
    after = dict(host.__dict__)

    check(
        before == after == {},
        "N9: stop_all() adds/mutates no instance attributes on the host",
    )


# ---------------------------------------------------------------------------
# N10 -- repeated stop_all() calls are independent
# ---------------------------------------------------------------------------
def scenario_repeated_calls_independent() -> None:
    host = AutonomousHost()

    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    a3, _, _ = _make_agent_and_collaborators()

    spy1 = _StopSpyAgent(a1, "first")
    spy2 = _StopSpyAgent(a2, "second-a")
    spy3 = _StopSpyAgent(a3, "second-b")

    host.stop_all([spy1])
    host.stop_all([spy2, spy3])

    check(
        spy1.stop_calls == 1 and spy2.stop_calls == 1 and spy3.stop_calls == 1,
        "N10: each call stopped exactly its own agents, independently "
        "of the other call",
    )


# ---------------------------------------------------------------------------
# N11 -- stop_all() returns None
# ---------------------------------------------------------------------------
def scenario_returns_none() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host = AutonomousHost()

    result = host.stop_all([a1, a2])

    check(result is None, "N11: stop_all() with multiple agents returns None")


# ---------------------------------------------------------------------------
# N12 -- stop_all() never calls RuntimeAnalysisPipeline/GoalPlanner directly
# ---------------------------------------------------------------------------
def scenario_never_calls_pipeline_or_goal_planner_directly() -> None:
    pipeline1 = _FakeRuntimeAnalysisPipeline()
    gp1 = _FakeGoalPlanner()
    a1 = _make_agent(pipeline1, gp1)
    pipeline2 = _FakeRuntimeAnalysisPipeline()
    gp2 = _FakeGoalPlanner()
    a2 = _make_agent(pipeline2, gp2)
    host = AutonomousHost()

    host.stop_all([a1, a2])

    check(
        pipeline1.calls == [] and pipeline2.calls == [],
        "N12: stop_all() never triggers RuntimeAnalysisPipeline.run()",
    )
    check(
        gp1.build_plan_calls == [] and gp2.build_plan_calls == [],
        "N12: stop_all() never triggers GoalPlanner.build_plan()",
    )
    check(
        not hasattr(host, "_runtime_analysis_pipeline")
        and not hasattr(host, "runtime_analysis_pipeline")
        and not hasattr(host, "_goal_planner")
        and not hasattr(host, "goal_planner"),
        "N12: AutonomousHost holds no direct pipeline/goal-planner reference",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_single_agent_matches_stop,
        scenario_multiple_agents_stopped_once_in_order,
        scenario_empty_iterable_rejected,
        scenario_none_iterable_rejected,
        scenario_invalid_entry_rejected,
        scenario_duplicate_agents_both_stopped,
        scenario_failing_agent_stops_batch,
        scenario_host_remains_stateless,
        scenario_repeated_calls_independent,
        scenario_returns_none,
        scenario_never_calls_pipeline_or_goal_planner_directly,
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
    print(f"PHASE 3 SPRINT 16 STOP-ALL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())