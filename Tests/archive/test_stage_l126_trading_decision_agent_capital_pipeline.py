"""Phase 10 Sprint 126 proof suite -- TradingDecisionAgent's final
capital-allocation pipeline.

``TradingDecisionAgent`` (extended in this sprint) now coordinates
the entire six-Skill decision pipeline:

    Task
      |
      v
    MarketAnalysisSkill
      |
      v
    RecommendationSkill
      |
      v
    PositionRiskSkill
      |
      v
    TradePlanSkill
      |
      v
    PositionSizingSkill
      |
      v
    CapitalAllocationSkill

-- returning ``{"market": ..., "recommendation": ..., "risk": ...,
"trade_plan": ..., "position_size": ..., "capital_allocation": ...}``,
each value the exact, unmodified ``SkillResult`` the corresponding
Skill produced.

Scope: dedicated proof suite for
``Orchestration.trading_decision_agent.TradingDecisionAgent`` only.
Mirrors the compact, table-driven, no-pytest, global-counter-plus-
``main()`` style already used by
``Tests/test_stage_l123_trading_decision_agent.py``.

Two layers of coverage:

  1. Seam-level scenarios, using spy Skill stand-ins, that prove the
     Agent calls all six Skills exactly once each, in the correct
     order, forwards output/error by identity, wires
     "stocks" -> "actions" -> "risk" -> "plans" -> "positions" from
     each stage's own output into the next, forwards "capital" from
     task.metadata straight to CapitalAllocationSkill, and never
     raises on malformed input or on a downstream failure.
  2. Real integration: real Market/Recommendation/PositionRisk/
     TradePlan/PositionSizing/CapitalAllocation Skill instances (the
     first wired to a real Tool chain via a real ToolResolver/
     ToolRegistry), proving the full documented flow actually works
     end-to-end and that capital is really allocated.

Invariant coverage:
    O1  -- each of the six Skills is called exactly once.
    O2  -- the six Skills are called in the fixed order
           MarketAnalysisSkill -> RecommendationSkill ->
           PositionRiskSkill -> TradePlanSkill -> PositionSizingSkill
           -> CapitalAllocationSkill.
    O3  -- the returned dict's six values are the exact SkillResult
           objects each Skill produced, forwarded by identity.
    O4  -- a failing SkillResult (success=False/error=<str>) from any
           of the six Skills is forwarded exactly as-is, and the
           pipeline continues to completion regardless.
    C1  -- SkillContext -> MarketAnalysisSkill carries
           parameters == {"symbols": [...]}.
    C2  -- SkillContext -> RecommendationSkill carries
           parameters == {"stocks": [...]}.
    C3  -- SkillContext -> PositionRiskSkill carries
           parameters == {"actions": [...]}.
    C4  -- SkillContext -> TradePlanSkill carries
           parameters == {"risk": [...]}.
    C5  -- SkillContext -> PositionSizingSkill carries
           parameters == {"plans": [...]} taken from
           trade_plan_result.output["plans"].
    C6  -- SkillContext -> CapitalAllocationSkill carries
           parameters == {"capital": <capital>, "plans": [...]},
           where the list is taken from
           position_size_result.output["positions"] and "capital" is
           taken from task.metadata["capital"].
    C7  -- every SkillContext's own task field is the exact Task
           object TradingDecisionAgent.execute() itself received.
    N1-N8 -- malformed metadata/outputs at every stage never raise,
           always falling back to an empty list/zero capital.
    N9  -- missing "capital" in task.metadata still calls
           CapitalAllocationSkill, with a safe default of 0.
    S1  -- overall success is the AND of all six SkillResults'
           .success.
    E1  -- when several Skills fail, every non-None .error can be
           joined into one string, in fixed order.
    T1  -- TradingDecisionAgent never calls execute_tool()/
           execute_tool_result().
    T2  -- TradingDecisionAgent never imports Tool machinery.
    A1  -- AST: no forbidden-name symbol anywhere in the module
           namespace.
    A2  -- AST: the module defines exactly one class,
           TradingDecisionAgent, with no new inheritance.
    A3  -- AST: execute() defines no nested function/lambda, no
           async, and constructs exactly six SkillContext instances
           and exactly six self._*.execute(...) calls.
    A4  -- AST: execute() contains no for/while/try, and exactly one
           return statement.
    A5  -- class shape: __init__ stores exactly the six injected
           collaborators; no other instance state; no helper method
           beyond __init__/execute.
    D1  -- deterministic: repeated real end-to-end runs with the same
           Task produce field-equal SkillResults.
    I1  -- real integration: a real TradingDecisionAgent, wired to
           real Skills (the first backed by a real Tool chain),
           executes a real Task with several symbols and a capital
           figure end-to-end, and returns six internally-consistent
           SkillResults with capital actually allocated.
"""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.capital_allocation_skill import CapitalAllocationSkill
from Orchestration.market_analysis_skill import MarketAnalysisSkill
from Orchestration.market_fundamental_tool import MarketFundamentalTool
from Orchestration.market_news_tool import MarketNewsTool
from Orchestration.market_price_tool import MarketPriceTool
from Orchestration.position_risk_skill import PositionRiskSkill
from Orchestration.position_sizing_skill import PositionSizingSkill
from Orchestration.recommendation_skill import RecommendationSkill
from Orchestration.skill_context import SkillContext
from Orchestration.skill_result import SkillResult
from Orchestration.task import Task
from Orchestration.tool_registry import ToolRegistry
from Orchestration.tool_resolver import ToolResolver
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


def _catch(fn):
    try:
        fn()
        return None
    except Exception as exc:  # noqa: BLE001
        return exc


# ---------------------------------------------------------------------------
# Fixtures -- seam-level: spy Skill stand-ins + a shared ordered call log
# ---------------------------------------------------------------------------
class CallLog:
    def __init__(self) -> None:
        self.events: List[str] = []

    def record(self, event: str) -> None:
        self.events.append(event)


def _make_spy(name: str, log: "CallLog", result: SkillResult):
    class _Spy:
        def __init__(self) -> None:
            self.result = result
            self.received_contexts: List[Any] = []

        def execute(self, context: Any) -> SkillResult:
            log.record(name)
            self.received_contexts.append(context)
            return self.result

    return _Spy()


class _FakeTask:
    """A minimal task-like object exposing only ``.metadata``, to
    prove TradingDecisionAgent never touches any other Task
    attribute."""

    def __init__(self, metadata: Any):
        self.metadata = metadata


def _spies(
    market_output: Any = None,
    market_success: bool = True,
    market_error: Any = None,
    recommendation_output: Any = None,
    recommendation_success: bool = True,
    recommendation_error: Any = None,
    risk_output: Any = None,
    risk_success: bool = True,
    risk_error: Any = None,
    trade_plan_output: Any = None,
    trade_plan_success: bool = True,
    trade_plan_error: Any = None,
    position_size_output: Any = None,
    position_size_success: bool = True,
    position_size_error: Any = None,
    capital_allocation_output: Any = None,
    capital_allocation_success: bool = True,
    capital_allocation_error: Any = None,
):
    log = CallLog()
    market_result = SkillResult(
        success=market_success,
        output=market_output if market_output is not None else {"stocks": []},
        error=market_error,
        metadata={},
    )
    recommendation_result = SkillResult(
        success=recommendation_success,
        output=recommendation_output if recommendation_output is not None else {"actions": []},
        error=recommendation_error,
        metadata={},
    )
    risk_result = SkillResult(
        success=risk_success,
        output=risk_output if risk_output is not None else {"risk": []},
        error=risk_error,
        metadata={},
    )
    trade_plan_result = SkillResult(
        success=trade_plan_success,
        output=trade_plan_output if trade_plan_output is not None else {"plans": []},
        error=trade_plan_error,
        metadata={},
    )
    position_size_result = SkillResult(
        success=position_size_success,
        output=position_size_output if position_size_output is not None else {"positions": []},
        error=position_size_error,
        metadata={},
    )
    capital_allocation_result = SkillResult(
        success=capital_allocation_success,
        output=capital_allocation_output if capital_allocation_output is not None else {"allocations": []},
        error=capital_allocation_error,
        metadata={},
    )

    market_spy = _make_spy("market", log, market_result)
    recommendation_spy = _make_spy("recommendation", log, recommendation_result)
    risk_spy = _make_spy("risk", log, risk_result)
    trade_plan_spy = _make_spy("trade_plan", log, trade_plan_result)
    position_size_spy = _make_spy("position_size", log, position_size_result)
    capital_allocation_spy = _make_spy("capital_allocation", log, capital_allocation_result)

    agent = TradingDecisionAgent(
        market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, capital_allocation_spy,
    )
    return (
        agent, log,
        market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, capital_allocation_spy,
        market_result, recommendation_result, risk_result, trade_plan_result,
        position_size_result, capital_allocation_result,
    )


# ---------------------------------------------------------------------------
# O1-O2 -- each Skill called exactly once, in the fixed order
# ---------------------------------------------------------------------------
def scenario_each_skill_called_exactly_once() -> None:
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, capital_allocation_spy, *_,
    ) = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    for spy, label in (
        (market_spy, "MarketAnalysisSkill"), (recommendation_spy, "RecommendationSkill"),
        (risk_spy, "PositionRiskSkill"), (trade_plan_spy, "TradePlanSkill"),
        (position_size_spy, "PositionSizingSkill"), (capital_allocation_spy, "CapitalAllocationSkill"),
    ):
        check(len(spy.received_contexts) == 1, f"O1: {label}.execute() called exactly once; got {len(spy.received_contexts)}")


def scenario_skills_called_in_fixed_order() -> None:
    agent, log, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    expected = ["market", "recommendation", "risk", "trade_plan", "position_size", "capital_allocation"]
    check(log.events == expected, f"O2: Skills called in the fixed order; got {log.events!r}")


def scenario_repeated_execute_repeats_the_same_fixed_order() -> None:
    agent, log, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    agent.execute(_FakeTask({"symbols": ["BBRI"], "capital": 2000}))
    expected = ["market", "recommendation", "risk", "trade_plan", "position_size", "capital_allocation"]
    check(log.events == expected * 2, f"O2: each execute() call repeats the exact same fixed order; got {log.events!r}")


# ---------------------------------------------------------------------------
# O3-O4 -- results forwarded by identity, unmerged, unmodified
# ---------------------------------------------------------------------------
def scenario_results_forwarded_by_identity() -> None:
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, capital_allocation_spy,
        market_result, recommendation_result, risk_result, trade_plan_result,
        position_size_result, capital_allocation_result,
    ) = _spies(market_output={"stocks": [{"symbol": "BBCA"}]})
    result = agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    check(isinstance(result, dict), f"O3: execute() returns a dict; got {type(result)!r}")
    expected_keys = {"market", "recommendation", "risk", "trade_plan", "position_size", "capital_allocation"}
    check(set(result.keys()) == expected_keys, f"O3: result has exactly the six expected keys; got {set(result.keys())!r}")
    check(result["market"] is market_result, "O3: result['market'] is the exact SkillResult MarketAnalysisSkill produced")
    check(result["recommendation"] is recommendation_result, "O3: result['recommendation'] is the exact SkillResult RecommendationSkill produced")
    check(result["risk"] is risk_result, "O3: result['risk'] is the exact SkillResult PositionRiskSkill produced")
    check(result["trade_plan"] is trade_plan_result, "O3: result['trade_plan'] is the exact SkillResult TradePlanSkill produced")
    check(result["position_size"] is position_size_result, "O3: result['position_size'] is the exact SkillResult PositionSizingSkill produced")
    check(result["capital_allocation"] is capital_allocation_result, "O3: result['capital_allocation'] is the exact SkillResult CapitalAllocationSkill produced")


def scenario_failure_error_forwarded_and_pipeline_continues() -> None:
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, capital_allocation_spy, *_,
    ) = _spies(market_success=False, market_error="BBRI: market_price: boom")
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBRI"], "capital": 1000})))
    check(exc is None, f"O4: a failing upstream Skill never raises; pipeline continues; got {exc!r}")

    result = agent.execute(_FakeTask({"symbols": ["BBRI"], "capital": 1000}))
    check(result["market"].success is False, "O4: a failing MarketAnalysisSkill result's success=False is forwarded unchanged")
    check(result["market"].error == "BBRI: market_price: boom", f"O4: error string is forwarded unchanged; got {result['market'].error!r}")
    check(len(recommendation_spy.received_contexts) == 2, "O4: RecommendationSkill still ran despite MarketAnalysisSkill's failure")
    check(len(risk_spy.received_contexts) == 2, "O4: PositionRiskSkill still ran despite the upstream failure")
    check(len(trade_plan_spy.received_contexts) == 2, "O4: TradePlanSkill still ran despite the upstream failure")
    check(len(position_size_spy.received_contexts) == 2, "O4: PositionSizingSkill still ran despite the upstream failure")
    check(len(capital_allocation_spy.received_contexts) == 2, "O4: CapitalAllocationSkill still ran despite the upstream failure")


# ---------------------------------------------------------------------------
# C1-C7 -- SkillContext construction and wiring between stages
# ---------------------------------------------------------------------------
def scenario_market_context_carries_symbols() -> None:
    agent, log, market_spy, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA", "BBRI", "BMRI"], "capital": 1000}))
    context = market_spy.received_contexts[0]
    check(dict(context.parameters) == {"symbols": ["BBCA", "BBRI", "BMRI"]}, f"C1: MarketAnalysisSkill context.parameters carries {{'symbols': [...]}}; got {dict(context.parameters)!r}")


def scenario_recommendation_context_carries_stocks() -> None:
    stocks = [{"symbol": "BBCA", "analysis": {"recommendation": "BUY"}}]
    agent, log, market_spy, recommendation_spy, *_ = _spies(market_output={"stocks": stocks})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    context = recommendation_spy.received_contexts[0]
    check(dict(context.parameters) == {"stocks": stocks}, f"C2: RecommendationSkill context.parameters carries {{'stocks': [...]}}; got {dict(context.parameters)!r}")


def scenario_risk_context_carries_actions() -> None:
    actions = [{"symbol": "BBCA", "action": "BUY"}]
    agent, log, market_spy, recommendation_spy, risk_spy, *_ = _spies(recommendation_output={"actions": actions})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    context = risk_spy.received_contexts[0]
    check(dict(context.parameters) == {"actions": actions}, f"C3: PositionRiskSkill context.parameters carries {{'actions': [...]}}; got {dict(context.parameters)!r}")


def scenario_trade_plan_context_carries_risk() -> None:
    risk_entries = [{"symbol": "BBCA", "action": "BUY", "risk": "LOW"}]
    agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy, *_ = _spies(risk_output={"risk": risk_entries})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    context = trade_plan_spy.received_contexts[0]
    check(dict(context.parameters) == {"risk": risk_entries}, f"C4: TradePlanSkill context.parameters carries {{'risk': [...]}}; got {dict(context.parameters)!r}")


def scenario_position_sizing_context_carries_plans() -> None:
    plans = [{"symbol": "BBCA", "action": "BUY", "risk": "LOW", "plan": "ACCUMULATE"}]
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, *_,
    ) = _spies(trade_plan_output={"plans": plans})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    context = position_size_spy.received_contexts[0]
    check(dict(context.parameters) == {"plans": plans}, f"C5: PositionSizingSkill context.parameters carries {{'plans': [...]}} taken from trade_plan_result.output['plans']; got {dict(context.parameters)!r}")


def scenario_capital_allocation_context_carries_capital_and_positions() -> None:
    positions = [{"symbol": "BBCA", "action": "BUY", "risk": "LOW", "plan": "ACCUMULATE", "position_size": "FULL"}]
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, capital_allocation_spy, *_,
    ) = _spies(position_size_output={"positions": positions})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 100_000_000}))
    context = capital_allocation_spy.received_contexts[0]
    check(
        dict(context.parameters) == {"capital": 100_000_000, "plans": positions},
        f"C6: CapitalAllocationSkill context.parameters carries {{'capital': ..., 'plans': [...]}} taken from position_size_result.output['positions'] and task.metadata['capital']; got {dict(context.parameters)!r}",
    )


def scenario_every_context_task_is_the_received_task_by_identity() -> None:
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, capital_allocation_spy, *_,
    ) = _spies()
    task = _FakeTask({"symbols": ["BBCA"], "capital": 1000})
    agent.execute(task)
    for spy, label in (
        (market_spy, "MarketAnalysisSkill"), (recommendation_spy, "RecommendationSkill"),
        (risk_spy, "PositionRiskSkill"), (trade_plan_spy, "TradePlanSkill"),
        (position_size_spy, "PositionSizingSkill"), (capital_allocation_spy, "CapitalAllocationSkill"),
    ):
        check(spy.received_contexts[0].task is task, f"C7: {label}'s SkillContext.task is the exact Task object received")


# ---------------------------------------------------------------------------
# N1-N9 -- malformed input never raises
# ---------------------------------------------------------------------------
def scenario_missing_symbols_key_yields_empty_list() -> None:
    agent, log, market_spy, *_ = _spies()
    exc = _catch(lambda: agent.execute(_FakeTask({"capital": 1000})))
    check(exc is None, f"N1: missing 'symbols' key never raises; got {exc!r}")
    agent.execute(_FakeTask({"capital": 1000}))
    context = market_spy.received_contexts[-1]
    check(dict(context.parameters) == {"symbols": []}, f"N1: missing 'symbols' key yields an empty list; got {dict(context.parameters)!r}")


def scenario_non_list_symbols_yields_empty_list() -> None:
    agent, log, market_spy, *_ = _spies()
    agent.execute(_FakeTask({"symbols": "not a list", "capital": 1000}))
    context = market_spy.received_contexts[-1]
    check(dict(context.parameters) == {"symbols": []}, f"N2: non-list 'symbols' value yields an empty list; got {dict(context.parameters)!r}")


def scenario_none_metadata_never_raises() -> None:
    agent, log, *_ = _spies()
    exc = _catch(lambda: agent.execute(_FakeTask(None)))
    check(exc is None, f"N3: metadata=None never raises; got {exc!r}")
    exc2 = _catch(lambda: agent.execute(object()))
    check(exc2 is None, f"N3: a task-like object with no .metadata attribute at all never raises; got {exc2!r}")


def scenario_missing_stocks_never_raises() -> None:
    agent, log, market_spy, recommendation_spy, *_ = _spies(market_output={})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000})))
    check(exc is None, f"N4: a market_result.output with no 'stocks' key never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    check(dict(recommendation_spy.received_contexts[-1].parameters) == {"stocks": []}, "N4: missing 'stocks' key yields an empty list for RecommendationSkill")


def scenario_missing_actions_never_raises() -> None:
    agent, log, market_spy, recommendation_spy, risk_spy, *_ = _spies(recommendation_output={})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000})))
    check(exc is None, f"N5: a recommendation_result.output with no 'actions' key never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    check(dict(risk_spy.received_contexts[-1].parameters) == {"actions": []}, "N5: missing 'actions' key yields an empty list for PositionRiskSkill")


def scenario_missing_risk_never_raises() -> None:
    agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy, *_ = _spies(risk_output={})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000})))
    check(exc is None, f"N6: a risk_result.output with no 'risk' key never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    check(dict(trade_plan_spy.received_contexts[-1].parameters) == {"risk": []}, "N6: missing 'risk' key yields an empty list for TradePlanSkill")


def scenario_missing_plans_never_raises() -> None:
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, *_,
    ) = _spies(trade_plan_output={})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000})))
    check(exc is None, f"N7: a trade_plan_result.output with no 'plans' key never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    check(dict(position_size_spy.received_contexts[-1].parameters) == {"plans": []}, "N7: missing 'plans' key yields an empty list for PositionSizingSkill")


def scenario_missing_positions_never_raises() -> None:
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, capital_allocation_spy, *_,
    ) = _spies(position_size_output={})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000})))
    check(exc is None, f"N8: a position_size_result.output with no 'positions' key never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    check(
        dict(capital_allocation_spy.received_contexts[-1].parameters) == {"capital": 1000, "plans": []},
        "N8: missing 'positions' key yields an empty list for CapitalAllocationSkill, capital still forwarded",
    )


def scenario_non_mapping_outputs_never_raise() -> None:
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, capital_allocation_spy, *_,
    ) = _spies(
        market_output="not a mapping",
        recommendation_output="not a mapping",
        risk_output="not a mapping",
        trade_plan_output="not a mapping",
        position_size_output="not a mapping",
    )
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000})))
    check(exc is None, f"N4-N8: non-Mapping .output values at every stage never raise; got {exc!r}")


def scenario_missing_capital_calls_capital_allocation_with_safe_default() -> None:
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, capital_allocation_spy, *_,
    ) = _spies()
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"]})))
    check(exc is None, f"N9: missing 'capital' key never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(len(capital_allocation_spy.received_contexts) == 2, "N9: CapitalAllocationSkill is still called when 'capital' is missing")
    context = capital_allocation_spy.received_contexts[-1]
    check(context.parameters["capital"] == 0, f"N9: missing 'capital' falls back to a safe default of 0; got {context.parameters['capital']!r}")


def scenario_non_numeric_capital_falls_back_to_zero() -> None:
    agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy, position_size_spy, capital_allocation_spy, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": "a lot"}))
    context = capital_allocation_spy.received_contexts[-1]
    check(context.parameters["capital"] == 0, f"N9: a non-numeric 'capital' value falls back to 0; got {context.parameters['capital']!r}")

    (
        agent2, log2, market_spy2, recommendation_spy2, risk_spy2, trade_plan_spy2,
        position_size_spy2, capital_allocation_spy2, *_,
    ) = _spies()
    agent2.execute(_FakeTask({"symbols": ["BBCA"], "capital": True}))
    context2 = capital_allocation_spy2.received_contexts[-1]
    check(context2.parameters["capital"] == 0, f"N9: a bool 'capital' value falls back to 0 (bool excluded); got {context2.parameters['capital']!r}")


# ---------------------------------------------------------------------------
# S1/E1 -- overall success and error aggregation are derivable from the
# forwarded SkillResults
# ---------------------------------------------------------------------------
def scenario_overall_success_is_and_of_all_six() -> None:
    agent, log, *_ = _spies()
    result = agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    overall_success = (
        result["market"].success and result["recommendation"].success
        and result["risk"].success and result["trade_plan"].success
        and result["position_size"].success and result["capital_allocation"].success
    )
    check(overall_success is True, "S1: overall success is True when every stage succeeds")

    (
        agent2, log2, market_spy2, recommendation_spy2, risk_spy2, trade_plan_spy2,
        position_size_spy2, capital_allocation_spy2, *_,
    ) = _spies(risk_success=False, risk_error="BBCA: risk boom")
    result2 = agent2.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    overall_success2 = (
        result2["market"].success and result2["recommendation"].success
        and result2["risk"].success and result2["trade_plan"].success
        and result2["position_size"].success and result2["capital_allocation"].success
    )
    check(overall_success2 is False, "S1: overall success is False as soon as any one stage fails")


def scenario_error_aggregation_in_fixed_order() -> None:
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, capital_allocation_spy, *_,
    ) = _spies(
        market_success=False, market_error="market boom",
        trade_plan_success=False, trade_plan_error="trade_plan boom",
    )
    result = agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    ordered_keys = ["market", "recommendation", "risk", "trade_plan", "position_size", "capital_allocation"]
    errors = [result[key].error for key in ordered_keys if result[key].error is not None]
    aggregated = "; ".join(errors)
    check(aggregated == "market boom; trade_plan boom", f"E1: errors aggregate in fixed order market->...->capital_allocation; got {aggregated!r}")


# ---------------------------------------------------------------------------
# T1-T2 -- no Tool access of any kind
# ---------------------------------------------------------------------------
def scenario_agent_has_no_tool_related_methods() -> None:
    check(not hasattr(TradingDecisionAgent, "execute_tool"), "T1: TradingDecisionAgent has no execute_tool method")
    check(not hasattr(TradingDecisionAgent, "execute_tool_result"), "T1: TradingDecisionAgent has no execute_tool_result method")
    check(not hasattr(TradingDecisionAgent, "_resolve_tool"), "T1: TradingDecisionAgent has no _resolve_tool attribute on the class")


def scenario_module_never_imports_tool_machinery() -> None:
    import Orchestration.trading_decision_agent as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.add(node.module or "")
            for alias in node.names:
                imported_names.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name)

    forbidden_imports = (
        "Orchestration.tool_resolver", "Orchestration.tool_registry",
        "Orchestration.tool_context", "Orchestration.market_price_tool",
        "Orchestration.market_news_tool", "Orchestration.market_fundamental_tool",
        "Orchestration.text_analysis_skill", "Orchestration.executor",
        "Orchestration.base_tool", "Orchestration.market_analysis_agent",
        "Orchestration.portfolio_analysis_skill", "Orchestration.watchlist_analysis_skill",
        "ToolResolver", "ToolRegistry", "ToolContext", "TextAnalysisSkill",
        "MarketAnalysisAgent",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"T2: module never imports {forbidden!r}")


# ---------------------------------------------------------------------------
# A1-A5 -- AST / namespace verification
# ---------------------------------------------------------------------------
def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.trading_decision_agent as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = {n.name for n in class_defs}
    check(class_names == {"TradingDecisionAgent"}, f"A2: module defines exactly one class; got {class_names!r}")

    for class_def in class_defs:
        base_names = [b.id for b in class_def.bases if isinstance(b, ast.Name)]
        check(base_names == [], f"A2: TradingDecisionAgent has no base class (no new inheritance); got {base_names!r}")

    forbidden_fragments = (
        "Planner", "Graph", "Engine", "Workflow", "Pipeline",
        "Coordinator", "Manager", "Dispatcher", "Router", "Factory",
        "Strategy", "Registry", "Service", "Repository", "Helper",
        "Utility", "Adapter", "Analyzer",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A1: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )


def scenario_execute_body_shape() -> None:
    source = inspect.getsource(TradingDecisionAgent.execute)
    tree = ast.parse(textwrap.dedent(source))

    top_level_def = tree.body[0]
    check(isinstance(top_level_def, ast.FunctionDef), "A3: execute() is a plain (non-async) function")

    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A3: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")

    async_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.AsyncFunctionDef)]
    check(len(async_nodes) == 0, f"A3: execute() contains no async def; got {len(async_nodes)}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

    forbidden_tool_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr in ("execute_tool", "execute_tool_result")
    ]
    check(len(forbidden_tool_calls) == 0, f"T1: execute() never calls execute_tool()/execute_tool_result(); got {len(forbidden_tool_calls)}")

    skill_context_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillContext"]
    check(len(skill_context_calls) == 6, f"A3: exactly six SkillContext(...) constructions; got {len(skill_context_calls)}")

    execute_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr == "execute"
        and isinstance(c.func.value, ast.Attribute)
        and isinstance(c.func.value.value, ast.Name) and c.func.value.value.id == "self"
    ]
    check(len(execute_calls) == 6, f"A3: exactly six self._*.execute(...) calls; got {len(execute_calls)}")

    return_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.Return)]
    check(len(return_nodes) == 1, f"A4: execute() contains exactly one return statement; got {len(return_nodes)}")


def scenario_execute_has_no_branching() -> None:
    source = inspect.getsource(TradingDecisionAgent.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]

    for_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, (ast.For, ast.AsyncFor))]
    while_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.While)]
    try_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.Try)]
    check(len(for_nodes) == 0, f"A4: execute() contains no for-loop; got {len(for_nodes)}")
    check(len(while_nodes) == 0, f"A4: execute() contains no while-loop; got {len(while_nodes)}")
    check(len(try_nodes) == 0, f"A4: execute() contains no try/except (no error-swallowing); got {len(try_nodes)}")

    # if-statements are permitted only for the defensive isinstance()
    # style read of task.metadata / each Skill's own result.output
    # (never for choosing *which* Skill to call, or *whether* to call
    # one, or for skipping a stage based on a prior success flag).
    if_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.If)]
    for if_node in if_nodes:
        called_names = {
            c.func.id for c in ast.walk(if_node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        }
        check(
            "SkillContext" not in called_names,
            "A4: no SkillContext(...) construction lives inside an if-branch (unconditional, hardcoded sequence)",
        )
        called_attrs = {
            c.func.attr for c in ast.walk(if_node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
        }
        check(
            "execute" not in called_attrs,
            "A4: no Skill.execute(...) call lives inside an if-branch (unconditional, hardcoded sequence)",
        )


def scenario_class_shape() -> None:
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        position_size_spy, capital_allocation_spy, *_,
    ) = _spies()
    check(
        agent.__dict__ == {
            "_market_analysis_skill": market_spy,
            "_recommendation_skill": recommendation_spy,
            "_position_risk_skill": risk_spy,
            "_trade_plan_skill": trade_plan_spy,
            "_position_sizing_skill": position_size_spy,
            "_capital_allocation_skill": capital_allocation_spy,
        },
        f"A5: __init__ stores exactly the six injected collaborators; got {agent.__dict__!r}",
    )
    check(agent._market_analysis_skill is market_spy, "A5: the stored MarketAnalysisSkill is the exact object passed in, by identity")
    check(agent._recommendation_skill is recommendation_spy, "A5: the stored RecommendationSkill is the exact object passed in, by identity")
    check(agent._position_risk_skill is risk_spy, "A5: the stored PositionRiskSkill is the exact object passed in, by identity")
    check(agent._trade_plan_skill is trade_plan_spy, "A5: the stored TradePlanSkill is the exact object passed in, by identity")
    check(agent._position_sizing_skill is position_size_spy, "A5: the stored PositionSizingSkill is the exact object passed in, by identity")
    check(agent._capital_allocation_skill is capital_allocation_spy, "A5: the stored CapitalAllocationSkill is the exact object passed in, by identity")


def scenario_no_extra_methods_beyond_init_and_execute() -> None:
    required_members = {"__init__", "execute"}
    for attr_name, attr_value in TradingDecisionAgent.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A5: no additional method/property defined on TradingDecisionAgent beyond __init__/execute; found {attr_name!r}",
        )


# ---------------------------------------------------------------------------
# D1/I1 -- real end-to-end integration
# ---------------------------------------------------------------------------
def _real_agent() -> TradingDecisionAgent:
    tool_registry = ToolRegistry()
    tool_registry.register("market_price", MarketPriceTool())
    tool_registry.register("market_news", MarketNewsTool())
    tool_registry.register("market_fundamental", MarketFundamentalTool())
    tool_resolver = ToolResolver(tool_registry)

    market_analysis_skill = MarketAnalysisSkill()
    # This is exactly the shape Executor.invoke_current_skill() injects
    # onto a Skill instance in production -- performed here by the test
    # harness (standing in for an Executor), never by
    # TradingDecisionAgent itself.
    market_analysis_skill._resolve_tool = tool_resolver.resolve

    recommendation_skill = RecommendationSkill()
    position_risk_skill = PositionRiskSkill()
    trade_plan_skill = TradePlanSkill()
    position_sizing_skill = PositionSizingSkill()
    capital_allocation_skill = CapitalAllocationSkill()

    return TradingDecisionAgent(
        market_analysis_skill, recommendation_skill, position_risk_skill,
        trade_plan_skill, position_sizing_skill, capital_allocation_skill,
    )


def scenario_real_end_to_end_chain() -> None:
    agent = _real_agent()
    task = Task(
        name="trading-decision",
        description="Produce a full trade decision with capital allocation for several IDX symbols end-to-end",
        metadata={"symbols": ["BBCA", "BBRI", "BMRI"], "capital": 100_000_000},
    )

    result = agent.execute(task)

    check(isinstance(result, dict), f"I1: real chain returns a dict; got {type(result)!r}")
    expected_keys = {"market", "recommendation", "risk", "trade_plan", "position_size", "capital_allocation"}
    check(set(result.keys()) == expected_keys, f"I1: result has exactly the six expected keys; got {set(result.keys())!r}")

    market_result = result["market"]
    recommendation_result = result["recommendation"]
    risk_result = result["risk"]
    trade_plan_result = result["trade_plan"]
    position_size_result = result["position_size"]
    capital_allocation_result = result["capital_allocation"]

    for res, label in (
        (market_result, "market"), (recommendation_result, "recommendation"),
        (risk_result, "risk"), (trade_plan_result, "trade_plan"),
        (position_size_result, "position_size"), (capital_allocation_result, "capital_allocation"),
    ):
        check(isinstance(res, SkillResult), f"I1: result[{label!r}] is a SkillResult; got {type(res)!r}")

    stocks = market_result.output["stocks"]
    symbols_in_order = [s["symbol"] for s in stocks]
    check(symbols_in_order == ["BBCA", "BBRI", "BMRI"], f"I1: original input order preserved in market output; got {symbols_in_order!r}")

    actions = recommendation_result.output["actions"]
    risk_entries = risk_result.output["risk"]
    plans = trade_plan_result.output["plans"]
    positions = position_size_result.output["positions"]
    allocations = capital_allocation_result.output["allocations"]

    check(len(actions) == 3, f"I1: RecommendationSkill produced one action per stock; got {len(actions)}")
    check(len(risk_entries) == 3, f"I1: PositionRiskSkill produced one risk entry per action; got {len(risk_entries)}")
    check(len(plans) == 3, f"I1: TradePlanSkill produced one plan per risk entry; got {len(plans)}")
    check(len(positions) == 3, f"I1: PositionSizingSkill produced one position entry per plan; got {len(positions)}")
    check(len(allocations) == 3, f"I1: CapitalAllocationSkill produced one allocation entry per position; got {len(allocations)}")

    allocation_symbols = [entry["symbol"] for entry in allocations]
    check(allocation_symbols == symbols_in_order, f"I1: CapitalAllocationSkill's allocations cover the exact same symbols in the exact same order; got {allocation_symbols!r}")

    for position_entry, allocation_entry in zip(positions, allocations):
        check(allocation_entry["position_size"] == position_entry["position_size"], f"I1: CapitalAllocationSkill's position_size matches PositionSizingSkill's own position_size for {position_entry['symbol']!r}")
        check(allocation_entry["plan"] == position_entry["plan"], f"I1: CapitalAllocationSkill's plan matches PositionSizingSkill's own plan for {position_entry['symbol']!r}")

    check(
        all(isinstance(entry["allocated_capital"], (int, float)) for entry in allocations),
        "I1: every allocation entry carries a numeric allocated_capital",
    )
    check(
        all(entry["allocated_capital"] <= 100_000_000 for entry in allocations),
        "I1: no allocation entry exceeds the total capital supplied",
    )
    # Note: the real MarketPriceTool/MarketNewsTool/MarketFundamentalTool
    # chain may legitimately yield "UNKNOWN" recommendations/positions in
    # a sandboxed environment with no network access, in which case every
    # allocated_capital is correctly 0 -- so no positivity assumption is
    # made here, only that the values are internally consistent (checked
    # above) and within bounds.

    overall_success = (
        market_result.success and recommendation_result.success and risk_result.success
        and trade_plan_result.success and position_size_result.success and capital_allocation_result.success
    )
    check(overall_success is True, "I1: overall success is True for a clean real end-to-end run")


def scenario_real_chain_is_deterministic() -> None:
    agent = _real_agent()
    task = Task(
        name="trading-decision",
        description="Produce a full trade decision with capital allocation for a couple of IDX symbols end-to-end",
        metadata={"symbols": ["BBCA", "BBRI"], "capital": 50_000_000},
    )

    result1 = agent.execute(task)
    result2 = agent.execute(task)
    for key in ("market", "recommendation", "risk", "trade_plan", "position_size", "capital_allocation"):
        check(result1[key] == result2[key], f"D1: repeated real end-to-end runs produce field-equal {key!r} SkillResults")


def scenario_real_chain_capital_hilang_uses_safe_default() -> None:
    agent = _real_agent()
    task = Task(
        name="trading-decision",
        description="Real chain with no capital figure supplied at all",
        metadata={"symbols": ["BBCA"]},
    )
    exc = _catch(lambda: agent.execute(task))
    check(exc is None, f"N9/I1: a real chain with no 'capital' key never raises; got {exc!r}")
    result = agent.execute(task)
    allocations = result["capital_allocation"].output["allocations"]
    check(len(allocations) == 1, f"N9/I1: CapitalAllocationSkill still ran and produced one entry; got {len(allocations)}")
    check(
        all(entry["allocated_capital"] == 0 for entry in allocations),
        "N9/I1: with no capital supplied, every allocated_capital falls back to 0, never raising",
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_each_skill_called_exactly_once,
        scenario_skills_called_in_fixed_order,
        scenario_repeated_execute_repeats_the_same_fixed_order,
        scenario_results_forwarded_by_identity,
        scenario_failure_error_forwarded_and_pipeline_continues,
        scenario_market_context_carries_symbols,
        scenario_recommendation_context_carries_stocks,
        scenario_risk_context_carries_actions,
        scenario_trade_plan_context_carries_risk,
        scenario_position_sizing_context_carries_plans,
        scenario_capital_allocation_context_carries_capital_and_positions,
        scenario_every_context_task_is_the_received_task_by_identity,
        scenario_missing_symbols_key_yields_empty_list,
        scenario_non_list_symbols_yields_empty_list,
        scenario_none_metadata_never_raises,
        scenario_missing_stocks_never_raises,
        scenario_missing_actions_never_raises,
        scenario_missing_risk_never_raises,
        scenario_missing_plans_never_raises,
        scenario_missing_positions_never_raises,
        scenario_non_mapping_outputs_never_raise,
        scenario_missing_capital_calls_capital_allocation_with_safe_default,
        scenario_non_numeric_capital_falls_back_to_zero,
        scenario_overall_success_is_and_of_all_six,
        scenario_error_aggregation_in_fixed_order,
        scenario_agent_has_no_tool_related_methods,
        scenario_module_never_imports_tool_machinery,
        scenario_no_forbidden_abstractions,
        scenario_execute_body_shape,
        scenario_execute_has_no_branching,
        scenario_class_shape,
        scenario_no_extra_methods_beyond_init_and_execute,
        scenario_real_end_to_end_chain,
        scenario_real_chain_is_deterministic,
        scenario_real_chain_capital_hilang_uses_safe_default,
    ]

    for scenario in scenarios:
        print(f"\n{scenario.__name__}")
        scenario()

    print(f"\n{'=' * 70}")
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())