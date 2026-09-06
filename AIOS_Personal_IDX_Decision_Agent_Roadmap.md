
AIOS — Personal IDX Decision & Support Agent

Status and purpose

Product goal: AIOS is a personal, evidence-led daily trading decision and support agent for IDX. It refreshes available market data, detects and ranks opportunities, explains risk-bounded trade plans, sends useful alerts, and maintains a separate paper portfolio and decision journal.

It is not: a broker, an autonomous trading bot, a financial adviser, or a system that submits live orders. A human remains the final decision-maker and, if desired, places any real order manually at their broker.

This document replaces the forward-looking portion of the former activation roadmap. It is written as an implementation roadmap for Claude/Codex, not as evidence that every prior activation is complete.

Reading the source correctly

Source-derived facts

The supplied original Master Prompt (Roadmap).md states that the initial IDX workflow is scanner → analysis/ranking → recommendation/risk validation → human approval → paper execution → audit/performance → notification. It also requires explicit failure states, restart-safe persistence, human approval, and no silent conversion of data errors into signals.

The same source makes old Activations 8–11 a later expansion: 8 was small-capital live IDX with a broker adapter; 9 US stocks; 10 crypto; and 11 forex. Its Activation 12 contains the Hermes/OpenClaw-like capabilities: tool registry, permissions, planner, durable memory, scheduler, and diagnostics.

The supplied newer AIOS_Day_Trade_Decision_Copilot_Roadmap.md explicitly says broker/live execution/autonomous buy-sell are outside the MVP; Telegram is the first channel; and current reusable seams include provider support, scheduler/event/runtime/permissions, market analysis/ranking/risk, paper execution/performance/journal persistence, and Telegram notifications. It also flags that data-provider failures must remain explicit and that durable, retrievable personal memory is not yet an end-to-end product flow.

The historical closeout material demonstrates implemented notification wiring and failure propagation, but its recorded real Telegram-delivery gate was blocked by absent credentials/network in that audit environment. Treat a real delivery as an operational proof to re-run, not as an assumed fact.

Redesign decisions in this document

The following are intentional product decisions, not claims that the old source already implemented them:

Live broker/API work is removed from the active roadmap.

“BUY/SELL” is reframed as a conditional plan; NO_TRADE is first-class.

Paper portfolio and journal become the measurement loop for the product.

Hermes/OpenClaw-like facilities become the controlled operating layer, rather than a late feature after live trading.

US, crypto, and forex are parked until this single IDX workflow proves useful and reliable.

Product boundaries (non-negotiable)

No broker dependency. No broker account, API key, endpoint, scraping of broker sessions, live order submission, or broker reconciliation is required or permitted in this roadmap.

Human-only real execution. AIOS may describe a plan; it must never tell a connector to place, amend, cancel, or check a live order.

Evidence before a plan. A trade plan needs sourced evidence and timestamps. Missing, stale, contradictory, or failed inputs yield an explicit non-action status—not a directional recommendation.

Fail closed. Provider, scheduler, notification, permission, or persistence failures are visible in health/audit records and never trigger a financial action.

Paper is separate. A journal decision does not create a paper order. Paper execution requires an explicit user paper command/approval.

No performance promise. Paper results measure process and simulated outcomes; they do not imply profitability or suitability for real trading.

Least privilege. Agent tools are read-only by default. Writes are limited to local decision/journal/paper state, each auditable and permission-gated.

Target operating loop

market-data refresh → quality/freshness gate → analysis + ranking →
DecisionBrief / NO_TRADE → notification when material → human review →
optional explicit paper action → journal + portfolio valuation → daily review
                                     │
                                     └→ scheduler, memory, diagnostics, audit

Canonical decision statuses

Only SUCCESS can contain a conditional trade plan. All other statuses are explicit and non-executable:

Status

Meaning

Ranking / alert behavior

SUCCESS

Evidence and risk gates support a conditional plan.

May rank and send a deduplicated plan alert.

NO_TRADE

Valid review found no setup meeting policy.

Record; no trade alert.

DATA_STALE

Evidence exists but exceeds freshness policy.

Exclude; send data-health alert only when material.

DATA_ERROR

Fetch/provider/schema failure.

Exclude; record and health-alert with rate limit.

INSUFFICIENT_DATA

Not enough valid inputs/history.

Exclude; record.

ANALYSIS_FAILED

Analysis could not be completed.

Exclude; record and diagnose.

RISK_REJECTED

Plan breaks personal risk limits.

Exclude; show the rejection reason to the user.

POLICY_BLOCKED

Market closed, symbol disallowed, kill switch, or permission block.

Exclude; record.

Data freshness and quality policy

Freshness must be evaluated per source and per field, using provider timestamp, received timestamp, source name, symbol/market, and validation result. Never substitute an old quote as a current quote without marking it stale.

Default policy values must be configuration, visible in doctor/health output, and covered by tests. Until an operator chooses values, use conservative defaults such as:

Data class

Suggested default

If stale/unavailable

Intraday price/volume used for a day-trade plan

15 minutes during market session

DATA_STALE; no plan/ranking

Market/session/calendar status

5 minutes

POLICY_BLOCKED until confirmed

News/event risk input

60 minutes, with source timestamp

Omit that factor or reject if policy makes it mandatory; never invent sentiment

End-of-day / historical bars

next trading-session refresh

Mark as historical; cannot alone support an intraday entry plan

Portfolio paper valuation

same quote freshness rule

Show valuation timestamp and “stale valuation” label

The scheduler may refresh only when the market/session policy permits it. It must use backoff and source-rate limits, retain the last good observation with its original timestamp, and publish a degradation event rather than hammering a failed provider.

Notification contract

Telegram remains the first delivery channel. Notifications are informational, concise, attributable, and never claim certainty.

Trigger

Delivery rule

Pre-market readiness

Once per configured trading day: data health, watchlist coverage, risk limits, and schedule state.

New or materially changed SUCCESS brief

Send once per symbol/brief version only when confidence, entry/stop/target, rank, or evidence changes materially. Include timestamp and “decision support, not an order.”

NO_TRADE

No push by default; include in scheduled summary.

Data/provider/scheduler degradation

Alert on state transition; rate-limit repeats and include recovery notification.

Risk limit / paper kill switch

Immediate, explicit alert; no paper action is taken automatically.

Market close

One recap: briefs, decisions, paper activity, portfolio valuation freshness, and open follow-ups.

Daily review

One review of adherence and paper performance, with no performance promise.

All sends need idempotency keys, persisted delivery attempts/outcomes, timezone-aware schedules (default Asia/Jakarta), quiet hours, a user toggle, and a manual retry path. Notification failure must not roll back already-committed local journal or paper state.

Paper-trading workflow

A scan produces a persisted DecisionBrief, NO_TRADE, or explicit failure result.

The user records TAKE, SKIP, or WAIT; this is a journal event, not an order.

Only a separate, explicit paper confirmation may create a paper order linked to the brief and risk validation.

Existing atomic paper safeguards remain mandatory: cash/position updates, fees, lot/quantity policy, idempotency, reconciliation, backup/restart recovery, and auditable order-trade linkage.

The portfolio is valued from timestamped market data; stale values are labelled and cannot be presented as live equity.

End-of-day review compares plan versus paper outcome: planned R, realised R where calculable, stop adherence, policy violations, fees, drawdown, and attribution by strategy/regime. It may report insufficient evidence rather than make a performance conclusion.

Reframed activation map

Former activation

Disposition

New role

0–4

Preserve proven foundations where current tests/state confirm them.

Baseline/startup, valid IDX scan, atomic paper engine, and manual CLI remain prerequisites.

5

Preserve performance/audit work; do not fabricate unresolved metrics.

Use as the paper-accounting foundation; define exposure explicitly before showing it as a real metric.

6

Preserve Telegram implementation and failure behavior.

Reuse for outbound alerts; prove real delivery in the target operator environment.

7

Preserve paper-validation controls and reconciliation.

Becomes ongoing validation, not a one-time gate to live trading.

8: live IDX

Retired from active scope.

Replaced by DecisionBrief, personal risk ledger, and proactive decision-support routine.

9: US stocks

Parked.

No implementation until the IDX workflow meets sustained-use gate.

10: crypto

Parked.

No implementation until separately authorized after IDX workflow proves useful.

11: forex

Parked.

No implementation until separately authorized after IDX workflow proves useful.

12: agent capabilities

Reframed and pulled forward with boundaries.

Scheduler, tool permissions, durable memory, diagnostics, and controlled tools operate the personal agent.

New phased roadmap

Each phase is sequential. Do not start the next phase until its gate is demonstrated with source-level tests and the stated CLI/state evidence. A blocked external service is a visible result, never a reason to fake a passing gate.

Phase A — Product mode and baseline contract

Objective: Freeze the no-broker product boundary and verify actual reusable contracts before adding behavior.

Implementation scope: Add/configure decision_copilot mode; inventory the real composition root, scanner/ranking/risk path, paper boundaries, scheduler, Telegram outbound adapter, persistence, permission registry, and diagnostics. Ensure any live/broker path is absent or disabled in this mode.

Acceptance gate: doctor and init identify mode, database, configured data sources, Telegram state, scheduler state, and optional providers; the command runs without broker configuration; the report identifies any external-data or real-Telegram proof blockers.

Phase B — DecisionBrief and policy gate (next activation)

Objective: Turn existing valid analysis/ranking/risk outputs into one durable, read-only, auditable decision artifact.

Implementation scope:

Audit and reuse the actual analysis/ranking/risk engines; do not create a second strategy engine.

Persist DecisionBrief with brief ID/version, symbol/market, status, generated-at, evidence/source timestamps, analysis/ranking linkage, confidence, reason codes, and policy result.

For SUCCESS, include conditional entry zone, invalidation/stop, target(s), risk/reward, risk amount/percentage, and assumptions only when supported by source calculations.

Add DecisionPolicy to reject stale/missing evidence, invalid risk arithmetic, session-loss limit breach, disallowed symbol, market/session block, and duplicate/currently unchanged brief.

Add read-only CLI: brief SYMBOL and brief watchlist; existing command names must be audited rather than assumed.

Support retrieval after restart and show source timestamps in output.

Acceptance gate: valid symbols yield different persisted briefs where evidence differs; failed/stale symbols never enter valid ranking or display disguised BUY/SELL advice; policy rejection includes a deterministic reason; a restart can read the same brief; focused tests plus a real CLI proof run against whatever data state is honestly available.

Phase C — Personal risk ledger and decision journal

Objective: Make discipline and learning first-class without creating an order.

Implementation scope: Persist personal limits (reference capital, per-trade risk, daily loss, maximum decisions/trades, loss-streak cooldown, allowed symbols); journal TAKE/SKIP/WAIT, free-text reason, optional manual execution/close data, planned/realised R when calculable, and adherence. Keep it distinct from the paper order/trade tables.

Acceptance gate: plan → user decision → optional outcome → review persists across restart; invalid plans or exceeded limits are RISK_REJECTED; the system never creates paper state merely because a journal decision was saved.

Phase D — Proactive IDX routine and data-health operations

Objective: Make AIOS work through the day without requiring repeated manual scans.

Implementation scope: Schedule pre-market check, market-session refresh/scan, data-health checks, close recap, and daily review; implement freshness policy, deduplication, retry/backoff, market-calendar gating, alert preferences, health summary, and audit events.

Acceptance gate: a simulated trading day produces exactly one pre-market check, correctly deduplicated material brief alerts, explicit source degradation/recovery messages, one close recap, and one review; disabled/closed-market schedules do not fetch or alert; all scheduled runs are observable after restart.

Phase E — Telegram inbound, single-user control plane

Objective: Allow the owner to use the core workflow from a phone without widening authority.

Implementation scope: Separate inbound adapter; allowlisted chat IDs; durable session/command audit; limited deterministic commands such as /scan, /plan SYMBOL, /journal, /review, /health, and /help; no free-form command can invoke paper execution or configuration changes without explicit policy/confirmation.

Acceptance gate: authorized sender receives a real read-only plan/health reply; unauthorized senders are rejected and audited; a restart retains journal/configuration; failure to poll or reply is visible through diagnostics. Prove outbound Telegram delivery in an environment with real credentials and network before calling delivery production-verified.

Phase F — Controlled Hermes/OpenClaw-like copilot layer

Objective: Make the agent conversational and proactive while preserving deterministic financial controls.

Implementation scope: Use existing provider/runtime/tool registry only after audit; allow LLM use for intent classification, explanation, summaries, and navigation of stored evidence. Add durable retrieval for user preferences, notes, previous decisions, and lessons with source links. Keep financial state in its own database models. Tools are explicitly classified: read-only, journal-write, paper-write, admin. Planner may schedule/read/summarize but cannot relax risk policy, create a paper order, or change permissions autonomously.

Acceptance gate: the agent accurately explains a stored decision or rejection with cited record IDs; unavailable LLM falls back to deterministic commands; tool-denial/audit logs prove it cannot cross permission or risk boundaries; no memory item can overwrite financial records.

Phase G — Paper portfolio validation and continuous review

Objective: Use the existing paper engine to validate process quality and operating reliability over time.

Implementation scope: Explicitly link approved briefs to paper orders; retain atomic execution/reconciliation/backup behavior; implement valuation freshness labels; finish only metrics with defined formulas (including exposure if shown); produce period reviews by strategy, regime, and decision adherence.

Acceptance gate: explicit approved-paper flow remains atomic through restart; reconciliation is clean; a review traces metrics to decisions/orders/trades/prices; stale valuation is labelled; no automated transition to real trading exists.

Phase H — Sustained-use review (no automatic expansion)

Objective: Decide whether the personal IDX agent is useful, reliable, and worth maintaining.

Implementation scope: Define an operator-selected observation window and review availability, data freshness failures, alert usefulness, plan/journal adherence, paper reconciliation, drawdown/process metrics, and operator feedback.

Acceptance gate: a written evidence review shows real operating records, known limitations, and a deliberate human decision to continue, simplify, or separately authorize a future market/broker investigation. It does not unlock live execution.

Implementation protocol for Claude/Codex

For the active phase only:

Read the actual source, migrations, composition root, and relevant tests first; preserve unrelated working-tree changes.

Report source-derived contracts and the smallest genuine gap. Do not infer method names or data models.

Implement one vertical slice, including explicit failure and restart behavior.

Run focused tests, relevant regressions, and an honest CLI/state proof. Report external blocks as BLOCKED.

Update the phase closeout with files changed, evidence, failures, tests, database/restart proof, risks, and status.

Do not begin the following phase until the current acceptance gate passes.

Immediate handoff: Phase B prompt

AIOS — PHASE B: DECISION BRIEF AND POLICY GATE

Product boundary: AIOS is a personal IDX decision-support and paper-trading agent.
Do not add broker APIs, live execution, broker credentials, live-order checks, US/crypto/forex work, or automatic BUY/SELL execution.
Preserve all current uncommitted changes; do not reset unrelated work.

First audit only the actual Phase-B-relevant source: composition root, scanner/analysis/ranking/risk result contracts, persistence/migrations, existing CLI, paper boundaries, and tests.

Then implement the smallest genuine vertical slice that:

1. Creates a single persisted DecisionBrief from existing valid analysis/ranking/risk outputs—do not duplicate engines.
2. Uses explicit statuses: SUCCESS, NO_TRADE, DATA_STALE, DATA_ERROR, INSUFFICIENT_DATA, ANALYSIS_FAILED, RISK_REJECTED, POLICY_BLOCKED.
3. Stores and displays evidence/source/timestamps/confidence/reason codes; exposes entry, invalidation/stop, target, and risk fields only when genuinely available.
4. Rejects stale or missing evidence, invalid risk math, personal loss-limit breach, and policy blocks. A rejected/failed item cannot appear as an actionable plan.
5. Adds a read-only CLI brief command only after confirming the project’s real command conventions.
6. Proves persistence/retrieval after restart and adds focused tests plus relevant regressions.

Do not claim production data or Telegram delivery when the environment cannot prove it. At the end report only:
FILES READ
FILES CHANGED
CONTRACTS FOUND
TESTS
CLI/RESTART PROOF
ACCEPTANCE
EXTERNAL BLOCKER
