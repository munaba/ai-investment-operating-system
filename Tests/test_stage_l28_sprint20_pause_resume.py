"""
Phase 3 Sprint 20 proof suite -- AutonomousScheduler pause/resume
lifecycle (``pause()`` / ``resume()``).

Scope: dedicated regression suite for the two new methods added to
``Orchestration.autonomous_scheduler.AutonomousScheduler`` in Sprint
20. ``schedule()``, ``tick()`` (active-path behavior), ``cancel()``,
``clear()``, and ``pending_jobs()`` themselves are unmodified and
already covered by ``Tests/test_stage_l28_sprint17_scheduler.py``,
``Tests/test_stage_l28_sprint18_queue_management.py``, and
``Tests/test_stage_l28_sprint19_cancel.py`` -- none of that is
re-verified here beyond what pause/resume itself needs.

No real ``RuntimeAnalysisPipeline`` and no real ``GoalPlanner`` are
built here -- plain fake objects stand in for both, exactly like the
Sprint 17/18/19 suites. A real ``AutonomousHost`` is used throughout.

No threading, no asyncio, no timers, no sleep, no persistence -- all
explicitly out of scope for Sprint 20 and never exercised or required
by this suite.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Invariant coverage:
    P1  -- pause() returns None.
    P2  -- resume() returns None.
    P3  -- pause() is idempotent: calling it repeatedly raises
           nothing and leaves the scheduler paused.
    P4  -- resume() is idempotent: calling it repeatedly (including
           on an already-active scheduler) raises nothing.
    P5  -- tick() while paused executes nothing (no host.start_all()
           calls) and returns an empty tuple, even with jobs queued.
    P6  -- tick() while paused leaves the queue completely untouched
           (verified via pending_jobs() before/after).
    P7  -- schedule() still works normally while paused -- jobs may
           be queued during a pause.
    P8  -- after resume(), tick() drains the queue exactly as before
           (including jobs queued while paused), in FIFO order.
    P9  -- cancel() still works normally while paused.
    P10 -- clear() still works normally while paused.
    P11 -- pending_jobs() still works normally while paused.
    P12 -- a fresh AutonomousScheduler starts in the active (not
           paused) state -- tick() runs jobs by default.
    P13 -- pause() then resume() then pause() again cycles correctly
           (tick() blocked, then allowed, then blocked again).
    P14 -- two independent AutonomousScheduler instances never share
           pause/resume state.
    P15 -- pausing mid-sequence (schedule, schedule, pause, tick,
           resume, tick) only blocks the tick() calls made while
           paused; the deferred jobs still run correctly on the next
           active tick(), with unchanged agents/context/iterations.
    P16 -- pause() does not affect a tick() already returned from (no
           retroactive effect on completed work).
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
from Orchestration.autonomous_host import AutonomousHost
from Orchestration.autonomous_scheduler import AutonomousScheduler, SchedulerJob

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


# ---------------------------------------------------------------------------
# P1 -- pause() returns None
# ---------------------------------------------------------------------------
def scenario_pause_returns_none() -> None:
    scheduler = AutonomousScheduler()
    result = scheduler.pause()
    check(result is None, "P1: pause() returns None")


# ---------------------------------------------------------------------------
# P2 -- resume() returns None
# ---------------------------------------------------------------------------
def scenario_resume_returns_none() -> None:
    scheduler = AutonomousScheduler()
    scheduler.pause()
    result = scheduler.resume()
    check(result is None, "P2: resume() returns None")


# ---------------------------------------------------------------------------
# P3 -- pause() is idempotent
# ---------------------------------------------------------------------------
def scenario_pause_is_idempotent() -> None:
    scheduler = AutonomousScheduler()
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler.schedule(spy_host, [agent], _FakeContext(), 1)

    for _ in range(3):
        result = scheduler.pause()
        check(result is None, "P3: repeated pause() calls each return None")

    tick_result = scheduler.tick()
    check(
        tick_result == () and len(spy_host.start_all_calls) == 0,
        "P3: after repeated pause() calls the scheduler is still paused "
        "(tick() executes nothing)",
    )


# ---------------------------------------------------------------------------
# P4 -- resume() is idempotent
# ---------------------------------------------------------------------------
def scenario_resume_is_idempotent() -> None:
    scheduler = AutonomousScheduler()

    for _ in range(3):
        result = scheduler.resume()
        check(
            result is None,
            "P4: repeated resume() calls on an already-active scheduler "
            "each return None and raise nothing",
        )

    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler.schedule(spy_host, [agent], _FakeContext(), 1)
    scheduler.pause()
    for _ in range(3):
        scheduler.resume()

    tick_result = scheduler.tick()
    check(
        len(tick_result) == 1 and len(spy_host.start_all_calls) == 1,
        "P4: repeated resume() calls after a pause() leave the scheduler "
        "active (tick() runs normally)",
    )


# ---------------------------------------------------------------------------
# P5 -- tick() while paused executes nothing and returns an empty tuple
# ---------------------------------------------------------------------------
def scenario_tick_while_paused_executes_nothing() -> None:
    scheduler = AutonomousScheduler()
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host1, host2 = _StartAllSpyHost(), _StartAllSpyHost()

    scheduler.schedule(host1, [a1], _FakeContext(), 1)
    scheduler.schedule(host2, [a2], _FakeContext(), 1)
    scheduler.pause()

    result = scheduler.tick()

    check(result == (), "P5: tick() while paused returns an empty tuple")
    check(
        len(host1.start_all_calls) == 0 and len(host2.start_all_calls) == 0,
        "P5: tick() while paused calls no job's host.start_all()",
    )
    check(
        a1.status is AutonomousAgentStatus.IDLE
        and a2.status is AutonomousAgentStatus.IDLE,
        "P5: tick() while paused never touches any queued agent's status",
    )


# ---------------------------------------------------------------------------
# P6 -- tick() while paused leaves the queue completely untouched
# ---------------------------------------------------------------------------
def scenario_tick_while_paused_leaves_queue_untouched() -> None:
    scheduler = AutonomousScheduler()
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host1, host2 = _StartAllSpyHost(), _StartAllSpyHost()
    ctx1, ctx2 = _FakeContext(), _FakeContext()

    scheduler.schedule(host1, [a1], ctx1, 1)
    scheduler.schedule(host2, [a2], ctx2, 2)
    scheduler.pause()

    before = scheduler.pending_jobs()
    scheduler.tick()
    scheduler.tick()  # calling it twice should still change nothing
    after = scheduler.pending_jobs()

    check(
        before == after
        and len(after) == 2
        and after[0].host is host1 and after[0].agents == (a1,)
        and after[0].context is ctx1 and after[0].iterations == 1
        and after[1].host is host2 and after[1].agents == (a2,)
        and after[1].context is ctx2 and after[1].iterations == 2,
        "P6: repeated tick() calls while paused leave the queue exactly "
        "as it was, in the same FIFO order",
    )


# ---------------------------------------------------------------------------
# P7 -- schedule() still works normally while paused
# ---------------------------------------------------------------------------
def scenario_schedule_works_while_paused() -> None:
    scheduler = AutonomousScheduler()
    scheduler.pause()

    agent, _, _ = _make_agent_and_collaborators()
    scheduler.schedule(_StartAllSpyHost(), [agent], _FakeContext(), 1)

    check(
        len(scheduler.pending_jobs()) == 1,
        "P7: schedule() while paused queues the job normally",
    )


# ---------------------------------------------------------------------------
# P8 -- after resume(), tick() drains the queue exactly as before
# ---------------------------------------------------------------------------
def scenario_resume_then_tick_drains_normally() -> None:
    scheduler = AutonomousScheduler()
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host1, host2 = _StartAllSpyHost(), _StartAllSpyHost()
    ctx1, ctx2 = _FakeContext(), _FakeContext()

    scheduler.schedule(host1, [a1], ctx1, 1)
    scheduler.pause()
    scheduler.schedule(host2, [a2], ctx2, 2)  # queued while paused

    blocked_result = scheduler.tick()
    check(blocked_result == (), "P8: tick() while paused returns nothing")

    scheduler.resume()
    result = scheduler.tick()

    check(
        len(result) == 2,
        "P8: tick() after resume() runs every job that had accumulated, "
        "including the one queued while paused",
    )
    check(
        host1.start_all_calls == [((a1,), ctx1, 1)]
        and host2.start_all_calls == [((a2,), ctx2, 2)],
        "P8: each job ran with its own original agents/context/iterations, "
        "in FIFO order",
    )
    check(
        scheduler.pending_jobs() == (),
        "P8: the queue is empty after the post-resume tick() drains it",
    )


# ---------------------------------------------------------------------------
# P9 -- cancel() still works normally while paused
# ---------------------------------------------------------------------------
def scenario_cancel_works_while_paused() -> None:
    scheduler = AutonomousScheduler()
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host1, host2 = _StartAllSpyHost(), _StartAllSpyHost()
    ctx1, ctx2 = _FakeContext(), _FakeContext()

    job_id_1 = scheduler.schedule(host1, [a1], ctx1, 1)
    scheduler.schedule(host2, [a2], ctx2, 1)
    scheduler.pause()

    scheduler.cancel(job_id_1)

    remaining = scheduler.pending_jobs()
    check(
        len(remaining) == 1
        and remaining[0].host is host2
        and remaining[0].agents == (a2,)
        and remaining[0].context is ctx2
        and remaining[0].iterations == 1,
        "P9: cancel() while paused still removes the targeted job "
        "normally",
    )

    scheduler.resume()
    result = scheduler.tick()
    check(
        len(result) == 1 and len(host1.start_all_calls) == 0,
        "P9: the job cancelled while paused never runs, even after "
        "resume()",
    )


# ---------------------------------------------------------------------------
# P10 -- clear() still works normally while paused
# ---------------------------------------------------------------------------
def scenario_clear_works_while_paused() -> None:
    scheduler = AutonomousScheduler()
    a1, _, _ = _make_agent_and_collaborators()
    host1 = _StartAllSpyHost()
    scheduler.schedule(host1, [a1], _FakeContext(), 1)
    scheduler.pause()

    scheduler.clear()

    check(
        scheduler.pending_jobs() == (),
        "P10: clear() while paused empties the queue normally",
    )

    scheduler.resume()
    result = scheduler.tick()
    check(
        result == () and len(host1.start_all_calls) == 0,
        "P10: nothing runs after resume() since clear() removed the only "
        "queued job while paused",
    )


# ---------------------------------------------------------------------------
# P11 -- pending_jobs() still works normally while paused
# ---------------------------------------------------------------------------
def scenario_pending_jobs_works_while_paused() -> None:
    scheduler = AutonomousScheduler()
    a1, _, _ = _make_agent_and_collaborators()
    host1 = _StartAllSpyHost()
    ctx1 = _FakeContext()
    scheduler.schedule(host1, [a1], ctx1, 1)
    scheduler.pause()

    pending = scheduler.pending_jobs()
    check(
        len(pending) == 1
        and pending[0].host is host1
        and pending[0].agents == (a1,)
        and pending[0].context is ctx1
        and pending[0].iterations == 1
        and isinstance(pending[0], SchedulerJob),
        "P11: pending_jobs() while paused reports the queue exactly as "
        "it would when active",
    )


# ---------------------------------------------------------------------------
# P12 -- a fresh scheduler starts active (not paused)
# ---------------------------------------------------------------------------
def scenario_fresh_scheduler_starts_active() -> None:
    scheduler = AutonomousScheduler()
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler.schedule(spy_host, [agent], _FakeContext(), 1)

    result = scheduler.tick()

    check(
        len(result) == 1 and len(spy_host.start_all_calls) == 1,
        "P12: a brand-new AutonomousScheduler starts active -- tick() "
        "runs queued jobs by default without calling pause()/resume()",
    )


# ---------------------------------------------------------------------------
# P13 -- pause() -> resume() -> pause() cycles correctly
# ---------------------------------------------------------------------------
def scenario_pause_resume_pause_cycle() -> None:
    scheduler = AutonomousScheduler()
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    a3, _, _ = _make_agent_and_collaborators()
    host1, host2, host3 = (
        _StartAllSpyHost(),
        _StartAllSpyHost(),
        _StartAllSpyHost(),
    )

    scheduler.schedule(host1, [a1], _FakeContext(), 1)
    scheduler.pause()
    check(
        scheduler.tick() == (),
        "P13: first pause() blocks tick()",
    )

    scheduler.resume()
    scheduler.schedule(host2, [a2], _FakeContext(), 1)
    result = scheduler.tick()
    check(
        len(result) == 2,
        "P13: resume() allows tick() to run everything accumulated so far",
    )

    scheduler.pause()
    scheduler.schedule(host3, [a3], _FakeContext(), 1)
    check(
        scheduler.tick() == () and len(host3.start_all_calls) == 0,
        "P13: pausing again blocks tick() again for newly queued work",
    )


# ---------------------------------------------------------------------------
# P14 -- independent scheduler instances never share pause/resume state
# ---------------------------------------------------------------------------
def scenario_instances_do_not_share_pause_state() -> None:
    scheduler_a = AutonomousScheduler()
    scheduler_b = AutonomousScheduler()

    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host_a, host_b = _StartAllSpyHost(), _StartAllSpyHost()

    scheduler_a.schedule(host_a, [a1], _FakeContext(), 1)
    scheduler_b.schedule(host_b, [a2], _FakeContext(), 1)

    scheduler_a.pause()

    result_a = scheduler_a.tick()
    result_b = scheduler_b.tick()

    check(
        result_a == () and len(host_a.start_all_calls) == 0,
        "P14: pausing scheduler_a blocks only scheduler_a's tick()",
    )
    check(
        len(result_b) == 1 and len(host_b.start_all_calls) == 1,
        "P14: scheduler_b remains active and unaffected by scheduler_a's "
        "pause()",
    )


# ---------------------------------------------------------------------------
# P15 -- pausing mid-sequence only blocks the ticks made while paused
# ---------------------------------------------------------------------------
def scenario_pause_mid_sequence_only_blocks_paused_ticks() -> None:
    scheduler = AutonomousScheduler()
    a1, _, _ = _make_agent_and_collaborators()
    a2, _, _ = _make_agent_and_collaborators()
    host1, host2 = _StartAllSpyHost(), _StartAllSpyHost()
    ctx1, ctx2 = _FakeContext(), _FakeContext()

    scheduler.schedule(host1, [a1], ctx1, 1)
    scheduler.schedule(host2, [a2], ctx2, 3)

    scheduler.pause()
    blocked = scheduler.tick()
    check(
        blocked == ()
        and len(host1.start_all_calls) == 0
        and len(host2.start_all_calls) == 0,
        "P15: the tick() made while paused runs neither deferred job",
    )

    scheduler.resume()
    result = scheduler.tick()

    check(
        len(result) == 2,
        "P15: the following active tick() runs both deferred jobs",
    )
    check(
        host1.start_all_calls == [((a1,), ctx1, 1)]
        and host2.start_all_calls == [((a2,), ctx2, 3)],
        "P15: each deferred job ran with its original, unchanged "
        "agents/context/iterations",
    )


# ---------------------------------------------------------------------------
# P16 -- pause() has no retroactive effect on an already-returned tick()
# ---------------------------------------------------------------------------
def scenario_pause_after_tick_has_no_retroactive_effect() -> None:
    scheduler = AutonomousScheduler()
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    scheduler.schedule(spy_host, [agent], _FakeContext(), 1)

    result = scheduler.tick()
    check(len(result) == 1, "P16: tick() ran the job before any pause()")

    scheduler.pause()

    check(
        len(spy_host.start_all_calls) == 1,
        "P16: pause() called after a completed tick() does not undo or "
        "re-trigger the already-finished work",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_pause_returns_none,
        scenario_resume_returns_none,
        scenario_pause_is_idempotent,
        scenario_resume_is_idempotent,
        scenario_tick_while_paused_executes_nothing,
        scenario_tick_while_paused_leaves_queue_untouched,
        scenario_schedule_works_while_paused,
        scenario_resume_then_tick_drains_normally,
        scenario_cancel_works_while_paused,
        scenario_clear_works_while_paused,
        scenario_pending_jobs_works_while_paused,
        scenario_fresh_scheduler_starts_active,
        scenario_pause_resume_pause_cycle,
        scenario_instances_do_not_share_pause_state,
        scenario_pause_mid_sequence_only_blocks_paused_ticks,
        scenario_pause_after_tick_has_no_retroactive_effect,
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
    print(f"PHASE 3 SPRINT 20 PAUSE/RESUME RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())