# Phase 2 Architecture: Evolving AutonomousAgent into a Real Autonomous Runtime

**Status:** Architecture proposal only — no implementation, no diffs, no new classes.
**Scope:** Defines the design AutonomousAgent must grow into, and how to get there without breaking Phase 1.
**Grounding:** Every recommendation below is anchored to concrete, existing code — `Orchestration/autonomous_agent.py`, `Orchestration/runtime_analysis_pipeline.py`, `Agents/stock_agent.py`, `Core/runtime.py`, `Core/approval.py`, `Core/composition_root.py` — not hypothetical infrastructure.

---

## 1. High-Level Responsibilities of AutonomousAgent

Today, `AutonomousAgent` (Stage L28A) is a frozen dataclass that only *aggregates* the ten decision-pipeline components (`reflection` … `learning_loop`). It calls nothing. Phase 2 must give it a real job — but the job is narrower than it sounds.

**AutonomousAgent should own the *loop*, not the *logic*.**

Concretely, its responsibilities are:

- **Drive repeated cycles** of the already-complete Observe → … → Learn chain, instead of the single pass `RuntimeAnalysisPipeline.run()` performs today.
- **Own cross-cycle state**: iteration count, lifecycle status, the active goal/objective, and enough context to build the next `ServiceContext` without a human re-prompting it each time.
- **Own the termination/pacing policy**: when to stop, retry, pause, or continue — not what any individual stage decides.
- **Own failure and approval routing at the loop level**: deciding whether a cycle's outcome should halt the loop, retry it, or pause for human sign-off.

It explicitly should **not**:

- Reimplement or duplicate any logic already inside `Reflector`, `DecisionEngine`, `DecisionPolicy`, `PolicyGuard`, `ExecutionIntent`, `ExecutionPlanner`, `ExecutionCoordinator`, `PortfolioEngine`, `PortfolioRisk`, or `LearningLoop`. Those ten components must remain exactly what Sprints 1–9 built them to be: pure, stateless, single-shot transformers.
- Reimplement what `RuntimeAnalysisPipeline` already does (registering a private Tool, driving it through `Executor`/`Runtime`, formatting the tool message). That stays the single-cycle execution kernel façade.
- Perform real-world side effects (placing an order, moving money) — no such capability exists anywhere in the current chain (`ExecutionCoordinator`, `PortfolioEngine`, and `PortfolioRisk` only ever produce structured *readiness/exposure/risk records*, never a real trade). AutonomousAgent must not quietly invent this; it's a distinct, future capability with its own approval and safety requirements.

In one sentence: **AutonomousAgent is a loop controller and goal owner that repeatedly invokes the existing single-cycle pipeline, not a new decision-making stage.**

---

## 2. Agent Lifecycle

The instinct is to reach for the canonical `Observe → Think → Plan → Decide → Execute → Learn → Reflect → Repeat` loop. That doesn't quite fit what's already built, and forcing it would misrepresent the real chain. The production chain already *is* an agent lifecycle — it just hasn't had an outer loop wrapped around it yet. Phase 2's job is to name and repeat it, not replace it.

Mapped onto real classes, one cycle looks like:

| Conceptual phase | Real implementation (already live) |
|---|---|
| **Observe** | `AnalysisPipeline.run(context)` → `Dict[str, ServiceResult]` |
| **Record** | `Observation` construction → `MemoryRecorder.record()` → `MemoryStore` |
| **Reason** | `Reflector.reflect(records)` → `DecisionEngine.decide(score)` |
| **Govern** | `DecisionPolicy.apply()` → `PolicyGuard.evaluate()` |
| **Commit** | `ExecutionIntent.build()` → `ExecutionPlanner.plan()` → `ExecutionCoordinator.coordinate()` |
| **Evaluate** | `PortfolioEngine.evaluate()` → `PortfolioRisk.assess()` |
| **Learn** | `LearningLoop.learn()` |
| **Repeat** | *Missing today — this is what Phase 2 adds.* |

Two honest observations that should shape the design rather than be papered over:

1. **There is no "Act" stage yet.** Nothing in the current chain places an order or otherwise touches the outside world. `ExecutionCoordinator`/`PortfolioEngine`/`PortfolioRisk` describe *readiness and risk*, not *action*. AutonomousAgent's lifecycle must have an explicit seam where real execution could later be inserted (after `PortfolioRisk`, gated on `approved=True`), but Phase 2 does not build that seam's contents — only the loop that would eventually call it.
2. **"Reflect" already means something different here than in the canonical loop.** `Reflector` performs statistical/aggregation reflection over stored `Observation`s, not agent self-critique. Reusing the word for a *second*, different purpose (e.g., "reflect on whether the loop itself is behaving well") would be confusing. If Phase 2 ever wants loop-level self-assessment, it needs a different name, not an overload of `Reflector`.

**Recommended lifecycle name for AutonomousAgent's loop:** *Observe → Reason → Govern → Commit → Evaluate → Learn → Repeat*, with an explicit, currently-empty **Act** seam after Evaluate, reserved for future work. This is not a new set of classes — it's a description of what `RuntimeAnalysisPipeline.run()` already does per call, plus the repetition and termination logic AutonomousAgent adds around it.

---

## 3. Required Public API

Recommendation: **two methods**, deliberately not one.

### `step(context) -> AutonomousAgentCycleResult` (or similarly named result)
Runs **exactly one** iteration of the lifecycle above, synchronously, with no loop, no sleep, no retry, no background thread. Internally it should do nothing more than: build/accept a `ServiceContext`, delegate to the same execution kernel `RuntimeAnalysisPipeline` already exposes, advance loop-local bookkeeping (iteration count, last-cycle outcome), and return a small immutable summary.

### `run(...)` (termination-bounded loop)
A thin driver that calls `step()` repeatedly until a termination condition is met — bounded iteration count, a deadline, or an external stop signal (see §8). All pacing/looping/termination logic lives here and *only* here.

### Why `step()`/`run()` and not `run()`/`execute()`/`process()`/`handle()`/`invoke()` alone

- **Vocabulary collision.** `run()` already means something specific and different at two other layers of this codebase: `StockAgent.run(message)` means "answer one chat turn," and `AnalysisPipeline.run(context)` means "execute the 11-step service pipeline once." Reusing `run()` *alone* for "start a potentially-unbounded autonomous loop" would overload a word that already has two other meanings in the same call graph.
- **Precedent already exists in this codebase for exactly this split.** `Core.runtime.Runtime` itself distinguishes `ingest()` (submit one event) from `step()` (advance one actor by one unit) from higher-level drivers like `replay()`. AutonomousAgent's `step()`/`run()` split mirrors that existing vocabulary rather than inventing new terminology.
- **Testability.** Every sprint so far (1–9) has prioritized deterministic, isolated testing (`logger.debug()`-only side effects, no I/O, pure functions). A bare `run()` that loops internally is hard to unit test deterministically. `step()` lets tests call it exactly once, or exactly N times, and assert on state after each call — the same style `Tests/test_stage_l11_runtime_analysis_pipeline.py` already uses.
- **Two audiences.** `step()` serves callers who want to drive the loop externally (a scheduler, a test, a CLI `for` loop). `run()` serves callers who just want "start it and let it go until some condition."

Additionally, for consistency with every other agent-shaped class in this codebase (`MarketAnalysisAgent`, `RuntimeAnalysisPipeline`, `StockAgent`, all `BaseProvider` implementations), AutonomousAgent should expose:

### `health_check() -> bool`
Never raises, mirrors the existing convention exactly, and gives operators a cheap liveness probe before starting a `run()`.

### `pause()` / `resume()` / `cancel()`
These should **not** be new mechanisms. They should be thin wrappers that flip AutonomousAgent's own lifecycle status and delegate to `Core.runtime.Runtime.suspend(actor_id)` / `Runtime.resume(actor_id, snapshot)` / `Runtime.cancel(actor_id, depth)` for any in-flight actor — all three already exist and are already tested (`Tests/test_stage5_suspend_resume.py`, `Tests/test_stage7_cancel.py`). See §7 and §8.

---

## 4. Internal State

**The ten L18–L27 components stay stateless. AutonomousAgent becomes the one place statefulness is allowed to live.** That asymmetry is intentional and should be preserved, not blurred.

What AutonomousAgent should own:

- **Lifecycle status** — an enum mirroring the existing `Agents.state.AgentState` pattern already used by `BaseAgent`/`StockAgent` (e.g. `IDLE`, `RUNNING`, `PAUSED`, `STOPPED`, `ERROR`), for consistency and so existing state-handling conventions (e.g. "must `reset()` from `ERROR`") transfer directly.
- **Iteration/session bookkeeping** — cycle count, timestamp of the last cycle, last cycle's outcome summary (not the full `Dict[str, ServiceResult]` — that stays internal to each cycle, exactly as it does today inside `RuntimeAnalysisPipeline`).
- **Goal/objective reference** — a reference to a `Goal` (Stage L15's `GoalPlanner` concept, built but currently unwired into production). This is what actually makes the loop "autonomous" rather than "repeatedly the same one-shot call": something has to decide *what* to keep observing across cycles, and that's a goal, not a stage.
- **Enough recurring parameters to build the next `ServiceContext`** — e.g., which ticker/instrument or universe to keep observing — **not** full `ServiceContext`-construction logic itself. That construction logic should continue to live wherever it already lives (mirroring `StockAgent._build_context`), reused, not duplicated.

What it should explicitly **not** own:

- Full planning context or `ServiceContext` construction logic (avoid duplicating `StockAgent`'s existing responsibility).
- Any of the ten stage components' internal state — they must remain reusable, cross-request singletons exactly as `composition_root.py` already builds them.

**Structural recommendation:** because AutonomousAgent will now hold mutable state, it can no longer remain a `@dataclass(frozen=True)`. The mutable session/loop state should live in a small, explicit, separately-named value object (e.g., a distinct state/session record) owned by AutonomousAgent, rather than loose instance attributes scattered across the class. This keeps state inspectable, testable in isolation, and swappable for persistence later (e.g., resuming a session after a process restart) without AutonomousAgent itself becoming a god object.

---

## 5. Relationship with RuntimeAnalysisPipeline

Four options were on the table: replace it, wrap it, call it, or be called by it.

**Recommendation: AutonomousAgent calls RuntimeAnalysisPipeline. It does not replace, wrap, or invert the relationship.**

| Option | Verdict | Why |
|---|---|---|
| **Replace** | Rejected | `RuntimeAnalysisPipeline` is explicitly LOCKED behavior across ten sprints, is the shared execution kernel `StockAgent` already depends on optionally, and has its own dedicated, passing regression suite (`test_stage_l11_runtime_analysis_pipeline.py`). Replacing it would break `StockAgent`'s existing (optional) wiring and every additive-only guarantee Phase 1 built. |
| **Wrap** (subclass/decorate) | Rejected | `RuntimeAnalysisPipeline`'s entire design is "stateless facade around one Tool-mediated pass" (its own docstring: "no per-call state ever lives on `self`"). Wrapping it to add loop state would either smuggle statefulness into a class explicitly designed not to have any, or produce a wrapper indistinguishable from AutonomousAgent itself — redundant. |
| **Be called by** (RuntimeAnalysisPipeline calls AutonomousAgent) | Rejected | Inverts the dependency direction the wrong way. Sprint 10 explicitly established "no execution logic inside `RuntimeAnalysisPipeline`" as a constraint; having the single-shot façade reach *up* into an unbounded loop controller violates that and creates a dependency cycle risk (composition root already builds `runtime_analysis_pipeline` before `autonomous_agent` is fully capable). |
| **Call** (chosen) | **Adopted** | Purely additive: `AutonomousAgent.step()` invokes `RuntimeAnalysisPipeline.run(context)` exactly the way `StockAgent._run_service_pipeline` already does. Zero changes required to `RuntimeAnalysisPipeline`'s public contract. Matches the dependency direction every prior sprint has used (higher-level component composes lower-level one via DI). |

**One genuine seam Phase 2 will eventually need, flagged but not built now:** today `RuntimeAnalysisPipeline._maybe_reflect_and_decide` only ever logs each stage's result via `logger.debug()` and the method returns nothing; `run()` returns just the final formatted `str`. For AutonomousAgent to make real loop-level decisions (e.g. "was this cycle's learning signal POSITIVE, should I keep going?"), it eventually needs more than log lines to inspect. The correct, additive way to close this gap later is an **optional, default-`None`** structured result made available *alongside* the existing `str` return — following the exact optional-constructor-argument pattern every one of Sprints 1–9 already used — never a breaking change to the current return type. This is called out as future work, not implemented here.

---

## 6. Relationship with StockAgent

**Recommendation: peers, not a hierarchy.** Neither becomes "the" top-level orchestrator that absorbs the other.

- `StockAgent` remains the **single-turn, human-request-driven** orchestrator: one `run(message)` call, one ticker, one provider-authored reply, backed by `ConversationMemory`. Its job is answering a question.
- `AutonomousAgent` becomes a **separate, parallel top-level orchestrator** for unattended/continuous operation: no per-turn human message, driven by `step()`/`run()` instead of `run(message)`.
- Both are peers that independently compose `RuntimeAnalysisPipeline` for their own purpose — exactly as `StockAgent` already does today via its optional `runtime_analysis_pipeline` constructor argument.

`Core/composition_root.py`'s `ApplicationGraph` already exposes `agent` (the `StockAgent` singleton) and `autonomous_agent` side by side, as independent attributes. Phase 2 should keep that shape: two siblings on the graph, not one subordinate to the other.

**Explicitly avoid:** making `StockAgent` depend on `AutonomousAgent` or vice versa. If a future product surface wants a chat command like "start monitoring BBCA," that's a UI/product integration (e.g., a tool/command that constructs and starts an `AutonomousAgent` session) — not an architectural coupling between the two classes.

---

## 7. Failure Handling

The substrate for this already exists and is already tested — Phase 2 should **reuse it**, not build a parallel failure-handling system.

Already available in `Core/runtime.py` / `Core/approval.py`:
- `ApprovalOutcome.APPROVED` / `DENIED` / `PENDING`
- `ApprovalDenied` / `ApprovalPending` exceptions
- `ToolExecutionError` (error-as-data wrapping for handler failures)
- `Runtime.cancel(actor_id, depth)` — recursive cancellation, already covers parent/child actor trees
- `Runtime.suspend(actor_id) -> Snapshot` / `Runtime.resume(actor_id, snapshot)`

Recommended flow:

- **Per-cycle failures.** If `RuntimeAnalysisPipeline.run()` raises inside `step()`, the loop-controller boundary (not any stage) catches it, records the failure into loop state (mirroring `AgentState.ERROR` handling already used by `BaseAgent`/`StockAgent`), and lets `run()`'s termination policy — not the exception handler itself — decide whether to stop or retry the *next* `step()` call.
- **Retries** are bounded and **cycle-level only** — retry the next `step()` call, never inject retry logic into any of the ten stages. They must stay deterministic and side-effect-free; retry semantics belong exclusively to the loop controller.
- **Cancellations** flow through `AutonomousAgent.cancel()`, which sets loop status to `STOPPING`/`STOPPED` and forwards to `Runtime.cancel(actor_id, depth)` for any in-flight actor — reusing the existing recursive-cancel machinery instead of inventing new plumbing.
- **Approvals are not failures.** `ApprovalPending` is a legitimate pause state, not an error. `run()` should transition to a distinct `PAUSED`/`AWAITING_APPROVAL` status and stop ticking until externally resumed, using `Runtime.suspend()`/`resume()` + `Snapshot` rather than a bespoke pause mechanism.
- **Unexpected runtime errors** transition AutonomousAgent to `ERROR` and stop the loop outright, mirroring exactly how `StockAgent.run()` already transitions to `AgentState.ERROR` on any exception. Recovery requires an explicit `reset()` call, for the same reason `StockAgent` already enforces this: safety-relevant boundaries should require a deliberate human/operator action to clear, not silently self-heal.

---

## 8. Long-Running Execution

Three termination models, all supportable without AutonomousAgent owning any concurrency primitives itself:

1. **Bounded** — `run(max_iterations=N)`. Deterministic, finite, ideal for tests and backtests. This should be the safest default and the only mode Phase 2's first implementation needs to fully support.
2. **Deadline/cadence-bounded** — `run(until=<timestamp>)` or a configured interval between cycles. Useful for scheduled operation, but note the distinction below.
3. **Indefinite with external stop** — `run()` with no bound, terminated only by an external `cancel()`/`stop()` call.

**Suspension** should reuse `Runtime.suspend(actor_id) -> Snapshot` / `Runtime.resume(actor_id, snapshot)` directly rather than invent a second persistence format. AutonomousAgent's own `PAUSED` status simply means "don't call `step()` again"; any in-flight `Runtime` actor is suspended via the existing snapshot mechanism, which is already exercised by `Tests/test_stage5_suspend_resume.py`.

**Shutdown** (`cancel()`/`stop()`) should be idempotent, transition status to `STOPPED`, and guarantee no further `step()` calls occur. Whether an in-flight actor is cancelled immediately or allowed to finish its current cycle is a policy flag (graceful vs. immediate), not a new mechanism — both map onto the existing `Runtime.cancel()` contract.

**A firm architectural boundary:** AutonomousAgent itself should **not** own a thread, timer, `asyncio` task, or scheduler. It stays a pure, synchronous, single-threaded "loop body + policy" object whose `step()`/`run()` are invoked by something *outside* it — a CLI loop, a cron job, a queue consumer, a future scheduler/host service. This matches the existing design discipline across every one of the ten stages (no threading, no async, no I/O beyond what's explicit) and keeps AutonomousAgent trivially unit-testable — call `step()` N times, assert on state, no mocking of real concurrency required. "Always-on background execution" is a distinct, separately-designed **Scheduler/Host** concern layered on top in a later phase, not something folded into AutonomousAgent.

---

## 9. Future Extensibility

- **Multi-agent.** Because AutonomousAgent (both today and as proposed) only holds duck-typed component references — no hard imports of concrete classes — running multiple independent `AutonomousAgent` instances side by side (e.g., one per ticker or universe) requires no new abstraction: each is just a fresh set of injected singletons plus its own loop state. Coordination *between* multiple agents (e.g., shared portfolio exposure limits across instruments) should be a separate future coordinator layered above them, reusing `PortfolioRisk`'s existing exposure/diversification/concentration semantics rather than duplicating that logic per agent.
- **Portfolio management across instruments.** `PortfolioEngine`/`PortfolioRisk` currently operate on one `ExecutionCoordinatorResult` per cycle. True cross-instrument portfolio management needs an aggregation point *above* individual AutonomousAgent loops. The current per-cycle `PortfolioEngineResult`/`PortfolioRiskResult` are the right unit to aggregate later — out of scope now, but nothing in this proposal blocks it.
- **Continuous monitoring.** Falls naturally out of the bounded/indefinite `run()` modes in §8. A "monitor without acting" mode is a future configuration toggle (e.g., stop the chain early after `PolicyGuard`/`ExecutionIntent` rather than proceeding to Commit/Evaluate), not a structural redesign — though today the chain always runs end-to-end regardless of approval outcome, so this toggle is itself future work.
- **Scheduling/background execution.** Explicitly deferred to the future Scheduler/Host component from §8 — this keeps AutonomousAgent's core loop reusable regardless of what triggers it.
- **Human approval.** `Runtime`'s `ApprovalPort` abstraction (already a `Protocol`, already has `AlwaysApprove`/`DenyAll`/`ToolWhitelist`/`ToolBlacklist` implementations in `Core/approval.py`) is the correct extension point for a future "require human sign-off before real execution" mode. A new `ApprovalPort` implementation (queue-backed, UI-backed, whatever the product needs) plugs in without AutonomousAgent needing any awareness of *how* approval is granted — only that `Runtime` may return `PENDING` and the loop must pause, which §7/§8 already account for.

---

## 10. Migration Plan (Phase 1 → Phase 2, Non-Breaking)

Following the exact additive discipline Sprints 1–9 already established:

1. **Evolve, don't replace, the class.** Convert `AutonomousAgent` from `@dataclass(frozen=True)` to a regular class that accepts the same ten component references, in the same order, with the same non-`None` validation it already performs in `__post_init__`. Every existing (currently nonexistent, since nothing calls it yet) construction site stays compatible. Expose the ten existing attributes as read-only properties so any future code that reads `agent.decision_engine`-style attributes keeps working unchanged.
2. **Add mutable loop state as a private, internal attribute** (or a small owned state object per §4), initialized to `IDLE`. This does not change the constructor signature.
3. **Add `step()` first, alone.** No loop, no sleep, no threading — build/accept a `ServiceContext`, call `RuntimeAnalysisPipeline.run(context)` once, capture the result, advance state, return a summary. Ship and test this in isolation (mirroring the exact test style already used for L18–L27) before adding anything else.
4. **Add `run(...)` as a thin driver over repeated `step()` calls** with a termination condition, entirely inside AutonomousAgent. No changes required to `Runtime`, `RuntimeAnalysisPipeline`, or any of the ten L18–L27 stages.
5. **Wire it into `composition_root.py` the same way every prior sprint did**: construct the singleton once, do not change its lifetime, do not pass it into `StockAgent` or `RuntimeAnalysisPipeline` (dependency flows the other way — see §5/§6), and continue exposing it on `ApplicationGraph` (already true today).
6. **Only after `step()`/`run()` are stable**, evaluate whether `RuntimeAnalysisPipeline` needs the additive, optional structured-result seam flagged in §5 — implemented as a strictly optional/default-`None` addition, following the exact pattern of every optional constructor argument added across Sprints 1–9, so the existing `str`-returning contract for every current caller (`StockAgent`, the full existing test suite) is untouched.
7. **Add approval/pause/cancel integration last**, once bounded `run()` is proven — it's the highest-risk, most-stateful piece, and should not block the simpler bounded-loop functionality from shipping first.
8. **At every step, run the full existing regression suite unchanged**: `integration_test.py`, `E2e_test.py`, every `test_stage_l1*`–`test_stage_l28*` file, `test_stage9_0_composition_root.py`. Phase 2 is additive by the same definition Phase 1 used — none of them should require modification, only new AutonomousAgent-specific test files alongside them.

This plan introduces zero breaking changes at any step: no existing public method signature changes, no existing return type changes, no existing singleton's lifetime changes, and no existing stage gains new responsibility. Everything new is additive, optional, and constructed exactly once — the same guarantee every sprint from L1 through L28 has already delivered.
