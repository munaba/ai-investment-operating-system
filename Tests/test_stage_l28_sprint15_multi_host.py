"""
Phase 3 Sprint 15 proof suite -- AutonomousHost.start_all (sequential
multi-agent orchestration).

Scope: dedicated regression suite for
``Orchestration.autonomous_host.AutonomousHost.start_all`` only.
``AutonomousHost.start``/``stop`` are unmodified and already covered by
their own dedicated suite (``Tests/test_stage_l28_sprint12_host.py``);
``AutonomousAgent`` itself is unmodified and covered by
``Tests/test_stage_l28_autonomous_agent.py`` and its sibling Sprint
suites -- none of that is re-verified here beyond what ``start_all()``
itself needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, constructor-
injected into real ``AutonomousAgent`` instances exactly like every
prior Sprint suite. A thin "spy" wrapper around a real
``AutonomousAgent`` is used in a few scenarios purely to count/observe
delegated calls (``run``) without changing their behavior.

No threading, no asyncio, no timers, no sleep, no cron, no daemon, no
queue, no worker, no background execution, no scheduler, no retries,
no automatic restart, no health monitoring, no priority/load-balancing/
round-robin, no agent spawning/destruction -- all explicitly out of
scope for Sprint 15 and never exercised or required by this suite.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Invariant coverage:
    M1  -- start_all() with one agent behaves like a single start().
    M2  -- start_all() with multiple agents calls agent.run() exactly
           once per agent, in order.
    M3  -- order is preserved (results correspond to agents in the
           order given, not sorted/reordered).
    M4  -- each agent's returned tuple is preserved unchanged inside
           the outer results tuple (identity/content check).
    M5  -- empty iterable raises AutonomousHostError, no agent run.
    M6  -- None iterable raises AutonomousHostError.
    M7  -- an invalid (non-agent-shaped) entry raises
           AutonomousHostError, no agent run at all (all-or-nothing
           validation).
    M8  -- invalid iterations (0, negative, non-int, None) raises
           AutonomousHostError, no agent run at all.
    M9  -- start_all() never calls RuntimeAnalysisPipeline directly.
    M10 -- start_all() never calls GoalPlanner directly.
    M11 -- duplicate agents (the same instance listed twice) are both
           executed -- no deduplication.
    M12 -- an exception raised by one agent's run() propagates
           unchanged, and agents listed after the failing one are
           never run.
    M13 -- AutonomousHost remains stateless: no instance attributes
           are added/mutated by start_all(), and it needs zero
           constructor arguments.
    M14 -- repeated start_all() calls on the same host instance are
           independent (no leaked/cached state between calls).
    M15 -- context=None raises AutonomousHostError, no agent run.
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
    """Thin spy wrapping a real AutonomousAgent: forwards run() to the
    real agent but records how many times it was called and with what
    arguments -- used only to assert delegation counts/order/args.
    Everything else (status) is forwarded transparently."""

    def __init__(self, real_agent: AutonomousAgent, label: str = "") -> None:
        self._real = real_agent
        self.label = label
        self.run_calls: List[Tuple[object, int]] = []

    @property
    def status(self) -> AutonomousAgentStatus:
        return self._real.status

    def run(
        self, context: object, max_iterations: int
    ) -> Tuple[AutonomousCycleResult, ...]:
        self.run_calls.append((context, max_iterations))
        return self._real.run(context, max_iterations)


# ---------------------------------------------------------------------------
# M1 -- one agent behaves like a single start()
# ---------------------------------------------------------------------------
def scenario_single_agent_matches_start() -> None:
    agent, pipeline, _ = _make_agent_and_collaborators()
    host = AutonomousHost()
    ctx = _FakeContext("m1")

    result = host.start_all([agent], ctx, iterations=3)

    check(isinstance(result, tuple), "M1: start_all() returns a tuple")
    check(len(result) == 1, "M1: one agent -> one entry in the outer tuple")
    check(
        isinstance(result[0], tuple) and len(result[0]) == 3,
        "M1: the single entry is the agent's own 3-result run() tuple",
    )
    check(len(pipeline.calls) == 3, "M1: pipeline.run() called 3 times via agent.run()")


# ---------------------------------------------------------------------------
# M2/M3 -- multiple agents, run exactly once each, in order
# ---------------------------------------------------------------------------
def scenario_multiple_agents_run_once_in_order() -> None:
    a1, p1, g1 = _make_agent_and_collaborators()
    a2, p2, g2 = _make_agent_and_collaborators()
    a3, p3, g3 = _make_agent_and_collaborators()
    spy1, spy2, spy3 = (
        _RunSpyAgent(a1, "a1"),
        _RunSpyAgent(a2, "a2"),
        _RunSpyAgent(a3, "a3"),
    )
    host = AutonomousHost()
    ctx = _FakeContext("m2")

    result = host.start_all([spy1, spy2, spy3], ctx, iterations=2)

    check(len(result) == 3, "M2: three agents -> three outer entries")
    check(
        len(spy1.run_calls) == 1
        and len(spy2.run_calls) == 1
        and len(spy3.run_calls) == 1,
        "M2: each agent's run() is called exactly once",
    )
    check(len(p1.calls) == 2 and len(p2.calls) == 2 and len(p3.calls) == 2,
          "M2: each agent's pipeline ran exactly 'iterations' times")
    check(
        spy1.run_calls[0] == (ctx, 2)
        and spy2.run_calls[0] == (ctx, 2)
        and spy3.run_calls[0] == (ctx, 2),
        "M3: every agent received the same context/iterations, in call order",
    )


# ---------------------------------------------------------------------------
# M4 -- each agent's returned tuple contents preserved unchanged
# ---------------------------------------------------------------------------
def scenario_result_contents_preserved() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host = AutonomousHost()
    ctx = _FakeContext("m4")

    result = host.start_all([a1, a2], ctx, iterations=2)

    check(
        [r.iteration for r in result[0]] == [1, 2],
        "M4: agent 1's iteration numbers preserved (1, 2)",
    )
    check(
        [r.iteration for r in result[1]] == [1, 2],
        "M4: agent 2's iteration numbers preserved (1, 2)",
    )
    check(
        all(r.success is True for entry in result for r in entry),
        "M4: every result across every agent reports success=True",
    )


# ---------------------------------------------------------------------------
# M5 -- empty iterable raises AutonomousHostError, no agent run
# ---------------------------------------------------------------------------
def scenario_empty_iterable_rejected() -> None:
    host = AutonomousHost()

    raised = False
    try:
        host.start_all([], _FakeContext("m5"), iterations=1)
    except AutonomousHostError:
        raised = True

    check(raised, "M5: start_all([], ...) raises AutonomousHostError")


# ---------------------------------------------------------------------------
# M6 -- None iterable raises AutonomousHostError
# ---------------------------------------------------------------------------
def scenario_none_iterable_rejected() -> None:
    host = AutonomousHost()

    raised = False
    try:
        host.start_all(None, _FakeContext("m6"), iterations=1)
    except AutonomousHostError:
        raised = True

    check(raised, "M6: start_all(None, ...) raises AutonomousHostError")


# ---------------------------------------------------------------------------
# M7 -- invalid (non-agent-shaped) entry rejected, all-or-nothing
# ---------------------------------------------------------------------------
def scenario_invalid_entry_rejected() -> None:
    a1, p1, _ = _make_agent_and_collaborators()
    spy1 = _RunSpyAgent(a1, "a1")
    host = AutonomousHost()

    for bad_entry in (None, "not-an-agent", 42, object()):
        p1.calls.clear()
        spy1.run_calls.clear()
        raised = False
        try:
            host.start_all([spy1, bad_entry], _FakeContext("m7"), iterations=1)
        except AutonomousHostError:
            raised = True

        check(
            raised,
            f"M7: an invalid entry ({bad_entry!r}) in 'agents' raises "
            "AutonomousHostError",
        )
        check(
            len(spy1.run_calls) == 0,
            f"M7: with invalid entry {bad_entry!r} present, no agent "
            "(including valid ones before it) was run -- all-or-nothing "
            "validation",
        )


# ---------------------------------------------------------------------------
# M8 -- invalid iterations rejected, no agent run at all
# ---------------------------------------------------------------------------
def scenario_invalid_iterations_rejected() -> None:
    for bad_value in (0, -1, "3", 2.5, None):
        a1, p1, _ = _make_agent_and_collaborators()
        spy1 = _RunSpyAgent(a1, "a1")
        host = AutonomousHost()

        raised = False
        try:
            host.start_all([spy1], _FakeContext("m8"), iterations=bad_value)
        except AutonomousHostError:
            raised = True

        check(
            raised,
            f"M8: start_all(..., iterations={bad_value!r}) raises "
            "AutonomousHostError",
        )
        check(
            len(spy1.run_calls) == 0,
            f"M8: iterations={bad_value!r} never reached any agent's run()",
        )


# ---------------------------------------------------------------------------
# M9 -- start_all() never calls RuntimeAnalysisPipeline directly
# ---------------------------------------------------------------------------
def scenario_never_calls_pipeline_directly() -> None:
    a1, p1, _ = _make_agent_and_collaborators()
    a2, p2, _ = _make_agent_and_collaborators()
    host = AutonomousHost()

    check(p1.calls == [] and p2.calls == [], "M9 precondition: no calls yet")

    host.start_all([a1, a2], _FakeContext("m9"), iterations=1)

    check(
        not hasattr(host, "_runtime_analysis_pipeline")
        and not hasattr(host, "runtime_analysis_pipeline"),
        "M9: AutonomousHost holds no direct RuntimeAnalysisPipeline reference",
    )


# ---------------------------------------------------------------------------
# M10 -- start_all() never calls GoalPlanner directly
# ---------------------------------------------------------------------------
def scenario_never_calls_goal_planner_directly() -> None:
    pipeline1 = _FakeRuntimeAnalysisPipeline()
    gp1 = _FakeGoalPlanner()
    a1 = _make_agent(pipeline1, gp1)
    pipeline2 = _FakeRuntimeAnalysisPipeline()
    gp2 = _FakeGoalPlanner()
    a2 = _make_agent(pipeline2, gp2)
    host = AutonomousHost()

    host.start_all([a1, a2], _FakeContext("m10"), iterations=1)

    check(
        gp1.build_plan_calls == [] and gp2.build_plan_calls == [],
        "M10: start_all() never triggers GoalPlanner.build_plan()",
    )
    check(
        not hasattr(host, "_goal_planner") and not hasattr(host, "goal_planner"),
        "M10: AutonomousHost holds no direct GoalPlanner reference",
    )


# ---------------------------------------------------------------------------
# M11 -- duplicate agents (same instance twice) both executed
# ---------------------------------------------------------------------------
def scenario_duplicate_agents_both_executed() -> None:
    a1, p1, _ = _make_agent_and_collaborators()
    spy1 = _RunSpyAgent(a1, "dup")
    host = AutonomousHost()
    ctx = _FakeContext("m11")

    result = host.start_all([spy1, spy1], ctx, iterations=1)

    check(len(result) == 2, "M11: the outer result has two entries (no dedup)")
    check(
        len(spy1.run_calls) == 2,
        "M11: the same agent instance's run() was called twice",
    )
    check(
        len(p1.calls) == 2,
        "M11: the underlying pipeline was invoked twice, once per listed run",
    )


# ---------------------------------------------------------------------------
# M12 -- a failing agent stops the batch; later agents never run
# ---------------------------------------------------------------------------
def scenario_failing_agent_stops_batch() -> None:
    good_pipeline = _FakeRuntimeAnalysisPipeline()
    good_gp = _FakeGoalPlanner()
    good_agent = _make_agent(good_pipeline, good_gp)
    good_spy = _RunSpyAgent(good_agent, "good")

    failing_pipeline = _FakeRuntimeAnalysisPipeline(should_fail=True)
    failing_gp = _FakeGoalPlanner()
    failing_agent = _make_agent(failing_pipeline, failing_gp)
    failing_spy = _RunSpyAgent(failing_agent, "failing")

    never_pipeline = _FakeRuntimeAnalysisPipeline()
    never_gp = _FakeGoalPlanner()
    never_agent = _make_agent(never_pipeline, never_gp)
    never_spy = _RunSpyAgent(never_agent, "never")

    host = AutonomousHost()

    raised = False
    try:
        host.start_all(
            [good_spy, failing_spy, never_spy], _FakeContext("m12"), iterations=2
        )
    except AutonomousAgentError:
        raised = True

    check(
        raised,
        "M12: the underlying AutonomousAgentError from a failing agent's "
        "run() propagates unchanged",
    )
    check(len(good_spy.run_calls) == 1, "M12: the good agent before it did run")
    check(
        len(failing_spy.run_calls) == 1,
        "M12: the failing agent was attempted exactly once (no retry)",
    )
    check(
        len(never_spy.run_calls) == 0,
        "M12: the agent listed after the failing one was never run",
    )


# ---------------------------------------------------------------------------
# M13 -- AutonomousHost remains stateless
# ---------------------------------------------------------------------------
def scenario_host_remains_stateless() -> None:
    try:
        host = AutonomousHost()
        constructed = True
    except TypeError:
        constructed = False

    check(
        constructed,
        "M13: AutonomousHost() can be constructed with zero arguments "
        "(no Composition Root wiring required)",
    )

    a1, _, _ = _make_agent_and_collaborators()
    before = dict(host.__dict__)
    host.start_all([a1], _FakeContext("m13"), iterations=1)
    after = dict(host.__dict__)

    check(
        before == after == {},
        "M13: start_all() adds/mutates no instance attributes on the host",
    )


# ---------------------------------------------------------------------------
# M14 -- repeated start_all() calls are independent
# ---------------------------------------------------------------------------
def scenario_repeated_calls_independent() -> None:
    host = AutonomousHost()

    a1, p1, _ = _make_agent_and_collaborators()
    a2, p2, _ = _make_agent_and_collaborators()

    result_first = host.start_all([a1], _FakeContext("m14-first"), iterations=1)

    a3, p3, _ = _make_agent_and_collaborators()
    result_second = host.start_all(
        [a2, a3], _FakeContext("m14-second"), iterations=2
    )

    check(
        len(result_first) == 1,
        "M14: the first call's result reflects only that call's agents",
    )
    check(
        len(result_second) == 2,
        "M14: the second call's result reflects only that call's agents "
        "(no leftover state from the first call)",
    )
    check(
        len(p1.calls) == 1 and len(p2.calls) == 2 and len(p3.calls) == 2,
        "M14: each call drove exactly its own agents' pipelines, "
        "independently of the other call",
    )


# ---------------------------------------------------------------------------
# M15 -- context=None raises AutonomousHostError, no agent run
# ---------------------------------------------------------------------------
def scenario_none_context_rejected() -> None:
    a1, p1, _ = _make_agent_and_collaborators()
    spy1 = _RunSpyAgent(a1, "a1")
    host = AutonomousHost()

    raised = False
    try:
        host.start_all([spy1], None, iterations=1)
    except AutonomousHostError:
        raised = True

    check(raised, "M15: start_all(..., context=None, ...) raises AutonomousHostError")
    check(len(spy1.run_calls) == 0, "M15: the refused call never reached any agent")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_single_agent_matches_start,
        scenario_multiple_agents_run_once_in_order,
        scenario_result_contents_preserved,
        scenario_empty_iterable_rejected,
        scenario_none_iterable_rejected,
        scenario_invalid_entry_rejected,
        scenario_invalid_iterations_rejected,
        scenario_never_calls_pipeline_directly,
        scenario_never_calls_goal_planner_directly,
        scenario_duplicate_agents_both_executed,
        scenario_failing_agent_stops_batch,
        scenario_host_remains_stateless,
        scenario_repeated_calls_independent,
        scenario_none_context_rejected,
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
    print(f"PHASE 3 SPRINT 15 MULTI-HOST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())