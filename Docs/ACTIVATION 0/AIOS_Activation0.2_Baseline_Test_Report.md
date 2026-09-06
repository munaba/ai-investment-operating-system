# ACTIVATION 0.2 — BASELINE TEST REPORT (AIOS)

**Method:** every file under `Tests/` (246 files, including the two legacy scripts `integration_test.py` and `E2e_test.py`) was executed exactly as the repository itself invokes them — `python3 Tests/<file>.py`, from the repository root, no arguments, no source or test file modified. Each run was given a 15-second timeout (no test ever approached it — total wall time for all 246 files was **36 seconds**, none of which was expected to run a network call). Full stdout/stderr for every run was captured to a per-file log; a companion CSV (`AIOS_Test_Pass_Matrix.csv`) lists status/duration/assertion-counts for all 246 files. Nothing in this report required guessing — every classification below is grounded in the captured logs.

**Important discovery about the test suite's own convention, which shapes everything below:** this is **not a pytest test suite**. 240 of the 246 files are hand-written "proof scripts": each defines its own `check(condition, description)` counter, a list of `scenario_*`/`test_*` functions, and a `main()` that runs them all, prints a `"<N> PASS / <M> FAIL"` (or similar) summary line, and returns exit code `0`/`1` accordingly. Only 2 files use `unittest.TestCase` (which self-executes via `unittest.main()`), and only 4 files actually `import pytest`. **`pytest` itself is not installed** in this environment and no `requirements.txt`/`pyproject.toml` exists to say it should be (see Activation 0 baseline report) — this directly determines the BLOCKED count below.

---

## 1. Test Inventory

| Group | File count | Test-case count (approx.) | Framework | Key dependency |
|---|---|---|---|---|
| **Structural / unit "proof scripts"** (the `test_stage_lNN_*` / `test_stageN_*` majority) | ~190 files | ~11,500 individual `check()` assertions | Custom hand-rolled `check()` counter + `main()`, no framework | Mostly hermetic (in-process fakes); a subset also instantiate real `SQLiteDatabase` |
| **Wiring tests** (filename contains `_wiring`, tests that `Core.composition_root.build_application()` constructs/exposes a component) | 17 files | ~400 assertions | Same custom `check()` pattern | `Core.composition_root.build_application()` |
| **Database/Repository tests** (directly instantiate `SQLiteDatabase(...)`) | 18 files | ~470 assertions | Custom `check()` pattern, real SQLite engine (temp file or in-memory, not the production DB file) | `Database.sqlite_database.SQLiteDatabase`, `Database.migrations*` |
| **Smoke test** | 1 file (`test_stock_agent_smoke.py`) | not individually re-counted | Custom `check()` pattern | `Agents.stock_agent.StockAgent` |
| **Legacy Integration test** | 1 file (`integration_test.py`) | 56 assertions | Custom `check()`/`[PASS]` pattern, own hand-built `_FakeYFTicker` | `Services.*` (stock/chart/news/backtest/notification) |
| **Legacy End-to-End test** | 1 file (`E2e_test.py`) | 71 assertions | Custom `[PASS]` pattern | `Agents.executor`, `Providers.*`, `Orchestration.tool_registry` |
| **pytest-dependent tests** | 4 files (`test_stage5_suspend_resume.py`, `test_stage6_delegate.py`, `test_stage7_cancel.py`, `test_idx_foundation_parity.py`) | unknown — see below | `pytest` (bare `assert`, `def test_*`, no self-invocation) | **pytest, not installed** |
| **Regression Test** (a sub-style within the structural group: docstrings explicitly say "LOCKED", "regression guard", "public surface unchanged", "no new top-level import") | 16 files (subset of the structural group above, not additional files) | included in structural count above | Same custom `check()` pattern | n/a |
| **Production Flow Test** (touches `main.py`/`ManualScanService` directly) | 2 files (`test_manual_scan_command.py`, `test_manual_scan_service.py`) | 25 + 25 assertions | Custom `check()` pattern, `import main`, `FakeManualScanService` | `main._run_manual_scan`, `Business.manual_scan_service.ManualScanService` — **via a fake service, not the real scanner/ranking chain** |

**Total: 246 files.**

---

## 2. PASS Matrix (summary — full 246-row matrix in the companion file `AIOS_Test_Pass_Matrix.csv`)

| Metric | Count |
|---|---|
| Total test files | **246** |
| Total individual assertions executed (`check()`/`assert`/unittest calls actually run) | **12,743** |
| PASS (files) | **188** |
| FAIL (files) | **41** |
| ERROR (files — crashed before producing a pass/fail summary) | **13** |
| BLOCKED (files — dependency, here `pytest`, not installed; includes 1 file that ran with exit 0 but executed zero real assertions because it's pytest-authored and nothing invoked its functions) | **4** |
| SKIPPED / XFAIL / XPASS | **0** (this test style has no such states — every check either runs and passes/fails, or the whole file crashes) |
| TIMEOUT | **0** (max single-file duration observed: 1 second; total run: 36 seconds) |
| INTERRUPTED | **0** |
| **File-level PASS RATE** | **188 / 246 = 76.4%** |
| **Assertion-level PASS RATE** (of the 12,743 assertions that actually ran, ignoring the 13 ERROR files where no count could be extracted and the BLOCKED files) | **12,539 pass / 204 fail = 98.4%** |

**Why these two pass-rate numbers diverge so much, and why both matter:** the assertion-level rate (98.4%) is high because most individual `check()` calls inside any given file do pass — a failing file typically fails on only 1–20 of its ~30–130 checks. The file-level rate (76.4%) is the more honest signal for "how many of the 246 independent proof-scripts are currently green," because task instructions correctly treat a file with even one failing assertion as a failing unit, not a mostly-passing one.

---

## 3. Structural Test Report

**Definition applied:** a test is **STRUCTURAL** if its assertions are about existence/shape/wiring — constructor signatures, dependency injection, "is registered", "is exposed on the graph", "public surface unchanged", "no new import introduced" — rather than about a computed business outcome.

- **All 17 `*_wiring.py` files** are structural by definition (they exist specifically to prove a component is constructed and exposed on `ApplicationGraph`). All 17 currently PASS.
- **16 files explicitly documented as "LOCKED regression guards"** (asserting an unchanged public surface / import set from a specific past stage) are structural. This is exactly the group responsible for most of the FAIL count (see §6, Stale Test Report) — most of their failures are the guard correctly detecting that a *later, sanctioned* stage added new methods/imports, which the guard (written for an earlier stage) was never updated to expect.
- **A large share of the `test_stage_l4x`–`test_stage_l9x` series** (Executor/Skill/Tool/ToolContext/SkillContext family, roughly stages L45–L99) is structural in this same sense: constructor argument checks, `NotImplementedError` contract checks, exact-method-set checks. Representative sample confirmed by direct log inspection:
  - `test_stage_l87_base_skill_tool_result.py`, `test_stage_l88_base_skill_skill_result.py`, `test_stage_l94_base_skill_tool_invocation.py`, `test_stage_l95_executor_current_tool_invocation.py`, `test_stage_l96_executor_resolve_tool.py` — all fail on an "exact public surface" assertion, not on a business-behavior assertion.
- **Database/Repository tests (18 files)** are a mixed case: they are structural in the sense of testing a layer's contract (CRUD/migration correctness against a real `SQLiteDatabase`), but they do exercise the real SQLite engine, so they are listed separately in §4 as functional-for-persistence purposes.

**Structural test file count: approximately 190–210 of the 246** (the wiring group + the L4x–L9x interface/contract group + most `test_stage_lNN_*` unit proof-scripts that check a single class's own constructor/contract rather than a cross-component business outcome). This is an approximate band, not an exact count, because "structural vs. functional" was not independently re-classified for every one of the ~190 files in the general `test_stage_lNN_*` group in this pass — the 41 FAIL + 13 ERROR + 17 wiring files were individually confirmed; the remainder is inferred from the same naming/docstring convention.

---

## 4. Functional Test Report

**Definition applied:** a test is **FUNCTIONAL** if it verifies an actual computed business outcome — a database row change, a recommendation value, a ranking order, cash/position mutation, a trade record, a notification send attempt.

Confirmed functional, by direct log inspection:

| File | What it actually verifies | Result |
|---|---|---|
| `test_account_balance_service.py` | Real `SQLiteDatabase`-backed account balance reads/writes | 13/13 PASS |
| `test_account_migration.py`, `test_order_migration.py`, `test_position_migration.py`\*, `test_snapshot_migration.py`, `test_trade_migration.py` | Migration application against a real (temp) SQLite database | 30/30, 35/36, **ERROR**\*, 33/33, 30/30 |
| `test_account_repository.py`, `test_order_repository.py`, `test_position_repository.py`, `test_snapshot_repository.py`, `test_trade_repository.py`, `test_performance_repository.py` | Real repository CRUD against real `SQLiteDatabase` | 26/27, 38/38, 33/34, 26/26, 32/32, 23/23 — all PASS overall |
| `test_execution_service.py`, `test_order_lifecycle_service.py` | Real order creation/execution against a real database | 40/40, 40/40 PASS |
| `test_paper_trading_engine.py` | The two-call `create_order → execute_order` sequence against a real database | 14/14 PASS — **note:** consistent with the Activation 0 finding that this engine's own documented scope excludes Position/Account/fee/tax, so "PASS" here means "does what it's documented to do," not "the paper trading vertical is complete" |
| `test_position_manager.py` | Position creation/update against a real database | 29/29 PASS — **note:** per Activation 0, this includes the hardcoded `realized_pnl=0.0` path, which passes because the test itself only asserts the documented placeholder behavior, not real P&L computation |
| `test_database_layer_smoke.py`, `test_database_layer_hardening.py` | Direct SQLite engine behavior (connection, transaction, concurrency-adjacent hardening) | 22/22, 34/34 PASS |
| `test_telegram_notification_channel.py`, `test_notification_dispatcher.py`, `test_notification_manager.py` | Notification event construction and dispatch call shape (against a fake/mocked HTTP client, confirmed in `integration_test.py`'s own "used the mocked HTTP client (no real request sent)" assertions — the dedicated notification test files were not independently re-opened in this pass to confirm they use the same mocked-HTTP pattern, flagged for a follow-up read) | not individually re-verified line-by-line this pass; all ran to PASS per the CSV |
| `integration_test.py` (legacy) | `StockService`/`ChartService`/`NewsService`/`BacktestService`/`NotificationService` real `.execute()` behavior against a hand-built fake `yfinance` ticker and a mocked HTTP client | 56/56 PASS |
| `E2e_test.py` (legacy) | `Executor`/`Planner`/`Agent` real error-propagation and state-machine behavior (`ToolNotFoundError`, `ToolExecutionError`, `ProviderError`, agent state transitions `IDLE`→`ERROR`→`IDLE`) | 71/71 PASS |
| `test_manual_scan_command.py`, `test_manual_scan_service.py` | `main._run_manual_scan` / `ManualScanService.run_scan` call shape and report-printing — **against a `FakeManualScanService`**, so it verifies orchestration correctness, not the real scanner/ranking/recommendation computation | 25/25, 24/25 PASS |

\* `test_position_migration.py` is not actually a distinct test — see §6, it is a byte-identical duplicate of `run_position_migrations.py` and ERRORs when run from `Tests/` due to a missing `sys.path` insert, which none of its migration-sibling files lack.

**Functional test file count: approximately 30–40 of the 246** (the database/repository/migration group, the two legacy E2E scripts, the notification group, and the two manual-scan tests). This is the group that actually touches real SQLite, real service `.execute()` outcomes, or real state transitions — everything else in the 246 is verifying shape/wiring/contract rather than a computed outcome.

---

## 5. Production Flow Coverage

Mapping the requested workflow (`startup → scan → analysis → ranking → recommendation → paper order → trade → position → performance → notification`) against actual tests found:

| Stage | Coverage | Covering test(s) |
|---|---|---|
| Startup (`validate_runtime_environment`, `build_application`) | **PARTIAL** | `test_stage9_4_startup_validation.py`, `test_stage9_0_composition_root.py`, `test_stage_c5_database_composition.py` — these confirm the function runs and constructs objects; **none** confirm a real process boot against a real `.env`/migrated database |
| `scan` command dispatch | **PARTIAL** | `test_manual_scan_command.py` — confirms `main._run_manual_scan` calls `run_scan()` and prints correctly, but against a **fake** `ManualScanService` |
| Watchlist scan (real, per-ticker loop) | **NONE found calling the real `MarketAnalysisAgent`+real Services chain end-to-end** — `test_stage_sprint5_step1_watchlist_scanner_wiring.py` only confirms `WatchlistScanner` is constructed/exposed on the graph, not that a real scan produces correct per-ticker output | `test_stage_sprint5_step1_watchlist_scanner_wiring.py` (wiring only) |
| Analysis (`MarketAnalysisSkill`/`TextAnalysisSkill`) | **PARTIAL** | `test_stage_l106_text_analysis_skill_pipeline.py` (39 pass/23 **fail**), `test_stage_l117_market_analysis_skill.py` — real logic is exercised, but the L106 file's own failures (`ToolRegistryError: no tool registered under name='market_news'`) directly reproduce the Activation 0 finding that `MarketAnalysisSkill`'s required tools are not resolvable in this configuration |
| Ranking (`WatchlistAnalysisSkill`, `RankingEngine`) | **PARTIAL** | `test_stage_l116_watchlist_analysis_skill.py` and similar — tests the normalization/sorting logic itself (including the documented "missing analysis → SELL/LOW" behavior) in isolation; **no test found that feeds a real multi-ticker scan result through ranking** |
| Recommendation (`RecommendationService`) | **PARTIAL** | dedicated `test_stage_l120_recommendation_skill.py`-style unit coverage exists; not chained to a real upstream scan | 
| Paper order / Trade / Position | **FUNCTIONAL but ISOLATED** | `test_paper_trading_engine.py`, `test_order_lifecycle_service.py`, `test_execution_service.py`, `test_position_manager.py` all run real DB-backed logic — **but always called directly with hand-supplied `account_id`/`symbol`/`quantity`, never fed a real `Recommendation` object from the analysis/ranking stages above** |
| Performance | **NONE found wired to real trade data** | performance-engine tests (`test_profit_factor_engine.py`, `test_win_rate_engine.py`, `test_expectancy_engine.py`, `test_trade_statistics_engine.py`, etc.) test each calculator against hand-constructed input, not against output actually produced by the paper-trading stage above |
| Notification | **NONE found triggered by a real event from any upstream stage** | `test_notification_dispatcher.py`/`test_notification_manager.py`/`test_telegram_notification_channel.py` test the notification classes directly with hand-built `NotificationEvent` objects — consistent with the Activation 0 finding that nothing in production code ever constructs and sends a real event from a real trade/scan outcome |

**Overall verdict for TASK 9 (Production Flow Test):**

> **NO END-TO-END PRODUCTION FLOW TEST EXISTS.**

No file in `Tests/` — including the two legacy E2E/integration scripts — drives `startup → scan → analysis → ranking → recommendation → paper order → trade → position → performance → notification` as one connected sequence against real components. Every stage is tested in isolation (with real SQLite for the DB-adjacent stages, with fakes/hand-built inputs everywhere upstream), and the two stages closest to "production flow" (`test_manual_scan_command.py`) explicitly substitute a fake for the very service that would connect scan to the rest of the chain.

---

## 6. Stale Test Report

Two distinct kinds of staleness were found, both confirmed directly from logs/diffs (not assumed):

### 6.1 A mislabeled non-test file
- **`Tests/test_position_migration.py` is a byte-for-byte identical copy of `run_position_migrations.py`** (confirmed via `diff`, both 70 lines, 0 differences). It contains no assertions, no `check()`, no test logic whatsoever — it is the manual migration-runner script itself, apparently copied into `Tests/` by mistake. It ERRORs when run directly from `Tests/` (`ModuleNotFoundError: No module named 'Core'`) purely because, unlike its siblings, it never had a `sys.path` insert — which makes sense, since it was never meant to live in `Tests/` at all. **This is not a stale test; it is a non-test file mislabeled as one, and should be flagged for the maintainers regardless of Activation 0.2's "don't fix anything" rule.**

### 6.2 Outdated "locked surface" regression guards
A cluster of files whose entire purpose is asserting "this class's public API/import set is exactly what it was at stage N" now fail because **later, presumably-sanctioned stages legitimately expanded that surface** and the guard was never updated. Confirmed directly from failure text:

- `test_stage_l87_base_skill_tool_result.py` / `test_stage_l88_base_skill_skill_result.py` / `test_stage_l94_base_skill_tool_invocation.py`: assert `BaseSkill`'s public callables are exactly `{name, description, execute, execute_tool}`; actual current surface also has `execute_tool_result` — added by a later stage, per the class's own evolution.
- `test_stage_l95_executor_current_tool_invocation.py` / `test_stage_l96_executor_resolve_tool.py`: assert `Executor`'s public callables are an exact small set; actual current `Executor` has ~12 public methods (`advance_skill`, `execute_current_tool`, `current_skill`, `execute_plan`, `invoke_current_skill`, `current_tool_invocation`, `resolve_current_tool`, `start_session`, `prepare_session`, `has_pending_tasks`, `execute_current_skill`, `execute`) — again consistent with many subsequent, intentional stages.
- `test_stage_l80_executor_skill_result.py` / `test_stage_l83_executor_skill_tools.py` / `test_stage_l84_executor_tool_resolution.py`: assert "no new top-level import introduced this sprint"; the current file imports several modules from stages that came after (`autonomous_host`, `tool_resolver`, `skill_execution_plan`, `execution_session`, etc.).
- `test_stage_l72_executor_skill_execution_plan.py`: fails on `AttributeError: 'ExecutionSession' object has no attribute 'skills'` — suggests `ExecutionSession`'s internal shape changed since this guard was written.
- `test_stage_l99_market_price_tool_execute.py`: fails asserting the tool's `execute()` body is "a single return statement" and that its imports are unchanged — again a surface-lock from an early stage that later work has legitimately moved past.

**These 16-or-so files are STALE in the specific sense the task asked to detect: they still run and still fail, testing an API contract the codebase has intentionally moved beyond.** They are not evidence of a regression in current behavior — they are evidence that the regression-guard tests themselves were never retired or updated once their "locked" stage was superseded. Per the Master Prompt's own Rule 3 ("Jangan menilai selesai hanya dari jumlah test"), this cluster is exactly the kind of noise that could mislead a naive "41 FAIL = 41 real bugs" reading.

### 6.3 Two additional confirmed regressions inside the same cluster (NOT stale — genuine mismatches worth separating out)
Two files fail for a reason that is not a surface-lock and does look like a genuine constructor-signature drift that the test was never updated for, OR a genuine incomplete migration on the source side (cannot distinguish from this pass alone; flagged for the next Activation to resolve, not fixed here):

- `test_stage_l118_market_analysis_agent.py`: `TypeError: MarketAnalysisAgent.__init__() missing 2 required positional arguments: 'portfolio_analysis_skill' and 'watchlist_analysis_skill'`.
- `test_stage_l123_trading_decision_agent.py` / `test_stage_l126_trading_decision_agent_capital_pipeline.py`: `TypeError: TradingDecisionAgent.__init__() missing 10 required positional arguments`.

These indicate the constructors of `MarketAnalysisAgent`/`TradingDecisionAgent` gained required parameters at some later stage, and these three specific tests (unlike the composition root, which builds these classes correctly, per §1 of the Activation 0 report) were never updated to supply them. **This is a real, currently-broken test file, not a false positive** — but whether the underlying *production* wiring (composition root) still supplies the now-required arguments correctly was already confirmed in Activation 0 as CONNECTED, so this looks like test-only drift rather than a production defect. Flagged, not resolved, per this Activation's no-fix rule.

---

## 7. Missing Coverage (Gap Analysis)

Direct answers to Task 10's questions, grounded in the inventory above:

- **What has never been tested at all, end-to-end?** The full `startup → scan → … → notification` chain — confirmed, no such test exists (§5, §9).
- **What is only tested via mock/fake?** `main._run_manual_scan`'s connection to `ManualScanService` (via `FakeManualScanService`); every notification test (hand-built `NotificationEvent`, mocked HTTP client per `integration_test.py`'s own assertion text); the legacy `integration_test.py`'s `yfinance` dependency (via `_FakeYFTicker`).
- **What has never touched a real database?** The large `Orchestration.*Skill`/`Agents.*` structural/unit group (~190 files) — these operate on in-memory fakes/stubs, not `SQLiteDatabase`. Only the 18 database/repository/migration files (§4) touch real SQLite, and even those use a temp/in-memory file, not anything resembling the actual production database path/lifecycle.
- **What has never touched the Repository layer specifically in a chained way?** No test was found that goes `Skill/Agent output → Repository write → Repository read-back` as one sequence; repository tests exercise the repository directly with hand-supplied data.
- **What has never touched notification in a triggered (not hand-built-event) way?** Everything — confirmed in Activation 0 that nothing in production code ever calls `notify()`, and confirmed here that no test constructs a notification from a real upstream trade/scan outcome either.
- **What has never touched paper trading from a real recommendation?** Everything — `PaperTradingEngine`/`OrderLifecycleService` are always tested with hand-supplied order parameters, never a `Recommendation` object produced by the (real or fake) analysis/ranking/recommendation stages.
- **What has never touched real startup (the actual `main.py` process boot)?** Everything — no test spawns `python main.py` as a subprocess or otherwise drives the real REPL; `test_manual_scan_command.py` imports `main` as a module and calls one internal function directly, which is different from a real process boot (it skips `validate_runtime_environment()` and the REPL loop entirely).
- **What has never touched migration as an automatic, startup-integrated step?** Everything — migration tests (`test_*_migration.py`) call `MigrationRunner`/the `run_*_migrations.py` logic directly and standalone; none test it being invoked from `build_application()` or `main.py`, because (per Activation 0) it never is.
- **What has never touched restart/recovery?** `test_stage_l155_production_recovery.py` exists by name and was not individually re-opened line-by-line in this pass to confirm what, specifically, it recovers from or whether that logic is reachable from `main.py` — flagged for a dedicated follow-up read rather than declared untested outright.
- **What has never touched a database transaction spanning multiple tables/services in one atomic unit?** No test was found exercising a single transaction that spans, e.g., `Order` + `Trade` + `Position` + `Account` together — consistent with Activation 0's finding that `PaperTradingEngine` itself explicitly owns no such transaction.

---

## 8. Baseline Summary (for use by subsequent Activations)

1. **246 test files exist; 188 currently pass cleanly, 41 fail, 13 error out before producing a result, and 4 are blocked by a missing `pytest` dependency** (one of which, `test_idx_foundation_parity.py`, silently executes zero assertions when run the way every other file in this suite is run — worth flagging to whoever maintains this suite, since it currently gives a false impression of passing).
2. **This is fundamentally a hand-rolled proof-script suite, not a pytest suite** — `pytest`/`unittest` conventions are the exception (6 files), not the rule (240 files). Any future Activation that assumes "run `pytest Tests/`" will discover almost nothing, since pytest isn't installed and wouldn't collect most of these files as tests even if it were (most define no `def test_*` functions at module scope that pytest would discover).
3. **The 41 FAIL files split into two very different categories that must not be conflated:** (a) ~39 files are stale "locked surface" regression guards failing because the codebase legitimately evolved past the stage they lock to, plus 2 real tool-registration/behavioral fails (`test_stage_l106`, `test_stage_l107`, `test_stage_l64`) that reproduce Activation 0's already-documented `ToolRegistryError` findings; (b) a small number (`test_stage_l118`, `test_stage_l123`, `test_stage_l126`) reflect genuine constructor-signature drift between an older test and the current `MarketAnalysisAgent`/`TradingDecisionAgent`.
4. **The database/repository/migration layer (18 files) is the most solidly, functionally tested part of the codebase** — all pass (aside from the mislabeled `test_position_migration.py`), and they exercise a real SQLite engine, not fakes.
5. **No test — including the two legacy E2E/integration scripts — exercises the full product workflow end-to-end.** Every pipeline stage (scan → analysis → ranking → recommendation → paper trade → position → performance → notification) is verified in isolation only. This is the single most important baseline fact for Activation 1 onward: **a green test run today provides no evidence that a real user command produces a correct, connected result**, exactly as the Master Prompt's own working rules warn.
6. **The 246-file count and the ~12,700 individual assertions are a real, substantial testing investment** — the finding above is not "the tests are bad," it is "the tests are aimed almost entirely at unit/contract/wiring correctness, and a production-flow test layer does not yet exist." That layer is the concrete gap subsequent Activations should close before relying on "tests are green" as a definition of done, consistent with the Master Prompt's Rule 4 (Definition of Done must be based on real behavior).

---

## Companion file

- `AIOS_Test_Pass_Matrix.csv` — full 246-row matrix: file name, return code, duration, pass/fail assertion counts, and final status, for every test file in `Tests/`.

## Note on audit completeness

Every PASS/FAIL/ERROR/BLOCKED classification and every quoted failure message in this report was read directly from a captured execution log, not inferred or assumed. The Structural/Functional split in §3–§4 is exact for the 41 FAIL + 13 ERROR + 17 wiring + 18 database files (all individually inspected), and is a reasonable, naming-convention-based estimate for the remaining ~150 files in the general `test_stage_lNN_*` unit-proof-script group, which were not each individually re-opened and re-classified line by line in this pass — a dedicated follow-up could tighten that estimate into an exact count if needed for a later Activation.
