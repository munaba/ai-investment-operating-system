"""AnalysisPipeline orchestrates the fixed 11-step analysis service chain.

Not an Agent, not a Service, not a Planner -- a pure orchestration helper
called by Executor. Contains no business logic; all business logic lives
in the injected services themselves.

See docs/analysis_pipeline.md for the full contract this class implements.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Tuple

from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult


class AnalysisPipeline:
    """Orchestrates the fixed 11-step analysis service chain.

    See docs/analysis_pipeline.md for the contract this class implements,
    including the accumulating-context data flow (SS5) and the
    skip-on-fail error handling policy (SS6).
    """

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
        """Wire up the fixed service chain, in execution order.

        Args:
            stock_service: Provides raw price data.
            technical_indicator_service: Computes technical indicators.
            moving_average_service: Computes moving averages.
            technical_score_service: Computes technical score.
            fundamental_service: Provides fundamental data.
            backtest_service: Runs backtest analysis. Runs before
                ``pattern_service`` because ``PatternService`` depends on
                the ``win_rate`` produced by ``BacktestService``.
            pattern_service: Matches price patterns.
            chart_service: Generates chart output.
            news_service: Provides news sentiment.
            risk_management_service: Computes risk/stop-loss data.
            scoring_service: Computes the final composite score.
        """
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
        """Run all configured services in order.

        Each service receives the context accumulated from prior
        successful services (docs/analysis_pipeline.md SS5). A failed
        service does not stop the pipeline (SS6, skip-on-fail): the next
        service still runs, using the context as it stood before the
        failed step.

        Args:
            context: Initial ServiceContext for this request.

        Returns:
            A dict mapping each service's name to its ServiceResult, with
            exactly one entry per configured service.
        """
        results: List[Tuple[str, ServiceResult]] = []
        current_context = context

        for service in self._services:
            current_context, result = self._execute_step(service, current_context)
            results.append((service.name, result))

        return self._build_result_dict(results)

    def health_check(self) -> bool:
        """Aggregate health check across all configured services.

        Returns:
            True only if every configured service reports healthy.
        """
        return all(service.health_check() for service in self._services)

    def _execute_step(
        self, service: BaseService, context: ServiceContext
    ) -> Tuple[ServiceContext, ServiceResult]:
        """Execute a single service and enrich context only on success.

        Per docs/analysis_pipeline.md SS5, only a successful ServiceResult
        may enrich the ServiceContext, and enrichment never mutates the
        incoming context in place -- a new ServiceContext instance is
        produced instead. On failure, the original context is returned
        unchanged (SS6, skip-on-fail).

        Enrichment writes `result.data` into `context.metadata` under a
        key equal to `service.name` (nested propagation, unchanged), and
        additionally merges `result.data`'s own keys into the top level of
        `context.metadata` (flat propagation), so downstream services can
        read a prior step's output either via
        `context.metadata[service.name]` or directly via its individual
        keys, without requiring any service to change how it reads
        metadata.

        Args:
            service: The service to execute.
            context: Context accumulated from prior successful steps.

        Returns:
            A tuple of (context to use for the next step, ServiceResult
            from this step).
        """
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
        """Convert an ordered list of (name, result) pairs into a dict.

        Args:
            results: Ordered (service_name, ServiceResult) pairs, one per
                configured service.

        Returns:
            Dict mapping service name to its ServiceResult.
        """
        return dict(results)