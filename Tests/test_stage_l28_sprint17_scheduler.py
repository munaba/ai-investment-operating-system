"""
Phase 3 Sprint 17 proof suite -- AutonomousScheduler (first synchronous
scheduler: FIFO queue + drain via AutonomousHost.start_all()).

Scope: dedicated regression suite for
``Orchestration.autonomous_scheduler.AutonomousScheduler`` only.
``AutonomousHost.start``/``start_all``/``stop``/``stop_all`` are
unmodified and already covered by their own dedicated suites
(``Tests/test_stage_l28_sprint12_host.py``,
``Tests/test_stage_l28_sprint15_multi_host.py``,
``Tests/test_stage_l28_sprint16_stop_all.py``); ``AutonomousAgent``
itself is unmodified and covered by
``Tests/test_stage_l28_autonomous_agent.py`` and its sibling Sprint
suites -- none of that is re-verified here beyond what
``AutonomousScheduler`` itself needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, constructor-
injected into real ``AutonomousAgent`` instances exactly like every
prior Sprint suite. A real ``AutonomousHost`` is used throughout (it
is itself stateless and already fully proven); a thin "spy" host is
used in a few scenarios purely to count/observe delegated
``start_all()`` calls without changing behavior.

No threading, no asyncio, no timers, no sleep, no cron, no daemon, no
background worker, no persistence -- all explicitly out of scope for
Sprint 17 and never exercised or required by this suite.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Invariant coverage:
    S1  -- schedule() stores work without executing it (agent never
           run until tick()).
    S2  -- tick() with one scheduled job executes it exactly once via
           host.start_all() and returns a 1-tuple of its result.
    S3  -- a second tick() call, right after a successful first
           tick(), executes nothing and returns an empty tuple.
    S4  -- multiple schedule() calls are drained by one tick() in
           strict FIFO order.
    S5  -- schedule() rejects a None host.
    S6  -- schedule() rejects a host without a callable start_all.
    S7  -- schedule() rejects None/empty/non-iterable/invalid-entry
           agents, matching AutonomousHost.start_all()'s own shape
           checks -- and nothing is queued when it rejects.
    S8  -- schedule() rejects a None context.
    S9  -- schedule() rejects invalid iterations (non-int, bool, < 1).
    S10 -- schedule() mutating the original list after scheduling has
           no effect on the already-queued job (eager snapshot).
    S11 -- a job that raises during tick() propagates the exception
           unchanged, and jobs queued after it are left untouched in
           the queue (not dropped, not attempted) for a future tick().
    S12 -- AutonomousScheduler never calls AutonomousAgent.run() or
           RuntimeAnalysisPipeline/GoalPlanner directly -- only
           through host.start_all().
    S13 -- tick() on a scheduler with nothing ever scheduled returns
           an empty tuple.
    S14 -- AutonomousScheduler needs zero constructor arguments and
           starts with an empty queue.
    S15 -- two independent AutonomousScheduler instances never share
           queued state.
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
    AutonomousAgentStatus,
)
from Orchestration.autonomous_host import AutonomousHost, AutonomousHostError
from Orchestration.autonomous_scheduler import (
    AutonomousScheduler,
    AutonomousSchedulerError,
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
    """Stand-in for one of the ten L18-L27 constructor dependencies."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeGoalPlanner:
    """Stand-in for Orchestration.planner.GoalPlanner. Neither
    AutonomousHost nor AutonomousScheduler must ever reach this
    directly."""

    def __init__(self) -> None:
        self.build_plan_calls: List[object] = []


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call --
    used here to prove AutonomousScheduler never reaches it
    directly."""

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


class _FakeContext:
    """Minimal stand-in for a ServiceContext-shaped object."""

    pass


class _StartAllSpyHost:
    """Thin spy wrapping a real AutonomousHost: forwards start_all()
    to the real host but records call order/args -- used only to
    assert delegation, never to change behavior."""

    def __init__(self) -> None:
        self._real = AutonomousHost()
        self.start_all_calls: List[Tuple[object, object, int]] = []

    def start_all(self, agents, context, iterations):
        self.start_all_calls.append((tuple(agents), context, iterations))
        return self._real.start_all(agents, context, iterations)


class _FailingHost:
    """Stand-in host whose start_all() always raises -- used to
    exercise the propagate-and-leave-remaining-queued behavior
    (S11)."""

    def __init__(self) -> None:
        self.start_all_calls = 0

    def start_all(self, agents, context, iterations):
        self.start_all_calls += 1
        raise AutonomousHostError("simulated start_all failure")


# ---------------------------------------------------------------------------
# S1 -- schedule() stores work without executing it
# ---------------------------------------------------------------------------
def scenario_schedule_does_not_execute() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    host = AutonomousHost()
    scheduler = AutonomousScheduler()

    scheduler.schedule(host, [agent], _FakeContext(), 1)

    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "S1: schedule() alone never runs the agent (status stays IDLE)",
    )


# ---------------------------------------------------------------------------
# S2 -- tick() with one job executes it exactly once, returns 1-tuple
# ---------------------------------------------------------------------------
def scenario_tick_executes_one_job_once() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()
    context = _FakeContext()

    scheduler.schedule(spy_host, [agent], context, 2)
    result = scheduler.tick()

    check(
        len(spy_host.start_all_calls) == 1,
        "S2: tick() delegates to host.start_all() exactly once for one job",
    )
    check(
        isinstance(result, tuple) and len(result) == 1,
        "S2: tick() returns a 1-tuple for one queued job",
    )
    check(
        agent.iteration_count == 2,
        "S2: the agent was actually run (iteration_count reflects the "
        "2 iterations) once tick() executed",
    )


# ---------------------------------------------------------------------------
# S3 -- a second tick() executes nothing
# ---------------------------------------------------------------------------
def scenario_second_tick_executes_nothing() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()

    scheduler.schedule(spy_host, [agent], _FakeContext(), 1)
    scheduler.tick()
    second_result = scheduler.tick()

    check(
        len(spy_host.start_all_calls) == 1,
        "S3: a second tick() does not trigger any further start_all() call",
    )
    check(
        second_result == (),
        "S3: a second tick() returns an empty tuple",
    )


# ---------------------------------------------------------------------------
# S4 -- multiple schedule() calls drained in strict FIFO order
# ---------------------------------------------------------------------------
def scenario_fifo_order_preserved() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    a3, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()
    ctx1, ctx2, ctx3 = _FakeContext(), _FakeContext(), _FakeContext()

    scheduler.schedule(spy_host, [a1], ctx1, 1)
    scheduler.schedule(spy_host, [a2], ctx2, 1)
    scheduler.schedule(spy_host, [a3], ctx3, 1)

    result = scheduler.tick()

    check(
        [call[1] for call in spy_host.start_all_calls] == [ctx1, ctx2, ctx3],
        "S4: jobs are executed by tick() in strict FIFO (schedule) order",
    )
    check(len(result) == 3, "S4: tick() returns one result entry per job")


# ---------------------------------------------------------------------------
# S5 -- schedule() rejects a None host
# ---------------------------------------------------------------------------
def scenario_none_host_rejected() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()

    raised = False
    try:
        scheduler.schedule(None, [agent], _FakeContext(), 1)
    except AutonomousSchedulerError:
        raised = True

    check(raised, "S5: schedule(None, ...) raises AutonomousSchedulerError")
    check(
        scheduler.tick() == (),
        "S5: nothing was queued by the rejected call",
    )


# ---------------------------------------------------------------------------
# S6 -- schedule() rejects a host without callable start_all
# ---------------------------------------------------------------------------
def scenario_host_without_start_all_rejected() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()

    class _NotAHost:
        pass

    raised = False
    try:
        scheduler.schedule(_NotAHost(), [agent], _FakeContext(), 1)
    except AutonomousSchedulerError:
        raised = True

    check(
        raised,
        "S6: a host-shaped object lacking start_all() raises "
        "AutonomousSchedulerError",
    )


# ---------------------------------------------------------------------------
# S7 -- schedule() rejects None/empty/non-iterable/invalid-entry agents
# ---------------------------------------------------------------------------
def scenario_invalid_agents_rejected() -> None:
    host = AutonomousHost()
    scheduler = AutonomousScheduler()

    raised = False
    try:
        scheduler.schedule(host, None, _FakeContext(), 1)
    except AutonomousSchedulerError:
        raised = True
    check(raised, "S7: schedule(..., agents=None, ...) raises")

    raised = False
    try:
        scheduler.schedule(host, [], _FakeContext(), 1)
    except AutonomousSchedulerError:
        raised = True
    check(raised, "S7: schedule(..., agents=[], ...) raises")

    raised = False
    try:
        scheduler.schedule(host, 42, _FakeContext(), 1)
    except AutonomousSchedulerError:
        raised = True
    check(raised, "S7: schedule(..., agents=42 (non-iterable), ...) raises")

    good_agent, _, _ = _make_agent_and_collaborators()
    for bad_entry in (None, "not-an-agent", 42, object()):
        raised = False
        try:
            scheduler.schedule(host, [good_agent, bad_entry], _FakeContext(), 1)
        except AutonomousSchedulerError:
            raised = True
        check(
            raised,
            f"S7: an invalid entry ({bad_entry!r}) among 'agents' raises",
        )

    check(
        scheduler.tick() == (),
        "S7: none of the rejected schedule() calls queued anything",
    )


# ---------------------------------------------------------------------------
# S8 -- schedule() rejects a None context
# ---------------------------------------------------------------------------
def scenario_none_context_rejected() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    host = AutonomousHost()
    scheduler = AutonomousScheduler()

    raised = False
    try:
        scheduler.schedule(host, [agent], None, 1)
    except AutonomousSchedulerError:
        raised = True

    check(raised, "S8: schedule(..., context=None, ...) raises")


# ---------------------------------------------------------------------------
# S9 -- schedule() rejects invalid iterations
# ---------------------------------------------------------------------------
def scenario_invalid_iterations_rejected() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    host = AutonomousHost()
    scheduler = AutonomousScheduler()

    for bad_iterations in (0, -1, 1.5, "1", None, True, False):
        raised = False
        try:
            scheduler.schedule(host, [agent], _FakeContext(), bad_iterations)
        except AutonomousSchedulerError:
            raised = True
        check(
            raised,
            f"S9: iterations={bad_iterations!r} raises "
            "AutonomousSchedulerError",
        )


# ---------------------------------------------------------------------------
# S10 -- mutating the original agents list after scheduling has no effect
# ---------------------------------------------------------------------------
def scenario_agents_snapshot_is_eager() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()

    mutable_agents = [a1]
    scheduler.schedule(spy_host, mutable_agents, _FakeContext(), 1)
    mutable_agents.append(a2)
    mutable_agents.clear()

    scheduler.tick()

    check(
        spy_host.start_all_calls[0][0] == (a1,),
        "S10: the queued job's agents snapshot is unaffected by later "
        "mutation of the original list passed to schedule()",
    )


# ---------------------------------------------------------------------------
# S11 -- a failing job propagates; later jobs stay queued untouched
# ---------------------------------------------------------------------------
def scenario_failing_job_propagates_and_leaves_rest_queued() -> None:
    good_agent, _, _ = _make_agent_and_collaborators()
    good_host = _StartAllSpyHost()

    failing_host = _FailingHost()
    failing_agent, _, _ = _make_agent_and_collaborators()

    never_agent, _, _ = _make_agent_and_collaborators()
    never_host = _StartAllSpyHost()

    scheduler = AutonomousScheduler()
    scheduler.schedule(good_host, [good_agent], _FakeContext(), 1)
    scheduler.schedule(failing_host, [failing_agent], _FakeContext(), 1)
    scheduler.schedule(never_host, [never_agent], _FakeContext(), 1)

    raised = False
    try:
        scheduler.tick()
    except AutonomousHostError:
        raised = True

    check(
        raised,
        "S11: the AutonomousHostError from a failing job's start_all() "
        "propagates unchanged out of tick()",
    )
    check(
        len(good_host.start_all_calls) == 1,
        "S11: the good job before the failing one was executed",
    )
    check(
        failing_host.start_all_calls == 1,
        "S11: the failing job was attempted exactly once (no retry)",
    )
    check(
        len(never_host.start_all_calls) == 0,
        "S11: the job queued after the failing one was never attempted",
    )

    # The job behind the failing one must still be queued -- an
    # explicit follow-up tick() should now run it.
    follow_up_result = scheduler.tick()
    check(
        len(never_host.start_all_calls) == 1,
        "S11: a follow-up tick() runs the job left behind after the "
        "earlier failure",
    )
    check(
        len(follow_up_result) == 1,
        "S11: the follow-up tick() result contains exactly the one "
        "remaining job's result",
    )


# ---------------------------------------------------------------------------
# S12 -- never touches AutonomousAgent/RuntimeAnalysisPipeline/GoalPlanner
#         directly -- only through host.start_all()
# ---------------------------------------------------------------------------
def scenario_never_bypasses_host() -> None:
    pipeline = _FakeRuntimeAnalysisPipeline()
    goal_planner = _FakeGoalPlanner()
    agent = _make_agent(pipeline, goal_planner)
    spy_host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()

    scheduler.schedule(spy_host, [agent], _FakeContext(), 1)
    scheduler.tick()

    check(
        len(spy_host.start_all_calls) == 1,
        "S12: the only execution path taken was host.start_all()",
    )
    check(
        not hasattr(scheduler, "_runtime_analysis_pipeline")
        and not hasattr(scheduler, "runtime_analysis_pipeline")
        and not hasattr(scheduler, "_goal_planner")
        and not hasattr(scheduler, "goal_planner"),
        "S12: AutonomousScheduler holds no direct pipeline/goal-planner "
        "reference",
    )
    # pipeline/goal_planner *are* legitimately touched -- but only as a
    # side effect of the agent's own run() inside start_all(), never by
    # the scheduler calling into them itself. We only assert the
    # scheduler object itself never references them directly (above).


# ---------------------------------------------------------------------------
# S13 -- tick() with nothing ever scheduled returns an empty tuple
# ---------------------------------------------------------------------------
def scenario_tick_with_nothing_scheduled() -> None:
    scheduler = AutonomousScheduler()

    result = scheduler.tick()

    check(
        result == (),
        "S13: tick() on a scheduler with nothing scheduled returns ()",
    )


# ---------------------------------------------------------------------------
# S14 -- zero constructor args, starts empty
# ---------------------------------------------------------------------------
def scenario_zero_args_constructor_starts_empty() -> None:
    scheduler = AutonomousScheduler()

    check(
        scheduler.tick() == (),
        "S14: AutonomousScheduler() takes no arguments and starts with "
        "an empty queue",
    )


# ---------------------------------------------------------------------------
# S15 -- two scheduler instances never share queued state
# ---------------------------------------------------------------------------
def scenario_instances_do_not_share_state() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()

    scheduler_a = AutonomousScheduler()
    scheduler_b = AutonomousScheduler()

    scheduler_a.schedule(spy_host, [a1], _FakeContext(), 1)
    result_b = scheduler_b.tick()

    check(
        result_b == (),
        "S15: scheduler_b's tick() sees none of scheduler_a's queued work",
    )
    check(
        len(spy_host.start_all_calls) == 0,
        "S15: scheduler_b's tick() triggered no start_all() call at all",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_schedule_does_not_execute,
        scenario_tick_executes_one_job_once,
        scenario_second_tick_executes_nothing,
        scenario_fifo_order_preserved,
        scenario_none_host_rejected,
        scenario_host_without_start_all_rejected,
        scenario_invalid_agents_rejected,
        scenario_none_context_rejected,
        scenario_invalid_iterations_rejected,
        scenario_agents_snapshot_is_eager,
        scenario_failing_job_propagates_and_leaves_rest_queued,
        scenario_never_bypasses_host,
        scenario_tick_with_nothing_scheduled,
        scenario_zero_args_constructor_starts_empty,
        scenario_instances_do_not_share_state,
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
    print(f"PHASE 3 SPRINT 17 SCHEDULER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())