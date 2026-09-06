from __future__ import annotations

import time

from Core.logger import get_logger
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.metadata_keys import MetadataKeys

logger = get_logger(__name__)


class ScoringService(BaseService):
    """Combines technical, fundamental, and pattern scores into a composite score.

    This service is stateless and reusable: it takes three already-computed
    component scores (technical, fundamental, pattern) supplied via
    ``ServiceContext.metadata`` and returns the weighted composite score
    plus its label ("BAGUS" / "NETRAL" / "LEMAH"). It does not compute any
    component score itself and does not fetch or look up any data.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this service."""
        return "scoring_service"

    @property
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        return (
            "Combines technical (45%), fundamental (35%), and pattern (20%) "
            "scores into a weighted composite score (0-100)."
        )

    @property
    def category(self) -> str:
        """Logical grouping this service belongs to."""
        return "market_data"

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        """Compute elapsed milliseconds since ``started_at`` (a ``time.monotonic()`` reading)."""
        return (time.monotonic() - started_at) * 1000

    @staticmethod
    def _calculate_composite_score(
        technical_score: float,
        fundamental_score: float,
        pattern_score: float,
    ) -> float:
        """Calculate the final weighted composite score.

        Algorithm preserved identically from the legacy
        ``hitung_skor_komposit`` function: technical 45%, fundamental 35%,
        pattern 20%.

        Args:
            technical_score: Technical score (0-100).
            fundamental_score: Fundamental score (0-100).
            pattern_score: Pattern-history score (0-100).

        Returns:
            The weighted composite score.
        """
        return (technical_score * 0.45) + (fundamental_score * 0.35) + (pattern_score * 0.20)

    @staticmethod
    def _label_for_score(overall_score: float) -> str:
        """Determine the qualitative label for the composite score.

        Thresholds preserved identically from the legacy
        ``hitung_skor_komposit`` function.

        Args:
            overall_score: The final composite score.

        Returns:
            ``"BAGUS"`` if ``overall_score >= 70``, ``"NETRAL"`` if
            ``overall_score >= 45``, otherwise ``"LEMAH"``.
        """
        if overall_score >= 70:
            return "BAGUS"
        elif overall_score >= 45:
            return "NETRAL"
        else:
            return "LEMAH"

    def execute(self, context: ServiceContext) -> ServiceResult:
        """Compute the composite score from component scores in ``context.metadata``.

        Reads ``technical_score``, ``fundamental_score``, and
        ``pattern_score`` (all required) from ``context.metadata``.

        This never raises for business-level failures (missing/invalid
        input) -- those are reported via ``ServiceResult.fail(...)`` instead,
        per ``BaseService``'s contract.

        Args:
            context: The request context to operate on.

        Returns:
            A successful ``ServiceResult`` with
            ``data={"technical_score", "fundamental_score", "pattern_score",
            "overall_score", "label"}`` on success, or a failed
            ``ServiceResult`` describing what went wrong.
        """
        started_at = time.monotonic()

        technical_score = context.get_metadata(MetadataKeys.TECHNICAL_SCORE, None)
        fundamental_score = context.get_metadata(MetadataKeys.FUNDAMENTAL_SCORE, None)
        pattern_score = context.get_metadata(MetadataKeys.PATTERN_SCORE, None)

        request_metadata = {
            MetadataKeys.TECHNICAL_SCORE: technical_score,
            MetadataKeys.FUNDAMENTAL_SCORE: fundamental_score,
            MetadataKeys.PATTERN_SCORE: pattern_score,
        }

        if technical_score is None or fundamental_score is None or pattern_score is None:
            return ServiceResult.fail(
                error=ValueError("Missing required component scores in context metadata"),
                message=(
                    "All of 'technical_score', 'fundamental_score', and 'pattern_score' "
                    "must be supplied in context metadata."
                ),
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        try:
            overall_score = self._calculate_composite_score(
                technical_score=technical_score,
                fundamental_score=fundamental_score,
                pattern_score=pattern_score,
            )
            label = self._label_for_score(overall_score)
        except Exception as exc:  # noqa: BLE001 - normalize any calculation failure
            return ServiceResult.fail(
                error=exc,
                message=f"Failed to compute composite score: {exc}",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        return ServiceResult.ok(
            data={
                MetadataKeys.TECHNICAL_SCORE: technical_score,
                MetadataKeys.FUNDAMENTAL_SCORE: fundamental_score,
                MetadataKeys.PATTERN_SCORE: pattern_score,
                MetadataKeys.OVERALL_SCORE: overall_score,
                MetadataKeys.LABEL: label,
            },
            message=f"Computed composite score: {overall_score:.1f} ({label}).",
            metadata=request_metadata,
            execution_time_ms=self._elapsed_ms(started_at),
        )

    def health_check(self) -> bool:
        """Check whether this service can currently compute a composite score.

        Runs the calculation against a small synthetic sample. Never raises:
        any failure is caught, logged, and reported as ``False``.

        Returns:
            ``True`` if the calculation completed without error, ``False``
            otherwise.
        """
        try:
            overall_score = self._calculate_composite_score(
                technical_score=70.0,
                fundamental_score=65.0,
                pattern_score=60.0,
            )
            self._label_for_score(overall_score)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"ScoringService health_check failed: {exc}")
            return False