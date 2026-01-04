# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Nothing yet

## [0.1.0] - 2026-01-01

### Added

**Core Infrastructure**
- Initial public release of CEMAF (Context Engineering Multi-Agent Framework)
- Core context management with immutable, patch-based provenance tracking
- Token budgeting system with automatic context compilation
- Deterministic run recording and replay capabilities for debugging
- DAG-based orchestration with parallel execution and conditional routing
- Memory management with TTL and strict scoping (SESSION, PROJECT, BRAND, PERSONAE)

**Context Engineering**
- `Context` class with immutable state and patch-based updates
- `ContextPatch` system tracking every change with full provenance
- `PatchLog` for append-only history enabling deterministic replay
- Token budgeting to stay within LLM limits
- `PriorityContextCompiler` for automatic context compilation with priority-based selection
- Advanced compilation with automatic summarization support

**Orchestration**
- `DAGExecutor` for dynamic DAG execution
- `DeepAgent` for hierarchical orchestration
- `Checkpointer` for resumable execution
- Multiple node types: Tool, Skill, Agent, Router, Parallel
- Parallel execution support with concurrent task handling
- Conditional routing based on context values

**Recording & Replay**
- `RunLogger` protocol for comprehensive run recording
- `InMemoryRunLogger` and extensible backend support
- Complete serialization of tool calls, LLM calls, patches, and context states
- `Replayer` with 3 replay modes: PATCH_ONLY, MOCK_TOOLS, LIVE_TOOLS
- Deterministic replay for debugging and validation

**Memory Management**
- 4 memory scopes: SESSION (request-scoped), PROJECT (days), BRAND (permanent), PERSONAE (permanent)
- TTL-based auto-expiration for all memory items
- `MemoryItem` model with rich metadata (source, timestamp, priority)
- Memory search capabilities within scopes
- Hooks for redaction and custom serialization

**Execution Control**
- `ExecutionContext` with `CancellationToken` for cooperative cancellation
- Timeout enforcement with configurable durations
- Graceful shutdown support for long-running operations

**LLM Integration**
- LLM client protocols for OpenAI and Anthropic
- Response parsing utilities for extracting JSON from LLM outputs
- Token estimation with support for tiktoken (OpenAI) and character-based fallback
- Streaming support for LLM responses

**Data Management**
- Caching layer with in-memory, TTL, and Redis backend support
- Vector store integrations with extensible protocol
- Pinecone reference implementation for vector storage
- Persistent storage protocols for PostgreSQL and SQLite

**Tools & Skills**
- Tool registry with dependency injection
- Skill registry with protocol-based extensibility
- MCP (Model Context Protocol) bridge for tool integration
- Atomic, stateless tool functions with automatic recording

**Developer Experience**
- Type-safe context paths with generic support
- Context source management with priority-based selection
- Configuration system with zero-config defaults and .env customization
- Factory patterns for automatic configuration loading from environment
- Comprehensive error handling with structured `Result` types
- Async-first architecture throughout

**Resilience Patterns**
- Retry mechanisms with exponential backoff
- Circuit breaker pattern for fault tolerance
- Rate limiting for API calls
- Event bus for pub/sub messaging
- Structured logging and observability

**Testing & Quality**
- 1,016 tests with 100% code coverage
- Pre-commit hooks with Ruff, MyPy (strict mode), Bandit, and Pytest
- Benchmarking and profiling tools for performance analysis
- Support for Python 3.14+
- Type-checked with mypy --strict
- Security scanning with bandit

**Documentation**
- 32+ documentation files covering all modules
- Architecture overview and design principles
- Quick start guide with zero-config setup
- Integration guide for LangGraph, AutoGen, CrewAI
- HOW_TO_USE.md with detailed patterns and examples
- Module references for all components
- Configuration guide with all environment variables
- API documentation with examples

**Community**
- MIT License for maximum permissiveness
- Contributor Covenant Code of Conduct v2.1
- Comprehensive contributing guidelines with development setup
- Discord community server (https://discord.gg/C8ZXAbD8)
- GitHub issue templates for bugs and feature requests
- Pull request template with quality checklist

**Infrastructure**
- Conventional commit format for all changes
- Semantic versioning for releases
- Continuous integration with pre-commit hooks
- Async-first architecture throughout
- Protocol-based design for pluggable implementations

---

## Version Links

[Unreleased]: https://github.com/drchinca/cemaf/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/drchinca/cemaf/releases/tag/v0.1.0
