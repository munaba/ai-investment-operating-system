from __future__ import annotations

import time
from typing import Optional

from Core.logger import get_logger
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.metadata_keys import MetadataKeys

logger = get_logger(__name__)


class RiskManagementService(BaseService):
    """Computes risk management parameters for a trade.

    This service is stateless and reusable: given an entry price and a set
    of risk parameters, it computes the stop loss price, take profit price,
    risk amount, position size, and risk/reward ratio. It does not decide
    whether to enter a trade (no BUY/SELL decision) -- it only derives
    parameters from the input supplied via ``ServiceContext.metadata``.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this service."""
        return "risk_management_service"

    @property
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        return "Computes stop loss, take profit, risk amount, position size, and risk/reward ratio for a trade."

    @property
    def category(self) -> str:
        """Logical grouping this service belongs to."""
        return "risk_management"

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        """Compute elapsed milliseconds since ``started_at`` (a ``time.monotonic()`` reading)."""
        return (time.monotonic() - started_at) * 1000

    @staticmethod
    def _calculate_risk_parameters(
        entry_price: float,
        stop_loss_percent: float,
        take_profit_percent: float,
        risk_per_trade_percent: float,
        account_balance: float,
    ) -> tuple[float, float, float, float, Optional[float]]:
        """Calculate risk management parameters for a long position.

        Args:
            entry_price: Planned entry price of the trade.
            stop_loss_percent: Stop loss distance from entry, as a percentage.
            take_profit_percent: Take profit distance from entry, as a percentage.
            risk_per_trade_percent: Fraction of account balance to risk on
                this trade, as a percentage.
            account_balance: Total account balance available.

        Returns:
            A ``(stop_loss_price, take_profit_price, risk_amount,
            position_size, risk_reward_ratio)`` tuple. ``position_size`` and
            ``risk_reward_ratio`` are ``None`` if the risk per unit is not
            positive (i.e. ``stop_loss_price >= entry_price``), since they
            would otherwise be undefined/infinite.
        """
        stop_loss_price = entry_price * (1 - stop_loss_percent / 100)
        take_profit_price = entry_price * (1 + take_profit_percent / 100)
        risk_amount = account_balance * (risk_per_trade_percent / 100)

        risk_per_unit = entry_price - stop_loss_price
        reward_per_unit = take_profit_price - entry_price

        if risk_per_unit <= 0:
            return stop_loss_price, take_profit_price, risk_amount, None, None

        position_size = risk_amount / risk_per_unit
        risk_reward_ratio = reward_per_unit / risk_per_unit

        return stop_loss_price, take_profit_price, risk_amount, position_size, risk_reward_ratio

    def execute(self, context: ServiceContext) -> ServiceResult:
        """Compute risk management parameters from values in ``context.metadata``.

        Reads ``entry_price``, ``stop_loss_percent``, ``take_profit_percent``,
        ``risk_per_trade_percent``, and ``account_balance`` from
        ``context.metadata``. All fields are required. This never raises for
        business-level failures (missing/invalid input) -- those are
        reported via ``ServiceResult.fail(...)`` instead, per
        ``BaseService``'s contract.

        Args:
            context: The request context to operate on. Must contain all
                required fields in its metadata.

        Returns:
            A successful ``ServiceResult`` with
            ``data={"stop_loss_price", "take_profit_price", "risk_amount",
            "position_size", "risk_reward_ratio"}`` on success, or a failed
            ``ServiceResult`` describing what went wrong.
        """
        started_at = time.monotonic()

        required_fields = (
            MetadataKeys.ENTRY_PRICE,
            MetadataKeys.STOP_LOSS_PERCENT,
            MetadataKeys.TAKE_PROFIT_PERCENT,
            MetadataKeys.RISK_PER_TRADE_PERCENT,
            MetadataKeys.ACCOUNT_BALANCE,
        )
        values = {field: context.get_metadata(field, None) for field in required_fields}
        request_metadata = {field: (value is not None) for field, value in values.items()}

        missing = [field for field, value in values.items() if value is None]
        if missing:
            return ServiceResult.fail(
                error=ValueError(f"Missing required field(s) in context metadata: {sorted(missing)}"),
                message=f"Missing required field(s): {', '.join(sorted(missing))}.",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        entry_price = values[MetadataKeys.ENTRY_PRICE]
        stop_loss_percent = values[MetadataKeys.STOP_LOSS_PERCENT]
        take_profit_percent = values[MetadataKeys.TAKE_PROFIT_PERCENT]
        risk_per_trade_percent = values[MetadataKeys.RISK_PER_TRADE_PERCENT]
        account_balance = values[MetadataKeys.ACCOUNT_BALANCE]

        if entry_price <= 0:
            return ServiceResult.fail(
                error=ValueError("'entry_price' must be greater than zero"),
                message="'entry_price' must be greater than zero.",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        if stop_loss_percent <= 0:
            return ServiceResult.fail(
                error=ValueError("'stop_loss_percent' must be greater than zero"),
                message="'stop_loss_percent' must be greater than zero.",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        if take_profit_percent <= 0:
            return ServiceResult.fail(
                error=ValueError("'take_profit_percent' must be greater than zero"),
                message="'take_profit_percent' must be greater than zero.",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        if risk_per_trade_percent <= 0:
            return ServiceResult.fail(
                error=ValueError("'risk_per_trade_percent' must be greater than zero"),
                message="'risk_per_trade_percent' must be greater than zero.",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        if account_balance <= 0:
            return ServiceResult.fail(
                error=ValueError("'account_balance' must be greater than zero"),
                message="'account_balance' must be greater than zero.",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        try:
            (
                stop_loss_price,
                take_profit_price,
                risk_amount,
                position_size,
                risk_reward_ratio,
            ) = self._calculate_risk_parameters(
                entry_price=entry_price,
                stop_loss_percent=stop_loss_percent,
                take_profit_percent=take_profit_percent,
                risk_per_trade_percent=risk_per_trade_percent,
                account_balance=account_balance,
            )
        except Exception as exc:  # noqa: BLE001 - normalize any calculation failure
            return ServiceResult.fail(
                error=exc,
                message=f"Failed to compute risk management parameters: {exc}",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        if position_size is None or risk_reward_ratio is None:
            return ServiceResult.fail(
                error=ValueError("'stop_loss_percent' does not produce a positive risk per unit"),
                message=(
                    "Computed stop loss price is not below entry price, so position size and "
                    "risk/reward ratio are undefined."
                ),
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        return ServiceResult.ok(
            data={
                MetadataKeys.STOP_LOSS_PRICE: stop_loss_price,
                MetadataKeys.TAKE_PROFIT_PRICE: take_profit_price,
                MetadataKeys.RISK_AMOUNT: risk_amount,
                MetadataKeys.POSITION_SIZE: position_size,
                MetadataKeys.RISK_REWARD_RATIO: risk_reward_ratio,
            },
            message="Computed risk management parameters.",
            metadata=request_metadata,
            execution_time_ms=self._elapsed_ms(started_at),
        )

    def health_check(self) -> bool:
        """Check whether this service can currently compute risk parameters.

        Runs the calculation against a small synthetic sample. Never raises:
        any failure is caught, logged, and reported as ``False``.

        Returns:
            ``True`` if the calculation completed without error, ``False``
            otherwise.
        """
        try:
            self._calculate_risk_parameters(
                entry_price=100.0,
                stop_loss_percent=2.0,
                take_profit_percent=4.0,
                risk_per_trade_percent=1.0,
                account_balance=10_000_000.0,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"RiskManagementService health_check failed: {exc}")
            return False