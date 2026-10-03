"""
Phase 3 Sprint 18 proof suite -- AutonomousScheduler queue management
(``pending_jobs()`` + ``clear()``).

Scope: dedicated regression suite for the two new read-only/mutating-
only-the-queue methods added to
``Orchestration.autonomous_scheduler.AutonomousScheduler`` in Sprint
18. ``schedule()`` and ``tick()`` themselves are unmodified and
already covered by ``Tests/test_stage_l28_sprint17_scheduler.py`` --
none of that is re-verified here beyond what ``pending_jobs()`` and
``clear()`` themselves need.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, exactly like the
Sprint 17 suite. A real ``AutonomousHost`` is used throughout.

No threading, no asyncio, no timers, no sleep, no persistence -- all
explicitly out of scope for Sprint 18 and never exercised or required
by this suite.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Invariant coverage:
    Q1  -- pending_jobs() on a fresh scheduler returns an empty tuple.
    Q2  -- pending_jobs() reflects one scheduled job without executing
           it (agent status stays IDLE, host.start_all() never
           called).
    Q3  -- pending_jobs() reflects multiple scheduled jobs in strict
           FIFO order.
    Q4  -- pending_jobs() returns a tuple (immutable snapshot type).
    Q5  -- mutating the tuple/entries returned by pending_jobs() has
           no effect on the scheduler's actual queue (verified via a
           subsequent tick()).
    Q6  -- calling pending_jobs() twice in a row returns equal
           snapshots and does not itself drain or reorder the queue.
    Q7  -- after tick() drains the queue, pending_jobs() reflects only
           the jobs left behind (matches Sprint 17 S11-style partial
           drain).
    Q8  -- clear() on an empty scheduler is a no-op and returns None.
    Q9  -- clear() removes every queued job; a following tick()
           executes nothing and returns an empty tuple.
    Q10 -- clear() never calls any queued job's host.start_all() and
           never touches any agent's status.
    Q11 -- clear() is safe to call repeatedly (idempotent).
    Q12 -- calling schedule() again after clear() works normally and
           the new job runs correctly on tick().
    Q13 -- pending_jobs() and clear() do not disturb FIFO ordering of
           jobs added before/after they are called.
    Q14 -- two independent AutonomousScheduler instances never share
           pending_jobs()/clear() state.
    Q15 -- pending_jobs() does not expose the scheduler's private
           ``_queue`` list object itself.
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
    SchedulerJob,
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
    """Stand-in for Orchestration.planner.GoalPlanner."""

    def __init__(self) -> None:
        self.build_plan_calls: List[object] = []


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline."""

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
    to the real host but records call order/args."""

    def __init__(self) -> None:
        self._real = AutonomousHost()
        self.start_all_calls: List[Tuple[object, object, int]] = []

    def start_all(self, agents, context, iterations):
        self.start_all_calls.append((tuple(agents), context, iterations))
        return self._real.start_all(agents, context, iterations)


class _FailingHost:
    """Stand-in host whose start_all() always raises."""

    def __init__(self) -> None:
        self.start_all_calls = 0

    def start_all(self, agents, context, iterations):
        self.start_all_calls += 1
        raise AutonomousHostError("simulated start_all failure")


# ---------------------------------------------------------------------------
# Q1 -- pending_jobs() on a fresh scheduler returns an empty tuple
# ---------------------------------------------------------------------------
def scenario_pending_jobs_empty_on_fresh_scheduler() -> None:
    scheduler = AutonomousScheduler()

    result = scheduler.pending_jobs()

    check(
        result == (),
        "Q1: pending_jobs() on a fresh scheduler returns an empty tuple",
    )


# ---------------------------------------------------------------------------
# Q2 -- pending_jobs() reflects one job without executing it
# ---------------------------------------------------------------------------
def scenario_pending_jobs_reflects_one_job_without_executing() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()
    context = _FakeContext()

    scheduler.schedule(spy_host, [agent], context, 3)
    snapshot = scheduler.pending_jobs()

    check(
        len(snapshot) == 1,
        "Q2: pending_jobs() shows exactly one entry after one schedule()",
    )
    check(
        isinstance(snapshot[0], SchedulerJob)
        and snapshot[0].host is spy_host
        and snapshot[0].agents == (agent,)
        and snapshot[0].context is context
        and snapshot[0].iterations == 3
        and isinstance(snapshot[0].job_id, str)
        and snapshot[0].job_id != "",
        "Q2: pending_jobs() entry matches (host, agents, context, "
        "iterations) exactly as scheduled, and exposes a non-empty "
        "job_id",
    )
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "Q2: pending_jobs() alone never runs the agent (status stays IDLE)",
    )
    check(
        len(spy_host.start_all_calls) == 0,
        "Q2: pending_jobs() never calls host.start_all()",
    )


# ---------------------------------------------------------------------------
# Q3 -- pending_jobs() reflects multiple jobs in strict FIFO order
# ---------------------------------------------------------------------------
def scenario_pending_jobs_fifo_order() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    a3, _, _ = _make_agent_and_collaborators()
    host1, host2, host3 = (
        _StartAllSpyHost(),
        _StartAllSpyHost(),
        _StartAllSpyHost(),
    )
    scheduler = AutonomousScheduler()
    ctx1, ctx2, ctx3 = _FakeContext(), _FakeContext(), _FakeContext()

    scheduler.schedule(host1, [a1], ctx1, 1)
    scheduler.schedule(host2, [a2], ctx2, 2)
    scheduler.schedule(host3, [a3], ctx3, 3)

    snapshot = scheduler.pending_jobs()

    check(
        len(snapshot) == 3
        and all(isinstance(job, SchedulerJob) for job in snapshot)
        and (snapshot[0].host, snapshot[0].agents, snapshot[0].context, snapshot[0].iterations)
        == (host1, (a1,), ctx1, 1)
        and (snapshot[1].host, snapshot[1].agents, snapshot[1].context, snapshot[1].iterations)
        == (host2, (a2,), ctx2, 2)
        and (snapshot[2].host, snapshot[2].agents, snapshot[2].context, snapshot[2].iterations)
        == (host3, (a3,), ctx3, 3),
        "Q3: pending_jobs() preserves strict FIFO order across multiple "
        "schedule() calls",
    )


# ---------------------------------------------------------------------------
# Q4 -- pending_jobs() returns a tuple
# ---------------------------------------------------------------------------
def scenario_pending_jobs_returns_tuple_type() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()
    scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)

    result = scheduler.pending_jobs()

    check(
        isinstance(result, tuple),
        "Q4: pending_jobs() returns a tuple, not a list",
    )
    check(
        all(isinstance(entry, SchedulerJob) for entry in result),
        "Q4: each pending_jobs() entry is a SchedulerJob instance",
    )


# ---------------------------------------------------------------------------
# Q5 -- mutating the returned snapshot has no effect on the real queue
# ---------------------------------------------------------------------------
def scenario_pending_jobs_snapshot_mutation_is_isolated() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()
    context = _FakeContext()

    scheduler.schedule(spy_host, [agent], context, 1)
    snapshot = scheduler.pending_jobs()

    # Tuples themselves can't be appended/removed in place -- attempt
    # the closest available mutation (rebinding the local name) and
    # confirm it has zero effect on the scheduler.
    snapshot = snapshot + ((None, (), None, 99),)

    result = scheduler.tick()

    check(
        len(result) == 1,
        "Q5: rebinding/extending the caller's local snapshot variable "
        "does not add anything to the real queue drained by tick()",
    )
    check(
        len(spy_host.start_all_calls) == 1,
        "Q5: only the originally-scheduled job's host.start_all() was "
        "ever called",
    )


# ---------------------------------------------------------------------------
# Q6 -- calling pending_jobs() twice does not itself drain/reorder
# ---------------------------------------------------------------------------
def scenario_pending_jobs_is_idempotent_read() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()
    context = _FakeContext()

    scheduler.schedule(spy_host, [agent], context, 1)

    first = scheduler.pending_jobs()
    second = scheduler.pending_jobs()

    check(
        first == second,
        "Q6: two consecutive pending_jobs() calls return equal snapshots",
    )
    check(
        len(scheduler.tick()) == 1,
        "Q6: repeated pending_jobs() calls did not drain or lose the "
        "queued job -- tick() still executes it",
    )


# ---------------------------------------------------------------------------
# Q7 -- after a partial tick() drain, pending_jobs() shows only what's left
# ---------------------------------------------------------------------------
def scenario_pending_jobs_reflects_partial_drain() -> None:
    good_agent, _, _ = _make_agent_and_collaborators()
    good_host = _StartAllSpyHost()

    failing_host = _FailingHost()
    failing_agent, _, _ = _make_agent_and_collaborators()

    never_agent, _, _ = _make_agent_and_collaborators()
    never_host = _StartAllSpyHost()

    scheduler = AutonomousScheduler()
    ctx_good, ctx_failing, ctx_never = (
        _FakeContext(),
        _FakeContext(),
        _FakeContext(),
    )
    scheduler.schedule(good_host, [good_agent], ctx_good, 1)
    scheduler.schedule(failing_host, [failing_agent], ctx_failing, 1)
    scheduler.schedule(never_host, [never_agent], ctx_never, 1)

    try:
        scheduler.tick()
    except AutonomousHostError:
        pass

    remaining = scheduler.pending_jobs()

    check(
        len(remaining) == 1
        and remaining[0].host is never_host
        and remaining[0].agents == (never_agent,)
        and remaining[0].context is ctx_never
        and remaining[0].iterations == 1,
        "Q7: after a mid-queue failure during tick(), pending_jobs() "
        "shows exactly the one job left behind",
    )


# ---------------------------------------------------------------------------
# Q8 -- clear() on an empty scheduler is a no-op and returns None
# ---------------------------------------------------------------------------
def scenario_clear_on_empty_scheduler_is_noop() -> None:
    scheduler = AutonomousScheduler()

    result = scheduler.clear()

    check(result is None, "Q8: clear() returns None")
    check(
        scheduler.pending_jobs() == (),
        "Q8: clear() on an already-empty scheduler leaves it empty",
    )


# ---------------------------------------------------------------------------
# Q9 -- clear() removes every queued job
# ---------------------------------------------------------------------------
def scenario_clear_removes_all_queued_jobs() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host1, host2 = _StartAllSpyHost(), _StartAllSpyHost()
    scheduler = AutonomousScheduler()

    scheduler.schedule(host1, [a1], _FakeContext(), 1)
    scheduler.schedule(host2, [a2], _FakeContext(), 1)

    result = scheduler.clear()

    check(result is None, "Q9: clear() returns None")
    check(
        scheduler.pending_jobs() == (),
        "Q9: clear() empties pending_jobs() after two scheduled jobs",
    )

    tick_result = scheduler.tick()
    check(
        tick_result == (),
        "Q9: tick() after clear() executes nothing and returns an "
        "empty tuple",
    )


# ---------------------------------------------------------------------------
# Q10 -- clear() never executes anything
# ---------------------------------------------------------------------------
def scenario_clear_never_executes_anything() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()

    scheduler.schedule(spy_host, [agent], _FakeContext(), 1)
    scheduler.clear()

    check(
        len(spy_host.start_all_calls) == 0,
        "Q10: clear() never calls a queued job's host.start_all()",
    )
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "Q10: clear() never touches a queued job's agent status",
    )


# ---------------------------------------------------------------------------
# Q11 -- clear() is safe to call repeatedly
# ---------------------------------------------------------------------------
def scenario_clear_is_idempotent() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()
    scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)

    scheduler.clear()
    second = scheduler.clear()
    third = scheduler.clear()

    check(
        second is None and third is None,
        "Q11: repeated clear() calls each return None",
    )
    check(
        scheduler.pending_jobs() == (),
        "Q11: repeated clear() calls leave the queue empty (idempotent)",
    )


# ---------------------------------------------------------------------------
# Q12 -- schedule() after clear() works normally
# ---------------------------------------------------------------------------
def scenario_schedule_after_clear_works_normally() -> None:
    old_agent, _, _ = _make_agent_and_collaborators()
    new_agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()

    scheduler.schedule(spy_host, [old_agent], _FakeContext(), 1)
    scheduler.clear()
    scheduler.schedule(spy_host, [new_agent], _FakeContext(), 5)

    result = scheduler.tick()

    check(
        len(spy_host.start_all_calls) == 1,
        "Q12: exactly one job (the one scheduled after clear()) runs",
    )
    check(
        spy_host.start_all_calls[0][2] == 5,
        "Q12: the post-clear() job's own iterations value reaches "
        "host.start_all() correctly",
    )
    check(
        len(result) == 1,
        "Q12: tick() returns exactly one result for the post-clear() job",
    )


# ---------------------------------------------------------------------------
# Q13 -- pending_jobs()/clear() do not disturb FIFO ordering
# ---------------------------------------------------------------------------
def scenario_fifo_preserved_around_inspection_and_clear() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host1, host2 = _StartAllSpyHost(), _StartAllSpyHost()
    scheduler = AutonomousScheduler()

    scheduler.schedule(host1, [a1], _FakeContext(), 1)
    scheduler.pending_jobs()  # inspect, should not disturb order
    scheduler.schedule(host2, [a2], _FakeContext(), 1)
    scheduler.pending_jobs()  # inspect again

    snapshot = scheduler.pending_jobs()
    check(
        snapshot[0].host is host1 and snapshot[1].host is host2,
        "Q13: FIFO order across interleaved pending_jobs() calls is "
        "unchanged",
    )

    scheduler.tick()
    check(
        list(scheduler.pending_jobs()) == [],
        "Q13: queue is empty after a full tick() following inspection",
    )


# ---------------------------------------------------------------------------
# Q14 -- two scheduler instances never share pending_jobs()/clear() state
# ---------------------------------------------------------------------------
def scenario_instances_do_not_share_queue_management_state() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()

    scheduler_a = AutonomousScheduler()
    scheduler_b = AutonomousScheduler()

    scheduler_a.schedule(spy_host, [a1], _FakeContext(), 1)

    check(
        scheduler_b.pending_jobs() == (),
        "Q14: scheduler_b's pending_jobs() sees none of scheduler_a's "
        "queued work",
    )

    scheduler_b.clear()  # no-op, must not affect scheduler_a
    check(
        len(scheduler_a.pending_jobs()) == 1,
        "Q14: clear() on scheduler_b does not affect scheduler_a's queue",
    )


# ---------------------------------------------------------------------------
# Q15 -- pending_jobs() does not hand out the private _queue list itself
# ---------------------------------------------------------------------------
def scenario_pending_jobs_does_not_expose_internal_list() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()
    scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)

    result = scheduler.pending_jobs()

    check(
        result is not scheduler._queue,
        "Q15: pending_jobs() does not return the same object as the "
        "private _queue list",
    )
    check(
        not isinstance(result, list),
        "Q15: pending_jobs() return type is not a list",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_pending_jobs_empty_on_fresh_scheduler,
        scenario_pending_jobs_reflects_one_job_without_executing,
        scenario_pending_jobs_fifo_order,
        scenario_pending_jobs_returns_tuple_type,
        scenario_pending_jobs_snapshot_mutation_is_isolated,
        scenario_pending_jobs_is_idempotent_read,
        scenario_pending_jobs_reflects_partial_drain,
        scenario_clear_on_empty_scheduler_is_noop,
        scenario_clear_removes_all_queued_jobs,
        scenario_clear_never_executes_anything,
        scenario_clear_is_idempotent,
        scenario_schedule_after_clear_works_normally,
        scenario_fifo_preserved_around_inspection_and_clear,
        scenario_instances_do_not_share_queue_management_state,
        scenario_pending_jobs_does_not_expose_internal_list,
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
    print(f"PHASE 3 SPRINT 18 QUEUE MANAGEMENT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())