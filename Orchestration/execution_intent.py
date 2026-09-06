from __future__ import annotations

from dataclasses import dataclass

from Core.exceptions import AgentError


class ExecutionIntentError(AgentError):
    """Raised when ExecutionIntent.build() encounters an unexpected failure.

    Mirrors the existing exception hierarchy (AgentError) used elsewhere
    in the codebase (ReflectionError, DecisionEngineError,
    DecisionPolicyError, PolicyGuardError), rather than deriving from
    the bare Exception class.
    """
    pass


@dataclass(frozen=True)
class ExecutionIntentResult:
    """Immutable result of ExecutionIntent.build().

    Stage L22 is intentionally minimal: a deterministic pass-through of
    an already-guarded policy result into a structured "ready for
    execution" object, or an explained denial when the guard did not
    approve it. No order placement, no sizing recalculation, no
    reference back to whatever produced the policy guard result it was
    given -- ExecutionIntent does not execute anything; it only
    describes an intent that a future stage may act on.
    """
    ready: bool
    action: str
    risk_level: str
    position_size: float
    denial_reason: str
    notes: str


class ExecutionIntent:
    """Pure, stateless component that turns a PolicyGuardResult into an
    ExecutionIntentResult.

    Design constraints (Stage L22, following the exact L18/L19/L20/L21
    additive pattern):
        - Stateless: no instance attributes, safe to reuse across calls.
        - Deterministic: same policy guard result always produces the
          same ExecutionIntentResult.
        - No LLM calls.
        - No Provider dependency.
        - No Database dependency.
        - No Runtime dependency.
        - No Memory dependency.
        - No Service dependency.

    ExecutionIntent never constructs, imports, or references any of the
    above, and does not import composition_root or PolicyGuard. It
    receives a plain ``policy_guard_result`` object (with ``approved``,
    ``action``, ``risk_level``, ``position_size``, and ``violations``
    attributes -- the same shape as
    ``Orchestration.policy_guard.PolicyGuardResult``, accessed purely by
    duck typing, never imported) and returns an ``ExecutionIntentResult``.
    It is not wired into StockAgent, RuntimeAnalysisPipeline, PolicyGuard,
    or ApplicationGraph's production call path -- it exists only as a
    standalone component, for a future stage to wire up.

    Behavior:
        - When ``approved`` is True: ``ready=True``, ``denial_reason``
          is the empty string, and ``action``/``risk_level``/
          ``position_size`` are carried through unchanged.
        - When ``approved`` is False: ``ready=False``, and
          ``denial_reason`` is built from the guard's own
          ``violations`` (joined, same separator PolicyGuard's own
          ``notes`` uses) -- or a generic fallback message if
          ``violations`` is empty. ``action``/``risk_level``/
          ``position_size`` are still carried through unchanged; this
          stage never substitutes or zeroes them out on denial, it only
          reports that the intent is not ready.

    ExecutionIntent does not execute a trade, place an order, or touch
    any execution surface -- it only produces a structured, immutable
    description of what a downstream stage would need to act on, or why
    it cannot yet.
    """

    def build(self, policy_guard_result) -> ExecutionIntentResult:
        try:
            approved = policy_guard_result.approved
            action = policy_guard_result.action
            risk_level = policy_guard_result.risk_level
            position_size = policy_guard_result.position_size
            violations = policy_guard_result.violations
        except AttributeError as exc:
            raise ExecutionIntentError(
                "ExecutionIntent.build() expects a policy guard result "
                "object with 'approved', 'action', 'risk_level', "
                "'position_size', and 'violations' attributes"
            ) from exc

        try:
            if approved:
                denial_reason = ""
                notes = f"execution intent ready for action={action}"
                ready = True
            else:
                if violations:
                    denial_reason = "; ".join(violations)
                else:
                    denial_reason = (
                        "policy guard result was not approved"
                    )
                notes = (
                    f"execution intent denied for action={action}: "
                    f"{denial_reason}"
                )
                ready = False

            return ExecutionIntentResult(
                ready=ready,
                action=action,
                risk_level=risk_level,
                position_size=position_size,
                denial_reason=denial_reason,
                notes=notes,
            )
        except ExecutionIntentError:
            raise
        except Exception as exc:
            raise ExecutionIntentError(
                f"Unexpected failure while building execution intent: {exc}"
            ) from exc