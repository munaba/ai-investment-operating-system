from __future__ import annotations

from dataclasses import dataclass

from Core.exceptions import AgentError


class PortfolioEngineError(AgentError):
    """Raised when PortfolioEngine.evaluate() encounters an unexpected failure.

    Mirrors the existing exception hierarchy (AgentError) used elsewhere
    in the codebase (ReflectionError, DecisionEngineError,
    DecisionPolicyError, PolicyGuardError, ExecutionIntentError,
    ExecutionPlannerError, ExecutionCoordinatorError), rather than
    deriving from the bare Exception class.
    """
    pass


@dataclass(frozen=True)
class PortfolioEngineResult:
    """Immutable result of PortfolioEngine.evaluate().

    Stage L25 is intentionally minimal: a deterministic pass-through of
    an already-coordinated execution result into a structured
    portfolio-level record, or a recorded non-approval when the
    coordination result was not itself coordinated. No allocation
    changes, no persistence, no reference back to whatever produced the
    execution coordinator result it was given -- PortfolioEngineResult
    only describes portfolio-level approval/allocation/exposure
    information for a future stage to act on.
    """
    approved: bool
    allocation_weight: float
    exposure: float
    notes: str


class PortfolioEngine:
    """Pure, stateless component that turns an ExecutionCoordinatorResult-
    shaped object into a PortfolioEngineResult.

    Design constraints (Stage L25, following the exact L18/L19/L20/L21/
    L22/L23/L24 additive pattern):
        - Stateless: no instance attributes, safe to reuse across calls.
        - Deterministic: same execution coordinator result always
          produces the same PortfolioEngineResult.
        - No LLM calls.
        - No Provider dependency.
        - No Database dependency.
        - No Runtime dependency.
        - No Memory dependency.
        - No Service dependency.

    PortfolioEngine never constructs, imports, or references any of the
    above, and does not import composition_root, Executor, Runtime,
    Database, or StockAgent. It receives a plain
    ``execution_coordinator_result`` object (with ``coordinated``,
    ``action``, ``risk_level``, and ``position_size`` attributes -- the
    same shape as
    ``Orchestration.execution_coordinator.ExecutionCoordinatorResult``,
    accessed purely by duck typing, never imported) and returns a
    ``PortfolioEngineResult``. It is not wired into StockAgent,
    RuntimeAnalysisPipeline, DecisionEngine, DecisionPolicy, PolicyGuard,
    ExecutionIntent, ExecutionPlanner, ExecutionCoordinator, or
    ApplicationGraph's production call path -- it exists only as a
    standalone component, for a future stage to wire up.

    Behavior:
        - When ``coordinated`` is True: ``approved=True``,
          ``allocation_weight`` is carried through directly from
          ``position_size`` (this stage performs no scaling or
          re-weighting of its own), ``exposure`` is likewise carried
          through directly from ``position_size``.
        - When ``coordinated`` is False: ``approved=False``, and both
          ``allocation_weight`` and ``exposure`` are ``0.0`` -- an
          uncoordinated execution result carries no portfolio exposure.

    PortfolioEngine does not place an order, adjust a real portfolio,
    call Runtime, call Executor, call Database, call Providers, call
    Services, or touch any execution surface -- it only produces a
    structured, immutable portfolio-level approval/allocation record.
    """

    def evaluate(self, execution_coordinator_result) -> PortfolioEngineResult:
        try:
            coordinated = execution_coordinator_result.coordinated
            action = execution_coordinator_result.action
            risk_level = execution_coordinator_result.risk_level
            position_size = execution_coordinator_result.position_size
        except AttributeError as exc:
            raise PortfolioEngineError(
                "PortfolioEngine.evaluate() expects an execution "
                "coordinator result object with 'coordinated', "
                "'action', 'risk_level', and 'position_size' attributes"
            ) from exc

        try:
            if coordinated:
                approved = True
                allocation_weight = position_size
                exposure = position_size
                notes = (
                    f"portfolio approved for action={action}, "
                    f"risk_level={risk_level}"
                )
            else:
                approved = False
                allocation_weight = 0.0
                exposure = 0.0
                notes = f"portfolio not approved for action={action}: execution was not coordinated"

            return PortfolioEngineResult(
                approved=approved,
                allocation_weight=allocation_weight,
                exposure=exposure,
                notes=notes,
            )
        except PortfolioEngineError:
            raise
        except Exception as exc:
            raise PortfolioEngineError(
                f"Unexpected failure while building portfolio engine result: {exc}"
            ) from exc