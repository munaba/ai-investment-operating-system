# Stage L12 — Technical Debt / Constraint Handover

**Stage:** L12 — Production Runtime Activation
**Status:** CLOSED
**Scope:** Additive only (Option A, approved). No existing call path was
removed; a new optional path was added and activated in production only.

---

## 1. What was built

### Modified file: `Agents/stock_agent.py` (additive only)
- `StockAgent.__init__` gained one new, optional constructor argument:
  `runtime_analysis_pipeline: Optional[RuntimeAnalysisPipeline] = None`,
  stored unchanged as `self.runtime_analysis_pipeline`.
- `_run_service_pipeline()` now branches on it:
  - **Not `None` (Stage L12 path):** the built `ServiceContext` is handed
    to `RuntimeAnalysisPipeline.run()` — i.e. routed through
    `Core.runtime.Runtime` as the execution kernel — and its
    already-formatted `str` return value is returned directly.
    `self.tool_context_builder.build()` is deliberately **not** called a
    second time on this path (its input is a
    `Dict[str, ServiceResult]`, not the `str`
    `RuntimeAnalysisPipeline.run()` returns — see the L12 audit's Hidden
    Coupling finding #2).
  - **`None` (default, pre-existing path):** byte-for-byte unchanged from
    before this stage — `self.analysis_pipeline.run(context)` then
    `self.tool_context_builder.build(results)`.
- No existing method signature, attribute, or call site inside this file
  was removed or renamed.

### Modified file: `Core/composition_root.py` (additive only)
- `build_application()`'s `StockAgent(...)` construction now passes the
  already-built `runtime_analysis_pipeline` (constructed by the
  pre-existing, Stage L11 `_build_runtime_analysis_pipeline()`) into
  `agent`'s new constructor argument of the same name.
- **This is the one and only place in the production graph that
  activates the Runtime-kernel path for `StockAgent`.** No other file
  constructs or wires a second `RuntimeAnalysisPipeline`.
- `ApplicationGraph` gained no new field (the field already existed
  since Stage L11); only what is done with the existing field changed.
- Docstrings (`ApplicationGraph`, `build_application`) updated to
  reflect that `StockAgent` now actually uses
  `runtime_analysis_pipeline`, and to record the Risk 1 assumption (§4
  below) inline at the point where `Executor`'s `approval_port` is
  built.

### New test file: `Tests/test_stage_l12_production_runtime_activation.py`
19 scenarios, all passing:
1. Fallback path (`runtime_analysis_pipeline=None`) end-to-end unchanged.
2. Runtime path produces output byte-for-byte identical to the fallback
   path, through `StockAgent.chat()` (not just `RuntimeAnalysisPipeline`
   in isolation — that was already proven by Stage L11's own suite).
3. Tool-registry hygiene holds through the full agent across repeated
   `chat()` calls (no leaked private Tool entries).
4. The two paths' exception taxonomies genuinely differ on an unexpected
   failure (`RuntimeError` vs `ToolExecutionError`) — proven, not just
   asserted, and both still transition the agent to `ERROR` correctly.
5. Composition-root wiring: `graph.agent.runtime_analysis_pipeline is
   graph.runtime_analysis_pipeline` (one shared instance), and
   `graph.agent.analysis_pipeline` is still the bare, unwrapped
   `AnalysisPipeline`.
6. Backward compatibility: constructing a `StockAgent` without the new
   argument at all still works, and defaults it to `None`.

### Not modified (confirmed, out of L12 scope)
`Orchestration/runtime_analysis_pipeline.py`,
`Orchestration/analysis_pipeline_adapter.py`, `Core/analysis_pipeline.py`,
`Core/tool_context_builder.py`, `Agents/executor.py`, `Core/runtime.py`,
`Agents/sandbox.py`, `Agents/tool_registry.py`,
`Agents/market_analysis_agent.py`, `Core/approval_config.py`. No existing
test file was modified — none of the pre-existing `StockAgent(...)`
construction call sites pass the new argument, so all of them continue
exercising the `None` fallback path unmodified.

---

## 2. Design note worth recording (not a new architectural decision)

Two execution paths for `StockAgent` now live side by side, deliberately
(approved trade-off, Option A):

- **Fallback:** `analysis_pipeline.run()` → `tool_context_builder.build()`,
  two separate calls, exception types propagate unwrapped.
- **Runtime (production, via composition_root):**
  `runtime_analysis_pipeline.run()`, one call, already-formatted `str`,
  unexpected exceptions surface as `ToolExecutionError`.

This duplication is accepted as **temporary** scaffolding for L12's
narrow goal (activate Runtime as the execution kernel, nothing else).
Collapsing to a single path is explicitly deferred — see §4 below.

---

## 3. Regression status

Full suite run, **34 test files** (33 pre-existing + 1 new for L12):

- 31 files (including the new `test_stage_l12_production_runtime_activation.py`):
  pass via `python3 Tests/<file>.py` (custom scenario runner).
- 3 files (`test_stage5_suspend_resume.py`, `test_stage6_delegate.py`,
  `test_stage7_cancel.py`): pre-existing characteristic, unrelated to
  L12 (written for `pytest`, no `sys.path` bootstrap of their own) —
  verified green via `python3 -m pytest` (31 passed).
- `test_stage9_0_composition_root.py`: 28/28 pass via the custom runner;
  its own Level-2 scenarios (requiring `GEMINI_API_KEY`/network/external
  packages) skip gracefully in this sandboxed environment — pre-existing,
  unrelated to L12.

**Result: 0 regressions introduced by L12.**

---

## 4. Technical debt / constraints for the next stage

1. **Two execution paths for `StockAgent` remain live.** This is the
   accepted Option A trade-off, not an oversight. Collapsing
   `_run_service_pipeline()` to a single Runtime-only path (removing the
   `None`-fallback branch and the now-redundant `analysis_pipeline` /
   `tool_context_builder` direct-call code) is explicitly **out of
   scope** for L12 and is a candidate for a future stage, once the
   Runtime path has been validated in real production traffic.
2. **`APPROVAL_POLICY=tool_whitelist` is fundamentally incompatible with
   `RuntimeAnalysisPipeline`'s per-call UUID-named private Tool, and this
   is NOT solved by L12.** `ToolWhitelistApprovalPort` does exact string
   matching (`Core/approval.py`); a UUID-suffixed tool name
   (`runtime_analysis_pipeline::<uuid4>`) can never appear in a static
   whitelist. **L12 assumes `APPROVAL_POLICY=always_approve` (the
   documented default) or `APPROVAL_POLICY=tool_blacklist`** for the
   Runtime-routed `StockAgent` path to function at all. If any
   deployment ever sets `APPROVAL_POLICY=tool_whitelist` — for this
   `Executor` instance, which is shared with any other tool-calling
   agent in the graph — every `StockAgent` request would receive
   `ApprovalDenied`, 100% failure, with no correctness bug in the
   pipeline itself. This is documented here as a known Phase 1
   limitation (per explicit instruction, not addressed by this stage);
   resolving it (e.g. a stable/prefix-matchable Tool identity, or a
   whitelist policy that understands per-call Tool names) is deferred to
   a future approval/security-focused stage.
3. **Exception taxonomy differs between the two paths on the unhappy
   path.** An unexpected exception from `analysis_pipeline.run()` or
   `tool_context_builder.build()` propagates with its original type on
   the fallback path, but surfaces as `Core.exceptions.ToolExecutionError`
   on the Runtime path (Executor's existing, unchanged Stage 8.2
   contract). Any caller above `StockAgent` catching a specific exception
   type for this rare path should be aware production now takes the
   Runtime path. Not a defect — proven and asserted explicitly in the new
   test suite (`scenario_exception_taxonomy_differs_on_failure`) so it
   cannot silently regress either way.
4. **Tool-registry churn (Stage L11 debt #2) is now live in production,**
   not just theoretical. Registering/unregistering a UUID-named Tool per
   `StockAgent.chat()` call is correctness-safe today (idempotent
   guarded `register`/`unregister`, re-proven end-to-end in this stage's
   own suite), but under real production call volume this is constant
   registry churn rather than one standing Tool. Same recommendation as
   L11: revisit if/when call volume grows enough to matter (contention on
   `ToolRegistry`'s internal lock).
5. **`AlwaysApprove` / `InMemoryEventStore` remain Phase 1 defaults**
   (unchanged, LOCKED since Stage L11/earlier) — no persistence, no real
   approval policy for this path yet, now carrying real production
   traffic instead of none. Expected to be revisited only when a later
   Phase explicitly calls for it.

---

## 5. Files touched (complete list)

**New:**
- `Tests/test_stage_l12_production_runtime_activation.py`
- `Docs/handover_l12.md` (this file)

**Modified (additive only):**
- `Agents/stock_agent.py`
- `Core/composition_root.py`

**Untouched (confirmed, per L12 scope discipline):**
`Orchestration/runtime_analysis_pipeline.py`,
`Orchestration/analysis_pipeline_adapter.py`, `Core/analysis_pipeline.py`,
`Core/tool_context_builder.py`, `Agents/executor.py`, `Core/runtime.py`,
`Agents/sandbox.py`, `Agents/tool_registry.py`,
`Agents/market_analysis_agent.py`, `Core/approval_config.py`, and every
pre-existing test file (no regression-guard edits were needed — Option A
made none necessary).

---

## L12 — CLOSED
