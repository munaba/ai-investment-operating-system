from Agents.market_analysis_agent import MarketAnalysisAgent


class IDXStockAgent(MarketAnalysisAgent):
    def __init__(
        self,
        planner,
        memory,
        executor,
        provider_manager,
        tool_context_builder,
        instrument_extractor,
        service_pipeline,
        default_provider_name,
    ):
        super().__init__(
            planner,
            memory,
            executor,
            provider_manager,
            tool_context_builder,
            instrument_extractor,
            service_pipeline,
            default_provider_name,
        )

    @property
    def name(self) -> str:
        return "idx_stock_agent"