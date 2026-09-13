# AIOS Unified Cockpit — Concept

> **CONCEPT ONLY — NOT FOR IMPLEMENTATION DURING ACTIVE PHASE H**
>
> Observation Window #1 remains `ACTIVE` / `PENDING`. This document is a
> planning artifact that maps already-proven backend capabilities to a
> future single-pane operator surface. No code, DB, migration, frontend
> page, permission, or observation-window semantic is changed by this doc.
> Build decisions for a real cockpit follow the Phase H gate:
> `PENDING` → `CONTINUE` / `SIMPLIFY` / `AUTHORIZE_FUTURE_INVESTIGATION`
> → then evaluate.

## 1 — Purpose & Scope

AIOS today has two honest frontend layers:

* **Product / public experience** — `/atrium` `/atlas` `/arc` `/materi` `/jejak` `/ikhtisar` `/profil` (visual storytelling, GSAP/Three.js/Lenis, `EmptyLayout`).
* **Operations / evidence** — `/phase0` … `/phase3` and the Phase H evidence views (utilitarian tables, scheduler/audit, review evidence).

Backend coverage already exceeds that split (copilot, scheduler, Telegram control plane, Decision Brief, Risk Ledger, valuation freshness, paper execution/review, observation window, sustained-use review, final review). No new feature is proposed here. This concept only arranges **capabilities that already ship** into one cockpit so the operator stops context-switching across tabs during observation.

Non-goal: visual redesign, new trading logic, new permissions, new storage.

## 2 — Low-Fidelity Mock (ASCII)

```
┌─────────────────────────────────────────────────────────────────┐
│  AIOS — Unified Cockpit                          [ACTIVE WINDOW] │
│  Window #1  2026-08-24 → 2026-09-23  Asia/Jakarta   PENDING      │
├─────────────────────────────────────────────────────────────────┤
│  SYSTEM STATE                                                    │
│  Window        ACTIVE (08-24 → 09-23, Asia/Jakarta)              │
│  Freshness     FRESH · last snapshot 17:32 Asia/Jakarta         │
│  Scheduler     HEALTH  last run … · dedup …                      │
│  Risk Gate     READY / BLOCKED  (ledger)                         │
│  Copilot       READ-ONLY                                         │
├─────────────────────────────────────────────────────────────────┤
│  MARKET / DECISION                          [Latest scan 17:32]  │
│  Symbol │ Signal │ Confidence │ Freshness │ Reason               │
│  BBCA   │  WAIT  │  —         │ FRESH     │ policy gate          │
│  TLKM   │  WAIT  │  —         │ STALE     │ valuation stale      │
│  …                                                              │
├─────────────────────────────────────────────────────────────────┤
│  DECISION CONTEXT                                                │
│  Latest Brief  #42  BBCA  WAIT  2026-09-13T10:31 Asia/Jakarta     │
│  Why           Policy gate / valuation / evidence refs           │
│  Strategy/Regime  strategy=RISK_LEDGER · regime=MARKET_REGIME   │
│  Valuation freshness  snapshot vs. brief vs. now                │
├─────────────────────────────────────────────────────────────────┤
│  PORTFOLIO / PAPER                                               │
│  Positions  2 OPEN · 3 CLOSED   Realized P&L  +Rp …              │
│  Orders     4 (last 24h)        Fees        Rp …                 │
│  Trades     7                   Reconciliation  ✓ / —             │
│  [Positions] [Orders] [Trades] [Equity/P&L] [CSV] [Markdown]    │
├─────────────────────────────────────────────────────────────────┤
│  OBSERVATION EVIDENCE  (SustainedUseReviewService — read-only)   │
│  Availability       ✓ / —                                        │
│  Freshness          ✓ / —                                        │
│  Alerts / Dedup     n new · dedup_state                         │
│  Journal            — / n entries                                │
│  Drawdown / Process —                                            │
│  Strategy / Regime  account-wide (not window-scoped)             │
│  Limitations        verbatim list (traceable)                    │
│  Traceability       window_id → brief_id → snapshot_id           │
├─────────────────────────────────────────────────────────────────┤
│  OPERATOR ACTIONS                         (HumanDecisionService)  │
│  [Review evidence]  [Submit feedback]  [Final decision …]        │
│  PENDING  — no auto-decision; explicit CONTINUE / SIMPLIFY /    │
│  AUTHORIZE_FUTURE_INVESTIGATION only.                            │
└─────────────────────────────────────────────────────────────────┘
```

### HTML sketch (optional, paste into a blank page to preview)

```html
<!-- CONCEPT ONLY — throwaway preview, no Blazor wiring -->
<div style="max-width:980px;margin:24px auto;font:13px/1.5 ui-monospace,monospace;color:#cbd5e1;background:#0b1220;border:1px solid #1e293b;border-radius:12px;overflow:hidden">
  <div style="padding:12px 16px;border-bottom:1px solid #1e293b;display:flex;justify-content:space-between">
    <strong>AIOS — Unified Cockpit</strong><span style="color:#f59e0b">ACTIVE WINDOW · PENDING</span>
  </div>
  <div style="padding:14px 16px;display:grid;gap:14px">
    <section><b>System State</b><br>Window ACTIVE &nbsp;·&nbsp; Freshness FRESH &nbsp;·&nbsp; Scheduler HEALTH &nbsp;·&nbsp; Risk Gate READY &nbsp;·&nbsp; Copilot READ-ONLY</section>
    <section><b>Market / Decision</b><br>Symbol | Signal | Confidence | Freshness — rows mirror Decision Brief read model</section>
    <section><b>Decision Context</b><br>Latest brief, reasoning, strategy/regime, valuation freshness</section>
    <section><b>Portfolio / Paper</b><br>Positions · Orders · Trades · Equity/P&L · Scheduler · export CSV/Markdown</section>
    <section><b>Observation Evidence</b><br>Availability · Freshness · Alerts/Dedup · Journal · Drawdown · Strategy/Regime · Limitations (verbatim)</section>
    <section><b>Operator Actions</b><br>Review · Feedback · Final Decision — explicit human choice only</section>
  </div>
  <div style="padding:10px 16px;border-top:1px solid #1e293b;color:#64748b;font-size:11px">CONCEPT ONLY — NOT FOR IMPLEMENTATION DURING ACTIVE PHASE H</div>
</div>
```

## 3 — Sections (what each shows, read-only)

| # | Section | What the operator sees | Interaction |
|---|---------|------------------------|-------------|
| 1 | **System State** | `operator_observation_windows.status`, wall-clock vs `Asia/Jakarta` window bounds, `DatabaseService` freshness, `scheduler_job_runs` health, `risk_limits` gate, copilot mode | Read-only badges; links to existing phase pages |
| 2 | **Market / Decision** | Latest scan symbols × signal (`WAIT`/`BUY`/…), confidence, freshness per symbol, brief reference | Filter/sort, no execution |
| 3 | **Decision Context** | Selected brief: `generated_at`, `status`, `reason`, `risk_amount`/`position_size`, strategy & regime attribution, valuation snapshot age | Deep-link to brief detail |
| 4 | **Portfolio / Paper** | `positions` (OPEN/CLOSED), `orders`, `trades`, equity/P&L, `notification_dedup_state`, CSV/Markdown export | Tabs identical to Phase 3 today |
| 5 | **Observation Evidence** | The 8 evidence dimensions from `SustainedUseReviewService` + `SustainedUseFinalReviewService` verbatim (including `[NOT_AVAILABLE]` / `[EXTERNAL_BLOCKED]` / `[AVAILABLE]` prefixes), `known_limitations[]`, `evidence_status` | Traceable to `window_id` |
| 6 | **Operator Actions** | `operator_feedback` composer, `final_review_records.human_decision` (`PENDING` → explicit choice), `decision_note`/`decided_by` | Write-gated; audit-logged |

## 4 — Capability Mapping (only proven backend)

Every row below exists in the repo at `2026-09-13` (`HEAD 771a4f4`) and is reachable via `DatabaseService` / `Program.cs` `/api` or a Blazor phase page. No row invents a new service.

| Cockpit field | Proven source | Route / table / service | Notes |
|---|---|---|---|
| Window ACTIVE/PENDING, bounds, timezone | `operator_observation_windows` | `GET /api/phase2/windows` · `DatabaseService.GetObservationWindowsAsync` | `window_id=1`, `Asia/Jakarta`, `ACTIVE` at doc time |
| Data freshness (snapshot age) | `portfolio_snapshots.timestamp` + valuation freshness | `GET /api/phase0/*` · `DatabaseService` | Compared to window `start_at`/`end_at` (ISO-8601 string compare, UTC-stamped) |
| Scheduler health, dedup | `scheduler_job_runs`, `notification_dedup_state` | `GET /api/phase3/scheduler`, `/api/phase3/dedup` | Already surfaced in Phase 3 |
| Risk gate | `risk_limits`, `audit_events` (risk) | `GET /api/phase3/audit` · `RiskLedger` | Fail-closed; no execution path from cockpit |
| Market/Decision rows | `decision_briefs` (+ `ranking_snapshots` when present) | `GET /api/phase1/*` or decision-brief read model | `status` in `{ SUCCESS, NO_TRADE, DATA_STALE, … }` |
| Decision Context detail | `decision_briefs` + `portfolio_snapshots` + strategy/regime services | `GET /api/phase2/review/{id}` | Strategy/regime are account-wide per `PaperReviewService` today — not window-scoped (documented limitation) |
| Positions / Orders / Trades / P&L | `positions`, `orders`, `trades`, `daily_performance` | `GET /api/phase3/positions`, `/orders`, `/trades` | Paper vs live separated; paper never auto-creates orders |
| Evidence panel (8 dims) | `SustainedUseReviewService` → `final_review_records.evidence_status`, `known_limitations` | `GET /api/phase2/review/{id}`, `/feedback/{id}` | 5×`[NOT_AVAILABLE]` when collaborator/account not supplied, 1×`[EXTERNAL_BLOCKED]` (broker investigation out-of-scope Phase H), 2×`[AVAILABLE]` (methodology) — verbatim preservation required |
| Operator feedback | `operator_feedback` | `GET /api/phase2/feedback/{id}` | Read-only history in cockpit |
| Final decision | `final_review_records.human_decision` (`PENDING`/`CONTINUE`/`SIMPLIFY`/`AUTHORIZE_FUTURE_INVESTIGATION`) + `HumanDecisionService.SubmitDecisionAsync` | `POST /api/decision/submit` | `PENDING` is the only auto-state; the other three are explicit human writes, audit-logged |

### What is explicitly NOT mapped

Broker live-market investigation, live order submission, risk-limit mutation, account mutation, LLM-driven decisions — all remain out-of-scope for this surface (Phase H Task 4 write scope is `operator_feedback` + `final_review_records` only; `SustainedUseFinalReviewService` never calls an LLM).

## 5 — Constraints & Exit Criteria

* **During ACTIVE Phase H:** this cockpit does not ship. The operational pages (`/phase0`…`/phase3`) remain the observer/operator surface; Atrium/Atlas/… remain locked product experience. No new route `/cockpit` is added while `final_review_records.human_decision = PENDING`.
* **After the gate:** when a human submits one of the three decisions, the cockpit concept is re-evaluated as the integration target — but still against the proven rows above, not against imagined features.
* **Traceability:** every evidence line shown must carry its source (`window_id`, `review_id`, dimension key, `[AVAILABLE]`/`[NOT_AVAILABLE]`/`[EXTERNAL_BLOCKED]` prefix) so the operator can audit it against `Docs/` closeouts and raw DB rows.

## 6 — Revision

* `2026-09-13` — initial concept (HEAD `771a4f4`, Window #1 `ACTIVE`, `PENDING`). Author: Hermes. Reviewer feedback incorporated (external cockpit assessment 2026-09-13).
