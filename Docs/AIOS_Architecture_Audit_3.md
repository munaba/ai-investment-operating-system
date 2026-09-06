# Architecture Audit — From "AI Agent Framework" to Personal AIOS

**Scope reviewed:** `Agents/`, `Core/`, `Providers/`, `Repository/`, `Database/`, `Services/`,
`Orchestration/`, `Tests/`, `main.py`, `Docs/architecture.md`, `Database/architecture.md`,
`Docs/project_context.md`, plus the empty `API/`, `Bot/`, `Market Data/`, `Utils/` folders.

This is an audit only — no code was written or changed. Every claim below is traced to a
specific file/behavior in the uploaded zip, not inferred from naming or intent. Two facts
drive most of the conclusions in this document, so they're stated up front:

> **Fact A.** The production entrypoint (`main.py` → `build_application()` → `StockAgent`)
> runs an 11-step `AnalysisPipeline` whose inter-step data flow is structurally broken — every
> step except step 1 (`StockService`) and step 8 (`NewsService`) fails its required-input check
> on every run, deterministically, regardless of network/API behavior. This is not a hypothesis;
> it's already fully documented, independently, in your own `Docs/architecture.md` §§2–9.
>
> **Fact B.** A second, structurally sophisticated subsystem already exists in `Core/runtime.py`
> (event-sourced actor runtime — step/resume/cancel/delegate/replay, an `ApprovalPort` and
> `SandboxPort`, causal-scope identity) and is fully unit-tested (11 dedicated test files,
> Stages 3–9.4). It is instantiated inside `Executor.__init__` and reachable from `StockAgent`
> — but `StockAgent.run()` never calls `self._executor.execute()`. The entire Runtime layer is
> not exercised by the production execution path today.

Put plainly: **the execution kernel is architecturally much further along than the live
application suggests. Most of the kernel components already exist and are individually
validated, but none of them have yet been demonstrated working together as the production
execution path.** That reframes what Stage L10 should be — see the final section.

---

## 1. Current Architecture Maturity

This is not an early-stage prototype. Evidence of maturity:

- A real layered dependency contract is written down and largely (not entirely) honored:
  `Agent → Orchestration → Service → Repository → Provider`, with forbidden edges listed
  explicitly in `Docs/project_context.md`.
- A hardened, backend-abstracted `Database` layer with a documented error-translation
  contract (`DatabaseError → RepositoryError → ServiceResult`), nested-savepoint transactions,
  cross-process migration locking verified with real subprocesses, and a fixed `:memory:`
  footgun (`Database/architecture.md`). This is production-grade engineering, not scaffolding.
- An event-sourced execution kernel (`Core/runtime.py`) with actor identity, step/resume/
  cancel/delegate, replay, and pluggable `ApprovalPort`/`SandboxPort` protocols — the exact
  shape a multi-domain "Brain" needs — backed by 11 dedicated stage test files.
- 32 test files, ~11,700 lines, covering unit, integration, and E2E levels, plus dedicated
  hardening tests for concurrency and locking edge cases.
- A `composition_root.py` that is genuinely hermetic (no network/filesystem I/O at
  construction time), idempotent, and whose docstring is a stage-by-stage audit trail of every
  additive decision back to Stage 9.0 — itself a sign of real engineering discipline over time.

Against that maturity, the honest overall grade is: **strong infrastructure, non-functional
product.** The parts that would make this useful *today* — the actual analysis pipeline a user
talks to — are the least reliable part of the codebase, while the parts that don't yet do
anything user-visible (Runtime, Repository layer, Database layer) are the most solid.

---

## 2. What Already Resembles an AI Operating System

- **`Core/runtime.py`** — this is, almost verbatim, a "Goal → Planning → Execution →
  Observation → Reflection" kernel already. It has actor lifecycle, event-sourced state
  (append-only event log + checkpoint/projection), suspend/resume, delegation between actors,
  cancellation, and an approval gate before side-effecting actions. This is AIOS-grade
  infrastructure, not agent-grade.
- **`ApprovalPort` / `SandboxPort` protocols + `Core/approval.py` / `Agents/sandbox.py`** —
  the "the AI must WORK, not only ANSWER" principle needs exactly this: a place where a
  planned action pauses for permission or runs in isolation before touching anything real.
  That seam already exists and is tested (`test_stage8_1_sandbox_approval.py`,
  `test_stage9_2_approval_policies.py`).
- **`Database` layer's error-contract discipline** — the `DatabaseError → RepositoryError →
  ServiceResult` translation chain, and the explicit statement that Agents must never see a
  raw `DatabaseError`, is exactly the kind of boundary discipline a long-lived personal system
  needs so that one domain's failure mode doesn't leak into every other domain.
- **`ProviderManager` / `ProviderSelector` / capability-based routing** (`Providers/`,
  `Agents/requirement_inference.py`) — a Brain that owns many domains needs to route a given
  step to whichever model/provider actually has the right capability; the beginnings of that
  (`select_by_requirement`, multi-provider registry as of "Stage L6") are already in place.
- **`AgentRegistry` / `ServiceRegistry` singletons** — a real registry pattern for "many things
  living under one process" already exists, even though nothing populates it with more than
  one agent or wires services through it yet (see §3).

## 3. What Is Still "AI Agent" Architecture

- **The only thing that actually runs end-to-end is single-domain, single-turn, single-ticker
  Indonesian stock Q&A.** `StockAgent._extract_ticker` requires exactly one 4-letter uppercase
  ticker per message and raises otherwise. There is no goal decomposition, no multi-step plan,
  no persistence of intent across turns beyond the in-process `ConversationMemory` (explicitly
  *not* backed by the database or vector store, per its own docstring).
- **`StockAgent.run` bypasses the planning/execution machinery it inherits.** It calls
  `AnalysisPipeline.run()` directly — a fixed, hardcoded, 11-step positional list with no
  dependency resolution, no conditional branching, no retry/backoff, no observation step, no
  reflection step. This is "chatbot with a fixed script," the exact shape the vision document
  says to move away from.
- **`main.py` is a blocking `input()`/`print()` REPL.** No scheduling, no background goals, no
  multi-channel input (Telegram/Discord live only as an unwired `NotificationService`), no
  session/state persistence across process restarts.
- **`ServiceRegistry` and `ToolRegistry`/`Executor` exist but are decorative** in the live path
  — `AnalysisPipeline` receives its 11 services via direct constructor injection, bypassing
  `ServiceRegistry` entirely, and `StockAgent.run` never calls `Executor.execute()` or
  `Planner.plan()`/`should_use_tool()` (only `Planner.select_provider()`). Two real
  orchestration subsystems exist; the live agent uses neither.
- **One agent, one domain, no cross-domain composition.** `MarketAnalysisAgent` and
  `IDXStockAgent` also exist as separate classes, not as Skills under one Brain — the codebase
  currently instantiates *disconnected specialized agents*, which is precisely Design
  Principle 3's "no" case ("do not create multiple disconnected agents").

## 4. Missing Subsystems (for the AIOS Vision Specifically)

Ranked by how directly they block "digital brain that does my daily work":

1. **A real planning layer that can decompose an arbitrary goal into steps.** `Planner.plan()`
   today is a keyword-substring heuristic over `ToolRegistry.list()` — good enough to decide
   "should I call a tool," nowhere near "here is a multi-step plan to reach this goal."
2. **A working data/dependency-resolution mechanism between steps.** The nesting bug (Fact A)
   isn't a one-off defect — it reveals that the current metadata model (flat dict, nest-by-
   producer-name, no un-nesting) cannot express "step N needs step M's output" at all. Any
   future Brain with many Skills needs a real typed contract or DAG between steps, not a
   convention that happens to work only when a reader's key name matches a writer's key name
   *and* both happen to be top-level.
3. **Cross-session, cross-domain memory.** `ChromaVectorStore`/`VectorStore` exists in
   `Database/` but has no caller anywhere outside its own module. A brain needs durable memory
   that survives process restarts and is shared across Skills — today nothing writes to it.
4. **Scheduling / proactivity.** Nothing in the codebase initiates work on its own — everything
   is a synchronous reply to a typed line in a terminal. An OS that "performs my daily work"
   needs triggers: time-based, event-based, or goal-persistence-based.
5. **A real multi-domain routing layer ("Brain dispatch").** `AgentRegistry` can hold many
   agents, but nothing decides *which* agent/Skill a given goal belongs to — that decision is
   currently made by which Python script you run.
6. **Skill packaging convention.** There's no shared interface that "Coding," "Stocks,"
   "Telegram," etc. would all implement, comparable to `BaseService`/`BaseAgent`/`BaseProvider`
   for their respective layers. Without one, "add a new domain as a Skill" (Principle 9) has
   nothing to plug into yet.
7. **Observability across a run**, not just per-service. `ServiceResult.message`,
   `.execution_time_ms`, and `.error` are populated by every one of the 11 services and read by
   *nothing* (`Docs/architecture.md` §2.3) — you're already generating the telemetry a
   "digital brain" would need for self-monitoring, and throwing it away.
8. **`API/`, `Bot/`, `Market Data/`, `Utils/`** are empty directories — placeholders for future
   surfaces/domains with zero content today.

## 5. Biggest Architectural Bottlenecks

1. **The metadata-nesting bug is the single highest-leverage bottleneck in the repository.**
   It silently defeats 9 of 11 pipeline steps. Nothing downstream of it can be trusted until
   it's fixed, and — more importantly for the AIOS pivot — *the mechanism itself* (implicit
   flat-namespace convention with no enforcement) is the wrong contract for a system that will
   eventually have many Skills reading and writing shared state. Fixing the bug without
   replacing the mechanism just delays the next version of the same class of failure.
2. **Two parallel orchestration engines, only one of which is used, and it's the weaker one.**
   `Runtime`/`Executor`/`Planner.plan()` (goal-oriented, approval-gated, resumable) sits idle
   while `StockAgent` hand-rolls a simpler, less capable pipeline. Every future domain built the
   way `StockAgent` was built inherits the same ceiling.
3. **Fixed, positional execution order with no dependency resolution.** `AnalysisPipeline`'s
   step order is "purely positional" (`Docs/architecture.md` §10) — there's no way to express
   "B needs A's output" other than getting the constructor argument order right by hand. This
   does not scale past ~11 steps, let alone to a Brain with many Skills each contributing steps.
4. **No un-nesting / no typed step-output contract.** Even if the nesting bug were patched today
   by flattening `result.data` into the top level, nothing would prevent two future Skills from
   colliding on the same key name — there is no namespacing discipline beyond convention.
5. **Single-agent, single-turn framing baked into `StockAgent` itself** (ticker-per-message
   extraction, no goal object, no plan object). This isn't a bug so much as evidence that the
   current "Agent" abstraction was designed for Q&A, not for the Goal→Plan→Execute→Observe→
   Reflect loop the vision calls for — that loop needs a first-class `Goal`/`Plan`/`Run` object
   that doesn't exist anywhere in the codebase yet.
6. **`ConversationMemory` is explicitly ephemeral** (in-process, not database- or vector-store-
   backed). A digital brain that's supposed to "become my digital brain" cannot forget
   everything on restart; this is a hard blocker for the vision, not a nice-to-have.

## 6. Scalability for a Single-User AIOS

The single-user framing (Design Principle 1) is good news here: several things that would be
hard problems for a multi-tenant system are non-problems for you, and the codebase already
reflects that correctly — no account/permission model has been built, which is right.

What *does* need to scale, even for one user, over a multi-year horizon:

- **Number of domains ("Skills"), not number of users.** The `AnalysisPipeline` positional-list
  pattern scales to maybe a dozen steps by hand; it will not scale to "Coding + Stocks + Crypto
  + Finance + Browser + Database + Excel + Telegram + Discord + University + Business +
  Automation" as one execution graph. This is the concrete, measurable reason the pivot matters
  architecturally, not just philosophically.
- **State volume over time.** `ConversationMemory`'s FIFO/bounded design and the unused vector
  store both point at the same gap: a single-user system that runs for years accumulates a lot
  of history, and "keep everything in a Python list for the life of the process" was never
  going to survive that, single-user or not.
- **The `Database` layer is already built to scale correctly for this** — SQLite today with an
  explicit, documented seam for Postgres/TimescaleDB/DuckDB later, nested transactions so
  Repository methods compose, and locking that's been verified with real OS processes. This
  layer does **not** need architectural rework for the AIOS pivot; it needs *tenants* (in the
  domain sense — one schema/namespace per Skill), not a rewrite.
- **Concurrency**: a single-user Brain that eventually runs Coding + Telegram + Crypto watchers
  concurrently needs the Runtime's actor model (already built) actually driving execution,
  since a single blocking `input()` loop (current `main.py`) cannot host concurrent domains at
  all.

## 7. Recommended Long-Term Module Hierarchy

This keeps every existing layer that's already correct (`Database`, `Repository`, `Providers`,
`Core` infra) and reorganizes only the layers the AIOS vision actually changes.

```
Core/                  # infra: config, logging, exceptions, event sourcing, approval, sandbox
  runtime.py            (existing — becomes the execution kernel for everything, not just Executor's private detail)
  composition_root.py

Brain/                 # NEW — replaces the "one agent per domain" pattern
  goal.py               # first-class Goal/Plan/Run objects (currently absent)
  planner.py             (promote/replace Agents/planner.py — real decomposition, not keyword match)
  dispatcher.py          # routes a Goal to the right Skill(s); today nothing does this
  reflection.py          # NEW — the "Reflection" step the vision calls for; absent today

Skills/                # NEW — replaces Agents/ as "one class per domain"
  base_skill.py          # the missing shared interface called out in §4.6
  coding/
  stocks/                (StockAgent's logic migrates here as a Skill, not a standalone Agent)
  crypto/
  finance/
  browser/
  database/
  excel/
  telegram/
  discord/
  university/
  business/
  automation/

Services/              # KEEP — this layer's SRP-per-service design is sound; the problem was
                        # never the services, it was how they're wired together (see Orchestration)

Orchestration/          # KEEP the name, replace the implementation
  service_pipeline.py    # currently a NotImplementedError stub — this is where dependency-
                          # resolved (DAG) step execution belongs, replacing AnalysisPipeline's
                          # positional list

Repository/             # KEEP — external/ and persistence/ split is correct, keep extending it
Database/                # KEEP — no structural change needed, see §6
Providers/                # KEEP — ProviderManager/ProviderSelector already fit the Brain model

Memory/                # NEW (or promote Database/vector_store) — cross-session, cross-Skill,
                        # durable memory; today unused and disconnected

Interfaces/             # NEW — replaces empty Bot/, API/
  cli.py                 (current main.py becomes one thin interface, not "the app")
  telegram/
  discord/
  api/
```

The key structural change is not adding folders — it's that **`Agents/` stops being where
domain logic lives.** Domains become Skills registered with the Brain; Agents-as-a-concept
either disappears or becomes a thin adapter Interfaces use to talk to the Brain.

## 8. Future Brain / Skill Architecture

Concretely, building on what already exists rather than inventing new machinery:

- **The Brain *is* `Core.runtime.Runtime`, promoted from "Executor's private implementation
  detail" to "the thing everything runs on."** Right now `Runtime` is constructed inside
  `Executor.__init__` and nothing outside `Executor` ever sees it directly. Making it the
  central kernel means every Skill's execution goes through the same actor/event/approval
  machinery — which is exactly what gives you one Brain instead of many disconnected agents.
- **A Skill is a `BaseService`-shaped contract, one level up**: name, description, category
  (already the pattern all 11 existing services follow), plus a `plan(goal) -> Steps` and
  `execute(step, context) -> ServiceResult`-equivalent. You do not need to invent this pattern
  from scratch — `BaseService`'s discipline (never raise for business failure, always return a
  result object, `health_check()`) is already the right shape; it just needs to be lifted from
  "one analysis step" to "one domain."
- **Domains that are currently separate Agent classes (`StockAgent`, `MarketAnalysisAgent`,
  `IDXStockAgent`, `IdxStockAgent`) collapse into Skills the Brain dispatches to**, not
  standalone entrypoints. `AgentRegistry` already has the right shape for this (a name →
  instance registry) — it's currently just underused, holding at most one agent in practice.
- **Approval and Sandbox stay exactly where they are** (`Core/approval.py`, `Agents/sandbox.py`,
  the `ApprovalPort`/`SandboxPort` protocols) — this is one of the few places the existing
  design already matches "the AI must WORK, not only ANSWER" precisely: a plan can pause for
  your sign-off before it does something irreversible, and that gate is domain-agnostic by
  construction.
- **Cross-Skill state goes through the Database/Repository layers you already hardened**, not
  through a new nested-dict metadata convention. That means the DAG-based `ServicePipeline`
  (currently a stub) should resolve step dependencies by reading/writing through Repository-
  shaped contracts, not by trusting flat dict keys to happen to match.

## 9. Long-Term Execution Pipeline

Mapping the vision's stated pipeline onto what exists vs. what's missing:

| Stage | Vision | What exists today | Gap |
|---|---|---|---|
| **Goal** | User or system states an objective | Nothing — a message is parsed directly into a ticker | No `Goal` object anywhere in the codebase |
| **Planning** | Decompose into steps | `Planner.plan()` (keyword heuristic) + `AnalysisPipeline`'s fixed list | No decomposition, no dependency resolution, no conditional branching |
| **Execution** | Run the steps | `Executor`/`Runtime` (sophisticated, unused) vs. `AnalysisPipeline.run` (used, structurally broken) | The good engine isn't wired in; the wired one is broken |
| **Observation** | Capture what happened | `ServiceResult.message`/`.execution_time_ms`/`.error` populated by every service | Populated but read by nothing — observation data exists and is discarded |
| **Reflection** | Learn / adjust from the result | Nothing | No reflection step exists in any form |

The practical implication: you don't need to design this pipeline from a blank page. You need
to (a) retire `AnalysisPipeline` as the thing that actually runs and replace it with the DAG-
based `ServicePipeline` it was already stubbed out to become, (b) route execution through
`Runtime` instead of around it, (c) actually persist the `ServiceResult` telemetry that's
already being generated as your Observation stage, and (d) add a Reflection stage as new work
— it's the one piece with no precedent anywhere in the current code.

## 10. Proposed Roadmap (Stages L10–L18+)

This roadmap reflects three corrections made after review, each of which changes the *order*
or *framing* of work below, not just its content:

- **Metadata flow is an architecture decision, not an implementation assumption.** The
  metadata-nesting bug and the fact that `AnalysisPipeline` itself is slated for retirement are
  two separate findings. Collapsing them into one "fix" invites a patch to get coded before
  anyone has actually decided the direction — so Stage L10 ends in a decision, not a diff.
- **Reflection is deferred until at least two Skills exist.** Reflection over a single
  workflow's history is just logging with an extra name. It only becomes real once there's more
  than one kind of observation history to compare across (Stock → Crypto → Coding → Browser →
  history → Reflection), so it's sequenced after the second Skill, not right after Observation
  infrastructure.
- **Brain and Skill are not designed separately from their first implementation.** Designing
  `BaseSkill` in the abstract and only later migrating `StockAgent` into it reliably produces a
  second round of interface changes once real implementation surfaces a missing method, a
  missing field on the context object, or a wrong dispatcher assumption. So `BaseSkill`'s design
  and `StockAgent`'s migration happen in the same stage, with the interface finalized only after
  that first migration validates it.

These corrections change the sequencing of work rather than the architectural destination.

**Stage L10 — Audit & architecture decisions only.**
No code changes. Two decisions get made and approved here:

- *Decision Point A — Metadata Flow Strategy.* Two options, evaluated on their own terms rather
  than pre-selected:
  - **Option A — Stabilization patch.** Flatten metadata so the current 11-step pipeline runs
    as documented. Cheap, small blast radius, explicitly throwaway — it exists only to keep
    production working while Option B or the ServicePipeline migration is built.
  - **Option B — Immediate DAG migration.** Implement `ServicePipeline` now and remove the
    live path's dependency on the positional `AnalysisPipeline` directly, instead of patching a
    pipeline that's already scheduled for retirement. Higher upfront cost, no throwaway work.
  - **Decision criterion.** Option A is appropriate when production stabilization is the
    immediate priority and temporary technical debt is acceptable. Option B is appropriate when
    avoiding duplicate implementation work outweighs the higher upfront migration cost.
- *Decision Point B — Runtime wiring.* Report the Runtime/Executor disconnect (Fact B) the same
  way — what's currently unreachable, what wiring it in would touch, and confirmation that it
  doesn't change `StockAgent`'s current observable behavior (Backward Compatibility, Principle
  5) — before any wiring happens.

Both decisions are reported per Design Principle 7 (root cause, blast radius, tradeoffs) and
wait for explicit approval before Stage L11 begins.

**Stage L11 — Implement the approved architectural decisions.**
Each Decision Point from L10 is implemented only if and as approved, independently of the
other:

- *If Decision Point A is approved:* implement whichever of Option A/Option B was chosen.
- *If Decision Point B is approved:* promote `Core.runtime.Runtime` from a private detail of
  `Executor.__init__` to a directly-constructed object in `composition_root.py`.

Either decision can be deferred without changing the other's implementation. Each piece that is
implemented ends with the usual audit/hidden-coupling report/blast-radius/proof-suite/
regression/tech-debt handover (Principle 6).

**Stages L12–L14 — Finish the orchestration foundation + Observation capture.**
`ServicePipeline` (DAG-based dependency resolution, if not already done as part of L10/L11's
Option B), `Goal`/`Plan`/`Run` as first-class objects (zero precedent in the current code today,
so this is designed deliberately once), and Observation *capture* — persisting the
`ServiceResult` telemetry that's already generated by every service but currently read by
nothing. This stage produces the data.

**Stage L15 — Reflection infrastructure (not Reflection logic yet).**
The storage schema, indexing, and hooks that Reflection will eventually read from — the system
that consumes the data L12–L14 produces. No reflection logic runs yet — there's only one
Skill's worth of history to learn from at this point, which per the correction above isn't
enough to reflect on meaningfully.

**Stage L16 — `BaseSkill` design + `StockAgent` migration, together.**
Design `BaseSkill` and migrate `StockAgent` into it as the first Skill in the same stage:
design → migrate → validate against real behavior → revise the interface → finalize. The
interface is allowed to change once, based on what the first real migration reveals, rather
than being frozen before any implementation exists.

**Stage L17 — Second Skill (e.g. Crypto).**
Validates the Brain/Skill abstraction under genuinely multi-domain conditions rather than a
single, possibly-idiosyncratic domain. This is also what makes Stage L18's Reflection
meaningful: two different kinds of Observation history to compare, not one.

**Stage L18 — Reflection engine goes active.**
Now that there's cross-Skill Observation history (Stock + Crypto, at minimum), Reflection has
something real to learn from — this is the first point in the roadmap where that's true.

**Stage L18+ — Scheduling, proactive execution, Interfaces (CLI/API/Bot), further Skills.**
Multi-domain steady state: all target domains registered as Skills, Interfaces as thin adapters
over the same Brain, Memory persisted and shared, Reflection actively shaping future Planning —
the point at which "digital brain that performs my daily work" is literally true of the running
system, not just the docs.

---

## What Stage L10 Should Become Under This Vision

Given Fact A's severity (9 of 11 production pipeline steps are silently non-functional right
now) and Fact B's low risk/high leverage (make an already-built, already-tested engine reachable
— no new logic), **Stage L10 is scoped as decisions only** — Decision Point A (metadata flow
strategy, Option A vs. Option B above) and Decision Point B (Runtime wiring) — kept strictly
separate from any Brain/Skill naming changes, which belong to L16 onward:

1. Report the metadata-nesting defect formally (per Design Principle 7) — root cause, blast
   radius (which of the 11 services are actually affected, confirmed above as 9 of 11), and
   Decision Point A's two options with their tradeoffs — and wait for approval before either is
   chosen.
2. Report the Runtime/Executor disconnect (Fact B) the same way — what's currently unreachable,
   what wiring it in would touch, and confirm this doesn't change `StockAgent`'s current
   observable behavior (Backward Compatibility, Principle 5) — before proceeding.
3. Only after both reports are approved does Stage L11 implement the chosen metadata strategy
   and the Runtime promotion, each ending with the required audit/hidden-coupling
   report/blast-radius/proof-suite/regression/tech-debt handover (Principle 6).

Everything else in this document — `Brain/`, `Skills/`, `Goal`/`Plan`/`Run`, the DAG pipeline,
Memory, Reflection — is real and worth building, but belongs to Stage L12 onward, not L10.
Stage L10's job is narrower and more urgent: **decide how the thing you already run should
actually work, and confirm how the thing you already built becomes reachable**, before any new
architecture is layered on top of either.
