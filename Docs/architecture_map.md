
# AIOS Architecture Map

Version: Phase 2 (Sprint 20+)
Status: Source of Truth
Project: AI Operation System (AIOS)

---

# 1. Project Goal

AIOS adalah AI Operating System yang berjalan secara **local-first** dengan dukungan provider lokal (Ollama) dan cloud provider bila diperlukan.

AIOS dibangun menggunakan Clean Architecture, Dependency Injection, dan Regression-Driven Development.

Seluruh autonomous runtime harus berjalan melalui pipeline yang telah ditentukan. Tidak boleh ada shortcut yang melewati pipeline.

---

# 2. High-Level Architecture

```
                        main.py
                           │
                           ▼
                 Core/composition_root.py
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
      Providers         Services       Repository
          │                │                │
          └────────────────┼────────────────┘
                           ▼
                    Orchestration
                           │
            ┌──────────────┼──────────────┐
            ▼                             ▼
       StockAgent                 AutonomousAgent
                                          │
                                          ▼
                                  AutonomousHost
                                          │
                                          ▼
                               AutonomousScheduler
```

---

# 3. Folder Responsibilities

## Core/

Owns:

- Composition Root
- Configuration
- Exceptions
- Logging

Rules:

- Owns dependency injection.
- Creates singleton objects.
- Must not contain business logic.

---

## Providers/

Owns:

- GeminiProvider
- OllamaProvider
- ProviderManager
- ProviderSelector
- Provider capabilities

Rules:

- Only communicates with LLM providers.
- No orchestration logic.
- No business rules.

---

## Services/

Owns domain services.

Examples:

- StockService
- ChartService
- NewsService
- NotificationService
- BacktestService

Rules:

- No provider selection.
- Stateless whenever possible.

---

## Repository/

Owns persistence abstraction.

Rules:

- Database access only.
- No orchestration.

---

## Database/

Owns SQLite persistence.

---

## Orchestration/

Owns AI reasoning.

Contains:

- Planner
- Reflection
- RuntimeAnalysisPipeline
- ExecutionCoordinator
- DecisionEngine
- LearningLoop
- PortfolioEngine
- Memory
- AutonomousAgent
- AutonomousHost
- AutonomousScheduler

This folder is the brain of AIOS.

---

## Agents/

Owns user-facing agents.

Example:

StockAgent

---

## Tests/

Regression tests.

Nothing may be merged unless regression stays green.

---

# 4. Autonomous Runtime

```
AutonomousScheduler
        │
        ▼
AutonomousHost
        │
        ▼
AutonomousAgent
        │
        ▼
RuntimeAnalysisPipeline
        │
        ▼
11 Analysis Components
```

Ownership:

Scheduler
→ queues execution

Host
→ invokes agents

Agent
→ owns lifecycle

Pipeline
→ owns execution

Services
→ perform work

---

# 5. AutonomousAgent State

Maintains:

- status
- iteration_count
- last_cycle_at
- goal
- current_plan
- session_id
- session_started_at

Collaborators:

- RuntimeAnalysisPipeline
- GoalPlanner

Public API:

- step()
- run()
- pause()
- resume()
- stop()
- snapshot()
- restore()
- plan_goal()
- advance_plan()
- set_goal()
- clear_goal()
- start_session()
- end_session()

---

# 6. AutonomousHost

Responsibilities:

- start()
- stop()
- start_all()
- stop_all()

Rules:

- Stateless.
- Never touches pipeline.
- Never owns agent state.

---

# 7. AutonomousScheduler

Responsibilities:

- queue jobs
- tick()
- schedule()
- cancel()
- clear()
- pending_jobs()
- pause()
- resume()

Rules:

- FIFO queue.
- Synchronous.
- No threading.
- No asyncio.
- No timers.
- No persistence.

---

# 8. Runtime Analysis Pipeline

RuntimeAnalysisPipeline is the single execution entry point.

Responsibilities:

- coordinate orchestration
- invoke analysis stages
- aggregate results

Never bypass this pipeline.

---

# 9. Provider Layer

Supported providers:

- Ollama
- Gemini

ProviderManager owns provider registration.

ProviderSelector decides which provider to use.

Business logic must never directly instantiate providers.

---

# 10. Dependency Rules

Allowed:

```
Agents
    ↓
Orchestration
    ↓
Services
    ↓
Repository
    ↓
Database
```

Providers may be used by Services or Orchestration through dependency injection only.

---

# 11. Forbidden Dependencies

Database
→ Orchestration

Database
→ Agents

Repository
→ Providers

Providers
→ Repository

Services
→ Composition Root

AutonomousScheduler
→ RuntimeAnalysisPipeline

AutonomousHost
→ RuntimeAnalysisPipeline

AutonomousHost
→ GoalPlanner

---

# 12. Composition Root

All object creation belongs to:

Core/composition_root.py

Rules:

- Singletons created here.
- Dependency wiring only.
- No business logic.

---

# 13. Testing Strategy

Required:

- Unit Tests
- Regression Tests
- Integration Tests
- E2E Tests

Regression failures block development.

---

# 14. Current AIOS Capabilities

Implemented:

✔ Local LLM (Ollama)

✔ Provider abstraction

✔ RuntimeAnalysisPipeline

✔ Planner

✔ Reflection

✔ Learning Loop

✔ Portfolio Engine

✔ AutonomousAgent

✔ AutonomousHost

✔ AutonomousScheduler

✔ Snapshot / Restore

✔ Goal Planning

✔ Execution Plans

✔ Queue Management

✔ Pause / Resume / Stop lifecycle

---

# 15. Not Yet Implemented

Planned:

- Event Bus
- Task Manager
- World State
- Resource Manager
- Plugin System
- Multi-Agent Coordinator
- Persistent Memory
- Workflow Engine

---

# 16. Development Principles

Every new feature must:

- preserve architecture
- use dependency injection
- avoid duplicate logic
- preserve regression tests
- avoid bypassing RuntimeAnalysisPipeline
- avoid bypassing Composition Root

If a feature requires redesigning existing modules, redesign must be documented and approved before implementation.

---

# 17. Source of Truth

Before implementing any sprint:

1. Read PROJECT_MASTER.md
2. Read ARCHITECTURE_MAP.md
3. Read the relevant Docs/* architecture document
4. Implement one sprint only
5. Keep regression tests green
