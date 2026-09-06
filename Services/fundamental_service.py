from __future__ import annotations

import time
from typing import Any, Optional

from Core.logger import get_logger
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.metadata_keys import MetadataKeys

logger = get_logger(__name__)


class FundamentalService(BaseService):
    """Computes a fundamental score (0-100) from valuation and profitability metrics.

    This service is stateless and reusable: it takes fundamental metrics
    supplied via ``ServiceContext.metadata`` (PER, ROE, dividend yield, and
    their sector averages) and returns a computed fundamental score. It does
    not fetch or look up any data itself.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this service."""
        return "fundamental_service"

    @property
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        return "Computes a fundamental score (0-100) from PER, ROE, and dividend yield relative to sector averages."

    @property
    def category(self) -> str:
        """Logical grouping this service belongs to."""
        return "market_data"

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        """Compute elapsed milliseconds since ``started_at`` (a ``time.monotonic()`` reading)."""
        return (time.monotonic() - started_at) * 1000

    @staticmethod
    def _calculate_fundamental_score(
        per: Optional[float],
        roe: Optional[float],
        dividend_yield: Optional[float],
        per_rata_sektor: Optional[float],
        roe_rata_sektor: Optional[float],
    ) -> int:
        """Calculate the fundamental score from valuation/profitability metrics.

        Algorithm preserved identically from the legacy ``hitung_skor_fundamental``
        function.

        Args:
            per: Price-to-earnings ratio of the stock.
            roe: Return on equity of the stock.
            dividend_yield: Dividend yield of the stock (in percent, e.g. ``4`` for 4%).
            per_rata_sektor: Sector-average PER, used as a relative benchmark.
            roe_rata_sektor: Sector-average ROE, used as a relative benchmark.

        Returns:
            An integer score clamped to the ``[0, 100]`` range.
        """
        skor = 50

        if per is not None and per_rata_sektor is not None and per > 0:
            if per < per_rata_sektor * 0.8:
                skor += 20
            elif per > per_rata_sektor * 1.2:
                skor -= 15

        if roe is not None and roe_rata_sektor is not None and roe_rata_sektor != 0:
            if roe > roe_rata_sektor * 1.2:
                skor += 15
            elif roe < roe_rata_sektor * 0.8:
                skor -= 10

        if dividend_yield is not None:
            if dividend_yield > 4:
                skor += 15
            elif dividend_yield > 2:
                skor += 5

        return max(0, min(100, round(skor)))

    def execute(self, context: ServiceContext) -> ServiceResult:
        """Compute the fundamental score from metrics in ``context.metadata``.

        Reads ``per``, ``roe``, ``dividend_yield``, ``per_rata_sektor``, and
        ``roe_rata_sektor`` from ``context.metadata`` (all optional; missing
        values are treated as ``None``, matching the legacy function's
        behavior).

        This never raises for business-level failures (missing/invalid
        input) -- those are reported via ``ServiceResult.fail(...)`` instead,
        per ``BaseService``'s contract.

        Args:
            context: The request context to operate on.

        Returns:
            A successful ``ServiceResult`` with
            ``data={"fundamental_score"}`` on success, or a failed
            ``ServiceResult`` describing what went wrong.
        """
        started_at = time.monotonic()

        per = context.get_metadata(MetadataKeys.PER, None)
        roe = context.get_metadata(MetadataKeys.ROE, None)
        dividend_yield = context.get_metadata(MetadataKeys.DIVIDEND_YIELD, None)
        per_rata_sektor = context.get_metadata(MetadataKeys.PER_SECTOR_AVG, None)
        roe_rata_sektor = context.get_metadata(MetadataKeys.ROE_SECTOR_AVG, None)

        request_metadata = {
            MetadataKeys.PER: per,
            MetadataKeys.ROE: roe,
            MetadataKeys.DIVIDEND_YIELD: dividend_yield,
            MetadataKeys.PER_SECTOR_AVG: per_rata_sektor,
            MetadataKeys.ROE_SECTOR_AVG: roe_rata_sektor,
        }

        if per is None and roe is None and dividend_yield is None:
            return ServiceResult.fail(
                error=ValueError("Missing required fundamental metrics in context metadata"),
                message=(
                    "No fundamental metrics were provided. Supply at least one of "
                    "'per', 'roe', or 'dividend_yield' in context metadata."
                ),
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        try:
            fundamental_score = self._calculate_fundamental_score(
                per=per,
                roe=roe,
                dividend_yield=dividend_yield,
                per_rata_sektor=per_rata_sektor,
                roe_rata_sektor=roe_rata_sektor,
            )
        except Exception as exc:  # noqa: BLE001 - normalize any calculation failure
            return ServiceResult.fail(
                error=exc,
                message=f"Failed to compute fundamental score: {exc}",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        return ServiceResult.ok(
            data={MetadataKeys.FUNDAMENTAL_SCORE: fundamental_score},
            message=f"Computed fundamental score: {fundamental_score}.",
            metadata=request_metadata,
            execution_time_ms=self._elapsed_ms(started_at),
        )

    def health_check(self) -> bool:
        """Check whether this service can currently compute a fundamental score.

        Runs the calculation against a small synthetic sample. Never raises:
        any failure is caught, logged, and reported as ``False``.

        Returns:
            ``True`` if the calculation completed without error, ``False``
            otherwise.
        """
        try:
            self._calculate_fundamental_score(
                per=12.0,
                roe=0.18,
                dividend_yield=3.5,
                per_rata_sektor=15.0,
                roe_rata_sektor=0.15,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"FundamentalService health_check failed: {exc}")
            return False