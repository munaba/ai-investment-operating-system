from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Tuple

from Database.account_constants import DEFAULT_ACCOUNT_BALANCE
from Services.base_service import BaseService
from Services.metadata_keys import MetadataKeys
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult

_DEFAULT_STOP_LOSS_PERCENT = 5.0
_DEFAULT_TAKE_PROFIT_PERCENT = 10.0
_DEFAULT_RISK_PER_TRADE_PERCENT = 1.0
# Activation 1.4: this used to be its own private literal
# (_DEFAULT_ACCOUNT_BALANCE = 100_000_000.0) duplicated independently of
# Core.bootstrap's default paper account balance. Both now import the
# same Database.account_constants.DEFAULT_ACCOUNT_BALANCE -- one place
# to change this number, not two that could silently drift apart.


class AnalysisPipeline:

    def __init__(
        self,
        stock_service: BaseService,
        technical_indicator_service: BaseService,
        moving_average_service: BaseService,
        technical_score_service: BaseService,
        fundamental_service: BaseService,
        backtest_service: BaseService,
        pattern_service: BaseService,
        chart_service: BaseService,
        news_service: BaseService,
        risk_management_service: BaseService,
        scoring_service: BaseService,
    ) -> None:
       
        self._services: List[BaseService] = [
            stock_service,
            technical_indicator_service,
            moving_average_service,
            technical_score_service,
            fundamental_service,
            backtest_service,
            pattern_service,
            chart_service,
            news_service,
            risk_management_service,
            scoring_service,
        ]

    def run(self, context: ServiceContext) -> Dict[str, ServiceResult]:
        
        results: List[Tuple[str, ServiceResult]] = []
        current_context = context

        for service in self._services:
            if service.name == "risk_management_service":
                current_context = self._prepare_risk_management_context(current_context)
            current_context, result = self._execute_step(service, current_context)
            results.append((service.name, result))

        return self._build_result_dict(results)

    def health_check(self) -> bool:
        
        return all(service.health_check() for service in self._services)

    @staticmethod
    def _prepare_risk_management_context(context: ServiceContext) -> ServiceContext:
       
        metadata = context.metadata
        additions: Dict[str, Any] = {}

        if (
            MetadataKeys.ENTRY_PRICE not in metadata
            and metadata.get(MetadataKeys.PRICE) is not None
        ):
            additions[MetadataKeys.ENTRY_PRICE] = metadata[MetadataKeys.PRICE]

        if MetadataKeys.STOP_LOSS_PERCENT not in metadata:
            additions[MetadataKeys.STOP_LOSS_PERCENT] = _DEFAULT_STOP_LOSS_PERCENT
        if MetadataKeys.TAKE_PROFIT_PERCENT not in metadata:
            additions[MetadataKeys.TAKE_PROFIT_PERCENT] = _DEFAULT_TAKE_PROFIT_PERCENT
        if MetadataKeys.RISK_PER_TRADE_PERCENT not in metadata:
            additions[MetadataKeys.RISK_PER_TRADE_PERCENT] = _DEFAULT_RISK_PER_TRADE_PERCENT
        if MetadataKeys.ACCOUNT_BALANCE not in metadata:
            additions[MetadataKeys.ACCOUNT_BALANCE] = DEFAULT_ACCOUNT_BALANCE

        if not additions:
            return context

        return replace(context, metadata={**metadata, **additions})

    def _execute_step(
        self, service: BaseService, context: ServiceContext
    ) -> Tuple[ServiceContext, ServiceResult]:
       
        result = service.execute(context)

        if result.success:
            enriched_metadata = {
                **context.metadata,
                **(result.data or {}),
                service.name: result.data,
            }
            context = replace(context, metadata=enriched_metadata)

        return context, result

    def _build_result_dict(
        self, results: List[Tuple[str, ServiceResult]]
    ) -> Dict[str, ServiceResult]:
        
        return dict(results)