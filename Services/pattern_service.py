from __future__ import annotations

import time
from typing import Optional

from Core.logger import get_logger
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.metadata_keys import MetadataKeys

logger = get_logger(__name__)


class PatternService(BaseService):
    """Computes a pattern-history score (0-100) from historical pattern statistics.

    This service is stateless and reusable: it takes pattern statistics
    supplied via ``ServiceContext.metadata`` (win rate and average return of
    historically similar patterns) and returns a computed pattern score. It
    does not fetch, search for, or look up any pattern data itself.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this service."""
        return "pattern_service"

    @property
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        return "Computes a pattern-history score (0-100) from win rate and average return of historically similar patterns."

    @property
    def category(self) -> str:
        """Logical grouping this service belongs to."""
        return "market_data"

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        """Compute elapsed milliseconds since ``started_at`` (a ``time.monotonic()`` reading)."""
        return (time.monotonic() - started_at) * 1000

    @staticmethod
    def _calculate_pattern_score(
        win_rate: Optional[float],
        rata_rata_return: Optional[float],
    ) -> int:
        """Calculate the pattern-history score.

        Algorithm preserved identically from the legacy ``hitung_skor_pola``
        function.

        Args:
            win_rate: Win rate (in percent) of historically similar patterns.
            rata_rata_return: Average return (in percent) of historically
                similar patterns.

        Returns:
            An integer score clamped to the ``[0, 100]`` range. Defaults to
            ``50`` when either input is missing, matching the legacy
            function's behavior.
        """
        if win_rate is None or rata_rata_return is None:
            return 50

        skor = win_rate
        if rata_rata_return > 5:
            skor += 10
        elif rata_rata_return < -5:
            skor -= 10

        return max(0, min(100, round(skor)))

    def execute(self, context: ServiceContext) -> ServiceResult:
        """Compute the pattern score from statistics in ``context.metadata``.

        Reads ``win_rate`` and ``rata_rata_return`` from
        ``context.metadata``. Both are optional inputs individually --
        matching the legacy function's behavior of returning a neutral
        score of ``50`` when either is missing -- but at least one of them
        must be present in the context for this service to run.

        This never raises for business-level failures (missing/invalid
        input) -- those are reported via ``ServiceResult.fail(...)`` instead,
        per ``BaseService``'s contract.

        Args:
            context: The request context to operate on.

        Returns:
            A successful ``ServiceResult`` with ``data={"pattern_score"}``
            on success, or a failed ``ServiceResult`` describing what went
            wrong.
        """
        started_at = time.monotonic()

        win_rate = context.get_metadata(MetadataKeys.WIN_RATE, None)
        rata_rata_return = context.get_metadata(MetadataKeys.AVG_RETURN, None)

        request_metadata = {
            MetadataKeys.WIN_RATE: win_rate,
            MetadataKeys.AVG_RETURN: rata_rata_return,
        }

        if win_rate is None and rata_rata_return is None:
            return ServiceResult.fail(
                error=ValueError("Missing required pattern statistics in context metadata"),
                message=(
                    "No pattern statistics were provided. Supply at least one of "
                    "'win_rate' or 'rata_rata_return' in context metadata."
                ),
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        try:
            pattern_score = self._calculate_pattern_score(
                win_rate=win_rate,
                rata_rata_return=rata_rata_return,
            )
        except Exception as exc:  # noqa: BLE001 - normalize any calculation failure
            return ServiceResult.fail(
                error=exc,
                message=f"Failed to compute pattern score: {exc}",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        return ServiceResult.ok(
            data={MetadataKeys.PATTERN_SCORE: pattern_score},
            message=f"Computed pattern score: {pattern_score}.",
            metadata=request_metadata,
            execution_time_ms=self._elapsed_ms(started_at),
        )

    def health_check(self) -> bool:
        """Check whether this service can currently compute a pattern score.

        Runs the calculation against a small synthetic sample. Never raises:
        any failure is caught, logged, and reported as ``False``.

        Returns:
            ``True`` if the calculation completed without error, ``False``
            otherwise.
        """
        try:
            self._calculate_pattern_score(win_rate=60.0, rata_rata_return=6.0)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"PatternService health_check failed: {exc}")
            return False