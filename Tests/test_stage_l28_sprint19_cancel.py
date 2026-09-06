"""
Phase 3 Sprint 19 proof suite -- AutonomousScheduler queued-job
cancellation (``cancel()``).

Scope: dedicated regression suite for the one new method added to
``Orchestration.autonomous_scheduler.AutonomousScheduler`` in Sprint
19. ``schedule()``, ``tick()``, ``pending_jobs()``, and ``clear()``
themselves are unmodified and already covered by
``Tests/test_stage_l28_sprint17_scheduler.py`` and
``Tests/test_stage_l28_sprint18_queue_management.py`` -- none of that
is re-verified here beyond what ``cancel()`` itself needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, exactly like the
Sprint 17/18 suites. A real ``AutonomousHost`` is used throughout.

No threading, no asyncio, no timers, no sleep, no persistence -- all
explicitly out of scope for Sprint 19 and never exercised or required
by this suite.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Invariant coverage:
    C1  -- cancel() on an empty queue raises AutonomousSchedulerError.
    C2  -- cancel() with a non-int job_index raises
           AutonomousSchedulerError (including bool, which is
           rejected even though bool is a subclass of int).
    C3  -- cancel() with a negative job_index raises
           AutonomousSchedulerError (no negative indexing supported).
    C4  -- cancel() with an out-of-range (too large) job_index raises
           AutonomousSchedulerError.
    C5  -- cancel() removes exactly the job at the given index and no
           other, verified via pending_jobs() before/after.
    C6  -- cancel() preserves FIFO order of the remaining jobs.
    C7  -- cancel() returns None on success.
    C8  -- cancel() never calls any job's host.start_all() and never
           touches any agent's status.
    C9  -- cancel(0) on a single-job queue empties the queue; a
           following tick() executes nothing and returns an empty
           tuple.
    C10 -- cancelling the last valid index (len - 1) works correctly.
    C11 -- a failed cancel() call (invalid index) leaves the queue
           completely untouched.
    C12 -- calling cancel() repeatedly for the same now-invalid index
           raises each time and never double-removes.
    C13 -- schedule() after a cancel() works normally and the new job
           runs correctly on tick().
    C14 -- two independent AutonomousScheduler instances never share
           cancel() state.
    C15 -- AutonomousSchedulerError raised by cancel() is an instance
           of the shared AgentError base (consistent with schedule()).
    C16 -- cancel() does not affect jobs already removed by a prior
           tick() -- cancelling among the jobs left behind after a
           partial drain only ever touches what's still queued.
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
# C1 -- cancel() on an empty queue raises
# ---------------------------------------------------------------------------
def scenario_cancel_on_empty_queue_raises() -> None:
    scheduler = AutonomousScheduler()

    try:
        scheduler.cancel("any-job-id")
        check(False, "C1: cancel() on an empty queue raises AutonomousSchedulerError")
    except AutonomousSchedulerError:
        check(True, "C1: cancel() on an empty queue raises AutonomousSchedulerError")


# ---------------------------------------------------------------------------
# C2 -- cancel() with a malformed/non-matching job_id raises (including
# values of the old index type, which are no longer valid identifiers)
# ---------------------------------------------------------------------------
def scenario_cancel_non_int_index_raises() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()
    scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)

    for bad_job_id in ("0", 1.0, None, [0], True, False):
        try:
            scheduler.cancel(bad_job_id)
            check(
                False,
                f"C2: cancel({bad_job_id!r}) raises AutonomousSchedulerError "
                f"for a job_id that matches no queued job",
            )
        except AutonomousSchedulerError:
            check(
                True,
                f"C2: cancel({bad_job_id!r}) raises AutonomousSchedulerError "
                f"for a job_id that matches no queued job",
            )

    check(
        len(scheduler.pending_jobs()) == 1,
        "C2: rejected non-matching cancel() calls leave the queue untouched",
    )


# ---------------------------------------------------------------------------
# C3 -- cancel() with a job_id that never matches any queued job raises
# (old "negative index" case, adapted to the job_id API)
# ---------------------------------------------------------------------------
def scenario_cancel_negative_index_raises() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()
    scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)

    try:
        scheduler.cancel("-1")
        check(
            False,
            "C3: cancel('-1') raises AutonomousSchedulerError (no such "
            "job_id was ever issued)",
        )
    except AutonomousSchedulerError:
        check(
            True,
            "C3: cancel('-1') raises AutonomousSchedulerError (no such "
            "job_id was ever issued)",
        )

    check(
        len(scheduler.pending_jobs()) == 1,
        "C3: a rejected unknown-job_id cancel() call leaves the queue "
        "untouched",
    )


# ---------------------------------------------------------------------------
# C4 -- cancel() with an unknown job_id raises (old "out-of-range index"
# case, adapted to the job_id API)
# ---------------------------------------------------------------------------
def scenario_cancel_out_of_range_index_raises() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()
    scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)

    for bad_job_id in ("job-1", "job-2", "job-99"):
        try:
            scheduler.cancel(bad_job_id)
            check(
                False,
                f"C4: cancel({bad_job_id!r}) raises AutonomousSchedulerError "
                f"for an unknown job_id on a 1-job queue",
            )
        except AutonomousSchedulerError:
            check(
                True,
                f"C4: cancel({bad_job_id!r}) raises AutonomousSchedulerError "
                f"for an unknown job_id on a 1-job queue",
            )

    check(
        len(scheduler.pending_jobs()) == 1,
        "C4: rejected unknown-job_id cancel() calls leave the queue "
        "untouched",
    )


# ---------------------------------------------------------------------------
# C5 -- cancel() removes exactly the targeted job and no other
# ---------------------------------------------------------------------------
def scenario_cancel_removes_exactly_targeted_job() -> None:
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

    id1 = scheduler.schedule(host1, [a1], ctx1, 1)
    id2 = scheduler.schedule(host2, [a2], ctx2, 2)
    id3 = scheduler.schedule(host3, [a3], ctx3, 3)

    scheduler.cancel(id2)  # remove the middle job (host2/a2)

    remaining = scheduler.pending_jobs()
    check(
        len(remaining) == 2
        and remaining[0].job_id == id1
        and remaining[0].host is host1
        and remaining[0].agents == (a1,)
        and remaining[0].context is ctx1
        and remaining[0].iterations == 1
        and remaining[1].job_id == id3
        and remaining[1].host is host3
        and remaining[1].agents == (a3,)
        and remaining[1].context is ctx3
        and remaining[1].iterations == 3,
        "C5: cancel(job_id) removes exactly the middle job and leaves "
        "the other two untouched",
    )


# ---------------------------------------------------------------------------
# C6 -- cancel() preserves FIFO order of the remaining jobs
# ---------------------------------------------------------------------------
def scenario_cancel_preserves_fifo_order() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    a3, _, _ = _make_agent_and_collaborators()
    a4, _, _ = _make_agent_and_collaborators()
    hosts = [_StartAllSpyHost() for _ in range(4)]
    scheduler = AutonomousScheduler()
    ctxs = [_FakeContext() for _ in range(4)]
    agents = [a1, a2, a3, a4]

    ids = []
    for host, agent, ctx in zip(hosts, agents, ctxs):
        ids.append(scheduler.schedule(host, [agent], ctx, 1))

    scheduler.cancel(ids[0])  # remove the first job

    remaining = scheduler.pending_jobs()
    check(
        len(remaining) == 3
        and [job.job_id for job in remaining] == ids[1:]
        and remaining[0].host is hosts[1] and remaining[0].agents == (a2,)
        and remaining[1].host is hosts[2] and remaining[1].agents == (a3,)
        and remaining[2].host is hosts[3] and remaining[2].agents == (a4,),
        "C6: cancel(job_id) shifts the remaining jobs forward while "
        "preserving their original relative FIFO order",
    )

    result = scheduler.tick()
    check(
        len(result) == 3,
        "C6: tick() after cancel() still runs the remaining jobs in the "
        "preserved order",
    )
    check(
        hosts[1].start_all_calls[0][0] == (a2,)
        and hosts[2].start_all_calls[0][0] == (a3,)
        and hosts[3].start_all_calls[0][0] == (a4,),
        "C6: each surviving job ran with its own original agents",
    )


# ---------------------------------------------------------------------------
# C7 -- cancel() returns None on success
# ---------------------------------------------------------------------------
def scenario_cancel_returns_none() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()
    job_id = scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)

    result = scheduler.cancel(job_id)

    check(result is None, "C7: cancel() returns None on success")


# ---------------------------------------------------------------------------
# C8 -- cancel() never executes anything
# ---------------------------------------------------------------------------
def scenario_cancel_never_executes_anything() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()

    job_id = scheduler.schedule(spy_host, [agent], _FakeContext(), 1)
    scheduler.cancel(job_id)

    check(
        len(spy_host.start_all_calls) == 0,
        "C8: cancel() never calls the cancelled job's host.start_all()",
    )
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "C8: cancel() never touches the cancelled job's agent status "
        "(stays IDLE)",
    )


# ---------------------------------------------------------------------------
# C9 -- cancel(0) on a single-job queue empties it
# ---------------------------------------------------------------------------
def scenario_cancel_single_job_queue_then_tick_is_empty() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler = AutonomousScheduler()
    job_id = scheduler.schedule(spy_host, [agent], _FakeContext(), 1)

    scheduler.cancel(job_id)

    check(
        scheduler.pending_jobs() == (),
        "C9: cancel(0) on a single-job queue leaves it empty",
    )
    result = scheduler.tick()
    check(
        result == (),
        "C9: tick() after cancelling the only queued job executes "
        "nothing and returns an empty tuple",
    )
    check(
        len(spy_host.start_all_calls) == 0,
        "C9: the cancelled job's host.start_all() was never called by "
        "the following tick()",
    )


# ---------------------------------------------------------------------------
# C10 -- cancelling the last valid index (len - 1) works correctly
# ---------------------------------------------------------------------------
def scenario_cancel_last_index_works() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host1, host2 = _StartAllSpyHost(), _StartAllSpyHost()
    scheduler = AutonomousScheduler()
    ctx1, ctx2 = _FakeContext(), _FakeContext()

    id1 = scheduler.schedule(host1, [a1], ctx1, 1)
    id2 = scheduler.schedule(host2, [a2], ctx2, 1)

    scheduler.cancel(id2)  # last scheduled job

    remaining = scheduler.pending_jobs()
    check(
        len(remaining) == 1
        and remaining[0].job_id == id1
        and remaining[0].host is host1
        and remaining[0].agents == (a1,)
        and remaining[0].context is ctx1
        and remaining[0].iterations == 1,
        "C10: cancelling the last-scheduled job's job_id removes only "
        "that job",
    )


# ---------------------------------------------------------------------------
# C11 -- a failed cancel() call leaves the queue completely untouched
# ---------------------------------------------------------------------------
def scenario_failed_cancel_leaves_queue_untouched() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host1, host2 = _StartAllSpyHost(), _StartAllSpyHost()
    scheduler = AutonomousScheduler()
    ctx1, ctx2 = _FakeContext(), _FakeContext()

    scheduler.schedule(host1, [a1], ctx1, 1)
    scheduler.schedule(host2, [a2], ctx2, 1)

    before = scheduler.pending_jobs()

    try:
        scheduler.cancel("unknown-job-id")
    except AutonomousSchedulerError:
        pass

    after = scheduler.pending_jobs()
    check(
        before == after,
        "C11: an unknown-job_id cancel() call leaves the queue exactly "
        "as it was before the call",
    )


# ---------------------------------------------------------------------------
# C12 -- repeated cancel() at a now-invalid index raises each time
# ---------------------------------------------------------------------------
def scenario_repeated_cancel_same_index_raises_each_time() -> None:
    agent, _, _ = _make_agent_and_collaborators()
    scheduler = AutonomousScheduler()
    job_id = scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)

    scheduler.cancel(job_id)  # queue now empty

    for _ in range(3):
        try:
            scheduler.cancel(job_id)
            check(
                False,
                "C12: repeated cancel(job_id) on an already-removed job_id "
                "raises AutonomousSchedulerError every time",
            )
        except AutonomousSchedulerError:
            check(
                True,
                "C12: repeated cancel(job_id) on an already-removed job_id "
                "raises AutonomousSchedulerError every time",
            )


# ---------------------------------------------------------------------------
# C13 -- schedule() after cancel() works normally
# ---------------------------------------------------------------------------
def scenario_schedule_after_cancel_works_normally() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host1, host2 = _StartAllSpyHost(), _StartAllSpyHost()
    scheduler = AutonomousScheduler()

    job_id = scheduler.schedule(host1, [a1], _FakeContext(), 1)
    scheduler.cancel(job_id)

    scheduler.schedule(host2, [a2], _FakeContext(), 2)
    result = scheduler.tick()

    check(
        len(result) == 1,
        "C13: schedule() after cancel() queues normally and runs on the "
        "next tick()",
    )
    check(
        len(host2.start_all_calls) == 1 and len(host1.start_all_calls) == 0,
        "C13: only the job scheduled after cancel() ran; the cancelled "
        "job's host was never called",
    )


# ---------------------------------------------------------------------------
# C14 -- independent scheduler instances never share cancel() state
# ---------------------------------------------------------------------------
def scenario_instances_do_not_share_cancel_state() -> None:
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    scheduler_a = AutonomousScheduler()
    scheduler_b = AutonomousScheduler()

    id_a = scheduler_a.schedule(_StartAllSpyHost(), [a1], _FakeContext(), 1)
    scheduler_b.schedule(_StartAllSpyHost(), [a2], _FakeContext(), 1)

    scheduler_a.cancel(id_a)

    check(
        scheduler_a.pending_jobs() == (),
        "C14: cancel() on scheduler_a empties only scheduler_a's queue",
    )
    check(
        len(scheduler_b.pending_jobs()) == 1,
        "C14: scheduler_b's queue is unaffected by scheduler_a's cancel()",
    )


# ---------------------------------------------------------------------------
# C15 -- AutonomousSchedulerError from cancel() is an AgentError
# ---------------------------------------------------------------------------
def scenario_cancel_error_is_agent_error_subclass() -> None:
    scheduler = AutonomousScheduler()

    try:
        scheduler.cancel("unknown-job-id")
        check(
            False,
            "C15: AutonomousSchedulerError raised by cancel() is an "
            "instance of AgentError",
        )
    except AutonomousSchedulerError as exc:
        check(
            isinstance(exc, AgentError),
            "C15: AutonomousSchedulerError raised by cancel() is an "
            "instance of AgentError",
        )


# ---------------------------------------------------------------------------
# C16 -- cancel() among jobs left behind after a partial tick() drain
# ---------------------------------------------------------------------------
def scenario_cancel_after_partial_drain_only_touches_remaining() -> None:
    good_agent, _, _ = _make_agent_and_collaborators()
    good_host = _StartAllSpyHost()

    failing_host = _FailingHost()
    failing_agent, _, _ = _make_agent_and_collaborators()

    survivor_agent, _, _ = _make_agent_and_collaborators()
    survivor_host = _StartAllSpyHost()

    doomed_agent, _, _ = _make_agent_and_collaborators()
    doomed_host = _StartAllSpyHost()

    scheduler = AutonomousScheduler()
    ctx_good, ctx_failing, ctx_survivor, ctx_doomed = (
        _FakeContext(),
        _FakeContext(),
        _FakeContext(),
        _FakeContext(),
    )
    scheduler.schedule(good_host, [good_agent], ctx_good, 1)
    scheduler.schedule(failing_host, [failing_agent], ctx_failing, 1)
    survivor_id = scheduler.schedule(
        survivor_host, [survivor_agent], ctx_survivor, 1
    )
    doomed_id = scheduler.schedule(doomed_host, [doomed_agent], ctx_doomed, 1)

    try:
        scheduler.tick()
    except AutonomousHostError:
        pass

    # Two jobs remain queued: survivor, then doomed.
    scheduler.cancel(doomed_id)  # remove "doomed"

    remaining = scheduler.pending_jobs()
    check(
        len(remaining) == 1
        and remaining[0].job_id == survivor_id
        and remaining[0].host is survivor_host
        and remaining[0].agents == (survivor_agent,)
        and remaining[0].context is ctx_survivor
        and remaining[0].iterations == 1,
        "C16: cancel() after a partial tick() drain removes only the "
        "targeted job among what's left, leaving the other survivor "
        "queued",
    )
    check(
        len(doomed_host.start_all_calls) == 0,
        "C16: the cancelled job's host.start_all() was never called",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_cancel_on_empty_queue_raises,
        scenario_cancel_non_int_index_raises,
        scenario_cancel_negative_index_raises,
        scenario_cancel_out_of_range_index_raises,
        scenario_cancel_removes_exactly_targeted_job,
        scenario_cancel_preserves_fifo_order,
        scenario_cancel_returns_none,
        scenario_cancel_never_executes_anything,
        scenario_cancel_single_job_queue_then_tick_is_empty,
        scenario_cancel_last_index_works,
        scenario_failed_cancel_leaves_queue_untouched,
        scenario_repeated_cancel_same_index_raises_each_time,
        scenario_schedule_after_cancel_works_normally,
        scenario_instances_do_not_share_cancel_state,
        scenario_cancel_error_is_agent_error_subclass,
        scenario_cancel_after_partial_drain_only_touches_remaining,
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
    print(f"PHASE 3 SPRINT 19 CANCEL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())