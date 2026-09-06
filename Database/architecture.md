
# Database Layer — Architecture Notes

This document covers the two things the audit asked to have made explicit:
the error contract, and exactly what `BaseDatabase` does and does not
abstract. It also records the deliberate behavior changes made while
fixing the audit's blockers, and what is still **not** done.

Scope reminder: this package is the Database foundation only. It does not
contain, and should not grow, a Repository layer, business tables, or a
query builder. Where this doc talks about Repositories/Services, it is
describing the contract those *future* layers must follow, not code that
exists yet.

---

## 1. The error contract

```
Database (SQLite today; Postgres/TimescaleDB/DuckDB later)
    |
    | raises DatabaseError  (Core.exceptions.DatabaseError -- exists today)
    v
Repository            (not built yet -- out of scope for this pass)
    |
    | must catch DatabaseError and raise RepositoryError
    v
Service
    |
    | must catch RepositoryError and return ServiceResult.fail(...)
    v
Agent
```

Rules for whoever builds the Repository layer next:

- **`DatabaseError` must never cross the Repository boundary.** Every
  public Repository method that touches `BaseDatabase`/`DatabaseManager`
  must catch `DatabaseError` (and only `DatabaseError` — don't catch
  broad `Exception` here, or genuine bugs get silently reclassified as
  data-layer failures) and re-raise as a `RepositoryError`, adding
  whatever business context the Database layer couldn't know about (e.g.
  "failed to save watchlist entry for BBCA.JK" rather than "SQLite
  execute failed: INSERT INTO ...").
- **`RepositoryError` must never cross the Service boundary.** Services
  catch it and translate to `ServiceResult.fail(...)`, exactly like they
  already do for `ProviderError` from the Providers layer.
- **Agents never see `DatabaseError` or `RepositoryError` directly** —
  only `ServiceResult`. This keeps the failure-handling story for Agents
  uniform regardless of which layer actually failed.
- `RepositoryError` doesn't exist in `Core.exceptions` yet (this pass
  didn't touch that file, since it's shared by unrelated layers already
  under test — see the note at the bottom of this doc). When it's added,
  it should follow `DatabaseError`'s existing shape (`message: str`,
  `details: Dict[str, Any]`) for consistency.

### What's already true today, in this package

- Every failure this package can produce comes out as `DatabaseError` —
  never a raw `sqlite3.Error`, `KeyError`, etc. Confirmed by
  `test_database_layer_hardening.py::scenario_database_errors_carry_consistent_shape`.
- `DatabaseError` always carries a human-readable `message` and a
  `details` dict with the underlying driver error, so a Repository can
  add context without losing the original cause.
- `rollback()` never raises (documented in `BaseDatabase.rollback` and
  enforced by `SQLiteDatabase.rollback`), specifically so cleanup code
  can call it unconditionally from a `finally`/`except` block without
  needing its own error handling.

---

## 2. What `BaseDatabase` abstracts, and what it deliberately doesn't

**Abstracted — safe to depend on for any backend:**

- Connect / disconnect / `is_connected`.
- `execute()` / `executemany()` returning a normalized `QueryResult`
  (rows as plain dicts, `rowcount`, `lastrowid`).
- Transactions that nest via savepoints: calling `begin()` while a
  transaction is already active opens a nested savepoint instead of
  raising, so Repository methods compose (one Repository method calling
  another, each wrapping its own `begin()`/`commit()`, just works). Only
  the outermost `commit()`/`rollback()` actually touches the database.
- A best-effort `exclusive=True` mode on the *outermost* `begin()`,
  meaning "serialize against every other writer, including other
  processes." Used by `MigrationRunner`.
- `health_check()` never raising.
- Every failure surfacing as `DatabaseError`.

**NOT abstracted — intentionally backend-specific:**

- **SQL dialect.** Callers write raw SQL against whatever backend is
  configured. There is no query builder, and per the task brief, none is
  planned. Moving to Postgres later means Repository SQL gets rewritten,
  not automatically translated.
- **Pragmas / tuning.** `DatabaseConfig.journal_mode`, `synchronous`,
  `foreign_keys`, and `extra_pragmas` are SQLite concepts. A Postgres
  backend would ignore them and expose its own tuning knobs; this is an
  escape hatch, not a portable setting.
- **Exact locking/concurrency semantics.** `exclusive=True` means "as
  strong as this backend can offer," not "identical blocking behavior
  everywhere." On SQLite it's a real OS-level file lock (see §4). On a
  networked backend it might be an advisory lock or `SELECT ... FOR UPDATE`, with different timeout/deadlock characteristics.
- **Process topology.** SQLite is an embedded, file-based, single-process-
  at-a-time-for-writes database. Postgres/Cloud SQL are networked,
  multi-client by design. This distinction is *why* the `:memory:` trap
  below exists for SQLite specifically and wouldn't for a networked
  backend.

Do not read more portability into `BaseDatabase` than this. If a future
Repository method needs backend-specific behavior, that's expected —
document it at the call site, don't try to hide it here.

---

## 3. Connection lifecycle (SQLite)

- One `sqlite3.Connection` per thread (SQLite connections aren't
  thread-safe to share), opened lazily on first use.
- `disconnect()` closes the calling thread's connection. `close_all()`
  closes every connection this `SQLiteDatabase` instance has ever opened,
  across all threads — for graceful shutdown.
- **Known limitation:** `close_all()` calls `sqlite3.Connection.close()`
  directly on connections it didn't open on the calling thread. SQLite
  connections can only be closed from the thread that created them
  (`check_same_thread=True`); if the owning thread is still alive and
  using its connection concurrently with your `close_all()` call, that
  connection's `close()` will raise internally, which `close_all()`
  catches and logs, then moves on. In practice this is fine for the
  intended use (shutdown, when other threads are also stopping), but
  `close_all()` is not a substitute for each thread cleanly calling
  `disconnect()` itself when that's possible.
- **Leak safety net:** if a thread never calls `disconnect()` (e.g. a
  thread-pool worker that just exits), its connection would previously
  leak until process exit. Now, a `weakref.finalize` tied to the
  `threading.Thread` object closes the connection once that thread object
  itself is garbage collected. This is a safety net, not a substitute for
  calling `disconnect()` — the finalizer only fires whenever Python's GC
  gets around to collecting the dead thread object, which is not
  deterministic.

---

## 4. Migration locking

`MigrationRunner.apply()` now:

1. Ensures the bootstrap `schema_migrations` table exists.
2. If nothing looks pending, returns immediately (no lock taken).
3. Otherwise acquires `begin(exclusive=True)` — `BEGIN EXCLUSIVE` on
   SQLite, which takes an OS-level exclusive lock on the database file
   immediately, blocking (up to `DatabaseConfig.timeout` seconds) until
   any other writer — in this process or another — releases it.
4. **Re-computes the pending list after acquiring the lock.** This is the
   part that actually prevents double-application: if another
   process/thread got the lock first and applied some migrations while
   we were waiting, we'll see that in `schema_migrations` once we get the
   lock and skip those versions.
5. Applies each pending migration in its own nested savepoint (so an
   individual migration's own failure is isolated and diagnosable), then
   commits the outer exclusive transaction once the whole batch succeeds.

**Deliberate behavior change:** previously, each migration committed
independently, so a batch of 3 migrations where the 3rd failed would
leave the first 2 permanently applied. Now the entire batch commits or
rolls back together. This is intentional: a locking mechanism whose
purpose is "don't leave migrations in a racy, ambiguous state" is
undermined by allowing a batch to be left half-applied on failure. The
tradeoff is that a large batch with one bad migration near the end
re-does more work on retry (nothing was kept) — for a schema-migration
runner, that's the right tradeoff.

**Verified with real OS processes, not just threads** — SQLite's
cross-process locking behavior can't be fully exercised with threads
alone, since the OS file lock is what's actually being tested. See
`test_database_layer_hardening.py::scenario_migration_lock_across_real_processes`,
which spawns two real subprocesses racing to migrate the same file and
asserts exactly 2 migrations end up applied in total.

**Not addressed:** advisory-lock behavior for a future networked backend
(Postgres). `exclusive=True` is currently only implemented for SQLite;
a Postgres `BaseDatabase` implementation would need its own locking
strategy (e.g. `pg_advisory_lock`) behind the same method signature.

---

## 5. The `:memory:` trap

Because this package gives each thread its own connection,
`db_path=":memory:"` used to silently mean *every thread gets its own,
separate, empty database* — no error, just quietly wrong data (writes
from one thread invisible to another). This is now rejected at
`SQLiteDatabase.__init__` time with a `DatabaseError` explaining why.

The documented escape hatch, for callers who genuinely want an in-memory
database shared across threads in one process:

```python
DatabaseConfig(
    db_path=Path("file::memory:?cache=shared"),
    uri_mode=True,
)
```

This uses SQLite's shared-cache URI form (`uri=True` passed to
`sqlite3.connect`). Caveat inherited from SQLite itself: a shared-cache
in-memory database is destroyed once its *last* connection closes, so if
every thread disconnects, the data is gone — there's no persistence
guarantee here. This mode exists for tests and small shared caches, not
as a general substitute for a real file-backed database.

Verified in
`test_database_layer_hardening.py::scenario_bare_memory_path_is_rejected`
and `::scenario_shared_cache_memory_uri_is_the_documented_escape_hatch`.

---

## 6. Nested transactions

`begin()` now nests via `SAVEPOINT` instead of raising when called while
a transaction is already active on the calling thread's connection.
`commit()`/`rollback()` release/roll back to the innermost savepoint;
only the outermost pair actually commits/rolls back to the database.
This is what makes Repository methods composable — see §2 and the
`scenario_composable_repository_pattern_via_manager_session` test.

`exclusive=True` is only valid for a brand-new top-level transaction
(raises `DatabaseError` if passed while nested) — exclusivity is a
property of the whole transaction, so it doesn't make sense to request it
partway through one that's already open with weaker isolation.

---

## Note on `Core.exceptions`

This pass did not modify `Core/exceptions.py` (not part of the uploaded
scope for this task, and it's shared by the Providers/Agents layers,
which already have their own passing test suites — `AgentError`,
`ProviderError`, `ToolError`). `DatabaseError` there is used unchanged.
Adding `RepositoryError` is called out above as something the Repository
layer's implementer should do when that layer is actually built.
