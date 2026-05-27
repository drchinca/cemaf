---
title: KG and DataSource as Shared RuntimeServices
spec_id: SPEC-02
status: Reviewed
last_reviewed: 2026-05-27
owner: drchinca
parent: SPEC-00 — Enterprise Context Brain
depends_on: SPEC-01
---

# SPEC-02: KG and DataSource as Shared RuntimeServices

> Promotes the Knowledge Graph from a meta-only asset to a shared `RuntimeService`,
> introduces a read-only `DataSource` connector protocol over enterprise systems,
> and defines the `PullInterceptor` that realizes **pull-not-push** retrieval —
> writing the canonical `ctx.surfaced_sources` set consumed by SPEC-05 cite-or-fail.

## 1. Context

`knowledge/MemoryBackedKnowledgeGraph` exists but is consumed only by `meta/`.
`retrieval/` exposes vector primitives but no abstraction over enterprise systems.

This spec:
1. Adds `knowledge_graph` and `data_sources` to `RuntimeServices` (per SPEC-00 §2).
2. Defines `DataSource` — a read-only, citeable connector protocol with health and timeout contracts.
3. Provides the **PullInterceptor** (PRE phase, position 2 in DEFAULT order — *before* BlueprintInterceptor) which retrieves context across KG, vector store, memory, and DataSources within `node.budget.pull_tokens`, **and writes the result to `ctx.surfaced_sources`** — the canonical membership set that SPEC-05 cite-or-fail enforces.

## 2. Interface Contract (MDE)

Common types in SPEC-00 §2 (`Citation`, `CiteableChunk`, `TokenBudget`).

```python
from typing import Protocol, runtime_checkable
from collections.abc import Mapping
from dataclasses import dataclass, field

class DataSourceCapability(Enum):
    READ      = "read"
    SEARCH    = "search"
    RELATIONS = "relations"

class HealthStatus(Enum):
    HEALTHY   = "healthy"
    DEGRADED  = "degraded"
    UNHEALTHY = "unhealthy"

@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    text: str
    entities: tuple[EntityRef, ...] = ()
    filters: Mapping[str, str] = field(default_factory=dict)   # Mapping per SPEC-00 §2 canonical wrap pattern
    top_k: int = 8
    timeout_ms: int = 3_000

class DataSource(Protocol):
    """Read-only enterprise connector. Protocol surface contains NO write methods.

    Note: NOT @runtime_checkable. PEP 544 forbids issubclass() against protocols
    with non-method members (`source_id`, `capabilities`); structural validation
    instead happens explicitly in DataSourceRegistry.register() per Inv 1, which
    inspects the concrete class's public surface.
    """
    source_id: str
    capabilities: frozenset[DataSourceCapability]

    async def retrieve(self, *, query: RetrievalQuery,
                       budget: TokenBudget) -> tuple[CiteableChunk, ...]: ...
    async def health(self) -> HealthStatus: ...

class DataSourceRegistry:
    """Static read-only-port enforcement happens at register() — see Inv 1."""
    ALLOWED_PUBLIC: ClassVar[frozenset[str]] = frozenset({"retrieve", "health", "source_id", "capabilities"})

    def register(self, source: DataSource) -> None:
        """Reject sources whose concrete class declares any public attribute
        (vars(type(source)), name not starting with '_') outside ALLOWED_PUBLIC —
        inherited members from object/Protocol bases are NOT counted.
        Raises DuplicateSourceError if source.source_id is already registered.
        Raises ReadOnlyViolationError if extra public surface is present."""
    def get(self, source_id: str) -> DataSource: ...
    def list_capable(self, capability: DataSourceCapability) -> tuple[DataSource, ...]: ...

# Carrier field on Context (added by PullInterceptor, read by SPEC-05 cite-or-fail)
#   ctx.surfaced_sources: tuple[CiteableChunk, ...]

class PullInterceptor(NodeInterceptor):
    """PRE phase, runs at position 2 — BEFORE BlueprintInterceptor.

    Strategy:
      1. Extract entities/keywords from goal.text (raw goal, not Blueprint)
         via the pinned EntityExtractor (deterministic regex+gazetteer
         implementation in `retrieval/entity_extractor.py`; LLM-based
         extractors require fixture cassettes per SPEC-00 Property 6).
      2. Query KG.neighbors() for each entity → CiteableChunks.
      3. Query each capable, healthy DataSource within per-source sub-budget.
      4. Query MemoryContextProvider for project/session memory.
      5. Merge into ctx.surfaced_sources, sorted by confidence desc.
      6. Apply ContextCompiler with tool_output_reserve_fraction (POC #2).
    """
    interceptor_id = "pull"
    phase = InterceptorPhase.PRE
```

## 3. Invariants (DbC)

1. `WHEN DataSourceRegistry.register(source) is called, THE registry SHALL reject any source whose concrete class exposes a public attribute (name not starting with '_') outside ALLOWED_PUBLIC = {"retrieve", "health", "source_id", "capabilities"}. The check uses ONLY attributes declared directly on the concrete type (excluding inherited members from object/Protocol bases): public_set = {n for n in vars(type(source)) if not n.startswith('_')}; violations raise ReadOnlyViolationError when public_set - ALLOWED_PUBLIC ≠ ∅. Helper attributes (loggers, config) MUST be private (leading underscore) or live on a non-DataSource collaborator.`
2. `WHEN PullInterceptor runs, sum(chunk.token_count for chunk in returned) SHALL be ≤ node.budget.pull_tokens.`
3. `Every CiteableChunk in ctx.surfaced_sources SHALL have a Citation with non-empty source_id and locator.`
4. `THE knowledge_graph service SHALL be queryable from any node — meta or non-meta — through RuntimeServices.knowledge_graph.`
5. `WHEN a DataSource is UNHEALTHY, PullInterceptor SHALL skip it without invoking retrieve(), emit a log event, and continue.`
6. `WHEN a DataSource.retrieve() exceeds query.timeout_ms, PullInterceptor SHALL cancel it, treat as skipped, and emit a log event.`
7. `IF no chunks are retrieved AND node.grounding == GroundingPolicy.REQUIRED, THEN PullInterceptor SHALL emit REJECT(reason="no_grounding_available").`
8. `Per-source token sub-budget SHALL default to a uniform split across capable+healthy sources; pluggable via PullInterceptor config.`
9. `THE registry SHALL reject duplicate source_id with DuplicateSourceError.`
10. `PullInterceptor SHALL set ctx.surfaced_sources atomically — either fully populated or absent on REJECT — never partial.`

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Pull-not-push context

  Scenario: Pull runs before Blueprint
    Given a DAG configured with ChainProfile.DEFAULT
    When pre-flight executes
    Then PullInterceptor decision is recorded before BlueprintInterceptor decision

  Scenario: KG neighbors enrich a normal node
    Given a Knowledge Graph with entity "OrderPipeline" and 3 neighbors
    And a non-meta node whose goal.text references "OrderPipeline"
    When PullInterceptor runs
    Then ctx.surfaced_sources contains 3 chunks tagged with Citation.source_id == "kg"
    And each citation locator points at the KG entity

  Scenario: DataSource retrieval respects per-source budget
    Given two healthy DataSources A and B with pull_tokens=2000 split uniformly
    When PullInterceptor runs
    Then sum(chunk.token_count) ≤ 2000
    And per-source sums each ≤ 1000

  Scenario: Read-only enforcement at registry
    Given a DataSource subclass exposing a public method "write"
    When DataSourceRegistry.register(source) is called
    Then ReadOnlyViolationError is raised
    And no source is registered

  Scenario: Unhealthy DataSource is skipped
    Given DataSource A.health() returns UNHEALTHY
    When PullInterceptor runs
    Then A.retrieve is not called
    And the run completes using surviving sources
    And a "datasource.skipped_unhealthy" log event is emitted

  Scenario: DataSource timeout is contained
    Given DataSource A.retrieve() exceeds query.timeout_ms
    When PullInterceptor runs
    Then A's task is cancelled
    And a "datasource.timeout" log event is emitted
    And surviving sources still populate ctx.surfaced_sources

  Scenario: Required grounding with no hits rejects pre-flight
    Given a node with grounding=REQUIRED and zero retrieved chunks
    When PullInterceptor runs
    Then PreflightDecision is REJECT with reason "no_grounding_available"
    And ctx.surfaced_sources is absent (not partially populated)

  Scenario: KG access symmetry (meta vs non-meta)
    Given a meta-agent and a normal agent both querying KG.neighbors("OrderPipeline")
    When both run
    Then the returned EntityRefs are identical
    And both calls flow through RuntimeServices.knowledge_graph

  Scenario: Duplicate source_id rejected
    Given a registry with source_id "salesforce_prod" registered
    When register() is called again with the same source_id
    Then a DuplicateSourceError is raised
```

## 5. Out of Scope

- Concrete enterprise adapters (Salesforce, SAP, Snowflake, Confluence) — each follow-on spec/PR.
- Write-back to enterprise systems.
- Caching layer for DataSource responses (separate optimization spec).
- Cross-source entity resolution (fuzzy match across sources).
- Token-counting authority — DataSources self-report `token_count`; cross-validation by a tokenizer service is a follow-on.

## 6. Dependencies

- SPEC-01 (interceptor protocol)
- SPEC-00 §2 (TokenBudget, CiteableChunk, Citation)
- `knowledge/graph.py`, `knowledge/protocols.py`
- `retrieval/protocols.py`
- `retrieval/entity_extractor.py` (NEW — pinned deterministic extractor for PullInterceptor step 1)
- `context/source.py` (`ContextSource`)

## 7. Correctness Properties

### Property 1: Read-only boundary
*For any* `DataSource` registered via `DataSourceRegistry.register`, the
concrete class's *directly-declared public* attribute set
(`{n for n in vars(type(source)) if not n.startswith('_')}`) is a subset of
`{"retrieve","health","source_id","capabilities"}`. Enforced at registration
time; `@runtime_checkable` Protocol presence-check alone is insufficient.
Inherited methods from base classes do not count.

**Validates: §3 Invariant 1 / §4 "Read-only enforcement at registry"**

### Property 2: Budget conservation
*For any* PullInterceptor invocation, sum of returned chunk token_counts ≤
`node.budget.pull_tokens`.

**Validates: §3 Invariant 2 / §4 "DataSource retrieval respects per-source budget"**

### Property 3: Citation membership initialization
*For every* CiteableChunk in `ctx.surfaced_sources` after PullInterceptor
returns ACCEPT, the Citation has a non-empty source_id and locator. This is the
membership set SPEC-05 cite-or-fail consumes.

**Validates: §3 Invariants 3, 10 / SPEC-05 Property 1**

### Property 4: KG access symmetry
*For any* node, KG queries resolve through `RuntimeServices.knowledge_graph` —
no separate path exists for meta vs non-meta callers.

**Validates: §3 Invariant 4 / §4 "KG access symmetry" / SPEC-00 Property 5**

### Property 5: Failure containment for DataSources
*For any* DataSource that is UNHEALTHY or times out, the PullInterceptor
returns within `node.budget.timeout_ms`, surviving sources still populate
`ctx.surfaced_sources`, and the failure is logged.

**Validates: §3 Invariants 5, 6 / §4 "Unhealthy DataSource is skipped", "DataSource timeout is contained"**

## 8. Eval Criteria

Pinned models / fixtures referenced explicitly so evaluators are replay-deterministic.

| Evaluator | Node | Mode | Threshold | Method | Pinned |
|---|---|---|---|---|---|
| BudgetConservationEvaluator | every PullInterceptor run | GATE | tokens ≤ budget | deterministic | n/a |
| GroundingCoverageEvaluator | nodes with grounding=REQUIRED | GATE | chunks ≥ 1 | deterministic | n/a |
| ProtocolSurfaceEvaluator | DataSource implementations | GATE | extra public methods == 0 | deterministic | n/a |
| RetrievalRelevanceEvaluator | sample of pulls | OBSERVE | mean cos-sim ≥ baseline from `cemaf/data/eval_pins/retrieval_relevance_baseline.json` (absolute floor 0.55); regression > 0.02 fails CI | semantic | embedding model `text-embedding-3-small@2024-01-25` (API version), pinned in `cemaf/llm/factories.py`; corpus `tests/fixtures/retrieval_eval_corpus_v1.jsonl` |

## 9. Observability Contract

- **Span**: `gen_ai.context.pull` — `node.id`, `kg.queries`, `datasources.queried`, `datasources.skipped`, `chunks.returned`, `tokens.used`, `tokens.budget`
- **Span**: `gen_ai.kg.query` — `entity.id`, `relation.types`, `neighbors.count`
- **Span**: `gen_ai.datasource.retrieve` — `source.id`, `latency_ms`, `chunks.count`, `tokens.used`
- **Log events**: `datasource.skipped_unhealthy`, `datasource.timeout`, `pull.no_grounding`, `kg.entity_missing`
- **Metrics** (per SPEC-00 §9 cardinality rules — `source_id` is span-attribute-only; metric labels use `source_kind ∈ {kg, vector, memory, datasource}` as a bounded enum): `cemaf_pull_chunks_total{source_kind}`, `cemaf_pull_tokens_used` (histogram, no labels), `cemaf_datasource_health{source_kind,status}`, `cemaf_datasource_duration_seconds{source_kind,outcome}` (histogram)
