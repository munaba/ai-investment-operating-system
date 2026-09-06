# AIOS Activation 2.1 — Canonical Analysis Path Audit

## Deliverable Report

Status: **AUDIT COMPLETE WITH A STOP CONDITION TRIGGERED (Section 8, item 1).**
This activation identified two independently-wired, both-actively-used
market-analysis chains that overlap in responsibility. Per the STOP
rules, no canonical selection has been *enforced*; Section 5 names a
reasoned **candidate** for "primary/outer" status, but the overlap
itself is left as an open architecture decision for a human to make,
not resolved here. No code was moved, merged, renamed, or deleted.

---

## 1. Files Read

Read in full or in the relevant sections (line-cited below where used
as evidence):

- `main.py`
- `Core/composition_root.py` (2,711 lines — the single object-assembly
  point for the whole application)
- `Core/analysis_pipeline.py`
- `Core/runtime.py` (referenced via composition_root wiring)
- `Agents/stock_agent.py`
- `Agents/market_analysis_agent.py`
- `Agents/executor.py`
- `Agents/tool_registry.py`
- `Orchestration/market_analysis_agent.py`
- `Orchestration/market_analysis_skill.py`
- `Orchestration/text_analysis_skill.py`
- `Orchestration/runtime_analysis_pipeline.py`
- `Orchestration/analysis_pipeline_adapter.py`
- `Orchestration/tool_registry.py`
- `Orchestration/tool_resolver.py`
- `Orchestration/executor.py`
- `Orchestration/watchlist_scanner.py`
- `Orchestration/trading_decision_agent.py` (constructor call site;
  full body out of scope, see Section 10)
- `Orchestration/position_risk_skill.py`
- `Orchestration/market_price_tool.py`, `market_news_tool.py`,
  `market_fundamental_tool.py`
- `Business/manual_scan_service.py`
- `Services/*.py` (import graph only; see Section 3.4)
- `Docs/ACTIVATION 0/AIOS_Activation0_Baseline_Audit.md`,
  `AIOS_Activation0.2_Baseline_Test_Report.md`
- `Docs/ACTIVATION 1/AIOS_Activation1.1_Dependency_Manifest_Report.md`,
  `AIOS_Activation1.5_Command_Validation_Report.md`

Not read line-by-line (out of scope for this activation; flagged in
Section 10): the 14 Skill files that make up
`TradingDecisionAgent`'s chain beyond `MarketAnalysisSkill` and
`PositionRiskSkill`; the Vision pipeline; the Workflow engine family;
all `Tests/` files (used only to corroborate wiring claims, never as a
source of truth for production behavior).

All conclusions below are call-graph findings from the source listed
above, not assumptions. Where I could not fully verify a claim inside
this activation's scope, it is listed as an **Out-of-Scope Finding**
(Section 10), not asserted as fact.

---

## 2. Entry Point Matrix

| Component | Responsibility | Called by | Calls | Dependency | Output | Actually used in production? |
|---|---|---|---|---|---|---|
| `Agents.market_analysis_agent.MarketAnalysisAgent` | Base class providing provider resolution / tool-context plumbing for the **chat/auto** agent lineage | `StockAgent.__init__` (subclass) | provider resolver, tool context builder | none of the analysis services directly | n/a (base class) | **Yes** — `StockAgent` extends it and is the `agent` field the REPL's `chat`/`auto` commands use (`main.py:196`, `main.py:63/73`). |
| `Orchestration.market_analysis_agent.MarketAnalysisAgent` | Hardcoded 3-Skill coordinator: `MarketAnalysisSkill → PortfolioAnalysisSkill → WatchlistAnalysisSkill` (`Orchestration/market_analysis_agent.py:1-45`) | `WatchlistScanner` (`Orchestration/watchlist_scanner.py:50`), constructed in `composition_root.py:1241` | 3 Skill instances via `Task→SkillContext→Skill.execute()` | none — no Tool access of its own; delegates entirely to the 3 Skills | combined `SkillResult` | **Yes** — reached by the `scan` command via `ManualScanService → WatchlistScanner`. |
| `MarketAnalysisSkill` (`Orchestration/market_analysis_skill.py:134`) | Runs `TextAnalysisSkill` once per symbol in `context.parameters["symbols"]` | `Orchestration.market_analysis_agent.MarketAnalysisAgent` (scan path) **and** `_build_trading_decision_agent()` (`composition_root.py:1427`, chat/auto path, see Section 4) | `TextAnalysisSkill.execute()` per symbol | none directly; forwards `_resolve_tool` if injected | `{"stocks": [...]}` | **Yes, in both paths**, via two separately-constructed instances (never the same object). |
| `AnalysisPipeline` (`Core/analysis_pipeline.py`) | Runs an ordered 11-`Service` pipeline over a `ServiceContext` | `StockAgent` (fallback) and `RuntimeAnalysisPipeline` (primary, wraps it as one Tool) | 11 `Service.analyze()` calls in sequence | `StockService`, `TechnicalIndicatorService`, `MovingAverageService`, `TechnicalScoreService`, `FundamentalService`, `PatternService`, `ChartService`, `NewsService`, `BacktestService`, `RiskManagementService`, `ScoringService` (`composition_root.py:1479-1494`) | `Dict[str, ServiceResult]` | **Yes** — built once in `_build_analysis_pipeline()` and is the only object in the codebase that touches all 11 Services in one call. |
| Technical Service (`TechnicalIndicatorService` + `TechnicalScoreService`, plus `MovingAverageService`) | Compute indicators/moving averages and a technical score | `AnalysisPipeline` only | — | `StockService` output (indirectly, via pipeline context) | `ServiceResult` | **Yes**, but **only** inside `AnalysisPipeline`. Never called from the Tool/Skill (`MarketPriceTool`/`TextAnalysisSkill`) side. |
| `FundamentalService` | Fundamental metrics | `AnalysisPipeline` directly, **and** `MarketFundamentalTool` (`Orchestration/market_fundamental_tool.py:96-97`, via `StockService`, not `FundamentalService` itself — see Section 6) | `StockService`/repository | — | `ServiceResult` | **Yes**, in `AnalysisPipeline`. `MarketFundamentalTool` does *not* import `FundamentalService`; it re-derives fundamental data from `StockService` independently. See Duplication Matrix. |
| `NewsService` | News aggregation | `AnalysisPipeline` directly, **and** `MarketNewsTool` (`Orchestration/market_news_tool.py:80`) | `NewsRepository` | — | `ServiceResult` | **Yes, and this one is a true shared dependency**, not a duplicate: both `AnalysisPipeline` and `MarketNewsTool` import the *same* `Services.news_service.NewsService` class. No second news implementation exists. |
| `RiskManagementService` | Portfolio/market-level risk scoring | `AnalysisPipeline` only (`composition_root.py:1492`) | — | — | `ServiceResult` | **Yes, but single-path only.** No Tool or Skill on the scan/trading-decision side imports it. `PositionRiskSkill` (used by `TradingDecisionAgent`) is a **different, position-level** risk calculation with no import of `RiskManagementService` at all (`Orchestration/position_risk_skill.py:124-133`) — not a duplicate of the same responsibility, a genuinely different one. |
| `ToolResolver` (`Orchestration/tool_resolver.py`) | Pure name→Tool lookup against a `ToolRegistry` (`resolve()` only, never executes) | `_build_trading_decision_agent()` (`composition_root.py:1433-1434`, wired onto `market_analysis_skill._resolve_tool`) | `Orchestration.tool_registry.ToolRegistry.get()` | — | resolved Tool instance | **Yes, but scoped to one call site.** Only one `ToolResolver` is constructed in the whole graph, and it is bound only to the `MarketAnalysisSkill` instance inside `TradingDecisionAgent`. |
| `ToolRegistry` — **two classes, same name** | Name→object registry | `Agents.tool_registry.ToolRegistry`: used by `Agents.executor.Executor` (the production Executor, `Agents/executor.py:15,61,85`) and `Agents.sandbox.GenericSandbox`. `Orchestration.tool_registry.ToolRegistry`: used by ~30 Orchestration Skill/Tool modules and by `ToolResolver`. | see above | — | — | **Both are live**, but for disjoint call graphs — see Duplication Matrix item 2. |

---

## 3. Call Graph (Actual, from Source)

### 3.1 Path A — `chat` / `auto` commands (primary REPL path)

```
User (REPL "auto <ticker>" or plain chat text)
  ↓ direct call
main.py:196 app.agent.chat(user_input)          [chat]
main.py:73  agent.run(context, ...)             [auto, agent = app.autonomous_agent]
  ↓ direct call (StockAgent extends Agents.market_analysis_agent.MarketAnalysisAgent)
Agents/stock_agent.py: StockAgent._run_service_pipeline()
  ↓ conditional direct call — composition_root.py:2653 ALWAYS passes a
    non-None runtime_analysis_pipeline in production, so this branch is
    the one actually taken (Agents/stock_agent.py:322,341-342):
Orchestration/runtime_analysis_pipeline.py: RuntimeAnalysisPipeline.run()
  ↓ registers ONE closure as a Tool, then calls it via the shared Executor
    (indirect call — dependency injection, Agents/executor.py Executor,
    which was constructed with Agents.tool_registry.ToolRegistry at
    composition_root.py:2374)
  ↓ inside that Tool closure — direct call:
Core/analysis_pipeline.py: AnalysisPipeline.run(context)
  ↓ direct calls, in fixed order (composition_root.py:1482-1493):
StockService → TechnicalIndicatorService → MovingAverageService →
TechnicalScoreService → FundamentalService → PatternService →
ChartService → NewsService → BacktestService → RiskManagementService →
ScoringService
  ↓ back in RuntimeAnalysisPipeline.run(), AFTER the AnalysisPipeline
    Tool call returns — direct calls, in fixed order, each optional/
    None-guarded (Orchestration/runtime_analysis_pipeline.py:344,506,
    606-663):
memory_recorder → reflector → decision_engine → decision_policy →
policy_guard → execution_intent → execution_planner →
execution_coordinator → portfolio_engine → portfolio_risk →
learning_loop → vision_pipeline → trading_decision_agent.execute(task)
  ↓ direct call — registry lookup for tool resolution (a SECOND,
    independently-constructed ToolRegistry+ToolResolver pair, built
    only here: composition_root.py:1429-1434):
Orchestration/trading_decision_agent.py: TradingDecisionAgent.execute()
  ↓ direct call, first of 14 Skills:
Orchestration/market_analysis_skill.py: MarketAnalysisSkill.execute()
  ↓ direct call, once per symbol:
Orchestration/text_analysis_skill.py: TextAnalysisSkill.execute()
  ↓ registry lookup via self.execute_tool_result(name, context) →
    self._resolve_tool(name) → ToolResolver.resolve(name) →
    Orchestration.tool_registry.ToolRegistry.get(name)
MarketPriceTool / MarketNewsTool / MarketFundamentalTool
  ↓ direct call
StockService (price, fundamental) / NewsService (news)
```

### 3.2 Path B — `scan` command

```
User (REPL "scan")
  ↓ direct call
main.py:192 _run_manual_scan(app) → app.manual_scan_service.run_scan()
  ↓ direct call, LOCKED fixed order (Business/manual_scan_service.py:52-58)
Orchestration/watchlist_scanner.py: WatchlistScanner.scan()
  ↓ direct call, once per watchlist symbol
Orchestration/market_analysis_agent.py: MarketAnalysisAgent.execute()
  ↓ direct call, 3 Skills in fixed order (Orchestration/market_analysis_agent.py:14-24)
MarketAnalysisSkill → PortfolioAnalysisSkill → WatchlistAnalysisSkill
  ↓ (MarketAnalysisSkill only) direct call, once per symbol
TextAnalysisSkill.execute()
  ↓ registry lookup — same three Tools as Path A's tail, but through a
    THIRD, separately-constructed ToolRegistry (this MarketAnalysisSkill
    instance is never the same object as the one in
    _build_trading_decision_agent(); whether it even has _resolve_tool
    injected at all is an Out-of-Scope Finding, Section 10)
MarketPriceTool / MarketNewsTool / MarketFundamentalTool
  ↓
StockService / NewsService
  ↓ (back in WatchlistScanner) direct call
Business/ranking_engine.py: RankingEngine.rank()
  ↓ direct call
Business/recommendation_service.py: RecommendationService.build_recommendations()
  ↓ direct call
Business/report_service.py: ReportService.build_report()
  ↓ direct call, once per Recommendation
Repository/persistence/snapshot_repository.py: SnapshotRepository.create()
  ↓ return
Report → main.py:_print_manual_scan_report()
```

**Legend applied above:** plain arrows = direct call; "registry
lookup" = resolved by name through `ToolRegistry`/`ToolResolver` at
runtime rather than a hardcoded reference; "dependency injection" =
object handed in at `composition_root.py` construction time and never
rebuilt by the receiver.

---

## 4. Analysis Layer Matrix

### Agent layer
- **`Agents.market_analysis_agent.MarketAnalysisAgent`**: orchestration
  base class only (provider selection, tool-context plumbing). No
  business logic of its own.
- **`StockAgent`**: orchestration. Chooses between two pipelines
  (`runtime_analysis_pipeline` if present, else `analysis_pipeline`
  directly) — in production this is not a real choice, since
  `composition_root.py` always supplies both and always passes the
  non-`None` `runtime_analysis_pipeline`, so the `analysis_pipeline`-only
  branch is dead in production (still legitimately live for tests that
  construct `StockAgent` without it).
- **`Orchestration.market_analysis_agent.MarketAnalysisAgent`**: pure
  orchestration, explicitly documented as "not a planner, not a graph,
  not dynamic routing" (`Orchestration/market_analysis_agent.py:26-27`).

### Skill layer
- **`MarketAnalysisSkill`**: reusable in principle (stateless,
  `__init__`-free) and is, in fact, reused — instantiated separately
  in two different production call sites (Path A tail, Path B). Not
  dead code. Not literally duplicate code (one class, two instances),
  but its **effect** duplicates part of what `AnalysisPipeline`
  computes — see Duplication Matrix.
- **`TextAnalysisSkill`**: reusable, used by `MarketAnalysisSkill` in
  both paths.
- **`AnalysisPipelineAdapter`** (`Orchestration/analysis_pipeline_adapter.py`):
  **dead code** in production. Grep-confirmed: no `AnalysisPipelineAdapter(`
  construction call exists anywhere outside its own file. Its sibling
  module's docstring self-documents this: *"`AnalysisPipelineAdapter`
  stays pure delegation, untouched — it already has its own regression
  lock and is out of scope"* (`Orchestration/runtime_analysis_pipeline.py:9-10`).

### Pipeline layer
- **`Core.analysis_pipeline.AnalysisPipeline`**: canonical for
  11-Service sequencing. Not obsolete, not bypassed — every production
  entry into it goes through `RuntimeAnalysisPipeline`.
- **`Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline`**:
  canonical outer kernel for Path A. Wraps `AnalysisPipeline` as a
  single Tool call, then chains ten further stages
  (memory/reflection/decision/policy/execution/portfolio/learning/
  vision/trading-decision), each individually optional via
  constructor default `None`. In production every one of those is
  wired non-`None` (`composition_root.py:2631-2644`), so all ten stages
  are live, not aspirational.
- **`AnalysisPipelineAdapter`**: obsolete/unused (see above).

### Service layer

| Service | Input | Output | Dependency | Side effect | Used? |
|---|---|---|---|---|---|
| `StockService` | ticker/period/interval | price/OHLC data | `StockDataRepository` | none observed | Yes — `AnalysisPipeline` **and** `MarketPriceTool`/`MarketFundamentalTool` |
| `TechnicalIndicatorService` | `StockService` output | indicator set | — | none | Yes — `AnalysisPipeline` only |
| `MovingAverageService` | `StockService` output | MAs | — | none | Yes — `AnalysisPipeline` only |
| `TechnicalScoreService` | indicators/MAs | technical score | — | none | Yes — `AnalysisPipeline` only |
| `FundamentalService` | ticker | fundamental metrics | — | none | Yes — `AnalysisPipeline` only. **Not** used by `MarketFundamentalTool`, which reads fundamentals via `StockService` instead — see Duplication Matrix item 3. |
| `NewsService` | ticker | news items | `NewsRepository` | none | Yes — `AnalysisPipeline` **and** `MarketNewsTool` (same class, not a duplicate) |
| `RiskManagementService` | pipeline context | risk assessment | — | none | Yes — `AnalysisPipeline` only |
| `PatternService`, `ChartService`, `BacktestService`, `ScoringService` | pipeline context | respective outputs | — | none | Yes — `AnalysisPipeline` only; no Tool/Skill counterpart exists for any of these four, so no duplication risk on them |

### ToolResolver / ToolRegistry
- **Who registers:** `_build_analysis_pipeline`-adjacent composition
  code registers `market_price`/`market_news`/`market_fundamental`
  into an `Orchestration.tool_registry.ToolRegistry` at
  `composition_root.py:1429-1432`; a **second**, separately-constructed
  instance of the same three registrations happens again at
  `composition_root.py:1429-1434` inside `_build_trading_decision_agent()`
  (confirmed: these are two different registry objects — the function
  boundary means `tool_registry` is a fresh local each time).
- **Who resolves:** only `ToolResolver.resolve()`, called from
  `BaseSkill.execute_tool_result()` inside `TextAnalysisSkill`.
- **Who uses the registry directly (not through ToolResolver):** ~30
  Orchestration Skill files import `Orchestration.tool_registry`
  for type annotations / `ToolRegistryError` handling, but the actual
  runtime *resolution* path observed in this audit is limited to the
  one `_resolve_tool` injection at `composition_root.py:1434`.
- **Is it canonical?** For the `Orchestration.tool_registry.ToolRegistry`
  family, yes, within its own scope (Tool lookup for
  price/news/fundamental). It has **no relationship at all** to
  `Agents.tool_registry.ToolRegistry`, which is a separate class
  serving `Agents.executor.Executor`/`GenericSandbox` — these two
  registries never share state and were never meant to (see Duplication
  Matrix item 2).
- **Bypass?** `MarketPriceTool`/`MarketNewsTool`/`MarketFundamentalTool`
  can also be — and, per Section 10, may in some code paths be —
  called without ever going through `ToolResolver`, since nothing in
  `BaseSkill` forces `_resolve_tool` to be set; an unset resolver would
  raise rather than silently bypass (confirmed by `ToolResolverError`
  being reserved for exactly that, per its docstring), but I did not
  verify every one of the ~30 Skill call sites individually — flagged
  in Section 10.

---

## 5. Duplication Matrix

| # | What's duplicated | Location A | Location B | Overlap | Actually used | Redundant |
|---|---|---|---|---|---|---|
| 1 | Market analysis orchestration (price+news+fundamental aggregation per symbol) | `AnalysisPipeline` (11 Services, incl. technical score + risk) | `MarketAnalysisSkill`→`TextAnalysisSkill` (3 Tools: price/news/fundamental only, no technical score, no risk) | Partial — both fetch price, fundamentals, and news for the same symbol; A does strictly more (adds technical scoring, risk, pattern, backtest, scoring) | **Both**, in the same `RuntimeAnalysisPipeline.run()` call for Path A (once via `AnalysisPipeline`, once more via `TradingDecisionAgent`'s embedded `MarketAnalysisSkill`), and separately again for Path B (`scan`) | B is redundant *for the subset it covers* only when Path A's tail also runs; for Path B alone (`scan` command) it is the sole analysis mechanism, so it is **not** redundant in that context |
| 2 | `ToolRegistry` class | `Agents.tool_registry.ToolRegistry` | `Orchestration.tool_registry.ToolRegistry` | Name and concept only; disjoint object graphs, disjoint callers | Both | Neither — genuinely separate concerns (agent-level Tool execution vs. Orchestration Skill-level Tool lookup). Confusing, not redundant. Composition root's own comment flags this: *"aliased `OrchestrationToolRegistry` here to avoid colliding with the unrelated `Agents.tool_registry.ToolRegistry`"* (`composition_root.py:1416-1418`). |
| 3 | Fundamental data access | `Services.fundamental_service.FundamentalService` (via `AnalysisPipeline`) | `Orchestration.market_fundamental_tool.MarketFundamentalTool` (via `StockService`, **not** `FundamentalService`) | Two different code paths compute "fundamentals" for the same symbol from two different Services | Both | Not verified which is more complete — Out-of-Scope Finding, Section 10 |
| 4 | `MarketAnalysisAgent` class name | `Agents.market_analysis_agent.MarketAnalysisAgent` | `Orchestration.market_analysis_agent.MarketAnalysisAgent` | Name only; completely different responsibilities (base class vs. 3-Skill coordinator) | Both | Neither — but the identical name across two live, unrelated classes is itself a defect (see Technical Debt) |
| 5 | `Executor` class | `Agents.executor.Executor` (production, wired at `composition_root.py:2374`) | `Orchestration.executor.Executor` | Name and general "runs a Runtime step" concept | `Agents.executor.Executor`: **yes**. `Orchestration.executor.Executor`: **no evidence of production construction found** — only referenced for type annotations inside `Orchestration/workflow_runtime.py` and `Orchestration/workflow_execution_coordinator.py`, and neither `workflow_runtime` nor any `WorkflowEngine`/`WorkflowRuntime` symbol appears anywhere in `composition_root.py` | `Orchestration.executor.Executor` and the whole Workflow-engine family it belongs to appear to be **dead code in production**, pending confirmation (Section 10) |
| 6 | `MarketAnalysisSkill` instantiation | Path A (`_build_trading_decision_agent()`, `composition_root.py:1427`) | Path B (`Orchestration.market_analysis_agent.MarketAnalysisAgent`'s constructor call site, `composition_root.py:884/913`) | Same class, two separate instances, each with its own separately-registered `ToolRegistry` | Both | Not code-redundant (DI, not copy-paste), but **behaviorally** redundant — two independent registries doing the identical three tool registrations |

No two-*ranking*, two-*scoring* flow, or two-*recommendation* flow was
found duplicated: `RankingEngine`, `ScoringService`, and
`RecommendationService`/`RecommendationSkill` are used on genuinely
separate paths (Business-layer scan pipeline vs.
`TradingDecisionAgent`'s `RecommendationSkill`) and were not traced
deeply enough in this activation to confirm or rule out overlap — see
Section 10.

---

## 6. Canonical Path Candidate

**Candidate: Path A — `StockAgent → RuntimeAnalysisPipeline →
(Executor/Tool) → AnalysisPipeline (11 Services) → ... → optional
downstream stages`.**

Technical reasoning:

1. **Most complete.** It is the only path that reaches all 11
   Services, including `TechnicalIndicatorService`,
   `TechnicalScoreService`, `PatternService`, `BacktestService`,
   `ScoringService`, and `RiskManagementService` — none of which have
   any counterpart on Path B.
2. **Most consistent with Activation 1.** Activation 1.5's own LOCKED
   DECISION OVERRIDE explicitly reasons about `app.agent`/provider
   validation as the primary command boundary (`main.py:180-197`,
   docstring citing "Activation 1.5, Section 3"), which is Path A's
   entry.
3. **Least additional change needed to declare canonical.** Path A
   already subsumes Path B's Tool layer (`MarketPriceTool`/
   `MarketNewsTool`/`MarketFundamentalTool` via `TextAnalysisSkill`)
   as its own tail stage (`TradingDecisionAgent`), so naming Path A
   canonical does not require deleting or rewriting Path B's
   components — they already exist as (duplicated) constituents of
   Path A too.

This is a **candidate, not a resolution.** Path B (`scan` command) is
not obsolete: it is the only path reachable from the `scan` command,
which itself is explicitly documented as intentionally
provider-independent (`main.py:189-193`, Activation 1.5 Section 3). A
canonical-path decision that simply deletes or reroutes Path B would
change the `scan` command's no-provider-required guarantee — that is
exactly the kind of "two valid paths requiring an architecture
decision" the STOP rule in Section 8 exists for. This candidate names
what the audit would build *from*, not what should be removed.

---

## 7. Technical Debt

- Two unrelated classes both named `MarketAnalysisAgent`
  (`Agents.` vs `Orchestration.`) and two unrelated classes both named
  `ToolRegistry` (`Agents.` vs `Orchestration.`) — both pairs are live,
  both are only disambiguated today by which module they're imported
  from, and `composition_root.py` itself has to alias one of them
  (`OrchestrationToolRegistry`) to avoid an import collision
  (`composition_root.py:1416-1418`) — a strong signal this naming
  collision is already a known friction point, not just a
  documentation nit.
- `MarketFundamentalTool` computing "fundamentals" from `StockService`
  rather than from `FundamentalService` means the word "fundamental"
  resolves to two different computations depending on which path a
  request takes, with no shared contract enforcing they agree.
- Three separate `ToolRegistry` instances exist for the identical
  three-tool registration (`market_price`/`market_news`/
  `market_fundamental`): one in `_build_analysis_pipeline`-adjacent
  code, one in `_build_trading_decision_agent()`, and (per Section
  3.2) potentially a third implied by Path B — each independently
  constructed rather than shared as one singleton.

## 8. Dead Code Candidate

- `Orchestration/analysis_pipeline_adapter.py` (`AnalysisPipelineAdapter`)
  — confirmed no production construction call anywhere in the
  repository outside its own file; self-documented as out of scope by
  the module that superseded it.
- `Orchestration/executor.py` (`Orchestration.executor.Executor`) and,
  by extension, the Workflow-engine modules that reference it
  (`workflow_runtime.py`, `workflow_execution_coordinator.py`) — no
  construction site found in `composition_root.py`. Flagged as
  **candidate**, not confirmed, since this activation did not
  exhaustively check every non-`composition_root.py` construction
  site (e.g., whether some test-only or CLI-adjacent bootstrap path
  builds it) — see Section 10.

## 9. Out-of-Scope Findings

The following surfaced during this audit but require further
investigation beyond Activation 2.1's scope (Analysis Entry Point /
Call Graph only) to resolve:

1. Whether `FundamentalService` and `MarketFundamentalTool`'s
   `StockService`-derived fundamentals actually agree in output shape
   or diverge in the numbers they'd report for the same ticker.
2. Whether the `MarketAnalysisSkill` instance used inside Path B
   (`Orchestration.market_analysis_agent.MarketAnalysisAgent`'s
   constructor, `composition_root.py:884/913`) ever has `_resolve_tool`
   injected at all — if not, every `TextAnalysisSkill.execute_tool_result()`
   call on the `scan` path would raise rather than silently degrade,
   which materially affects whether Path B is fully functional today.
3. Full confirmation that `Orchestration.executor.Executor` and the
   Workflow-engine family are unreachable from every entry point, not
   just `composition_root.py` (e.g., no separate bootstrap script
   elsewhere in the repo).
4. Whether `RankingEngine`/`ScoringService`/`RecommendationService`
   (Business layer, Path B) and `RecommendationSkill`
   (`TradingDecisionAgent`, Path A tail) compute comparable rankings
   from comparable inputs, or are non-overlapping by design.
5. The full 14-Skill body of `TradingDecisionAgent` beyond
   `MarketAnalysisSkill`/`PositionRiskSkill` was not read in this
   activation.

---

## 10. Recommendation

1. Do not merge, delete, or refactor anything as a result of this
   report — this activation is audit-only, per its own scope.
2. Treat the Section 5/6 overlap (`AnalysisPipeline` vs.
   `MarketAnalysisSkill`/`TextAnalysisSkill`, both reachable inside a
   single Path A `run()` call via `TradingDecisionAgent`) as the
   priority item for a dedicated architecture decision: is
   `TradingDecisionAgent`'s embedded market-analysis re-fetch
   intentional (e.g., a decision-time refresh) or an accidental
   duplicate of work `AnalysisPipeline` already did earlier in the
   same `run()`? This cannot be answered from source alone; it needs
   the original design intent.
3. Resolve the two Out-of-Scope items 2 and 3 above before any future
   activation that touches `ToolResolver` wiring or the Workflow
   engine, since both affect whether components currently assumed
   "used" are actually functioning.
4. Consider (for a future, separate activation — not this one)
   renaming one of the two `MarketAnalysisAgent` classes and one of
   the two `ToolRegistry` classes purely for readability; this audit
   found no functional bug from the collision, only debt.

## 11. Final Status

**Activation 2.1 complete.** Entry points audited, call graph built
from source, layers audited, duplication identified, one canonical
*candidate* named with technical justification, and a STOP condition
(Section 8, rule 1: two valid, both-used paths requiring an
architecture decision) is formally raised for Section 6's core
finding rather than resolved unilaterally. No pipeline was created,
no class was merged, no file was deleted, and no refactor was
performed, per this activation's own constraints.
