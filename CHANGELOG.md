# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

**Evals System (PRs #61-65)**
- `OnlineEvalPipeline` subscribing to TASK_COMPLETED events with GATE/OBSERVE modes
- `HierarchicalJudge` with three-tier cascade: deterministic → semantic → LLM judge
- `QualityPolice` with rolling window, anomaly detection, and halt gate
- `RunEvalTool`, `CheckQualityTool`, `RecordScoreTool` as CEMAF tools
- `QualityGuardAgent` registered in AgentRegistry for self-evaluation
- Shared test fakes in `tests/unit/evals/conftest.py`

**OpenViking Enhancements (PRs #67-71)**
- `MemoryDeduplicator` protocol and `SemanticDeduplicator` (exact key + embedding similarity)
- `ContextType` enum (RESOURCE/MEMORY/SKILL) with `ContextTypeBehavior` rules
- `TieredMemoryStore` with L0/L1/L2 progressive retrieval
- `ScopePath` and `PropagatingScorer` for hierarchical scope propagation
- `ExtractionPipeline` and `RuleBasedExtractor` for post-session memory extraction

**Production Backends (PRs #74-76)**
- `StructuredLogger` with JSON-lines output
- `PrometheusMetrics` with lazy metric registration and `generate_metrics()`
- `SqliteMemoryStore` backed by aiosqlite
- `OpenAIEmbeddingProvider` using text-embedding-3-small
- `ResilientLLMClient` with retry, circuit breaker, and rate limiting
- VectorStore injectable in `create_memory_manager`

**Architecture (PRs #58-59)**
- `RuntimeServices` frozen dataclass bundling 16 optional runtime deps
- `bootstrap.create_executor()` composition root
- Node-type handlers extracted to `orchestration/node_handlers.py`

**Web (PR #77)**
- FastAPI architecture advisor using CEMAF's own agent stack

**Infrastructure (PRs #23-31)**
- `InstrumentedLLMClient` for transparent LLM call recording into RunLogger (PR #23)
- `ProviderRegistry[T]` generic extensible factory registry replacing if/elif chains (PR #24)
- `CancellationToken` support in `DAGExecutor.run()` for cooperative cancellation (PR #25)
- `NodeType.LOOP` and `Node.loop()` for iterative subgraph execution with exit conditions (PR #26)
- `create_token_estimator()` smart factory preferring tiktoken when available (PR #27)
- `compressible` flag in algorithm exclusion details for Greedy and Knapsack (PR #27)
- `context_compiler_registry`, `llm_registry`, `vector_store_registry` — extensible backend registries

### Fixed

**P0 Bugs**
- Session cascade bootstrap failure with proper recall query (PR #58)
- Loop `UnboundLocalError` in DAGExecutor (PR #60)
- `Context.set()` now uses `copy.deepcopy()` for nested dict immutability (PR #60)
- Dead online eval pipeline not receiving events (PR #63)
- Decorative thresholds in QualityPolice having no effect (PR #63)
- Swallowed errors hiding evaluation failures (PR #63)
- `scope_path` bug in `PropagatingScorer` causing incorrect ancestor queries (PR #73)

**P1 Bugs**
- Anthropic adapter: tool results, stream tool_use events, assistant tool_call blocks (PR #58)
- `datetime.now()` replaced with `utc_now()` everywhere (PR #60)
- Tiered store scope_path propagation (PR #73)
- MEMORY_EXTRACTED event missing output field (PR #73)
- P1/P2 type safety and dead code removal (PR #65)

**P2 Fixes**
- Session dispose scoped cleanup (PR #73)
- Zero-assertion tests replaced with proper checks (PR #60)
- Exception swallowing in EventBus handlers (PR #60)

**Integration & DI Gaps (PRs #72, #76)**
- `ContextTypeClassifier` protocol added
- `TieredMemoryStore` → `ContextProvider` wiring
- Factory gaps closed for extraction pipeline, scope scorer, session manager
- 30+ missing exports added to `__init__.py` across 7 packages: core, context, orchestration, llm, observability, agents, memory (PR #29)
- Redundant `_utc_now` in `result.py` replaced with `core.utils.utc_now` (PR #29)

### Changed
- MCP bridges consolidated to `mcp/bridges/` (PR #60)
- `ToolSchema.to_definition()` bridges tools → LLM protocols (PR #60)
- Singleton pattern removed from AgentRegistry (PR #60)
- Agentic DAG integration tests with real agents, eval pipeline, and quality police (PR #66)
- LLM, context compiler, and retrieval factories now use `ProviderRegistry` instead of if/elif chains
- `ContextNodeExecutor` auto-wraps agents' LLM clients with `InstrumentedLLMClient`
- Test suite expanded from 1464 → 1557 → 2118+ tests (PRs #29, #30, #57-76)
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
