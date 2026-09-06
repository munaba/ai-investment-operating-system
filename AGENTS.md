# AGENTS.md — AIOS (Personal IDX Decision & Support Agent)

## What this project is

AIOS is a personal, evidence-led daily trading decision-support agent for
the Indonesian stock market (IDX), with a controlled copilot layer on top.
See `AIOS_Personal_IDX_Decision_Agent_Roadmap.md` (root) for the full
product spec — read it before touching anything, it is the source of
truth for scope and phase gates.

**It is NOT:** a broker, an autonomous trading bot, a financial adviser,
or a system that submits live orders. A human is always the final
decision-maker. Any real order is placed manually by the user at their
own broker.

## Non-negotiable product boundaries

- No broker dependency — no broker account, API key, live order
  submission, or broker reconciliation anywhere in this codebase.
- Human-only real execution — the system may describe a plan; it must
  never place, amend, or cancel a live order.
- Evidence before a plan — a trade plan needs sourced evidence and
  timestamps. Missing/stale/contradictory/failed inputs yield an
  explicit non-action status, never a directional recommendation.
- Fail closed — provider, scheduler, notification, permission, or
  persistence failures show up in health/audit records and never
  trigger a financial action.
- Paper is separate — a journal decision never auto-creates a paper
  order. Paper execution needs an explicit user command/approval.
- Least privilege — tools are read-only by default. Writes are scoped,
  auditable, and permission-gated.
- US/crypto/forex are parked — do not implement or expand them unless
  explicitly and separately authorized. IDX is the only active market.

## Engineering conventions (apply to every task, every phase)

- **Audit before code.** Read the actual source, migrations,
  composition root, and relevant tests for the area you're touching
  before writing anything. Do not infer method names or data models —
  verify them.
- **Additive-only changes.** Don't alter or remove existing behavior
  without explicit instruction. Preserve unrelated uncommitted changes
  in the working tree.
- **No fabricated data, ever.** If evidence is missing or a
  collaborator wasn't wired up, return an explicit status/sentinel
  (e.g. `PENDING`, `DATA_STALE`, `INSUFFICIENT_DATA`) — never a
  plausible-looking default.
- **Phase boundaries are locked.** Each roadmap phase (A through H) has
  a defined acceptance gate. Do not start the next phase, or reach
  into scope from a later/parked phase, until the current gate is
  demonstrated. If you hit a blocker or an ambiguous boundary, stop and
  report it — do not improvise past it.
- **Regression tests are mandatory per phase/task.** New service or
  policy work ships with its own focused test file under `Tests/`, plus
  a check that existing regressions still pass.
- **Canonical decision statuses** (see roadmap for full table):
  `SUCCESS`, `NO_TRADE`, `DATA_STALE`, `DATA_ERROR`,
  `INSUFFICIENT_DATA`, `ANALYSIS_FAILED`, `RISK_REJECTED`,
  `POLICY_BLOCKED`. Only `SUCCESS` may carry a conditional trade plan.

## Working style the user (Nabil) expects

- Give complete files or precisely targeted snippets — not diffs.
- Verify/cross-check data or results thoroughly before moving to a new
  topic; don't proceed on assumptions.
- Send/output files immediately once created — don't describe them
  first and hand them over later.
- Report structure at the end of a task, matching the roadmap's own
  protocol: `FILES READ`, `FILES CHANGED`, `CONTRACTS FOUND`, `TESTS`,
  `CLI/RESTART PROOF`, `ACCEPTANCE`, `EXTERNAL BLOCKER`.

## Project structure (top level)

| Path | Purpose |
|---|---|
| `Core/` | Composition root, bootstrap, runtime, doctor/diagnostics, config, product mode |
| `Business/` | Domain policies and engines (risk ledger, paper trading engine, position manager, ranking, market calendars, per-market policies) |
| `Orchestration/` | Copilot layer: skills, tools, planner, executor, scheduler, permission/capability system, workflow runtime |
| `Services/` | Application-facing services (decision brief, journal, observation window, sustained-use review, notifications) |
| `Repository/` | Persistence layer (base repository; per-feature repositories live under `Repository/persistence/`) |
| `Providers/` | LLM/provider abstraction (Gemini, Ollama, provider selection) |
| `Agents/` | Agent framework primitives (registry, planner, executor, memory) predating the Orchestration copilot layer |
| `Database/` | DB manager, migrations (one `migrations_*.py` per feature area), backup |
| `Tests/` | Test suites — one file per stage/activation/phase/feature |
| `Docs/` | Closeout reports per Activation/Phase — check here for what's actually been verified vs. claimed |
| `run_*_migrations.py` (root) | Standalone migration runners, one per feature area |
| `main.py` | Entry point |

## Roadmap status (verify against `Docs/` closeout reports before trusting this)

Phases A–G are complete per the roadmap's sequential gate model. Phase H
("Sustained-use review — no automatic expansion") is active:

- Task 1 — Observation window infrastructure: complete.
- Task 2 — `Services/sustained_use_review_service.py`
  (`SustainedUseReviewService`) — assembles real, possibly-partial
  evidence for a review window; read-only, no state mutation.
- Task 4 — `Services/sustained_use_final_review_service.py`
  (`SustainedUseFinalReviewService`) — ties Task 1's observation window,
  Task 2's evidence, and new `operator_feedback` /
  `final_review_records` tables together. Makes **no**
  CONTINUE/SIMPLIFY/AUTHORIZE_FUTURE_INVESTIGATION decision itself —
  `human_decision` stays `PENDING` until a human explicitly supplies
  one. Never calls an LLM. Write scope is strictly limited to
  `operator_feedback` and `final_review_records` — no access to
  order/trade/position/risk-limit/account tables.

Phase H's acceptance gate does not unlock live execution under any
circumstance — treat that as permanent, not phase-specific.

Before assuming any other phase/task status, check `Docs/<ACTIVATION or
PHASE>/*.md` closeout reports and the actual source — this table is a
snapshot, not a guarantee.

## What NOT to do

- Don't add broker APIs, live-order paths, or credentials for real
  trading.
- Don't implement or expand US/crypto/forex scope without explicit
  separate authorization.
- Don't let a memory/copilot-layer component overwrite or bypass
  financial records, risk policy, or permissions.
- Don't let `Services/sustained_use_final_review_service.py` (or any
  Phase H component) touch order/trade/position/risk-limit/account
  state — it's evidence-and-feedback only.
- Don't infer or fabricate a `human_decision` / recommendation where
  the roadmap requires an explicit human input.
- Don't hand-wave a CLI/restart proof — run it for real and report
  `BLOCKED` if the environment can't support it (e.g. no real Telegram
  credentials).
