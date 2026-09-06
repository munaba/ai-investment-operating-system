
AIOS Repository — End-to-End Architecture Review (Post-L18)

Scope of this review: full static inspection of Core, Orchestration, Agents, Services, Providers, Database, Repository, main.py, and Core/composition_root.py as the wiring source of truth — not the docs' self-description, per your standing rule that implementation wins over documentation.

FACT

1. The live call path vs. the built call path (this is the central fact everything below hangs on)

Tracing main.py → build_application() → app.agent.chat() → StockAgent.chat(), the only path that ever actually runs today is:

StockAgent.chat()
  → self._memory.add()            (Agents.memory.ConversationMemory — chat history)
  → self._instrument_extractor    (ticker parsing)
  → self._run_service_pipeline()  → AnalysisPipeline / RuntimeAnalysisPipeline → 11 Services
  → self._planner.select_provider() (Agents.planner.Planner — LLM provider choice, NOT GoalPlanner)
  → provider.chat()

Separately, fully built and fully tested, sits an entire second stack that nothing calls:

GoalPlanner.build_plan() → ExecutionPlan → GoalPlanner.execute_plan()
  → ServiceSkill.execute() (wraps the same 11 Services, differently)
  → ObservationRecorder.record() → Observation
  → MemoryRecorder.record() → MemoryStore
  → Reflector.reflect() → ReflectionRecord

I confirmed this by direct search, not inference: ObservationRecorder, Orchestration.memory, and Orchestration.reflection are referenced only by themselves and their own test files — zero production references. GoalPlanner is constructed in composition_root.py and placed on ApplicationGraph.goal_planner (so it looks wired), but composition_root.py's own docstrings state directly that "no ... AnalysisPipeline call path reads or calls goal_planner." It's exposed on the graph and touched by nothing.

This isn't a surprise buried in the code — Orchestration/service_skill.py's own module docstring says it outright: "The production StockAgent call path is untouched by this module... nothing in this module is wired into that path." Each of L13, L15, L16, L17, L18 was built as declared, intentional scaffolding for "a future stage to discover and use." That future stage has not arrived across five milestones.

2. Duplicated concept: two registries of "a callable capability + its metadata"
   Agents.tool_registry.Tool / ToolRegistry — used by the live Executor/Sandbox path.
   Orchestration.service_skill.ServiceSkill / SKILL_METADATA_BY_SERVICE — used only by the dormant GoalPlanner path.

Both wrap the same 11 Services as invokable units with declarative metadata. They are not aliases of each other — they're two independent implementations of the same idea, registered separately in composition_root.py, addressed by different name fields (Tool.name vs ServiceSkill.tool_name/service_name). This is a direct symptom of finding #1, not a separate root cause.

3. Two independent orchestration engines for "turn a request into an ordered chain of Service calls"
   Live: Core.analysis_pipeline.AnalysisPipeline — a fixed, hardcoded 11-step chain over BaseService/ServiceContext.
   Dormant: Orchestration.planner.GoalPlanner — a dynamic, metadata-driven forward-chaining planner over ServiceSkill.required_inputs/produced_outputs.

Both solve dependency-ordering and context-threading between the same services. The dynamic one (GoalPlanner) is architecturally the more capable of the two — it's the right shape for a system that will eventually add Forex/Crypto/Futures/Options services with different dependency graphs per asset class — but it is the one nothing runs.

4. Domain modeling quality is inverted between the two stacks
   Live path (Services/Core.analysis_pipeline): stringly-typed. Data flows as ServiceContext.metadata: Dict[str, Any], keyed by string constants in MetadataKeys (e.g. TICKER = "ticker", PRICE = "harga" — Indonesian and English key names mixed in the same class, a minor naming inconsistency). No Instrument, Position, Order, Portfolio, or Trade domain object exists anywhere in the repository.
   Dormant path (Orchestration): proper immutable value objects — Goal, PlanStep, ExecutionPlan, Observation, MemoryRecord, ReflectionRecord — each frozen, each with a single clear owner, each following a locked one-directional dependency rule (Planner → Observation → Memory → Reflection, never the reverse). This is genuinely good DDD-flavored design. It's just disconnected from the system it's modeling.
5. Provider (LLM) abstraction — good, and worth calling out as good

Providers/base_provider.py + capabilities.py + provider_selector.py + requirement.py give a real capability-based selection mechanism (ProviderRequirement → ProviderSelector → concrete BaseProvider), with GeminiProvider/OllamaProvider as interchangeable implementations and a one-line registration point in composition_root._PROVIDER_CLASSES. Adding a third LLM provider is additive, not invasive. This layer would scale fine to "multiple LLM providers" in your roadmap without rework.

6. Repository layer — good, correctly bounded

Repository/persistence (WatchlistRepository, DB-backed) vs Repository/external (NewsRepository, StockDataRepository, external API-backed) is a clean, correctly-drawn boundary — both subclass a common BaseRepository, but the split between "our data" and "someone else's data" is exactly the right seam for a system that will eventually pull Forex/Crypto data from different external providers.

7. Persistence layer covers exactly one domain concept: Watchlist

Database/models.py defines only MigrationRecord plus whatever migrations_watchlist.py creates — watchlist is the only persisted business entity. There is no schema, migration, or model for portfolio, position, order, execution, or trade history. Given the roadmap explicitly includes portfolio management and execution, this is a real, large gap — but it is a roadmap gap, not technical debt: nothing was built badly here, nothing exists yet to be wrong.

8. Naming: Planner exists twice with different meanings

Agents.planner.Planner (per-turn: "which LLM provider / should a tool fire for this message") and Orchestration.planner.GoalPlanner (per-goal: "which services, in what order, to satisfy a Goal") are unrelated concepts sharing a root name in different modules. GoalPlanner's fuller name avoids direct collision, but at the import level (from Agents.planner import Planner next to from Orchestration.planner import GoalPlanner in the same composition_root.py) a reader has to hold two different mental models of "planner" simultaneously. Minor, not load-bearing, but a real readability cost as more stages accumulate.

9. Memory naming — flagged, but already correctly handled

Agents.memory.ConversationMemory (chat history) vs Orchestration.memory.MemoryRecord/MemoryStore (AIOS structured execution knowledge) are two different concepts sharing the word "Memory." Unlike finding #8, this one is not a violation — every docstring in both files explicitly disambiguates it, and I confirmed neither module imports the other. This is good naming discipline under a real constraint (both concepts legitimately deserve the word "memory" in an agent system) — noting it as handled well, not as a problem.

10. Event-sourced kernel (Core/runtime.py) — solid foundation, underused

Core.runtime implements a real Actor/Event/EventStore/Gateway/ReducerShell/Snapshot model — genuine event-sourcing primitives, which is exactly the right foundation for "continuous learning" and "autonomous decision making" (you get replay, auditability, and state reconstruction for free). Today it's used narrowly — as a way to run AnalysisPipeline as one big Tool call (RuntimeAnalysisPipeline) — not as the backbone for agent decisions generally. That's an intentional, staged scope (documented directly in runtime_analysis_pipeline.py), not a flaw.

CHANGE (findings, not implementation — nothing here is a proposal to code)

Organized against your checklist, repository-specific only:

Dependency direction: Correct and consistently enforced within the Orchestration stack (Observation never imports Memory; Memory never imports Reflection; both documented and enforced by import-absence checks in the L17/L18 test suites). The inter-stack dependency direction — Orchestration → live call path — simply doesn't exist yet in either direction. Not a violation; an absence.
Layering: Individually, each layer (Providers, Services, Repository, Database) is well-formed. The break is at the orchestration tier specifically, where two competing layers occupy the same conceptual slot (finding #3).
Domain boundaries: IDX-stock-analysis is the only fully realized domain. IDXStockAgent/StockAgent/MarketAnalysisAgent form a reasonable inheritance ladder for adding asset classes (a future ForexAgent/CryptoAgent fits the existing shape), but every Service, metadata key, and pipeline step is presently stock-specific in content even where the class names are generic.
Service boundaries: Clean — each Service in Services/ has one responsibility, BaseService is a genuine abstraction, ServiceRegistry is a real registry not a god object.
Coupling / cohesion: High cohesion within each stack; the cross-stack coupling that should exist (dormant stack feeding the live one) is exactly what's missing, which is a curious inversion — usually the risk is too much coupling, here the risk is a wall between two things that architecturally belong together.
SOLID: Open/Closed is respected well in the Provider layer (_PROVIDER_CLASSES dict) and Service layer (add a Service, register it, done). No Liskov or Interface-Segregation violations found in the class hierarchies inspected.
Hidden technical debt vs. roadmap: The Tool/ServiceSkill duplication (finding #2) is technical debt — it's an accidental byproduct of the split, not a deliberate design decision, and it will cost real effort to reconcile later. Missing Portfolio/Order/Position domain objects are roadmap, not debt — labeling that as debt would be inventing a problem where none exists yet, per your instruction.
Missing abstractions for the stated future: No Instrument/Symbol value object distinguishing asset class (equity ticker vs. forex pair vs. crypto pair vs. options contract) exists anywhere — today ticker is a bare string everywhere it appears. This becomes a real abstraction gap the moment a second asset class is added, since asset-class-specific fields (contract expiry for options/futures, base/quote currency for forex) have nowhere principled to live yet. This is roadmap-adjacent debt: fine today with one asset class, expensive to retrofit once multiple exist and code has already assumed "ticker is a stock symbol" in a dozen places.
Where future AI learning becomes difficult: Nowhere structurally — Memory and Reflection are the right shapes for it. The difficulty is entirely upstream: there is currently no automatic producer of Observation objects from the live agent's actual actions, because the live agent doesn't go through GoalPlanner/ServiceSkill at all. Continuous learning needs a continuous stream of real Observations; today that stream is empty in production.
Where autonomous trading becomes difficult: Same root cause plus finding #7 — no execution/order/portfolio domain model exists to hang risk checks, position sizing, or trade approval against. RiskManagementService computes numbers but there is no Order for it to gate.
WHY

Every finding above traces back to one pattern: each L-numbered stage since L13 has been built as a parallel, additive, non-invasive branch, exactly as instructed at the time ("no existing production call path was touched") — which was the right call for each individual stage in isolation, and each stage's own regression suite proves it did what it claimed. But six stages of "additive only, don't touch production" in a row, with no stage designated to do the joining, has produced two complete, internally excellent, mutually unaware systems. Neither stack is bad engineering. The gap between them is the actual architectural cost.

THE ONE BIGGEST ARCHITECTURAL WEAKNESS

The AIOS learning loop (Plan → Execute → Observe → Memorize → Reflect) is fully built and fully tested, but has no producer. It is not reachable from the one place in the entire repository where a real user request enters the system. Every future capability on your roadmap — continuous learning, reflection-informed planning, multi-agent coordination, autonomous decision-making — depends on Observation objects that, today, nothing in production ever creates. Adding Forex, Crypto, Futures, or Options as new asset classes on top of the current live path (AnalysisPipeline, hardcoded 11-step, stock-shaped) would extend the wrong stack — the one with no Instrument abstraction and no execution-history trail — while the stack actually designed for it sits idle.

Left unaddressed, this gets more expensive every stage, not less: each new milestone has two plausible places to attach (the live stack or the dormant one), and the dormant stack's own internal vocabulary (Goal/PlanStep/ExecutionPlan) will keep drifting further from the live stack's vocabulary (ServiceContext/pipeline step) the longer the join is deferred. The fix, whenever you choose to do it, isn't a redesign of either stack — both are sound — it's a single, deliberate integration milestone whose entire job is making StockAgent (or its successor) actually call GoalPlanner instead of AnalysisPipeline directly, so that every real request finally produces a real Observation.

REGRESSION RISK

None from this review — read-only, no files touched, nothing proposed to implement. The risk being described above is a cost-of-delay risk, not a regression risk: the longer the two stacks stay unconnected, the more expensive the eventual join becomes, because each new milestone added to either side widens the gap. That's a forward-looking cost to flag, not a current defect to fix.

STOP

Architecture review complete. No code proposed, no implementation started, L19 not begun. This is an observational document for your planning — waiting for your direction on what, if anything, comes next.
