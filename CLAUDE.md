# CEMAF Project Instructions

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

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `agents` | Agent base classes and registry | `base.py`, `registry.py` |
| `blueprint` | Pipeline/DAG blueprint definitions | `base.py`, `parser.py` |
| `cache` | Result caching with TTL | `base.py`, `protocols.py` |
| `citation` | Source citation tracking | `base.py`, `tracker.py` |
| `config` | Settings, env loading, provider registry | `protocols.py`, `factories.py` |
| `context` | Context compilation, budgets, sources, type classification | `compiler.py`, `budget.py`, `source.py` |
| `core` | Domain types, enums, result, utils | `types.py`, `enums.py`, `result.py`, `utils.py` |
| `evals` | Evaluation framework (deterministic, semantic, LLM judge, online) | `protocols.py`, `hierarchy.py`, `online.py`, `police.py`, `tools.py` |
| `events` | EventBus pub/sub with typed events | `protocols.py`, `bus.py` |
| `generation` | Content generation strategies | `base.py`, `protocols.py` |
| `ingestion` | Data ingestion pipelines | `base.py`, `protocols.py` |
| `llm` | LLM client protocols, Anthropic adapter, resilient wrapper | `protocols.py`, `anthropic.py`, `resilient.py`, `factories.py` |
| `mcp` | Model Context Protocol bridges and adapter | `bridges/`, `adapter.py` |
| `memory` | Memory store, scoring, semantic, tiered, dedup, extraction, session | `base.py`, `manager.py`, `session.py`, `factories.py`, `sqlite_store.py` |
| `moderation` | Content safety pipeline | `pipeline.py`, `protocols.py` |
| `observability` | Logging, health, metrics, run logger, structured/prometheus | `protocols.py`, `structured.py`, `prometheus_metrics.py`, `factories.py` |
| `orchestration` | DAG executor, node handlers, runtime services | `executor.py`, `node_handlers.py`, `services.py` |
| `persistence` | Run/entity persistence | `entities.py`, `protocols.py` |
| `replay` | Execution replay and debugging | `base.py`, `protocols.py` |
| `resilience` | Retry, circuit breaker, rate limiter | `retry.py`, `circuit_breaker.py`, `rate_limiter.py`, `factories.py` |
| `retrieval` | Vector store, embedding providers | `protocols.py`, `memory_store.py` |
| `rlm` | Recursive Language Model queries | `base.py`, `protocols.py` |
| `scheduler` | Task scheduling | `base.py`, `protocols.py` |
| `skills` | Agent skill definitions | `base.py`, `protocols.py` |
| `streaming` | Streaming response handling | `base.py`, `protocols.py` |
| `tools` | Tool protocol, schema, registry | `base.py`, `registry.py` |
| `validation` | Input/output validation | `base.py`, `protocols.py` |
