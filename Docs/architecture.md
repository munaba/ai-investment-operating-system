# Current Repository Architecture Specification

Scope: `Agents/*`, `Core/*`, `Providers/*`, `Database/*`, `Services/*`, plus
`analysis_pipeline.py`, `tool_context_builder.py`, and the three test files
(`E2e_test.py`, `integration_test.py`, `test_stock_agent_smoke.py`), as
uploaded. Every statement below is traced directly from that source. Where
a fact could not be verified from the code (e.g. whether `yfinance`/`plotly`
network calls behave a certain way at runtime), it is described as an
external dependency rather than asserted.

---

## 1. Complete Pipeline Execution Order

There are two independent pipelines in this repository. They are not the
same thing and do not share configuration.

### 1.1 Generic engine (`BaseAgent.run`)

```
Message → ConversationMemory.add → Planner.plan → [Executor.execute] → Planner.select_provider → BaseProvider.generate → ConversationMemory.add → reply text
```

- `Planner.plan` calls `should_use_tool` (a keyword-substring heuristic
  against `ToolRegistry.list()`) and `select_provider`.
- `Executor.execute` only runs if `Plan.use_tool` is `True`.
- This path is implemented in `base_agent.py` and is not the path used by
  `StockAgent` (see 1.2).

### 1.2 `StockAgent.run` — fixed 11-step `AnalysisPipeline`

`StockAgent.run` does **not** call `Planner.plan`, `Planner.should_use_tool`,
or `Executor.execute`. It overrides the generic engine's control flow
entirely:

```
Message
 → ConversationMemory.add(message)
 → _extract_ticker(message.content)        # regex + stopword filter
 → _build_context(ticker)                  # ServiceContext(metadata={"ticker": ticker})
 → AnalysisPipeline.run(context)            # fixed 11-step chain, see below
 → ToolContextBuilder.build(results)        # dict[str, ServiceResult] → one TOOL message string
 → Planner.select_provider(provider_name)
 → provider.generate(history + [tool_message])
 → ConversationMemory.add(reply)
 → reply text
```

`Planner` is used here only for `select_provider` (provider lookup by
name). `Executor` and `ToolRegistry` are held by `StockAgent` (inherited
from `BaseAgent`) but never invoked in `StockAgent.run`.

The 11-step service chain, in the fixed order set by
`AnalysisPipeline.__init__`'s `self._services` list (this order is not
configurable except by constructing a different `AnalysisPipeline`):

| #  | Service                       | `.name`                       |
| -- | ----------------------------- | ------------------------------- |
| 1  | `StockService`              | `stock_service`               |
| 2  | `TechnicalIndicatorService` | `technical_indicator_service` |
| 3  | `MovingAverageService`      | `moving_average_service`      |
| 4  | `TechnicalScoreService`     | `technical_score_service`     |
| 5  | `FundamentalService`        | `fundamental_service`         |
| 6  | `PatternService`            | `pattern_service`             |
| 7  | `ChartService`              | `chart_service`               |
| 8  | `NewsService`               | `news_service`                |
| 9  | `BacktestService`           | `backtest_service`            |
| 10 | `RiskManagementService`     | `risk_management_service`     |
| 11 | `ScoringService`            | `scoring_service`             |

Each step runs via `AnalysisPipeline._execute_step`, which:

1. Calls `service.execute(context)`.
2. If `result.success`, produces a **new** `ServiceContext` via
   `dataclasses.replace(context, metadata={**context.metadata, service.name: result.data})`.
3. If not successful, the original `context` is returned unchanged.
4. Every step runs regardless of prior failures (skip-on-fail — see §5).

`AnalysisPipeline.run` returns `Dict[str, ServiceResult]` — one entry per
configured service, keyed by `service.name` — built by
`_build_result_dict`. This is a **separate object** from the final
`ServiceContext`; it is what `ToolContextBuilder.build()` consumes.

### 1.3 Per-service purpose / inputs / outputs / consumers

Inputs listed are the literal `context.get_metadata(key, default)` calls
inside each service's `execute()`. `ServiceContext.get_metadata` is a flat
`self.metadata.get(key, default)` — there is no nested-path lookup
anywhere in the codebase. Whether an input is actually *reachable* at
runtime (i.e. whether that top-level key is ever populated by the time
this step runs) is addressed in §2 and §7–§9, not here — this table
states only what each service *declares* it reads.

**1. `StockService`**

- Purpose: fetch OHLCV history + company info for a ticker via `yfinance`.
- Required inputs: none (all optional with defaults).
- Optional inputs: `ticker` (default `"BBCA.JK"`), `period` (default
  `"6mo"`), `interval` (default `"1d"`).
- Outputs (`result.data`): `ticker`, `history`, `info`, `harga`, `per`,
  `roe`, `dividend_yield`.
- Downstream consumers: `ToolContextBuilder` (`[Stock]` section, via the
  `results` dict). See §2 for whether other services can read its output.

**2. `TechnicalIndicatorService`**

- Purpose: compute RSI, MACD, MACD signal, Bollinger upper/lower, ATR, OBV
  from OHLCV history.
- Required inputs: `history`.
- Optional inputs: none.
- Outputs: `rsi`, `macd`, `macd_signal`, `bollinger_upper`,
  `bollinger_lower`, `atr`, `obv`.
- Downstream consumers: `ToolContextBuilder` (`[Technical Indicator]`
  section).

**3. `MovingAverageService`**

- Purpose: compute MA20/MA50/MA200 from OHLCV history.
- Required inputs: `history`.
- Optional inputs: none.
- Outputs: `ma20`, `ma50`, `ma200`.
- Downstream consumers: `ToolContextBuilder` (`[Moving Average]` section).

**4. `TechnicalScoreService`**

- Purpose: combine price/MA/RSI/Bollinger values into one technical score
  (0–100).
- Required inputs: `harga`.
- Optional inputs: `rsi`, `ma20`, `ma50`, `ma200`, `bollinger_upper`,
  `bollinger_lower` (each individually `None`-tolerant).
- Outputs: `technical_score`.
- Downstream consumers: `ToolContextBuilder` (`[Technical Score]`
  section).

**5. `FundamentalService`**

- Purpose: compute a fundamental score (0–100) from PER/ROE/dividend
  yield vs. sector averages.
- Required inputs: at least one of `per`, `roe`, `dividend_yield`
  (fails if all three are absent).
- Optional inputs: `per_rata_sektor`, `roe_rata_sektor`.
- Outputs: `fundamental_score`.
- Downstream consumers: `ToolContextBuilder` (`[Fundamental]` section).

**6. `PatternService`**

- Purpose: compute a pattern-history score (0–100) from win rate / average
  return of historically similar patterns.
- Required inputs: at least one of `win_rate`, `rata_rata_return`.
- Optional inputs: none (either individually may be absent — score
  defaults to `50` in that case, but at least one must be present or the
  step fails outright).
- Outputs: `pattern_score`.
- Downstream consumers: `ToolContextBuilder` (`[Pattern]` section).

**7. `ChartService`**

- Purpose: build a multi-panel Plotly technical chart (candlestick +
  optional Volume/EMA/SMA/RSI/MACD/Bollinger panels).
- Required inputs: `history`.
- Optional inputs: `ticker` (default `""`), `indicators` (default = all
  of `SUPPORTED_INDICATORS`), `image_path`.
- Outputs: `figure`, `image_path`, `metadata` (a nested dict:
  `ticker`, `rows`, `indicators_included`, `indicators_skipped`).
- Downstream consumers: `ToolContextBuilder` (`[Chart]` section).

**8. `NewsService`**

- Purpose: fetch recent news articles for a ticker via `yfinance`.
- Required inputs: none (all optional with defaults).
- Optional inputs: `ticker` (default `"BBCA.JK"`), `max_news` (default
  `10`).
- Outputs: `ticker`, `news`, `total_news`.
- Downstream consumers: `ToolContextBuilder` (`[News]` section).

**9. `BacktestService`**

- Purpose: run a fast/slow moving-average crossover backtest.
- Required inputs: `history`.
- Optional inputs: `strategy` (default `"ema_cross"`, must be
  `"ema_cross"`/`"sma_cross"`), `initial_capital` (default
  `100_000_000.0`), `fast_period` (default `20`), `slow_period` (default
  `50`).
- Outputs: `strategy`, `total_return`, `final_capital`, `total_trade`,
  `win_rate`, `trade_history`.
- Downstream consumers: `ToolContextBuilder` (`[Backtest]` section).

**10. `RiskManagementService`**

- Purpose: compute stop loss, take profit, risk amount, position size,
  risk/reward ratio for a long position.
- Required inputs: `entry_price`, `stop_loss_percent`,
  `take_profit_percent`, `risk_per_trade_percent`, `account_balance` (all
  five required; any single missing value fails the step).
- Optional inputs: none.
- Outputs: `stop_loss_price`, `take_profit_price`, `risk_amount`,
  `position_size`, `risk_reward_ratio`.
- Downstream consumers: `ToolContextBuilder` (`[Risk Management]`
  section).

**11. `ScoringService`**

- Purpose: combine technical (45%), fundamental (35%), pattern (20%)
  scores into a weighted composite score + label (`BAGUS`/`NETRAL`/
  `LEMAH`).
- Required inputs: `technical_score`, `fundamental_score`,
  `pattern_score` (all three required).
- Optional inputs: none.
- Outputs: `technical_score`, `fundamental_score`, `pattern_score`
  (echoed), `overall_score`, `label`.
- Downstream consumers: `ToolContextBuilder` (`[Scoring]` section).

---

## 2. Complete Metadata Contract

Two distinct namespaces exist and must not be conflated:

- **`ServiceContext.metadata`** — the per-request dict passed into every
  `execute()` call. Read only via the flat accessor
  `ServiceContext.get_metadata(key, default)`.
- **`ServiceResult.data`** — each service's own output payload. Consumed
  in two, and only two, ways in the entire repository:
  (a) `AnalysisPipeline._execute_step` writes the *whole dict* into
  `ServiceContext.metadata` under the key `service.name` (not flattened —
  see §5), and (b) `ToolContextBuilder.build()` reads `result.data`
  directly from the `results` dict returned by `AnalysisPipeline.run`
  (independent of `ServiceContext.metadata`).

### 2.1 `ServiceContext.metadata` — top-level keys

The **only** code in the repository that ever writes to
`ServiceContext.metadata` is:

- `StockAgent._build_context`, which seeds exactly one key: `ticker`.
- `AnalysisPipeline._execute_step`, which — on each successful step —
  adds exactly one key: the service's own `.name`, whose value is that
  service's entire `result.data` dict.

No other writer exists. In particular, no code ever copies keys out of a
producer's `result.data` dict into the top level of
`ServiceContext.metadata`.

| Top-level key                   | Producer                                          | Required/Optional per consumer                  | Consumer(s) (by literal`get_metadata` call)       | Overwritten?                                                                                                                              | Ever read? | Read before written?                        |
| ------------------------------- | ------------------------------------------------- | ----------------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------- |
| `ticker`                      | `StockAgent._build_context` (seed)              | Optional everywhere it's read                   | `StockService`, `ChartService`, `NewsService` | No — preserved unchanged through every`{**context.metadata, ...}` merge in `_execute_step` (dict-spread never removes existing keys) | Yes        | No — always written before pipeline starts |
| `stock_service`               | `AnalysisPipeline._execute_step` (after step 1) | n/a — no service reads this literal nested key | none                                                | No                                                                                                                                        | No         | n/a                                         |
| `technical_indicator_service` | `_execute_step` (after step 2)                  | n/a                                             | none                                                | No                                                                                                                                        | No         | n/a                                         |
| `moving_average_service`      | `_execute_step` (after step 3)                  | n/a                                             | none                                                | No                                                                                                                                        | No         | n/a                                         |
| `technical_score_service`     | `_execute_step` (after step 4)                  | n/a                                             | none                                                | No                                                                                                                                        | No         | n/a                                         |
| `fundamental_service`         | `_execute_step` (after step 5)                  | n/a                                             | none                                                | No                                                                                                                                        | No         | n/a                                         |
| `pattern_service`             | `_execute_step` (after step 6)                  | n/a                                             | none                                                | No                                                                                                                                        | No         | n/a                                         |
| `chart_service`               | `_execute_step` (after step 7)                  | n/a                                             | none                                                | No                                                                                                                                        | No         | n/a                                         |
| `news_service`                | `_execute_step` (after step 8)                  | n/a                                             | none                                                | No                                                                                                                                        | No         | n/a                                         |
| `backtest_service`            | `_execute_step` (after step 9)                  | n/a                                             | none                                                | No                                                                                                                                        | No         | n/a                                         |
| `risk_management_service`     | `_execute_step` (after step 10)                 | n/a                                             | none                                                | No                                                                                                                                        | No         | n/a                                         |
| `scoring_service`             | `_execute_step` (after step 11)                 | n/a                                             | none                                                | No                                                                                                                                        | No         | n/a                                         |

All 11 service-name keys are written but never read by any
`get_metadata` call anywhere in the codebase — every service reads only
flat, service-agnostic key names (`history`, `harga`, `rsi`, etc.), never
`context.get_metadata("stock_service")` or similar.

### 2.2 Flat key names declared as inputs by some service, but never present at the top level

Every key below is *read* by at least one service via
`context.get_metadata(<key>, ...)`, but is **never written** to the top
level of `ServiceContext.metadata` by anything — because the only writer
(`_execute_step`) nests producer output under the producer's service
name, and no code un-nests it (§2.1). These reads therefore always
receive the caller's supplied default (`None` unless otherwise noted).

| Key                                                                                                              | Declared reader(s)                                                                             | Required by reader?   | Textually matching producer (data-dict key), if any                                                                   |
| ---------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `history`                                                                                                      | `TechnicalIndicatorService`, `MovingAverageService`, `ChartService`, `BacktestService` | Required in all four  | `StockService.data["history"]`                                                                                      |
| `harga`                                                                                                        | `TechnicalScoreService`                                                                      | Required              | `StockService.data["harga"]`                                                                                        |
| `per`                                                                                                          | `FundamentalService`                                                                         | One-of-three required | `StockService.data["per"]`                                                                                          |
| `roe`                                                                                                          | `FundamentalService`                                                                         | One-of-three required | `StockService.data["roe"]`                                                                                          |
| `dividend_yield`                                                                                               | `FundamentalService`                                                                         | One-of-three required | `StockService.data["dividend_yield"]`                                                                               |
| `rsi`                                                                                                          | `TechnicalScoreService`                                                                      | Optional              | `TechnicalIndicatorService.data["rsi"]`                                                                             |
| `ma20` / `ma50` / `ma200`                                                                                  | `TechnicalScoreService`                                                                      | Optional              | `MovingAverageService.data["ma20"/"ma50"/"ma200"]`                                                                  |
| `bollinger_upper` / `bollinger_lower`                                                                        | `TechnicalScoreService`                                                                      | Optional              | `TechnicalIndicatorService.data["bollinger_upper"/"bollinger_lower"]`                                               |
| `technical_score`                                                                                              | `ScoringService`                                                                             | Required              | `TechnicalScoreService.data["technical_score"]`                                                                     |
| `fundamental_score`                                                                                            | `ScoringService`                                                                             | Required              | `FundamentalService.data["fundamental_score"]`                                                                      |
| `pattern_score`                                                                                                | `ScoringService`                                                                             | Required              | `PatternService.data["pattern_score"]`                                                                              |
| `win_rate`                                                                                                     | `PatternService`                                                                             | One-of-two required   | `BacktestService.data["win_rate"]` (see §9 — also unreachable by execution order even ignoring the nesting issue) |
| `rata_rata_return`                                                                                             | `PatternService`                                                                             | One-of-two required   | none anywhere in the repo                                                                                             |
| `per_rata_sektor` / `roe_rata_sektor`                                                                        | `FundamentalService`                                                                         | Optional              | none anywhere in the repo                                                                                             |
| `entry_price`, `stop_loss_percent`, `take_profit_percent`, `risk_per_trade_percent`, `account_balance` | `RiskManagementService`                                                                      | All five required     | none anywhere in the repo                                                                                             |

### 2.3 `ServiceResult` field usage (all services)

Every `BaseService.execute()` returns a `ServiceResult` with five fields
besides `success`: `message`, `data`, `metadata`, `execution_time_ms`,
`error`. Grepping every call site that reads a `ServiceResult` instance
(`AnalysisPipeline`, `ToolContextBuilder`, `StockAgent`) shows:

| Field                 | Populated by                    | Read by                                                                                                       |
| --------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `success`           | every service                   | `AnalysisPipeline._execute_step` (enrichment gate), `ToolContextBuilder._build_section` (FAILED vs. body) |
| `data`              | every service                   | `AnalysisPipeline._execute_step` (enrichment source), `ToolContextBuilder._build_section` (section body)  |
| `message`           | every service                   | nothing                                                                                                       |
| `metadata`          | every service                   | nothing                                                                                                       |
| `execution_time_ms` | every service                   | nothing                                                                                                       |
| `error`             | only`ServiceResult.fail(...)` | nothing                                                                                                       |

---

## 3. Service Dependency Graph

### 3.1 As wired into the analysis pipeline (data-flow edges that actually resolve)

```
StockAgent
 └─ AnalysisPipeline
     ├─ StockService            (reads: ticker [seed] — resolves)
     ├─ TechnicalIndicatorService (reads: history — never resolves)
     ├─ MovingAverageService     (reads: history — never resolves)
     ├─ TechnicalScoreService    (reads: harga — never resolves)
     ├─ FundamentalService       (reads: per/roe/dividend_yield — never resolves)
     ├─ PatternService           (reads: win_rate/rata_rata_return — never resolves)
     ├─ ChartService             (reads: history — never resolves)
     ├─ NewsService              (reads: ticker [seed, optional] — resolves)
     ├─ BacktestService          (reads: history — never resolves)
     ├─ RiskManagementService    (reads: entry_price etc. — never resolves)
     └─ ScoringService           (reads: technical_score/fundamental_score/pattern_score — never resolves)
 └─ ToolContextBuilder (pure formatter; depends only on the `results` dict, not on ServiceContext)
```

"Never resolves" means: given the only context-construction call site in
the repository (`StockAgent._build_context`, seeding `{"ticker": ...}`
only) and the only metadata-writer (`_execute_step`, nesting under
service name), that service's required-input check will find `None` and
return a failed `ServiceResult` every time this pipeline is run through
`StockAgent`. This follows deterministically from tracing the two
mechanisms together (§2); it does not depend on live network/API
behavior. `StockService` and `NewsService` are the two steps whose inputs
are satisfiable without any upstream service succeeding.

### 3.2 Structural (import-time) dependencies

```
BaseService (abstract)
 ├─ StockService
 ├─ TechnicalIndicatorService
 ├─ MovingAverageService
 ├─ TechnicalScoreService
 ├─ FundamentalService
 ├─ PatternService
 ├─ ChartService
 ├─ NewsService
 ├─ BacktestService
 ├─ RiskManagementService
 ├─ ScoringService
 └─ NotificationService

AnalysisPipeline → BaseService, ServiceContext, ServiceResult (positional DI of the 11 named services above; NotificationService is not one of the 11 and is never passed to AnalysisPipeline)

StockAgent → BaseAgent, AnalysisPipeline, ToolContextBuilder, ServiceContext, ServiceResult, Planner, ConversationMemory, Executor
BaseAgent  → Planner, ConversationMemory, Executor, BaseProvider (via Providers package), AgentState
Planner    → ProviderManager, ToolRegistry
Executor   → ToolRegistry
ToolContextBuilder → ServiceResult only (pure formatter; no other collaborators)
```

### 3.3 Components present in the repository but not reachable from `StockAgent`

Traced by grepping every call site outside each component's own module:

- **`ServiceRegistry`** (`service_registry.py`): never `.register()`ed or
  `.get()`-ed anywhere outside its own file and the `Services` package
  `__init__.py` re-export. `AnalysisPipeline` receives its 11 services by
  direct constructor injection, bypassing `ServiceRegistry` entirely.
- **`ToolRegistry`** / **`Executor`**: used by the generic `BaseAgent.run`
  engine and by `Planner`, but `StockAgent.run` never calls
  `self._executor.execute()` or `self._planner.plan()` /
  `self._planner.should_use_tool()` — only `self._planner.select_provider()`.
- **`NotificationService`**: implements `BaseService`, but is never passed
  to `AnalysisPipeline` and never registered anywhere in production code
  (only instantiated directly inside `integration_test.py`).
- **`ChromaVectorStore` / `VectorStore`** (`vector_store.py`): no caller
  anywhere outside `vector_store.py` itself.
- **`DatabaseManager` / `MigrationManager`** (`database.py`,
  `migrations.py`): no caller anywhere outside their own modules.
  `ConversationMemory`'s own docstring states it is deliberately not
  backed by the database or vector store.
- No file in the uploaded set constructs a production `AnalysisPipeline`
  or a production `StockAgent`; the only two call sites that build a full
  `AnalysisPipeline(...)` are inside `test_stock_agent_smoke.py`.

---

## 4. Metadata Dependency Graph

Nodes are top-level `ServiceContext.metadata` keys; edges are
producer → consumer relationships that actually resolve at runtime,
traced from §2.1–§2.2:

```
[seed: "ticker"] ──▶ StockService.execute (reads ticker)
[seed: "ticker"] ──▶ ChartService.execute (reads ticker, optional)
[seed: "ticker"] ──▶ NewsService.execute (reads ticker, optional)
```

That is the entire resolvable metadata dependency graph. Every other
declared read (`history`, `harga`, `per`, `roe`, `dividend_yield`, `rsi`,
`ma20`, `ma50`, `ma200`, `bollinger_upper`, `bollinger_lower`,
`technical_score`, `fundamental_score`, `pattern_score`, `win_rate`,
`rata_rata_return`, `per_rata_sektor`, `roe_rata_sektor`, `entry_price`,
`stop_loss_percent`, `take_profit_percent`, `risk_per_trade_percent`,
`account_balance`) is a dangling edge: a consumer node with no
resolvable producer edge feeding it, per §2.2.

Separately, the **result-collection graph** (independent of
`ServiceContext.metadata`) is a flat fan-in, not a chain:

```
StockService ──┐
TechnicalIndicatorService ──┤
MovingAverageService ──┤
TechnicalScoreService ──┤
FundamentalService ──┤
PatternService ──┼──▶ AnalysisPipeline.run() returns Dict[str, ServiceResult] ──▶ ToolContextBuilder.build()
ChartService ──┤
NewsService ──┤
BacktestService ──┤
RiskManagementService ──┤
ScoringService ──┘
```

Every one of the 11 services feeds this graph regardless of
`success`/`failure` — `ToolContextBuilder` renders a `[Label]` section
for every canonical key present in `results` and prints the literal
string `FAILED` as that section's body when `result.success` is `False`.

---

## 5. Invariants Enforced by the Implementation

- **Execution order**: fixed, defined solely by the literal order of
  `self._services` in `AnalysisPipeline.__init__`. Not data-driven, not
  configurable via `ServiceContext`.
- **Skip-on-fail**: a failed step never stops the pipeline. The next
  service still runs, and it runs against the `ServiceContext` as it
  stood *before* the failed step (i.e. a failed step's output is never
  merged in) — enforced by `_execute_step`'s `if result.success:` guard.
- **Metadata propagation is nesting, not flattening**: `_execute_step`
  merges `{service.name: result.data}` into `context.metadata`. It never
  spreads `result.data`'s own keys into the top level. This is the single
  mechanism responsible for the "never resolves" rows in §3.1 — stated
  here as a fact about the code, not a defect judgment.
- **`ServiceContext` copy-on-write, not type-enforced**: `ServiceContext`
  is declared as a plain `@dataclass` (not `frozen=True`, unlike
  `MemoryEntry` in `memory.py`, which is `frozen=True`). Nothing in the
  language prevents in-place mutation of `context.metadata`. The only
  actual writer, `_execute_step`, always calls `dataclasses.replace(...)`
  to produce a new instance rather than mutating fields in place — this
  is a code-level discipline, not a compiler/runtime guarantee.
- **`ServiceResult.data` vs. `ServiceResult.metadata`**: `.data` is the
  sole payload ever read by any consumer (`AnalysisPipeline`,
  `ToolContextBuilder`). `.metadata` is populated by every service
  (typically an echo of the raw input values used) but is never read
  anywhere in the repository (§2.3).
  `.message`, `.execution_time_ms`, and `.error` are likewise populated
  by every service and never read anywhere.
- **Service isolation**: no `BaseService` implementation imports or calls
  another `BaseService` implementation, an `Agent`, a `Provider`, the
  database, or performs an HTTP request of its own — the sole exception
  by design is `NotificationService`, which does perform HTTP requests
  (Discord/Telegram), consistent with its `category` of `"notification"`
  rather than `"market_data"`/`"finance"`.
- **Graceful failure (business-level)**: every `execute()` implementation
  reviewed catches its own internal exceptions and returns
  `ServiceResult.fail(...)`; none of the 11 pipeline services lets a
  business-level exception propagate out of `execute()`. `Executor`,
  separately, converts *tool* handler exceptions into
  `ToolExecutionError` — a different mechanism, for the unrelated
  `ToolRegistry`/`Executor` path (§3.3).
- **Fixed rendering order independent of execution order**:
  `ToolContextBuilder._SECTION_ORDER` lists sections as `Stock`,
  `Technical Indicator`, `Moving Average`, `Technical Score`,
  `Fundamental`, `Pattern`, **`News`**, **`Chart`**, `Backtest`,
  `Risk Management`, `Scoring`. `AnalysisPipeline`'s execution order has
  **`Chart` before `News`** (step 7, then step 8). The two orderings
  disagree specifically on the Chart/News pair; `ToolContextBuilder`'s
  section order does not mirror the pipeline's execution order.
- **Singletons**: `ToolRegistry`, `ServiceRegistry`, `ProviderManager`,
  `Config`, `DatabaseManager`, `LoggerFactory` are all thread-safe
  double-checked-locking singletons (`__new__` + `_instance_lock`). Each
  exposes a `reset()` classmethod explicitly documented as test-only.
- **Provider role mapping**: `GeminiProvider` maps `MessageRole.TOOL` to
  the Gemini SDK role `"user"` (`_ROLE_MAP`), and folds every
  `MessageRole.SYSTEM` message's content into a single
  `system_instruction` string rather than sending it as a turn.
- **Ticker extraction**: `StockAgent._extract_ticker` requires exactly one
  distinct 4-letter uppercase ticker candidate (after removing stopwords
  `BELI`, `JUAL`, `SAYA`, `YANG`, `ATAU`) in the user's message; zero or
  more-than-one distinct candidates raises `StockAgentError` before the
  pipeline ever runs.

---

## 6. Externally Required Inputs Never Produced Inside the Repository

- `GEMINI_API_KEY`, `GEMINI_MODEL` — environment variables read by
  `GeminiProvider` via `Core.config`.
- Live `yfinance` data (network + third-party service) — `StockService`,
  `NewsService`.
- `plotly` (and optionally `kaleido` for image export) — `ChartService`.
- `pandas`, `numpy` — imported at module level by
  `MovingAverageService`, `TechnicalIndicatorService`, `ChartService`,
  `TechnicalScoreService`; lazily imported by `BacktestService`.
- `entry_price`, `stop_loss_percent`, `take_profit_percent`,
  `risk_per_trade_percent`, `account_balance` — required by
  `RiskManagementService`; produced by no service in the repository and
  never seeded by `StockAgent`.
- `win_rate` (as a *reachable* top-level key), `rata_rata_return` —
  required (one-of-two) by `PatternService`; `rata_rata_return` is
  produced by no service anywhere; `win_rate` is produced by
  `BacktestService` but is unreachable both by the nesting mechanism
  (§5) and by execution order (§9).
- `per_rata_sektor`, `roe_rata_sektor` — optional inputs to
  `FundamentalService`; produced by no service anywhere.
- `period`, `interval` (for `StockService`), `max_news` (for
  `NewsService`), `strategy`/`initial_capital`/`fast_period`/
  `slow_period` (for `BacktestService`), `indicators`/`image_path` (for
  `ChartService`) — all optional-with-defaults, and none are ever seeded
  by `StockAgent._build_context`, so every run uses each service's
  hardcoded default.
- Discord/Telegram credentials (`webhook_url`, `telegram_bot_token`,
  `telegram_chat_id`) and the `requests` package — required by
  `NotificationService`, which is unwired from the pipeline entirely
  (§3.3).

---

## 7. Metadata Keys Produced but Never Consumed

(By literal key name, via `get_metadata`, anywhere in the repository —
independent of whether the producing step ever actually succeeds at
runtime.)

- `StockService.data`: `info` (no reader anywhere).
- `TechnicalIndicatorService.data`: `macd`, `macd_signal`, `atr`, `obv`
  (no reader anywhere).
- `ChartService.data`: `figure`, `image_path`, `metadata` (no reader
  anywhere).
- `NewsService.data`: `news`, `total_news` (no reader anywhere; its
  `ticker` field is likewise never read by name).
- `BacktestService.data`: `strategy`, `total_return`, `final_capital`,
  `total_trade`, `trade_history` (no reader anywhere by name; `win_rate`
  is addressed separately in §9 since it textually matches a consumer).
- `RiskManagementService.data`: `stop_loss_price`, `take_profit_price`,
  `risk_amount`, `position_size`, `risk_reward_ratio` (no reader
  anywhere).
- `ScoringService.data`: `overall_score`, `label` (no reader anywhere via
  `get_metadata`; both do reach the final tool message through the
  separate `results`-dict → `ToolContextBuilder` path, §1.3/§4).
- Every `ServiceResult.message`, `.metadata`, `.execution_time_ms`, and
  `.error` value produced by all 11 services (§2.3).

Additionally — and structurally, regardless of the above — every key
inside every service's `result.data` dict is "produced but never
consumed via metadata" in the sense of §5's nesting invariant, since no
code ever un-nests a `context.metadata[service.name]` dict back to the
top level. §2.2 lists the subset of those keys whose names textually
match a declared consumer elsewhere; this section lists the keys with no
name-match at all.

---

## 8. Metadata Keys Consumed but Never Produced

By literal key name, checked against every `result.data` dict across all
11 services and against `StockAgent._build_context`'s seed:

- `rata_rata_return` (`PatternService`) — no producer anywhere.
- `per_rata_sektor`, `roe_rata_sektor` (`FundamentalService`) — no
  producer anywhere.
- `entry_price`, `stop_loss_percent`, `take_profit_percent`,
  `risk_per_trade_percent`, `account_balance` (`RiskManagementService`)
  — no producer anywhere.

Every other declared read in §2.2 (`history`, `harga`, `per`, `roe`,
`dividend_yield`, `rsi`, `ma20`, `ma50`, `ma200`, `bollinger_upper`,
`bollinger_lower`, `technical_score`, `fundamental_score`,
`pattern_score`, `win_rate`) *does* have a textually matching producer
key inside some `result.data` dict — it is unreachable via the top-level
namespace (§5), not unproduced in absolute terms. Those are listed in
§2.2, not repeated here.

---

## 9. Execution-Order Dependencies

- `TechnicalScoreService` (step 4) declares optional inputs (`rsi`,
  `ma20`, `ma50`, `ma200`, `bollinger_upper`, `bollinger_lower`) whose
  textually matching producers are `TechnicalIndicatorService` (step 2)
  and `MovingAverageService` (step 3) — both of which run *before* step 4
  in the fixed order. Order is consistent with the intended data flow;
  only the nesting issue (§5) prevents it from resolving.
- `ScoringService` (step 11) declares required inputs
  (`technical_score`, `fundamental_score`, `pattern_score`) whose
  textually matching producers are `TechnicalScoreService` (step 4),
  `FundamentalService` (step 5), and `PatternService` (step 6) — all run
  before step 11. Order is consistent; nesting again is what breaks
  resolution.
- `PatternService` (step 6) declares `win_rate` as a required (one-of-two)
  input. The only textually matching producer, `BacktestService`, runs at
  **step 9** — three steps *after* `PatternService` has already executed
  and returned. Even if the metadata-nesting mechanism in §5 flattened
  producer output to the top level, `PatternService` would still never
  see `BacktestService`'s `win_rate`, because step 6 has already run and
  returned by the time step 9 produces that value. This is a pipeline-order
  dependency that could not be satisfied by fixing nesting alone.
- `ChartService` (step 7) and `NewsService` (step 8) both declare
  `history`/`ticker` reads that are independent of each other; there is
  no order dependency between them, but `ToolContextBuilder`'s fixed
  section order renders `News` before `Chart` while `AnalysisPipeline`
  executes `Chart` before `News` (§5) — an ordering disagreement between
  the two independent orderings that exist in the codebase (pipeline
  execution order vs. tool-message rendering order).
- No service at any step reads a metadata key whose textually matching
  producer runs *later* in the fixed order, except the
  `PatternService`/`BacktestService`/`win_rate` case above.

---

## 10. Current Repository Architecture Specification

This section is the authoritative summary for implementing a new service
against the codebase as it exists today.

**Where a new pipeline service would be added:**

1. Implement `BaseService` (`name`, `description`, `category`, `execute`,
   `health_check`), following the pattern common to all 11 existing
   implementations: read inputs via `context.get_metadata(key, default)`,
   never raise for business-level failure, return
   `ServiceResult.ok(data=...)` or `ServiceResult.fail(error, ...)`.
2. Add it as a new constructor parameter to `AnalysisPipeline.__init__`
   and append it to `self._services` at the position that matches its
   intended place in the fixed execution order — order is purely
   positional, there is no dependency-resolution mechanism.
3. Add its `.name` → display-label pair to
   `ToolContextBuilder._SECTION_ORDER` if its result should appear in the
   final tool message sent to the LLM provider — this is a second,
   independent ordering from the pipeline's execution order (§5, §9) and
   must be kept in sync manually.

**What a new service can and cannot rely on from `ServiceContext`:**

- It can rely on `context.metadata["ticker"]` being present (seeded once
  by `StockAgent._build_context` and preserved through every subsequent
  merge).
- It **cannot** rely on any prior service's `result.data` keys being
  present at the top level of `context.metadata` — as implemented today,
  a prior service's entire output is nested under
  `context.metadata[<that service's .name>]`, and no code anywhere reads
  that nested path. A new service that wants a prior service's specific
  output field must either read it via that nested path explicitly
  (`context.get_metadata("stock_service", {}).get("history")` — a pattern
  not used by any existing service) or the enrichment step in
  `AnalysisPipeline._execute_step` would need to change.
- It **cannot** rely on `ServiceContext` being frozen — nothing in the
  type system prevents in-place mutation, only the convention followed by
  the sole existing writer (`_execute_step`, via `dataclasses.replace`).

**What is guaranteed regardless of any single service's success/failure:**

- Every configured service runs exactly once per `AnalysisPipeline.run`
  call, in fixed order, regardless of any earlier step's outcome.
- `AnalysisPipeline.run` always returns exactly one `ServiceResult` per
  configured service, keyed by `.name`.
- `ToolContextBuilder.build` always renders one `[Label]` section per
  canonical key present in that results dict, with `success=False`
  results rendered as the literal body `FAILED`, and never raises.
- Only `ServiceResult.success` and `ServiceResult.data` are read by any
  consumer in the repository; `.message`, `.metadata`, `.execution_time_ms`,
  and `.error` are write-only as far as the current codebase is
  concerned.

**Components that exist but are not part of the wired `StockAgent` path**
(§3.3): `ServiceRegistry`, the generic `BaseAgent`/`Planner`/`Executor`/
`ToolRegistry` tool-triggering mechanism, `NotificationService`,
`ChromaVectorStore`/`VectorStore`, and `DatabaseManager`/
`MigrationManager`. A new service that needs any of these must be wired
to them explicitly — none of the existing 11 pipeline services do.
