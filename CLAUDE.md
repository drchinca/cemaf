# CEMAF Project Instructions

## Architecture Overview

CEMAF is a **protocol-first, multi-agent orchestration framework** for context engineering. It has two layers:

> **Target architecture**: SPEC-00..06 (`docs/specs/SPEC-00-enterprise-context-brain.md` and siblings) define the Enterprise Context Brain — the umbrella architecture this codebase is converging toward (interceptor pipeline, datasource registry, blueprint-as-LLM-input, task state machine, guardian mesh, self-resolving DAG). For where each spec concept lands in the codebase and the phased build-out, see [`docs/architecture/spec-module-map.md`](docs/architecture/spec-module-map.md).

### Layer 1: Base Framework (the engine)

The base framework provides composable primitives for building multi-agent systems. Every integration point is a `@runtime_checkable` Protocol — bring your own LLM, vector store, memory backend, etc.

```
┌─────────────────────────────────────────────────────────────┐
│                     ORCHESTRATION                            │
│  DAGExecutor → topological sort → node dispatch → context    │
│  ContextNodeExecutor → agent resolution → goal building      │
│  RuntimeServices → 16 optional deps, frozen dataclass        │
│  bootstrap.create_executor() → composition root              │
└──────────────┬──────────────────────────────────┬────────────┘
               │                                  │
    ┌──────────▼──────────┐          ┌────────────▼────────────┐
    │   AGENT LAYER       │          │   INFRASTRUCTURE        │
    │                     │          │                         │
    │  Agent[GoalT,       │          │  EventBus (pub/sub)     │
    │    ResultT] protocol│          │  MemoryManager          │
    │  AgentRegistry      │          │    (semantic+episodic)  │
    │  Tool protocol      │          │  ContextCompiler        │
    │  ToolRegistry       │          │    (token budgets)      │
    │  Skill protocol     │          │  EvalPipeline           │
    │                     │          │    (quality police)     │
    │  Built-in agents:   │          │  Resilience             │
    │    Librarian         │          │    (retry+breaker)     │
    │    Researcher        │          │  Observability         │
    │    Summarizer        │          │    (structured logs)   │
    │    Writer            │          │  VectorStore           │
    │    QualityGuard      │          │  LLMClient             │
    └─────────────────────┘          └─────────────────────────┘
```

**Entry point**: `bootstrap.create_executor(agent_registry=, services=) → DAGExecutor`

**Execution flow**: `DAGExecutor.run(dag)` → topological sort → for each node: resolve agent from registry → build goal from input_mapping → `agent.run(goal, context)` → store output in context → next node reads it.

### Layer 2: Self-Hosting Engine (CEMAF's first client)

Three opt-in modules where CEMAF uses its own primitives to introspect, audit, and extend itself. **Fully decoupled** — zero base framework modules import from these. Dependency arrow is strictly one-way.

```
┌─────────────────────────────────────────────────────────────┐
│                  SELF-HOSTING LAYER                           │
│                                                              │
│  meta/              audit/              knowledge/            │
│  ├─ agents.py       ├─ subscriber.py    ├─ graph.py          │
│  │  MetaArchitect   │  EventBusAudit    │  MemoryBackedKG    │
│  │  MetaSynthesizer │  Log → AuditEntry │  entities as       │
│  │  MetaAuditor     ├─ trail.py         │  MemoryItems       │
│  │  MetaKG Agent    │  quality trends   ├─ protocols.py      │
│  ├─ tools.py        │  z-score anomaly  │  KnowledgeGraph    │
│  │  Introspect      │  detection        │  protocol          │
│  │  GenerateDAG     ├─ protocols.py     └──────────┬─────────┘
│  │  TraceAnalyzer   │  AuditLog,                   │
│  │  KGTool          │  AuditTrail                   │
│  ├─ dags.py         │  protocols                    │
│  │  self_audit      └──────────┬────────────────────┘
│  │  feature_synth              │
│  │  kg_refresh                 │ consumes (never imported by)
│  ├─ bootstrap.py               │
│  │  create_meta_               ▼
│  │  executor()     ┌──────────────────────┐
│  └─ registry.py    │   BASE FRAMEWORK     │
│                    │   (Layer 1)          │
│                    └──────────────────────┘
└─────────────────────────────────────────────────────────────┘
```

**Entry point**: `meta.bootstrap.create_meta_executor()` — wraps `create_executor()`, auto-creates audit system from EventBus, KG from MemoryManager, registers 4 meta-agents + 4 meta-tools.

**How it works**: Meta-agents are standard `Agent[GoalT, ResultT]` implementations. They use meta-tools (standard `Tool` ABC) to interact with CEMAF internals. Everything runs through the same `DAGExecutor` — no special execution paths.

| Meta-Agent | What It Does | Tools It Uses |
|-----------|-------------|--------------|
| `MetaArchitect` | Designs DAG pipelines from feature descriptions | IntrospectRegistryTool, GenerateDAGTool |
| `MetaSynthesizer` | Generates CEMAF agent Python source from templates | None (template-based) |
| `MetaAuditor` | Analyzes execution traces for quality/anomalies | TraceAnalyzerTool |
| `MetaKnowledgeGraph` | Queries/refreshes the entity knowledge graph | KnowledgeGraphTool |

| Pre-built DAG | Flow | Purpose |
|--------------|------|---------|
| `self_audit` | MetaAuditor → audit_report | Audit recent execution quality |
| `feature_synthesis` | MetaArchitect → MetaSynthesizer | Design + generate new agent |
| `knowledge_refresh` | MetaAuditor → MetaKnowledgeGraph | Extract execution data into KG |

## Testing Discipline

**CRITICAL**: Every feature requires THREE levels of testing:

1. **Contract tests (TDD)** — Define interfaces/protocols first, write 2-3 contract tests before implementing
2. **Unit tests** — Test each module in isolation with mocks/fakes
3. **Integration tests** — Test actual wiring between modules to verify they work together end-to-end

### Integration Testing Rules

- Unit tests alone are insufficient. If module A produces output that module B consumes, there MUST be an integration test that wires A → B with real implementations (not mocks)
- Integration tests live in `tests/integration/` mirroring the module pairs they test (e.g., `tests/integration/test_memory_context.py`)
- When adding a bridge, adapter, or cross-module factory, the PR is NOT complete until integration tests prove the seam works
- A `to_*()` bridge method without a test that actually feeds its output into the target system is a dead-end seam, not an integration

### Examples of Required Integration Tests

| Feature | Integration Test |
|---------|-----------------|
| SemanticMemoryStore | Memory store + VectorStore + EmbeddingProvider wired together, store and search round-trip |
| CompactedMemory.to_context_source() | Compact memory items → feed into ContextCompiler → verify compiled output |
| SessionManager lifecycle | Bootstrap → ingest → compact → verify context sources are usable |
| MemoryManager + EventBus | Remember items → verify events actually published and receivable |
| TieredMemoryStore → ContextProvider | Store with tiers → progressive_search → verify tiered results usable as context sources |
| ExtractionPipeline → MemoryStore | Run extraction on session data → verify promoted items land in persistent store |
| ResilientLLMClient | Wire retry + circuit breaker + rate limiter → verify call survives transient failures |
| StructuredLogger | Log with context → verify JSON lines output with correct fields |
| Deduplicator → MemoryStore | Store item → store near-duplicate → verify dedup resolution (skip/merge) |
| SqliteMemoryStore | set → get → list_by_scope → cleanup_expired round-trip with real SQLite |
| Self-Audit DAG | create_meta_executor → DAGExecutor.run(self_audit_dag) → verify audit report in final_context |
| Feature Synthesis | ArchitectAgent → AgentSynthesizer chaining → verify generated code passes ast.parse() |
| Knowledge Refresh | MetaAuditor → KnowledgeGraphAgent → verify both outputs propagate through context |
| Quality Degradation | Seed good + bad scores → run self_audit_dag → verify anomaly detected in report |
| Registry Introspection | MetaArchitect discovers meta-agents → includes them in generated DAG |
| Hub & Spoke KG | HubKnowledgeGraph over real MemoryBackedKnowledgeGraph + real EventBus → write → spoke evicts → re-read returns fresh value (`test_hub_spoke_kg.py`) |
| Failure-Feedback Loop | IterationLoop + real ShellSandbox + RunTestsSkill → fail-then-pass fixture → verify re-attempt converges (`test_iteration_sandbox.py`) |
| Auction Agent Selection | Real registry + DefaultAgentSelector + executor + BudgetGuard → two WRITE agents compete → low-load winner runs, recorded in metadata; static node unaffected (`test_agent_auction.py`) |
| Agent Council | Real council members + executor + DefaultVoteAggregator → deliberate → vote → winning choice becomes NodeResult.output (steers DAG); no-decision = success+empty; full DAGExecutor.run (`test_agent_council.py`) |
| Blueprint Harvest | `create_blueprint_harvester()` + real EventBus → high-scoring run distilled into a reusable blueprint, discoverable by `library.search` (`test_blueprint_harvest_factory.py`) |

## Pattern Reference

### Protocol-First Design

All integration points are `@runtime_checkable` Protocol classes. Implementations are structural (no inheritance required). This enables BYO-X: bring your own embedding provider, LLM client, memory store, etc.

```python
@runtime_checkable
class MemoryDeduplicator(Protocol):
    async def find_duplicates(self, candidate: MemoryItem, *, threshold: float = 0.85) -> tuple[DuplicateMatch, ...]: ...
    async def resolve(self, candidate: MemoryItem, matches: tuple[DuplicateMatch, ...]) -> DeduplicationResult: ...
```

### Factory Pattern

Every module exposes `create_*()` factories with optional dependencies and sensible defaults. Config-from-env variants read `CEMAF_*` environment variables.

```python
manager = create_memory_manager(memory_store=SqliteMemoryStore(db_path="prod.db"))
client = create_resilient_client(client=anthropic_client, metrics=prometheus)
```

### RuntimeServices

Frozen dataclass bundling all optional runtime dependencies. Injected into `ContextNodeExecutor` and `DAGExecutor`.

| Group | Field | Type |
|-------|-------|------|
| Observability | `run_logger` | `RunLogger \| None` |
| Observability | `event_bus` | `EventBus \| None` |
| Observability | `health_monitor` | `HealthMonitor \| None` |
| Observability | `budget_guard` | `BudgetGuard \| None` |
| Quality | `online_eval_pipeline` | `OnlineEvalPipeline \| None` |
| Quality | `quality_police` | `QualityPolice \| None` |
| Memory | `memory_manager` | `MemoryManager \| None` |
| Memory | `session_manager` | `SessionManager \| None` |
| Content Safety | `moderation_pipeline` | `ModerationPipeline \| None` |
| Context | `context_compiler` | `ContextCompiler \| None` |
| Context | `token_budget` | `TokenBudget \| None` |
| Context | `domain_context` | `DomainContext \| None` |
| LLM + Retrieval | `llm_client` | `LLMClient \| None` |
| LLM + Retrieval | `vector_store` | `VectorStore \| None` |
| Recovery | `auto_heal_manager` | `AutoHealManager \| None` |

### Result Pattern

`Result[T]` wraps success/failure without exceptions. Used across tool execution and eval returns.

```python
return Result.ok(data=eval_result.to_dict())
return Result.fail(error="Rate limit exceeded")
```

### Event-Driven Architecture

`EventBus` pub/sub with typed `EventType` enum. Components subscribe to events (TASK_COMPLETED, EVAL_COMPLETED, QUALITY_ALERT, MEMORY_EXTRACTED) and react asynchronously.

### Data Conventions

- All value objects: `@dataclass(frozen=True, slots=True)` or `frozen=True`
- IDs: `NewType` wrappers (`AgentID`, `ToolID`, `TokenCount`, `Confidence`)
- Timestamps: `utc_now()` from `core.utils`, never `datetime.now()`
- Configs: Pydantic `BaseModel` with `model_config = {"frozen": True}`

## Module Map

### Core (types, patterns, utilities)

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `core` | Domain types, enums, Result[T], utc_now(), generate_id() | `types.py`, `enums.py`, `result.py`, `utils.py` |
| `config` | Settings, env loading, provider registry | `protocols.py`, `factories.py` |

### Agent System (who does the work)

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `agents` | Agent[GoalT, ResultT] ABC, AgentRegistry, built-in agents (Librarian/Researcher/Summarizer/Writer), opt-in auction selection (SPEC-09) | `base.py`, `registry.py`, `context_agents.py`, `selection.py` |
| `council` | Deliberative multi-agent decisions (SPEC-10) — N members vote, pluggable VoteAggregator (majority/weighted/quorum/unanimous), ballot provenance | `council.py`, `aggregator.py`, `protocols.py`, `types.py` |
| `skills` | Skill protocol + built-in kits. `skills/coding/` is the polyglot file/shell/test kit a coding loop calls | `base.py`, `protocols.py`, `coding/` |
| `tools` | Tool ABC, ToolSchema, ToolRegistry, @tool decorator | `base.py`, `registry.py` |
| `sandbox` | `ShellSandbox` — cwd-confined, time/output-bounded, env-scrubbed, network-screened subprocess execution (the polyglot substrate) | `shell.py` |
| `state` | `StateMachine` FSM primitive — domain-neutral state + transition modelling | `fsm.py` |

> **Substrate, not application.** `sandbox` + `skills/coding` are generic capabilities — they execute commands and manipulate files inside a confined workspace, but they do not decide *what* to build. Spec→code orchestration (the agent loop that reads a spec and drives these skills until tests pass) lives in the `iccha_autonomy` control plane, which depends on CEMAF. Keep that boundary: CEMAF stays domain- and task-agnostic.

### Orchestration (how work gets coordinated)

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `orchestration` | DAGExecutor, ContextNodeExecutor, RuntimeServices, node handlers | `executor.py`, `context_node_executor.py`, `services.py`, `dag.py` |
| `blueprint` | Semantic blueprint definitions for structured generation + the harvest flywheel (learn reusable blueprints from high-scoring runs via `create_blueprint_harvester()`) | `core.py`, `parser.py`, `library.py`, `harvest.py`, `harvest_defaults.py`, `factories.py` |
| `scheduler` | Task scheduling | `base.py`, `protocols.py` |

### Context Engineering (what agents know)

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `context` | Immutable Context, ContextCompiler, token budgets, patches (provenance) | `context.py`, `compiler.py`, `budget.py`, `patch.py`, `source.py` |
| `memory` | Semantic + episodic memory, tiered storage, dedup, extraction, session | `base.py`, `manager.py`, `semantic.py`, `session.py`, `sqlite_store.py` |
| `retrieval` | VectorStore, EmbeddingProvider protocols | `protocols.py`, `memory_store.py` |
| `rlm` | Recursive Language Model — divide-and-conquer large context queries | `base.py`, `protocols.py` |

### LLM Integration (talking to models)

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `llm` | LLMClient protocol, Anthropic / OpenAI-compat / Ollama adapters, resilient wrapper, complexity-based ModelRouter | `protocols.py`, `anthropic.py`, `openai_compat.py`, `ollama.py`, `resilient.py`, `model_router.py`, `factories.py` |
| `mcp` | Model Context Protocol bridges and adapter | `bridges/`, `adapter.py` |
| `generation` | Content generation strategies | `base.py`, `protocols.py` |
| `streaming` | Streaming response handling | `base.py`, `protocols.py` |

### Quality & Safety (keeping things correct)

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `evals` | Evaluation framework — deterministic, semantic, LLM judge, online pipeline, QualityPolice | `protocols.py`, `hierarchy.py`, `online.py`, `police.py`, `tools.py` |
| `iteration` | Failure-feedback loop (SPEC-08) — pytest/ruff/mypy parsers → `FailureSignal` → bounded `IterationLoop` re-attempts. Per-task substrate, not a RuntimeService | `loop.py`, `parsers.py`, `protocols.py`, `types.py` |
| `moderation` | Content safety pipeline | `pipeline.py`, `protocols.py` |
| `validation` | Input/output validation | `base.py`, `protocols.py` |
| `citation` | Source citation tracking | `base.py`, `tracker.py` |

### Infrastructure (operational concerns)

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `events` | EventBus pub/sub with typed EventType enum | `protocols.py`, `bus.py` |
| `observability` | StructuredLogger (JSON lines), PrometheusMetrics, health, run logger | `protocols.py`, `structured.py`, `prometheus_metrics.py` |
| `resilience` | Retry, circuit breaker, rate limiter | `retry.py`, `circuit_breaker.py`, `rate_limiter.py` |
| `persistence` | Run/entity persistence | `entities.py`, `protocols.py` |
| `cache` | Result caching with TTL | `base.py`, `protocols.py` |
| `replay` | Execution replay and debugging | `base.py`, `protocols.py` |
| `ingestion` | Data ingestion pipelines | `base.py`, `protocols.py` |

### Self-Hosting Layer (CEMAF introspects itself)

These modules are **opt-in consumers** of the base framework. No base module imports from them.

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `audit` | Structured audit trail — EventBus subscriber → AuditEntry, quality trend, z-score anomaly detection | `subscriber.py`, `trail.py`, `protocols.py`, `models.py` |
| `knowledge` | Knowledge graph — entities/relations backed by MemoryManager; hub-and-spoke caching (SPEC-07) for bounded-LRU point-read acceleration | `graph.py`, `protocols.py`, `models.py`, `hub_spoke.py` |
| `meta` | Self-hosting agents, tools, DAGs, and bootstrap | `agents.py`, `tools.py`, `dags.py`, `bootstrap.py`, `registry.py` |
