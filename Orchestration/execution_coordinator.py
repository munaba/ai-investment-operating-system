from __future__ import annotations

from dataclasses import dataclass

from Core.exceptions import AgentError


class ExecutionCoordinatorError(AgentError):
    """Raised when ExecutionCoordinator.coordinate() encounters an unexpected failure.

    Mirrors the existing exception hierarchy (AgentError) used elsewhere
    in the codebase (ReflectionError, DecisionEngineError,
    DecisionPolicyError, PolicyGuardError, ExecutionIntentError,
    ExecutionPlannerError), rather than deriving from the bare Exception
    class.
    """
    pass


@dataclass(frozen=True)
class ExecutionCoordinatorResult:
    """Immutable result of ExecutionCoordinator.coordinate().

    Stage L24 is intentionally minimal: a deterministic pass-through of
    an already-built execution plan into a structured coordination
    record, or a recorded hold reason when the plan was not ready for
    sequencing. No order placement, no scheduling against a real clock
    or queue, no reference back to whatever produced the execution plan
    it was given -- ExecutionCoordinatorResult only describes
    coordination/sequencing readiness for a future stage to act on.
    """
    coordinated: bool
    action: str
    risk_level: str
    position_size: float
    sequence_position: int
    hold_reason: str
    notes: str


class ExecutionCoordinator:
    """Pure, stateless component that turns an ExecutionPlan-shaped
    object into an ExecutionCoordinatorResult.

    Design constraints (Stage L24, following the exact L18/L19/L20/L21/
    L22/L23 additive pattern):
        - Stateless: no instance attributes, safe to reuse across calls.
        - Deterministic: same execution plan always produces the same
          ExecutionCoordinatorResult.
        - No LLM calls.
        - No Provider dependency.
        - No Database dependency.
        - No Runtime dependency.
        - No Memory dependency.
        - No Service dependency.

    ExecutionCoordinator never constructs, imports, or references any of
    the above, and does not import composition_root, Executor, Runtime,
    Database, or StockAgent. It receives a plain ``execution_plan``
    object (with ``planned``, ``action``, ``risk_level``,
    ``position_size``, and ``skip_reason`` attributes -- the same shape
    as ``Orchestration.execution_planner.ExecutionPlan``, accessed
    purely by duck typing, never imported) and returns an
    ``ExecutionCoordinatorResult``. It is not wired into StockAgent,
    RuntimeAnalysisPipeline, DecisionEngine, DecisionPolicy, PolicyGuard,
    ExecutionIntent, ExecutionPlanner, or ApplicationGraph's production
    call path -- it exists only as a standalone component, for a future
    stage to wire up.

    Behavior:
        - When ``planned`` is True: ``coordinated=True``,
          ``sequence_position=1`` (single-item sequencing -- this stage
          coordinates readiness for one plan at a time, it does not
          batch or reorder), ``hold_reason`` is the empty string, and
          ``action``/``risk_level``/``position_size`` are carried
          through unchanged.
        - When ``planned`` is False: ``coordinated=False``,
          ``sequence_position=0``, and ``hold_reason`` is taken from the
          plan's own ``skip_reason`` -- or a generic fallback message if
          ``skip_reason`` is empty. ``action``/``risk_level``/
          ``position_size`` are still carried through unchanged; this
          stage never substitutes or zeroes them out on hold, it only
          reports that coordination could not proceed.

    ExecutionCoordinator does not execute a trade, place an order, call
    Runtime, call Executor, call Database, call Providers, call
    Services, or touch any execution surface -- it only produces a
    structured, immutable coordination/sequencing record, or the reason
    coordination is being held.
    """

    def coordinate(self, execution_plan) -> ExecutionCoordinatorResult:
        try:
            planned = execution_plan.planned
            action = execution_plan.action
            risk_level = execution_plan.risk_level
            position_size = execution_plan.position_size
            skip_reason = execution_plan.skip_reason
        except AttributeError as exc:
            raise ExecutionCoordinatorError(
                "ExecutionCoordinator.coordinate() expects an execution "
                "plan object with 'planned', 'action', 'risk_level', "
                "'position_size', and 'skip_reason' attributes"
            ) from exc

        try:
            if planned:
                hold_reason = ""
                sequence_position = 1
                notes = f"execution coordinated for action={action}"
                coordinated = True
            else:
                if skip_reason:
                    hold_reason = skip_reason
                else:
                    hold_reason = "execution plan was not planned"
                sequence_position = 0
                notes = (
                    f"execution coordination held for action={action}: "
                    f"{hold_reason}"
                )
                coordinated = False

            return ExecutionCoordinatorResult(
                coordinated=coordinated,
                action=action,
                risk_level=risk_level,
                position_size=position_size,
                sequence_position=sequence_position,
                hold_reason=hold_reason,
                notes=notes,
            )
        except ExecutionCoordinatorError:
            raise
        except Exception as exc:
            raise ExecutionCoordinatorError(
                f"Unexpected failure while building execution coordinator "
                f"result: {exc}"
            ) from exc