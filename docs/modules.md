# Module Layout

Where each kind of thing lives in CEMAF. Use this as the acceptance criterion when adding new modules: if your change doesn't fit one of these packages, either the split is wrong or you need a new package (get reviewer sign-off before creating one).

Related docs: [**Architecture**](architecture.md) · [**Design Patterns**](patterns.md)

---

## Top-level layout

```
cemaf/
├── src/cemaf/
│   ├── core/              Types, enums, Result[T], utilities — depends on nothing
│   ├── config/            Settings, provider registry, env loading
│   │
│   │  ─── LAYER 1: Base framework ───
│   │
│   ├── agents/            Agent protocol, registry, built-in agents
│   ├── skills/            Skill protocol — composable agent capabilities
│   ├── tools/             Tool ABC, ToolRegistry, @tool decorator
│   ├── blueprint/         Semantic blueprints for structured generation
│   │
│   ├── orchestration/     DAG execution, RuntimeServices, composition
│   ├── scheduler/         Task scheduling, gates
│   │
│   ├── context/           Immutable Context, ContextPatch, compiler, budget
│   ├── memory/            MemoryManager, semantic/episodic/tiered stores, sessions
│   ├── retrieval/         VectorStore + EmbeddingProvider protocols
│   ├── rlm/               Recursive LLM — divide-and-conquer long-context
│   │
│   ├── llm/               LLMClient protocol + 6 adapters + decorators
│   ├── generation/        Content generation strategies
│   ├── streaming/         Streaming response handling
│   │
│   ├── evals/             Evaluation framework (protocols, hierarchy, pipeline)
│   ├── moderation/        Content safety (pre/post-flight gates, rules)
│   ├── validation/        Input/output validation
│   ├── citation/          Source citation tracking
│   │
│   ├── events/            EventBus pub/sub
│   ├── observability/     Structured logger, metrics, health, run logger
│   ├── resilience/        Retry, circuit breaker, rate limiter
│   ├── persistence/       Run/entity persistence
│   ├── cache/             TTL-bounded result caching
│   ├── replay/            Execution replay and debugging
│   ├── ingestion/         Data ingestion pipelines
│   │
│   ├── mcp/               Model Context Protocol — adapter, bridges, transports
│   │
│   │  ─── LAYER 2: Self-hosting (opt-in, one-way dep on Layer 1) ───
│   │
│   ├── audit/             EventBus → AuditEntry trail, anomaly detection
│   ├── knowledge/         Knowledge graph backed by MemoryManager
│   └── meta/              Self-hosting agents, tools, DAGs, bootstrap
│
├── tests/                 unit/ + integration/ mirroring src/ layout
├── docs/                  Architecture, patterns, modules, per-feature guides
├── examples/              Runnable end-to-end examples
└── openspec/              OpenSpec change proposals (dogfood for MetaSpecifier)
```

---

## Layer 0 — Foundation

### `core/` — types, enums, utilities
- **Role**: The bottom of the import graph. Every other module can import from `core`; `core` imports from nothing in this project.
- **Contains**: `JSON` type alias, `NewType` wrappers (`AgentID`, `NodeID`, `RunID`, `TokenCount`, `Confidence`), `Enum`s (`MemoryScope`, `NodeType`, `ToolRiskLevel`, …), `Result[T]`, `utc_now()`, `generate_id()`, `copy_deep`.
- **Does NOT contain**: Any feature logic. Any class with methods that talk to other packages. Any protocol that another package owns.
- **When to add here**: a primitive needed by ≥3 packages with no behavioral dependency on any feature.

### `config/` — settings, env loading, provider registry
- **Role**: Where `CEMAF_*` env vars are read, where `Settings` lives, where the `ProviderRegistry` pattern registers swappable backends by name.
- **Contains**: `Settings` (Pydantic `BaseSettings`), `get_settings()`, `ProviderRegistry` base, `factories.py` for `create_*_from_env`.
- **Does NOT contain**: actual backend implementations (those live in their feature packages).

---

## Layer 1 — Base framework

### `agents/` — Agent protocol + built-ins
- **Role**: defines `Agent[GoalT, ResultT]` ABC, `AgentRegistry`, built-in agents (Librarian, Researcher, Summarizer, Writer).
- **Contains**: `agents/base.py` (Agent, AgentContext, AgentResult, AgentState), `agents/registry.py`, `agents/context_agents.py` (built-ins).
- **When to add**: A new agent type is a new file with a `class Foo(Agent[FooGoal, FooResult])`. Register via `registry.register_agent(...)`.

### `skills/` — composable capabilities
- **Role**: `Skill[InputT, OutputT]` protocol for atomic agent capabilities. An agent chains skills.
- **Contains**: `skills/base.py`, `skills/protocols.py`.

### `tools/` — atomic functions
- **Role**: `Tool` ABC, `ToolSchema`, `ToolRegistry`, `@tool` decorator. A Tool is stateless, returns `Result[T]`, never raises.
- **Contains**: `tools/base.py` (ABC + schema + decorator), `tools/registry.py`.
- **Boundary**: Tools are deterministic; LLM-backed reasoning lives in Agents/Skills, not here.

### `blueprint/` — structured generation
- **Role**: Semantic blueprints for producing structured content with LLMs (Denis Rothman's pattern).
- **Contains**: `blueprint/base.py`, `blueprint/core.py`, `blueprint/parser.py`.

### `orchestration/` — DAG execution, composition
- **Role**: The top of Layer 1. Owns `DAGExecutor`, `ContextNodeExecutor`, `RuntimeServices`, node-type handlers, bootstrap glue.
- **Contains**:
  - `executor.py` — `DAGExecutor`, `ExecutorConfig`, `NodeResult`, `ExecutionResult`, `HaltSignal`, `HaltReason`
  - `context_node_executor.py` — `NodeExecutor` impl; dispatches each node through the resolver chain, then runs the interceptor PRE/POST chain (incl. the bounded RECOVER loop)
  - `resolvers/` — `NodeResolver` chain (first-match-wins): `CouncilResolver`, `AuctionResolver`, `StaticRefResolver`; adding a node kind = registering a resolver
  - `results.py` — `NodeResult`, `ExecutionResult` (leaf value types, extracted to break import cycles)
  - `services.py` — `RuntimeServices` frozen dataclass (15+ optional deps)
  - `node_handlers.py` — router, loop, parallel, conditional handlers
  - `dag.py` — `DAG`, `Node`, `Edge`, `EdgeCondition`
  - `factories.py` — `create_dag_executor` convenience factory
  - `checkpointer.py` — replay checkpoint support
- **Imports**: everything in Layer 1. **Nothing imports from `orchestration/` except Layer 2 and tests/examples.**

### `scheduler/` — scheduling, gates
- **Role**: Task scheduling, execution gates (lock, session count, time-based). Used by `meta/` dream cycle.
- **Extension point**: implement `ExecutionGate` and register it with `execution_gate_registry.register(...)` for declarative gate-set composition.

### `context/` — immutable context + patches + compilation
- **Role**: The data model for "what the agent knows." `Context` is immutable, mutated via `ContextPatch`. `ContextCompiler` compiles under a `TokenBudget`.
- **Contains**: `context.py` (Context), `patch.py` (ContextPatch, PatchOperation, PatchSource), `compiler.py` (ContextCompiler, SimpleTokenEstimator), `advanced_compiler.py` (PriorityContextCompiler with knapsack/optimal), `budget.py` (TokenBudget), `source.py` (ContextSource + ContextType), `classification.py` (ContextTypeBehavior), `merge.py` (parallel branch merging).
- **Extension point**: implement `MergeStrategy` and register it with `merge_strategy_registry.register(...)` to customize parallel branch merge semantics.

### `memory/` — scoped memory, sessions
- **Role**: `MemoryManager` protocol + `DefaultMemoryManager` composing semantic + episodic + dedup. Session lifecycle (`SessionManager`). Tiered storage. Extraction pipeline.
- **Contains**: `base.py` (MemoryItem, MemoryStore protocol, InMemoryStore), `manager.py`, `semantic.py`, `episodic.py`, `session.py`, `tiered.py`, `deduplication.py`, `sqlite_store.py`, `extraction.py`, `scope.py`.
- **Boundary**: Memory is *persistent by nature* (SESSION < PROJECT < BRAND). `context/` is transient per-run state.

### `retrieval/` — VectorStore + EmbeddingProvider protocols
- **Role**: the retrieval interface. Protocols + default impls (`InMemoryVectorStore`, `MockEmbeddingProvider`).
- **Contains**: `retrieval/protocols.py` (Document, VectorStore, EmbeddingProvider, SearchResult), `retrieval/memory_store.py`.

### `rlm/` — Recursive LLM
- **Role**: Divide-and-conquer querying for 1M+ token contexts; the system prompts a sub-LLM to map/reduce over context chunks.

### `llm/` — LLMClient protocol + adapters
- **Role**: the LLM integration layer. `LLMClient` protocol + 6 adapters + 3 decorators (moderating, resilient, instrumented).
- **Contains**: `protocols.py` (LLMClient, Message, ToolDefinition, LLMConfig, CompletionResult, StreamChunk), `anthropic.py`, `openai_compat.py` (OpenAI/Groq/Together/Ollama/vLLM/Qwen/DeepSeek/Llama), `gemini.py`, `mock.py`, `resilient.py`, `moderating.py`, `instrumented.py`.
- **Invariant**: Every adapter implements the full `LLMClient` protocol including `count_tokens_exact`. Decorators wrap any `LLMClient` and are composable.

### `generation/`, `streaming/` — content generation + streaming
- **Role**: Generation strategies beyond plain completion; streaming response primitives.

### `evals/` — evaluation framework
- **Role**: deterministic + LLM-judge evaluators, hierarchical escalation, online pipeline, quality police.
- **Contains**: `protocols.py` (Evaluator, EvalResult, EvalMetric, EvalConfig), `evaluators.py` (ExactMatch, Contains, Regex, JsonValid, Length), `semantic.py`, `llm_judge.py`, `hierarchy.py`, `composite.py`, `online.py`, `police.py`, `grounding.py` (GroundednessEvaluator, ToolUseSuccessEvaluator), `tools.py` (RunEvalTool, etc.), `agents.py` (QualityGuardAgent).

### `moderation/` — content safety
- **Role**: Pre/post-flight gates for content moderation + PII detection + rule engine.
- **Contains**: `pipeline.py` (ModerationPipeline), `protocols.py` (gates, rules, results), `rules.py` (built-in rule set).

### `validation/` — input/output shape validation
- **Role**: validators that run before and after node execution to ensure contract shapes.

### `citation/` — source tracking
- **Role**: `CitationTracker` records which sources supported which claims. Used by Glass-Box audit.

### `events/` — EventBus pub/sub
- **Role**: typed `Event` + `EventBus` protocol + `InMemoryEventBus`. `EventType` enum is the vocabulary.
- **Contains**: `events/protocols.py`, `events/bus.py`, `events/notifiers.py`, `events/factories.py`.
- **Extension point**: register custom `EventBus` and `Notifier` backends with `event_bus_registry` / `notifier_registry`.
- **Role in architecture**: the seam between orchestration and cross-cutting subscribers (evals, audit, knowledge graph). Modules that would otherwise import each other communicate here.

### `observability/` — logging, metrics, health
- **Role**: `StructuredLogger` (JSON lines), `PrometheusMetrics`, `HealthMonitor`, `BudgetGuard`, `RunLogger` + `InMemoryRunLogger`, `ProvenanceLink`, glass-box `DecisionStep`.
- **Contains**: `config.py` (configure/get singletons — only Layer 1 module with module-level globals, and those are opt-in), `structured.py`, `prometheus_metrics.py`, `budget_guard.py`, `health.py`, `run_logger.py`, `alerting_rules.py`, `glass_box.py`, `token_telemetry.py`.

### `resilience/` — retry, circuit breaker, rate limiter
- **Role**: composable async resilience primitives.
- **Contains**: `retry.py` (RetryPolicy, RetryConfig, DEFAULT_TRANSIENT_EXCEPTIONS), `circuit_breaker.py`, `rate_limiter.py`.

### `persistence/` — durable run/entity storage
- **Role**: `RunRecord`, `Project`, persistence protocols.

### `cache/` — TTL-bounded caching
- **Role**: `@cache_result` decorator + caching primitives. Used by retrieval / LLM heavy paths.

### `replay/` — re-run recorded executions
- **Role**: `Replayer` consumes a `RunRecord` and re-applies patches deterministically.

### `ingestion/` — batch data loading
- **Role**: Ingestion pipelines for populating memory from external sources.

### `mcp/` — Model Context Protocol
- **Role**: MCP adapter (CEMAF as MCP server), bridges (Tool ↔ MCP tool, Resource ↔ MCP resource, Prompt ↔ MCP prompt), transport layer.
- **Contains**: `adapter.py` (MCPAdapter), `bridges/` (tool_bridge, resource_bridge, prompt_bridge, openspec/), `transports/` (stdio, http-stream), `protocols.py`, `types.py`, `mock.py`.
- **Key sub-package**: `mcp/bridges/openspec/` — the OpenSpec MCP bridge that lets `meta/` drive the OpenSpec CLI for self-spec.

---

## Layer 2 — Self-hosting

Opt-in modules that consume Layer 1. **Layer 1 never imports from Layer 2.**

### `audit/` — structured audit trail
- **Role**: EventBus subscriber that converts every event into an `AuditEntry`, with quality-trend + z-score anomaly detection.
- **Contains**: `subscriber.py` (`EventBusAuditLog`), `trail.py` (`AuditTrail`), `models.py`, `protocols.py`, `factories.py`.
- **Extension point**: implement `AuditLog` / `AuditTrail` and register factories with `audit_log_registry.register(...)` or `audit_trail_registry.register(...)`.

### `knowledge/` — knowledge graph
- **Role**: entity + relation graph backed by `MemoryManager`. Entities persist as `MemoryItem` at PROJECT scope; relation indexes are per-entity.
- **Contains**: `graph.py` (`MemoryBackedKnowledgeGraph`), `models.py`, `protocols.py`, `factories.py`.
- **Extension point**: implement `KnowledgeGraph` and either inject it directly through `RuntimeServices` / `MetaServices` or register a factory with `knowledge_graph_registry.register(...)`.

### `improvement/` + `trust/` — self-improvement feedback
- **Role**: converts execution summaries into strategy-memory updates and tool/skill trust changes.
- **Contains**: `improvement/loop.py` (`SelfImprovementLoop`), `improvement/protocols.py`, `improvement/factories.py`, `trust/ledger.py`, and `memory/strategy.py`.
- **Extension point**: implement `StrategyMemoryBackend`, `TrustLedgerBackend`, or `SelfImprovementProcessor`, then register factories with `strategy_memory_registry`, `trust_ledger_registry`, or `improvement_loop_registry`.

### `meta/` — self-hosting agents, DAGs, bootstrap
- **Role**: agents that introspect + extend CEMAF using CEMAF primitives. `MetaArchitect` (DAG design), `MetaSpecifier` (OpenSpec proposals), `MetaSynthesizer` (agent code gen), `MetaAuditor` (trace analysis), `MetaKnowledgeGraph` (KG ops), `MetaScaffolder` (runnable CEMAF-app synthesis).
- **Contains**: `agents.py`, `goals.py`, `tools.py`, `dags.py` (self_audit, feature_synthesis, knowledge_refresh, self_spec, app_synthesis), `bootstrap.py` (`create_meta_executor`), `registry.py`, `specifier.py`, `scaffolder.py`.
- **Entry point**: `create_meta_executor()` wraps `create_executor()` and auto-wires audit + KG.

---

## Placement decisions — worked examples

These came up in real PRs. If you hit one, here's how we decided.

**"I'm adding a GroundednessEvaluator."** → `evals/grounding.py`. An evaluator is an `Evaluator` protocol impl; `evals/` is where they live.

**"I'm adding a ModeratingLLMClient wrapper."** → `llm/moderating.py`. It's an `LLMClient` decorator; `llm/` is where decorators and adapters live. `moderation/` owns the *pipeline and gates*; `llm/` owns the LLM-facing integration.

**"I need a new cross-cutting controller (rate limit per tenant)."** → Implementation in `resilience/` (the primitive). Wiring in `orchestration/services.py` (a new optional field on `RuntimeServices`). Halt integration in `orchestration/executor.py::_halt_signal()`. New `HaltReason` value. Not a new package.

**"I need to validate OpenSpec proposals."** → `mcp/bridges/openspec/` — it's a bridge to an external MCP-compatible tool. Not `validation/` (that's input/output contract shapes), not `evals/` (that's quality measurement).

**"I want a graph database backend for the knowledge graph."** → Implement `KnowledgeGraph` protocol from `knowledge/protocols.py`, name it `Neo4jKnowledgeGraph`, place in `knowledge/neo4j.py`. Inject via `RuntimeServices(knowledge_graph=...)` / `meta.bootstrap.MetaServices(knowledge_graph=...)`, or register it with `knowledge_graph_registry.register(...)` for factory construction.

**"I want to add a new HaltReason: LATENCY_SLO_BREACH."** → New enum value in `orchestration/executor.py::HaltReason`. New optional field on `RuntimeServices`: `slo_tracker: SLOTracker | None = None`. Wire the check into `_halt_signal()`. Add a regression test. **Do not** create a new top-level package for "slo".

---

## What doesn't belong in the main tree

- **Client application code.** If you're building an app that *uses* CEMAF, it goes in a separate repo / package. Previously there was a `youtube_research` folder; we removed it. The framework stays framework.
- **Example notebooks.** Use `examples/*.py` for executable examples. No `.ipynb` in the repo.
- **Framework-specific integrations** (LangGraph, AutoGen, CrewAI adapters). These live in separate packages that depend on `cemaf` — not in `cemaf/` itself.
- **Generated artifacts.** `openspec/changes/` is a dogfood directory for MetaSpecifier-generated proposals; agents write here at runtime. It's in the repo because it's the canonical example of CEMAF speccing CEMAF, but runtime writes go to a scratch dir.

---

## When you can't decide

If the placement is unclear, the answer is almost always:

1. **Is it a Protocol?** → `<package>/protocols.py` (or `<package>/base.py`).
2. **Is it a default implementation?** → sibling file next to the protocol.
3. **Is it a factory?** → `<package>/factories.py`.
4. **Is it wiring glue?** → `bootstrap.py` (app-level) or `orchestration/services.py` (framework-level).
5. **Does it depend on Layer 1 only?** → Layer 1 package.
6. **Does it consume Layer 1 to extend it?** → Layer 2 (`audit/`, `knowledge/`, `meta/`).

If none of these fit, bring it to review before creating a new package.
