"""L3 Calibration Metrics -- Brier score, ECE, reliability bins.

Pure functions for measuring probabilistic calibration.
Brier score: mean squared error between predicted probability and binary outcome.
ECE (Expected Calibration Error): binned calibration metric.
"""
from __future__ import annotations

from typing import List, Tuple


def brier_score(probabilities: List[float], outcomes: List[int]) -> float:
    """Brier score: mean((p - outcome)^2).

    Args:
        probabilities: Predicted probabilities [0, 1].
        outcomes: Binary outcomes (0 or 1).

    Returns:
        Brier score [0, 1]. Lower is better. 0 = perfect calibration.
    """
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have same length")
    if not probabilities:
        return 0.0

    return sum((p - o) ** 2 for p, o in zip(probabilities, outcomes)) / len(probabilities)


def ece(
    probabilities: List[float],
    outcomes: List[int],
    n_bins: int = 10,
) -> float:
    """Expected Calibration Error (ECE).

    Bins predicted probabilities, computes average predicted probability and
    actual outcome frequency per bin, weighted by bin size.

    Args:
        probabilities: Predicted probabilities [0, 1].
        outcomes: Binary outcomes (0 or 1).
        n_bins: Number of bins (default 10).

    Returns:
        ECE [0, 1]. Lower is better. 0 = perfect calibration.
    """
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have same length")
    if not probabilities:
        return 0.0

    bins: List[List[Tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, o in zip(probabilities, outcomes):
        bin_idx = min(int(p * n_bins), n_bins - 1)
        bins[bin_idx].append((p, o))

    total = len(probabilities)
    ece_sum = 0.0
    for bin_items in bins:
        if not bin_items:
            continue
        avg_pred = sum(p for p, _ in bin_items) / len(bin_items)
        avg_outcome = sum(o for _, o in bin_items) / len(bin_items)
        ece_sum += len(bin_items) * abs(avg_pred - avg_outcome)

    return ece_sum / total


def reliability_bins(
    probabilities: List[float],
    outcomes: List[int],
    n_bins: int = 10,
) -> List[Tuple[float, float, int]]:
    """Reliability diagram data: (avg_pred, avg_outcome, count) per bin.

    Args:
        probabilities: Predicted probabilities [0, 1].
        outcomes: Binary outcomes (0 or 1).
        n_bins: Number of bins (default 10).

    Returns:
        List of (avg_predicted_prob, avg_actual_outcome, bin_count) tuples,
        one per bin. Empty bins are omitted.
    """
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have same length")

    bins: List[List[Tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, o in zip(probabilities, outcomes):
        bin_idx = min(int(p * n_bins), n_bins - 1)
        bins[bin_idx].append((p, o))

    result = []
    for bin_items in bins:
        if not bin_items:
            continue
        avg_pred = sum(p for p, _ in bin_items) / len(bin_items)
        avg_outcome = sum(o for _, o in bin_items) / len(bin_items)
        result.append((avg_pred, avg_outcome, len(bin_items)))

    return result


# ponytail: no model-specific logic, no ranking integration, no DB.
# Add walk-forward test when n >= 200 per class.
