from __future__ import annotations

from dataclasses import dataclass

from Core.exceptions import AgentError


class DecisionEngineError(AgentError):
    """Raised when DecisionEngine.decide() encounters an unexpected failure.

    Mirrors the existing exception hierarchy (AgentError) used elsewhere
    in the codebase, rather than deriving from the bare Exception class.
    """
    pass


@dataclass(frozen=True)
class Decision:
    """Immutable result of DecisionEngine.decide().

    Phase 1 is intentionally minimal: a deterministic score -> action
    mapping plus a confidence value and a short human-readable rationale.
    No history, no persistence, no reference back to whatever produced
    ``score`` -- that decoupling is the explicit point of this stage.
    """
    action: str
    confidence: float
    score: float
    rationale: str


class DecisionEngine:
    """Pure, stateless component that maps a composite score to a Decision.

    Design constraints (Stage L19, Phase 1):
        - Stateless: no instance attributes, safe to reuse across calls.
        - Deterministic: same score always produces the same Decision.
        - No LLM calls.
        - No Provider dependency.
        - No Database dependency.
        - No Runtime dependency.
        - No ServiceContext dependency.

    DecisionEngine never constructs, imports, or references any of the
    above. It receives a plain ``float`` from the caller and returns a
    ``Decision``. It is not wired into StockAgent or
    RuntimeAnalysisPipeline -- it exists on the object graph only as
    another constructed component, for a future stage to wire up.
    """

    _BUY_THRESHOLD = 70.0
    _HOLD_THRESHOLD = 45.0
    _SCORE_MIN = 0.0
    _SCORE_MAX = 100.0

    def decide(self, score: float) -> Decision:
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise DecisionEngineError(
                f"DecisionEngine.decide() expects a float score, "
                f"got {type(score).__name__}"
            )

        try:
            score_value = float(score)

            if score_value >= self._BUY_THRESHOLD:
                action = "BUY"
                rationale = (
                    f"score {score_value} >= {self._BUY_THRESHOLD} threshold for BUY"
                )
            elif score_value >= self._HOLD_THRESHOLD:
                action = "HOLD"
                rationale = (
                    f"score {score_value} in [{self._HOLD_THRESHOLD}, "
                    f"{self._BUY_THRESHOLD}) range for HOLD"
                )
            else:
                action = "SELL"
                rationale = (
                    f"score {score_value} < {self._HOLD_THRESHOLD} threshold for SELL"
                )

            confidence = self._normalize_confidence(score_value)

            return Decision(
                action=action,
                confidence=confidence,
                score=score_value,
                rationale=rationale,
            )
        except DecisionEngineError:
            raise
        except Exception as exc:
            raise DecisionEngineError(
                f"Unexpected failure while deciding on score={score!r}: {exc}"
            ) from exc

    def _normalize_confidence(self, score_value: float) -> float:
        """Normalize an arbitrary score onto a 0.0-1.0 confidence range.

        Clamps to [SCORE_MIN, SCORE_MAX] before dividing, so scores
        outside the nominal 0-100 band still yield a valid 0.0-1.0
        confidence instead of an out-of-range value.
        """
        clamped = max(self._SCORE_MIN, min(self._SCORE_MAX, score_value))
        return (clamped - self._SCORE_MIN) / (self._SCORE_MAX - self._SCORE_MIN)