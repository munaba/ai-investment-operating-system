
# PHASE D.1 CLOSEOUT — Proactive IDX Scheduler Routine, verified-blocker fixes

## 1. Objective

Fix the two VERIFIED blockers from the Phase D closeout only: the
data-health `candidate=None` bug and the missing `scheduler`
CLI wiring (`idx-tick`/`simulate-day`/`status`). No repository audit,
no redesign, no Phase A/B/C changes, no Phase E work, no broker/live
execution changes.

## 2. Audit findings (before any change)

- **Blocker 1 (data-health bug):** already fixed on disk.
  `Orchestration/idx_daily_scheduler.py::_job_data_health_check()`
  already calls
  `self._freshness_policy.evaluate(candidate=last_good, now=now, last_good=last_good)`
  — not `candidate=None`. `grep -rn "candidate=None" Orchestration/`
  returns nothing. The method's own docstring (`"Phase D.1 fix: ..."`) documents this exact change as already applied. Verified
  against `Business/data_freshness_policy.py::DataFreshnessPolicy.evaluate()`'s
  documented contract: passing the last-known-good `session_scan`
  observation as `candidate` (never a fabricated value, never a
  re-stamped timestamp — `observed_at` is the observation's own
  original value) is exactly what allows `FRESH` to be reached, while
  a missing/aged observation still resolves to `MISSING`/`STALE`
  exactly as before. **No source change was needed for Blocker 1.**
- **Blocker 2 (CLI wiring):** confirmed missing.
  `main.py`'s `_run_scheduler_command()` recognized only the `tick`
  subcommand (Activation 12 Scheduler, unrelated to Phase D). No
  dispatch existed for `idx-tick`, `simulate-day`, or `status`, even
  though `app.idx_daily_scheduler` (`Orchestration.idx_daily_scheduler.IDXDailyScheduler`)
  and `app.health_audit_service` (`Services.health_audit_service.HealthAuditService`)
  were already fully built and wired into the application graph by
  `Core/composition_root.py`.

## 3. Changes made

- **`main.py` (extended only).**
  - New imports: `date`, `timedelta` (stdlib `datetime`); `POST_CLOSE_END`,
    `PRE_MARKET_OPEN`, `load_idx_market_calendar` from
    `Business.idx_market_calendar` (all pre-existing, unmodified
    constants/functions — no new calendar logic).
  - New `_print_idx_tick_result()` — prints one
    `Orchestration.idx_daily_scheduler.TickResult` verbatim (now,
    trading_date, session, and each job's attempted/outcome/detail).
  - New `_print_scheduler_status_snapshot()` — prints one
    `Services.health_audit_service.HealthSnapshot` verbatim (jobs,
    dedup_states, recent_events) — no recomputation, mirrors that
    service's own "invents nothing, computes nothing" contract.
  - New `_run_scheduler_idx_tick_command(app, argv)` — parses
    `--now ISO8601` (defaults to real current UTC time when omitted),
    calls `app.idx_daily_scheduler.tick(now)` exactly once, prints
    the result.
  - New `_run_scheduler_simulate_day_command(app, argv)` — parses
    `--date YYYY-MM-DD` (defaults to today via
    `IDXMarketCalendar.local_date`) and `--interval-minutes N`
    (default 5), then calls `app.idx_daily_scheduler.tick()`
    repeatedly at that cadence from `PRE_MARKET_OPEN` through
    `POST_CLOSE_END` on that IDX-local date. Every simulated moment is
    still an explicit, caller-supplied `now` passed straight to
    `tick()` — no internal clock, no new scheduling logic is
    introduced; this command only generates the sequence of `now`
    values an operator would otherwise pass to `idx-tick` one at a
    time.
  - New `_run_scheduler_status_command(app, argv)` — parses
    `--date YYYY-MM-DD` (optional), calls
    `app.health_audit_service.get_snapshot(trading_date=date_raw)`,
    prints it.
  - `_run_scheduler_command()` extended to dispatch `idx-tick`,
    `simulate-day`, and `status` alongside the existing `tick`
    branch. **The `tick` branch (`_run_scheduler_tick_command`) is
    byte-for-byte unchanged.**
  - No other function in `main.py` was touched. No import was
    removed. No existing dispatch branch (`report`, `scan`, `paper`,
    `account`, `orders`, `trades`, etc.) was modified.

No other file was modified. `Orchestration/idx_daily_scheduler.py`,
`Services/health_audit_service.py`, `Core/composition_root.py`,
`Business/data_freshness_policy.py`, and every Phase A/B/C file are
untouched. No broker/live execution, US/crypto/forex code was
touched. No Phase E work was started.

## 4. FILES READ

- `Orchestration/idx_daily_scheduler.py`
- `Business/data_freshness_policy.py`
- `Business/idx_market_calendar.py`
- `Services/health_audit_service.py`
- `Core/composition_root.py` (`_build_idx_daily_scheduler`,
  `_build_health_audit_service`, `ApplicationGraph` fields)
- `Database/models.py` (`SchedulerJobRun`, `NotificationDedupState`,
  `AuditEvent` field shapes, for the status printer)
- `Database/database_config.py`, `run_scheduler_migrations.py`
- `main.py` (full file, for existing CLI dispatch/arg-parsing
  conventions — `_run_scheduler_tick_command`,
  `_parse_symbol_and_flag`, the `report`/`scheduler` top-level
  dispatch block)
- `Tests/test_phase_d_idx_scheduler.py`
- `Docs/PHASE A/PHASE_A_Decision_Copilot_Closeout_Report.md` (format
  convention reused for this report)
- `.env`, `data/` (state only, not modified — a scratch copy was used
  for all CLI proof runs, see Section 7)

## 5. FILES CHANGED

- `main.py` — extended (four new functions + one extended dispatch
  function + import additions; no existing function body modified)
- `Docs/PHASE D/PHASE_D_Proactive_IDX_Routine_Closeout_Report.md` —
  **new** (this file)

## 6. TESTS

- `python Tests/test_phase_d_idx_scheduler.py`: **59/59 PASS**
  (Scenarios A–L: IDX session gating, pre-market/market-close/
  daily-review exactly-once idempotency, session-scan repeatability,
  retry/backoff, notification dedup/rate-limit, data-freshness
  degradation/recovery, restart persistence, audit persistence, no
  automatic paper order). Run both before and after the `main.py`
  change — identical result, confirming the CLI wiring touched
  nothing this suite covers.
- Regression suite (run via `python Tests/<file>.py`, all
  direct-executable, none pytest-discoverable — matches this
  repository's existing proof-script convention):
  - `test_activation12_scheduler_market_close_recap.py`: 3/3 PASS
  - `test_doctor_command.py`: 38/38 PASS
  - `test_notification_builder.py`: 35/35 PASS
  - `test_notification_dispatcher.py`: 40/40 PASS
  - `test_notification_event.py`: 31/31 PASS
  - `test_notification_manager.py`: 41/41 PASS
  - `test_stage_l28_sprint17_scheduler.py`: 40/40 PASS
  - `test_stage_l28_sprint23_scheduler_events.py`: 59/59 PASS
  - `test_stage_sprint7_step7_notification_wiring.py`: 58/58 PASS
  - `test_telegram_notification_channel.py`: 47/47 PASS
  - `test_activation6_2_notification_failure_propagation.py`: 37/37
    PASS
  - **Total: 429/429 PASS across all regression suites run, 0 fail.**

## 7. CLI PROOF

Run against a scratch copy of the database
(`/tmp/proof_investment_platform.db`, copied from
`data/investment_platform.db` and migrated with
`python run_scheduler_migrations.py`) — the real production
`data/investment_platform.db` was never written to.

- `python main.py scheduler idx-tick` — ran to completion; correctly
  reported `session=closed` for the actual current moment (a Sunday),
  no job considered (non-trading day, matches
  `IDXMarketCalendar.is_trading_day`).
- `python main.py scheduler idx-tick --now 2026-08-24T09:15:00+07:00`
  (a Monday, IDX regular session) — `session_scan` SUCCESS,
  `data_health_check` SUCCESS with `status=FRESH` (confirming Blocker
  1's fix is live, not just unit-tested: the freshness check reached
  `FRESH` immediately after a `session_scan` success in the same
  process). `yfinance`/Telegram calls correctly failed closed
  (sandbox network egress does not allow `query1/query2.finance.yahoo.com`
  or the Telegram API) — the job still completed and recorded the
  failure via the existing retry/notification-failure path; no
  traceback, no crash.
- `python main.py scheduler simulate-day --date 2026-08-24 --interval-minutes 60` — 8 ticks simulated across
  pre-market → regular → lunch_break → regular → after-hours;
  `data_health_check` correctly alternated `FRESH` during/just after
  an open-session scan and `STALE` during the pre-market and
  lunch-break gaps (age computed from the real last successful
  `session_scan` observation each time, never fabricated).
- `python main.py scheduler status --date 2026-08-24` — printed every
  `scheduler_job_runs` row, `notification_dedup_state` row, and the
  most recent `audit_events` rows for that date verbatim, matching
  what the simulate-day run above produced.
- `python main.py scheduler tick` (the pre-existing, untouched
  command) — still runs to completion: `scheduler tick: executed 4 job(s)`.

## 8. ACCEPTANCE

- [X] `python Tests/test_phase_d_idx_scheduler.py` passes: 59/59.
- [X] Data-health job evaluates the actual last-known-good
  `session_scan` observation as `candidate`, preserving its
  original timestamp — confirmed already correct in source, and
  confirmed live via CLI proof (Section 7) and the standalone
  suite's Scenario D/G.
- [X] first-ever/no observation => MISSING or explicit no-data state
  — Scenario D.
- [X] fresh real observation => FRESH — Scenario D, and live via
  `idx-tick`/`simulate-day` proof.
- [X] old observation => STALE — Scenario D, and live via
  `simulate-day` proof (pre-market/lunch-break gaps).
- [X] FRESH→STALE degradation alert works — Scenario G.
- [X] STALE/MISSING→FRESH recovery alert works — Scenario G.
- [X] dedup/rate-limit behavior remains intact — Scenario F/G, and
  `notification_dedup_state`/`audit_events` rows in the `status`
  CLI proof show `SUPPRESS_NO_CHANGE`/`SUPPRESS_RATE_LIMITED`
  logic still governing repeat alerts.
- [X] `scheduler idx-tick`, `scheduler simulate-day`, `scheduler status` all work — Section 7.
- [X] existing `scheduler tick` still works, unmodified — Section 7.
- [X] no automatic paper order — Scenario L re-confirms (no
  `PaperTradingEngine`/`OrderLifecycleService`/`ExecutionService`
  import or reference anywhere in `Orchestration/idx_daily_scheduler.py`);
  the new CLI commands call only `tick()`/`get_snapshot()`, never
  construct an `Order`/`Trade`/mutate a `Position`.
- [X] no fabricated data — `candidate`/`last_good` in the freshness
  check and every printed CLI field are read verbatim from the
  audit log / repositories, never invented or re-stamped.

## 9. EXTERNAL BLOCKER

- `yfinance` calls to `query1/query2.finance.yahoo.com` and Telegram
  Bot API calls both fail in this sandboxed environment (network
  egress allowlist does not include those hosts) — pre-existing,
  external, unrelated to this fix. `session_scan`/notification jobs
  correctly catch these failures via their existing
  try/except-and-record-FAILED path (see `_attempt()`/
  `_apply_dedup_decision()` in `idx_daily_scheduler.py`, both
  unmodified) rather than crashing the tick — this is the intended
  restart-safe behavior, not a new gap introduced by this change.

## STOP

Phase D.1 is complete. Both verified blockers are resolved (Blocker 1
was already fixed in source; Blocker 2's CLI wiring is now added).
No repository audit, redesign, Phase A/B/C, Phase E, or broker/live
execution work was started.
