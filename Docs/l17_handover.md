
# Stage L17 — Memory Layer — Handover

**Stage:** L17 — Memory Layer (AIOS Phase 1, continued)
**Status:** CLOSED
**Scope:** Additive only. No existing production call path was touched.
Baseline: L11, L12, L13, L15 Phase 1, L16 — all CLOSED, not redesigned,
not touched.

---

## 1. Stage Summary

L17 built the AIOS Memory layer in `Orchestration/memory.py`. The module's
own docstring frames the milestone narrowly ("Phase 1: the `MemoryRecord`
value object... Explicitly NOT part of this milestone: `MemoryStore`,
`MemoryRecorder`"), but the file as it exists in the repository today
contains all three objects — `MemoryRecord`, `MemoryStore`, and
`MemoryRecorder` — fully implemented and fully covered by the L17
regression suite. This handover documents the module as it actually
ships, in three phases:

**Phase 1 — `MemoryRecord`.** An immutable value object wrapping exactly
one `Orchestration.observation.Observation`, plus its own identity
(`record_id`, a fresh `uuid4` per instance) and its own timestamp
(`recorded_at`, wall-clock `time.time()` at construction). Both
`record_id` and `recorded_at` are produced by the dataclass's own
`field(default_factory=...)`, so a plain `MemoryRecord(observation=...)`
call is always sufficient — no external id/timestamp helper is required.

**Phase 2 — `MemoryStore`.** A simple in-memory repository keyed by
`MemoryRecord.record_id`. Holds one private, mutable
`Dict[str, MemoryRecord]` internally but never exposes it or a live view
of it — `list()` always returns a fresh `tuple` snapshot, `get()` returns
a single already-immutable `MemoryRecord` or `None`. Four operations:
`add`, `get`, `list`, `clear`, plus `__len__`.

**Phase 3 — `MemoryRecorder`.** The sole bridge between an `Observation`
and Memory storage. Holds exactly one collaborator, a `MemoryStore`
instance, injected via constructor. Its one method, `record(observation)`,
wraps the given `Observation` in a fresh `MemoryRecord`, inserts it into
the store, and returns it — no inspection, transformation, or validation
of the `Observation` happens here.

The three phases relate as a strict dependency chain: `MemoryRecord` is
the value shape; `MemoryStore` persists that shape in-process; `MemoryRecorder`
is the only thing that constructs a `MemoryRecord` and hands it to a
store on the caller's behalf. Nothing in this module calls `GoalPlanner`,
a `ServiceSkill`, or Runtime — its only external dependency is reading an
already-built `Observation` (L16), matching the module's own locked
dependency-direction rule (§3.1 below).

---

## 2. Files Added / Modified

### Created

- **`Orchestration/memory.py`** — the Memory Layer itself: `MemoryError`,
  `MemoryRecord`, `MemoryStore`, `MemoryRecorder`. Exists to give
  `Observation` objects a durable-shaped, in-process home, independent of
  whatever produced the `Observation` in the first place.
- **`Tests/test_stage_l17_memory.py`** — dedicated regression suite (5
  groups, 27 scenarios, 46 checks). Same scenario-based, no-pytest,
  no-external-mocks style as `test_stage_l11_*.py` through
  `test_stage_l16_observation.py`: a global pass/fail counter, plain
  `Goal`/`ExecutionPlan`/`PlanStep`/`ServiceResult`/`Observation`
  fixtures, and a `main()` runner.
- **`l17_handover.md`** (this file) — stage closure record, same format
  as `l15_phase1_handover.md` and `l16_handover.md`.

### Modified

- None. L17 made no changes to any existing production file. Confirmed
  directly: `Core/composition_root.py` contains no reference to `Memory`,
  `MemoryStore`, `MemoryRecorder`, or `MemoryRecord` anywhere.

### Unchanged by design

- **`Orchestration/observation.py`** (`Observation`, `StepObservation`,
  `ObservationRecorder`) — Memory reads an `Observation` as input but
  never calls into `ObservationRecorder`; `Observation` has no knowledge
  Memory exists.
- **`Orchestration/planner.py`** (`GoalPlanner` and its value objects) —
  unchanged; Memory never calls `GoalPlanner`.
- **`Agents/memory.py`** (`ConversationMemory`) — unchanged and
  unrelated. L17 Memory is AIOS structured execution knowledge derived
  from `Observation`; it is a different namespace and a different
  concept from chat/message history, and this module neither reads nor
  writes `ConversationMemory`.
- **`Core/composition_root.py`** — unchanged, as stated above.
- **All pre-existing test files** — unchanged; re-run as regression proof
  only, not edited.

---

## 3. Architecture Decisions (LOCKED)

1. **Memory depends on Observation; Observation must never depend on
   Memory.** `Orchestration.observation` is read-only input to this
   module. `Orchestration/observation.py` has no import of, and no
   knowledge of, `Orchestration.memory`. This is the same one-directional
   pattern already governing Planner → Observation.
2. **Two distinct timestamps are deliberately never conflated.**
   `Observation.recorded_at` (L16, unchanged) is when the `Observation`
   itself was built; `MemoryRecord.recorded_at` is when that
   `Observation` was memorized. An `Observation` is not necessarily
   memorized the instant it is created, so both are kept independently
   for a future consumer to distinguish "when it happened" from "when it
   was memorized."
3. **`MemoryRecord` is immutable.** `@dataclass(frozen=True)`; field
   reassignment raises `FrozenInstanceError` (proven directly in the
   regression suite). `record_id`/`recorded_at` come exclusively from the
   dataclass's own `field(default_factory=...)` — never from a custom
   `__init__` or an external helper — so construction stays a single,
   plain `MemoryRecord(observation=...)` call.
4. **`MemoryRecord` never holds a live reference to a collaborator.**
   Every field is either the already-immutable `Observation` itself or a
   plain value produced at construction time — never a `GoalPlanner`,
   `ObservationRecorder`, Runtime object, or any other live collaborator.
5. **`MemoryStore` exposes no live internal state.** Its one private
   collection (`Dict[str, MemoryRecord]`) is never returned directly;
   `list()` always returns a fresh `tuple` snapshot, and `get()` returns
   either a single (already-immutable) `MemoryRecord` or `None`.
   Mutating a returned `list()` tuple never affects the store.
6. **A `record_id` collision is the store's one genuine-misuse error; a
   lookup miss is not.** `MemoryStore.add()` raises `MemoryError` if
   `record.record_id` is already present. `MemoryStore.get()` returns
   `None` for a missing id — never raised as an error — since a lookup
   miss is a normal, expected outcome.
7. **`MemoryStore` has zero constructor dependencies.** It does not call
   a Service, `ServiceSkill`, `GoalPlanner`, Runtime, or Provider, so it
   takes nothing to construct and always starts empty.
8. **`MemoryRecorder` holds exactly one collaborator — the `MemoryStore`
   it was given.** No other state. It does not inspect, transform, or
   validate the `Observation` it is handed; it constructs exactly one
   `MemoryRecord` wrapping it, inserts that record into the store, and
   returns it.
9. **`MemoryRecorder` never catches or reinterprets store errors.** A
   `record_id` collision surfaced by `MemoryStore.add()` propagates out
   of `MemoryRecorder.record()` unmodified (proven directly in the
   regression suite by forcing a collision via a patched `uuid.uuid4`).
10. **A business failure inside an `Observation` is memorized as-is.**
    `MemoryRecorder` does not filter out, retry, or reinterpret a failed
    step — an `Observation` with `all_succeeded is False` is stored
    exactly like a fully-succeeded one.
11. **`MemoryError` follows the existing exception convention.** It
    subclasses `Core.exceptions.AgentError` directly, the same pattern as
    `GoalPlannerError`/`ObservationError`/`MemoryError`.
12. **AIOS Memory is a distinct namespace from `Agents.memory.ConversationMemory`.**
    This module never reads or writes `ConversationMemory` (chat/message
    history) or any other provider-level prompt memory; the two concepts
    are not to be confused or merged.
13. **Memory owns no Runtime, Planner, or Service references.** This
    module is not imported by, and does not import from,
    `Orchestration.planner`, `Orchestration.service_skill`,
    `Core.runtime`, `Core.composition_root`, or any file under `Agents/`.

---

## 4. Regression Summary

`Tests/test_stage_l17_memory.py` — **46 PASS / 0 FAIL** (5 groups, 27
scenarios):

- **Group 1 — `MemoryError`** (2 scenarios): subclasses `AgentError`;
  carries `message`/`details`; `details` defaults to `{}`.
- **Group 2 — `MemoryRecord` value shape** (6 scenarios): frozen
  dataclass; wraps the exact `Observation` instance (not a copy); fresh
  `uuid4` per instance; `recorded_at` is a float timestamp, distinct from
  `Observation.recorded_at`; single-call construction is always
  sufficient.
- **Group 3 — `MemoryStore`** (8 scenarios): starts empty; add/get round
  trip; missing-id lookup returns `None`, not an error; duplicate
  `record_id` raises `MemoryError`; `list()` preserves insertion order
  and returns a fresh snapshot, not a live reference; `clear()` empties
  the store; zero constructor dependencies.
- **Group 4 — `MemoryRecorder`** (7 scenarios): holds only the store it
  was given; wraps and returns a `MemoryRecord`; inserts into the store;
  returns the same instance that was stored; never mutates the
  `Observation`; reusable across repeated calls with independent
  `record_id`s; propagates a store collision unmodified.
- **Group 5 — Observation → MemoryRecorder → MemoryStore integration**
  (4 scenarios): end-to-end field survival (`plan_step_names`,
  `aggregated_outputs`) through the full trip; multiple `Observation`s
  produce multiple independent records; a failed-step `Observation` is
  memorized as-is, including `failed_service_names`; stores are isolated
  per `MemoryRecorder` instance.

**Full pre-existing regression suite, re-run as part of this audit
(34 test files):** unchanged from before L17 — zero regressions
introduced by L17. One pre-existing, unrelated failure remains on the
baseline (`Tests/test_stage_l6_multi_provider_registry.py`, a stale
`ApplicationGraph` field-set scope guard that predates L17 and is
tracked separately, not part of L17's scope).

---

## 5. Technical Debt / Open Items

Inherited, unaffected by L17:

- **L15/L16's open items remain open** (no `blocked_steps` tracking on
  `ExecutionPlan`, no generic `translate_metadata` mechanism, no
  `ObservationStore`, no query API over `Observation`s) — none of these
  are Memory's responsibility and none were touched here.

New, specific to L17:

- **Module docstring scope note is stale.** `Orchestration/memory.py`'s
  top-of-file docstring still describes the milestone as "Phase 1: the
  `MemoryRecord` value object" and lists `MemoryStore`/`MemoryRecorder`
  as "Explicitly NOT part of this milestone" — but both classes are
  present and fully tested in the same file today. This is a
  documentation-only inconsistency (the code and tests are correct and
  complete); a future small edit to the module docstring to reflect
  Phases 1–3 as shipped would remove the discrepancy, but no production
  behavior is affected by leaving it as-is.
- **No retrieval/query API beyond `get(record_id)`/`list()`.** There is
  no way to ask "give me all records whose `Observation` touched service
  X" or "give me the last N records" — `MemoryStore.list()` returns
  everything, unfiltered, unordered by anything other than insertion
  order.
- **No size/retention bound.** `MemoryStore` grows without limit; there
  is no FIFO/eviction policy analogous to `ConversationMemory.max_size`.
- **No persistence.** `MemoryStore` is an in-process, in-memory
  dictionary only. Nothing here writes to SQLite, ChromaDB, or any other
  durable store — a future stage's decision, not resolved here.
- **No Composition Root wiring.** `Core/composition_root.py` has no
  `MemoryStore`/`MemoryRecorder` field or factory. Memory is not yet
  reachable from any production call path.
- **No automatic recording hook.** Nothing in `GoalPlanner` or
  `ObservationRecorder` calls `MemoryRecorder.record(...)` automatically;
  today it is only reachable by a caller constructing and invoking it
  directly, exactly as `ObservationRecorder` was at the end of L16.

---

## 6. Recommended Next Stage

The roadmap locked since L15 and re-validated in L16 (**Observation →
Memory → Reflection**) is now fully implemented at the source level: all
three layers exist in `Orchestration/`. However, this handover's own
regression audit (§4) found the Memory layer itself complete and
proven — the reflection layer built on top of it, `Orchestration/reflection.py`,
is a separate concern documented on its own in `l18_handover.md`, and
that document's audit found its regression suite (`Tests/test_stage_l18_reflection.py`)
to be an empty file. Per the same discipline this project has followed
since L11 — no stage is considered CLOSED without a passing dedicated
regression suite — the most direct next stage is **closing that gap**:
writing `Tests/test_stage_l18_reflection.py` before any further
milestone (Composition Root wiring, an `ObservationStore`, a
`MemoryStore` retention policy, or any new Skill) is opened. See
`l18_handover.md` §7 for the full recommendation.

---

## L17 — CLOSED
