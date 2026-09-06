"""
Phase 3 Sprint 21 proof suite -- AutonomousScheduler stable job
identity (``SchedulerJob.job_id``).

Scope: dedicated regression suite for Sprint 21 only. Sprint 21
replaces queue-index-based job identity with a stable ``job_id``
(uuid4 string) minted once per job at ``schedule()`` time:

    - ``schedule()`` now returns the new job's ``job_id`` instead of
      ``None``.
    - ``pending_jobs()`` now yields ``SchedulerJob`` instances (each
      exposing ``job_id``, ``host``, ``agents``, ``context``,
      ``iterations``) instead of bare ``(host, agents, context,
      iterations)`` tuples.
    - ``cancel()`` now takes a ``job_id`` string instead of a queue
      index, and raises ``AutonomousSchedulerError`` for an unknown
      ``job_id``.

FIFO execution order, ``tick()`` behavior, ``clear()``, and
``pause()``/``resume()`` are otherwise unchanged and are re-verified
here only to the extent Sprint 21 could plausibly have disturbed them.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, exactly like the
Sprint 17-20 suites. A real ``AutonomousHost`` is used throughout.

No threading, no asyncio, no timers, no sleep, no persistence -- all
explicitly out of scope for Sprint 21 and never exercised or required
by this suite.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Invariant coverage:
    J1  -- schedule() returns a str job_id (not None).
    J2  -- job_ids are unique across multiple schedule() calls, even
           with otherwise-identical arguments (duplicate agents/host).
    J3  -- pending_jobs() entries expose the same job_id returned by
           schedule(), in the same order.
    J4  -- pending_jobs() entries are SchedulerJob instances exposing
           host, agents, context, iterations matching what was
           scheduled.
    J5  -- cancel(job_id) removes exactly the targeted job and no
           other.
    J6  -- cancel() with an unknown job_id raises
           AutonomousSchedulerError, including on an empty queue.
    J7  -- cancel() preserves FIFO order of the remaining jobs.
    J8  -- FIFO execution order via tick() is unaffected by the switch
           to job_id (results still arrive in schedule() order).
    J9  -- duplicate agents across two different schedule() calls are
           allowed and produce two distinct job_ids.
    J10 -- clear() empties the queue regardless of job_id contents,
           and a subsequent pending_jobs() is empty.
    J11 -- pause()/resume() behavior is unaffected: tick() while
           paused executes nothing and leaves job_ids/queue untouched;
           resuming drains normally.
    J12 -- cancelling a job_id twice raises the second time (it no
           longer exists after the first removal).
    J13 -- a cancelled job's host.start_all() is never called.
    J14 -- AutonomousSchedulerError raised by cancel() for an unknown
           job_id is an instance of the shared AgentError base.
    J15 -- two independent AutonomousScheduler instances never share
           job_id/cancel() state.
    J16 -- SchedulerJob instances are immutable (frozen dataclass) --
           attempting to reassign a field raises.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
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
# J1 -- schedule() returns a str job_id
# ---------------------------------------------------------------------------
def scenario_schedule_returns_str_job_id() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()

    job_id = scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)

    check(
        isinstance(job_id, str) and job_id != "",
        "J1: schedule() returns a non-empty str job_id",
    )


# ---------------------------------------------------------------------------
# J2 -- job_ids are unique, even for otherwise-identical jobs
# ---------------------------------------------------------------------------
def scenario_job_ids_are_unique() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    host = _StartAllSpyHost()
    context = _FakeContext()
    scheduler = AutonomousScheduler()

    ids = [
        scheduler.schedule(host, [agent], context, 1) for _ in range(5)
    ]

    check(
        len(set(ids)) == len(ids),
        "J2: job_ids are unique across multiple schedule() calls, even "
        "with identical host/agents/context/iterations",
    )


# ---------------------------------------------------------------------------
# J3 -- pending_jobs() entries expose the same job_id schedule() returned
# ---------------------------------------------------------------------------
def scenario_pending_jobs_expose_matching_job_ids() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()

    id1 = scheduler.schedule(_StartAllSpyHost(), [a1], _FakeContext(), 1)
    id2 = scheduler.schedule(_StartAllSpyHost(), [a2], _FakeContext(), 2)

    pending = scheduler.pending_jobs()

    check(
        [job.job_id for job in pending] == [id1, id2],
        "J3: pending_jobs() reports job_ids in the same order as "
        "schedule() returned them",
    )


# ---------------------------------------------------------------------------
# J4 -- pending_jobs() entries are SchedulerJob instances with correct fields
# ---------------------------------------------------------------------------
def scenario_pending_jobs_entries_have_correct_fields() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    host = _StartAllSpyHost()
    context = _FakeContext()
    scheduler = AutonomousScheduler()

    job_id = scheduler.schedule(host, [agent], context, 3)
    pending = scheduler.pending_jobs()

    check(len(pending) == 1, "J4: pending_jobs() has exactly one entry")
    entry = pending[0]
    check(
        isinstance(entry, SchedulerJob),
        "J4: pending_jobs() entry is a SchedulerJob instance",
    )
    check(
        entry.job_id == job_id
        and entry.host is host
        and entry.agents == (agent,)
        and entry.context is context
        and entry.iterations == 3,
        "J4: pending_jobs() entry's fields match exactly what was "
        "scheduled",
    )


# ---------------------------------------------------------------------------
# J5 -- cancel(job_id) removes exactly the targeted job and no other
# ---------------------------------------------------------------------------
def scenario_cancel_removes_exactly_targeted_job() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    a3, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()

    id1 = scheduler.schedule(_StartAllSpyHost(), [a1], _FakeContext(), 1)
    id2 = scheduler.schedule(_StartAllSpyHost(), [a2], _FakeContext(), 1)
    id3 = scheduler.schedule(_StartAllSpyHost(), [a3], _FakeContext(), 1)

    scheduler.cancel(id2)

    remaining_ids = [job.job_id for job in scheduler.pending_jobs()]
    check(
        remaining_ids == [id1, id3],
        "J5: cancel(job_id) removes exactly the targeted job, "
        "preserving the other two in order",
    )


# ---------------------------------------------------------------------------
# J6 -- cancel() with an unknown job_id raises, including on empty queue
# ---------------------------------------------------------------------------
def scenario_cancel_unknown_job_id_raises() -> None:
    scheduler = AutonomousScheduler()

    try:
        scheduler.cancel("not-a-real-job-id")
        check(
            False,
            "J6: cancel() with an unknown job_id on an empty queue "
            "raises AutonomousSchedulerError",
        )
    except AutonomousSchedulerError:
        check(
            True,
            "J6: cancel() with an unknown job_id on an empty queue "
            "raises AutonomousSchedulerError",
        )

    agent, _, _ = _make_agent_and_collaborators()
    real_id = scheduler.schedule(
        _StartAllSpyHost(), [agent], _FakeContext(), 1
    )

    try:
        scheduler.cancel("still-not-a-real-job-id")
        check(
            False,
            "J6: cancel() with an unknown job_id on a non-empty queue "
            "raises AutonomousSchedulerError",
        )
    except AutonomousSchedulerError:
        check(
            True,
            "J6: cancel() with an unknown job_id on a non-empty queue "
            "raises AutonomousSchedulerError",
        )

    check(
        len(scheduler.pending_jobs()) == 1
        and scheduler.pending_jobs()[0].job_id == real_id,
        "J6: a failed cancel() call leaves the real job untouched",
    )


# ---------------------------------------------------------------------------
# J7 -- cancel() preserves FIFO order of remaining jobs
# ---------------------------------------------------------------------------
def scenario_cancel_preserves_fifo_order() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    a3, _, _ = _make_agent_and_collaborators()
    a4, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()

    ids = [
        scheduler.schedule(_StartAllSpyHost(), [a], _FakeContext(), 1)
        for a in (a1, a2, a3, a4)
    ]

    scheduler.cancel(ids[1])  # remove second job

    remaining_ids = [job.job_id for job in scheduler.pending_jobs()]
    check(
        remaining_ids == [ids[0], ids[2], ids[3]],
        "J7: cancel() preserves the original relative FIFO order of "
        "the remaining jobs",
    )


# ---------------------------------------------------------------------------
# J8 -- FIFO execution order via tick() is unaffected by job_id switch
# ---------------------------------------------------------------------------
def scenario_fifo_execution_order_preserved() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    a3, _, _ = _make_agent_and_collaborators()
    host1, host2, host3 = (
        _StartAllSpyHost(),
        _StartAllSpyHost(),
        _StartAllSpyHost(),
    )
    scheduler = AutonomousScheduler()

    scheduler.schedule(host1, [a1], _FakeContext(), 1)
    scheduler.schedule(host2, [a2], _FakeContext(), 1)
    scheduler.schedule(host3, [a3], _FakeContext(), 1)

    scheduler.tick()

    check(
        len(host1.start_all_calls) == 1
        and len(host2.start_all_calls) == 1
        and len(host3.start_all_calls) == 1,
        "J8: all three scheduled jobs executed exactly once via tick()",
    )
    check(
        scheduler.pending_jobs() == (),
        "J8: queue is empty after a fully successful tick()",
    )


# ---------------------------------------------------------------------------
# J9 -- duplicate agents across two schedule() calls are allowed
# ---------------------------------------------------------------------------
def scenario_duplicate_agents_allowed() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()

    id1 = scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)
    id2 = scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)

    check(
        id1 != id2,
        "J9: scheduling the same agent instance twice succeeds and "
        "produces two distinct job_ids",
    )
    check(
        len(scheduler.pending_jobs()) == 2,
        "J9: both jobs sharing the same agent instance are queued",
    )


# ---------------------------------------------------------------------------
# J10 -- clear() empties the queue regardless of job_id contents
# ---------------------------------------------------------------------------
def scenario_clear_empties_queue() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()

    scheduler.schedule(_StartAllSpyHost(), [a1], _FakeContext(), 1)
    scheduler.schedule(_StartAllSpyHost(), [a2], _FakeContext(), 1)

    scheduler.clear()

    check(
        scheduler.pending_jobs() == (),
        "J10: clear() empties the queue; pending_jobs() is empty "
        "afterward",
    )


# ---------------------------------------------------------------------------
# J11 -- pause()/resume() behavior is unaffected by the job_id switch
# ---------------------------------------------------------------------------
def scenario_pause_resume_unaffected() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()

    job_id = scheduler.schedule(host, [agent], _FakeContext(), 1)
    scheduler.pause()

    result = scheduler.tick()
    check(
        result == () and len(host.start_all_calls) == 0,
        "J11: tick() while paused executes nothing",
    )
    check(
        len(scheduler.pending_jobs()) == 1
        and scheduler.pending_jobs()[0].job_id == job_id,
        "J11: the queued job_id is untouched while paused",
    )

    scheduler.resume()
    result = scheduler.tick()
    check(
        len(result) == 1 and len(host.start_all_calls) == 1,
        "J11: resuming drains the queue normally on the next tick()",
    )


# ---------------------------------------------------------------------------
# J12 -- cancelling a job_id twice raises the second time
# ---------------------------------------------------------------------------
def scenario_cancel_twice_raises_second_time() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()

    job_id = scheduler.schedule(
        _StartAllSpyHost(), [agent], _FakeContext(), 1
    )
    scheduler.cancel(job_id)

    try:
        scheduler.cancel(job_id)
        check(
            False,
            "J12: cancelling the same job_id a second time raises "
            "AutonomousSchedulerError",
        )
    except AutonomousSchedulerError:
        check(
            True,
            "J12: cancelling the same job_id a second time raises "
            "AutonomousSchedulerError",
        )


# ---------------------------------------------------------------------------
# J13 -- a cancelled job's host.start_all() is never called
# ---------------------------------------------------------------------------
def scenario_cancelled_job_host_never_called() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()

    job_id = scheduler.schedule(host, [agent], _FakeContext(), 1)
    scheduler.cancel(job_id)
    scheduler.tick()

    check(
        len(host.start_all_calls) == 0,
        "J13: a cancelled job's host.start_all() is never invoked, "
        "even after a subsequent tick()",
    )


# ---------------------------------------------------------------------------
# J14 -- AutonomousSchedulerError from cancel() is an AgentError
# ---------------------------------------------------------------------------
def scenario_cancel_error_is_agent_error_subclass() -> None:
    scheduler = AutonomousScheduler()

    try:
        scheduler.cancel("unknown-job-id")
        check(
            False,
            "J14: AutonomousSchedulerError raised by cancel() is an "
            "instance of AgentError",
        )
    except AutonomousSchedulerError as exc:
        check(
            isinstance(exc, AgentError),
            "J14: AutonomousSchedulerError raised by cancel() is an "
            "instance of AgentError",
        )


# ---------------------------------------------------------------------------
# J15 -- independent scheduler instances never share job_id/cancel() state
# ---------------------------------------------------------------------------
def scenario_instances_do_not_share_job_id_state() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    scheduler_a = AutonomousScheduler()
    scheduler_b = AutonomousScheduler()

    id_a = scheduler_a.schedule(_StartAllSpyHost(), [a1], _FakeContext(), 1)
    id_b = scheduler_b.schedule(_StartAllSpyHost(), [a2], _FakeContext(), 1)

    check(id_a != id_b, "J15: independent schedulers mint distinct job_ids")

    try:
        scheduler_b.cancel(id_a)
        check(
            False,
            "J15: cancel() on scheduler_b with scheduler_a's job_id "
            "raises AutonomousSchedulerError (no cross-instance state)",
        )
    except AutonomousSchedulerError:
        check(
            True,
            "J15: cancel() on scheduler_b with scheduler_a's job_id "
            "raises AutonomousSchedulerError (no cross-instance state)",
        )

    check(
        len(scheduler_a.pending_jobs()) == 1
        and len(scheduler_b.pending_jobs()) == 1,
        "J15: both schedulers' queues remain untouched after the "
        "cross-instance cancel() attempt",
    )


# ---------------------------------------------------------------------------
# J16 -- SchedulerJob instances are immutable (frozen dataclass)
# ---------------------------------------------------------------------------
def scenario_scheduler_job_is_immutable() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()
    scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)

    entry = scheduler.pending_jobs()[0]

    try:
        entry.iterations = 99  # type: ignore[misc]
        check(
            False,
            "J16: mutating a SchedulerJob field raises (frozen dataclass)",
        )
    except (AttributeError, TypeError):
        check(
            True,
            "J16: mutating a SchedulerJob field raises (frozen dataclass)",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_schedule_returns_str_job_id,
        scenario_job_ids_are_unique,
        scenario_pending_jobs_expose_matching_job_ids,
        scenario_pending_jobs_entries_have_correct_fields,
        scenario_cancel_removes_exactly_targeted_job,
        scenario_cancel_unknown_job_id_raises,
        scenario_cancel_preserves_fifo_order,
        scenario_fifo_execution_order_preserved,
        scenario_duplicate_agents_allowed,
        scenario_clear_empties_queue,
        scenario_pause_resume_unaffected,
        scenario_cancel_twice_raises_second_time,
        scenario_cancelled_job_host_never_called,
        scenario_cancel_error_is_agent_error_subclass,
        scenario_instances_do_not_share_job_id_state,
        scenario_scheduler_job_is_immutable,
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
    print(f"PHASE 3 SPRINT 21 JOB ID RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())