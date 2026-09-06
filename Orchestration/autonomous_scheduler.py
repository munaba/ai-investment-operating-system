from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple
from uuid import uuid4

from Core.exceptions import AgentError
from Orchestration.autonomous_host import AutonomousHost
from Orchestration.event_bus import Event, EventBus


class AutonomousSchedulerError(AgentError):
    """Raised when ``AutonomousScheduler.schedule()`` is given invalid
    inputs.

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``AutonomousHostError``,
    ``AutonomousAgentError``, ``ReflectionError``,
    ``DecisionEngineError``, ``DecisionPolicyError``,
    ``PolicyGuardError``, ``ExecutionIntentError``,
    ``ExecutionPlannerError``, ``ExecutionCoordinatorError``,
    ``PortfolioEngineError``, ``PortfolioRiskError``,
    ``LearningLoopError``), rather than deriving from the bare
    ``Exception`` class.
    """

    pass


@dataclass(frozen=True)
class SchedulerJob:
    """Sprint 21 -- an immutable value object giving one queued unit of
    work (one ``host.start_all(agents, context, iterations)`` call
    waiting to happen) a stable, unique identity that survives queue
    position changes (cancellations, partial drains, etc.).

    ``job_id`` is a ``uuid4`` string minted once, at ``schedule()``
    time, and never changes for the lifetime of this job. It is the
    only supported way to refer to a specific queued job from the
    outside (``cancel()`` takes a ``job_id``, and ``pending_jobs()``
    reports each job's ``job_id`` alongside its contents) -- callers
    must no longer rely on queue index, since that shifts whenever an
    earlier job is cancelled or ticked.

    Instances are frozen (immutable) -- once constructed by
    ``schedule()``, a ``SchedulerJob``'s fields cannot be reassigned.
    """

    job_id: str
    host: AutonomousHost
    agents: Tuple[object, ...]
    context: object
    iterations: int


class AutonomousScheduler:
    """Phase 3, Sprint 17 -- the first synchronous ``AutonomousScheduler``.

    ``AutonomousScheduler`` owns exactly one thing: a FIFO queue of
    *already-validated, not-yet-run* work. It holds no other state,
    and it never executes anything on its own -- execution happens
    exclusively when a caller invokes ``tick()``.

    Execution is delegated exclusively to
    ``Orchestration.autonomous_host.AutonomousHost.start_all()``. This
    scheduler never imports, references, or calls
    ``Orchestration.autonomous_agent.AutonomousAgent`` or
    ``Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline``
    directly -- every agent run happens strictly through the
    already-existing, unmodified ``AutonomousHost.start_all()`` call
    path, exactly as Sprint 15 built it.

    This is deliberately *not* a scheduler in the background-worker
    sense. There is no threading, no asyncio, no timers, no sleep, no
    cron, no daemon, no background worker, and no persistence of any
    kind (nothing is written to disk/DB -- the queue lives only in
    this instance's own process memory and is lost the moment the
    instance is garbage collected). ``tick()`` performs plain,
    synchronous, in-process work and returns.

    FIFO only: ``schedule()`` calls are queued in the order they
    arrive, and ``tick()`` drains that queue strictly in the order it
    was built, one job at a time. There is no priority ordering, no
    sorting, no reordering, and no automatic retry -- a job that
    raises during ``tick()`` is not re-queued or re-attempted; running
    it again requires an explicit new ``schedule()`` call.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        """Sprint 23.1 -- ``event_bus`` is now optional. When omitted
        (or explicitly passed as ``None``), a brand-new, independent
        ``EventBus()`` instance is created and used -- this is
        identical in every observable respect to a caller
        constructing ``EventBus()`` themselves and passing it in
        explicitly. There is no sharing, caching, or singleton behind
        this default: every ``AutonomousScheduler()`` (or
        ``AutonomousScheduler(None)``) call gets its own fresh, fully
        independent ``EventBus``, exactly as ``EventBus``'s own "not a
        global singleton" contract requires.

        Sprint 23's explicit-argument form -- ``AutonomousScheduler(
        event_bus)`` with a real ``EventBus`` -- is unchanged: that
        instance is stored, unchanged, as ``self._event_bus``, exactly
        as before. No other constructor behavior changes: the queue
        still starts empty and the scheduler still starts unpaused.

        Args:
            event_bus: the ``EventBus`` instance this scheduler will
                ``publish()`` lifecycle events to. Optional; defaults
                to ``None``, which auto-creates a new, independent
                ``EventBus()``.
        """
        if event_bus is None:
            event_bus = EventBus()
        self._event_bus = event_bus
        self._queue: List[SchedulerJob] = []
        self._paused: bool = False

    def _publish(self, event_name: str, payload: dict) -> None:
        """Sprint 23 -- internal helper publishing exactly one
        ``Event`` through ``self._event_bus``, sourced as
        ``"AutonomousScheduler"``. Never called for its side effects
        on scheduler state -- publishing never changes queue
        contents, pause state, or any other scheduler behavior.
        """
        self._event_bus.publish(
            Event(
                event_name=event_name,
                source="AutonomousScheduler",
                payload=payload,
            )
        )

    def schedule(
        self,
        host: AutonomousHost,
        agents: Iterable[object],
        context: object,
        iterations: int,
    ) -> str:
        """Validate one unit of work, mint a stable unique ``job_id``
        for it, and store it (as a ``SchedulerJob``) at the back of
        the FIFO queue. Nothing is executed here.

        ``schedule()`` performs the same shape of up-front, all-or-
        nothing validation ``AutonomousHost.start_all()`` itself
        applies (so a malformed call is rejected immediately, at
        schedule time, rather than silently queued and only failing
        later inside ``tick()``) -- but it never calls ``host``,
        never calls any agent's ``run()``, and never mutates any
        agent's status. ``agents`` is eagerly materialized into a
        ``tuple`` snapshot at schedule time, so later mutation of a
        list the caller passed in has no effect on the already-queued
        job.

        Args:
            host: the ``AutonomousHost`` instance that ``tick()``
                will later delegate this job's execution to. Must not
                be ``None`` and must expose a callable ``start_all``.
            agents: a non-empty iterable of agent-like objects (each
                must be non-None and expose a callable ``run`` and a
                ``status`` attribute -- the same shape
                ``AutonomousHost.start_all()`` itself requires). Must
                not be ``None`` or empty.
            context: the ``ServiceContext``-shaped object that will be
                passed unchanged to ``host.start_all()`` when this job
                runs. Must not be ``None``.
            iterations: how many cycles each agent's ``run()`` should
                perform when this job runs. Must be an ``int`` >= 1.

        Returns:
            The newly minted ``job_id`` (a ``uuid4`` string) for this
            queued job -- the caller's only handle for later
            targeting it with ``cancel()``.

        Raises:
            AutonomousSchedulerError: if ``host`` is ``None`` or does
                not expose a callable ``start_all``; if ``agents`` is
                ``None``, is not iterable, is empty, or contains a
                ``None`` or non-agent-shaped entry; if ``context`` is
                ``None``; or if ``iterations`` is not an ``int`` >= 1.
        """
        if host is None or not hasattr(host, "start_all") or not callable(
            getattr(host, "start_all")
        ):
            raise AutonomousSchedulerError(
                "AutonomousScheduler.schedule() requires a non-None "
                "'host' exposing a callable 'start_all'"
            )

        if agents is None:
            raise AutonomousSchedulerError(
                "AutonomousScheduler.schedule() requires a non-None "
                "'agents' iterable"
            )

        try:
            agent_tuple: Tuple[object, ...] = tuple(agents)
        except TypeError as exc:
            raise AutonomousSchedulerError(
                "AutonomousScheduler.schedule() requires 'agents' to be "
                "an iterable"
            ) from exc

        if len(agent_tuple) == 0:
            raise AutonomousSchedulerError(
                "AutonomousScheduler.schedule() requires a non-empty "
                "'agents' iterable"
            )

        for index, candidate in enumerate(agent_tuple):
            if (
                candidate is None
                or not hasattr(candidate, "run")
                or not callable(getattr(candidate, "run"))
                or not hasattr(candidate, "status")
            ):
                raise AutonomousSchedulerError(
                    f"AutonomousScheduler.schedule() requires every entry "
                    f"in 'agents' to be an AutonomousAgent-shaped object "
                    f"(non-None, with a callable 'run' and a 'status' "
                    f"attribute); entry at index {index} is not"
                )

        if context is None:
            raise AutonomousSchedulerError(
                "AutonomousScheduler.schedule() requires a non-None "
                "'context'"
            )

        if (
            not isinstance(iterations, int)
            or isinstance(iterations, bool)
            or iterations < 1
        ):
            raise AutonomousSchedulerError(
                "AutonomousScheduler.schedule() requires 'iterations' to "
                "be an int >= 1"
            )

        job_id = str(uuid4())
        self._queue.append(
            SchedulerJob(job_id, host, agent_tuple, context, iterations)
        )
        self._publish(
            "scheduler.job_scheduled",
            {"job_id": job_id, "iterations": iterations},
        )
        return job_id

    def tick(self) -> Tuple[object, ...]:
        """Execute every job currently in the FIFO queue, exactly
        once each, strictly in the order it was scheduled -- unless
        the scheduler is currently paused (Sprint 20), in which case
        ``tick()`` executes nothing at all.

        While paused, ``tick()`` performs no delegation to any job's
        ``host.start_all()``, leaves the queue completely untouched
        (nothing is dequeued, dropped, or reordered), and returns an
        empty tuple immediately. This is the only difference paused
        state makes -- ``schedule()``, ``cancel()``, ``clear()``, and
        ``pending_jobs()`` all continue to behave exactly as before,
        paused or not.

        When active (not paused), each queued job is removed from the
        front of the queue and immediately delegated as exactly one
        ``job.host.start_all(job.agents, job.context, job.iterations)``
        call -- no wrapping, no transformation, no retries, no
        timers. A job is only removed once it has been dequeued for
        execution; if that delegated call itself raises, the
        exception propagates out of ``tick()`` unchanged and
        immediately, and any jobs still remaining in the queue behind
        it are left queued (untouched, not attempted, not dropped) for
        a future ``tick()`` call.

        Calling ``tick()`` again immediately after a fully successful
        ``tick()`` executes nothing and returns an empty tuple, since
        every job that completed was already removed.

        Returns:
            A ``tuple`` of per-job results, in the same order the
            jobs were scheduled -- ``results[i]`` is exactly what
            ``job[i].host.start_all(...)`` returned, unwrapped and
            unchanged. An empty queue returns an empty tuple. A
            paused scheduler always returns an empty tuple.

        Raises:
            AutonomousHostError: propagated unchanged if a delegated
                ``host.start_all()`` call itself raises (e.g. invalid
                per-job state discovered by the host, or an agent in
                a terminal status).
            AutonomousAgentError: propagated unchanged if a delegated
                ``host.start_all()`` call itself raises one (e.g. a
                mid-run agent failure).
        """
        if self._paused:
            return tuple()

        results: List[object] = []
        while self._queue:
            job = self._queue.pop(0)
            self._publish("scheduler.job_started", {"job_id": job.job_id})
            try:
                result = job.host.start_all(
                    job.agents, job.context, job.iterations
                )
            except Exception:
                self._publish(
                    "scheduler.job_failed", {"job_id": job.job_id}
                )
                raise
            self._publish("scheduler.job_finished", {"job_id": job.job_id})
            results.append(result)
        return tuple(results)

    def pause(self) -> None:
        """Move the scheduler into the paused state (Sprint 20).

        Once paused, ``tick()`` executes nothing and leaves the queue
        untouched until ``resume()`` is called. ``pause()`` never
        touches the queue itself -- jobs may still be added via
        ``schedule()`` while paused, and ``pending_jobs()``,
        ``cancel()``, and ``clear()`` all continue to work normally.

        Idempotent: calling ``pause()`` while already paused is a
        no-op and raises nothing.

        Returns:
            ``None``.
        """
        self._paused = True
        self._publish("scheduler.paused", {})
        return None

    def resume(self) -> None:
        """Move the scheduler back into the active state (Sprint 20).

        Once resumed, ``tick()`` goes back to draining the queue
        exactly as it did before ``pause()`` was called. ``resume()``
        never touches the queue itself.

        Idempotent: calling ``resume()`` while already active is a
        no-op and raises nothing.

        Returns:
            ``None``.
        """
        self._paused = False
        self._publish("scheduler.resumed", {})
        return None

    def pending_jobs(self) -> Tuple[SchedulerJob, ...]:
        """Return an immutable snapshot of every job currently waiting
        in the FIFO queue, in queue order (front first).

        This is read-only inspection: it performs no execution, calls
        no job's ``host.start_all()``, mutates no agent's status, and
        does not remove or reorder anything -- calling it any number
        of times has no effect on what a subsequent ``tick()`` will
        do. The internal queue (a private ``list``) is never handed
        out directly; a new ``tuple`` is built from it each call, so
        mutating the returned structure -- or anything the caller
        does with it -- cannot affect this scheduler's own state.
        Each entry is itself a frozen ``SchedulerJob`` (immutable), so
        its fields -- including ``job_id`` -- cannot be altered by the
        caller either.

        Returns:
            A ``tuple`` of ``SchedulerJob`` instances, one per
            currently-queued job, oldest (next to run) first. Each
            exposes ``job_id``, ``host``, ``agents``, ``context``, and
            ``iterations``. ``agents`` is itself already the
            immutable ``tuple`` snapshot ``schedule()`` captured.
            Empty queue returns an empty tuple.
        """
        return tuple(self._queue)

    def cancel(self, job_id: str) -> None:
        """Remove exactly one queued job by its stable ``job_id``
        (Sprint 21), without executing it.

        ``cancel()`` never calls any job's ``host.start_all()`` and
        never touches any agent's status -- it only ever removes an
        entry from the private queue. The remaining jobs keep their
        original relative FIFO order (nothing is reordered).

        Args:
            job_id: the ``job_id`` string returned by ``schedule()``
                (and reported by ``pending_jobs()``) for the job to
                remove.

        Returns:
            ``None``.

        Raises:
            AutonomousSchedulerError: if ``job_id`` does not match any
                job currently in the queue (including when the queue
                is empty).
        """
        for index, job in enumerate(self._queue):
            if job.job_id == job_id:
                del self._queue[index]
                self._publish("scheduler.job_cancelled", {"job_id": job_id})
                return None

        raise AutonomousSchedulerError(
            f"AutonomousScheduler.cancel() received unknown 'job_id' "
            f"{job_id!r}"
        )

    def clear(self) -> None:
        """Remove every job currently waiting in the FIFO queue.

        No queued job is executed -- ``clear()`` never calls any
        job's ``host.start_all()`` and never touches any agent's
        status. It is safe to call on an already-empty queue, and
        safe to call repeatedly (each call after the first is a
        no-op). Only this scheduler's own queue is affected; jobs
        that have already been dequeued and executed by a prior
        ``tick()`` are unaffected (there is nothing left to clear for
        them), and other ``AutonomousScheduler`` instances are
        unaffected.

        Returns:
            ``None``.
        """
        self._queue.clear()
        self._publish("scheduler.queue_cleared", {})
        return None