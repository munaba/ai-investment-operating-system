"""
Sprint 5 STEP 1 proof suite -- WatchlistRepository + MarketAnalysisAgent
wiring into Core.composition_root, and WatchlistScanner.

Scope (per Sprint 5 STEP 1 LOCKED DECISION, Revisi): this proves
exactly what that decision authorized, no more:

  1. ``build_application()`` still builds without raising.
  2. ``graph.watchlist_repository`` is a real, production
     ``WatchlistRepository`` -- constructed over the exact same
     ``database_manager`` instance as the graph itself (identity, not
     just type/equality).
  3. ``graph.market_analysis_agent`` is a real, production
     ``Orchestration.market_analysis_agent.MarketAnalysisAgent`` (the
     Phase 11 Sprint 119 three-Skill coordinator) -- never the
     unrelated ``Agents.market_analysis_agent.MarketAnalysisAgent``
     abstract base class.
  4. ``graph.market_analysis_agent`` is NOT the same
     ``MarketAnalysisSkill`` *instance*
     ``_build_trading_decision_agent()`` builds -- ``TradingDecisionAgent``
     remains an untouched black box (no refactor happened per LOCKED
     DECISION rule 3). Activation 2.2 update: both instances now
     resolve tools through the same single production ``ToolResolver``
     (see ``_build_market_tool_resolver()``), so neither is left
     without one.
  5. ``WatchlistScanner`` (construction-only dependency shape: exactly
     ``WatchlistRepository`` + ``MarketAnalysisAgent``) calls
     ``MarketAnalysisAgent.execute()`` exactly once per ticker and
     collects each result, using a stub ``WatchlistRepository`` and a
     spy ``MarketAnalysisAgent`` -- no real database connection, no
     real Skill execution, matching the hermetic, no-I/O pattern every
     other ``Tests/test_stage_*.py`` file in this project already uses.

It deliberately does NOT test ``WatchlistRepository``'s own CRUD
behavior, and does NOT exercise ``MarketAnalysisSkill``/``TextAnalysisSkill``
end-to-end against real Tools/Services -- only that a real resolver is
now attached (Activation 2.2), not what it returns when called.

Run directly: ``python Tests/test_stage_sprint5_step1_watchlist_scanner_wiring.py``
-- no external test framework required, matching every other
``Tests/test_stage_*.py`` file in this project.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Agents.market_analysis_agent import MarketAnalysisAgent as AgentsMarketAnalysisAgent  # noqa: E402
from Core.composition_root import ApplicationGraph, build_application  # noqa: E402
from Orchestration.market_analysis_agent import MarketAnalysisAgent  # noqa: E402
from Orchestration.task import Task  # noqa: E402
from Orchestration.watchlist_scanner import WatchlistScanner  # noqa: E402
from Repository.persistence.watchlist_repository import WatchlistRepository  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


def scenario_graph_builds_without_raising() -> ApplicationGraph:
    """build_application() still builds without raising after this addition."""
    graph = build_application(
        provider_name="gemini-sprint5-step1-test",
        agent_name="sprint5-step1-test-agent",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    return graph


def scenario_watchlist_repository_present_and_real(graph: ApplicationGraph) -> None:
    """graph.watchlist_repository is a real, production WatchlistRepository,
    sharing the graph's own database_manager instance."""
    check(
        isinstance(graph.watchlist_repository, WatchlistRepository),
        "graph.watchlist_repository is a real WatchlistRepository instance",
    )
    check(
        graph.watchlist_repository._database_manager is graph.database_manager,
        "graph.watchlist_repository shares the exact same database_manager instance as the graph",
    )


def scenario_market_analysis_agent_present_and_real(graph: ApplicationGraph) -> None:
    """graph.market_analysis_agent is the Orchestration MarketAnalysisAgent,
    never the unrelated Agents.MarketAnalysisAgent ABC."""
    check(
        isinstance(graph.market_analysis_agent, MarketAnalysisAgent),
        "graph.market_analysis_agent is an Orchestration.market_analysis_agent.MarketAnalysisAgent instance",
    )
    check(
        not isinstance(graph.market_analysis_agent, AgentsMarketAnalysisAgent),
        "graph.market_analysis_agent is NOT an Agents.market_analysis_agent.MarketAnalysisAgent (unrelated ABC)",
    )


def scenario_market_analysis_agent_independent_of_trading_decision_agent(graph: ApplicationGraph) -> None:
    """graph.market_analysis_agent's MarketAnalysisSkill is NOT the same
    *instance* TradingDecisionAgent uses -- no Skill sharing, no
    refactor of either Agent. Activation 2.2 (Production Dependency
    Resolver): both Skill instances now resolve tools through the same
    single production ToolResolver, so a resolver is present on both
    -- neither is left with a missing/fake resolver, and no second,
    independently-constructed ToolRegistry/ToolResolver exists in the
    graph."""
    tda_market_skill = graph.trading_decision_agent._market_analysis_skill
    maa_market_skill = graph.market_analysis_agent._market_analysis_skill
    check(
        tda_market_skill is not maa_market_skill,
        "market_analysis_agent's MarketAnalysisSkill is a distinct instance from TradingDecisionAgent's",
    )
    check(
        hasattr(maa_market_skill, "_resolve_tool"),
        "market_analysis_agent's MarketAnalysisSkill now has _resolve_tool injected (Activation 2.2 fix)",
    )
    check(
        hasattr(tda_market_skill, "_resolve_tool"),
        "TradingDecisionAgent's own MarketAnalysisSkill still has its _resolve_tool",
    )
    check(
        maa_market_skill._resolve_tool.__self__ is tda_market_skill._resolve_tool.__self__,
        "both MarketAnalysisSkill instances are bound to the exact same production ToolResolver "
        "(no second, independently-constructed ToolRegistry/ToolResolver)",
    )


def scenario_build_application_is_idempotent() -> None:
    """Calling build_application() a second time does not raise (re-entrant
    registries), same guarantee every other addition in this module keeps."""
    build_application(
        provider_name="gemini-sprint5-step1-test-2",
        agent_name="sprint5-step1-test-agent-2",
    )
    check(True, "build_application() can be called a second time without raising")


class _SpyMarketAnalysisAgent:
    """A minimal stand-in for MarketAnalysisAgent: records every task it
    was called with, and returns a distinct, identifiable result per
    call -- no real Skill execution, no I/O.
    """

    def __init__(self) -> None:
        self.calls: List[Any] = []

    def execute(self, task: Any) -> dict:
        self.calls.append(task)
        symbols = task.metadata.get("symbols") if isinstance(task.metadata, dict) or hasattr(task.metadata, "get") else []
        return {"market": f"result-for-{list(symbols)}"}


class _StubWatchlistRepository:
    """A minimal stand-in for WatchlistRepository.list_all() -- no
    database connection, no I/O."""

    def __init__(self, tickers: List[str]) -> None:
        self._tickers = tickers

    def list_all(self) -> List[str]:
        return list(self._tickers)


def scenario_watchlist_scanner_construction_shape() -> None:
    """WatchlistScanner takes exactly two constructor arguments:
    WatchlistRepository, MarketAnalysisAgent."""
    stub_repo = _StubWatchlistRepository(["BBCA", "TLKM"])
    spy_agent = _SpyMarketAnalysisAgent()
    scanner = WatchlistScanner(stub_repo, spy_agent)
    check(
        scanner._watchlist_repository is stub_repo,
        "WatchlistScanner stores watchlist_repository by identity",
    )
    check(
        scanner._market_analysis_agent is spy_agent,
        "WatchlistScanner stores market_analysis_agent by identity",
    )


def scenario_watchlist_scanner_calls_agent_once_per_ticker() -> None:
    """scan() calls MarketAnalysisAgent.execute() exactly once per
    ticker, each with a Task carrying metadata={"symbols": [ticker]},
    and collects each result keyed by ticker."""
    stub_repo = _StubWatchlistRepository(["BBCA", "TLKM", "ASII"])
    spy_agent = _SpyMarketAnalysisAgent()
    scanner = WatchlistScanner(stub_repo, spy_agent)

    results = scanner.scan()

    check(len(spy_agent.calls) == 3, "MarketAnalysisAgent.execute() was called exactly 3 times (once per ticker)")
    check(
        all(isinstance(call, Task) for call in spy_agent.calls),
        "every call to MarketAnalysisAgent.execute() was passed a real Task instance",
    )
    check(
        [dict(call.metadata)["symbols"] for call in spy_agent.calls] == [["BBCA"], ["TLKM"], ["ASII"]],
        "each Task carries metadata={'symbols': [ticker]} for its own ticker, in watchlist order",
    )
    check(
        set(results.keys()) == {"BBCA", "TLKM", "ASII"},
        "scan() returns a dict keyed by every ticker in the watchlist",
    )
    check(
        results["BBCA"] == {"market": "result-for-['BBCA']"},
        "scan() forwards each ticker's MarketAnalysisAgent.execute() result unchanged",
    )


def scenario_watchlist_scanner_empty_watchlist() -> None:
    """scan() with an empty watchlist calls the agent zero times and
    returns an empty dict -- never raises."""
    stub_repo = _StubWatchlistRepository([])
    spy_agent = _SpyMarketAnalysisAgent()
    scanner = WatchlistScanner(stub_repo, spy_agent)

    results = scanner.scan()

    check(spy_agent.calls == [], "MarketAnalysisAgent.execute() was never called for an empty watchlist")
    check(results == {}, "scan() returns an empty dict for an empty watchlist")


def main() -> int:
    print("scenario_graph_builds_without_raising")
    try:
        graph = scenario_graph_builds_without_raising()
    except Exception:  # noqa: BLE001
        global _FAIL
        _FAIL += 1
        _FAILURES.append("scenario_graph_builds_without_raising raised an unexpected exception")
        print("  ERROR - build_application() raised unexpectedly:")
        traceback.print_exc()
        graph = None

    scenarios_needing_graph = [
        scenario_watchlist_repository_present_and_real,
        scenario_market_analysis_agent_present_and_real,
        scenario_market_analysis_agent_independent_of_trading_decision_agent,
    ]
    if graph is not None:
        for scenario in scenarios_needing_graph:
            print(f"\n{scenario.__name__}")
            try:
                scenario(graph)
            except Exception:  # noqa: BLE001
                _FAIL += 1
                _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
                print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
                traceback.print_exc()

    standalone_scenarios = [
        scenario_build_application_is_idempotent,
        scenario_watchlist_scanner_construction_shape,
        scenario_watchlist_scanner_calls_agent_once_per_ticker,
        scenario_watchlist_scanner_empty_watchlist,
    ]
    for scenario in standalone_scenarios:
        print(f"\n{scenario.__name__}")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"SPRINT 5 STEP 1 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())