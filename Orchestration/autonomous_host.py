from __future__ import annotations

from typing import Iterable, List, Tuple

from Core.exceptions import AgentError
from Orchestration.autonomous_agent import (
    AutonomousAgent,
    AutonomousAgentStatus,
    AutonomousCycleResult,
)


class AutonomousHostError(AgentError):
    """Raised when ``AutonomousHost.start``/``stop`` is given invalid
    inputs, or when the targeted agent is not in a state that may be
    (re)started.

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``AutonomousAgentError``,
    ``ReflectionError``, ``DecisionEngineError``, ``DecisionPolicyError``,
    ``PolicyGuardError``, ``ExecutionIntentError``,
    ``ExecutionPlannerError``, ``ExecutionCoordinatorError``,
    ``PortfolioEngineError``, ``PortfolioRiskError``,
    ``LearningLoopError``), rather than deriving from the bare
    ``Exception`` class.
    """

    pass


class AutonomousHost:
    """Phase 2, Sprint 12 -- the first Host/Scheduler capable of
    repeatedly driving an ``AutonomousAgent``.

    ``AutonomousHost`` is a pure orchestration shim: it owns exactly
    two responsibilities -- starting an agent (by delegating to its
    already-existing ``run()``) and stopping an agent (by delegating
    to its already-existing ``stop()``). It holds no state of its own,
    takes no constructor arguments, and introduces no new behavior
    beyond input validation and delegation.

    This is deliberately *not* a scheduler in the background-worker
    sense. There is no threading, no asyncio, no timers, no sleep, no
    cron, no daemon, no queue, no retry, no automatic restart, and no
    health monitoring. ``start()`` performs exactly one synchronous
    call to ``agent.run(context, iterations)`` and returns; the entire
    "repeatedly driving" behavior already lives inside
    ``AutonomousAgent.run()``'s own loop over ``step()`` (Sprint 4) --
    ``AutonomousHost`` does not loop, retry, or re-invoke anything
    itself.

    ``AutonomousHost`` never touches ``RuntimeAnalysisPipeline`` or
    ``GoalPlanner`` directly, never reads or writes
    ``AutonomousAgent``'s private lifecycle attributes, and never
    constructs an ``AutonomousCycleResult`` itself -- every one of
    those remains exclusively ``AutonomousAgent``'s concern, exactly
    as it already was before this sprint.
    """

    def start(
        self,
        agent: AutonomousAgent,
        context: object,
        iterations: int,
    ) -> Tuple[AutonomousCycleResult, ...]:
        """Start ``agent`` for exactly one synchronous run.

        Validates its own three inputs, then performs exactly one
        delegation to ``agent.run(context, iterations)`` and returns
        that tuple unchanged -- no wrapping, no transformation, no
        retries, no scheduling, no timers. Every status transition,
        every ``iteration_count``/``last_cycle_at`` update, and every
        delegation to ``RuntimeAnalysisPipeline``/``GoalPlanner``
        happens exclusively inside ``AutonomousAgent`` itself, as it
        already did before this sprint -- none of that logic is
        duplicated or reimplemented here.

        Args:
            agent: the ``AutonomousAgent`` instance to drive. Must not
                be ``None``.
            context: the ``ServiceContext``-shaped object passed
                unchanged to ``agent.run()``. Must not be ``None``
                (``AutonomousAgent.run()`` would reject it anyway, but
                ``AutonomousHost`` validates it directly rather than
                relying solely on that downstream check, matching the
                "validates inputs" responsibility called out for this
                sprint).
            iterations: how many cycles ``agent.run()`` should
                perform. Must be an ``int`` >= 1.

        Returns:
            The exact ``tuple`` of ``AutonomousCycleResult`` instances
            returned by ``agent.run(context, iterations)`` --
            unchanged, unwrapped.

        Raises:
            AutonomousHostError: if ``agent`` is ``None``, if
                ``context`` is ``None``, if ``iterations`` is not an
                ``int`` >= 1, or if ``agent.status`` is currently
                ``STOPPED`` or ``ERROR`` (a host must never (re)start
                an agent that is already terminal/failed -- no
                retry/recovery is implemented here, matching
                ``AutonomousAgent`` itself). Any ``AutonomousAgentError``
                raised by the delegated ``agent.run()`` call itself
                (e.g. a mid-run failure) propagates unchanged and is
                never caught or swallowed here.
        """
        if agent is None:
            raise AutonomousHostError(
                "AutonomousHost.start() requires a non-None 'agent'"
            )
        if context is None:
            raise AutonomousHostError(
                "AutonomousHost.start() requires a non-None 'context'"
            )
        if not isinstance(iterations, int) or isinstance(
            iterations, bool
        ) or iterations < 1:
            raise AutonomousHostError(
                "AutonomousHost.start() requires 'iterations' to be "
                "an int >= 1"
            )
        if agent.status is AutonomousAgentStatus.STOPPED:
            raise AutonomousHostError(
                "AutonomousHost.start() refused: agent status is "
                "STOPPED, this is a terminal lifecycle state -- a "
                "new AutonomousAgent is required to start further runs"
            )
        if agent.status is AutonomousAgentStatus.ERROR:
            raise AutonomousHostError(
                "AutonomousHost.start() refused: agent status is "
                "ERROR, no retry/recovery is implemented by "
                "AutonomousHost or AutonomousAgent"
            )

        return agent.run(context, iterations)

    def start_all(
        self,
        agents: Iterable[AutonomousAgent],
        context: object,
        iterations: int,
    ) -> Tuple[Tuple[AutonomousCycleResult, ...], ...]:
        """Sequentially start every agent in ``agents``, in order.

        Phase 3, Sprint 15. Purely an iteration wrapper around the
        existing, unmodified ``start()`` above: for every agent in
        ``agents`` (in the order given), this calls
        ``agent.run(context, iterations)`` exactly once and appends the
        returned tuple to a results list. No threading, asyncio,
        multiprocessing, queue, scheduler, timer, background worker,
        priority ordering, load balancing, round robin, parallel
        execution, retry, backoff, or automatic pause/resume/recovery/
        restore is implemented -- this is one plain ``for`` loop over
        one thread.

        Every entry is validated up front, before any agent is run: an
        all-or-nothing check so that a failing validation never leaves
        some agents run and others not. Once validation passes,
        agents are run strictly in the order given, with no sorting,
        filtering, retrying, or deduplication -- an agent listed twice
        is run twice, and both result tuples are kept.

        Args:
            agents: a non-empty iterable of agent-like objects (each
                must be non-None and expose a callable ``run`` and a
                ``status`` attribute -- the same shape ``start()``
                itself relies on). Must not be ``None`` or empty.
            context: the same ``context`` value passed unchanged to
                every ``agent.run(context, iterations)`` call. Must
                not be ``None``.
            iterations: how many cycles each agent's ``run()`` should
                perform. Must be an ``int`` >= 1, shared by every
                agent in this call.

        Returns:
            A ``tuple`` of per-agent result tuples, in the same order
            as ``agents`` was given -- ``results[i]`` is exactly what
            ``agents[i].run(context, iterations)`` returned, unwrapped
            and unchanged.

        Raises:
            AutonomousHostError: if ``agents`` is ``None``, is empty,
                contains a ``None`` or non-agent-shaped entry, or if
                ``context``/``iterations`` fail the same validation
                ``start()`` applies. Also raised (via the per-agent
                delegation to ``start()``) if any individual agent's
                ``status`` is currently ``STOPPED`` or ``ERROR``.
                Any exception raised by a delegated ``agent.run()``
                call itself propagates unchanged and immediately --
                agents listed after the failing one are never run.
        """
        if agents is None:
            raise AutonomousHostError(
                "AutonomousHost.start_all() requires a non-None 'agents' "
                "iterable"
            )

        try:
            agent_list: List[object] = list(agents)
        except TypeError as exc:
            raise AutonomousHostError(
                "AutonomousHost.start_all() requires 'agents' to be an "
                "iterable"
            ) from exc

        if len(agent_list) == 0:
            raise AutonomousHostError(
                "AutonomousHost.start_all() requires a non-empty 'agents' "
                "iterable"
            )

        for index, candidate in enumerate(agent_list):
            if (
                candidate is None
                or not hasattr(candidate, "run")
                or not callable(getattr(candidate, "run"))
                or not hasattr(candidate, "status")
            ):
                raise AutonomousHostError(
                    f"AutonomousHost.start_all() requires every entry in "
                    f"'agents' to be an AutonomousAgent-shaped object "
                    f"(non-None, with a callable 'run' and a 'status' "
                    f"attribute); entry at index {index} is not"
                )

        # context/iterations are validated once, up front, shared by
        # every agent in this call -- this mirrors start()'s own
        # validation exactly (duplicated here only so that an invalid
        # context/iterations is rejected before *any* agent runs,
        # rather than after the first agent in the list has already
        # been driven by a per-agent call to start()).
        if context is None:
            raise AutonomousHostError(
                "AutonomousHost.start_all() requires a non-None 'context'"
            )
        if (
            not isinstance(iterations, int)
            or isinstance(iterations, bool)
            or iterations < 1
        ):
            raise AutonomousHostError(
                "AutonomousHost.start_all() requires 'iterations' to be "
                "an int >= 1"
            )

        results: List[Tuple[AutonomousCycleResult, ...]] = []
        for candidate in agent_list:
            results.append(self.start(candidate, context, iterations))

        return tuple(results)

    def stop(self, agent: AutonomousAgent) -> None:
        """Stop ``agent``.

        Pure delegation: calls ``agent.stop()`` and nothing more. Any
        validation of the *current* lifecycle state (e.g. refusing to
        stop an already-``ERROR`` agent) is already implemented inside
        ``AutonomousAgent.stop()`` itself and is not duplicated here.

        Args:
            agent: the ``AutonomousAgent`` instance to stop. Must not
                be ``None``.

        Raises:
            AutonomousHostError: if ``agent`` is ``None``.
            AutonomousAgentError: propagated unchanged if
                ``agent.stop()`` itself raises (e.g. because the agent
                is currently in ``ERROR``).
        """
        if agent is None:
            raise AutonomousHostError(
                "AutonomousHost.stop() requires a non-None 'agent'"
            )

        agent.stop()

    def stop_all(self, agents: Iterable[AutonomousAgent]) -> None:
        """Sequentially stop every agent in ``agents``, in order.

        Phase 3, Sprint 16. The stop-side counterpart to ``start_all()``
        above: purely an iteration wrapper around the existing,
        unmodified ``stop()`` method. For every agent in ``agents`` (in
        the order given), this calls ``agent.stop()`` exactly once. No
        threading, asyncio, multiprocessing, queue, scheduler, timer,
        background worker, retry, backoff, or automatic
        pause/resume/recovery/restore is implemented -- this is one
        plain ``for`` loop over one thread, matching ``start_all()``'s
        own scope exactly.

        Every entry is validated up front, before any agent is
        stopped: an all-or-nothing check so that a failing validation
        never leaves some agents stopped and others not. Once
        validation passes, agents are stopped strictly in the order
        given, with no sorting, filtering, retrying, or deduplication
        -- an agent listed twice is stopped twice (a no-op the second
        time, since ``AutonomousAgent.stop()`` is itself idempotent).

        Args:
            agents: a non-empty iterable of agent-like objects (each
                must be non-None and expose a callable ``stop`` --
                the same shape ``stop()`` itself relies on). Must not
                be ``None`` or empty.

        Returns:
            ``None``. Mirrors ``stop()``'s own return value; no
            results are collected or returned, matching that
            existing method exactly.

        Raises:
            AutonomousHostError: if ``agents`` is ``None``, is empty,
                or contains a ``None`` or non-agent-shaped entry.
                Any exception raised by a delegated ``agent.stop()``
                call itself (e.g. ``AutonomousAgentError`` from an
                agent in ``ERROR``) propagates unchanged and
                immediately -- agents listed after the failing one are
                never stopped.
        """
        if agents is None:
            raise AutonomousHostError(
                "AutonomousHost.stop_all() requires a non-None 'agents' "
                "iterable"
            )

        try:
            agent_list: List[object] = list(agents)
        except TypeError as exc:
            raise AutonomousHostError(
                "AutonomousHost.stop_all() requires 'agents' to be an "
                "iterable"
            ) from exc

        if len(agent_list) == 0:
            raise AutonomousHostError(
                "AutonomousHost.stop_all() requires a non-empty 'agents' "
                "iterable"
            )

        for index, candidate in enumerate(agent_list):
            if (
                candidate is None
                or not hasattr(candidate, "stop")
                or not callable(getattr(candidate, "stop"))
            ):
                raise AutonomousHostError(
                    f"AutonomousHost.stop_all() requires every entry in "
                    f"'agents' to be an AutonomousAgent-shaped object "
                    f"(non-None, with a callable 'stop'); entry at index "
                    f"{index} is not"
                )

        for candidate in agent_list:
            self.stop(candidate)