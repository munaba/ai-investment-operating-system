"""Sprint 155 proof suite -- production recovery.

Sprint 154 extended ``TradingDecisionAgent`` from 6 to 14 constructor
arguments. ``Core/composition_root.py`` still called the old 6-arg
constructor, so ``build_application()`` raised ``TypeError`` and
production could not start. This suite proves that recovery:
``_build_trading_decision_agent()`` now constructs all 14 already-
existing Skills and hands them to ``TradingDecisionAgent`` in its
fixed order, and the resulting instance is the exact one wired into
``RuntimeAnalysisPipeline`` and exposed on ``ApplicationGraph``.

Hermetic (Stage 9.0 style): real classes, no network, no API key, no
duplicate singleton construction. ``build_application()`` failing to
construct would fail this suite immediately by raising.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.composition_root import ApplicationGraph, build_application
from Orchestration.capital_allocation_skill import CapitalAllocationSkill
from Orchestration.market_analysis_skill import MarketAnalysisSkill
from Orchestration.order_validation_skill import OrderValidationSkill
from Orchestration.paper_trading_skill import PaperTradingSkill
from Orchestration.portfolio_alert_skill import PortfolioAlertSkill
from Orchestration.portfolio_monitor_skill import PortfolioMonitorSkill
from Orchestration.portfolio_performance_skill import PortfolioPerformanceSkill
from Orchestration.portfolio_report_skill import PortfolioReportSkill
from Orchestration.portfolio_update_skill import PortfolioUpdateSkill
from Orchestration.position_risk_skill import PositionRiskSkill
from Orchestration.position_sizing_skill import PositionSizingSkill
from Orchestration.recommendation_skill import RecommendationSkill
from Orchestration.runtime_analysis_pipeline import RuntimeAnalysisPipeline
from Orchestration.trade_history_skill import TradeHistorySkill
from Orchestration.trade_plan_skill import TradePlanSkill
from Orchestration.trading_decision_agent import TradingDecisionAgent

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
    else:
        _FAIL += 1
        _FAILURES.append(description)
    print(f"  {'PASS' if condition else 'FAIL'} - {description}")


_SKILL_ATTR_TYPES = [
    ("_market_analysis_skill", MarketAnalysisSkill),
    ("_recommendation_skill", RecommendationSkill),
    ("_position_risk_skill", PositionRiskSkill),
    ("_trade_plan_skill", TradePlanSkill),
    ("_position_sizing_skill", PositionSizingSkill),
    ("_capital_allocation_skill", CapitalAllocationSkill),
    ("_order_validation_skill", OrderValidationSkill),
    ("_paper_trading_skill", PaperTradingSkill),
    ("_trade_history_skill", TradeHistorySkill),
    ("_portfolio_update_skill", PortfolioUpdateSkill),
    ("_portfolio_monitor_skill", PortfolioMonitorSkill),
    ("_portfolio_performance_skill", PortfolioPerformanceSkill),
    ("_portfolio_alert_skill", PortfolioAlertSkill),
    ("_portfolio_report_skill", PortfolioReportSkill),
]


def scenario_build_application_succeeds() -> ApplicationGraph:
    graph = build_application(
        provider_name="gemini-stage-l155-test",
        agent_name="stock_agent-stage-l155-test",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph, no TypeError raised")
    return graph


def scenario_trading_decision_agent_fully_constructed(graph: ApplicationGraph) -> None:
    agent = graph.trading_decision_agent
    check(isinstance(agent, TradingDecisionAgent), "graph.trading_decision_agent is a real TradingDecisionAgent")
    for attr, expected_type in _SKILL_ATTR_TYPES:
        value = getattr(agent, attr, None)
        check(value is not None, f"TradingDecisionAgent.{attr} is set (not None)")
        check(type(value) is expected_type, f"TradingDecisionAgent.{attr} is a real {expected_type.__name__}")


def scenario_runtime_analysis_pipeline_receives_same_instance(graph: ApplicationGraph) -> None:
    pipeline = graph.runtime_analysis_pipeline
    check(isinstance(pipeline, RuntimeAnalysisPipeline), "graph.runtime_analysis_pipeline is a real RuntimeAnalysisPipeline")
    check(
        pipeline._trading_decision_agent is graph.trading_decision_agent,
        "RuntimeAnalysisPipeline holds the exact same TradingDecisionAgent instance as graph.trading_decision_agent (no duplicate construction)",
    )


def scenario_no_duplicate_skill_instances(graph: ApplicationGraph) -> None:
    agent = graph.trading_decision_agent
    instances = [getattr(agent, attr) for attr, _ in _SKILL_ATTR_TYPES]
    ids = [id(i) for i in instances]
    check(len(ids) == len(set(ids)), "all 14 Skill instances on TradingDecisionAgent are distinct objects (no accidental aliasing)")


def scenario_deterministic_repeated_construction() -> None:
    graph_a = build_application(provider_name="gemini-l155-det-a", agent_name="stock_agent-l155-det-a")
    graph_b = build_application(provider_name="gemini-l155-det-b", agent_name="stock_agent-l155-det-b")
    all_match = all(
        type(getattr(graph_a.trading_decision_agent, attr)) is expected_type
        is type(getattr(graph_b.trading_decision_agent, attr))
        for attr, expected_type in _SKILL_ATTR_TYPES
    )
    check(all_match, "deterministic: all 14 Skill attribute types match the expected classes on every independent build")
    check(
        graph_a.runtime_analysis_pipeline._trading_decision_agent is graph_a.trading_decision_agent,
        "deterministic: build A wires its own TradingDecisionAgent instance into its own RuntimeAnalysisPipeline",
    )
    check(
        graph_b.runtime_analysis_pipeline._trading_decision_agent is graph_b.trading_decision_agent,
        "deterministic: build B wires its own TradingDecisionAgent instance into its own RuntimeAnalysisPipeline",
    )
    check(
        graph_a.trading_decision_agent is not graph_b.trading_decision_agent,
        "deterministic: two independent build_application() calls do not share one TradingDecisionAgent",
    )


def scenario_classic_runtime_path_untouched(graph: ApplicationGraph) -> None:
    """Only the constructor wiring changed -- StockAgent, Executor, and
    AnalysisPipeline are exactly the pre-existing production classes."""
    check(type(graph.executor).__name__ == "Executor", "graph.executor is still the real Executor class")
    check(type(graph.agent).__name__ == "StockAgent", "graph.agent is still the real StockAgent class")
    check(
        graph.agent.runtime_analysis_pipeline is graph.runtime_analysis_pipeline,
        "graph.agent still receives the same runtime_analysis_pipeline instance as the graph exposes",
    )


def main() -> int:
    print("scenario_build_application_succeeds")
    try:
        graph = scenario_build_application_succeeds()
    except Exception:  # noqa: BLE001
        global _FAIL
        _FAIL += 1
        _FAILURES.append("scenario_build_application_succeeds raised an unexpected exception")
        print("  ERROR - build_application() raised unexpectedly:")
        traceback.print_exc()
        graph = None

    if graph is not None:
        for scenario in (
            scenario_trading_decision_agent_fully_constructed,
            scenario_runtime_analysis_pipeline_receives_same_instance,
            scenario_no_duplicate_skill_instances,
            scenario_classic_runtime_path_untouched,
        ):
            print(f"\n{scenario.__name__}")
            try:
                scenario(graph)
            except Exception:  # noqa: BLE001
                _FAIL += 1
                _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
                traceback.print_exc()

    print("\nscenario_deterministic_repeated_construction")
    try:
        scenario_deterministic_repeated_construction()
    except Exception:  # noqa: BLE001
        _FAIL += 1
        _FAILURES.append("scenario_deterministic_repeated_construction raised an unexpected exception")
        traceback.print_exc()

    print(f"\n{_PASS} PASS / {_FAIL} FAIL")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())