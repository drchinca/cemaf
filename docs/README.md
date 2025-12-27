# CEMAF Documentation

**Context Engineering Multi-Agent Framework**

Welcome to the CEMAF documentation. This guide is organized by module for easy navigation.

## 📚 Documentation Index

### Getting Started
- [Quick Start Guide](quickstart.md) - Installation and first steps
- [Architecture Overview](architecture.md) - System design and components

### Core Modules
- [Core](core.md) - Types, enums, Result pattern, utilities
- [Context Management](context.md) - TokenBudget, Compiler, AdvancedContextCompiler
- [Memory](memory.md) - MemoryStore protocols and scopes

### Execution Layer
- [Tools](tools.md) - Atomic, stateless functions
- [Skills](skills.md) - Composable capabilities
- [Agents](agents.md) - Autonomous entities with goals
- [Orchestration](orchestration.md) - DAG, Executor, DeepAgent, Checkpointing

### Infrastructure
- [LLM](llm.md) - LLM client protocols and adapters
- [Retrieval](retrieval.md) - Vector stores and embeddings
- [Streaming](streaming.md) - SSE and stream buffers
- [Generation](generation.md) - Image, audio, video, UI, code generation

### Supporting Modules
- [Resilience](resilience.md) - Retry, CircuitBreaker, RateLimiter
- [Events](events.md) - Event bus and notifiers
- [Cache](cache.md) - Caching with TTL and eviction
- [Validation](validation.md) - Validation rules and pipelines
- [Scheduler](scheduler.md) - Job scheduling and triggers
- [Config](config.md) - Configuration management
- [Observability](observability.md) - Logger, Tracer, Metrics
- [Persistence](persistence.md) - Entities (Project, Run, Artifact)
- [Evals](evals.md) - Evaluators and LLM-as-judge

## 🚀 Quick Links

- [Installation](quickstart.md#installation)
- [Define a Tool](tools.md#defining-a-tool)
- [Build a DAG](orchestration.md#building-dags)
- [Context Management](context.md#context-class)
- [Result Pattern](core.md#result-pattern)

## 📊 Project Stats

- **426 tests** | **55 fixtures** | **TDD from day one**
- **MIT License**

