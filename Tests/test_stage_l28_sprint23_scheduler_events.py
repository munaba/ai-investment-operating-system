"""
Phase 3 Sprint 23 proof suite -- AutonomousScheduler -> EventBus
integration.

Scope: dedicated regression suite for
``Orchestration.autonomous_scheduler.AutonomousScheduler`` only, as
wired to a real ``Orchestration.event_bus.EventBus`` in this Sprint.
``EventBus`` itself is unmodified and already covered by its own
dedicated suite (``Tests/test_stage_l28_sprint22_event_bus.py``);
``AutonomousHost``/``AutonomousAgent`` are unmodified and covered by
their own Sprint suites -- none of that is re-verified here beyond
what the Scheduler-EventBus wiring itself needs. Prior Scheduler
behavior (Sprints 17-21) is re-proven here only insofar as it must
remain byte-for-byte unchanged now that publishing has been added;
this is not a re-run of those suites.

A real ``EventBus`` and a real ``AutonomousHost`` are used throughout.
A "recording" subscriber (a plain list-appending callable) is
subscribed to every ``scheduler.*`` event name up front, and a thin
spy host is used in a couple of scenarios purely to observe/force
``start_all()`` behavior without changing it.

No threading, no asyncio, no timers, no sleep, no cron, no daemon, no
background worker, no persistence, no logging, no retries -- all
explicitly out of scope for Sprint 23 and never exercised or required
by this suite.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x / Sprint 1x-2x proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    E1  -- (Sprint 23.1) a None/omitted event_bus auto-creates a
           fresh, independent EventBus rather than raising; no two
           default-constructed schedulers ever share one.
    E2  -- constructor stores the given event_bus as self._event_bus
           and otherwise behaves exactly as before (empty queue,
           unpaused).
    E3  -- schedule() publishes exactly one scheduler.job_scheduled
           event, with the correct job_id/iterations payload, after
           the job is queued.
    E4  -- a rejected schedule() call (invalid input) publishes
           nothing.
    E5  -- tick() on one successful job publishes job_started then
           job_finished, in that order, each exactly once, with the
           correct job_id payload -- and no job_failed.
    E6  -- tick() on a failing job publishes job_started then
           job_failed (never job_finished), the original exception is
           re-raised unchanged, and job_failed is published before
           the exception propagates out of tick().
    E7  -- multiple queued jobs: tick() publishes job_started/
           job_finished pairs in strict FIFO order, matching the
           order the jobs were scheduled -- one pair per job, no
           duplicates.
    E8  -- cancel() publishes exactly one scheduler.job_cancelled
           event with the correct job_id, after the job is removed;
           a cancelled job is never started/finished by a later
           tick().
    E9  -- cancel() on an unknown job_id raises (unchanged behavior)
           and publishes nothing.
    E10 -- clear() publishes exactly one scheduler.queue_cleared
           event (empty payload); cleared jobs never fire job_started.
    E11 -- pause() publishes exactly one scheduler.paused event
           (empty payload); resume() publishes exactly one
           scheduler.resumed event (empty payload).
    E12 -- tick() while paused publishes nothing at all (no
           job_started/job_finished/job_failed) and returns an empty
           tuple, exactly as before.
    E13 -- publishing never changes Scheduler behavior: FIFO order,
           return values, and queue contents are identical to the
           pre-Sprint-23 (no-subscriber) case, with or without any
           subscribers registered.
    E14 -- every event this Scheduler ever publishes is sourced as
           "AutonomousScheduler".
    E15 -- across a full multi-call scenario (schedule x N, tick,
           cancel, clear, pause, resume), every event fires exactly
           once per triggering call -- no duplicates, no missing
           events, correct total count.
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
from Orchestration.event_bus import Event, EventBus, EventBusError

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

_SCHEDULER_EVENT_NAMES = (
    "scheduler.job_scheduled",
    "scheduler.job_cancelled",
    "scheduler.queue_cleared",
    "scheduler.paused",
    "scheduler.resumed",
    "scheduler.job_started",
    "scheduler.job_finished",
    "scheduler.job_failed",
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
    to the real host but records call order/args -- used only to
    assert delegation, never to change behavior."""

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


class _Recorder:
    """Subscribes to a fixed set of event names on a real EventBus and
    records every delivered Event, in delivery order, for later
    assertion. A plain callable per event name (EventBus rejects
    duplicate (event_name, handler) pairs, so each name gets its own
    bound method)."""

    def __init__(self, bus: EventBus, event_names: Tuple[str, ...]) -> None:
        self.events: List[Event] = []
        for name in event_names:
            bus.subscribe(name, self._on_event)

    def _on_event(self, event: Event) -> None:
        self.events.append(event)

    def names(self) -> List[str]:
        return [e.event_name for e in self.events]

    def of(self, event_name: str) -> List[Event]:
        return [e for e in self.events if e.event_name == event_name]


def _make_wired_scheduler() -> Tuple[AutonomousScheduler, EventBus, _Recorder]:
    bus = EventBus()
    recorder = _Recorder(bus, _SCHEDULER_EVENT_NAMES)
    scheduler = AutonomousScheduler(bus)
    return scheduler, bus, recorder


# ---------------------------------------------------------------------------
# E1 -- Sprint 23.1: a None/omitted event_bus auto-creates an
# independent EventBus (no longer raises; no singleton)
# ---------------------------------------------------------------------------
def scenario_none_event_bus_auto_creates_independent_bus() -> None:
    scheduler_explicit_none = AutonomousScheduler(None)
    scheduler_omitted = AutonomousScheduler()

    check(
        isinstance(scheduler_explicit_none._event_bus, EventBus),
        "E1: AutonomousScheduler(None) auto-creates a real EventBus "
        "instead of raising",
    )
    check(
        isinstance(scheduler_omitted._event_bus, EventBus),
        "E1: AutonomousScheduler() (event_bus omitted) auto-creates a "
        "real EventBus",
    )
    check(
        scheduler_explicit_none._event_bus is not scheduler_omitted._event_bus,
        "E1: two default-constructed schedulers own two independent "
        "EventBus instances (no singleton)",
    )

    # Prove independence isn't just object identity -- a subscriber on
    # one auto-created bus never sees events published via the other.
    recorder = _Recorder(scheduler_explicit_none._event_bus, _SCHEDULER_EVENT_NAMES)
    agent, _, _ = _make_agent_and_collaborators()
    scheduler_omitted.schedule(AutonomousHost(), [agent], _FakeContext(), 1)

    check(
        recorder.events == [],
        "E1: a scheduler's auto-created EventBus is never shared with "
        "another default-constructed scheduler's auto-created EventBus",
    )


# ---------------------------------------------------------------------------
# E2 -- constructor stores event_bus, queue starts empty, unpaused
# ---------------------------------------------------------------------------
def scenario_constructor_stores_event_bus_and_starts_clean() -> None:
    bus = EventBus()
    scheduler = AutonomousScheduler(bus)

    check(
        scheduler._event_bus is bus,
        "E2: constructor stores the given event_bus as self._event_bus",
    )
    check(
        scheduler.pending_jobs() == (),
        "E2: queue still starts empty",
    )
    check(
        scheduler.tick() == (),
        "E2: an unpaused, empty scheduler's tick() still returns ()",
    )


# ---------------------------------------------------------------------------

# E3 -- schedule() publishes exactly one job_scheduled event
# ---------------------------------------------------------------------------
def scenario_schedule_publishes_job_scheduled() -> None:
    scheduler, _, recorder = _make_wired_scheduler()
    agent, _, _ = _make_agent_and_collaborators()
    host = AutonomousHost()

    job_id = scheduler.schedule(host, [agent], _FakeContext(), 3)

    scheduled_events = recorder.of("scheduler.job_scheduled")
    check(
        len(scheduled_events) == 1,
        "E3: exactly one scheduler.job_scheduled event published",
    )
    check(
        scheduled_events[0].payload == {"job_id": job_id, "iterations": 3},
        "E3: scheduler.job_scheduled payload is {job_id, iterations}",
    )
    check(
        scheduled_events[0].source == "AutonomousScheduler",
        "E3: scheduler.job_scheduled is sourced as AutonomousScheduler",
    )


# ---------------------------------------------------------------------------
# E4 -- a rejected schedule() call publishes nothing
# ---------------------------------------------------------------------------
def scenario_rejected_schedule_publishes_nothing() -> None:
    scheduler, _, recorder = _make_wired_scheduler()

    raised = False
    try:
        scheduler.schedule(None, [object()], _FakeContext(), 1)
    except AutonomousSchedulerError:
        raised = True

    check(raised, "E4: invalid schedule() call still raises as before")
    check(
        recorder.events == [],
        "E4: a rejected schedule() call publishes no events at all",
    )


# ---------------------------------------------------------------------------
# E5 -- successful tick() publishes job_started then job_finished
# ---------------------------------------------------------------------------
def scenario_successful_tick_publishes_started_then_finished() -> None:
    scheduler, _, recorder = _make_wired_scheduler()
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()

    job_id = scheduler.schedule(spy_host, [agent], _FakeContext(), 1)
    recorder.events.clear()  # isolate tick()'s own publishing

    result = scheduler.tick()

    check(len(result) == 1, "E5: tick() still returns a 1-tuple of results")
    check(
        recorder.names() == ["scheduler.job_started", "scheduler.job_finished"],
        "E5: job_started then job_finished, in that order, nothing else",
    )
    check(
        recorder.of("scheduler.job_started")[0].payload == {"job_id": job_id},
        "E5: scheduler.job_started payload is {job_id}",
    )
    check(
        recorder.of("scheduler.job_finished")[0].payload == {"job_id": job_id},
        "E5: scheduler.job_finished payload is {job_id}",
    )
    check(
        recorder.of("scheduler.job_failed") == [],
        "E5: a successful job never publishes scheduler.job_failed",
    )


# ---------------------------------------------------------------------------
# E6 -- a failing tick() publishes job_started then job_failed, then raises
# ---------------------------------------------------------------------------
def scenario_failing_tick_publishes_started_then_failed_then_raises() -> None:
    scheduler, _, recorder = _make_wired_scheduler()
    agent, _, _ = _make_agent_and_collaborators()
    failing_host = _FailingHost()

    job_id = scheduler.schedule(failing_host, [agent], _FakeContext(), 1)
    recorder.events.clear()

    raised = False
    try:
        scheduler.tick()
    except AutonomousHostError:
        raised = True

    check(raised, "E6: the original AutonomousHostError still propagates")
    check(
        recorder.names() == ["scheduler.job_started", "scheduler.job_failed"],
        "E6: job_started then job_failed, in that order, nothing else",
    )
    check(
        recorder.of("scheduler.job_failed")[0].payload == {"job_id": job_id},
        "E6: scheduler.job_failed payload is {job_id}",
    )
    check(
        recorder.of("scheduler.job_finished") == [],
        "E6: a failing job never publishes scheduler.job_finished",
    )


# ---------------------------------------------------------------------------
# E7 -- multiple jobs: strict FIFO started/finished pairing
# ---------------------------------------------------------------------------
def scenario_multiple_jobs_fifo_started_finished_pairs() -> None:
    scheduler, _, recorder = _make_wired_scheduler()
    agent1, _, _ = _make_agent_and_collaborators()
    agent2, _, _ = _make_agent_and_collaborators()
    agent3, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()

    id1 = scheduler.schedule(spy_host, [agent1], _FakeContext(), 1)
    id2 = scheduler.schedule(spy_host, [agent2], _FakeContext(), 1)
    id3 = scheduler.schedule(spy_host, [agent3], _FakeContext(), 1)
    recorder.events.clear()

    results = scheduler.tick()

    check(len(results) == 3, "E7: tick() drains all three queued jobs")
    check(
        recorder.names()
        == [
            "scheduler.job_started",
            "scheduler.job_finished",
            "scheduler.job_started",
            "scheduler.job_finished",
            "scheduler.job_started",
            "scheduler.job_finished",
        ],
        "E7: three started/finished pairs, no interleaving, no duplicates",
    )
    check(
        [e.payload["job_id"] for e in recorder.of("scheduler.job_started")]
        == [id1, id2, id3],
        "E7: job_started fires in strict schedule() (FIFO) order",
    )
    check(
        [e.payload["job_id"] for e in recorder.of("scheduler.job_finished")]
        == [id1, id2, id3],
        "E7: job_finished fires in strict schedule() (FIFO) order",
    )


# ---------------------------------------------------------------------------
# E8 -- cancel() publishes exactly one job_cancelled event
# ---------------------------------------------------------------------------
def scenario_cancel_publishes_job_cancelled() -> None:
    scheduler, _, recorder = _make_wired_scheduler()
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()

    job_id = scheduler.schedule(spy_host, [agent], _FakeContext(), 1)
    recorder.events.clear()

    scheduler.cancel(job_id)

    check(
        recorder.names() == ["scheduler.job_cancelled"],
        "E8: exactly one scheduler.job_cancelled event published",
    )
    check(
        recorder.of("scheduler.job_cancelled")[0].payload == {"job_id": job_id},
        "E8: scheduler.job_cancelled payload is {job_id}",
    )

    recorder.events.clear()
    result = scheduler.tick()

    check(
        result == (),
        "E8: a cancelled job is never executed by a later tick()",
    )
    check(
        recorder.events == [],
        "E8: a cancelled job never fires job_started/job_finished",
    )
    check(
        len(spy_host.start_all_calls) == 0,
        "E8: a cancelled job's host.start_all() is never called",
    )


# ---------------------------------------------------------------------------
# E9 -- cancel() on an unknown job_id raises and publishes nothing
# ---------------------------------------------------------------------------
def scenario_cancel_unknown_job_id_publishes_nothing() -> None:
    scheduler, _, recorder = _make_wired_scheduler()

    raised = False
    try:
        scheduler.cancel("does-not-exist")
    except AutonomousSchedulerError:
        raised = True

    check(raised, "E9: cancel() with an unknown job_id still raises")
    check(
        recorder.events == [],
        "E9: a rejected cancel() call publishes no events at all",
    )


# ---------------------------------------------------------------------------
# E10 -- clear() publishes exactly one queue_cleared event
# ---------------------------------------------------------------------------
def scenario_clear_publishes_queue_cleared() -> None:
    scheduler, _, recorder = _make_wired_scheduler()
    agent1, _, _ = _make_agent_and_collaborators()
    agent2, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()

    scheduler.schedule(spy_host, [agent1], _FakeContext(), 1)
    scheduler.schedule(spy_host, [agent2], _FakeContext(), 1)
    recorder.events.clear()

    scheduler.clear()

    check(
        recorder.names() == ["scheduler.queue_cleared"],
        "E10: exactly one scheduler.queue_cleared event published",
    )
    check(
        recorder.of("scheduler.queue_cleared")[0].payload == {},
        "E10: scheduler.queue_cleared payload is empty",
    )

    recorder.events.clear()
    result = scheduler.tick()

    check(result == (), "E10: cleared jobs are never executed")
    check(
        recorder.events == [],
        "E10: cleared jobs never fire job_started",
    )


# ---------------------------------------------------------------------------
# E11 -- pause()/resume() publish paused/resumed with empty payloads
# ---------------------------------------------------------------------------
def scenario_pause_resume_publish_events() -> None:
    scheduler, _, recorder = _make_wired_scheduler()

    scheduler.pause()
    check(
        recorder.names() == ["scheduler.paused"],
        "E11: pause() publishes exactly one scheduler.paused event",
    )
    check(
        recorder.of("scheduler.paused")[0].payload == {},
        "E11: scheduler.paused payload is empty",
    )

    recorder.events.clear()
    scheduler.resume()
    check(
        recorder.names() == ["scheduler.resumed"],
        "E11: resume() publishes exactly one scheduler.resumed event",
    )
    check(
        recorder.of("scheduler.resumed")[0].payload == {},
        "E11: scheduler.resumed payload is empty",
    )


# ---------------------------------------------------------------------------
# E12 -- tick() while paused publishes nothing
# ---------------------------------------------------------------------------
def scenario_paused_tick_publishes_nothing() -> None:
    scheduler, _, recorder = _make_wired_scheduler()
    agent, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()

    scheduler.schedule(spy_host, [agent], _FakeContext(), 1)
    scheduler.pause()
    recorder.events.clear()

    result = scheduler.tick()

    check(result == (), "E12: a paused tick() still returns an empty tuple")
    check(
        recorder.events == [],
        "E12: a paused tick() publishes no job_started/finished/failed",
    )
    check(
        len(spy_host.start_all_calls) == 0,
        "E12: a paused tick() never calls host.start_all()",
    )


# ---------------------------------------------------------------------------
# E13 -- publishing never changes Scheduler behavior
# ---------------------------------------------------------------------------
def scenario_publishing_does_not_change_behavior() -> None:
    bus_a = EventBus()  # no subscribers at all
    bus_b = EventBus()
    _Recorder(bus_b, _SCHEDULER_EVENT_NAMES)  # subscribed recorder

    scheduler_a = AutonomousScheduler(bus_a)
    scheduler_b = AutonomousScheduler(bus_b)

    agent_a1, _, _ = _make_agent_and_collaborators()
    agent_a2, _, _ = _make_agent_and_collaborators()
    agent_b1, _, _ = _make_agent_and_collaborators()
    agent_b2, _, _ = _make_agent_and_collaborators()

    host_a = AutonomousHost()
    host_b = AutonomousHost()

    id_a1 = scheduler_a.schedule(host_a, [agent_a1], _FakeContext(), 1)
    id_a2 = scheduler_a.schedule(host_a, [agent_a2], _FakeContext(), 2)
    id_b1 = scheduler_b.schedule(host_b, [agent_b1], _FakeContext(), 1)
    id_b2 = scheduler_b.schedule(host_b, [agent_b2], _FakeContext(), 2)

    check(
        (id_a1 != id_a2) and (id_b1 != id_b2),
        "E13: job_ids remain unique regardless of subscriber presence",
    )

    pending_a = scheduler_a.pending_jobs()
    pending_b = scheduler_b.pending_jobs()
    check(
        [j.iterations for j in pending_a] == [j.iterations for j in pending_b]
        == [1, 2],
        "E13: queue contents/order identical with vs. without subscribers",
    )

    results_a = scheduler_a.tick()
    results_b = scheduler_b.tick()

    check(
        len(results_a) == len(results_b) == 2,
        "E13: tick() drains the same number of jobs either way",
    )
    check(
        scheduler_a.pending_jobs() == () and scheduler_b.pending_jobs() == (),
        "E13: both queues end up empty after tick(), subscribers or not",
    )


# ---------------------------------------------------------------------------
# E14 -- every published event is sourced as AutonomousScheduler
# ---------------------------------------------------------------------------
def scenario_all_events_sourced_as_scheduler() -> None:
    scheduler, _, recorder = _make_wired_scheduler()
    agent1, _, _ = _make_agent_and_collaborators()
    agent2, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()
    failing_host = _FailingHost()

    scheduler.schedule(spy_host, [agent1], _FakeContext(), 1)
    scheduler.schedule(failing_host, [agent2], _FakeContext(), 1)
    scheduler.pause()
    scheduler.resume()
    try:
        scheduler.tick()
    except AutonomousHostError:
        pass
    scheduler.clear()

    check(
        len(recorder.events) > 0,
        "E14: at least one event was published across the scenario",
    )
    check(
        all(e.source == "AutonomousScheduler" for e in recorder.events),
        "E14: every scheduler.* event is sourced as 'AutonomousScheduler'",
    )


# ---------------------------------------------------------------------------
# E15 -- full multi-call scenario: exactly-once accounting, no duplicates
# ---------------------------------------------------------------------------
def scenario_full_scenario_exact_event_accounting() -> None:
    scheduler, _, recorder = _make_wired_scheduler()
    agent1, _, _ = _make_agent_and_collaborators()
    agent2, _, _ = _make_agent_and_collaborators()
    agent3, _, _ = _make_agent_and_collaborators()
    spy_host = _StartAllSpyHost()

    id1 = scheduler.schedule(spy_host, [agent1], _FakeContext(), 1)
    id2 = scheduler.schedule(spy_host, [agent2], _FakeContext(), 1)
    id3 = scheduler.schedule(spy_host, [agent3], _FakeContext(), 1)

    scheduler.cancel(id2)  # remove the middle job before it ever runs

    scheduler.pause()
    no_op_result = scheduler.tick()
    scheduler.resume()

    results = scheduler.tick()

    scheduler.clear()  # queue already empty; still fires queue_cleared

    check(
        no_op_result == (),
        "E15: the paused tick() in the middle of the scenario did nothing",
    )
    check(
        len(results) == 2,
        "E15: the resumed tick() runs exactly the two remaining jobs",
    )

    counts = {name: len(recorder.of(name)) for name in _SCHEDULER_EVENT_NAMES}
    check(
        counts["scheduler.job_scheduled"] == 3,
        "E15: exactly 3 job_scheduled events (one per schedule() call)",
    )
    check(
        counts["scheduler.job_cancelled"] == 1,
        "E15: exactly 1 job_cancelled event",
    )
    check(
        counts["scheduler.paused"] == 1 and counts["scheduler.resumed"] == 1,
        "E15: exactly 1 paused event and exactly 1 resumed event",
    )
    check(
        counts["scheduler.job_started"] == 2 and counts["scheduler.job_finished"] == 2,
        "E15: exactly 2 job_started and 2 job_finished events (id1, id3 only)",
    )
    check(
        counts["scheduler.job_failed"] == 0,
        "E15: no job_failed events (nothing raised in this scenario)",
    )
    check(
        counts["scheduler.queue_cleared"] == 1,
        "E15: exactly 1 queue_cleared event",
    )
    check(
        [e.payload["job_id"] for e in recorder.of("scheduler.job_started")]
        == [id1, id3],
        "E15: job_started fired for id1 and id3 only, in FIFO order",
    )
    check(
        len(recorder.events)
        == sum(counts.values()),
        "E15: total recorded events equals the sum of every per-name count "
        "(no stray/duplicate events of any kind)",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_none_event_bus_auto_creates_independent_bus,
        scenario_constructor_stores_event_bus_and_starts_clean,
        scenario_schedule_publishes_job_scheduled,
        scenario_rejected_schedule_publishes_nothing,
        scenario_successful_tick_publishes_started_then_finished,
        scenario_failing_tick_publishes_started_then_failed_then_raises,
        scenario_multiple_jobs_fifo_started_finished_pairs,
        scenario_cancel_publishes_job_cancelled,
        scenario_cancel_unknown_job_id_publishes_nothing,
        scenario_clear_publishes_queue_cleared,
        scenario_pause_resume_publish_events,
        scenario_paused_tick_publishes_nothing,
        scenario_publishing_does_not_change_behavior,
        scenario_all_events_sourced_as_scheduler,
        scenario_full_scenario_exact_event_accounting,
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
    print(f"PHASE 3 SPRINT 23 SCHEDULER EVENTS RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())