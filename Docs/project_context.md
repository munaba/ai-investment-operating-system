
# AI Investment Platform — Project Context

> **Version:** 1.0
> **Status:** Active Development

---

# Project Vision

This project is **NOT** a prototype.

It is a long-term software engineering project intended to become a professional **Investment Intelligence Platform** capable of supporting multiple financial markets and multiple AI agents.

The goal is to build a platform that can continuously evolve for years without requiring major architectural rewrites.

---

# Long-Term Goals

The platform should eventually support:

* Indonesian Stocks
* US Stocks
* Forex
* Cryptocurrency
* ETFs
* Commodities
* Bonds

Future capabilities include:

* AI Market Analysis
* Portfolio Management
* Decision Engine
* Learning Engine
* Auto Research
* Auto Screening
* Auto Backtesting
* Risk Management
* AI Investment Advisor
* Multi-Agent Collaboration

---

# Core Philosophy

The LLM is **NOT** the decision maker.

The Decision Engine produces structured investment decisions.

The LLM explains, summarizes, and communicates those decisions to users.

Deterministic logic should always remain outside the LLM whenever possible.

---

# Architecture Principles

The project follows:

* Clean Architecture
* SOLID Principles
* Dependency Injection
* Separation of Concerns
* Composition over Inheritance
* Testability First
* Backward Compatibility

Every architectural change should improve maintainability and scalability.

---

# Current Architecture

Current layers:

Agents/

↓

Orchestration/

↓

Services/

↓

Repositories (planned)

↓

Providers/

↓

External APIs

---

# Current Status

Completed:

* Multi-Agent Foundation
* AnalysisPipeline
* ServicePipeline
* Tool Context Builder
* Technical Analysis Services
* Scoring Services
* Risk Services
* MarketAnalysisAgent
* IDXStockAgent
* Testing Infrastructure

All existing tests should continue passing after every architectural change.

---

# Roadmap

## Sprint 1

Foundation

Completed

---

## Sprint 2

Multi-Agent Foundation

Completed

---

## Sprint 3

Repository Layer

Current Sprint

---

## Sprint 4

Decision Engine

Planned

---

## Sprint 5

Portfolio Engine

Planned

---

## Sprint 6

Learning Engine

Planned

---

## Sprint 7

Plugin System

Planned

---

## Sprint 8

Cloud Deployment

Planned

---

# Folder Responsibilities

## Agents

High-level AI agents.

Responsibilities:

* Coordinate work
* Receive requests
* Call orchestration layer

Agents should NOT contain business logic.

---

## Orchestration

Coordinates workflows.

Responsibilities:

* Pipeline execution
* Tool ordering
* Context building
* Agent orchestration

No market-specific logic.

---

## Services

Business logic layer.

Responsibilities:

* Technical analysis
* Fundamental analysis
* Scoring
* Risk analysis
* Pattern detection

Services must never communicate directly with external providers.

---

## Repositories (Planned)

Data access layer.

Responsibilities:

* Yahoo Finance
* Binance
* Bybit
* Finnhub
* Polygon
* AlphaVantage
* TradingView

Repositories normalize external data.

Repositories hide provider implementation details.

---

## Providers

LLM providers.

Examples:

* Gemini
* OpenAI
* Anthropic

Providers should never contain business logic.

---

## Core

Shared infrastructure.

Examples:

* Config
* Logger
* Exceptions
* Utilities

---

# Dependency Rules

Allowed:

Agent

↓

Orchestration

↓

Service

↓

Repository

↓

Provider / External API

Forbidden:

Service → Agent

Repository → Service

Provider → Service

Agent → External API

Business logic inside Providers

---

# Dependency Injection Rules

Always prefer constructor injection.

Avoid global mutable state.

Singletons are allowed only when they represent infrastructure services.

---

# Backward Compatibility

Every architectural refactor must preserve:

* Existing public APIs
* Existing constructors
* Existing tests
* Existing outputs

Breaking changes must be explicitly documented.

---

# Testing Rules

Every new feature should include tests when appropriate.

Before completing any task:

* Smoke tests
* Integration tests
* End-to-end tests

must continue passing.

No architectural change is considered complete until tests pass.

---

# Coding Guidelines

Prefer:

Small classes.

Single Responsibility Principle.

Explicit dependencies.

Reusable components.

Readable code over clever code.

Avoid:

Large God Classes.

Duplicated logic.

Circular dependencies.

Hidden coupling.

Hard-coded provider calls.

Deep inheritance hierarchies.

---

# Current Priorities

1. Repository Layer
2. Decision Engine
3. Domain Models
4. Portfolio Engine
5. Learning Engine
6. Plugin System
7. Cloud Deployment

---

# Definition of Success

The project should eventually become a production-quality AI Investment Platform capable of:

* Multi-market analysis
* Multi-agent collaboration
* Deterministic investment decisions
* Explainable AI
* Continuous evolution without architectural rewrites

Every new feature should move the project closer to that vision.
