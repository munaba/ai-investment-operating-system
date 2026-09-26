# PHASE_I_GATE3.1_PLAN.md

# Phase I Gate 3.1 — UTC-Aware Datetime Normalization (Bugfix)

Status: **PLAN — AWAITING AUDIT. No code written.**

---

## 1. Goal

Fix an empirically discovered bug in `Orchestration/decision_copilot.py`:
naive datetimes supplied as `since`/`until` cause
`TypeError: can't compare offset-naive and offset-aware datetimes`.

Gate 3.1 restores the fail-closed promise Gate 1/2 established
("unparseable bound → `DATA_ERROR`") by removing the crash class
entirely: **no input may ever escape as an unhandled `TypeError`**.

---

## 2. The Bug, As Measured

### 2.1 Root Cause (grep-verified)

Database timestamps are **UTC-aware** strings with explicit offset:

```text
$ grep -n "decided_at =" Services/journal_service.py
Services/journal_service.py:118:    decided_at = datetime.now(timezone.utc).isoformat()

$ sqlite3 data/investment_platform.db "SELECT scan_time FROM ranking_snapshots LIMIT 1"
2026-08-22T08:06:26.024842+00:00
```

`datetime.fromisoformat("2026-09-01")` yields a **naive** datetime
(`tzinfo is None`). Comparing it to an aware one always raises
`TypeError`. Confirmed directly:

```text
raw scan_time from DB      : '2026-08-22T08:06:26.024842+00:00'
parsed -> tzinfo            : UTC (AWARE)
user since "2026-09-01"     -> tzinfo: None (NAIVE)
COMPARISON RAISES           : TypeError: can't compare offset-naive and offset-aware datetimes
```

### 2.2 Failure Surface — Measured, Not Assumed

My first probe was **wrong** and I am correcting it. I claimed earlier
that `patterns` was merely "hidden because `journal_entries=0`". That
is false. I ran a full combo probe
(`scratch/gate31_probe.py`, 13 cases against the real skill):

| # | Method | Bounds | DB row | Result |
|---|--------|--------|--------|--------|
| 1 | patterns | naive | naive | `SUCCESS` count=2 |
| 2 | patterns | naive | **aware** | `INSUFFICIENT_DATA` ← **SILENT WRONG ANSWER** |
| 3 | patterns | aware | aware | `SUCCESS` count=1 |
| 4 | patterns | mixed (naive since, aware until) | aware | `DATA_ERROR` |
| 5 | patterns | `"not-a-date"` | — | `DATA_ERROR` ✓ |
| 6 | evidence | none | aware | `SUCCESS` count=2 |
| 7 | evidence | naive | **aware** | **CRASH** `TypeError` @ `decision_copilot.py:183` |
| 8 | evidence | aware | aware | `SUCCESS` count=1 |
| 9 | evidence | mixed | aware | **CRASH** `TypeError` @ `decision_copilot.py:168` |
| 10 | evidence | naive | naive | `SUCCESS` count=1 |
| 11 | evidence | `"not-a-date"` | — | `DATA_ERROR` ✓ |
| 12 | evidence | since>until | — | `DATA_ERROR` ✓ |

**Two distinct failure classes, not one:**

- **Class A — hard crash** (`evidence` only): `TypeError` escapes to
  the CLI, printing a raw traceback. Violates fail-closed.
- **Class B — silent wrong answer** (`patterns` only): the `TypeError`
  at L100-101 is *inside* `except (ValueError, TypeError,
  AttributeError)`, so the row is silently **skipped** via `continue`.
  The operator gets `INSUFFICIENT_DATA` — an authoritative-sounding
  status — when the truth is "your date filter crashed on 40 rows".

Class B is the more dangerous one: it is invisible, and
`INSUFFICIENT_DATA` is a canonical non-action status that a downstream
operator could reasonably read as "there is no data".

Class B is currently **latent in production** only because
`journal_entries` happens to be 0 rows. The moment any journal entry is
recorded (via the normal `JournalService.record` path, which writes
aware UTC), every naive-bound `patterns` call silently returns
`INSUFFICIENT_DATA` regardless of actual data. Existing tests do not
catch it because all their fixtures use naive bounds + naive rows.

### 2.3 Why this is a real defect, not a cosmetic one

`AGENTS.md`: *"Evidence before a plan — a trade plan needs sourced
evidence and timestamps."* `INSUFFICIENT_DATA` is one of the eight
canonical statuses in the roadmap. Returning it from a comparison
failure is a fabricated status, which `AGENTS.md` forbids:
*"No fabricated data, ever — if evidence is missing, return an
explicit status/sentinel, never a plausible-looking default."*
A status derived from a swallowed exception is exactly that.

---

## 3. Scope

### 3.1 In Scope (single file)

`Orchestration/decision_copilot.py` — unlocked for this gate only.

### 3.2 Out of Scope

- `main.py` — unaffected; the bug is below the CLI.
- `Core/composition_root.py`, `Orchestration/capability.py`,
  `skill_registry.py` — stay locked.
- All 7 other locked files — stay locked.
- No new dependency (`timezone` is `datetime` stdlib).
- No signature change. No output-key change. No new status value.

### 3.3 Unlocking Discipline

Per your instruction #4: `decision_copilot.py` is opened **for this
specific fix only**, and re-locked (md5 re-captured) immediately after
the commit. Gate 3.1 does not permanently revoke the lock.

---

## 4. The Fix

### 4.1 One module-level helper (single source of truth)

```python
from datetime import datetime, timezone

def _parse_utc_aware(raw: Any) -> datetime:
    """Parse an ISO-8601 string into a **tz-aware UTC** datetime.

    Database timestamps (``scan_time``, ``decided_at``) are UTC-aware
    ISO strings with an explicit offset. A bound supplied without one
    (e.g. ``"2026-09-01"``) parses to a naive datetime, and comparing
    naive against aware always raises ``TypeError``. Naive input is
    therefore interpreted as UTC, which is exactly what every writer in
    this codebase already does (``datetime.now(timezone.utc).isoformat()``).

    Raises ``ValueError``/``TypeError`` on unparseable input; callers
    already convert those into an explicit ``DATA_ERROR``.
    """
    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
```

`timezone` is stdlib; no new dependency.

### 4.2 The 7 Call Sites (grep-verified line numbers)

```text
$ grep -n "since_dt\|until_dt\|scan_dt\|decided_dt" Orchestration/decision_copilot.py
80:            since_dt = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
81:            until_dt = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
100:            decided_dt = datetime.fromisoformat(entry.decided_at.replace("Z", "+00:00"))
158:                since_dt = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
164:                until_dt = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
180:            scan_dt = datetime.fromisoformat(str(snap.scan_time).replace("Z", "+00:00"))
```

| Site | Method | Line | Change |
|------|--------|------|--------|
| 1 | `analyze_historical_patterns` | 80 | `since_dt = _parse_utc_aware(since)` |
| 2 | `analyze_historical_patterns` | 81 | `until_dt = _parse_utc_aware(until)` |
| 3 | `analyze_historical_patterns` | 100 | `decided_dt = _parse_utc_aware(entry.decided_at)` |
| 4 | `analyze_evidence_profile` | 158 | `since_dt = _parse_utc_aware(since)` |
| 5 | `analyze_evidence_profile` | 164 | `until_dt = _parse_utc_aware(until)` |
| 6 | `analyze_evidence_profile` | 180 | `scan_dt = _parse_utc_aware(snap.scan_time)` |
| 7 | `analyze_evidence_profile` | 227 | `dt = _parse_utc_aware(snap.scan_time)` (min/max — see §4.3) |

**Out of the 7, how many are strictly necessary for the reported crash?** Sites 1, 2, 4, 5
(bounds) plus 3 and 6 (row values) — all 6, because a single naive
value on *either* side of a comparison raises. Fixing only the bounds
leaves Class A crashing (naive bound vs aware row); fixing only the
rows leaves it crashing too (aware bound vs naive row). All 6 or
nothing. Site 7 is a 7th, separate call of the same parse (see §4.3).

### 4.3 Seventh Site — CONFIRMED IN SCOPE by operator (2026-09-26)

`decision_copilot.py:227` parses `snap.scan_time` **again**, inside the
min/max block, and compares against other `scan_time` values:

```text
$ grep -n "scan_time_min\|scan_time_max" Orchestration/decision_copilot.py
202:        scan_time_min: Optional[datetime] = None
203:        scan_time_max: Optional[datetime] = None
227:                dt = datetime.fromisoformat(str(snap.scan_time).replace("Z", "+00:00"))
228:                if scan_time_min is None or dt < scan_time_min:
230:                if scan_time_max is None or dt > scan_time_max:
```

It compares row-vs-row (all aware in production, so it works today),
and its `except (ValueError, TypeError): pass` at L232 would silently
drop a row from min/max if a mixed-storage DB ever appeared.

**Operator decision: INCLUDE in Gate 3.1.** Rationale on record — same
defect class (silent exception hiding corrupt data), same file, and
leaving it now only defers debt that is easy to forget. Cost: one
additional line in an already-open file. Scope is therefore **7 sites**,
not 6.

### 4.4 Non-goal: I will NOT change the `since`/`until` echo

`output["since"]` (L248-249) echoes `since_dt.isoformat()`. After the
fix this becomes `"2026-09-01T00:00:00+00:00"` for input `"2026-09-01"`
— the normalization becomes **visible in the output**, which is good
and auditable. No output key is added or removed.

---

## 5. Test Plan

### 5.1 New Test File — `Tests/test_phase_i_gate3.1_datetime.py`

A standalone file matching this repo's existing pattern (no framework;
run directly with `python <file>`; `check()` helper).

**Phase A — RED (run BEFORE the fix, must fail):**

| Case | Assertion |
|------|-----------|
| A1 | `analyze_evidence_profile("2026-09-01")` vs aware stub row **inside** range → currently raises `TypeError`; test asserts a `SkillResult` is returned. **Fails pre-fix.** |
| A2 | same, for `until` only |
| A3 | `analyze_evidence_profile("2026-09-01", "2026-12-31T23:59:59+00:00")` (mixed) → currently `TypeError` @ L168. **Fails pre-fix.** |
| A4 | `analyze_historical_patterns("A", "2026-09-01", "2026-12-31")` vs aware `decided_at` inside range → currently `INSUFFICIENT_DATA` with `entry_count` lost. Asserts `SUCCESS` + `entry_count==1`. **Fails pre-fix (Class B).** |
| A5 | `since > until` with mixed awareness → must be `DATA_ERROR`, not crash |

**Phase B — GREEN (run AFTER the fix, same file, no test edits):**

The identical assertions. Post-fix expectations:

| Case | Expected |
|------|----------|
| A1 | `success=True`, `snapshot_count==1` |
| A2 | `success=True`, `snapshot_count==1` |
| A3 | `success=True`, `snapshot_count==1` |
| A4 | `success=True`, `entry_count==1` |
| A5 | `error=="DATA_ERROR"` |

**Phase C — Regression that the fix must not break:**

| Case | Assertion |
|------|-----------|
| C1 | `"not-a-date"` still → `DATA_ERROR` (not `TypeError`) |
| C2 | `None` since/until on `evidence` still → `SUCCESS` |
| C3 | naive rows + naive bounds still → `SUCCESS` (existing fixtures unaffected) |
| C4 | `since>until` → `DATA_ERROR` |
| C5 | `output["since"]` echoes the **normalized** aware value, so normalization is auditable |
| C6 | no bound-parse ever escapes as an unhandled exception: a table of ~12 malformed inputs (empty string, `"2026-13-45"`, `"null"`, `0`, `True`, list, dict) all return a `SkillResult` — never raise |

**Phase D — Boundary proof (source scan):**

| Check | Expectation |
|-------|-------------|
| D1 | helper is pure — no `INSERT/UPDATE/DELETE/DROP`, no engine/broker/permission refs in the new code block |
| D2 | no new import except `timezone` from stdlib `datetime` |
| D3 | `json`, `Any`, `Optional` still imported; nothing orphaned |
| D4 | helper is module-level and *private* (`_`-prefixed) — not a new public API |
| D5 | the 6 (or 7) call sites are the only `fromisoformat` calls left in the file: `grep -n "fromisoformat" → 1` (the helper body) |

### 5.2 Full Regression (your instruction #3)

Exact current counts, verified by running each suite:

| Suite | Count | Command |
|-------|-------|---------|
| `Tests/test_phase_i_gate1_decision_copilot.py` | **124** | hermes-venv python |
| `Tests/test_phase_i_gate3_cli_bridge.py` | **83** | hermes-venv python |
| `Tests/test_phase_a_decision_copilot.py` | **45** | hermes-venv python |
| `Tests/test_activation12_2_permission_enforcer.py` | **26** | hermes-venv python |
| `Tests/test_activation12_3_permission_wiring.py` | **11** | hermes-venv python |
| **Existing total** | **289** | |
| `Tests/test_phase_i_gate3.1_datetime.py` (**new**) | ~24 (TBD after writing) | hermes-venv python |

**289 before, 289+N after — every one green.**

Note on the arithmetic in your message: 124+45+26+11+83 = **289**, not 208.
(124 already contains the Gate 2 cases, so 124 is not double-counted.)
The pre-fix RED run is a deliberate exception: A1–A5 are *expected* to
fail, and that failure output is itself the evidence of the bug.

---

## 6. Locked Files — Verification Plan

Baseline md5 to capture before editing:

```text
26706557fd9e079a678504954f682151  Orchestration/decision_copilot.py   <- OPENS this gate
4d7b683e5d7dac3367665a3927f413c9  Orchestration/capability.py
de6b9a6edaad095fd58edef063d67324  Core/composition_root.py
241a3629eed53c1bd6da671ded3e8ae6  Repository/persistence/performance_repository.py
b0beac167884673f6231c7f436a0af23  Repository/persistence/journal_repository.py
47acb96ce82dfdaa3bab19db01f33a56  Database/models.py
6a9220d2b4ada6e24059f09bc9666312  Orchestration/skill_result.py
e5ec16efa7152017b875bef21e42a156  Orchestration/base_skill.py
main.py                          <- tracked since 7e06441, must be byte-identical
Tests/test_phase_i_gate1_decision_copilot.py  <- LOCKED, no test edits here
Tests/test_phase_i_gate3_cli_bridge.py         <- LOCKED, no test edits here
```

**`main.py` and both existing test files are locked too.** The new
datetime cases go in a **new** file, so Gate 1/2/3 proofs stay exactly
as committed — their counts (124, 83) must not move. Your instruction
#1 asks for a test that *reproduces* the crash; that is satisfied by the
new file's Phase A, without editing the locked suites.

---

## 7. Acceptance Criteria

1. `python main.py decision-copilot evidence 2026-09-01` → `STATUS: SUCCESS`
   with real data, **no traceback**. This is the exact command that
   crashed during Gate 3 manual verification.
2. `python main.py decision-copilot patterns <acc> 2026-09-01 2026-12-31`
   → no longer a silently-degraded status.
3. All 289 existing tests green; new file green.
4. 8 locked-file md5s unchanged except `decision_copilot.py`, which
   changes by exactly the helper + 6 call sites.
5. `decision_copilot.py` re-locked after commit (new md5 recorded).
6. Real-DB row counts unchanged before/after (`ranking_snapshots`,
   `journal_entries`, `decision_briefs`, `accounts`) — empirical
   read-only proof, same standard as Gate 3.
7. One commit: `fix(phase-i): normalize aware/naive datetime comparison in decision_copilot`.
8. **No new status value, no signature change, no new output key.**

---

## 8. Known Limitation (stated, not hidden)

Naive input is **interpreted as UTC**, not as Jakarta local time. For a
naive bound like `"2026-09-01"` this is a midnight-UTC reading, i.e.
07:00 WIB. For `evidence` on the real DB (newest row
`2026-09-11T05:52:04+00:00`) this is immaterial. It *would* matter for
an operator who means "from 00:00 my local time" — the offset is 7
hours. I am not adding a config knob or a local-time default because
that would (a) widen scope past a bugfix, and (b) invent a timezone
policy the codebase has never had. The interpretation is stated in the
helper docstring and is visible in the echoed `output["since"]`, so it
is auditable rather than silent. Flag it if you want a different
convention.

---

## 9. Files to Touch

| File | Action | Lines |
|------|--------|-------|
| `Orchestration/decision_copilot.py` | edit: add helper + `timezone` import, swap 6 (or 7) call sites | +13 / −6 |
| `Tests/test_phase_i_gate3.1_datetime.py` | **new** standalone test file | ~250 |
| `Docs/PHASE I/PHASE_I_GATE3.1_PLAN.md` | this plan, in repo | new |

Nothing else. No commit until you approve.
