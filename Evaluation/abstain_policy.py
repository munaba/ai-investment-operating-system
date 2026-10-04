"""L3 Abstain Policy -- reject when n < threshold or confidence < threshold.

Pure function: abstain(n_samples, confidence, min_samples, min_confidence) -> bool.

Returns True if the model should abstain (reject the prediction), False otherwise.
"""
from __future__ import annotations


def abstain(
    n_samples: int,
    confidence: float,
    min_samples: int = 30,
    min_confidence: float = 0.7,
) -> bool:
    """Return True if the model should abstain from making a prediction.

    Args:
        n_samples: Number of samples backing the prediction.
        confidence: Confidence score [0, 1].
        min_samples: Minimum samples required to make a prediction.
        min_confidence: Minimum confidence required to make a prediction.

    Returns:
        True if n_samples < min_samples OR confidence < min_confidence, False otherwise.
    """
    return n_samples < min_samples or confidence < min_confidence


# ponytail: no ranking-specific logic, no DB access, no yfinance fetch.
# Add walk-forward test when n >= 200 per class.
