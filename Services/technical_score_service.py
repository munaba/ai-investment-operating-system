from __future__ import annotations

import time
from typing import Optional

import pandas as pd

from Core.logger import get_logger
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.metadata_keys import MetadataKeys

logger = get_logger(__name__)


class TechnicalScoreService(BaseService):
    """Computes a composite technical score from price, MA, RSI, and Bollinger Band values.

    This service is stateless and reusable: it takes previously-computed
    technical values supplied via ``ServiceContext.metadata`` (e.g. produced
    by ``TechnicalIndicatorService`` and ``MovingAverageService``) and
    returns a single composite technical score. It does not compute
    indicators itself.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this service."""
        return "technical_score_service"

    @property
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        return "Computes a composite technical score (0-100) from price, MA20/MA50/MA200, RSI, and Bollinger Band."

    @property
    def category(self) -> str:
        """Logical grouping this service belongs to."""
        return "market_data"

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        """Compute elapsed milliseconds since ``started_at`` (a ``time.monotonic()`` reading)."""
        return (time.monotonic() - started_at) * 1000

    @staticmethod
    def _calculate_technical_score(
        rsi: Optional[float],
        harga: Optional[float],
        ma20: Optional[float],
        ma50: Optional[float],
        ma200: Optional[float],
        upper_band: Optional[float],
        lower_band: Optional[float],
    ) -> int:
        """Calculate the composite technical score.

        Algorithm preserved identically from the legacy
        ``hitung_skor_teknikal`` function.

        Args:
            rsi: Latest RSI value.
            harga: Latest closing price.
            ma20: Latest MA20 value.
            ma50: Latest MA50 value.
            ma200: Latest MA200 value.
            upper_band: Latest Bollinger Band upper value.
            lower_band: Latest Bollinger Band lower value.

        Returns:
            The composite technical score, clamped to the ``[0, 100]`` range.
        """
        skor = 50

        if rsi is not None and not pd.isna(rsi):
            if rsi < 30:
                skor += 20
            elif rsi < 45:
                skor += 8
            elif rsi > 70:
                skor -= 20
            elif rsi > 55:
                skor -= 8

        if harga is not None and ma20 is not None and ma50 is not None and not pd.isna(ma20) and not pd.isna(ma50):
            if harga > ma20 and harga > ma50:
                skor += 15
            elif harga < ma20 and harga < ma50:
                skor -= 15

        if harga is not None and ma200 is not None and not pd.isna(ma200):
            skor += 10 if harga > ma200 else -10

        if harga is not None and upper_band is not None and lower_band is not None:
            lebar_band = upper_band - lower_band
            if lebar_band > 0:
                posisi = (harga - lower_band) / lebar_band
                if posisi < 0.2:
                    skor += 10
                elif posisi > 0.8:
                    skor -= 10

        return max(0, min(100, round(skor)))

    def execute(self, context: ServiceContext) -> ServiceResult:
        """Compute the composite technical score from values in ``context.metadata``.

        Reads ``harga``, ``ma20``, ``ma50``, ``ma200``, ``rsi``,
        ``bollinger_upper``, and ``bollinger_lower`` from ``context.metadata``.
        This never raises for business-level failures (missing/invalid input) --
        those are reported via ``ServiceResult.fail(...)`` instead, per
        ``BaseService``'s contract.

        Args:
            context: The request context to operate on. Must contain
                ``harga`` in its metadata; all other fields are optional,
                matching the legacy algorithm's ``None``-tolerant behavior.

        Returns:
            A successful ``ServiceResult`` with ``data={"technical_score"}``
            on success, or a failed ``ServiceResult`` describing what went
            wrong.
        """
        started_at = time.monotonic()

        harga = context.get_metadata(MetadataKeys.PRICE, None)
        request_metadata = {"harga_provided": harga is not None}

        if harga is None:
            return ServiceResult.fail(
                error=ValueError("Missing required 'harga' in context metadata"),
                message="No price was provided. Supply 'harga' in context metadata.",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        try:
            rsi = context.get_metadata(MetadataKeys.RSI, None)
            ma20 = context.get_metadata(MetadataKeys.MA20, None)
            ma50 = context.get_metadata(MetadataKeys.MA50, None)
            ma200 = context.get_metadata(MetadataKeys.MA200, None)
            upper_band = context.get_metadata(MetadataKeys.BOLLINGER_UPPER, None)
            lower_band = context.get_metadata(MetadataKeys.BOLLINGER_LOWER, None)

            technical_score = self._calculate_technical_score(
                rsi=rsi,
                harga=harga,
                ma20=ma20,
                ma50=ma50,
                ma200=ma200,
                upper_band=upper_band,
                lower_band=lower_band,
            )
        except Exception as exc:  # noqa: BLE001 - normalize any calculation failure
            return ServiceResult.fail(
                error=exc,
                message=f"Failed to compute technical score: {exc}",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        return ServiceResult.ok(
            data={
                MetadataKeys.TECHNICAL_SCORE: technical_score,
            },
            message="Computed composite technical score.",
            metadata=request_metadata,
            execution_time_ms=self._elapsed_ms(started_at),
        )

    def health_check(self) -> bool:
        """Check whether this service can currently compute the technical score.

        Runs the calculation against a small synthetic sample. Never raises:
        any failure is caught, logged, and reported as ``False``.

        Returns:
            ``True`` if the calculation completed without error, ``False``
            otherwise.
        """
        try:
            self._calculate_technical_score(
                rsi=25.0,
                harga=105.0,
                ma20=100.0,
                ma50=98.0,
                ma200=90.0,
                upper_band=110.0,
                lower_band=95.0,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"TechnicalScoreService health_check failed: {exc}")
            return False