# ACTIVATION 3.2 — Audit & Verification Report

**Scope of this pass:** audit the ZIP baseline (implementation already written, build green, tests not yet run, no proof behavior, not yet declared done), verify roadmap conformance, run tests, fix what's broken, produce independent proof of behavior, and only then report status.

**Status: Activation 3.2 can be declared DONE, with one open product-decision flagged below (not a defect — see "Known, honestly-documented gap").**

---

## 0. What I used as "the roadmap"

The ZIP does not contain a separate Activation 3.2 spec document (`Docs/ACTIVATION 3/` only has the 3.1 audit). In its absence I used two things as ground truth, and you should confirm there isn't a third document I'm missing:

1. The extremely explicit "LOCKED DECISION" docstring inside `Business/paper_trading_engine.py` itself (written by the previous engineer, self-documenting scope/constraints).
2. Your checklist in this conversation (idempotency, risk limit, kill switch, migration v12, pre-trade-before-Order, zero-write on failure, no silent fallback, no partial write, restart durability).

Both sources agree with each other and with what the code actually does (verified below), so I'm treating them as reliable — but flagging that I never saw an independent 3.2 spec to cross-check against.

---

## 1. Roadmap conformance audit

| Item you asked me to check | Finding |
|---|---|
| Duplicate request/idempotency — sesuai roadmap, bukan over-engineered? | **Sesuai.** One repository (`OrderIdempotencyRepository`), one table, one gate (#10). No retry queue, no distributed lock, no TTL — just check-then-reject on a primary key. Write happens *after* Trade succeeds (documented trade-off: favors "never block a legitimate retry" over "never allow a same-millisecond race," honestly disclosed in the docstring, not hidden). |
| Risk limit — mengarang business rule baru? | **Tidak.** Single rule: `quantity * requested_price <= max_order_value`, read from an env var via the *existing* `Core.config` mechanism (same one `approval_config` already uses). No new config system, no invented tiers/thresholds. |
| Kill switch — pakai komponen production yang ada? | **Ya.** `KILL_SWITCH_ENABLED` env var via the same `Core.config` singleton, injected once at composition-root build time. No new subsystem. |
| Migration v12 — aman terhadap init/restart/re-run? | **Ya, independently proven** — see Proof 1 and Proof 6 below. `CREATE TABLE IF NOT EXISTS`, registered in the single canonical `migration_registry.py`, tracked in `schema_migrations`, applied under `MigrationRunner`'s existing exclusive-lock + batch-rollback machinery (pre-existing infra, not new). |
| Pre-trade validation before Order created? | **Ya.** All 12 gates run and complete before `OrderLifecycleService.create_order()` is ever called. Read line-by-line; every gate call is `get_by_id`/`get_open_position`/`get_by_key` — no `INSERT`/`UPDATE` anywhere in the gate chain. |
| Order/Trade/Cash/Position/Portfolio zero-write on failure? | **Ya, independently proven** — Proof 2 (raw SQL byte-for-byte identical before/after two different failing gates). |
| No silent fallback? | **Confirmed.** `Core.config.get_bool/get_float` raise `ConfigurationError` on a malformed env var; they only default when the var is *absent*. No `try/except: pass` anywhere in the 3.2 code path. |
| No partial write? | **Confirmed** for the failure path (Proof 2). On the success path, Order→Trade→idempotency-key is still three independently-committed statements (Activation 3.1's audited transaction boundary is explicitly **not** changed by 3.2 — see gap below), so "partial write" in the sense of "crash mid-sequence leaves a stuck row" is still theoretically possible, exactly as 3.1 already documented and exactly as this Activation says it intentionally leaves alone. |
| Restart keeps state? | **Ya, independently proven** — Proof 5, using a brand-new `SQLiteDatabase`/`DatabaseManager`/repository graph against the same file, no shared in-memory state. |

**Out-of-roadmap changes found:** one, and it's a legitimate, well-documented bug fix, not scope creep — see §3.

---

## 2. Tests: run, not just trusted

Full suite (249 files under `Tests/`) executed directly (`python3 <file>.py`, `PYTHONPATH=.`), not just imported:

- **Before any fix:** 191 pass / 58 fail.
- I did **not** assume the 58 failures were pre-existing — I read every one that even mentioned 3.2-adjacent keywords (7 candidates), and traced each to its actual cause.
- **3 were genuine regressions caused by 3.2** (see §3) — fixed.
- **55 were pre-existing, unrelated to 3.2** — verified individually (not assumed), examples:
  - `test_stage_l123/l126/l152_*` — `TradingDecisionAgent.__init__()` missing 8–10 args. Traced to `PaperTradingSkill` (an *Orchestration*-layer component the 3.1 report explicitly identified as a different class with a similar name — it does no persistence at all) and several unrelated skills (`position_sizing_skill`, `portfolio_*`). Nothing to do with `Business.paper_trading_engine`.
  - `test_stage_l5/l6_composition_root_integration` — assert `ApplicationGraph`'s field set is a specific short historical list. The actual list contains dozens of fields from many activations *older* than 3.2 (`account_balance_service`, `manual_scan_service`, `notification_dispatcher`, etc.), proving this assertion was already broken long before 3.2 started. Not touched — rewriting stage-lockstep tests across the whole history is out of this Activation's scope, and I was not asked to true up the entire test suite's technical debt.
- **After fixes: 194 pass / 55 fail**, and I diffed the fail-lists before/after to confirm **zero new failures introduced** and **exactly the 3 intended fixes landed**.

### Core 3.2 test: `Tests/test_paper_trading_engine.py` — 79/79 PASS
Covers all 12 gates individually (each with its own row-count-based zero-write assertion, not just "an exception was raised"), the happy path (BUY/SELL), duplicate-key rejection, gate-ordering ("first match wins"), collaborator-set shape, and a restart-persistence scenario — all using a real SQLite file, not mocks.

---

## 3. Regressions found and fixed (with reasoning for each)

All three were **stale test fixtures that predate a legitimate 3.2 change**, not bugs in the 3.2 implementation itself. I fixed the tests, not the implementation, because in each case the implementation's new behavior was correct and the test's expectation was simply never updated:

1. **`Tests/test_doctor_command.py`** — `_apply_all_migrations()` helper hardcoded 6 domain migration tuples; `doctor`'s live check now expects 7 (idempotency added to the registry). Doctor logic itself was right — the fixture just didn't apply migration 12, so it correctly reported BLOCKED. Fixed by adding `IDEMPOTENCY_MIGRATIONS` to the fixture's loop.
2. **`Tests/test_init_command.py`** — two scenarios (`scenario_c_partial_migration`, `scenario_e_recovery`) hardcoded the expected final table set without `order_idempotency_keys`. Verified independently (outside the test) that `run_init()` on a clean DB correctly produces `order_idempotency_keys` via migration 12 — the table set was right, the assertion was outdated. Fixed both literals.
3. **`Tests/test_stage_sprint4_step9_paper_trading_engine_wiring.py`** — asserted `PaperTradingEngine` holds "exactly two collaborator attributes," which was Sprint 4 STEP 9's pre-3.2 contract. Activation 3.2's own module docstring explicitly LOCKS the extended 5-collaborator + 2-config-value contract, and `test_paper_trading_engine.py` (written *for* 3.2) already independently proves that exact new contract. Updated the stale assertion to match the documented, intentional extension rather than deleting the check.

**One legitimate non-test change worth flagging explicitly, found during audit** (not something I made — already in the ZIP, and I verified it was necessary and correct): `Business/execution_service.py` was changed to read `Trade.fill_price` from `Order.requested_price` instead of `Order.filled_price`. Investigated why: `Order.filled_price` is set to `0.0` at creation and nothing before `ExecutionService` ever writes a different value into it, so every trade produced through the *actual* `create_order()` → `execute_order()` chain would have silently recorded `fill_price = 0.0` regardless of the real requested price — a real latent bug that 3.1's transaction-boundary audit didn't catch because its own test fixtures bypassed `OrderLifecycleService` and injected `filled_price` directly. This fix is well-documented in the module docstring, doesn't add a new business rule, and is covered by all 40 passing cases in `test_execution_service.py`. I verified it independently in Proof 3 below (`trade.fill_price == 9500.0`, the requested price).

---

## 4. Independent proof of behavior (not the vendor's own tests)

I wrote a separate proof script (`activation_3_2_independent_proof.py`, attached) that does **not** reuse `Tests/test_paper_trading_engine.py`'s assertions — it dumps raw SQL (`sqlite3` directly against the file, bypassing the repository layer being audited) before/after each operation. Full output attached as `activation_3_2_proof_run_output.log`. Summary:

| Proof | Result |
|---|---|
| 1. Fresh `init` applies migration 12 | `applied_versions() = [1,2,3,4,5,10,11,12]`, `order_idempotency_keys` table exists, empty |
| 2. Failure path (insufficient cash, and separately risk limit) | Raw SQL state **byte-identical** before/after in both cases — zero write confirmed independently of the repository layer's own row-count helper |
| 3. Success path | Exactly 1 new `orders` row (`FILLED`), 1 new `trades` row (`fill_price = 9500.0`, matching the bug-fix in §3), 1 new `order_idempotency_keys` row. `accounts.cash` **unchanged** — see gap below |
| 4. Idempotency | Same key resubmitted → rejected, raw SQL state unchanged, zero additional writes |
| 5. Restart | Connection closed, brand-new `SQLiteDatabase`/`DatabaseManager` opened against the same file → Order still `FILLED`, Trade still present |
| 6. Migration re-run | Re-applying the full migration set against an already-migrated DB → empty "newly applied" list, no duplicate `schema_migrations` rows, safe no-op |

Exit code `0`, all assertions passed.

---

## 5. Known, honestly-documented gap — needs your decision, not mine

Verified independently (Proof 3, and by grepping the whole repo for `.apply_trade(` outside `Tests/`): **a successful `submit_order()` still does not update `Account.cash` or `Position`.** `AccountBalanceService`/`PositionManager` are constructed in `composition_root.py` but `apply_trade()` is called from nowhere in production — exactly what Activation 3.1's audit already found, and Activation 3.2's docstring explicitly says it does **not** change that boundary ("does NOT change Activation 3.1's audited transaction boundary in any way").

This is consistent and honestly disclosed, not a hidden defect — but it means: after Activation 3.2, a paper BUY order will validate correctly, get filled, and be recorded as a Trade, while the account's cash balance silently stays exactly where it was. If your expectation for "Activation 3.2 done" includes cash/position actually moving, that's **not yet built** — it would be a new Activation (wiring `AccountBalanceService.apply_trade()`/`PositionManager.apply_trade()` into the execution path, likely alongside finally giving this chain a real transaction boundary, which 3.1 already flagged as missing). I did not build this because it's outside what either the docstring or your checklist asked for this Activation — flagging so you can decide rather than deciding for you.

---

## 6. Files changed in this pass

- `Tests/test_doctor_command.py` — migration fixture updated to include idempotency migrations (see attached `patched_tests/`)
- `Tests/test_init_command.py` — two stale expected-table-set literals updated
- `Tests/test_stage_sprint4_step9_paper_trading_engine_wiring.py` — stale collaborator-count assertion updated to match the documented Activation 3.2 contract
- No production code was touched — the implementation itself was already correct where I found it; only stale test fixtures needed updating.

## 7. What I did not do (explicitly out of scope, flagging rather than silently skipping)
- Did not touch the 55 pre-existing unrelated test failures (older technical debt, unrelated subsystems).
- Did not implement cash/position wiring (§5) — that's a scope decision for you.
- Did not locate an independent Activation 3.2 spec document beyond what's in the code itself — if one exists outside this ZIP, worth a second pass against it.
