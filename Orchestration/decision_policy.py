from __future__ import annotations

from dataclasses import dataclass

from Core.exceptions import AgentError


class DecisionPolicyError(AgentError):
    """Raised when DecisionPolicy.apply() encounters an unexpected failure.

    Mirrors the existing exception hierarchy (AgentError) used elsewhere
    in the codebase, rather than deriving from the bare Exception class.
    """
    pass


@dataclass(frozen=True)
class DecisionPolicyResult:
    """Immutable result of DecisionPolicy.apply().

    Stage L20A is intentionally minimal: a deterministic action -> policy
    mapping that translates a Decision's action into concrete entry/exit
    permissions, position sizing, and risk level. No history, no
    persistence, no reference back to whatever produced the decision.
    """
    action: str
    confidence: float
    position_size: float
    allow_entry: bool
    allow_exit: bool
    risk_level: str
    notes: str


class DecisionPolicy:
    """Pure, stateless component that maps a Decision to a DecisionPolicyResult.

    Design constraints (Stage L20A):
        - Stateless: no instance attributes, safe to reuse across calls.
        - Deterministic: same decision always produces the same result.
        - No LLM calls.
        - No Provider dependency.
        - No Database dependency.
        - No Runtime dependency.
        - No Memory dependency.
        - No Service dependency.

    DecisionPolicy never constructs, imports, or references any of the
    above, and does not import composition_root. It receives a plain
    ``decision`` object (with ``action`` and ``confidence`` attributes)
    and returns a ``DecisionPolicyResult``. It is not wired into
    StockAgent, RuntimeAnalysisPipeline, or ApplicationGraph -- it exists
    only as a standalone component, for a future stage to wire up.
    """

    _POLICIES = {
        "BUY": {
            "allow_entry": True,
            "allow_exit": False,
            "position_size": 1.0,
            "risk_level": "NORMAL",
        },
        "HOLD": {
            "allow_entry": False,
            "allow_exit": False,
            "position_size": 0.5,
            "risk_level": "LOW",
        },
        "SELL": {
            "allow_entry": False,
            "allow_exit": True,
            "position_size": 0.0,
            "risk_level": "HIGH",
        },
    }

    def apply(self, decision) -> DecisionPolicyResult:
        try:
            action = decision.action
        except AttributeError as exc:
            raise DecisionPolicyError(
                "DecisionPolicy.apply() expects a decision object with an "
                "'action' attribute"
            ) from exc

        policy = self._POLICIES.get(action)
        if policy is None:
            raise DecisionPolicyError(
                f"DecisionPolicy.apply() received an unrecognized action: "
                f"{action!r}"
            )

        confidence = getattr(decision, "confidence", 0.0)

        return DecisionPolicyResult(
            action=action,
            confidence=confidence,
            position_size=policy["position_size"],
            allow_entry=policy["allow_entry"],
            allow_exit=policy["allow_exit"],
            risk_level=policy["risk_level"],
            notes=f"policy applied for action={action}",
        )