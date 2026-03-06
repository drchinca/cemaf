# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `InstrumentedLLMClient` for transparent LLM call recording into RunLogger (PR #23)
- `ProviderRegistry[T]` generic extensible factory registry replacing if/elif chains (PR #24)
- `CancellationToken` support in `DAGExecutor.run()` for cooperative cancellation (PR #25)
- `NodeType.LOOP` and `Node.loop()` for iterative subgraph execution with exit conditions (PR #26)
- `create_token_estimator()` smart factory preferring tiktoken when available (PR #27)
- `compressible` flag in algorithm exclusion details for Greedy and Knapsack (PR #27)
- `context_compiler_registry`, `llm_registry`, `vector_store_registry` — extensible backend registries

### Fixed
- 30+ missing exports added to `__init__.py` across 7 packages: core, context, orchestration, llm, observability, agents, memory (PR #29)
- Redundant `_utc_now` in `result.py` replaced with `core.utils.utc_now` (PR #29)

### Changed
- LLM, context compiler, and retrieval factories now use `ProviderRegistry` instead of if/elif chains
- `ContextNodeExecutor` auto-wraps agents' LLM clients with `InstrumentedLLMClient`
- Test suite expanded from 1464 → 1557 total (1452 unit + 105 integration) covering persistence, cost tracking, rate limiter, resilience decorators, core/registry, and DAG executor (PRs #29, #30)
- CI pipeline added: lint, type-check, security scan, tests with coverage on every push/PR (PR #31)

## [0.2.0] - 2026-02-19

**Glass Box Architecture Enhancement**

Scientific-grade audit trail, provenance tracking, and full token accountability for production datalake-scale workloads.

**Added:**
- `ProvenanceChain` and `ProvenanceLink` for cross-referencing every artifact in a DAG run (LLM calls, context sources, citations, costs)
- `DomainContext` for domain-scoped business rules, vocabulary constraints, and citation style requirements
- `VerificationStatus` enum (UNVERIFIED, VERIFIED, DISPUTED, RETRACTED) for citation verification
- `ExclusionReason` enum (BUDGET_EXCEEDED, LOW_PRIORITY, STALE, DUPLICATE, FILTERED) for context source tracking
- `BudgetGuard` with configurable warning/critical/halt thresholds for cost and token enforcement across DAG runs
- `GlassBoxReporter` generating complete audit reports: decision traces, token audits, cost breakdowns, citation coverage verification
- `ContextNodeExecutor` bridging DAG nodes to agents via dynamic registry with provenance threading
- Dynamic `AgentRegistry` extending `BaseRegistry[Agent]` with domain-scoped lookups and auto-generated capabilities
- Autonomous `Planner` with LLM-based DAG generation and domain context injection
- Context engineering agents: Librarian, Researcher, Summarizer, Writer
- Parallel RLM chunk processing via `asyncio.gather` for divide-and-conquer branches
- Partial coverage fallback for RLM when max depth or single large chunk is reached
- Enhanced `LLMCall` and `ToolCall` with node_id, agent_id, context_sources_used, context_hash, budget_utilization, cost_usd, provenance_link_id
- Enhanced `RunRecord` with total_cost_usd, provenance_chain, selection_summaries
- Model pricing for claude-opus-4-6, claude-sonnet-4-6, gpt-4o, o1, o3 with cache pricing
- Token budget `utilization` and `headroom` properties
- Structured exclusion details in Greedy and Knapsack context selection algorithms
- `record_context_compilation()`, `record_budget_utilization()`, `record_citation_event()` metrics helpers
- `coverage_ratio` field on `RecursiveQueryResult`
- `DomainID`, `TenantID`, `ProvenanceID` NewType identifiers

**Changed:**
- `CitedFact.verification_status` uses `VerificationStatus` enum instead of raw string
- Citation protocol methods aligned to sync (matching tracker.py implementation)
- `Citation` model extended with `retrieved_at`, `agent_id`, `node_id`, `context_path`, `provenance_link_id`
- `DAGExecutor` accepts optional `budget_guard` parameter for cost enforcement
- RLM engine uses parallel processing instead of sequential left/right queries
- RLM fallback processes budget-sized batches instead of only the first chunk

**Stats:** 1464 tests | 100% passing | 47 files changed | +5,796 lines

## [0.1.0] - 2026-01-01

**Initial Alpha Release**

CEMAF provides infrastructure for building AI agent systems with context management, token budgeting, and deterministic replay.

**Core Features:**
- Context patches with provenance tracking
- Token budgeting and automatic compilation
- Deterministic run recording and replay
- DAG-based orchestration
- Memory management with scoping and TTL
- Framework-agnostic design (works with LangGraph, AutoGen, CrewAI)

For complete documentation, see [README.md](README.md) and [docs/](docs/).

**Note**: This is an Alpha release. APIs may change based on feedback.

---

[Unreleased]: https://github.com/drchinca/cemaf/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/drchinca/cemaf/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/drchinca/cemaf/releases/tag/v0.1.0
