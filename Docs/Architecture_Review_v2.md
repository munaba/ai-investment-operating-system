# Architecture Review v2 — Decision Pipeline

## 1. Current Decision Pipeline

```
Reflection → DecisionEngine → DecisionPolicy → PolicyGuard → ExecutionIntent
```

## 2. Component Responsibilities

**Reflection (L18)** — Reflects over a batch of `MemoryRecord` history and produces an immutable `ReflectionRecord` summarizing that batch (count and timestamp), decoupled from how Memory is stored.

**DecisionEngine (L19)** — Maps a composite score to a `Decision` (action, confidence, rationale) using fixed deterministic thresholds.

**DecisionPolicy (L20)** — Maps a `Decision`'s action to a `DecisionPolicyResult`, translating it into concrete entry/exit permissions, position sizing, and risk level.

**PolicyGuard (L21)** — Validates a `DecisionPolicyResult` against a fixed set of guard-rail rules (entry/exit conflicts, position-size bounds, valid risk level), producing an approved/rejected `PolicyGuardResult` with explicit violations.

**ExecutionIntent (L22)** — Converts an approved `PolicyGuardResult` into a structured, immutable "ready for execution" intent, or an explained denial when not approved. Does not execute anything.

## 3. Design Principles

- **Additive architecture** — every stage is a pure addition to the object graph; no existing component, API, or behavior is modified.
- **Stateless** — no component holds instance attributes; every instance is safe to reuse across calls.
- **Deterministic** — identical input always produces an identical, equal output.
- **No LLM inside the decision pipeline** — Reflection through ExecutionIntent contain zero LLM calls or Provider dependencies.
- **Composition-root construction only** — each component is constructed in `Core/composition_root.py` and exposed on `ApplicationGraph`; none is wired into `StockAgent`, `RuntimeAnalysisPipeline`, or any other pipeline stage.
- **No runtime coupling** — no component imports or references `Core.runtime.Runtime`, `Executor`, `Database`, or `Memory`.
- **Dependency inversion preserved** — each stage accepts its predecessor's output purely by duck typing (matching attribute shape), never by importing the predecessor's module or class.

## 4. Current Project Status

**Decision Pipeline v1 — COMPLETE.**
All five stages (L18–L22) are implemented, composition-root wired, individually tested, and verified against the full integration and E2E regression suite. This is the frozen production baseline.

## 5. Next Milestones

- **L23** — ExecutionPlanner
- **L24** — ExecutionCoordinator
- **L25** — PortfolioEngine
- **L26** — PortfolioRisk
- **L27** — LearningLoop
- **L28** — AutonomousAgent
