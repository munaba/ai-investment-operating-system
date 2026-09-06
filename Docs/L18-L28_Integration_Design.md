# L18–L28 Integration Design

**Basis for this report:** direct inspection of `Orchestration/*.py` as extracted
from `logs.zip` (11 files, 1,378 lines total). `Core/composition_root.py`,
`Agents/`, `Services/`, and `Database/` were **not included** in this upload,
so composition-root wiring and StockAgent's current construction could not be
verified directly — those sections below are recommendations against the
documented contract, not confirmed source reads. Everything else (class
signatures, imports, cross-references) is read from the actual files.

## 1. Current Dependency Graph

Verified by grep across every `.py` file for both `import` statements and
bare class-name references — not just docstrings:

```
MemoryRecord (Orchestration/memory.py)
        │  imported by
        ▼
Reflection.reflect(records) -> ReflectionRecord      [L18]
        (duck-typed handoff only — no import below this point)
        ▼
DecisionEngine.decide(score) -> Decision              [L19]
        ▼
DecisionPolicy.apply(decision) -> DecisionPolicyResult [L20]
        ▼
PolicyGuard.evaluate(policy_result) -> PolicyGuardResult [L21]
        ▼
ExecutionIntent.build(policy_guard_result) -> ExecutionIntentResult [L22]
        ▼
ExecutionPlanner.plan(execution_intent) -> ExecutionPlan [L23]
        ▼
ExecutionCoordinator.coordinate(execution_plan) -> ExecutionCoordinatorResult [L24]
        ▼
PortfolioEngine.evaluate(execution_coordinator_result) -> PortfolioEngineResult [L25]
        ▼
PortfolioRisk.assess(portfolio_engine_result) -> PortfolioRiskResult [L26]
        ▼
LearningLoop.learn(portfolio_risk_result) -> LearningLoopResult [L27]

AutonomousAgent (frozen dataclass)                    [L28]
    holds references to all 10 of the above (L18–L27)
    exposes NO run/execute/step method — pure container, by design
```

Separately, verified in `Orchestration/runtime_analysis_pipeline.py`:

```
RuntimeAnalysisPipeline.__init__ imports only:
    Agents.executor.Executor
    Agents.tool_registry.{Tool, ToolRegistry}
    Core.analysis_pipeline.AnalysisPipeline
    Core.tool_context_builder.ToolContextBuilder
    Services.service_context.ServiceContext
```

None of L18–L28 appear in that import list. `RuntimeAnalysisPipeline.run()`
calls the existing 11-step `AnalysisPipeline` only. This confirms the
production request path (`StockAgent → RuntimeAnalysisPipeline → Executor →
AnalysisPipeline`) does not touch the Decision Pipeline / Learning Loop at all
today.

Each stage's chain link is by **duck typing only** — e.g. `decision_policy.py`
never does `from Orchestration.decision_engine import Decision`; it accepts
whatever object is passed to `apply()`. This matches the design principle
in `Architecture_Review_v2.md` ("Dependency inversion preserved") and means
wiring them together is a construction/call-site problem, not a refactor.

## 2. Dead Code (Confirmed)

All 11 files are dead code by import graph — none is imported from
`runtime_analysis_pipeline.py`, `service_pipeline.py`, `analysis_pipeline_adapter.py`,
or any other Orchestration module:

| Component | File | Status |
|---|---|---|
| Reflection (L18) | reflection.py | Unreferenced outside its own tests/docstrings |
| DecisionEngine (L19) | decision_engine.py | Unreferenced |
| DecisionPolicy (L20) | decision_policy.py | Unreferenced |
| PolicyGuard (L21) | policy_guard.py | Unreferenced |
| ExecutionIntent (L22) | execution_intent.py | Unreferenced |
| ExecutionPlanner (L23) | execution_planner.py | Unreferenced |
| ExecutionCoordinator (L24) | execution_coordinator.py | Unreferenced |
| PortfolioEngine (L25) | portfolio_engine.py | Unreferenced |
| PortfolioRisk (L26) | portfolio_risk.py | Unreferenced |
| LearningLoop (L27) | learning_loop.py | Unreferenced |
| AutonomousAgent (L28) | autonomous_agent.py | Unreferenced; also **cannot** be invoked even if referenced — no `run`/`execute` method exists on the class at all (confirmed by reading the full file). It is a passive, frozen, 10-field container. |

I could not check whether any of these are constructed inside
`Core/composition_root.py` and merely left off `ApplicationGraph`, versus
never constructed anywhere — that file wasn't in the upload. Either way, they
are not reachable from the runtime call path.

## 3. What Should Be Invoked First

The chain has one entry point and one shape decision that gates everything
downstream: **Reflection**, because it's the only stage whose input
(`Tuple[MemoryRecord, ...]`) is a real, already-produced type elsewhere in the
codebase (`Orchestration/memory.py`) rather than an output of a sibling L18–L27
stage. Every other stage's input is produced by the stage before it.

The one open question this report can't resolve from the files present: what
currently supplies real `MemoryRecord` batches at runtime (a `MemoryStore`/
`MemoryRecorder` from `Agents/` per your memory notes, not in this upload).
That's the actual first integration dependency — without it, Reflection has
nothing real to reflect over except test fixtures.

## 4. Integration Order

Given the strict linear duck-typed chain, the only safe order is the chain's
own order — each stage's output is the next stage's only input, so there's no
valid alternate sequencing:

1. Confirm/build the real `MemoryRecord` source feeding Reflection (outside
   this file set — likely `Agents/memory.py` / a `MemoryStore`).
2. Reflection (L18) — call `reflect()` on a real batch, produce `ReflectionRecord`.
3. Bridge `ReflectionRecord` → a composite score → `DecisionEngine.decide()` (L19).
   This bridge (score derivation) doesn't exist in any file inspected — it's
   the one piece of real glue code the integration needs, not present as
   dead code anywhere.
4. DecisionPolicy.apply() (L20)
5. PolicyGuard.evaluate() (L21)
6. ExecutionIntent.build() (L22)
7. ExecutionPlanner.plan() (L23)
8. ExecutionCoordinator.coordinate() (L24)
9. PortfolioEngine.evaluate() (L25)
10. PortfolioRisk.assess() (L26)
11. LearningLoop.learn() (L27)
12. AutonomousAgent (L28) constructed last, purely to hold the 10 references
    — since it has no invocation method, "integrating" it means nothing more
    than constructing it at the composition root once the other nine are
    live call sites. It doesn't gate or get gated by anything.

## 5. Files That Must Change

Based on the verified import graph, wiring this in without new orchestration
stages touches:

- **`Core/composition_root.py`** (not in this upload — construct each of the
  10 stateless components, following the existing pattern used for
  `stock_repository=`/`news_repository=` DI; expose on `ApplicationGraph`).
- **`Orchestration/runtime_analysis_pipeline.py`** — the only currently-verified
  file that would need a new call site to actually *invoke* the chain per
  request, since it's the confirmed production entry point. This is the one
  place where "additive, no breaking changes" has to be tested carefully:
  adding a call here changes `RuntimeAnalysisPipeline.run()`'s behavior, even
  if its signature doesn't change.
- **One new glue point between ReflectionRecord and DecisionEngine's `score:
  float` input** — not a new orchestration stage, just the score-derivation
  logic the chain currently has no owner for. This is the only genuinely new
  code required; everything else is construction and call-site wiring of code
  that already exists.
- Whatever currently produces `MemoryRecord` batches (unverified — not in this
  upload) may need a read path exposed to whatever calls Reflection.

I did not find `StockAgent`'s source in this upload, so I can't tell you its
exact current shape or whether it should be the caller instead of
`RuntimeAnalysisPipeline`.

## 6. Risk Analysis

- **Highest risk: the missing score-derivation glue.** It's the only piece of
  this integration that isn't already-tested, already-reviewed code — it's
  new logic translating `ReflectionRecord` into the `float` `DecisionEngine`
  expects, and its correctness directly determines every downstream decision.
- **Second: touching `RuntimeAnalysisPipeline.run()`.** It's documented as
  stateless and additive-only today; adding a call to the Decision Pipeline
  inside it means its output can now vary based on Decision Pipeline state,
  which is a behavior change worth its own regression pass even without an
  API signature change.
- **Low risk: the 10 orchestration stages themselves.** Each is small
  (72–216 lines), stateless, already isolated, and connected only by duck
  typing — wiring them together doesn't require modifying any of their
  internals.
- **Unverifiable risk:** without `Core/composition_root.py` in hand, I can't
  confirm there isn't already partial wiring in progress, or a reason these
  were deliberately left disconnected beyond "not yet integrated." Recommend
  reading that file directly before starting.

## 7. Estimated Implementation Stages

1. Locate/confirm the real `MemoryRecord` producer and its read API.
2. Write the score-derivation glue (ReflectionRecord → float) — the one new
   piece of logic.
3. Composition-root wiring: construct all 10 stages, expose on `ApplicationGraph`.
4. Single new call site in `RuntimeAnalysisPipeline.run()` (or wherever
   `StockAgent` actually lives, once seen) invoking the chain end-to-end.
5. Regression pass focused specifically on `RuntimeAnalysisPipeline` output
   parity for existing call patterns, since that's the file whose behavior
   is actually changing.
6. Construct `AutonomousAgent` last, at the composition root, once the other
   nine have live call sites — it has nothing to test beyond construction
   validation, since it exposes no invocable method.
