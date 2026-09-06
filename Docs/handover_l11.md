# Stage L11 — Technical Debt / Constraint Handover

**Stage:** L11 — Runtime sebagai Execution Kernel (AIOS Phase 1)
**Status:** CLOSED
**Scope:** Additive only. No existing production call path was rewired.

---

## 1. What was built

### New file: `Orchestration/runtime_analysis_pipeline.py`
`RuntimeAnalysisPipeline` — a facade that runs the existing 11-step
`AnalysisPipeline` through the Runtime execution kernel (`Core/runtime.py`,
via `Agents/executor.py::Executor`) as **one Tool call per `run()`
invocation** — the "satu Tool besar" design (locked decision #1).

Key implementation facts:

- **Stateless** (decision #6): holds only standard constructor-injected
  collaborators (`executor`, `analysis_pipeline`, `tool_context_builder`,
  `tool_registry`). No per-call state lives on `self`.
- **Private Tool handler** (decision #4): each `run(context)` call mints a
  uniquely-named Tool (`runtime_analysis_pipeline::<uuid4>`), registers it,
  calls `Executor.execute(tool_name)` with no args/kwargs, then
  unregisters it in a `finally` block — success or failure.
- **String-only boundary** (decision #5): `ToolContextBuilder.build()` runs
  *inside* the handler closure. Only the final `str` ever crosses the
  Runtime/Executor JSON tool-call boundary.
- **New class, not an adapter evolution** (decision #2/#3):
  `Orchestration/analysis_pipeline_adapter.py::AnalysisPipelineAdapter` was
  **not modified**. It remains pure delegation, unchanged, under its own
  pre-existing regression lock.
- **One turn = one Actor** (decision #9): `Executor.execute()` is called
  with `actor_id=None` (its default), so each `run()` call mints a fresh
  Actor via `Executor`'s existing, unchanged default path.
- **Approval/EventStore** (decision #7/#8): unchanged. This class never
  constructs a `Runtime`, `ApprovalPort`, or `EventStore` itself — it only
  consumes an already-built `Executor`, which still resolves to
  `AlwaysApproveApprovalPort` / `InMemoryEventStore` in production
  (`Core/composition_root.py`, untouched in that respect).

### Modified file: `Core/composition_root.py` (additive only)
- `ApplicationGraph` gained one new field: `runtime_analysis_pipeline`.
- New factory `_build_runtime_analysis_pipeline()`, wired into
  `build_application()`.
- **`StockAgent`'s own construction and call path is untouched.**
  `graph.agent.analysis_pipeline` is still the bare `AnalysisPipeline`
  instance — `StockAgent` does **not** route through
  `RuntimeAnalysisPipeline` in Phase 1. This is intentional and additive:
  the Runtime-kernel path is now reachable from the production graph, but
  nothing about today's live request path changed.

### New test file: `Tests/test_stage_l11_runtime_analysis_pipeline.py`
18 scenarios, all passing: output parity with the direct call path, Tool
registry hygiene (success and failure paths), statelessness across calls,
`health_check()` delegation, composition-root wiring, and a functional
re-proof that `AnalysisPipelineAdapter` is still pure delegation.

### Modified test files (regression-guard updates, not scope changes)
- `Tests/test_stage_l5_composition_root_integration.py`
- `Tests/test_stage_l6_multi_provider_registry.py`

Both files pinned an assertion that `ApplicationGraph` "gained no new
field" as a scope guard for their own (already-CLOSED) stages. L11
legitimately adds a field, so both assertions were updated to expect the
pre-existing field set **plus** `runtime_analysis_pipeline` — the same
pattern this codebase already used when Stage L5 narrowed Stage L4's
locked-file guard (documented inline in both files, at the edited
scenario).

---

## 2. Design note worth recording (not a new architectural decision)

Crossing the Runtime/Executor boundary requires JSON-serializable
`args`/`kwargs` (`Agents/executor.py::Executor.execute` /
`Agents/sandbox.py::GenericSandbox`). `ServiceContext` and
`dict[str, ServiceResult]` are **not** JSON-serializable (nested
dataclasses, arbitrary `metadata`, `Optional[Exception]`, etc.).

This was resolved by capturing `context` via **closure** in the private
Tool handler rather than passing it through `args`/`kwargs` — so
`Executor.execute()` is always called with an empty envelope, and only the
handler's `str` return value ever needs to round-trip through JSON. This
is a direct, necessary consequence of locked decisions #4 and #5, not a
new design choice — flagged here only so a future reader doesn't have to
re-derive it.

---

## 3. Regression status

Full suite run, 32 test files:

- 29 files: pass via `python3 Tests/<file>.py` (custom scenario runner).
- 3 files (`test_stage5_suspend_resume.py`, `test_stage6_delegate.py`,
  `test_stage7_cancel.py`): written for `pytest`, not the standalone
  runner (no `sys.path` bootstrap of their own) — **pre-existing**
  characteristic, unrelated to L11. Verified green via
  `python3 -m pytest` (31 passed).
- `test_stage9_0_composition_root.py`: its own Level-2 scenarios
  (requiring `GEMINI_API_KEY` / network / external packages) skip
  gracefully in this sandboxed environment — pre-existing, unrelated to
  L11.

**Result: 0 regressions introduced by L11.**

---

## 4. Technical debt / constraints for the next stage

1. **`RuntimeAnalysisPipeline` is not yet wired into `StockAgent`.** It
   exists on `ApplicationGraph` but nothing in production calls it yet.
   Swapping `StockAgent`'s call path from `AnalysisPipeline` directly to
   `RuntimeAnalysisPipeline` is explicitly **out of scope** for L11
   (blast-radius discipline) and is a candidate for a future stage, once
   decided.
2. **Tool-name churn.** Each `run()` call registers and unregisters a
   fresh UUID-named Tool. `ToolRegistry` handles this correctly today
   (guarded `register`/`unregister`), but under high call volume this
   means constant registry churn rather than one standing Tool. Not a
   correctness issue at Phase 1 scale; worth a look if/when call volume
   grows enough to matter (e.g. contention on `ToolRegistry`'s internal
   lock).
3. **`AlwaysApprove` / `InMemoryEventStore` remain Phase 1 defaults**
   (locked decisions #7/#8) — no persistence, no real approval policy for
   this path yet. Expected to be revisited only when a later Phase
   explicitly calls for it.
4. **Premature-generalization question is closed for now, not
   forever.** The evaluated (and rejected, for now) alternative — a
   generic `ExecutionPipeline`/`RuntimePipeline` shared by future
   `CodingPipeline`/`ResearchPipeline`/`AutomationPipeline` — should be
   revisited once a second real pipeline implementor actually exists, not
   before (see this session's architecture discussion prior to
   `APPROVE L11`).

---

## 5. Files touched (complete list)

**New:**
- `Orchestration/runtime_analysis_pipeline.py`
- `Tests/test_stage_l11_runtime_analysis_pipeline.py`
- `Docs/handover_l11.md` (this file)

**Modified (additive only):**
- `Core/composition_root.py`
- `Tests/test_stage_l5_composition_root_integration.py`
- `Tests/test_stage_l6_multi_provider_registry.py`

**Untouched (confirmed, per locked decisions #3/#7/#8/#10):**
`Orchestration/analysis_pipeline_adapter.py`, `Core/analysis_pipeline.py`,
`Core/tool_context_builder.py`, `Agents/executor.py`, `Core/runtime.py`,
`Agents/sandbox.py`, `Agents/tool_registry.py`, `Agents/stock_agent.py`,
`Core/approval_config.py`.

---

## L11 — CLOSED
