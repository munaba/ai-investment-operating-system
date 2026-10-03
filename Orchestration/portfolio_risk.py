from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from Core.exceptions import AgentError

# Deterministic, fixed thresholds -- no config, no runtime input.
_EXPOSURE_LOWER_BOUND = 0.0
_EXPOSURE_UPPER_BOUND = 1.0
_ALLOCATION_LOWER_BOUND = 0.0
_ALLOCATION_UPPER_BOUND = 1.0
_CONCENTRATION_THRESHOLD = 0.5
_EXPOSURE_LOW_CEILING = 0.33
_EXPOSURE_MODERATE_CEILING = 0.66


class PortfolioRiskError(AgentError):
    """Raised when PortfolioRisk.assess() encounters an unexpected failure.

    Mirrors the existing exception hierarchy (AgentError) used elsewhere
    in the codebase (ReflectionError, DecisionEngineError,
    DecisionPolicyError, PolicyGuardError, ExecutionIntentError,
    ExecutionPlannerError, ExecutionCoordinatorError,
    PortfolioEngineError), rather than deriving from the bare Exception
    class.
    """
    pass


@dataclass(frozen=True)
class PortfolioRiskResult:
    """Immutable result of PortfolioRisk.assess().

    Stage L26 is intentionally minimal: a deterministic, fixed-threshold
    validation of an already-evaluated portfolio engine result into a
    structured, portfolio-level risk record. No position sizing, no
    order placement, no persistence, no reference back to whatever
    produced the portfolio engine result it was given --
    PortfolioRiskResult only describes exposure/diversification
    risk-assessment information for a future stage to act on.
    """
    approved: bool
    exposure_level: str
    diversification_level: str
    violations: Tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""


class PortfolioRisk:
    """Pure, stateless component that turns a PortfolioEngineResult-shaped
    object into a PortfolioRiskResult.

    Design constraints (Stage L26, following the exact L18/L19/L20/L21/
    L22/L23/L24/L25 additive pattern):
        - Stateless: no instance attributes, safe to reuse across calls.
        - Deterministic: same portfolio engine result always produces
          the same PortfolioRiskResult (fixed thresholds only, no
          external input).
        - No LLM calls.
        - No Provider dependency.
        - No Database dependency.
        - No Runtime dependency.
        - No Memory dependency.
        - No Service dependency.

    PortfolioRisk never constructs, imports, or references any of the
    above, and does not import composition_root, Executor, Runtime,
    Database, StockAgent, or any other Orchestration module (its only
    project import is ``Core.exceptions.AgentError``). It receives a
    plain ``portfolio_engine_result`` object (with ``approved``,
    ``allocation_weight``, and ``exposure`` attributes -- the same
    shape as ``Orchestration.portfolio_engine.PortfolioEngineResult``,
    accessed purely by duck typing, never imported) and returns a
    ``PortfolioRiskResult``. It is not wired into StockAgent,
    RuntimeAnalysisPipeline, DecisionEngine, DecisionPolicy, PolicyGuard,
    ExecutionIntent, ExecutionPlanner, ExecutionCoordinator,
    PortfolioEngine, or ApplicationGraph's production call path -- it
    exists only as a standalone component, for a future stage to wire
    up.

    Behavior:
        - When ``approved`` is False (the upstream portfolio engine
          result was not itself approved): ``approved=False``,
          ``exposure_level="NONE"``, ``diversification_level="NONE"``,
          ``violations`` is empty (there is nothing to validate -- the
          upstream result was already rejected), and ``notes`` states
          that risk was not evaluated because the portfolio engine
          result was not approved.
        - When ``approved`` is True, fixed-threshold checks run against
          ``exposure`` and ``allocation_weight``:
            * exposure outside ``[0.0, 1.0]`` -> a violation and
              ``exposure_level="INVALID"``.
            * allocation_weight outside ``[0.0, 1.0]`` -> a violation.
            * allocation_weight above ``0.5`` (concentration threshold)
              -> a violation and ``diversification_level="CONCENTRATED"``;
              otherwise ``diversification_level="DIVERSIFIED"`` (subject
              to the out-of-range check above, which takes priority and
              reports ``"INVALID"`` instead).
            * a valid exposure is bucketed into ``"NONE"`` (0.0),
              ``"LOW"`` (<= 0.33), ``"MODERATE"`` (<= 0.66), or
              ``"HIGH"`` (> 0.66 up to 1.0).
          ``approved`` in the result is ``True`` only when the upstream
          result was approved *and* no violations were found; any
          violation makes the result not approved, regardless of the
          upstream flag.

    PortfolioRisk does not place an order, adjust a real portfolio,
    call Runtime, call Executor, call Database, call Providers, call
    Services, or touch any execution surface -- it only produces a
    structured, immutable portfolio-level risk-assessment record.
    """

    def assess(self, portfolio_engine_result) -> PortfolioRiskResult:
        try:
            approved = portfolio_engine_result.approved
            allocation_weight = portfolio_engine_result.allocation_weight
            exposure = portfolio_engine_result.exposure
        except AttributeError as exc:
            raise PortfolioRiskError(
                "PortfolioRisk.assess() expects a portfolio engine "
                "result object with 'approved', 'allocation_weight', "
                "and 'exposure' attributes"
            ) from exc

        try:
            if not approved:
                return PortfolioRiskResult(
                    approved=False,
                    exposure_level="NONE",
                    diversification_level="NONE",
                    violations=tuple(),
                    notes=(
                        "portfolio risk not evaluated: portfolio engine "
                        "result was not approved"
                    ),
                )

            violations = []

            exposure_in_range = (
                _EXPOSURE_LOWER_BOUND <= exposure <= _EXPOSURE_UPPER_BOUND
            )
            if not exposure_in_range:
                violations.append(
                    f"exposure {exposure} outside allowed range "
                    f"[{_EXPOSURE_LOWER_BOUND}, {_EXPOSURE_UPPER_BOUND}]"
                )

            allocation_in_range = (
                _ALLOCATION_LOWER_BOUND
                <= allocation_weight
                <= _ALLOCATION_UPPER_BOUND
            )
            if not allocation_in_range:
                violations.append(
                    f"allocation_weight {allocation_weight} outside "
                    f"allowed range [{_ALLOCATION_LOWER_BOUND}, "
                    f"{_ALLOCATION_UPPER_BOUND}]"
                )

            concentrated = (
                allocation_in_range
                and allocation_weight > _CONCENTRATION_THRESHOLD
            )
            if concentrated:
                violations.append(
                    f"allocation_weight {allocation_weight} exceeds "
                    f"concentration threshold {_CONCENTRATION_THRESHOLD}, "
                    f"diversification insufficient"
                )

            if not exposure_in_range:
                exposure_level = "INVALID"
            elif exposure == _EXPOSURE_LOWER_BOUND:
                exposure_level = "NONE"
            elif exposure <= _EXPOSURE_LOW_CEILING:
                exposure_level = "LOW"
            elif exposure <= _EXPOSURE_MODERATE_CEILING:
                exposure_level = "MODERATE"
            else:
                exposure_level = "HIGH"

            if not allocation_in_range:
                diversification_level = "INVALID"
            elif concentrated:
                diversification_level = "CONCENTRATED"
            else:
                diversification_level = "DIVERSIFIED"

            result_approved = len(violations) == 0

            if result_approved:
                notes = (
                    f"portfolio risk approved: "
                    f"exposure_level={exposure_level}, "
                    f"diversification_level={diversification_level}"
                )
            else:
                notes = (
                    f"portfolio risk rejected: "
                    f"{'; '.join(violations)}"
                )

            return PortfolioRiskResult(
                approved=result_approved,
                exposure_level=exposure_level,
                diversification_level=diversification_level,
                violations=tuple(violations),
                notes=notes,
            )
        except PortfolioRiskError:
            raise
        except Exception as exc:
            raise PortfolioRiskError(
                f"Unexpected failure while building portfolio risk result: {exc}"
            ) from exc