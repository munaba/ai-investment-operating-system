"""Observation -- turns one completed ``GoalPlanner`` execution into a
single, immutable, serialization-friendly artifact (Stage L16, Phase 2:
Observation Layer).

Scope note (LOCKED baseline, approved architecture review -- see
``Docs/l16_architecture.md``): this stage implements exactly three
things and nothing else:

  1. ``ObservationError`` -- the module's own exception type, following
     the same convention as ``GoalPlannerError``/``PlannerError``
     (subclasses ``Core.exceptions.AgentError``).
  2. ``Observation`` -- an immutable value object describing one
     completed execution: the ``Goal`` metadata it started from, the
     order the plan's steps ran in, per-step telemetry (success,
     message, timing, output/error), and a simple aggregated view of
     every successful step's output. Contains only value data (see
     "Immutability & serialization safety" below) -- never a live
     reference to any collaborator that produced it.
  3. ``ObservationRecorder`` -- one generic, non-specialized class that
     builds an ``Observation`` from a ``Goal``, an ``ExecutionPlan``,
     and the ``List[ServiceResult]`` ``GoalPlanner.execute_plan``
     already returned for that plan. It never executes anything, never
     retries anything, never talks to a Service/Skill/Runtime/Provider,
     and never mutates the ``ServiceResult``/``ExecutionPlan``/``Goal``
     it is given.

Explicitly NOT part of this stage (LOCKED, see ``Docs/l16_architecture.md``):
``ObservationStore`` (persistence/query), Memory (L17), Reflection (L18),
any Composition Root wiring, any Runtime/Planner/Service integration. This
module is not imported by, and does not import from,
``Orchestration.planner``, ``Orchestration.service_skill``, ``Core.runtime``,
``Core.event``, ``Core.event_store``, ``Agents.executor``, ``Agents.sandbox``,
``Agents.memory``, or ``Core.composition_root``. It is additive-only,
standing on its own until a future stage wires it up.

Existing, unrelated concepts this module must never be confused with,
merged into, or reuse (LOCKED boundaries, see ``Docs/l16_architecture.md``
Section 14):

  - ``Core.event.EventType.OBSERVATION`` is a Runtime *event-sourcing*
    type constant (genesis/ingest bookkeeping, since Stage 5) -- a
    structural label at a completely different layer. This module's
    ``Observation`` class shares an English word with it and nothing
    else.
  - ``Agents.memory.ConversationMemory`` is chat/message history (the
    user/assistant conversation). It has nothing to do with this
    module, and this module never reads or writes it.

Immutability & serialization safety (LOCKED design constraint): every
field on ``Observation`` (and its nested ``StepObservation`` entries) is
built exclusively from ``dataclass``/``dict``/``list``/``tuple``/``str``/
``int``/``float``/``bool``/``None`` -- see each class's own docstring for
the exact shape. In particular:

  - A ``ServiceResult.error`` (a live ``Exception`` instance) is never
    stored -- only its ``str(...)`` rendering, as ``error_message``.
  - Dict-shaped fields (``goal_metadata``, a step's ``data``/``metadata``
    when they happen to be dicts, and ``aggregated_outputs``) are always
    a fresh shallow copy at the moment ``ObservationRecorder.record(...)``
    runs, never the same dict object the caller (or a ``ServiceResult``)
    still holds a live reference to.
  - Nothing on ``Observation`` ever holds a reference to a
    ``GoalPlanner``, ``ServiceSkill``, ``BaseService``, Runtime object,
    ``Executor``, ``ProviderManager``/``BaseProvider``, ``ToolRegistry``,
    ``ServiceRegistry``, ``DatabaseManager``, callable, lambda, or open
    resource of any kind.

One thing this module deliberately does NOT attempt: a Service's own
``ServiceResult.data`` payload (e.g. a price history structure) is
carried through as-is (or shallow-copied, if it is itself a dict) -- this
module has no way to know, and no business deciding, what shape a given
Service's domain payload takes. That is unchanged Service-level behavior,
not something Observation re-validates or transforms.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from Core.exceptions import AgentError
from Orchestration.planner import ExecutionPlan, Goal
from Services.service_result import ServiceResult


class ObservationError(AgentError):
    """Raised by :class:`ObservationRecorder` for recording-level failures.

    Following the same convention as ``GoalPlannerError``/``PlannerError``
    (both subclass ``Core.exceptions.AgentError``). Raised only when the
    inputs handed to :meth:`ObservationRecorder.record` are internally
    inconsistent (see that method's own docstring) -- never for a
    business failure inside a ``ServiceResult`` (a failed step is
    recorded as-is, not treated as an error at this layer -- see
    :class:`StepObservation`).
    """


@dataclass(frozen=True)
class StepObservation(object):
    """Immutable, value-only telemetry for exactly one executed
    ``PlanStep``.

    Every field here is plain value data (str/bool/float/Optional/dict) --
    never a live object. ``error_message`` is deliberately a ``str``
    rendering of ``ServiceResult.error``, never the ``Exception`` itself
    (see module docstring, "Immutability & serialization safety").

    Attributes:
        order: Zero-based position of this step within the
            ``ExecutionPlan`` it was recorded from -- preserves execution
            order explicitly, independent of list position (so a future
            consumer does not have to rely on tuple ordering alone).
        service_name: The ``PlanStep.service_name`` this telemetry is
            for.
        required_inputs: The ``PlanStep.inputs`` this step was planned
            with, copied verbatim (already a ``Tuple[str, ...]`` on
            ``PlanStep`` -- no conversion needed).
        success: ``ServiceResult.success`` for this step, unmodified.
        message: ``ServiceResult.message`` for this step, unmodified.
        data: A shallow copy of ``ServiceResult.data`` when it is a
            ``dict`` (so this ``StepObservation`` never shares a live,
            mutable dict with the ``ServiceResult`` it was built from);
            otherwise the value is carried through exactly as-is (see
            module docstring's closing note on Service-level payloads).
        error_message: ``str(ServiceResult.error)`` when the step failed
            and carried an error, else ``None``. Never the exception
            object itself.
        execution_time_ms: ``ServiceResult.execution_time_ms`` for this
            step, unmodified -- this is the per-step timing every
            production Service already records; this class does not
            measure anything itself.
        result_metadata: A shallow copy of ``ServiceResult.metadata``
            (already a ``Dict[str, Any]`` on ``ServiceResult``).
    """

    order: int
    service_name: str
    required_inputs: Tuple[str, ...]
    success: bool
    message: str
    data: Any
    error_message: Optional[str]
    execution_time_ms: float
    result_metadata: Dict[str, Any]


@dataclass(frozen=True)
class Observation(object):
    """Immutable, value-only artifact describing one completed
    ``GoalPlanner`` execution (one ``ExecutionPlan`` run once via
    ``execute_plan``).

    An ``Observation`` is per-plan (the whole run), never per-step --
    ``StepObservation`` is per-step, and a ``ServiceResult`` (unchanged,
    L13) remains per-step as well. This class does not replace, wrap, or
    subclass ``ServiceResult`` -- see module docstring.

    Every field is built exclusively from value types (see module
    docstring, "Immutability & serialization safety") so this object is
    suitable for a future Memory layer (L17) to persist without any
    cleanup or conversion -- nothing here needs to be "unwrapped" before
    being written somewhere durable.

    Attributes:
        goal_metadata: A shallow copy of the ``Goal.metadata`` this
            execution started from (the plan's original input, before
            any accumulation happened during ``execute_plan``) -- not
            the running/accumulated context ``GoalPlanner`` builds up
            internally, which is transient and already gone by the time
            ``execute_plan`` returns.
        plan_step_names: The ``service_name`` of every ``PlanStep`` in
            ``ExecutionPlan.steps``, in the same (deterministic) order
            ``build_plan`` produced them.
        steps: One :class:`StepObservation` per executed step, in
            execution order -- length always equal to
            ``len(plan_step_names)`` (see
            :meth:`ObservationRecorder.record`'s consistency check).
        aggregated_outputs: A single merged view of every *successful*
            step's ``dict``-shaped ``data``, folded in execution order
            with later steps' keys overwriting same-named earlier keys
            -- the same merge rule ``GoalPlanner.accumulate_context``
            uses internally, reimplemented independently here (this
            module never calls into ``GoalPlanner`` -- see module
            docstring). A failed step or non-dict ``data`` contributes
            nothing, exactly like ``accumulate_context``.
        recorded_at: Wall-clock ``time.time()`` epoch seconds at the
            moment :meth:`ObservationRecorder.record` built this
            ``Observation`` -- not any Runtime/Service-internal
            timestamp.
    """

    goal_metadata: Dict[str, Any]
    plan_step_names: Tuple[str, ...]
    steps: Tuple[StepObservation, ...]
    aggregated_outputs: Dict[str, Any]
    recorded_at: float = field(default_factory=time.time)

    @property
    def step_count(self) -> int:
        """Number of steps this ``Observation`` recorded telemetry for."""
        return len(self.steps)

    @property
    def all_succeeded(self) -> bool:
        """``True`` iff every recorded step succeeded (vacuously ``True``
        for a zero-step ``Observation``, matching
        ``GoalPlanner.execute_plan([])`` returning ``[]`` for an empty
        plan)."""
        return all(step.success for step in self.steps)

    @property
    def failed_service_names(self) -> Tuple[str, ...]:
        """``service_name`` of every step that did not succeed, in
        execution order."""
        return tuple(step.service_name for step in self.steps if not step.success)


class ObservationRecorder:
    """Builds an :class:`Observation` from one completed ``GoalPlanner``
    execution. One generic class -- not specialized per Service, per
    Goal, or per plan shape (same "one class, no subclassing" pattern
    ``ServiceSkill`` uses, L13).

    Holds no state and no collaborator references: it is constructed
    with no arguments and never stores anything between calls to
    :meth:`record`.
    """

    def __init__(self) -> None:
        """No dependencies -- ``ObservationRecorder`` does not call a
        Service, a ``ServiceSkill``, a ``GoalPlanner``, Runtime, or a
        Provider, so it has nothing to be constructed with."""

    def record(
        self,
        goal: Goal,
        plan: ExecutionPlan,
        results: List[ServiceResult],
    ) -> Observation:
        """Build one :class:`Observation` from a completed execution.

        Pure transformation only (LOCKED baseline, see module
        docstring): reads ``goal``, ``plan``, and ``results``, never
        mutates any of them, never calls a Service/``ServiceSkill``/
        ``GoalPlanner``/Runtime/Provider, never retries anything, and
        never interprets *why* a step failed beyond copying its already-
        computed ``ServiceResult`` fields.

        Args:
            goal: The ``Goal`` the ``plan`` was built for (normally
                ``plan.goal``, but accepted explicitly so a caller who
                already has both on hand does not need to re-derive one
                from the other).
            plan: The ``ExecutionPlan`` that was executed.
            results: The ``List[ServiceResult]`` returned by
                ``GoalPlanner.execute_plan(plan)`` for this same
                ``plan`` -- must be the same length as ``plan.steps``,
                in the same order (exactly what ``execute_plan`` already
                guarantees; this method only checks the shape, it does
                not re-run or re-order anything).

        Returns:
            A new, immutable :class:`Observation`.

        Raises:
            ObservationError: If ``len(results) != len(plan.steps)`` --
                the one internal-consistency check this method performs.
                Never raised for a business failure or an empty plan
                (``plan.steps == () and results == []`` is valid and
                produces a zero-step ``Observation``).
        """
        if len(results) != len(plan.steps):
            raise ObservationError(
                "ObservationRecorder.record: results length does not match "
                "plan.steps length -- results must be exactly what "
                "GoalPlanner.execute_plan(plan) returned for this same plan.",
                details={
                    "plan_step_count": len(plan.steps),
                    "results_count": len(results),
                },
            )

        step_observations: List[StepObservation] = []
        aggregated_outputs: Dict[str, Any] = {}

        for index, (step, result) in enumerate(zip(plan.steps, results)):
            data = dict(result.data) if isinstance(result.data, dict) else result.data
            result_metadata = dict(result.metadata)
            error_message = str(result.error) if result.error is not None else None

            step_observations.append(
                StepObservation(
                    order=index,
                    service_name=step.service_name,
                    required_inputs=step.inputs,
                    success=result.success,
                    message=result.message,
                    data=data,
                    error_message=error_message,
                    execution_time_ms=result.execution_time_ms,
                    result_metadata=result_metadata,
                )
            )

            # Same merge rule as GoalPlanner.accumulate_context (later
            # step's dict-shaped data overwrites same-named earlier
            # keys; a failed or non-dict result contributes nothing) --
            # reimplemented here rather than calling GoalPlanner, since
            # ObservationRecorder never holds or calls a GoalPlanner
            # (see module docstring).
            if result.success and isinstance(result.data, dict):
                aggregated_outputs = {**aggregated_outputs, **result.data}

        return Observation(
            goal_metadata=dict(goal.metadata),
            plan_step_names=tuple(step.service_name for step in plan.steps),
            steps=tuple(step_observations),
            aggregated_outputs=aggregated_outputs,
        )