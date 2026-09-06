
# AIOS

AI Operation System

Version
Current Phase
Current Sprint
Project Status

---

# Vision

Apa tujuan AIOS.

---

# Design Principles

- Clean Architecture
- SOLID
- DI
- Test First
- No duplicated logic
- Runtime driven
- Local First
- Ollama First

---

# Current Architecture

ApplicationGraph

↓

Agents

↓

Orchestration

↓

Services

↓

Database

↓

Providers

↓

LLM

---

# AI Runtime

Runtime

Executor

Planner

Memory

Approval

RuntimeAnalysisPipeline

AutonomousAgent

AutonomousHost

AutonomousScheduler

---

# Autonomous Stack

Sprint 1–20 summary

Sprint 1
...

Sprint 2
...

...

Sprint 20
...

---

# Dependency Graph

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
11 Orchestration Components

---

# Providers

Gemini

Anthropic

Ollama

Future

OpenAI

DeepSeek

Mistral

---

# Memory System

Conversation

Knowledge

Embeddings

ChromaDB

Future Long-term Memory

---

# Tool System

ToolRegistry

Executor

Runtime

ServicePipeline

AnalysisPipeline

---

# Current Capabilities

✅ Market Analysis

✅ Technical Analysis

✅ Fundamental Analysis

✅ Portfolio Engine

✅ Risk Engine

✅ Reflection

✅ Learning

✅ Autonomous Runtime

✅ Scheduler

---

# Not Yet Implemented

Plugin Marketplace

Web Agent

Desktop Agent

Filesystem Agent

Email Agent

Browser Agent

Voice Agent

GUI Agent

Persistent Sessions

Distributed Agents

---

# Development Rules

Tidak boleh:

- duplicate logic
- bypass Runtime
- bypass Pipeline
- bypass Composition Root

Semua dependency harus DI.

Semua fitur wajib regression test.

---

# Testing Rules

Smoke

Integration

E2E

Regression

Tidak boleh ada regression.

---

# Coding Rules

Single Responsibility

Composition

Immutable Result Objects

Thin Orchestration

No God Objects

---

# Roadmap

Phase 1
Foundation

✔

Phase 2
Autonomous Runtime

✔

Phase 3
Persistent Intelligence

Next

Phase 4
Plugin Ecosystem

Future

Phase 5
Distributed AIOS

Future

---

# Current Project Health

Architecture

Stable

Regression

PASS

Runtime

PASS

Providers

PASS

Autonomous Runtime

PASS

Scheduler

PASS

Known historical failures

2 (legacy ApplicationGraph field-list tests)

---

# How New Development Works

Every future sprint must

Read PROJECT_MASTER.md

Read related architecture docs

Implement one sprint only

Never redesign existing modules

Never duplicate logic

Keep all regression tests green
