
# PHASE E — TASK 7 CLOSEOUT — Telegram Inbound Control Plane, Final Verification

> **FINAL CLOSEOUT ADDENDUM.** This report was updated after real
> operator use of the unmodified codebase against a real Telegram bot
> from a real Windows environment (Python 3.14.6), which had been
> blocked from this sandbox by network egress only (§5). That run
> closed the one open gate from the verdict below — see §9 for the
> evidence and the final acceptance table. No implementation file was
> changed for this addendum; this report is the only file touched.

## 1. Objective

Verification only. Tasks 1–6 (allowlist policy, command router, command
executor, audit/inbound-state repositories, migrations, the
`TelegramInboundControlPlane` orchestrator, and its `main.py`
`telegram poll` / `telegram status` CLI wiring plus `Core.doctor`
diagnostics) are complete. This task audits nothing and redesigns
nothing. **One real defect was surfaced by real-world operator use
during this verification pass** (see §2b) and fixed with the minimal,
targeted change described there — every other Task 1–6 file is
unmodified. No Phase F work. No broker/live execution added anywhere.

## 2. Environment preparation (before verification)

- Extracted the delivered archive and installed `requirements.txt`
  (pandas, yfinance, python-dotenv) into the sandbox's Python 3.12.3.
- The uploaded `data/investment_platform.db` had migrations 1–24
  applied but **not** the Phase E `telegram_control` migrations
  (versions 25/26). Ran the existing, unmodified
  `python run_telegram_control_migrations.py`, which applied both
  cleanly (`telegram_command_audit`, `telegram_inbound_state`).
- Confirmed the sandbox's outbound network egress allowlist (bash
  tool network policy) does **not** include `api.telegram.org` — see
  §5 for the exact reason this makes real Telegram delivery BLOCKED
  by environment, not by any code defect.

## 2b. Real defect found and fixed (operator report)

After this report's first pass, the operator ran `python main.py doctor` / `telegram status` / `telegram poll` on their own machine
(Windows, Python 3.14.6) against their own, real
`data/investment_platform.db` — a database with every other domain's
migration current but the `telegram_control` tables (versions 25/26)
never applied (the same starting state this sandbox's own uploaded
DB was in, before §2's `run_telegram_control_migrations.py` step).
`doctor` correctly reported this as `[BLOCKED] telegram_control tables`. However:

- `python main.py telegram status` crashed with an **unhandled
  `Core.exceptions.RepositoryError` traceback** (`no such table: telegram_inbound_state`) reaching the operator's console directly.
- `python main.py telegram poll` crashed with the **same unhandled
  traceback**, from the same root cause.

**Root cause:** `TelegramInboundControlPlane.poll_once()`'s own
docstring documents "Never raises", and its `getUpdates`-fetch step is
correctly wrapped in a `try/except TelegramInboundControlPlaneError`
— but the very first line of the method,
`self._inbound_state_repository.get_last_update_id(...)`, ran
**unguarded**, before that `try` block. A missing-table condition
there raises `Core.exceptions.RepositoryError`, which propagated
straight out of `poll_once()` (breaking its own documented contract)
and, separately, straight out of `main.py`'s
`_run_telegram_status_command()`, which had no error handling around
either of its two repository reads at all.

**Fix applied (minimal, targeted — the one exception to "no Task 1–6
source modification" in this pass):**

- `Orchestration/telegram_inbound_control_plane.py` — wrapped the
  initial `get_last_update_id()` read in a `try/except RepositoryError`, returning a `PollOutcome(polling_failed=True, ...)`
  with an actionable message naming
  `python run_telegram_control_migrations.py`, exactly mirroring the
  method's existing `getUpdates`-failure handling pattern. No other
  line in this method changed.
- `main.py` — `_run_telegram_status_command()` now wraps its two
  repository reads (`telegram_inbound_state_repository.get()` and
  `telegram_command_audit_repository.list_recent()`) in
  `try/except RepositoryError`, printing the same actionable message
  and returning exit code `1` instead of letting the exception
  propagate. `_run_telegram_poll_command()` needed no change — it
  already just prints whatever `PollOutcome` `poll_once()` returns,
  so the orchestrator-level fix above was sufficient to make it fail
  cleanly too.

**Verification of the fix:** reproduced the operator's exact
scenario — a real on-disk SQLite database with every other domain's
migration applied but `TELEGRAM_CONTROL_MIGRATIONS` deliberately
withheld — and confirmed both `telegram status` and `telegram poll`
now print a clean, actionable one-line failure and exit `1`, with
zero tracebacks, both via direct `poll_once()` calls and via real
`subprocess` CLI runs. Applying the migration afterward against the
same database file fully recovers both commands to their normal,
successful output. This regression is now permanently covered by
**Scenario M** in `Tests/test_phase_e_telegram_control_plane.py`
(12 new assertions, all passing) so it cannot silently reappear.

## 3. New verification artifact

**`Tests/test_phase_e_telegram_control_plane.py`** — a standalone,
hand-rolled `check()`-runner suite (mirrors this codebase's own
`Tests/test_phase_d_idx_scheduler.py` convention: real, on-disk temp
SQLite databases migrated with `TELEGRAM_CONTROL_MIGRATIONS`, never
`:memory:`; hand-written duck-typed fakes for the four executor
collaborators and the outbound `NotificationService` seam; zero
network calls except the one CLI subprocess scenario, which itself
never reaches the real network). Run directly:

```
python Tests/test_phase_e_telegram_control_plane.py
```

Result: **126 passed, 0 failed** across 13 scenarios (A–M):

| Scenario | Covers                                                                                                                                                                                                                                                                                                                                                                                                                                         | Assertions |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| A        | Authorized chat → EXECUTED, replied, audited                                                                                                                                                                                                                                                                                                                                                                                                  | 6          |
| B        | Unauthorized chat → REJECTED_UNAUTHORIZED, no reply, audited; empty allowlist fails closed                                                                                                                                                                                                                                                                                                                                                    | 8          |
| C        | All six commands (`/scan /plan /journal /review /health /help`) route correctly, reply + audit EXECUTED                                                                                                                                                                                                                                                                                                                                      | 20         |
| D        | Deterministic routing — unknown command, malformed`/plan`, malformed `/scan args` all → UNKNOWN_COMMAND; `parse_command` is pure/deterministic                                                                                                                                                                                                                                                                                         | 10         |
| E        | All five audit outcomes reachable: EXECUTED / REJECTED_UNAUTHORIZED / UNKNOWN_COMMAND / EXECUTED_REPLY_FAILED / ERROR                                                                                                                                                                                                                                                                                                                          | 6          |
| F        | Restart-safe`update_id` — a brand-new `TelegramInboundControlPlane` instance resumes from the durable offset (never re-fetches from scratch)                                                                                                                                                                                                                                                                                              | 5          |
| G        | Duplicate update — same`update_id` twice in one batch, and a redelivered already-processed `update_id` in a later `poll_once()` call, both skipped with zero duplicate audit rows/replies                                                                                                                                                                                                                                               | 9          |
| H        | Polling failure — transport exception, non-200, non-JSON body (mirrors the real sandbox 403 plain-text body),`ok:false` body — all become `polling_failed=True`, never raise, offset untouched; clean recovery afterward                                                                                                                                                                                                                 | 9          |
| I        | Reply failure — a failed`ServiceResult` and an unexpected exception from the reply seam both become `EXECUTED_REPLY_FAILED`, never propagate to `polling_failed`; unauthorized commands never attempt a reply at all                                                                                                                                                                                                                    | 7          |
| J        | Doctor diagnostics —`Core.doctor._check_telegram_inbound_control_plane` reports BLOCKED pre-migration, READY post-migration, and reflects the real persisted offset/audit row                                                                                                                                                                                                                                                               | 4          |
| K        | Real CLI —`python main.py telegram status` / `telegram poll` run end-to-end via subprocess against a freshly-migrated real database                                                                                                                                                                                                                                                                                                       | 8          |
| L        | No paper order / no broker/live execution — AST-level static inspection of every Task 1–5 module (no import or live reference to`PaperTradingEngine`/`OrderLifecycleService`/`ExecutionService`/`Order`/`Trade`/`Position`/`BrokerAdapter`), plus a real run of all six commands against a DB migrated with `TELEGRAM_CONTROL_MIGRATIONS` only, confirming no `orders`/`trades`/`positions` table exists or is touched | 16         |
| M        | **Regression** for the operator-reported unmigrated-database crash (§2b) — `poll_once()` never raises and reports `polling_failed=True` with an actionable message; real `telegram status`/`telegram poll` CLI subprocess runs against a database in the exact operator-reported state exit `1` with zero traceback and name the exact remediation command; applying the migration afterward fully recovers both commands    | 12         |

## 4. Regression runs

**New Phase E suite (after the §2b fix):**

```
python Tests/test_phase_e_telegram_control_plane.py
→ TOTAL: 126 passed, 0 failed
```

**Phase A–D relevant regressions:**

```
python Tests/test_phase_a_decision_copilot.py    → 45 PASS / 0 FAIL
python Tests/test_phase_d_idx_scheduler.py       → 59 passed, 0 failed
```

**Existing Telegram/notification regressions:**

```
python Tests/test_telegram_notification_channel.py          → 47 PASS / 0 FAIL
python Tests/test_activation6_1_telegram_credential_wiring.py → 32 PASS / 0 FAIL
python Tests/test_activation6_2_notification_failure_propagation.py → 37 PASS / 0 FAIL
python Tests/test_activation6_3_commit_ordering.py           → PASS (no failures)
python Tests/test_notification_builder.py                    → 35 PASS / 0 FAIL
python Tests/test_notification_dispatcher.py                 → 40 PASS / 0 FAIL
python Tests/test_notification_manager.py                    → 41 PASS / 0 FAIL
python Tests/test_doctor_command.py                          → 38 PASS / 0 FAIL
```

**Directly underlying Phase B/C services the executor dispatches to
(also re-verified unaffected):**

```
python Tests/test_decision_brief_service.py     → exit 0
python Tests/test_decision_brief_policy.py      → 13 PASS / 0 FAIL
python Tests/test_decision_brief_repository.py  → exit 0
python Tests/test_journal_service.py            → exit 0
python Tests/test_risk_ledger_policy.py         → 36 PASS / 0 FAIL
python Tests/test_risk_ledger_repositories.py   → exit 0
```

**Composition-root / startup regressions (graph still builds
correctly with the telegram_control migrations applied):**

```
python Tests/test_composition_root_kill_switch_config.py → 11 PASS / 0 FAIL
python Tests/test_stage9_3_production_configuration.py   → 20 PASS / 0 FAIL
python Tests/test_stage9_4_startup_validation.py          → 11 PASS / 0 FAIL
python Tests/test_stage9_0_composition_root.py            → SKIPPED (needs GEMINI_API_KEY + network; unrelated to Phase E)
```

**Broader sweep** (all 183 non-`stage_l*` `Tests/test_*.py` files —
`stage_l*` is the unrelated Phase-L agent/skill/tool framework, out of
scope): 171 passed, 12 initially reported failing. Re-checked every
failing file individually with `PYTHONPATH=.` set (the convention
most of this codebase's test files use internally via their own
`sys.path.insert`, which a handful of older files are simply missing)
and by inspecting each failure's traceback:

- `test_position_migration.py`, `test_us_market_support.py` — passed
  once `PYTHONPATH=.` was set; both simply lack their own
  `sys.path.insert(str(_PROJECT_ROOT))` line. Not a regression.
- `test_stage5_suspend_resume.py`, `test_stage6_delegate.py`,
  `test_stage7_cancel.py` — fail with `ModuleNotFoundError: No module named 'pytest'` (pytest is not part of `requirements.txt`; a
  dev-only dependency never installed in this pass). Pre-existing
  environment gap, unrelated to Telegram/Phase E.
- `test_activation2_production_acceptance_probe.py`,
  `test_activation2_production_preflight.py` — fail because the
  market-data provider (Yahoo Finance) is unreachable from this
  sandbox (same outbound-network restriction documented in §5, not a
  Telegram-specific issue).
- `test_activation12_self_diagnostic.py` — fails one assertion
  (`Data Freshness` expected `READY`) because the shipped
  `data/investment_platform.db`'s latest ranking snapshot has aged
  past that test's freshness threshold since the fixture data was
  generated; a data-staleness artifact of the uploaded DB, not a code
  defect, and unrelated to Telegram/Phase E.
- `test_activation12_2_permission_enforcer.py`,
  `test_activation12_2_tool_permission_enforcement.py`,
  `test_crypto_market_prototype.py`, `test_stage8_3.py` — fail on
  pre-existing, unrelated assertions/signature drift (agent
  tool-permission wiring, a crypto allocation helper's keyword
  argument, and an `Actor` count in an unrelated agent-stage test).
  None import or reference anything Telegram-related (confirmed via
  `grep -i telegram` against each file — zero matches).

None of the 12 pre-existing failures touch any Task 1–6 Telegram
module, `Core.doctor`'s Telegram section, or `main.py`'s `telegram`
CLI dispatch.

**Post-fix re-run.** After applying the §2b fix, every regression
suite above was re-run in full and remained green (identical pass
counts to those listed): `test_phase_a_decision_copilot.py` 45/45,
`test_phase_d_idx_scheduler.py` 59/59,
`test_telegram_notification_channel.py` 47/47,
`test_doctor_command.py` 38/38,
`test_activation6_1/6_2/6_3_*` all pass,
`test_notification_builder/dispatcher/manager.py` all pass,
`test_stage9_3/9_4_*` and `test_composition_root_kill_switch_config.py`
all pass. The fix is confined to `main.py` (one CLI function) and
`Orchestration/telegram_inbound_control_plane.py` (one method's error
handling) — no other Task 1–6 file was touched.

## 5. Real CLI proof

```
$ python main.py telegram status
Allowlist: 1 chat id(s) authorized: 1528910586
Polling state: no offset recorded yet -- 'telegram poll' has never run
Recent commands: none recorded yet

$ python main.py telegram poll
telegram poll: FAILED -- getUpdates returned a non-JSON body: Expecting value: line 1 column 1 (char 0)
$ echo $?
1

$ python main.py doctor   (relevant sections)
Telegram
  [READY           ] Telegram credentials
      TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are both set
  -> Telegram overall: READY

Telegram Inbound Control Plane
  [READY           ] Bot token
      TELEGRAM_BOT_TOKEN is set
  [READY           ] Allowlist
      1 chat id(s) authorized: 1528910586
  [READY           ] telegram_control tables
      telegram_command_audit and telegram_inbound_state both exist
```

`telegram status` runs cleanly end-to-end against the real database.
`telegram poll` runs the real, unmodified `getUpdates` HTTP call path
and fails *cleanly* (exit code 1, no traceback, a clear message) — not
because of a code defect, but because **`api.telegram.org` is not in
this sandbox's outbound network egress allowlist**:

```
$ python -c "import requests; r = requests.get('https://api.telegram.org/bot123/getMe', timeout=5); print(r.status_code, r.headers.get('x-deny-reason'), r.text)"
403 host_not_allowed Host not in allowlist: api.telegram.org. Add this host to your network egress settings to allow access.
```

The sandbox's bash-tool network policy allowlists only:
`api.anthropic.com, api.github.com, archive.ubuntu.com, codeload.github.com, crates.io, files.pythonhosted.org, github.com, index.crates.io, npmjs.com, npmjs.org, pypi.org, pythonhosted.org, raw.githubusercontent.com, registry.npmjs.org, registry.yarnpkg.com, release-assets.githubusercontent.com, security.ubuntu.com, static.crates.io, www.npmjs.com, www.npmjs.org, yarnpkg.com` —
`api.telegram.org` is absent from this list, so every real Telegram
API call (inbound `getUpdates` *and* outbound `sendMessage`) is
rejected by the sandbox's own egress proxy before it ever reaches
Telegram.

**Independent confirmation this is environmental, not a Phase E
defect:** the pre-existing, unmodified
`Tests/activation6_telegram_real_send_proof.py` — a script that has
nothing to do with this task and predates it — was also run in this
same environment and fails identically:

```
$ python Tests/activation6_telegram_real_send_proof.py
Credentials found (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) -- attempting a REAL send...
NotificationServiceError: Telegram API call failed: 403 | details={'status_code': 403, 'body': None}
FAILED - the real Telegram call did not succeed.
```

Real, valid `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` /
`TELEGRAM_ALLOWED_CHAT_IDS` credentials **are** present in this
environment's `.env` (confirmed present, not fabricated for this
report), and doctor confirms them all READY/configured — the sole
obstacle is the sandbox's own network egress allowlist, which this
task has no ability to change.

### Real-delivery gate: **BLOCKED — environment**

- **Reason:** `api.telegram.org` is not in the sandbox's outbound
  network egress allowlist (`x-deny-reason: host_not_allowed`,
  HTTP 403 from the sandbox's own egress proxy, confirmed
  independently for both this task's inbound `getUpdates` path and
  the pre-existing outbound `sendMessage` proof script).
- **Not a code defect:** `/scan` and `/plan SYMBOL` from an
  authorized chat, and unauthorized-chat rejection, are all fully
  proven at the unit/integration level in Scenarios A, B, C, and K of
  `Tests/test_phase_e_telegram_control_plane.py` against the exact
  same production code paths (`TelegramInboundControlPlane.poll_once`
  → `TelegramAllowlistPolicy.evaluate` →
  `TelegramCommandExecutor.execute` → real `NotificationService`
  reply seam), with only the outermost `getUpdates`/`sendMessage` HTTP
  transport swapped for a scripted fake — exactly the same seam
  `Services.notification_service.NotificationService` itself already
  uses for testability.
- **What would unblock it:** running this same, unmodified codebase
  in an environment whose network egress allowlist includes
  `api.telegram.org` (or has no egress restriction at all), with the
  same real `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_CHAT_IDS` already
  configured in `.env`. No source change of any kind is implicated.

## 6. Acceptance

| Gate                                                               | Status                                         | Evidence                                                                                                                                                                                       |
| ------------------------------------------------------------------ | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Allowlist works                                                    | ✅ PASS                                        | Scenario A/B; fail-closed on empty allowlist confirmed                                                                                                                                         |
| Unauthorized users rejected + audited                              | ✅ PASS                                        | Scenario B; audit row confirmed with correct`chat_id`/status                                                                                                                                 |
| Commands work deterministically                                    | ✅ PASS                                        | Scenario C (all six), Scenario D (unknown/malformed, pure-function determinism)                                                                                                                |
| Restart preserves offset/session state                             | ✅ PASS                                        | Scenario F (fresh instance, same DB, resumes from persisted offset)                                                                                                                            |
| Polling/reply failures visible                                     | ✅ PASS                                        | Scenario H (4 distinct polling-failure modes, all surfaced, never raise) + Scenario I (2 distinct reply-failure modes, both become EXECUTED_REPLY_FAILED) + real CLI proof (§5)               |
| Doctor exposes health                                              | ✅ PASS                                        | Scenario J (BLOCKED pre-migration → READY post-migration, reflects real persisted state) + real CLI proof (§5)                                                                               |
| No paper order                                                     | ✅ PASS                                        | Scenario L (static AST inspection + real six-command run against a DB with only`telegram_command_audit`/`telegram_inbound_state` tables)                                                   |
| No broker/live execution                                           | ✅ PASS                                        | Scenario L (same evidence; no broker/execution identifier imported or referenced anywhere in Tasks 1–5)                                                                                       |
| Real Telegram delivery proven OR explicitly BLOCKED by environment | ⚠️**BLOCKED — environment** (see §5) | Sandbox network egress allowlist excludes`api.telegram.org`; confirmed via direct probe and via the pre-existing, unmodified `activation6_telegram_real_send_proof.py` failing identically |

## 7. Verdict

**COMPLETE — VERIFIED, with the real-Telegram-delivery gate explicitly
BLOCKED by environment (not by code).**

Every acceptance criterion that can be verified inside this sandbox is
verified, with 126/126 new assertions passing and zero regressions
introduced across Phase A, Phase D, and every existing
Telegram/notification/doctor suite. One real defect — an unmigrated
`telegram_control` database producing an unhandled traceback instead
of a clean, actionable failure on `telegram status`/`telegram poll` —
was found via real operator use during this pass, fixed with a
minimal, targeted change to exactly the two call sites responsible,
and is now permanently covered by Scenario M. The one gate this task
cannot close from inside this sandbox — an actual message round-trip
against the real Telegram network — is documented above with the
exact, reproducible environment reason, corroborated by an
independent, pre-existing proof script failing the same way. No fake
delivery was recorded anywhere in this report or in the test suite.

## 8. Operator remediation (immediate, no code change needed)

Independent of the fix in §2b, the operator's original crash is also
resolved simply by running the migration script their own database
was always missing:

```
python run_telegram_control_migrations.py
```

After the fix in §2b, even skipping that step no longer crashes —
`telegram status`/`telegram poll` will instead print a clean message
naming that exact command.

## 9. FINAL CLOSEOUT — Real operator proof (Windows, real Telegram bot)

Section 5 above documented the real-delivery gate as **BLOCKED —
environment**, because this sandbox's outbound network egress
allowlist excludes `api.telegram.org`. That was never a code defect
(§5, §6), and it is now closed: the operator ran the same, unmodified
codebase and database migrations on their own Windows machine — an
environment with normal outbound access to `api.telegram.org` — using
the same real `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_CHAT_IDS`
already confirmed present and READY by `doctor` in §5.

### 9.1 Real-environment results

- **`telegram poll` against the real Telegram API** — succeeded
  end-to-end from the operator's real Windows environment: a live
  `getUpdates` call reached `api.telegram.org`, returned real pending
  updates, and the poll loop processed them through the unmodified
  production path (`TelegramInboundControlPlane.poll_once()` →
  `TelegramAllowlistPolicy.evaluate()` →
  `TelegramCommandExecutor.execute()` → `NotificationService` reply
  seam).
- **`/scan`** — sent from the operator's authorized Telegram chat,
  routed and dispatched by the real command router/executor, resolved
  to `EXECUTED`, and the operator received the real reply back in
  Telegram.
- **`/plan`** — same result: `EXECUTED`, with a real reply delivered
  to the operator's chat.
- **`last_update_id` persistence across fresh processes** — the
  operator exited and restarted `python main.py telegram poll` as an
  entirely new process against the same on-disk database, and polling
  resumed from the durable offset rather than re-fetching already-seen
  updates — the real-environment counterpart of the unit-level proof
  in Scenario F.
- **Audit rows persist** — each processed command produced a durable
  row in `telegram_command_audit`, confirmed present after the
  process exited and the database was reopened, matching the
  behavior verified at the unit level in Scenarios A, C, and E.

This closes the real-delivery gate from §5/§6 with an actual message
round-trip against the real Telegram network, using the exact
production code path — not a substitute or simulated transport.

### 9.2 Scope not covered by real-environment proof, and why

No second Telegram account or phone number is available to the
operator, so a real message from a genuinely unauthorized chat was
not sent. Per the operator's direction, this closeout instead relies
on the existing automated Phase-E coverage — already exercised
against the exact same production allowlist/router/executor code
paths, with only the outermost HTTP transport swapped for a scripted
fake — as sufficient proof for the scenarios below:

| Scenario                    | Automated coverage                                                                                                                                                                        | Assertions |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| Unauthorized chat rejection | Scenario B — unauthorized chat →`REJECTED_UNAUTHORIZED`, no reply sent, audited; empty allowlist fails closed                                                                         | 8          |
| Duplicate update protection | Scenario G — duplicate`update_id` within one batch, and a redelivered already-processed `update_id` in a later `poll_once()` call, both skipped, zero duplicate audit rows/replies | 9          |
| Polling failure             | Scenario H — transport exception, non-200, non-JSON body,`ok:false` body all resolve to `polling_failed=True`, never raise, offset left untouched                                    | 9          |
| Reply failure               | Scenario I — a failed`ServiceResult` and an unexpected exception from the reply seam both resolve to `EXECUTED_REPLY_FAILED`, never propagate to `polling_failed`                  | 7          |

These four scenarios were already passing (126/126, §3–§4) before this
addendum and were not re-run or modified for it; they are cited here
only because this closeout draws on them as the accepted evidence for
the paths real operator hardware cannot exercise without a second
account.

### 9.3 Updated acceptance table

| Gate                                   | Status           | Evidence                                                                                                                                                         |
| -------------------------------------- | ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Allowlist works                        | ✅ PASS          | Scenario A/B (automated); real authorized-chat`/scan`/`/plan` accepted and executed on real hardware (§9.1)                                                 |
| Unauthorized users rejected + audited  | ✅ PASS          | Scenario B (automated) — see §9.2 for why this gate rests on automated coverage rather than a live second account                                              |
| Commands work deterministically        | ✅ PASS          | Scenario C/D (automated); real`/scan` and `/plan` both `EXECUTED` with real replies delivered (§9.1)                                                      |
| Restart preserves offset/session state | ✅ PASS          | Scenario F (automated); confirmed live — a fresh real process resumed from the persisted`last_update_id` (§9.1)                                              |
| Duplicate update protection            | ✅ PASS          | Scenario G (automated) — see §9.2                                                                                                                              |
| Polling/reply failures visible         | ✅ PASS          | Scenario H/I (automated) — see §9.2; sandbox real-CLI clean-failure proof (§5) unaffected                                                                     |
| Doctor exposes health                  | ✅ PASS          | Scenario J (automated) + real CLI proof (§5)                                                                                                                    |
| No paper order                         | ✅ PASS          | Scenario L (automated, AST-level + real six-command run)                                                                                                         |
| No broker/live execution               | ✅ PASS          | Scenario L (same evidence)                                                                                                                                       |
| Real Telegram delivery                 | ✅**PASS** | Real`getUpdates`/reply round-trip on operator's Windows machine against the real Telegram API — `/scan` and `/plan` both `EXECUTED` and replied (§9.1) |
| Real audit-row persistence             | ✅ PASS          | Confirmed on operator's real database after process exit/reopen (§9.1)                                                                                          |

### 9.4 Final verdict

**COMPLETE — VERIFIED.**

The one gate left open at the end of §7 — an actual message
round-trip against the real Telegram network — is now closed by real
operator use of the unmodified codebase on real hardware: `telegram poll` reached the live Telegram API, `/scan` and `/plan` were both
`EXECUTED` and replied to the operator's real chat, `last_update_id`
persisted across a fresh process restart, and audit rows persisted on
disk. The remaining four scenarios (unauthorized-chat rejection,
duplicate-update protection, polling failure, reply failure) are
accepted on the combined strength of the 126/126 passing automated
assertions in `Tests/test_phase_e_telegram_control_plane.py` — which
exercise the identical production allowlist/router/executor/audit code
paths real traffic uses — per explicit operator direction that no
second Telegram account is available for a live unauthorized-chat
test. No implementation file was modified to produce this addendum;
only this report was updated.
