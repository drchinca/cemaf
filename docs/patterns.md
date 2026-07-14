# Design Patterns

The catalog of patterns that make CEMAF work. Every one shows up in multiple places; learn them here so you recognize them anywhere.

Related docs: [**Architecture**](architecture.md) · [**Module Layout**](modules.md)

---

## Table of contents
1. [Protocol-first design](#1-protocol-first-design)
2. [Bring Your Own X (BYO-X)](#2-bring-your-own-x-byo-x)
3. [RuntimeServices bundle](#3-runtimeservices-bundle)
4. [Composition root](#4-composition-root)
5. [Context as immutable patch chain](#5-context-as-immutable-patch-chain)
6. [Frozen value objects, NewType IDs](#6-frozen-value-objects-newtype-ids)
7. [Result[T] instead of exceptions](#7-resultt-instead-of-exceptions)
8. [HaltSignal with structured reason](#8-haltsignal-with-structured-reason)
9. [ContextVar for per-run state](#9-contextvar-for-per-run-state)
10. [Factory pattern for config-driven wiring](#10-factory-pattern-for-config-driven-wiring)
11. [Event-driven cross-module communication](#11-event-driven-cross-module-communication)
12. [Decorator/wrapper LLM clients](#12-decoratorwrapper-llm-clients)
13. [Protocol-gated growing asset (blueprint triad)](#13-protocol-gated-growing-asset-blueprint-triad)

---

## 1. Protocol-first design

**Every integration point in CEMAF is a `@runtime_checkable` Protocol.**

```python
# src/cemaf/memory/base.py
@runtime_checkable
class MemoryStore(Protocol):
    async def get(self, scope: MemoryScope, key: str) -> MemoryItem | None: ...
    async def set(self, item: MemoryItem) -> None: ...
    async def delete(self, scope: MemoryScope, key: str) -> bool: ...
    async def list_by_scope(self, scope: MemoryScope) -> tuple[MemoryItem, ...]: ...
```

Consequences:
- No inheritance required. Any class with the right methods satisfies the contract.
- Trivial test doubles: `class FakeStore: ...` — done.
- `isinstance(obj, MemoryStore)` works at runtime.
- Defaults (`SqliteMemoryStore`, `InMemoryStore`) are just *one* implementation among many.

Rule: **if a module has a swappable dep, that dep is a Protocol.** If you find yourself subclassing a concrete class to plug in a new backend, the base is missing a Protocol.

---

## 2. Bring Your Own X (BYO-X)

Protocols enable BYO. Every integration point documents what BYO looks like:

- **BYO-LLM**: implement `LLMClient` protocol → pass via `RuntimeServices(llm_client=...)`.
- **BYO-VectorStore**: implement `VectorStore` → pass via `RuntimeServices(vector_store=...)`.
- **BYO-MemoryBackend**: implement `MemoryStore` → inject into `create_memory_manager`.
- **BYO-EmbeddingProvider**: implement `EmbeddingProvider` → inject into `create_memory_manager`.
- **BYO-TokenEstimator**: implement `TokenEstimator` → inject into `ContextCompiler`.
- **BYO-OpenSpecRuntime**: implement `OpenSpecRuntime` → `System` / `Npx` / `Fake` ship; yours next.

Example, custom vector store:

```python
class PgVectorStore:
    """Postgres-backed vector store with pgvector extension."""

    async def search(self, query_embedding, k=10, filter=None):
        # your pgvector SQL here
        ...

    async def add(self, document):
        ...

    async def count(self) -> int: ...
    async def clear(self) -> None: ...

from cemaf.orchestration.services import RuntimeServices
services = RuntimeServices(vector_store=PgVectorStore(...))
```

No subclassing, no inheritance, no fork.

---

## 3. RuntimeServices bundle

**Cross-cutting dependencies arrive in a single typed frozen dataclass, not as individual kwargs.**

```python
# src/cemaf/orchestration/services.py
@dataclass(frozen=True)
class RuntimeServices:
    # Observability
    run_logger: RunLogger | None = None
    event_bus: EventBus | None = None
    health_monitor: HealthMonitor | None = None
    budget_guard: BudgetGuard | None = None
    # Quality
    online_eval_pipeline: OnlineEvalPipeline | None = None
    quality_police: QualityPolice | None = None
    # Memory
    memory_manager: MemoryManager | None = None
    session_manager: SessionManager | None = None
    # Content Safety
    moderation_pipeline: ModerationPipeline | None = None
    # Context
    context_compiler: ContextCompiler | None = None
    token_budget: TokenBudget | None = None
    domain_context: DomainContext | None = None
    # LLM + Retrieval
    llm_client: LLMClient | None = None
    vector_store: VectorStore | None = None
    # Recovery
    auto_heal_manager: AutoHealManager | None = None
```

Why:
- **One typed shape.** Mypy catches wiring errors at type-check time.
- **Request-scoped DI.** One `RuntimeServices` per request gives per-tenant budget, per-user eval, per-run logging context — without any framework support beyond passing the bundle.
- **Graceful degradation.** Every field is optional. Absence of a service means "that behavior is off" — the framework degrades, nothing crashes.
- **Future-proof.** Adding a new cross-cutting controller (rate limit, SLO, tenant quota) adds a field to `RuntimeServices`. The executor constructor stays stable.

Anti-pattern: **do not** add new kwargs to `DAGExecutor.__init__`. Every new cross-cutting concern lands on `RuntimeServices`. The legacy 13-kwarg constructor is a 0.3.x-only bridge, removed in 0.4.

---

## 4. Composition root

**There is exactly one place that knows how to wire the executor: `bootstrap.create_executor`.**

```python
# src/cemaf/bootstrap.py
def create_executor(
    *,
    agent_registry: AgentRegistry,
    services: RuntimeServices | None = None,
    config: ExecutorConfig | None = None,
) -> DAGExecutor:
    svc = services or RuntimeServices()
    cfg = config or ExecutorConfig()

    # wire subscriptions
    if svc.event_bus and cfg.enable_events:
        if svc.online_eval_pipeline:
            svc.online_eval_pipeline.subscribe()
        if svc.quality_police:
            svc.quality_police.subscribe(event_bus=svc.event_bus)

    # assemble the node executor
    node_executor = ContextNodeExecutor(
        agent_registry=agent_registry,
        run_logger=svc.run_logger,
        domain_context=svc.domain_context,
        llm_client=svc.llm_client,
        vector_store=svc.vector_store,
        memory_manager=svc.memory_manager,
        session_manager=svc.session_manager,
        context_compiler=svc.context_compiler,
        token_budget=svc.token_budget,
    )

    return DAGExecutor(
        node_executor=node_executor,
        services=svc,
        config=cfg,
    )
```

Self-hosting apps use `meta.bootstrap.create_meta_executor(...)` which wraps this and auto-wires audit + knowledge graph.

Rule: **application code never instantiates `DAGExecutor` directly.** Always go through `create_executor` (or `create_meta_executor`). This lets us add framework-wide wiring (subscription lifecycle, health monitoring) in one place.

---

## 5. Context as immutable patch chain

**`Context` is immutable. Every state change is a `ContextPatch` applied to produce a new `Context`.**

```python
# Every update creates a new context; patch_history is the audit trail.
ctx = Context()
patch = ContextPatch(
    path="research_output",
    operation=PatchOperation.SET,
    value={"findings": [...]},
    source=PatchSource.AGENT,
    source_id="researcher",
    reason="Research complete",
    correlation_id=run_id,
)
new_ctx = ctx.apply(patch)

# Full provenance chain:
for patch in new_ctx.get_timeline():
    print(patch.source, patch.source_id, patch.reason, patch.applied_at)
```

This pattern makes:
- **Replay** trivial: `replayer.replay(run_record)` re-applies every patch.
- **Debugging** trivial: the patch chain tells you exactly when and why any value appeared.
- **Auditing** trivial: cost attribution, citation tracking, glass-box explanation all walk the same chain.
- **Concurrent safety** free: no one ever mutates the dict; two nodes running in parallel see the same starting state.

The cost: `context.set(key, value)` copies. Use `copy.deepcopy` on nested dicts to keep the invariant. The `ContextPatch` objects themselves are lightweight frozen dataclasses.

---

## 6. Frozen value objects, NewType IDs

**Every value object is immutable. Every identifier is a `NewType`.**

```python
# src/cemaf/memory/base.py
@dataclass(frozen=True, slots=True)
class MemoryItem:
    scope: MemoryScope
    key: str
    value: JSON
    confidence: Confidence
    created_at: datetime = field(default_factory=utc_now)
    ...

# src/cemaf/core/types.py
AgentID = NewType("AgentID", str)
NodeID = NewType("NodeID", str)
RunID = NewType("RunID", str)
TokenCount = NewType("TokenCount", int)
Confidence = NewType("Confidence", float)
```

Why frozen:
- Hashable → usable as dict keys / set members.
- Thread-safe and coroutine-safe without locks.
- Equality is structural, no surprise identity checks.

Why NewType:
- `register(agent_id=run_id)` becomes a type error instead of a subtle bug where the wrong string flows into the wrong slot.
- Mypy distinguishes domain strings from each other even when the runtime type is identical.

Rule: **string-typed domain identifiers are an anti-pattern.** Always `NewType` or an `Enum`.

---

## 7. Result[T] instead of exceptions

**Internal call boundaries return `Result[T]`, not raise.**

```python
# src/cemaf/core/result.py
@dataclass(frozen=True)
class Result[T]:
    success: bool
    data: T | None = None
    error: str | None = None
    hints: list[Hint] = field(default_factory=list)
    metadata: JSON = field(default_factory=dict)

    @classmethod
    def ok(cls, data: T, ...) -> Result[T]: ...
    @classmethod
    def fail(cls, error: str, ...) -> Result[T]: ...
```

Used by:
- Every `Tool.execute()` returns `ToolResult = Result[Any]`.
- Every moderation gate returns `ModerationResult`.
- Every evaluation returns `EvalResult`.

Consequences:
- Callers handle success and failure in the same shape.
- The `Result` type carries `hints` and `metadata` — structured error context, not just a string message.
- Composable: `.map(fn)`, `.unwrap_or(default)`, `bool(result)` just work.

Exceptions are still raised at the *outer* boundary (Python semantics at the OS level), but control flow inside feature code uses `Result[T]`.

---

## 8. HaltSignal with structured reason

**Halt gates return a structured `HaltSignal`, not a bool.**

```python
# src/cemaf/orchestration/executor.py
class HaltReason(str, Enum):
    BUDGET_EXHAUSTED = "budget_exhausted"
    QUALITY_DEGRADED = "quality_degraded"

@dataclass(frozen=True, slots=True)
class HaltSignal:
    reason: HaltReason
    source: str
    detail: str = ""
```

`DAGExecutor._halt_signal()` aggregates all controllers (BudgetGuard, QualityPolice, future: rate limit, SLO, tenant quota) and returns the first-firing signal with source + detail. A bool adapter `_should_halt()` is kept for the `NodeHandlerContext.should_halt` callback that LOOP body polling uses.

Why structured:
- On-call at 3am reads *which* controller fired and *why*. "halted=True" is not actionable.
- New halt signals register a new `HaltReason` value; callers pattern-match on the enum.
- Logs and alerts carry the source so routing ("budget halts page finance, quality halts page research") works.

---

## 9. ContextVar for per-run state

**Per-run state lives in `contextvars.ContextVar`, not instance fields.**

```python
# src/cemaf/orchestration/executor.py
_route_choices_var: ContextVar[dict[NodeID, set[NodeID]] | None] = ContextVar(
    "cemaf_route_choices", default=None,
)
_correlation_id_var: ContextVar[str] = ContextVar(
    "cemaf_correlation_id", default="",
)

# At run() entry:
route_token = _route_choices_var.set({})
correlation_token = _correlation_id_var.set(str(run_id))
try:
    return await self._run_impl(...)
finally:
    _route_choices_var.reset(route_token)
    _correlation_id_var.reset(correlation_token)
```

Why ContextVar:
- asyncio propagates ContextVar across sub-tasks correctly — readers in spawned coroutines see the right value.
- No need to thread `run_id` / `route_choices` through every helper signature.
- Concurrent `run()` calls on the same `DAGExecutor` instance each get their own view. Sequential runs in the same task reset cleanly via `finally`.

Anti-pattern: `self._correlation_id = str(run_id)` at `run()` entry (what CEMAF used to do — two concurrent runs clobbered each other).

---

## 10. Factory pattern for config-driven wiring

**Every module exposes `create_*()` factories; `create_from_env()` reads `CEMAF_*` env vars for zero-config defaults.**

```python
def create_memory_manager(
    *,
    memory_store: MemoryStore | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    event_bus: EventBus | None = None,
    dedup_threshold: float = 0.85,
) -> MemoryManager: ...

def create_memory_manager_from_env() -> MemoryManager:
    """Honors CEMAF_MEMORY_BACKEND, CEMAF_EMBEDDING_PROVIDER, …"""
    ...
```

Applications can go zero-config (`create_memory_manager_from_env()`) or fully-wired (`create_memory_manager(memory_store=my_store, ...)`). The factory is the seam where env overrides land; no module reads `os.environ` at import time.

---

## 11. Event-driven cross-module communication

**Modules that would otherwise have a direct import talk through the `EventBus`.**

```python
# Executor emits:
await event_bus.publish(Event.create(
    type=EventType.TASK_COMPLETED,
    payload={"node_id": ..., "output": ..., "cost_estimate_usd": ...},
    source="dag_executor",
    correlation_id=run_id,
))

# OnlineEvalPipeline subscribes:
event_bus.subscribe(EventType.TASK_COMPLETED, self._handle_task_completed)

# QualityPolice subscribes to EVAL_COMPLETED:
event_bus.subscribe(EventType.EVAL_COMPLETED, self._handle_eval_completed)

# AuditLog (Layer 2) subscribes to everything:
event_bus.subscribe(EventType.ALL, self._audit)
```

Wins:
- `orchestration/` has zero imports from `evals/` or `audit/`.
- Adding a new cross-cutting subscriber is a factory call, not a feature integration.
- Replay can re-emit events to reproduce a run's behavior.

Rule: **if module A would import module B only to notify it, use the EventBus instead.**

---

## 12. Decorator/wrapper LLM clients

**Cross-cutting LLM concerns (retry, moderation, instrumentation) compose as decorators around a base `LLMClient`.**

```python
from cemaf.llm import create_llm_client
from cemaf.llm.moderating import ModeratingLLMClient
from cemaf.llm.resilient import ResilientLLMClient
from cemaf.llm.instrumented import InstrumentedLLMClient

base = create_llm_client("ollama", model="gemma3:4b")

# Compose: resilient(moderating(instrumented(base)))
client = ResilientLLMClient(
    client=ModeratingLLMClient(
        inner=InstrumentedLLMClient(client=base, run_logger=logger),
        moderation=pipeline,
    ),
    retry_config=RetryConfig(...),
    circuit_breaker=CircuitBreaker(...),
    rate_limiter=RateLimiter(...),
)

# Services see a single LLMClient; they don't know about the stack.
services = RuntimeServices(llm_client=client)
```

Order matters:
- `resilient` outermost: retries and circuit-breaking wrap the whole call including moderation.
- `moderating` middle: sanitizes tool-result messages inbound, buffers stream outbound for sentence-level moderation.
- `instrumented` innermost: records the actual bytes on the wire.

All three satisfy `LLMClient` protocol; `RuntimeServices` sees one opaque `LLMClient` object.

---

## 13. Protocol-gated growing asset (blueprint triad)

A **catalog that grows itself** without becoming a magic black box — every decision that would normally be hardcoded ("what's good enough?", "how do we derive the next entry?", "where does it land?") is a pluggable `@runtime_checkable` Protocol. The engine is pure orchestration; the judgment lives behind protocol seams the caller controls.

The canonical instance is the blueprint triad (`cemaf.blueprint`):

- **Read surface**: `BlueprintLibrary` — one searchable index over developer-authored (BYO) entries and autonomously harvested entries. Same `search()`, same resolution.
- **Retrieve surface**: `BlueprintSelectorHook` — one-method protocol. `ContextNodeExecutor` imports only this, not any blueprint type.
- **Write surface**: `BlueprintHarvesterEngine` orchestrates three pluggable decisions behind protocols:
  - `HarvestPolicy` — is this run good enough to harvest?
  - `RunCorrelator` — what do we know about this run?
  - `BlueprintDistiller` — what blueprint does this run yield?

Default implementations ship in `cemaf.meta.harvest_defaults`:

```python
engine = BlueprintHarvesterEngine(
    writable_source=source,
    library=library,
    policy=ScoreThresholdHarvestPolicy(threshold=0.8),
    correlator=InMemoryRunCorrelator(),
    distiller=RecipeBlueprintDistiller(),
)
```

BYO any or all:

```python
class MyPolicy:
    def should_harvest(self, *, event): ...  # domain logic

engine = BlueprintHarvesterEngine(
    writable_source=source,
    policy=MyPolicy(),
    correlator=InMemoryRunCorrelator(),
    distiller=RecipeBlueprintDistiller(),
)
```

**Why this is a pattern, not just a feature**: the same shape can produce a growing skill catalog, a growing pattern library, a growing eval-criteria index. The substrate — protocol orchestrator + BYO decision protocols + writable source behind a pluggable read surface — is reusable. See [`docs/blueprints.md`](blueprints.md) for the full API and the race-handling contract (bounded `lookup` retries + require-both-signals correlation).

---

## How these patterns reinforce each other

These aren't independent. They lock together:

- **Protocol-first** makes **BYO-X** possible.
- **BYO-X** means services have no inheritance surface, which is why **RuntimeServices** can be a flat frozen dataclass.
- **RuntimeServices** + **Composition root** means no module-level singletons in features.
- **Frozen value objects** make **Immutable context patches** safe to hash and diff.
- **Result[T]** makes **Tool/Eval/Moderation** interfaces uniform.
- **HaltSignal** + **ContextVar** let one `DAGExecutor` instance serve many concurrent runs with debuggable halts.
- **EventBus** + **Factory pattern** let the base framework stay ignorant of self-hosting Layer 2.

Violating any one pattern usually breaks another. Reviewers should hold the line on all of them.
