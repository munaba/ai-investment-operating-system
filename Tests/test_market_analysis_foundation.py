from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import unittest

from Orchestration.analysis_pipeline_adapter import AnalysisPipelineAdapter
from Orchestration.service_pipeline import ServicePipeline
from Orchestration.instrument_extractor import IDXTickerExtractor
from Agents.market_analysis_agent import MarketAnalysisAgent


# ---------------------------------------------------------------------------
# 1. AnalysisPipelineAdapter — pure delegation
# ---------------------------------------------------------------------------

class FakeAnalysisPipeline:
    """Lightweight stand-in for AnalysisPipeline. No inheritance required —
    AnalysisPipelineAdapter should only care that run()/health_check() exist.
    """

    def __init__(self):
        self.run_calls = 0
        self.health_check_calls = 0
        self._run_return_value = {"sentinel": object()}
        self._health_return_value = object()

    def run(self, context):
        self.run_calls += 1
        self.last_run_context = context
        return self._run_return_value

    def health_check(self):
        self.health_check_calls += 1
        return self._health_return_value


class TestAnalysisPipelineAdapterDelegation(unittest.TestCase):
    def setUp(self):
        self.fake_pipeline = FakeAnalysisPipeline()
        self.adapter = AnalysisPipelineAdapter(self.fake_pipeline)

    def test_run_returns_exact_wrapped_value_with_no_transformation(self):
        context = object()  # sentinel: adapter must not copy/mutate this
        result = self.adapter.run(context)

        self.assertIs(
            result,
            self.fake_pipeline._run_return_value,
            "adapter.run(...) must return exactly the wrapped pipeline's "
            "return value (identity match), not a copy or transformation.",
        )
        self.assertEqual(
            self.fake_pipeline.run_calls,
            1,
            "Wrapped pipeline's run() must be called exactly once.",
        )
        self.assertIs(
            self.fake_pipeline.last_run_context,
            context,
            "adapter.run(...) must forward the exact context object it "
            "received, with no copying.",
        )

    def test_health_check_returns_exact_wrapped_value(self):
        result = self.adapter.health_check()

        self.assertIs(
            result,
            self.fake_pipeline._health_return_value,
            "adapter.health_check() must return exactly the wrapped "
            "pipeline's return value (identity match).",
        )
        self.assertEqual(
            self.fake_pipeline.health_check_calls,
            1,
            "Wrapped pipeline's health_check() must be called exactly once.",
        )

    def test_run_and_health_check_are_independent_pure_delegations(self):
        # Calling both should not cross-increment each other's counters,
        # confirming there is no shared/transformed state in between.
        self.adapter.run(object())
        self.adapter.health_check()

        self.assertEqual(self.fake_pipeline.run_calls, 1)
        self.assertEqual(self.fake_pipeline.health_check_calls, 1)


# ---------------------------------------------------------------------------
# 2. ServicePipeline — placeholder
# ---------------------------------------------------------------------------

class TestServicePipelinePlaceholder(unittest.TestCase):
    def setUp(self):
        self.service_pipeline = ServicePipeline([])

    def test_health_check_returns_true(self):
        self.assertIs(
            self.service_pipeline.health_check(),
            True,
            "ServicePipeline.health_check() must return True even though "
            "run() is not yet implemented.",
        )

    def test_run_raises_not_implemented_error(self):
        with self.assertRaises(NotImplementedError):
            self.service_pipeline.run(object())


# ---------------------------------------------------------------------------
# 3. IDXTickerExtractor — placeholder
# ---------------------------------------------------------------------------

class TestIDXTickerExtractorPlaceholder(unittest.TestCase):
    def setUp(self):
        self.extractor = IDXTickerExtractor()

    def test_extract_raises_not_implemented_error(self):
        # Intentionally not testing regex behavior yet -- this class is a
        # placeholder and must fail loudly rather than guess at a ticker.
        with self.assertRaises(NotImplementedError):
            self.extractor.extract("BBCA")


# ---------------------------------------------------------------------------
# 4. MarketAnalysisAgent — construction / exact dependency wiring
# ---------------------------------------------------------------------------

class FakePlanner:
    pass


class FakeMemory:
    pass


class FakeExecutor:
    pass


class DummyAgent(MarketAnalysisAgent):
    """Minimal concrete subclass. Only `name` is overridden, per the
    requirement that we do not exercise run/chat/health_check here."""

    @property
    def name(self):
        return "dummy"


class TestMarketAnalysisAgentConstruction(unittest.TestCase):
    def setUp(self):
        self.planner = FakePlanner()
        self.memory = FakeMemory()
        self.executor = FakeExecutor()
        self.provider_manager = object()
        self.tool_context_builder = object()
        self.instrument_extractor = object()
        self.service_pipeline = object()

        self.agent = DummyAgent(
            self.planner,
            self.memory,
            self.executor,
            self.provider_manager,
            self.tool_context_builder,
            self.instrument_extractor,
            self.service_pipeline,
            "default",
        )

    def test_construction_succeeds(self):
        self.assertIsInstance(self.agent, DummyAgent)
        self.assertEqual(self.agent.name, "dummy")

    def test_base_agent_dependencies_stored_on_exact_attributes(self):
        self.assertIs(self.agent._planner, self.planner)
        self.assertIs(self.agent._memory, self.memory)
        self.assertIs(self.agent._executor, self.executor)

    def test_market_analysis_agent_dependencies_stored_on_exact_attributes(self):
        self.assertIs(self.agent._provider_manager, self.provider_manager)
        self.assertIs(self.agent._tool_context_builder, self.tool_context_builder)
        self.assertIs(self.agent._instrument_extractor, self.instrument_extractor)
        self.assertIs(self.agent._service_pipeline, self.service_pipeline)
        self.assertEqual(self.agent._default_provider_name, "default")

    def test_run_is_not_called_during_construction(self):
        # Sanity check: constructing the agent must not touch run/chat, since
        # our fakes implement nothing beyond object identity.
        try:
            DummyAgent(
                self.planner,
                self.memory,
                self.executor,
                self.provider_manager,
                self.tool_context_builder,
                self.instrument_extractor,
                self.service_pipeline,
                "default",
            )
        except Exception as exc:  # pragma: no cover - diagnostic only
            self.fail(f"Construction unexpectedly raised: {exc}")


if __name__ == "__main__":
    unittest.main()