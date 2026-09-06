from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from Core.exceptions import AgentError

_VALID_RISK_LEVELS = ("LOW", "NORMAL", "HIGH")


class PolicyGuardError(AgentError):
    """Raised when PolicyGuard.evaluate() encounters an unexpected failure.

    Mirrors the existing exception hierarchy (AgentError) used elsewhere
    in the codebase (ReflectionError, DecisionEngineError,
    DecisionPolicyError), rather than deriving from the bare Exception
    class.
    """
    pass


@dataclass(frozen=True)
class PolicyGuardResult:
    """Immutable result of PolicyGuard.evaluate().

    Stage L21 is intentionally minimal: a deterministic set of
    guard-rail checks run against an already-produced policy result
    (e.g. a ``DecisionPolicyResult``), yielding a single ``approved``
    verdict plus the specific ``violations`` (if any) that produced it.
    No history, no persistence, no reference back to whatever produced
    the policy result it was given.
    """
    approved: bool
    action: str
    risk_level: str
    position_size: float
    violations: Tuple[str, ...]
    notes: str


class PolicyGuard:
    """Pure, stateless component that validates a policy result against
    a fixed set of deterministic guard-rail checks.

    Design constraints (Stage L21, following the exact L18/L19/L20
    additive pattern):
        - Stateless: no instance attributes, safe to reuse across calls.
        - Deterministic: same policy result always produces the same
          PolicyGuardResult.
        - No LLM calls.
        - No Provider dependency.
        - No Database dependency.
        - No Runtime dependency.
        - No Memory dependency.
        - No Service dependency.

    PolicyGuard never constructs, imports, or references any of the
    above, and does not import composition_root or DecisionPolicy. It
    receives a plain ``policy_result`` object (with ``action``,
    ``confidence``, ``position_size``, ``allow_entry``, ``allow_exit``,
    and ``risk_level`` attributes -- the same shape as
    ``Orchestration.decision_policy.DecisionPolicyResult``, accessed
    purely by duck typing, never imported) and returns a
    ``PolicyGuardResult``. It is not wired into StockAgent,
    RuntimeAnalysisPipeline, DecisionPolicy, or ApplicationGraph's
    production call path -- it exists only as a standalone component,
    for a future stage to wire up.

    Guard rules applied (all three are checked independently, so more
    than one violation can be reported for a single policy result):
        - ``allow_entry`` and ``allow_exit`` must not both be True
          (a policy result cannot simultaneously permit opening and
          closing a position).
        - ``position_size`` must fall within the inclusive ``[0.0, 1.0]``
          range.
        - ``risk_level`` must be one of ``"LOW"``, ``"NORMAL"``,
          ``"HIGH"``.

    A policy result with zero violations is ``approved=True``; any
    violation makes it ``approved=False``.
    """

    def evaluate(self, policy_result) -> PolicyGuardResult:
        try:
            action = policy_result.action
            position_size = policy_result.position_size
            allow_entry = policy_result.allow_entry
            allow_exit = policy_result.allow_exit
            risk_level = policy_result.risk_level
        except AttributeError as exc:
            raise PolicyGuardError(
                "PolicyGuard.evaluate() expects a policy result object "
                "with 'action', 'position_size', 'allow_entry', "
                "'allow_exit', and 'risk_level' attributes"
            ) from exc

        try:
            violations = []

            if allow_entry and allow_exit:
                violations.append(
                    "conflicting entry/exit flags: allow_entry and "
                    "allow_exit are both True"
                )

            if (
                isinstance(position_size, bool)
                or not isinstance(position_size, (int, float))
                or not (0.0 <= float(position_size) <= 1.0)
            ):
                violations.append(
                    f"position_size out of range: {position_size!r} is "
                    "not within [0.0, 1.0]"
                )

            if risk_level not in _VALID_RISK_LEVELS:
                violations.append(
                    f"unrecognized risk_level: {risk_level!r} is not one "
                    f"of {_VALID_RISK_LEVELS}"
                )

            approved = len(violations) == 0
            violations_tuple = tuple(violations)

            if approved:
                notes = f"policy result for action={action} approved"
            else:
                notes = (
                    f"policy result for action={action} rejected: "
                    f"{'; '.join(violations_tuple)}"
                )

            return PolicyGuardResult(
                approved=approved,
                action=action,
                risk_level=risk_level,
                position_size=position_size,
                violations=violations_tuple,
                notes=notes,
            )
        except PolicyGuardError:
            raise
        except Exception as exc:
            raise PolicyGuardError(
                f"Unexpected failure while evaluating policy result: {exc}"
            ) from exc