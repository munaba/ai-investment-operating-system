# Portability Smell — Hardcoded Absolute Windows Paths

**Severity:** Low
**Status:** Logged only — NOT fixed in Batch 3 (per audit directive; fix deferred unless explicitly requested)
**Logged:** 2026-08-27
**Audit context:** Found during Batch 3 review of `HumanDecisionService` testability. Two services hardcode absolute Windows paths under `F:\\My Son\\`, which breaks on any machine where the project lives elsewhere (Linux/macOS CI, another user's drive, container). No runtime bug on the current host.

---

## `Services/DatabaseService.cs`

`_dbPath` is hardcoded at class scope:

```csharp
private readonly string _dbPath = @"F:\My Son\data\investment_platform.db";
```

Used to build a read-only SQLite connection string in the constructor:

```csharp
_connectionString = $"Data Source={_dbPath};Mode=ReadOnly";
```

**Impact:** The dashboard can only connect to a DB at exactly that path. Moving `data/` or running on a non-Windows host fails at startup/open. Recommendation (when picked up): resolve from `IConfiguration["ConnectionStrings:ReadOnly"]` or `Path.Combine(AppContext.BaseDirectory, "data", "investment_platform.db")`, not a literal `F:\My Son`.

---

## `Services/HumanDecisionService.cs`

`_workingDirectory` is hardcoded at class scope:

```csharp
private readonly string _workingDirectory = @"F:\My Son";
```

Used as `ProcessStartInfo.WorkingDirectory` when shelling out to `python main.py ...`.

**Impact:** Decision submission only works when `main.py` lives under `F:\My Son`. Same portability defect as above. Note: this file was refactored in Batch 3 to add an `IProcessRunner` test seam (no behavior change) — the hardcoded path is untouched and remains the only portability issue here. Recommendation (when picked up): inject the working directory via config or a relative/resolved path.

---

## Why severity = Low

- Both paths are correct and functional on the current dev host (`F:\My Son\...` exists; `main.py` present).
- The app is LAN-only, single-user, runs on this one Windows machine — no cross-platform deployment is planned.
- No security exposure; purely a maintainability / portability smell.
- Does not block Batch 3 acceptance (tests pass, prod build clean).

---

# Historical Note: `AlertService.TestMode` Static Mutable Flag (Removed Pre-Batch 4)

**Status:** Historical — flag already removed from production code before Batch 4 test expansion.
**Originally logged:** 2026-08-27 (during Batch 4 planning)
**Evidence of prior existence:** `docs/verification/phase4c-alert-testmode-proof.md` documents using `AlertService.TestMode = true` for manual verification.

---

## Context

During Batch 4 test expansion planning, the `phase4c-alert-testmode-proof.md` document was discovered, which explicitly references `AlertService.TestMode` as a static boolean flag used to force synthetic alert data for manual verification. However, the current `Services/AlertService.cs` (as of Batch 4) **does not contain this flag** — it was removed at some point prior to Batch 4 (exact commit/author unknown; file is untracked in git).

The alert logic now uses the proper test seams:
- `IDatabaseService` injection (constructor) — faked in tests via `FakeDatabaseService`
- `ITimeProvider` injection (constructor, optional) — faked in tests via `FixedTimeProvider`

---

## Why this was a Medium-severity finding (when the flag existed)

1. **Correctness / trust violation:** If `TestMode` was somehow set `true` in production, the dashboard returned **synthetic alert data** to the user with **zero indication it is fake** — a data-integrity backdoor.

2. **Race condition under parallel test execution:** xUnit runs test classes in parallel by default. A static mutable field shared across tests meant `TestMode = true` in one test class leaked into another running concurrently — flaky/false positives guaranteed.

3. **Not a proper test seam:** The flag bypassed `IDatabaseService` entirely, returning hardcoded synthetic alerts. Real tests should inject a fake `IDatabaseService` (already injectable via constructor) and exercise the actual alert logic with controlled data.

---

## Current state (Batch 4)

- Flag **removed** from `AlertService.cs`
- Tests use `FakeDatabaseService` + `FixedTimeProvider` — no static flag dependency
- No action needed; finding kept for historical traceability only.
