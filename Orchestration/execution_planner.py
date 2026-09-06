from __future__ import annotations

from dataclasses import dataclass

from Core.exceptions import AgentError


class ExecutionPlannerError(AgentError):
    """Raised when ExecutionPlanner.plan() encounters an unexpected failure.

    Mirrors the existing exception hierarchy (AgentError) used elsewhere
    in the codebase (ReflectionError, DecisionEngineError,
    DecisionPolicyError, PolicyGuardError, ExecutionIntentError), rather
    than deriving from the bare Exception class.
    """
    pass


@dataclass(frozen=True)
class ExecutionPlan:
    """Immutable result of ExecutionPlanner.plan().

    Stage L23 is intentionally minimal: a deterministic pass-through of
    an already-built execution intent into a structured planning
    record, or a recorded skip reason when the intent was not ready.
    No order placement, no scheduling, no reference back to whatever
    produced the execution intent it was given -- ExecutionPlan only
    describes planning information for a future stage to act on.
    """
    planned: bool
    action: str
    risk_level: str
    position_size: float
    skip_reason: str
    notes: str


class ExecutionPlanner:
    """Pure, stateless component that turns an ExecutionIntent-shaped
    object into an ExecutionPlan.

    Design constraints (Stage L23, following the exact L18/L19/L20/L21/
    L22 additive pattern):
        - Stateless: no instance attributes, safe to reuse across calls.
        - Deterministic: same execution intent always produces the same
          ExecutionPlan.
        - No LLM calls.
        - No Provider dependency.
        - No Database dependency.
        - No Runtime dependency.
        - No Memory dependency.
        - No Service dependency.

    ExecutionPlanner never constructs, imports, or references any of the
    above, and does not import composition_root or ExecutionIntent. It
    receives a plain ``execution_intent`` object (with ``ready``,
    ``action``, ``risk_level``, ``position_size``, and
    ``denial_reason`` attributes -- the same shape as
    ``Orchestration.execution_intent.ExecutionIntentResult``, accessed
    purely by duck typing, never imported) and returns an
    ``ExecutionPlan``. It is not wired into StockAgent,
    RuntimeAnalysisPipeline, DecisionEngine, DecisionPolicy, PolicyGuard,
    ExecutionIntent, or ApplicationGraph's production call path -- it
    exists only as a standalone component, for a future stage to wire up.

    Behavior:
        - When ``ready`` is True: ``planned=True``, ``skip_reason`` is
          the empty string, and ``action``/``risk_level``/
          ``position_size`` are carried through unchanged.
        - When ``ready`` is False: ``planned=False``, and
          ``skip_reason`` is taken from the intent's own
          ``denial_reason`` -- or a generic fallback message if
          ``denial_reason`` is empty. ``action``/``risk_level``/
          ``position_size`` are still carried through unchanged; this
          stage never substitutes or zeroes them out on skip, it only
          reports that the plan is not ready.

    ExecutionPlanner does not execute a trade, place an order, or touch
    any execution surface -- it only produces a structured, immutable
    planning record, or the reason a plan could not yet be made.
    """

    def plan(self, execution_intent) -> ExecutionPlan:
        try:
            ready = execution_intent.ready
            action = execution_intent.action
            risk_level = execution_intent.risk_level
            position_size = execution_intent.position_size
            denial_reason = execution_intent.denial_reason
        except AttributeError as exc:
            raise ExecutionPlannerError(
                "ExecutionPlanner.plan() expects an execution intent "
                "object with 'ready', 'action', 'risk_level', "
                "'position_size', and 'denial_reason' attributes"
            ) from exc

        try:
            if ready:
                skip_reason = ""
                notes = f"execution plan created for action={action}"
                planned = True
            else:
                if denial_reason:
                    skip_reason = denial_reason
                else:
                    skip_reason = "execution intent was not ready"
                notes = (
                    f"execution plan skipped for action={action}: "
                    f"{skip_reason}"
                )
                planned = False

            return ExecutionPlan(
                planned=planned,
                action=action,
                risk_level=risk_level,
                position_size=position_size,
                skip_reason=skip_reason,
                notes=notes,
            )
        except ExecutionPlannerError:
            raise
        except Exception as exc:
            raise ExecutionPlannerError(
                f"Unexpected failure while building execution plan: {exc}"
            ) from exc