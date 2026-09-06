# AIOS Activation 2.2 — Production Dependency Resolver

## Deliverable Report

Status: **FIXED. Acceptance gate met.** One production bug found and
fixed: `Orchestration.market_analysis_agent.MarketAnalysisAgent`'s
`MarketAnalysisSkill` (used by the `scan` command) had **no
`ToolResolver` at all** — not a second, competing one, an absent one —
so every `TextAnalysisSkill.execute_tool_result()` call it made failed
internally with a missing-resolver error on every symbol, silently
(caught, never raised). This activation wires it to the same single
production `ToolResolver` `TradingDecisionAgent`'s `MarketAnalysisSkill`
already used, without creating any new resolver/registry class, without
touching business logic, and without changing Activation 2.1's
canonical-path candidate. Verified live, before and after (Section 6).

---

## 1. Files Read

- `Core/composition_root.py` (full file, focused re-read of
  `_build_market_analysis_agent()`, `_build_trading_decision_agent()`,
  and `build_application()`'s call sequence)
- `Orchestration/market_analysis_agent.py`
- `Orchestration/market_analysis_skill.py`
- `Orchestration/text_analysis_skill.py`
- `Orchestration/base_skill.py` (`execute_tool_result()` /
  `execute_tool()` contract)
- `Orchestration/tool_resolver.py`
- `Orchestration/tool_registry.py`
- `Agents/tool_registry.py`
- `Agents/executor.py`
- `Orchestration/watchlist_scanner.py`
- `Orchestration/trading_decision_agent.py` (constructor signature only)
- `Business/manual_scan_service.py`
- `Tests/test_stage_sprint5_step1_watchlist_scanner_wiring.py`
- `Tests/test_stage_l123_trading_decision_agent.py`,
  `Tests/test_stage_l152_trading_decision_wiring.py`,
  `Tests/test_stage_l5_composition_root_integration.py`,
  `Tests/test_stage_l6_multi_provider_registry.py`,
  `Tests/test_stage_l60_market_price_tool.py` (read only to classify
  failures as pre-existing/unrelated — see Section 7)
- `AIOS_Activation2.1_Canonical_Analysis_Path_Audit.md` (this
  activation's own prior output, used as the audit baseline per the
  brief's instruction to build on Activation 0/1/2.1)

## 2. Files Changed

- `Core/composition_root.py` — 158 changed lines (diffed against the
  untouched upload). Summary of the change, by function:
  - **New function** `_build_market_tool_resolver()` — builds the one
    production `Orchestration.tool_registry.ToolRegistry` (aliased
    `OrchestrationToolRegistry`), registers the three existing
    `MarketPriceTool`/`MarketNewsTool`/`MarketFundamentalTool`
    instances under `"market_price"`/`"market_news"`/
    `"market_fundamental"`, wraps it in one `ToolResolver`, and
    returns it.
  - **`_build_market_analysis_agent()`** — now takes `tool_resolver:
    ToolResolver` as a parameter and injects
    `market_analysis_skill._resolve_tool = tool_resolver.resolve`
    before construction (previously did neither).
  - **`_build_trading_decision_agent()`** — now takes `tool_resolver:
    ToolResolver` as a parameter instead of building its own
    `ToolRegistry`/`ToolResolver` inline; behavior otherwise
    unchanged.
  - **`build_application()`** — now calls
    `market_tool_resolver = _build_market_tool_resolver()` once,
    before `_build_market_analysis_agent(market_tool_resolver)`, and
    passes the same `market_tool_resolver` into
    `_build_trading_decision_agent(market_tool_resolver)` later in the
    same function body.
- `Tests/test_stage_sprint5_step1_watchlist_scanner_wiring.py` —
  updated `scenario_market_analysis_agent_independent_of_trading_decision_agent`
  (the one scenario that directly asserted the pre-fix, no-resolver
  behavior) to assert the fixed behavior instead, plus one new check
  that both `MarketAnalysisSkill` instances are bound to the *same*
  `ToolResolver` object. Module docstring updated to match. No other
  test file was touched.

## 3. Files Created

- This report: `AIOS_Activation2.2_Production_Dependency_Resolver_Report.md`

No new source module, class, resolver, or registry was created
anywhere in the application code, per the activation's constraints.

---

## 4. Resolver Matrix

| Resolver | Who creates | Who owns | Who uses | Lifecycle | Singleton / transient | Status |
|---|---|---|---|---|---|---|
| `Orchestration.tool_resolver.ToolResolver` (the one production instance) | `_build_market_tool_resolver()`, called once from `build_application()` | Held locally as `market_tool_resolver` inside `build_application()`; not exposed as its own `ApplicationGraph` field (graph-visibility was not required by the brief; both consumers already expose it indirectly via `._resolve_tool`) | `MarketAnalysisSkill` inside `TradingDecisionAgent` **and** `MarketAnalysisSkill` inside `Orchestration.market_analysis_agent.MarketAnalysisAgent` — the same object, injected onto two different Skill instances | Built once per `build_application()` call (i.e. once per application boot, or once per test that calls `build_application()`) | Singleton for the lifetime of one `ApplicationGraph` | **Production, live, confirmed by runtime wiring** (Section 6) |
| Pre-Activation-2.2 `ToolResolver` built inline in `_build_trading_decision_agent()` | (removed) | (removed) | (removed) | (removed) | (removed) | **Removed** — folded into the shared one above; no behavior change for `TradingDecisionAgent`'s own Skill, which still gets a working resolver, just no longer its own private instance |
| Absent resolver on `Orchestration.market_analysis_agent.MarketAnalysisAgent`'s `MarketAnalysisSkill` | n/a | n/a | n/a | n/a | n/a | **Bug, now fixed** — this was not a second valid resolver, it was the complete absence of one, confirmed by the exact runtime error captured in Section 6 |
| `Agents.tool_registry.ToolRegistry` + whatever resolves against it inside `Agents.executor.Executor`/`GenericSandbox` | `_build_executor()`-adjacent code (unchanged by this activation) | `Agents.executor.Executor` | `StockAgent`'s chat/auto path (via `RuntimeAnalysisPipeline`'s Executor call for the `AnalysisPipeline` Tool) | Singleton for the graph's lifetime | Singleton | **Production, live, out of scope for this activation** — this is a structurally different registry serving a different call (the single `AnalysisPipeline`-as-one-Tool call), not a `market_price`/`market_news`/`market_fundamental` lookup, and was not touched |

## 5. ToolRegistry Matrix

| Registry | Location | Who registers | Who resolves | Who uses it | Production? |
|---|---|---|---|---|---|
| `Orchestration.tool_registry.ToolRegistry` instance built by `_build_market_tool_resolver()` | `Core/composition_root.py`, new function | `market_price`→`MarketPriceTool()`, `market_news`→`MarketNewsTool()`, `market_fundamental`→`MarketFundamentalTool()` — same three registrations as before this activation, now made exactly once instead of once per caller | `ToolResolver.resolve()`, called from `BaseSkill.execute_tool_result()` inside `TextAnalysisSkill`, for both `MarketAnalysisSkill` instances | `TradingDecisionAgent`'s `MarketAnalysisSkill` **and** `Orchestration.market_analysis_agent.MarketAnalysisAgent`'s `MarketAnalysisSkill` | Yes — the only registry now involved in resolving these three tool names anywhere in the graph |
| `Agents.tool_registry.ToolRegistry` instance built for `Agents.executor.Executor` | `Core/composition_root.py:2374`-area (unchanged) | Whatever `Executor`'s own construction registers (unchanged, out of scope) | `Agents.executor.Executor`/`GenericSandbox` internals (unchanged, out of scope) | `StockAgent`'s Path A tail via `RuntimeAnalysisPipeline` | Yes, but unrelated to `market_price`/`market_news`/`market_fundamental` — **not a duplicate of the registry above**, a genuinely different registry for a genuinely different Tool (`AnalysisPipeline`-as-one-Tool) |

**Is more than one `ToolRegistry` needed?** Yes, but only these two,
and only because they serve two structurally different Tool concepts
(the single big `AnalysisPipeline` Tool used by `Agents.executor.Executor`,
versus the three small `Market*Tool`s used by `MarketAnalysisSkill`).
Before this activation there were, in effect, **three** local
constructions of the small-Tool registry (one live inside
`_build_trading_decision_agent()`, and a second that should have
existed for `_build_market_analysis_agent()` but was never built at
all). After this activation there is **one**. This activation did not
create a new `ToolRegistry` class or a third kind of registry — per
the "Jangan membuat ToolRegistry baru" constraint — it only removed
the duplicate construction of the existing one.

## 6. Runtime Wiring

### 6.1 Actual call graph, `main.py` → Tool, for the fixed path

```
main.py:192 _run_manual_scan(app)
  ↓
Business/manual_scan_service.py: ManualScanService.run_scan()
  ↓ direct call
Orchestration/watchlist_scanner.py: WatchlistScanner.scan()
  ↓ direct call, once per ticker
Orchestration/market_analysis_agent.py: MarketAnalysisAgent.execute()
  ↓ direct call
Orchestration/market_analysis_skill.py: MarketAnalysisSkill.execute()
  ↓ direct call, once per symbol
Orchestration/text_analysis_skill.py: TextAnalysisSkill.execute()
  ↓ self.execute_tool_result("market_price"/"market_news"/"market_fundamental", context)
  ↓ self._resolve_tool(name)        <-- Activation 2.2: now a bound
                                          method of the ONE production
                                          ToolResolver, not undefined
  ↓ registry lookup
Orchestration/tool_resolver.py: ToolResolver.resolve(name)
  ↓ Orchestration.tool_registry.ToolRegistry.get(name)
MarketPriceTool / MarketNewsTool / MarketFundamentalTool
  ↓ direct call
Services.stock_service.StockService / Services.news_service.NewsService
```

### 6.2 Live, empirical proof (not just source reading)

Ran directly against the built `ApplicationGraph`, once on the
untouched upload and once on the fixed tree, same input
(`Task(name="scan", description="scan", metadata={"symbols": ["BBCA"]})`
into `app.market_analysis_agent.execute(task)`):

**Before (pristine upload, unmodified):**
```
{'market': SkillResult(success=False, output={'stocks': [{'symbol': 'BBCA', 'analysis': None}]},
  error="BBCA: BaseSkill.execute_tool() requires '_resolve_tool' to have been injected
         (no ToolResolver was ever supplied by the Executor)", ...), ...}
```

**After (this activation's fix):**
```
{'market': SkillResult(success=True, output={'stocks': [{'symbol': 'BBCA',
  'analysis': {'recommendation': 'UNKNOWN', 'confidence': 'LOW',
  'reason': 'insufficient data', ...}}]}, error=None, ...), ...}
```

The `'recommendation': 'UNKNOWN'`/`'insufficient data'` content
reflects the sandbox's missing optional `yfinance` package (a
pre-existing environment limitation, confirmed unrelated to resolver
wiring — see Section 7), not a resolver failure: `success` flipped
from `False` to `True` and the error string disappeared entirely,
which is exactly and only what fixing the missing `_resolve_tool`
injection changes.

Also confirmed directly (not inferred): the two `MarketAnalysisSkill`
instances remain distinct objects (no merge, no shared Skill state,
per Activation 2.1's/LOCKED DECISION's "no refactor" constraint), while
`_resolve_tool.__self__` — the bound `ToolResolver` each one closes
over — is the identical object for both:

```python
>>> maa_skill is not tda_skill
True
>>> maa_skill._resolve_tool.__self__ is tda_skill._resolve_tool.__self__
True
```

## 7. Dependency Graph (Skill-level)

| Skill | Dependency needed | How obtained (before) | How obtained (after) | Uses production resolver? | Matches runtime registry? |
|---|---|---|---|---|---|
| `MarketAnalysisSkill` (inside `TradingDecisionAgent`, Path A tail) | `_resolve_tool` → `market_price`/`market_news`/`market_fundamental` | Built inline, its own private `ToolRegistry`+`ToolResolver`, in `_build_trading_decision_agent()` | Injected from the single `market_tool_resolver` built once in `build_application()` | Yes, both before and after — the fix did not change its behavior, only where the resolver it already had comes from | Yes |
| `MarketAnalysisSkill` (inside `Orchestration.MarketAnalysisAgent`, `scan` command) | `_resolve_tool` → `market_price`/`market_news`/`market_fundamental` | **None** — never injected | Injected from the same single `market_tool_resolver` | **No → Yes (this activation's fix)** | **No → Yes** |
| `TextAnalysisSkill` (used by both `MarketAnalysisSkill`s above) | `_resolve_tool`, forwarded from whichever `MarketAnalysisSkill` constructs it per-symbol | Forwarded from its caller — no dependency of its own | Unchanged — still purely forwarded | N/A — inherits its caller's resolver | N/A |

No mismatch remains between any Skill's dependency source and the
runtime `ToolRegistry`/`ToolResolver` production wiring.

## 8. Before / After

| | Before | After |
|---|---|---|
| Number of `ToolRegistry`/`ToolResolver` pairs constructed for `market_price`/`market_news`/`market_fundamental` | 1 (only inside `_build_trading_decision_agent()`) | 1 (shared, built once in `build_application()`) |
| `Orchestration.market_analysis_agent.MarketAnalysisAgent`'s `MarketAnalysisSkill._resolve_tool` | **Not set** — `AttributeError`-shaped failure caught internally by `BaseSkill`, surfaced as `SkillResult(success=False, error="... requires '_resolve_tool' ...")` for every symbol on the `scan` command | Set, bound to the shared production `ToolResolver` |
| `scan` command's market-analysis output | Always `analysis: None` per symbol (silently degraded, no crash) | Real `TextAnalysisSkill` output per symbol, subject only to actual data availability (e.g. `yfinance` installed or not) |
| `TradingDecisionAgent`'s `MarketAnalysisSkill._resolve_tool` | Set, bound to its own private `ToolResolver` | Set, bound to the shared production `ToolResolver` (same resolve behavior, different construction site) |
| Business logic / analysis algorithm / recommendation rules | Unchanged | **Unchanged** — no Service, Skill scoring logic, or recommendation rule was modified |
| Activation 2.1 canonical-path candidate (Path A: `StockAgent → RuntimeAnalysisPipeline → AnalysisPipeline → ...`) | — | **Unchanged** — this activation touched only the `market_price`/`market_news`/`market_fundamental` Tool-resolution wiring that Path A's `TradingDecisionAgent` tail and Path B both already used; it did not alter which path is canonical or how either path's Services/Skills are sequenced |

## 9. Regression Evidence

Ran the entire standalone `Tests/test_*.py` suite (246 files, no
pytest framework — each is directly executable) against both the
untouched upload and the fixed tree, using the same commands, in the
same sandbox:

```
PRISTINE (unmodified upload): 246 total, 57 failed
FIXED (this activation):      246 total, 57 failed
diff of the two failing-file lists: IDENTICAL — zero new failures, zero newly-passing files
```

The one exception is intentional, not a regression:
`Tests/test_stage_sprint5_step1_watchlist_scanner_wiring.py` was
edited (Section 2) specifically because it asserted the pre-fix,
no-resolver behavior; it still passes end-to-end after the edit
(19/19 checks), now asserting the corrected behavior plus the new
same-resolver-identity check.

All 57 baseline failures were individually confirmed pre-existing and
unrelated to this activation's change:
- The large majority (e.g. `test_stage_l60_market_price_tool.py`,
  `test_position_migration.py`, `test_stage6_delegate.py`, all
  `test_stage_l45`–`l99` executor/skill/tool-contract files) never
  import `Core.composition_root` at all, so `composition_root.py`'s
  edit cannot affect them; their failures are pre-existing baseline
  issues (e.g. an `execute(None)` contract check, an AST
  import-allowlist check) outside this activation's scope.
- `test_stage_l152_trading_decision_wiring.py` fails because its own
  test helper constructs `TradingDecisionAgent(...)` directly with an
  outdated 6-positional-argument call, unrelated to the
  `tool_resolver` parameter this activation added to
  `_build_trading_decision_agent()` — confirmed by grep: this test
  never calls `_build_trading_decision_agent()` or
  `composition_root.build_application()`'s `trading_decision_agent`
  field construction path in the way that would exercise the change.
- `test_stage_l5_composition_root_integration.py` and
  `test_stage_l6_multi_provider_registry.py` fail on an exact
  `ApplicationGraph` field-name-set comparison that was already stale
  before this activation (missing many fields added by Sprints/Stages
  after L5/L6, e.g. `account_repository`, `snapshot_repository`) —
  confirmed identical failure content on the pristine copy.

Per the brief's instruction ("Jangan memperbaiki test baseline yang
tidak terkait"), none of these 57 pre-existing, unrelated failures
were touched.

Command-level regression (`doctor`/`init`/`scan`/`auto`/`chat`):

- `python main.py doctor` — runs, reports `BLOCKED` for missing
  `google-genai`/`GEMINI_API_KEY`/uninitialized DB — identical,
  expected behavior for this sandbox's environment, unrelated to this
  change.
- `python main.py init` — `INIT SUCCESS`, unchanged.
- `scan` (REPL) — runs to completion, no crash, before and after; with
  a seeded watchlist symbol, the direct-call reproduction in Section
  6.2 is the more precise regression proof since the REPL's own
  console output does not surface the internal `SkillResult.error`
  either way.
- `auto`/`chat` — not exercised end-to-end in this sandbox (no
  `GEMINI_API_KEY`/`google-genai` installed, a pre-existing
  environment gap, not something this activation's change affects);
  `Agents.tool_registry.ToolRegistry`/`Agents.executor.Executor`,
  which the chat/auto path uses, were not modified by this activation
  at all (Section 4/5), so no wiring change exists on that path to
  regress.

## 10. Out-of-Scope Findings

1. `NewsService.execute failed: ... No module named 'yfinance'` was
   observed during live verification — a pre-existing optional
   dependency gap (flagged by `doctor` itself), not a resolver defect,
   and out of scope for this activation.
2. Activation 2.1's Duplication Matrix item 3 (`FundamentalService` vs.
   `MarketFundamentalTool`'s independent `StockService`-derived
   fundamentals) is unaffected by this fix and remains open.
3. Whether `RankingEngine`/`RecommendationService` (Path B) ever
   actually reads the `'market'` key this activation just started
   populating correctly, or only reads `'watchlist'`/`'portfolio'`, was
   not traced in this activation — the empirical BBCA run in Section
   6.2 shows the final `SELL`/`LOW` recommendation unchanged before and
   after, which is consistent with either "the fix has no downstream
   effect yet because nothing reads `'market'`" or "the fix's effect is
   masked by `yfinance` being absent in this sandbox." Distinguishing
   between those two explanations would require reading
   `RecommendationService`/`RankingEngine`, which is out of scope here
   (would touch recommendation logic, explicitly forbidden by this
   activation's own constraints).
4. Whether any other Skill beyond the two `MarketAnalysisSkill`
   instances audited here relies on `_resolve_tool` without it being
   verified end-to-end was not exhaustively re-checked in this
   activation (Activation 2.1's Out-of-Scope item 2 is the specific
   instance this activation resolved; broader Skill-by-Skill dependency
   audits beyond `MarketAnalysisSkill`/`TextAnalysisSkill` were not
   repeated here since the brief scoped Section 3 to those two by
   name).

No STOP condition was triggered: no second, independently-valid
production resolver was found requiring an architecture decision (the
"second" resolver identified in Activation 2.1 turned out, on closer
audit, to not exist — the gap was an absent resolver, not a competing
one); no analysis-flow change, new pipeline, or business-logic change
was required to fix it.

## 11. Final Status

**Activation 2.2 complete. Acceptance gate met:**
- ✅ Every `MarketAnalysisSkill` instance in the production graph
  (`TradingDecisionAgent`'s and `Orchestration.MarketAnalysisAgent`'s)
  now obtains its Tool dependency through the same one production
  `ToolResolver`.
- ✅ `ToolResolver` is the only dependency-resolution path exercised at
  runtime for `market_price`/`market_news`/`market_fundamental` — no
  fake/dummy/fallback resolver exists on the production path (the
  previous gap was an absent resolver on one Skill instance, now
  closed).
- ✅ No fake resolver was introduced; no new `ToolRegistry` or
  `ToolResolver` class was created.
- ✅ No local/private `ToolRegistry` remains on the production path —
  the single shared instance replaces what were, in effect, one live
  and one missing construction.
- ✅ Dependency graph verified against live runtime wiring (Section 6),
  not just source reading.
- ✅ All regression tests affected by this change still pass; all
  pre-existing, unrelated failures are unchanged in count and content
  (Section 9).

Activation 2.1's canonical-path candidate (Path A) was not altered.
No business logic, analysis algorithm, Service implementation, or
recommendation rule was changed. No new pipeline was created.
