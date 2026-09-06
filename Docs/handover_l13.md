# Stage L13 — Technical Debt / Constraint Handover

**Stage:** L13 — Granular Skills
**Status:** CLOSED
**Scope:** Additive only. No existing production call path was rewired.
L13 is not about a Planner and not about a "Brain" — it only gives
Runtime the *capability* to call any one of the 11 Services individually,
via a standing Tool per Service. Nothing in production calls that
capability yet.

Production path (unchanged, LOCKED):

```
User → StockAgent → RuntimeAnalysisPipeline → Runtime → AnalysisPipeline → 11 Services
```

---

## 1. What was built

### New file: `Orchestration/service_skill.py`

**`SkillMetadata`** — a frozen `@dataclass` with exactly four fields:
`service_name`, `required_inputs`, `optional_inputs`, `produced_outputs`.
No methods beyond what `@dataclass` generates for free (`__init__`,
`__eq__`, `__repr__`). No validator, no parser, no dependency resolver,
no scheduler — proven by the new test suite (scenario
`scenario_skill_metadata_is_declarative_only`: enumerates
`SkillMetadata`'s public attributes and asserts nothing beyond the four
declared fields exists).

**`SKILL_METADATA_BY_SERVICE`** — a module-level `Dict[str, SkillMetadata]`,
one literal entry per one of the 11 pipeline Services. Every field value
is a direct transcription of what that Service's own `execute()` reads
from / writes into `ServiceContext.metadata` (verified against each
Service's source, not inferred or reflected at runtime):

- "required" = the Service's own `execute()` explicitly checks for the
  key's absence and returns `ServiceResult.fail(...)` if missing.
- "optional" = the Service reads the key via
  `context.get_metadata(key, <default>)` and tolerates it being
  missing/`None`.
- Where a Service accepts "at least one of" several keys
  (`fundamental_service`: per/roe/dividend_yield;
  `pattern_service`: win_rate/avg_return), all of those keys are listed
  under `required_inputs` as a flat list — the "at least one" vs. "all
  of" distinction is *not* separately encoded anywhere in
  `SkillMetadata`, by design (no behavior).
- The three orphan metadata keys the L13 audit already found
  (`PER_SECTOR_AVG`, `ROE_SECTOR_AVG`, `AVG_RETURN`) appear here exactly
  like any other input this mapping records — this mapping only records
  what each Service itself reads, not who (if anyone) produces it.
- `risk_management_service`'s `required_inputs` is identical to
  `Core/analysis_pipeline.py`'s own `required_fields` list inside
  `_prepare_risk_management_context` — but that pipeline-level
  PRICE → ENTRY_PRICE translation + simulation-default filling is **not**
  reimplemented here. Calling `ServiceSkill(risk_management_service,
  ...).execute(...)` directly, without that translation having already
  happened, fails exactly the way calling
  `RiskManagementService.execute()` directly always has.

**`ServiceSkill`** — one generic, non-specialized wrapper class,
constructed 11 times in production (never subclassed). Constructor:
`(service: BaseService, metadata: SkillMetadata)`. Behavior is limited to
exactly:

- `execute(*, user_input="", metadata=None, agent_name="", provider_name="",
  request_id=None) -> ServiceResult`: builds a `ServiceContext` from the
  given arguments (defaulting `request_id` to a fresh `uuid4` when
  omitted) and returns `service.execute(context)` unmodified — no
  merging with any other context, no reading of `self._metadata` to
  validate/resolve/fill anything, no transformation of the returned
  `ServiceResult`.
- `health_check()`: pure passthrough to `service.health_check()`.
- `metadata` (property): exposes the injected `SkillMetadata`.
- `tool_name` (property): `f"skill.{metadata.service_name}"` — a stable,
  standing name (unlike `RuntimeAnalysisPipeline`'s private,
  UUID-suffixed per-call Tool name).

### Modified file: `Core/composition_root.py` (additive only)

- New factory `_build_service_skills()`: iterates
  `service_registry.list()` (already populated by the pre-existing
  `_build_analysis_pipeline()`), wraps each Service with a matching
  `SKILL_METADATA_BY_SERVICE` entry in a `ServiceSkill` (no new Service
  instance constructed — the exact same instance already held by
  `ServiceRegistry` is wrapped), and registers each as a standing Tool
  (`Agents.tool_registry.Tool`) under `skill.<service_name>` into the
  shared `tool_registry`, guarded by `tool_registry.exists(...)` for the
  same re-entrancy reason every other registration in this file already
  uses this guard. A Service present in `ServiceRegistry` without a
  matching `SKILL_METADATA_BY_SERVICE` entry is skipped (never triggers
  in production today — see §4 below).
- `ApplicationGraph` gained one new field: `service_skills:
  Dict[str, ServiceSkill]`, added as the field immediately after
  `runtime_analysis_pipeline`.
- `build_application()` calls `_build_service_skills()` after
  `_build_analysis_pipeline()` (required ordering — `service_registry`
  must already be populated) and includes the result in the returned
  `ApplicationGraph`.
- **`StockAgent`'s own construction and call path is untouched.** `agent`
  is built exactly as Stage L12 left it; nothing about
  `agent.analysis_pipeline` / `agent.runtime_analysis_pipeline` changed.
  No existing `StockAgent(...)` construction call site anywhere in the
  codebase was touched.
- Docstrings (`ApplicationGraph`, `build_application`) updated to record
  the Stage L13 addition, following the same inline-comment pattern
  Stage L11/L12 already used for their own additions.

### New test file: `Tests/test_stage_l13_service_skill.py`

54 checks across 9 scenarios, all passing:

1. `scenario_parity_wrapper_vs_direct_service` — `ServiceSkill.execute()`
   produces the same `ServiceResult.data`/`.message` as calling the
   Service directly for an equivalent context; an exception the Service
   raises still propagates unmodified (no `try`/`except` added).
2. `scenario_execute_defaults_request_id_when_omitted` — `execute()`
   works with only `metadata` supplied.
3. `scenario_health_check_passthrough` — pure passthrough, both healthy
   and unhealthy cases.
4. `scenario_tool_registration_and_invocation` — exactly 11
   `ServiceSkill`s are built, keyed by exactly
   `SKILL_METADATA_BY_SERVICE`'s keys; every one is registered as
   `skill.<name>` in `tool_registry`; invoking the registered
   `skill.stock_service` Tool's handler actually runs the real
   `StockService` and returns a `ServiceResult`.
5. `scenario_idempotent_across_repeated_build_application_calls` —
   calling `build_application()` twice in the same process does not
   raise `ToolAlreadyRegisteredError` for skill Tools.
6. `scenario_composition_wiring_shares_instances_and_leaves_stockagent_untouched`
   — every `ServiceSkill` wraps the *same* instance already in
   `ServiceRegistry` (white-box check on `skill._service is
   registry_instance`); `agent.runtime_analysis_pipeline` /
   `agent.analysis_pipeline` are exactly as Stage L12 left them;
   `StockAgent` itself has no `service_skills` attribute.
7. `scenario_skill_metadata_is_declarative_only` — spot-checks one
   `SkillMetadata` entry against source, and proves the class exposes no
   attribute beyond its four declared fields.
8. `scenario_debt_r3_generic_sandbox_fallback_still_applies` — **runs a
   skill Tool through the real, unmodified `GenericSandbox.execute()`**
   and asserts the JSON-encoded result is the stringified
   `ServiceResult` (`"ServiceResult(...)"`), proving R3 is unfixed and
   still reachable through this new path — functionally, not just by
   comment.
9. `scenario_debt_r4_no_context_accumulation` — a Service requiring a
   prior step's output (mirroring `technical_score_service`'s need for
   `harga`/PRICE) still fails when called standalone via its skill
   without that key explicitly supplied, and a prior unrelated
   `ServiceSkill.execute()` call leaves no trace for a later one —
   proving `ServiceSkill` does not reimplement
   `AnalysisPipeline`'s SS5 context accumulation.

### Modified test files (regression-guard updates only, not scope changes)

- `Tests/test_stage_l5_composition_root_integration.py`
- `Tests/test_stage_l6_multi_provider_registry.py`

Both files pinned an assertion that `ApplicationGraph`'s field set/order
was "the pre-L5/L6 set + Stage L11's `runtime_analysis_pipeline`" as a
scope guard for their own (already-CLOSED) stages. Stage L11 had already
narrowed both once, for its own added field, following an explicit,
documented precedent (Stage L5 itself narrowing Stage L4's locked-file
guard). L13 legitimately adds one more field (`service_skills`,
immediately after `runtime_analysis_pipeline`), so both assertions were
updated the same way, at the same edited scenario, with the reasoning
recorded inline: what each scenario continues to prove is unchanged — no
*other* field was added or reordered by any stage between L5/L6 and L13.

### Not modified (confirmed, out of L13 scope)

`Core/analysis_pipeline.py`, `Core/runtime.py`, `Agents/executor.py`,
`Agents/sandbox.py`, `Agents/tool_registry.py`,
`Orchestration/runtime_analysis_pipeline.py`,
`Orchestration/analysis_pipeline_adapter.py`, `Agents/stock_agent.py`,
`Core/tool_context_builder.py`, `Core/approval_config.py`,
`Services/base_service.py`, `Services/service_context.py`,
`Services/service_result.py`, `Services/service_registry.py`, and every
one of the 11 Service implementations (`Services/stock_service.py`,
`Services/technical_indicator_service.py`,
`Services/moving_average_service.py`,
`Services/technical_score_service.py`, `Services/fundamental_service.py`,
`Services/pattern_service.py`, `Services/chart_service.py`,
`Services/news_service.py`, `Services/backtest_service.py`,
`Services/risk_management_service.py`, `Services/scoring_service.py`).
No existing test file's own scenarios were changed in meaning — only the
two field-set literals described above.

---

## 2. Design note worth recording (not a new architectural decision)

`GenericSandbox._encode()` (`Agents/sandbox.py`, unchanged) JSON-encodes a
Tool handler's return value, falling back to `str(result)` when it is not
directly JSON-serializable (R3, pre-existing debt). Every `ServiceSkill`
Tool handler returns a `ServiceResult` — a dataclass that can carry an
`Optional[Exception]` and arbitrary `data` — which is never
JSON-serializable. This was already true in principle before L13 (the
fallback itself is untouched, Stage 8.2 LOCKED), but L13 is the first
stage where a *standing* Tool exists whose handler routinely returns a
`ServiceResult` reachable via `GenericSandbox`/`Executor.execute()` (as
opposed to `RuntimeAnalysisPipeline`'s private handler, which always
returns an already-formatted `str`). This is exercised, not just
theorized, by this stage's own test suite
(`scenario_debt_r3_generic_sandbox_fallback_still_applies`) — flagged
here so a future reader doesn't have to re-derive why R3 now has a live,
standing reachability path in addition to its original one.

---

## 3. Regression status

Full suite run, **35 test files** (34 pre-existing + 1 new for L13):

- 32 files (including the new `test_stage_l13_service_skill.py`): pass
  via `python3 Tests/<file>.py` (custom scenario runner). This count
  includes the two regression-guard updates
  (`test_stage_l5_composition_root_integration.py`,
  `test_stage_l6_multi_provider_registry.py`), both green after their
  field-set literal was updated per §1 above.
- 3 files (`test_stage5_suspend_resume.py`, `test_stage6_delegate.py`,
  `test_stage7_cancel.py`): pre-existing characteristic, unrelated to
  L13 (written for `pytest`, no `sys.path` bootstrap of their own) —
  verified green via `python3 -m pytest` (31 passed).
- `test_stage9_0_composition_root.py`: 28/28 pass via the custom runner;
  its own Level-2 scenarios (requiring `GEMINI_API_KEY`/network/external
  packages) skip gracefully in this sandboxed environment — pre-existing,
  unrelated to L13, unchanged from L11/L12.

**Result: 0 regressions introduced by L13**, after the two expected,
narrow field-set-literal updates described in §1.

---

## 4. Technical debt / constraints for the next stage

1. **`SkillMetadata` is stored, never read by production code.** Nothing
   in this stage (or any prior stage) reads `SkillMetadata.required_inputs`
   / `.optional_inputs` / `.produced_outputs` to do anything — no
   validation, no dependency ordering, no discovery. It exists purely so
   a future Planner (L14) has a declarative graph to read. Until that
   Planner exists, `SkillMetadata` is inert data.
2. **11 standing Tools now exist in `tool_registry` with no caller.**
   `skill.stock_service` through `skill.scoring_service` are registered
   and invocable (proven by this stage's own test suite), but nothing in
   the production `StockAgent` → `RuntimeAnalysisPipeline` → `Runtime` →
   `AnalysisPipeline` path ever calls them. This is the intended L13
   scope (capability only), not an oversight — see module docstring.
3. **R3 (`GenericSandbox`'s `str(result)` fallback) now has a live,
   standing reachability path**, not just a theoretical one — see §2
   above. Not fixed here (LOCKED debt, unchanged from prior stages); a
   future stage that actually drives a `ServiceSkill` Tool through
   `Executor.execute()` (e.g. a Planner) will get a stringified
   `ServiceResult`, not a structured one, unless this is addressed first.
4. **R4 (no context accumulation) is now directly exercisable per
   Service**, not just true of the pipeline as a whole. A future Planner
   calling more than one `ServiceSkill` in sequence (e.g.
   `skill.technical_indicator_service` then
   `skill.technical_score_service`) must itself carry forward whatever
   `technical_indicator_service` produced (e.g. `rsi`) into the next
   call's `metadata` — `ServiceSkill` provides no memory across calls,
   by design (see module docstring, decision #2). Not fixed here (LOCKED
   debt, same R4 first flagged in the L13 audit).
5. **`risk_management_service`'s skill has no PRICE → ENTRY_PRICE
   translation.** Calling `ServiceSkill(risk_management_service,
   ...).execute(metadata={...})` standalone requires `ENTRY_PRICE`
   already present in `metadata` — `AnalysisPipeline`'s own
   `_prepare_risk_management_context` translation is pipeline-level and
   was deliberately not duplicated into `ServiceSkill` (see module
   docstring, and `SKILL_METADATA_BY_SERVICE["risk_management_service"]`'s
   inline comment). A future Planner driving this skill standalone must
   supply `ENTRY_PRICE` itself (e.g. by first reading `harga`/PRICE from
   `skill.stock_service`'s own output).
6. **A `ServiceRegistry` entry without a matching `SKILL_METADATA_BY_SERVICE`
   entry is silently skipped by `_build_service_skills()`**, not a
   fail-fast error. Never triggers in production today (the L13 audit
   covers exactly the 11 Services `_build_analysis_pipeline` registers;
   `NotificationService` stays unregistered/unwired). Left as an
   explicit, documented branch rather than an implicit `KeyError` — worth
   revisiting if a future stage adds a new Service to the pipeline ahead
   of its own metadata audit (should probably become fail-fast at that
   point, per the same reasoning already applied to the
   `ToolRegistry`-duplicate concern in `_build_service_skills()`'s own
   docstring).
7. **Prior-stage debt (L11/L12, unaffected by L13, still live):**
   `AlwaysApprove`/`InMemoryEventStore` Phase 1 defaults;
   `APPROVAL_POLICY=tool_whitelist` incompatibility with
   `RuntimeAnalysisPipeline`'s UUID-named per-call Tool; exception
   taxonomy differing between `StockAgent`'s Runtime path and fallback
   path; Tool-registry churn from `RuntimeAnalysisPipeline`'s per-call
   UUID Tool. None of these are touched or made worse by L13 — see the
   L11/L12 handovers for full detail.

---

## 5. Files touched (complete list)

**New:**
- `Orchestration/service_skill.py`
- `Tests/test_stage_l13_service_skill.py`
- `Docs/handover_l13.md` (this file)

**Modified (additive only):**
- `Core/composition_root.py`
- `Tests/test_stage_l5_composition_root_integration.py`
- `Tests/test_stage_l6_multi_provider_registry.py`

**Untouched (confirmed, per L13 scope discipline):**
`Core/analysis_pipeline.py`, `Core/runtime.py`, `Agents/executor.py`,
`Agents/sandbox.py`, `Agents/tool_registry.py`,
`Orchestration/runtime_analysis_pipeline.py`,
`Orchestration/analysis_pipeline_adapter.py`, `Agents/stock_agent.py`,
`Core/tool_context_builder.py`, `Core/approval_config.py`,
`Services/base_service.py`, `Services/service_context.py`,
`Services/service_result.py`, `Services/service_registry.py`, all 11
Service implementations, and every other pre-existing test file.

---

## L13 — CLOSED
