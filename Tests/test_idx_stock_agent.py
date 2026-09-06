from Agents.idx_stock_agent import IDXStockAgent
from Agents.market_analysis_agent import MarketAnalysisAgent


class FakePlanner:
    pass


class FakeMemory:
    pass


class FakeExecutor:
    pass


def test_idx_stock_agent_construction_and_identity():
    planner = FakePlanner()
    memory = FakeMemory()
    executor = FakeExecutor()
    provider_manager = object()
    tool_context_builder = object()
    instrument_extractor = object()
    service_pipeline = object()
    default_provider_name = "gemini"

    agent = IDXStockAgent(
        planner,
        memory,
        executor,
        provider_manager,
        tool_context_builder,
        instrument_extractor,
        service_pipeline,
        default_provider_name,
    )

    assert isinstance(agent, MarketAnalysisAgent)
    assert agent.name == "idx_stock_agent"

    assert agent._planner is planner
    assert agent._memory is memory
    assert agent._executor is executor
    assert agent._provider_manager is provider_manager
    assert agent._tool_context_builder is tool_context_builder
    assert agent._instrument_extractor is instrument_extractor
    assert agent._service_pipeline is service_pipeline
    assert agent._default_provider_name == "gemini"