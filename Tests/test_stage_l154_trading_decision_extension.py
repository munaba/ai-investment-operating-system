"""Phase 11/13 Sprint 154 proof suite -- TradingDecisionAgent extended
into the full fourteen-Skill production chain (MarketAnalysisSkill ->
... -> CapitalAllocationSkill -> OrderValidationSkill ->
PaperTradingSkill -> TradeHistorySkill -> PortfolioUpdateSkill ->
PortfolioMonitorSkill -> PortfolioPerformanceSkill ->
PortfolioAlertSkill -> PortfolioReportSkill), returning a dict with
fourteen keys, each the exact unmodified SkillResult the
corresponding Skill produced, "portfolio_report" being the final one.

Mirrors the compact, table-driven, no-pytest, global-counter-plus-
main() style already used by
Tests/test_stage_l126_trading_decision_agent_capital_pipeline.py.
Seam-level only: every collaborator is a spy Skill stand-in.

Invariant coverage: O1/O2 -- call count & fixed order across all 14
Skills. O3 -- identity-forwarded results, final = portfolio_report.
O4 -- a mid-chain failure never stops the pipeline. C1-C8 -- context
wiring for the 8 new stages. N1-N6 -- malformed/missing output never
raises. A1 -- constructor stores the new collaborators by identity,
public surface stays execute()-only. D1 -- deterministic repeats.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.skill_result import SkillResult
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


# Fixtures -- seam-level: spy Skill stand-ins + a shared ordered call log
_STAGES = [
    ("market", "stocks"),
    ("recommendation", "actions"),
    ("risk", "risk"),
    ("trade_plan", "plans"),
    ("position_size", "positions"),
    ("capital_allocation", "allocations"),
    ("order_validation", "orders"),
    ("paper_trading", "executions"),
    ("trade_history", "history"),
    ("portfolio_update", "portfolio"),
    ("portfolio_monitor", "monitor"),
    ("portfolio_performance", "performance"),
    ("portfolio_alert", "alerts"),
    ("portfolio_report", "report"),
]


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
    """A minimal task-like object exposing only ``.metadata``."""

    def __init__(self, metadata: Any):
        self.metadata = metadata


def _spies(overrides: Any = None):
    """Build fourteen spies + a shared CallLog + a TradingDecisionAgent.

    ``overrides`` maps stage name -> {"output": ..., "success": ...,
    "error": ...}. Any stage not overridden gets a default success
    SkillResult carrying an empty list under its own output key.
    """
    overrides = overrides or {}
    log = CallLog()
    results = {}
    spies = {}
    for stage, output_key in _STAGES:
        cfg = overrides.get(stage, {})
        output = cfg.get("output", {output_key: []})
        result = SkillResult(
            success=cfg.get("success", True),
            output=output,
            error=cfg.get("error", None),
            metadata={},
        )
        results[stage] = result
        spies[stage] = _make_spy(stage, log, result)

    agent = TradingDecisionAgent(
        spies["market"], spies["recommendation"], spies["risk"],
        spies["trade_plan"], spies["position_size"], spies["capital_allocation"],
        spies["order_validation"], spies["paper_trading"], spies["trade_history"],
        spies["portfolio_update"], spies["portfolio_monitor"],
        spies["portfolio_performance"], spies["portfolio_alert"],
        spies["portfolio_report"],
    )
    return agent, log, spies, results


_ORDER = [stage for stage, _ in _STAGES]


# O1-O2 -- each Skill called exactly once, in the fixed 14-stage order
def scenario_each_skill_called_exactly_once() -> None:
    agent, log, spies, _ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    counts = {stage: len(spies[stage].received_contexts) for stage in _ORDER}
    check(all(c == 1 for c in counts.values()), f"O1: all 14 Skills' execute() called exactly once each; got {counts!r}")


def scenario_skills_called_in_fixed_order() -> None:
    agent, log, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    check(log.events == _ORDER, f"O2: all 14 Skills called in the fixed order; got {log.events!r}")


def scenario_repeated_execute_repeats_the_same_fixed_order() -> None:
    agent, log, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    agent.execute(_FakeTask({"symbols": ["BBRI"], "capital": 2000}))
    check(log.events == _ORDER * 2, f"D1: each execute() call repeats the exact same 14-stage order; got {log.events!r}")


# O3 -- all fourteen results forwarded by identity; final = portfolio_report
def scenario_results_forwarded_by_identity() -> None:
    agent, log, spies, results = _spies()
    result = agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    check(isinstance(result, dict), f"O3: execute() returns a dict; got {type(result)!r}")
    expected_keys = set(_ORDER)
    check(set(result.keys()) == expected_keys, f"O3: result has exactly the 14 expected keys; got {set(result.keys())!r}")
    check(
        all(result[stage] is results[stage] for stage in _ORDER),
        "O3: every one of the 14 values is the exact SkillResult that Skill produced, forwarded by identity",
    )
    check(
        result["portfolio_report"] is results["portfolio_report"],
        "O3: the final PortfolioReportSkill result is exposed as result['portfolio_report']",
    )


# O4 -- a failing upstream Skill never stops the pipeline
def scenario_failure_forwarded_and_pipeline_continues() -> None:
    agent, log, spies, _ = _spies(
        overrides={"order_validation": {"success": False, "error": "boom", "output": {"orders": []}}}
    )
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBRI"], "capital": 1000})))
    check(exc is None, f"O4: a failing mid-chain Skill never raises; pipeline continues; got {exc!r}")

    result = agent.execute(_FakeTask({"symbols": ["BBRI"], "capital": 1000}))
    check(result["order_validation"].success is False, "O4: failing OrderValidationSkill result forwarded unchanged")
    check(result["order_validation"].error == "boom", f"O4: error string forwarded unchanged; got {result['order_validation'].error!r}")
    downstream = ("paper_trading", "trade_history", "portfolio_update", "portfolio_monitor",
                  "portfolio_performance", "portfolio_alert", "portfolio_report")
    check(
        all(len(spies[s].received_contexts) == 2 for s in downstream),
        "O4: every downstream Skill still ran (twice, across both calls) despite the upstream failure",
    )


# C1-C8 -- SkillContext wiring for the eight new stages
def scenario_order_validation_context_carries_allocations() -> None:
    allocations = [{"symbol": "BBCA", "action": "BUY", "capital": 1000}]
    agent, log, spies, _ = _spies(overrides={"capital_allocation": {"output": {"allocations": allocations}}})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    context = spies["order_validation"].received_contexts[0]
    check(dict(context.parameters) == {"allocations": allocations}, f"C1: OrderValidationSkill context carries {{'allocations': [...]}}; got {dict(context.parameters)!r}")


def scenario_paper_trading_context_carries_orders() -> None:
    orders = [{"symbol": "BBCA", "action": "BUY", "capital": 1000, "status": "APPROVED"}]
    agent, log, spies, _ = _spies(overrides={"order_validation": {"output": {"orders": orders}}})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    context = spies["paper_trading"].received_contexts[0]
    check(dict(context.parameters) == {"orders": orders}, f"C2: PaperTradingSkill context carries {{'orders': [...]}}; got {dict(context.parameters)!r}")


def scenario_trade_history_context_carries_executions() -> None:
    executions = [{"symbol": "BBCA", "execution_status": "EXECUTED"}]
    agent, log, spies, _ = _spies(overrides={"paper_trading": {"output": {"executions": executions}}})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    context = spies["trade_history"].received_contexts[0]
    check(dict(context.parameters) == {"executions": executions}, f"C3: TradeHistorySkill context carries {{'executions': [...]}}; got {dict(context.parameters)!r}")


def scenario_portfolio_update_context_carries_history() -> None:
    history = [{"symbol": "BBCA", "execution_status": "EXECUTED"}]
    agent, log, spies, _ = _spies(overrides={"trade_history": {"output": {"history": history}}})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    context = spies["portfolio_update"].received_contexts[0]
    check(dict(context.parameters) == {"history": history}, f"C4: PortfolioUpdateSkill context carries {{'history': [...]}}; got {dict(context.parameters)!r}")


def scenario_portfolio_monitor_context_carries_portfolio() -> None:
    portfolio = [{"symbol": "BBCA", "status": "OPEN"}]
    agent, log, spies, _ = _spies(overrides={"portfolio_update": {"output": {"portfolio": portfolio}}})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    context = spies["portfolio_monitor"].received_contexts[0]
    check(dict(context.parameters) == {"portfolio": portfolio}, f"C5: PortfolioMonitorSkill context carries {{'portfolio': [...]}}; got {dict(context.parameters)!r}")


def scenario_portfolio_performance_context_carries_monitor_as_portfolio() -> None:
    monitor = [{"symbol": "BBCA", "monitor_status": "ACTIVE"}]
    agent, log, spies, _ = _spies(overrides={"portfolio_monitor": {"output": {"monitor": monitor}}})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    context = spies["portfolio_performance"].received_contexts[0]
    check(dict(context.parameters) == {"portfolio": monitor}, f"C6: PortfolioPerformanceSkill context carries {{'portfolio': [...]}} sourced from monitor output; got {dict(context.parameters)!r}")


def scenario_portfolio_alert_context_carries_performance() -> None:
    performance = [{"symbol": "BBCA", "performance": "TRACKING"}]
    agent, log, spies, _ = _spies(overrides={"portfolio_performance": {"output": {"performance": performance}}})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    context = spies["portfolio_alert"].received_contexts[0]
    check(dict(context.parameters) == {"performance": performance}, f"C7: PortfolioAlertSkill context carries {{'performance': [...]}}; got {dict(context.parameters)!r}")


def scenario_portfolio_report_context_carries_alerts() -> None:
    alerts = [{"symbol": "BBCA", "alert": "WATCH"}]
    agent, log, spies, _ = _spies(overrides={"portfolio_alert": {"output": {"alerts": alerts}}})
    agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000}))
    context = spies["portfolio_report"].received_contexts[0]
    check(dict(context.parameters) == {"alerts": alerts}, f"C8: PortfolioReportSkill context carries {{'alerts': [...]}}; got {dict(context.parameters)!r}")


# N1-N8 -- malformed/missing output at every new stage never raises
def scenario_malformed_capital_allocation_output_yields_empty_allocations() -> None:
    agent, log, spies, _ = _spies(overrides={"capital_allocation": {"output": "not-a-mapping"}})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000})))
    check(exc is None, f"N1: malformed capital_allocation.output never raises; got {exc!r}")
    context = spies["order_validation"].received_contexts[0]
    check(dict(context.parameters) == {"allocations": []}, "N1: malformed output falls back to an empty allocations list")


def scenario_missing_orders_key_yields_empty_orders() -> None:
    agent, log, spies, _ = _spies(overrides={"order_validation": {"output": {}}})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000})))
    check(exc is None, f"N2: missing orders key never raises; got {exc!r}")
    context = spies["paper_trading"].received_contexts[0]
    check(dict(context.parameters) == {"orders": []}, "N2: missing key falls back to an empty orders list")


def scenario_non_list_executions_yields_empty_executions() -> None:
    agent, log, spies, _ = _spies(overrides={"paper_trading": {"output": {"executions": "oops"}}})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000})))
    check(exc is None, f"N3: non-list executions never raises; got {exc!r}")
    context = spies["trade_history"].received_contexts[0]
    check(dict(context.parameters) == {"executions": []}, "N3: non-list value falls back to an empty executions list")


def scenario_none_history_output_yields_empty_history() -> None:
    agent, log, spies, _ = _spies(overrides={"trade_history": {"output": None}})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000})))
    check(exc is None, f"N4: None history .output never raises; got {exc!r}")
    context = spies["portfolio_update"].received_contexts[0]
    check(dict(context.parameters) == {"history": []}, "N4: None .output falls back to an empty history list")


def scenario_missing_monitor_key_yields_empty_performance_input() -> None:
    agent, log, spies, _ = _spies(overrides={"portfolio_monitor": {"output": {}}})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000})))
    check(exc is None, f"N6: missing monitor key never raises; got {exc!r}")
    context = spies["portfolio_performance"].received_contexts[0]
    check(dict(context.parameters) == {"portfolio": []}, "N6: missing monitor key falls back to an empty portfolio list")


def scenario_non_list_alerts_yields_empty_report_input() -> None:
    agent, log, spies, _ = _spies(overrides={"portfolio_alert": {"output": {"alerts": "bad"}}})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"], "capital": 1000})))
    check(exc is None, f"N7: non-list alerts never raises; got {exc!r}")
    context = spies["portfolio_report"].received_contexts[0]
    check(dict(context.parameters) == {"alerts": []}, "N7: non-list value falls back to an empty alerts list")


def scenario_malformed_task_metadata_still_completes_all_14_stages() -> None:
    agent, log, spies, _ = _spies()
    exc = _catch(lambda: agent.execute(_FakeTask("not-a-mapping")))
    check(exc is None, f"N5: malformed task.metadata never raises across the full chain; got {exc!r}")
    check(log.events == _ORDER, "N5: all 14 stages still run despite malformed task.metadata")


# ---------------------------------------------------------------------------
# A1 -- constructor stores the 8 new collaborators by identity; no new
# public methods were introduced beyond execute()
# ---------------------------------------------------------------------------
def scenario_constructor_stores_new_collaborators_and_no_new_public_methods() -> None:
    agent, log, spies, _ = _spies()
    stored = {
        "order_validation": agent._order_validation_skill,
        "paper_trading": agent._paper_trading_skill,
        "trade_history": agent._trade_history_skill,
        "portfolio_update": agent._portfolio_update_skill,
        "portfolio_monitor": agent._portfolio_monitor_skill,
        "portfolio_performance": agent._portfolio_performance_skill,
        "portfolio_alert": agent._portfolio_alert_skill,
        "portfolio_report": agent._portfolio_report_skill,
    }
    check(
        all(stored[stage] is spies[stage] for stage in stored),
        "A1: all 8 new collaborators stored by identity, unwrapped, unmodified",
    )
    public_methods = {name for name in dir(agent) if not name.startswith("_") and callable(getattr(agent, name))}
    check(public_methods == {"execute"}, f"A1: no new public method beyond execute(); got {public_methods!r}")


# D1 -- deterministic repeated execution
def scenario_deterministic_repeated_runs_produce_field_equal_results() -> None:
    agent, log, spies, results = _spies()
    task = _FakeTask({"symbols": ["BBCA"], "capital": 1000})
    result_a = agent.execute(task)
    result_b = agent.execute(task)
    check(
        all(result_a[stage] is result_b[stage] is results[stage] for stage in _ORDER),
        "D1: all 14 results are identical (same spy result objects) across repeated runs",
    )


SCENARIOS = [
    scenario_each_skill_called_exactly_once,
    scenario_skills_called_in_fixed_order,
    scenario_repeated_execute_repeats_the_same_fixed_order,
    scenario_results_forwarded_by_identity,
    scenario_failure_forwarded_and_pipeline_continues,
    scenario_order_validation_context_carries_allocations,
    scenario_paper_trading_context_carries_orders,
    scenario_trade_history_context_carries_executions,
    scenario_portfolio_update_context_carries_history,
    scenario_portfolio_monitor_context_carries_portfolio,
    scenario_portfolio_performance_context_carries_monitor_as_portfolio,
    scenario_portfolio_alert_context_carries_performance,
    scenario_portfolio_report_context_carries_alerts,
    scenario_malformed_capital_allocation_output_yields_empty_allocations,
    scenario_missing_orders_key_yields_empty_orders,
    scenario_non_list_executions_yields_empty_executions,
    scenario_none_history_output_yields_empty_history,
    scenario_missing_monitor_key_yields_empty_performance_input,
    scenario_non_list_alerts_yields_empty_report_input,
    scenario_malformed_task_metadata_still_completes_all_14_stages,
    scenario_constructor_stores_new_collaborators_and_no_new_public_methods,
    scenario_deterministic_repeated_runs_produce_field_equal_results,
]


def main() -> int:
    for scenario in SCENARIOS:
        print(f"-- {scenario.__name__} --")
        scenario()
    print(f"\n{_PASS} PASS / {_FAIL} FAIL")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())