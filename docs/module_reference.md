# CEMAF Module Reference Guide

**Last Updated**: March 2026

> **Note**: This is a technical reference guide providing a comprehensive module-by-module breakdown of the CEMAF framework. For learning-oriented documentation with tutorials and examples, see the [official documentation](./README.md).

Complete overview of all modules in the CEMAF (Context Engineering Multi-Agent Framework) codebase.

## Core Primitives (`cemaf/core/`)

### `types.py`

- **Purpose**: Type-safe identifiers using `NewType`
- **Exports**: `AgentID`, `ToolID`, `SkillID`, `NodeID`, `RunID`, `ProjectID`, `TokenCount`, `Confidence`, `JSON`, `ProvenanceID`, `DomainID`, `TenantID`
- **Key Feature**: Prevents mixing different ID types at compile time

### `enums.py`

- **Purpose**: Centralized enums for status, types, and scopes
- **Exports**:
  - `AgentStatus` (idle, running, waiting, completed, failed)
  - `RunStatus` (pending, running, completed, failed, cancelled)
  - `NodeType` (tool, skill, agent, router, parallel, conditional, loop)
  - `MemoryScope` (brand, project, audience_segment, platform, personae, session)
  - `ContextArtifactType` (brand_constitution, style_guide, symbol_canon, etc.)
  - `Priority` (low, medium, high, critical)
  - `VerificationStatus` (unverified, verified, disputed, retracted)
  - `ExclusionReason` (budget_exceeded, low_priority, stale, duplicate, filtered)

### `provenance.py`

- **Purpose**: Glass box audit trail for DAG runs
- **Exports**: `SourceReference`, `ProvenanceLink`, `ProvenanceChain`
- **Key Feature**: Cross-references every LLM call with its context sources, citations, patches, and costs

### `domain.py`

- **Purpose**: Domain-scoped business rules for multi-tenant deployments
- **Exports**: `DomainContext`
- **Key Feature**: Carries business rules, vocabulary constraints, citation style requirements through agent execution

### `result.py`

- **Purpose**: Generic `Result[T]` pattern for consistent error handling
- **Features**:
  - `Result.ok(data)` / `Result.fail(error)`
  - `map()`, `unwrap()`, `unwrap_or()`
  - Metadata support, timestamps
  - Replaces custom result types across modules

### `utils.py`

- **Purpose**: Shared utilities
- **Functions**:
  - `utc_now()` - Consistent UTC datetime
  - `generate_id(prefix)` - Unique ID generation
  - `safe_json()` - JSON serialization with datetime/bytes/set support
  - `truncate()` - Text truncation

### `constants.py`

- **Purpose**: All magic numbers and defaults
- **Categories**: Execution, Agent, DeepAgent, Context/Token limits, Memory, Confidence thresholds, DAG execution
- **Philosophy**: NO hardcoded values elsewhere in codebase

### `provider_registry.py`

- **Purpose**: Generic extensible factory registry replacing if/elif chains
- **Exports**: `ProviderRegistry[T]`
- **Key Methods**: `register(backend, factory)`, `create(backend, **kwargs)`, `has(backend)`, `list_backends()`
- **Used By**: LLM factories (`llm_registry`), context factories (`context_compiler_registry`), retrieval factories (`vector_store_registry`)

### `execution.py` & `storage.py`

- **Purpose**: Execution context and storage abstractions
- **Key Classes**:
  - `CancellationToken`: Cooperative cancellation with parent-child hierarchy
  - `ExecutionContext`: Context manager for timeout and cancellation
  - `CancelledException`, `TimeoutException`: Execution exceptions

### `recovery.py`

- **Purpose**: Autonomous recovery and self-healing for infrastructure errors
- **Key Classes**: `AutoHealManager`
- **Features**: Registered as optional dependency in `RuntimeServices`

---

## Tools/Skills/Agents Hierarchy

### `tools/base.py`

- **Purpose**: Atomic, stateless functions
- **Key Classes**:
  - `ToolSchema`: JSON Schema for tool parameters (OpenAI/Anthropic format conversion, `to_definition()` bridge to LLM protocols)
  - `Tool`: Abstract base class
  - `@tool()` decorator: Convert functions to tools
- **Features**:
  - Always returns `Result`, never raises
  - Supports recording via `execute_with_recording()`
  - Pre/post-flight moderation hooks
  - Tool call tracking

### `skills/base.py`

- **Purpose**: Composable capabilities using tools
- **Key Classes**:
  - `Skill[InputT, OutputT]`: Generic skill with typed input/output
  - `SkillOutput`: Result with tool call trace
  - `SkillContext`: Read-only context (run_id, agent_id, memory, artifacts)
- **Features**: Skills compose multiple tools, have access to context

### `agents/base.py`

- **Purpose**: Autonomous entities with goals and memory
- **Key Classes**:
  - `Agent[GoalT, ResultT]`: Generic agent with typed goal/result
  - `AgentState`: Mutable state (status, iteration, skill_calls, messages, working_memory)
  - `AgentContext`: Isolated context (run_id, agent_id, parent, depth, global_memory, artifacts)
  - `AgentResult`: Result with state trace and skill results
- **Features**: Agents orchestrate skills, maintain state, make decisions

### `agents/registry.py`

- **Purpose**: Dynamic, domain-scoped agent registry
- **Key Classes**:
  - `AgentRegistry(BaseRegistry[Agent])`: Dynamic agent registration and discovery
- **Features**:
  - `register_agent(agent_class, domain_id)` for domain-scoped registration
  - `get_for_domain(domain_id)` for domain-scoped lookup
  - `get_capabilities_description()` auto-generated from registered agents
  - Factory `create_default_registry()` replaces singleton pattern

### `agents/context_agents.py`

- **Purpose**: Built-in context engineering agents
- **Key Agents**:
  - `LibrarianAgent`: Context retrieval and organization
  - `ResearcherAgent`: Multi-source research and synthesis
  - `SummarizerAgent`: Intelligent content compression
  - `WriterAgent`: Context-aware content generation

---

## Orchestration (`cemaf/orchestration/`)

### `dag.py`

- **Purpose**: Dynamic DAG (Directed Acyclic Graph) for workflow definition
- **Key Classes**:
  - `Node`: Workflow node (tool/skill/agent/router/parallel/conditional/loop)
  - `Edge`: Connection with conditions (ALWAYS, ON_SUCCESS, ON_FAILURE, JSON_RULE)
  - `Condition`: Serializable condition with operators (equals, contains, etc.)
  - `DAG`: Graph with nodes, edges, validation, cycle detection
- **Factory Methods**: `Node.tool()`, `Node.skill()`, `Node.agent()`, `Node.router()`, `Node.parallel()`, `Node.conditional()`, `Node.loop()`
- **Features**:
  - Dynamic construction at runtime
  - Composable (nests DAGs)
  - Loop nodes for iterative subgraph execution (max_iterations, exit_condition)
  - Mermaid export
  - JSON serialization

### `executor.py`

- **Purpose**: Executes DAGs with dependency resolution
- **Key Classes**:
  - `DAGExecutor`: Main executor
  - `ExecutorConfig`: Configuration (max_parallel, enable_logging, enable_events, enable_moderation, node_timeout_seconds)
  - `NodeResult`: Result of single node execution
  - `ExecutionResult`: Complete DAG execution result
- **Features**:
  - Topological sort for dependency resolution
  - Delegates node-type-specific logic to `node_handlers.py`
  - Cooperative cancellation via `CancellationToken` parameter in `run()`
  - Context propagation
  - Checkpointing for resume
  - Context patch emission
  - Run logging integration
  - Session lifecycle management (bootstrap/dispose via `SessionManager`)
  - Quality police halt gate integration

### `node_handlers.py`

- **Purpose**: Node-type-specific execution handlers extracted from DAGExecutor
- **Key Classes**:
  - `NodeHandlerContext`: Shared context (route_choices, apply_output, execute_with_retry, merge_strategy, max_parallel, run_logger, correlation_id)
- **Key Functions**: Handlers for ROUTER, CONDITIONAL, LOOP, and PARALLEL node types
- **Benefits**: Keeps DAGExecutor focused on orchestration flow; handlers are independently testable

### `services.py`

- **Purpose**: Runtime services bundle (DI container) for orchestration
- **Key Classes**:
  - `RuntimeServices`: Frozen dataclass bundling the injectable runtime dependencies across observability, quality, memory, content safety, context, LLM/retrieval, knowledge, agent-selection, council, interceptors, blueprints, and recovery categories
- **Features**: All deps optional (default `None`; `max_recovery_attempts` defaults to 2), used by `bootstrap.create_executor()`

### `deep_agent.py`

- **Purpose**: Hierarchical multi-agent orchestration with context isolation
- **Key Classes**:
  - `DeepAgentOrchestrator`: Orchestrates parent-child agent spawning
  - `DeepAgentResult`: Result with child spawn trace
  - `DeepAgentConfig`: Limits (max_depth, max_children, max_total, timeout)
- **Features**:
  - Parent spawns children with isolated context
  - Recursive task decomposition
  - Dynamic DAG creation from goals
  - Context isolation between levels

### `node_handlers.py`

- **Purpose**: Node-type-specific execution handlers extracted from DAGExecutor
- **Key Classes**:
  - `NodeHandlerContext`: Frozen slots dataclass bundling route_choices, apply_output, execute_with_retry, merge_strategy, max_parallel, run_logger, correlation_id
- **Key Functions**:
  - `execute_router_node()`: Execute ROUTER node and select allowed downstream targets
  - `execute_conditional_node()`: Evaluate condition and select branch
  - `execute_loop_node()`: Iterative subgraph execution with exit conditions
  - `execute_parallel_node()`: Concurrent execution of parallel branches
- **Benefits**: Clean separation of node type logic from core executor

### `services.py`

- **Purpose**: Runtime services bundle for orchestration components
- **Key Classes**:
  - `RuntimeServices`: Frozen dataclass bundling the injectable runtime dependencies grouped by concern:
    - Observability: `run_logger`, `event_bus`, `health_monitor`, `budget_guard`, `tracer`
    - Quality: `online_eval_pipeline`, `quality_police`
    - Memory: `memory_manager`, `session_manager`
    - Content safety: `moderation_pipeline`
    - Context: `context_compiler`, `token_budget`, `domain_context`
    - LLM + Retrieval: `llm_client`, `vector_store`
    - Knowledge (SPEC-02/07): `knowledge_graph`
    - Agent selection (SPEC-09): `agent_selector`
    - Council (SPEC-10): `council_aggregator`
    - Interceptors (SPEC-01a): `interceptor_pipeline`, `max_recovery_attempts` (RECOVER budget, default 2)
    - Blueprints: `blueprint_library`, `blueprint_selector`
    - Recovery: `auto_heal_manager`
- **Used By**: `bootstrap.create_executor()` composition root

### `checkpointer.py`

- **Purpose**: Save/restore execution state for resumability
- **Key Components**: Checkpoint protocol and implementations

### `context_node_executor.py`

- **Purpose**: Bridge between DAG nodes and agents via dynamic registry
- **Key Classes**:
  - `ContextNodeExecutor(NodeExecutor)`: Resolves node ref_id to agent via registry
- **Features**:
  - Builds GoalT from resolved inputs
  - Threads DomainContext + provenance through AgentContext
  - Records LLMCall/ContextPatch/Citation via RunLogger
  - Builds ProvenanceLink per execution
  - Accepts optional `MemoryManager` + `SessionManager` (recall before node, ingest after)

### `planner.py`

- **Purpose**: Dynamic DAG planning with domain-aware capabilities
- **Key Classes**:
  - `DynamicPlanner`: Generates DAG plans from goals using LLM
- **Features**:
  - Accepts `domain_context: DomainContext` for domain-scoped planning
  - Dynamic capabilities description from AgentRegistry
  - Injects domain info into planning prompt

### `dependency_resolver.py`

- **Purpose**: Resolve node dependencies for parallel execution
- **Key Components**: Topological sort, dependency graph analysis

### `factories.py`

- **Purpose**: Factory functions for orchestration components
- **Key Functions**:
  - `create_dag_executor()` - Create DAGExecutor with sensible defaults
  - Additional factory functions for orchestrator setup
- **Benefits**: Simplifies configuration while maintaining dependency injection

---

## Bootstrap (`cemaf/bootstrap.py`)

- **Purpose**: Composition root for creating a fully-wired executor
- **Key Functions**:
  - `create_executor(agent_registry, config, services)` - Wires `ContextNodeExecutor`, subscribes `OnlineEvalPipeline` and `QualityPolice` to EventBus, creates `DAGExecutor` with all optional services
- **Features**: Single entry point that replaces manual wiring of 15+ components

---

## Context Engine (`cemaf/context/`)

### `context.py`

- **Purpose**: Immutable context object for agentic workflows
- **Key Class**: `Context`
- **Features**:
  - Immutable (all mutations return new instance)
  - `set()` uses `copy.deepcopy()` for nested dict immutability
  - Dot-notation access (`context.get("user.preferences.theme")`)
  - `set()`, `merge()`, `delete()` operations
  - JSON-serializable

### `patch.py`

- **Purpose**: Provenance tracking for context changes
- **Key Classes**:
  - `ContextPatch`: Immutable record of change (path, operation, value, source, timestamp, reason)
  - `PatchOperation`: SET, DELETE, MERGE, APPEND
  - `PatchSource`: TOOL, AGENT, LLM, SYSTEM, USER
  - `PatchLog`: Append-only log of patches
- **Features**: Full audit trail of who changed what and when

### `source.py`

- **Purpose**: Context source abstraction with metadata and type classification
- **Key Classes**:
  - `ContextType`: Enum (RESOURCE, MEMORY, SKILL) for behavioral classification
  - `ContextSource`: Source of context with priority, recency, token count, and optional `context_type`
- **Features**: Unified representation for documents, API responses, tool outputs, and memory items

### `classification.py`

- **Purpose**: Context type classification and behavioral rules
- **Key Classes**:
  - `ContextTypeBehavior`: Rules per type (cacheable, shareable, compressible, default_ttl, default_priority, preferred_compaction)
  - `ContextTypeClassifier`: Protocol for classifying sources
  - `DefaultContextTypeClassifier`: Default implementation with sensible mappings
- **Features**: Determines compaction, caching, and sharing behavior based on source type

### `compiler.py`

- **Purpose**: Assembles context for LLM calls
- **Key Classes**:
  - `CompiledContext`: Compiled context with deterministic hash
  - `ContextCompiler`: Protocol for compiling context
  - `PriorityContextCompiler`: Priority-based selection with pluggable algorithms
- **Features**:
  - Gathers artifacts and memories
  - Respects token budget
  - Deterministic output (same inputs -> same hash)
  - Converts to LLM message format
  - Pluggable selection algorithms

### `algorithm.py`

- **Purpose**: Extensible context selection algorithms for token budget optimization
- **Key Classes**:
  - `ContextSelectionAlgorithm`: Protocol for selection strategies
  - `SelectionResult`: Immutable result with selected sources and metadata
  - `GreedySelectionAlgorithm`: O(n) fast selection by priority (default)
  - `KnapsackSelectionAlgorithm`: O(n x budget) optimal priority maximization via dynamic programming
  - `OptimalSelectionAlgorithm`: Brute force for small sets (<20 sources), knapsack fallback for larger sets
- **Features**:
  - Pluggable algorithm implementations via protocol
  - Automatic fallback strategies for large budgets/datasets
  - Rich metadata tracking (selection_method, excluded_keys, max_priority_sum, guaranteed_optimal)
  - Engineers can implement custom algorithms by conforming to protocol
- **Related**: Full guide with examples in [docs/context_algorithms.md](./context_algorithms.md)

### `budget.py`

- **Purpose**: Token budget management
- **Key Classes**:
  - `TokenBudget`: Defines max tokens, reserved output, allocations
  - `BudgetAllocation`: Allocation per section with priority
- **Features**: Model-specific budgets, section allocation, output reservation

### `classification.py`

- **Purpose**: Behavioral semantics for context sources based on type
- **Key Classes**:
  - `ContextTypeBehavior`: Frozen dataclass encoding cacheable, shareable, compressible, default_ttl, default_priority, preferred_compaction
  - `ContextTypeClassifier`: Protocol for classifying sources and resolving behavior
  - `DefaultContextTypeClassifier`: Default classifier with configurable behavior registry and source_type_map
- **Exports**: `classify_source()`, `get_behavior()` module-level convenience functions
- **Types**: Maps to `ContextType` enum (RESOURCE, MEMORY, SKILL) from `context/source.py`
- **Features**: Per-type compaction rules, caching/sharing policies, TTL defaults

### `advanced_compiler.py`

- **Purpose**: Advanced context compilation with LLM-based summarization
- **Key Classes**:
  - `AdvancedContextCompiler`: Dual-mode compiler (pure summarization or two-stage optimization)
  - `AdvancedCompilerConfig`: Configuration for summarization behavior
- **Features**:
  - **Mode 1 (default)**: Includes all sources, summarizes low-priority ones to fit budget
  - **Mode 2 (algorithm-enabled)**: Uses selection algorithm first, then summarization fallback
  - LLM-based content summarization to compress sources while preserving information
  - Configurable summarization targets and retry logic
- **Dependencies**: Uses `context/algorithm.py` for Mode 2 selection strategies
- **Related**: Full guide in [docs/context.md](./context.md#advancedcontextcompiler-modes)

### `factories.py`

- **Purpose**: Factory functions for context compilers
- **Key Functions**:
  - `create_priority_compiler()` - Create PriorityContextCompiler with defaults
  - `create_advanced_compiler()` - Create AdvancedContextCompiler with LLM client
  - `create_greedy_compiler()` - Explicit greedy algorithm selection
  - `create_knapsack_compiler()` - Explicit knapsack algorithm selection
  - `create_optimal_compiler()` - Explicit optimal algorithm selection
  - `create_token_estimator(model)` - Smart factory preferring tiktoken when available
  - `create_context_compiler_from_config()` - Environment-based compiler creation via `ProviderRegistry`
- **Registry**: `context_compiler_registry` -- extensible `ProviderRegistry[ContextCompiler]` with greedy/knapsack/optimal built-in
- **Benefits**: Provides sensible defaults while maintaining dependency injection principles

---

## RLM - Recursive Language Models (`cemaf/rlm/`)

### `protocols.py`

- **Purpose**: Core RLM protocols for recursive context querying
- **Key Classes**:
  - `ContextChunk`: Immutable chunk of context (chunk_id, content, token_count, parent_id, depth, metadata)
  - `RecursiveQueryResult`: Result with answer, relevant_chunks, error, execution metadata
  - `ChunkingStrategy`: Protocol for breaking content into chunks
  - `RecursiveQueryEngine`: Protocol for recursive query execution
- **Features**:
  - Chunks convert to `ContextSource` for compilation
  - Hierarchical chunk organization (parent/child relationships)
  - Full execution trace (depth, chunks examined, LLM calls, tokens used)

### `chunking.py`

- **Purpose**: Chunking strategies for breaking large content into processable chunks
- **Key Class**: `FixedSizeChunkingStrategy`
- **Features**:
  - Token-based chunking with paragraph/sentence/word boundaries
  - Configurable chunk size (default 500 tokens)
  - Uses `TokenEstimator` for accurate sizing
  - Creates flat chunk structure (depth=0)

### `engine.py`

- **Purpose**: Recursive query engine with divide-and-conquer strategy
- **Key Class**: `DivideAndConquerQueryEngine`
- **Algorithm**:
  1. Base case: If chunks fit in budget, single LLM call
  2. Recursive case: Split chunks, query each, aggregate results
  3. Fallback: Max depth reached or single large chunk, query first chunk only
- **Features**:
  - Uses `PriorityContextCompiler` for budget enforcement
  - Respects max_depth to prevent infinite recursion
  - Aggregates results from recursive queries
  - Detailed metadata (strategy, depth, tokens, LLM calls)

### `tool.py`

- **Purpose**: RLM as a CEMAF Tool for integration with Skills and Agents
- **Key Class**: `RLMQueryTool`
- **Features**:
  - Implements standard `Tool` protocol
  - Schema compatible with OpenAI/Anthropic function calling
  - Parameters: instruction, content, max_depth, max_tokens, chunk_size
  - Returns `ToolResult` with execution metadata
  - Never raises exceptions (always returns Result)

### `__init__.py`

- **Purpose**: Public API and factory function
- **Key Function**: `create_rlm_tool()`
- **Features**:
  - Creates configured RLMQueryTool with sensible defaults
  - Dependency injection for LLM client and token estimator
  - Customizable parameters (chunk_size, max_depth, max_tokens)
  - Wires together: ChunkingStrategy + RecursiveQueryEngine + RLMQueryTool

### Integration with CEMAF

RLM integrates seamlessly with CEMAF's core systems:
- **Context Compilation**: Uses `TokenBudget` and `ContextCompiler`
- **Token Estimation**: Uses `TokenEstimator` for accurate chunk sizing
- **LLM Integration**: Uses `LLMClient` protocol (supports any LLM backend)
- **Tool System**: Implements `Tool` protocol (works with `ToolRegistry`)
- **Skill/Agent Composition**: Injects into Skills via dependency injection
- **Result Pattern**: Returns `Result[T]` consistently

### Use Cases

- Query large documents (100K+ tokens) that exceed LLM context window
- Recursive analysis of large codebases
- Summarization of extensive reports or datasets
- Finding specific information in large knowledge bases
- Divide-and-conquer processing of batch data

### Example

```python
from cemaf.rlm import create_rlm_tool
from cemaf.llm.anthropic import AnthropicLLMClient

llm = AnthropicLLMClient(api_key="...")
rlm_tool = create_rlm_tool(llm, chunk_size=500, max_depth=3)

result = await rlm_tool.execute(
    instruction="Find all mentions of CEMAF",
    content=large_document,  # 100K tokens
)

print(f"Answer: {result.data}")
print(f"Metadata: {result.metadata}")
# depth_reached, chunks_examined, llm_calls_made, total_tokens_used
```

---

## Observability (`cemaf/observability/`)

### `run_logger.py`

- **Purpose**: Recording and replaying agent runs with provenance tracking
- **Key Classes**:
  - `ToolCall`: Record of tool invocation (input, output, duration, timestamp, correlation_id, node_id, agent_id)
  - `LLMCall`: Record of LLM call (messages, response, tokens, latency, context_sources_used, context_hash, budget_utilization, cost_usd, provenance_link_id)
  - `RunRecord`: Complete run record (run_id, patches, tool_calls, llm_calls, final_context, total_cost_usd, provenance_chain, selection_summaries)
  - `RunLogger`: Protocol for recording (includes `record_provenance_link()`)
  - `InMemoryRunLogger`: In-memory implementation
- **Features**:
  - Replay-friendly (deterministic)
  - Full trace of execution with provenance
  - Correlation IDs for tracing
  - Cost tracking per LLM call

### `budget_guard.py`

- **Purpose**: Cost and token limit enforcement across DAG runs
- **Key Classes**:
  - `AlertLevel`: Enum (INFO, WARNING, CRITICAL, HALT)
  - `BudgetAlert`: Immutable alert record (level, utilization, message)
  - `BudgetGuard`: Configurable guard with `record_usage()`, `check_budget()`, `should_halt()`
- **Features**:
  - Configurable warning/critical/halt thresholds
  - Tracks accumulated cost and tokens
  - Integrated with DAGExecutor

### `glass_box.py`

- **Purpose**: Complete audit report generation from RunRecords
- **Key Classes**:
  - `CostBreakdown`: Per-model, per-node, per-agent cost breakdown
  - `TokenAudit`: Per-source, per-node, per-agent token breakdown with exclusion reasons
  - `DecisionStep`: What an LLM saw vs decided (sources seen/excluded, citations, output)
  - `CitationCoverage`: Verification that citations reference sources the LLM actually saw
  - `GlassBoxReport`: Complete audit trail (provenance, citations, tokens, costs, decisions, quality)
  - `GlassBoxReporter`: Generates reports from RunRecords
- **Features**:
  - Decision trace: full transparency into each LLM call
  - Citation coverage verification
  - Serializable via `to_dict()`

### `structured.py`

- **Purpose**: Production-grade structured logging
- **Key Classes**:
  - `StructuredLogger`: JSON-lines logger satisfying the `Logger` protocol
- **Features**:
  - Outputs structured JSON records to stdout
  - Timestamps, log levels, injectable context fields
  - Drop-in replacement for the default logger in production

### `prometheus_metrics.py`

- **Purpose**: Production metrics collection for monitoring and alerting
- **Key Classes**:
  - `PrometheusMetrics`: `MetricsCollector` backed by `prometheus_client`
- **Features**:
  - Lazy metric registration (counters, gauges, histograms)
  - Configurable prefix (default: `cemaf`)
  - `generate_metrics()` for Prometheus scraping endpoint
  - Requires `prometheus-client` package (`cemaf[prometheus]`)

### `health.py`

- **Purpose**: Health monitoring for runtime components
- **Key Classes**: `HealthMonitor`
- **Features**: Registered as optional dependency in `RuntimeServices`

### `protocols.py` & `simple.py`

- **Purpose**: Additional observability protocols and simple implementations

---

## Memory & Retrieval

### `memory/base.py`

- **Purpose**: Memory storage with scoping and TTL
- **Key Classes**:
  - `MemoryItem`: Immutable memory item (scope, key, value, confidence, TTL, expires_at, scope_path)
  - `MemoryStore`: Abstract store with redaction/serialization hooks
  - `InMemoryStore`: In-memory implementation
- **Features**:
  - Scoped memory (brand, project, session, etc.)
  - TTL support
  - Redaction hooks for PII
  - Serialization hooks
  - Expiration cleanup

### `memory/protocols.py`

- **Purpose**: Memory store protocol definitions
- **Key Protocols**: `MemoryStore`

### `memory/semantic.py`

- **Purpose**: Semantic (embedding-based) memory storage and search
- **Key Classes**:
  - `MemoryQuery`: Query parameters (text, scope, limit, min_confidence, scope_path)
  - `MemorySearchResult`: Result with item, score, rank
  - `SemanticMemoryStore`: Protocol for semantic memory stores
  - `DefaultSemanticMemoryStore`: Implementation backed by `VectorStore` + `EmbeddingProvider`
- **Features**: Embedding-based similarity search over memory items

### `memory/scoring.py`

- **Purpose**: Memory relevance scoring
- **Key Classes**: `TemporalDecayScorer`
- **Features**: Time-based decay for memory relevance ranking

### `memory/episodic.py`

- **Purpose**: Episodic memory (event-based) storage
- **Key Classes**:
  - `Episode`, `EpisodicEvent`: Episodic memory structures
  - `InMemoryEpisodicStore`: In-memory implementation

### `memory/manager.py`

- **Purpose**: High-level memory management facade
- **Key Classes**:
  - `MemoryManager`: Protocol for memory management
  - `DefaultMemoryManager`: Default implementation coordinating store, scoring, and events

### `memory/compaction.py`

- **Purpose**: Memory compaction (summarization and deduplication)
- **Key Classes**: `MemoryCompactor`, `SimpleMemoryCompactor`

### `memory/session.py`

- **Purpose**: Session lifecycle management
- **Key Classes**:
  - `SessionManager`: Protocol
  - `DefaultSessionManager`: Manages bootstrap/dispose, runs `ExtractionPipeline` on dispose
- **Features**: Scoped session cleanup, extraction pipeline integration

### `memory/context_provider.py`

- **Purpose**: Bridge between memory system and context compiler pipeline
- **Key Classes**:
  - `MemoryContextProvider`: Protocol that pulls memories and formats them as `ContextSource` items for compilation
- **Features**: Closes the memory -> retrieval -> context loop

### `memory/deduplication.py`

- **Purpose**: Detect and resolve near-duplicate memory items
- **Key Classes**:
  - `MatchType`: Enum (EXACT_KEY, SEMANTIC, PARTIAL_KEY)
  - `DeduplicationAction`: Enum (STORE_NEW, SKIP, MERGE)
  - `DuplicateMatch`: Detected duplicate with match type, similarity score, existing item
  - `MemoryDeduplicator`: Protocol for deduplication
  - `SemanticDeduplicator`: Implementation using exact key match + embedding similarity threshold
- **Features**: Prevents duplicate memories from accumulating across sessions

### `memory/tiered.py`

- **Purpose**: Three-tier memory item representation
- **Key Classes**:
  - `TieredMemoryItem`: L0 (metadata), L1 (summary), L2 (full content)
  - `TierGenerator`: Protocol for generating tiers from a MemoryItem
  - `TruncationTierGenerator`: Default implementation using value truncation

### `memory/tiered_store.py`

- **Purpose**: Tier-aware memory store with progressive retrieval
- **Key Classes**:
  - `TieredMemoryStore`: Wraps `SemanticMemoryStore` with L0/L1/L2 progressive search
- **Features**:
  - `store_with_tiers()` generates and caches tier representations
  - `progressive_search()` retrieves L0 candidates, promotes relevant ones to L1/L2
  - Stays within token budget by loading detail on demand

### `memory/scope_hierarchy.py`

- **Purpose**: Hierarchical scope propagation for memory retrieval
- **Key Classes**:
  - `ScopePath`: Slash-separated hierarchical path (`project/campaign/assets`)
  - `PropagatingScorer`: Queries ancestor scopes with distance-decayed relevance
- **Features**:
  - `ScopePath.parent`, `ScopePath.is_ancestor_of()`, `ScopePath.depth`
  - Memory items carry `scope_path` for fine-grained retrieval
  - Ancestor queries enable inheritance of project-level memories into child scopes

### `memory/extraction.py`

- **Purpose**: Memory extraction from session episodes
- **Key Classes**:
  - `ExtractedMemory`: Extracted fact with confidence and source episode
  - `MemoryExtractor`: Protocol for extraction
  - `RuleBasedExtractor`: Default implementation using configurable rules

### `memory/extraction_pipeline.py`

- **Purpose**: Extract -> deduplicate -> store pipeline
- **Key Classes**:
  - `ExtractionReport`: Summary (extracted_count, stored_count, deduplicated_count, skipped_count)
  - `ExtractionPipeline`: Orchestrates extractor -> deduplicator -> memory manager
- **Features**: Runs during `SessionManager.dispose()`, promotes SESSION to PROJECT scope, emits `MEMORY_EXTRACTED` event

### `memory/sqlite_store.py`

- **Purpose**: SQLite-backed persistent MemoryStore
- **Key Classes**:
  - `SqliteMemoryStore`: Persistent store using `aiosqlite`
- **Features**:
  - Single table with scope/key primary key
  - JSON-serialized values, TTL/expiry columns
  - Supports `scope_path` for hierarchical scoping
  - Production-ready alternative to `InMemoryStore`

### `memory/factories.py`

- **Purpose**: Factory functions for memory components
- **Key Functions**:
  - `create_memory_store(backend)` - Factory with `"memory"` and `"sqlite"` backends
  - `create_semantic_memory_store()` - Wires VectorStore + EmbeddingProvider
  - `create_memory_manager(embedding_provider)` - Full manager with optional embedding provider
  - `create_tiered_memory_store()` - TieredMemoryStore with tier generator
  - `create_extraction_pipeline()` - ExtractionPipeline with extractor + deduplicator
  - `create_scope_scorer()` - PropagatingScorer with configurable decay
  - `create_session_manager(extraction_pipeline)` - SessionManager with optional extraction
- **Benefits**: BYO-X pattern -- every component is injectable

### `retrieval/protocols.py`

- **Purpose**: Vector store and embedding abstractions
- **Key Classes**:
  - `Document`: Document with content, embedding, metadata
  - `SearchResult`: Search result with similarity score
  - `EmbeddingProvider`: Protocol for embedding generation
  - `VectorStore`: Protocol for vector storage and search
- **Features**: Metadata filtering, similarity search, embedding generation

### `retrieval/hybrid.py`

- **Purpose**: Combines vector and keyword search
- **Key Classes**: `HybridRetriever`, `RetrievalConfig`
- **Features**: Reciprocal Rank Fusion (RRF) to merge results

### `retrieval/memory_store.py`

- **Purpose**: In-memory vector store implementation
- **Key Classes**: `InMemoryVectorStore`, `MockEmbeddingProvider`
- **Features**: Fast in-memory storage for development and testing

### `retrieval/openai_embeddings.py`

- **Purpose**: Production embedding provider using OpenAI API
- **Key Classes**:
  - `OpenAIEmbeddingProvider`: `EmbeddingProvider` backed by OpenAI `text-embedding-3-small`
- **Features**:
  - Configurable model and dimension (default: 1536)
  - Handles empty text gracefully (returns zero vectors)
  - `embed_batch()` sends all non-empty texts in a single API call
  - Requires `openai` package (`cemaf[openai]`)

### `retrieval/factories.py`

- **Purpose**: Factory functions for retrieval components
- **Key Functions**:
  - Vector store creation with embedding providers
  - Hybrid retriever configuration
- **Benefits**: Simplified setup for retrieval pipelines

---

## LLM (`cemaf/llm/`)

### `protocols.py`

- **Purpose**: Protocol-based LLM client abstraction
- **Key Classes**:
  - `MessageRole`: SYSTEM, USER, ASSISTANT, TOOL
  - `Message`: Message with role, content, tool_calls, tool_call_id
  - `ToolCall`: Tool call request (id, name, arguments)
  - `ToolDefinition`: Tool schema for LLM
  - `LLMClient`: Protocol for LLM clients
  - `CompletionResult`: Result with message, tokens, latency
  - `StreamChunk`: Streaming chunk
- **Features**:
  - Pluggable backends (OpenAI, Anthropic, local)
  - Tool/function calling
  - Streaming support
  - Token counting

### `instrumented.py`

- **Purpose**: Transparent LLM call recording for glass box audit
- **Key Classes**:
  - `InstrumentedLLMClient`: Wraps any `LLMClient`, auto-records every `complete()`/`stream()` call into a `RunLogger`
- **Features**:
  - Records model, input/output tokens, duration, cost, node_id, agent_id per call
  - Transparent -- callers see a standard `LLMClient` interface
  - Automatically applied by `ContextNodeExecutor` when `RunLogger` is present
  - Records failures as well as successes

### `resilient.py`

- **Purpose**: Resilient LLM client with fault tolerance
- **Key Classes**:
  - `ResilientLLMClient`: Wraps any `LLMClient` with retry, circuit breaker, and rate limiting
- **Features**:
  - `RetryPolicy` with configurable backoff (constant/linear/exponential/fibonacci)
  - `CircuitBreaker` with failure window and recovery timeout
  - `RateLimiter` with token bucket algorithm
  - Optional `MetricsCollector` for observability integration
  - Transparent -- delegates to inner client, adds resilience layers

### `tiktoken_estimator.py`

- **Purpose**: Precise token counting for OpenAI models using tiktoken
- **Key Classes**:
  - `TiktokenEstimator`: Model-specific tokenizer with `is_accurate` property
- **Used By**: `create_token_estimator()` factory (preferred when available)

### `mock.py`

- **Purpose**: Mock LLM client for testing

---

## Evals (`cemaf/evals/`)

### `protocols.py`

- **Purpose**: Output evaluation abstraction
- **Key Classes**:
  - `EvalMetric`: PASS_FAIL, EXACT_MATCH, SEMANTIC_SIMILARITY, COHERENCE, RELEVANCE, TOXICITY, etc.
  - `EvalConfig`: Configuration (pass_threshold, metrics)
  - `EvalResult`: Result with score (0.0-1.0), passed, reason, expected/actual, confidence
  - `Evaluator`: Protocol for evaluators
  - `BaseEvaluator`: Abstract base with shared logic
- **Features**: Multi-metric evaluation, confidence scores

### `evaluators.py`

- **Purpose**: Built-in deterministic evaluators
- **Key Classes**: `ExactMatchEvaluator`, `ContainsEvaluator`, `LengthEvaluator`, `JSONSchemaEvaluator`

### `semantic.py`

- **Purpose**: Semantic similarity evaluator using embeddings

### `llm_judge.py`

- **Purpose**: LLM-based evaluation (LLM-as-judge)

### `composite.py`

- **Purpose**: Composite evaluator that runs multiple evaluators and aggregates results
- **Key Classes**: `CompositeEvaluator`

### `hierarchy.py`

- **Purpose**: Hierarchical multi-tier evaluation -- fast checks first, expensive judges last
- **Key Classes**:
  - `TierResult`: Result from a single tier (tier, score, passed, escalated)
  - `HierarchicalJudgeConfig`: Thresholds (tier1_pass_threshold, tier3_ambiguity_range, tier3_sample_rate)
  - `HierarchicalJudge(BaseEvaluator)`: Three-tier cascade
- **Algorithm**:
  1. **Tier 1** (deterministic): Runs fast evaluators (exact match, length, JSON schema)
  2. **Tier 2** (semantic): Runs if tier 1 score falls in ambiguity range
  3. **Tier 3** (LLM judge): Runs if tier 2 is ambiguous or via configurable sample rate
- **Features**: Minimizes LLM judge calls while maintaining evaluation quality

### `online.py`

- **Purpose**: Online evaluation pipeline for runtime quality monitoring
- **Key Classes**:
  - `EvalMode`: Enum (GATE, OBSERVE)
  - `NodeEvalBinding`: Binds evaluators to node patterns (specific node_id or `"*"` wildcard)
  - `OnlineEvalPipeline`: Subscribes to `TASK_COMPLETED` events via `EventBus`
- **Features**:
  - Event-driven evaluation on node outputs during execution
  - GATE mode blocks downstream nodes on eval failure
  - OBSERVE mode logs results without blocking
  - Wired automatically by `bootstrap.create_executor()`

### `police.py`

- **Purpose**: Rolling quality monitor with anomaly detection and halt logic
- **Key Classes**:
  - `AlertLevel`: Enum (WARN, CRITICAL, HALT)
  - `QualityAlert`: Alert with level, score, rolling_mean, message
  - `QualityPoliceConfig`: Thresholds (window_size, warn_threshold, critical_threshold, halt_threshold)
  - `QualityPolice`: Rolling window quality monitor
- **Features**:
  - Maintains rolling window of recent scores
  - Emits alerts when quality degrades below thresholds
  - `should_halt()` gate integrated with `DAGExecutor`
  - Subscribes to EventBus for automatic score ingestion

### `tools.py`

- **Purpose**: Eval system exposed as CEMAF tools for agent self-evaluation
- **Key Classes**:
  - `RunEvalTool`: Run evaluators against output text
  - `CheckQualityTool`: Check current quality police status
  - `RecordScoreTool`: Record a score to quality police
- **Features**: Built-in evaluator registry (`BUILTIN_EVALUATORS`), `resolve_evaluators(names)` helper

### `agents.py`

- **Purpose**: Quality guard agent that dogfoods the CEMAF agent framework
- **Key Classes**:
  - `QualityGuardGoal`: Goal model (output, expected, evaluator_names, record_to_police)
  - `QualityGuardAgent`: Registered CEMAF agent that evaluates outputs using eval tools and records scores to QualityPolice

### `factories.py`

- **Purpose**: Factory functions for evaluation components
- **Key Functions**:
  - `create_exact_match_evaluator()` - ExactMatchEvaluator with defaults
  - `create_composite_evaluator()` - CompositeEvaluator from evaluator list
  - `create_composite_evaluator_from_config()` - Environment-based creation

---

## Persistence (`cemaf/persistence/`)

### `entities.py`

- **Purpose**: Domain models for multi-tenant project management
- **Key Classes**:
  - `Project`: Multi-tenant project container (status, dates, tenant_id, owner_id)
  - `ContextArtifact`: Versioned context document (type, content, version, sha, source)
  - `ContentItem`: Generated content (platform, format, brief, title, body, caption, hashtags, assets, status)
  - `Run`: Execution run record
- **Features**: All immutable (frozen Pydantic models)

### `protocols.py`

- **Purpose**: Persistence layer protocols

---

## Resilience (`cemaf/resilience/`)

### `retry.py`

- **Purpose**: Configurable retry with backoff
- **Key Classes**:
  - `RetryConfig`: max_attempts, backoff_strategy (constant/linear/exponential/fibonacci), jitter
  - `RetryResult`: Result with attempts count
- **Features**: Exception-based retry, result-based retry, jitter to prevent thundering herd

### `circuit_breaker.py`

- **Purpose**: Prevent cascading failures
- **Key Classes**:
  - `CircuitState`: CLOSED, OPEN, HALF_OPEN
  - `CircuitConfig`: failure_threshold, failure_window, recovery_timeout, success_threshold
  - `CircuitMetrics`: Total/successful/failed/rejected calls
- **Features**: State machine, failure counting, automatic recovery testing

### `rate_limiter.py`

- **Purpose**: Control request rates
- **Key Classes**:
  - `RateLimitConfig`: rate (req/s), burst, wait_on_limit
  - `RateLimiter`: Token bucket algorithm
- **Features**: Smooth rate limiting, wait or reject modes

### `decorators.py`

- **Purpose**: Decorators for applying resilience patterns

---

## Scheduler (`cemaf/scheduler/`)

### `protocols.py`

- **Purpose**: Job scheduling contracts
- **Key Classes**:
  - `JobStatus`: PENDING, RUNNING, COMPLETED, FAILED, CANCELLED, TIMEOUT
  - `JobResult`: Result with status, duration, result/error
  - `Job`: Job definition
  - `Trigger`: Protocol for job triggers
  - `Scheduler`: Protocol for schedulers
- **Features**: Async job execution, trigger-based scheduling

### `executor.py` & `triggers.py`

- **Purpose**: Job executor and trigger implementations

### `mock.py`

- **Purpose**: Mock scheduler for testing

---

## Validation & Moderation

### `validation/pipeline.py`

- **Purpose**: Chain multiple validation rules
- **Key Classes**: `ValidationPipeline`
- **Features**: Fail-fast or collect-all modes, ordered rule execution

### `validation/rules.py` & `validation/protocols.py`

- **Purpose**: Validation rules and protocols

### `moderation/pipeline.py`

- **Purpose**: Pre-flight and post-flight content moderation
- **Key Classes**:
  - `ModerationPipeline`: Chains pre/post gates
  - `ModerationResult`: Result with allowed flag, violations, redacted_content
- **Features**:
  - Input/output checking
  - Event integration
  - Content redaction

### `moderation/gates.py` & `moderation/rules.py`

- **Purpose**: Moderation gates and rules

### `moderation/protocols.py`

- **Purpose**: Moderation protocols

---

## Streaming (`cemaf/streaming/`)

### `protocols.py`

- **Purpose**: Streaming output handling
- **Key Classes**:
  - `EventType`: CONTENT, TOOL_CALL_START, TOOL_CALL_ARGS, TOOL_CALL_END, THINKING, ERROR, DONE
  - `StreamEvent`: Typed event with data, timestamp, metadata
  - `StreamHandler`: Protocol for handling events
  - `StreamBuffer`: Accumulates streaming content
  - `CallbackStreamHandler`: Handler with user callbacks
- **Features**: Chunk accumulation, progress callbacks, cancellation

### `sse.py`

- **Purpose**: Server-Sent Events implementation

---

## Cache (`cemaf/cache/`)

### `protocols.py`

- **Purpose**: Cache abstraction
- **Key Classes**:
  - `CacheEntry`: Cached value with metadata (key, value, created_at, expires_at, hit_count)
  - `CacheStats`: Statistics (hits, misses, size, evictions, hit_rate)
  - `Cache`: Protocol for cache stores
- **Features**: TTL support, hit counting, expiration

### `stores.py` & `decorators.py`

- **Purpose**: Cache store implementations and decorators

### `mock.py`

- **Purpose**: Mock cache for testing

---

## Blueprint/Config

### `blueprint/schema.py`

- **Purpose**: Semantic blueprint models for content generation
- **Key Classes**:
  - `Blueprint`: Defines HOW to accomplish a task (scene_goal, style_guide, participants, instruction)
  - `SceneGoal`: Objective with success_criteria, constraints, priority
  - `StyleGuide`: Tone, format, length_hint, vocabulary, avoid terms, examples
  - `Participant`: Role with name, traits, voice, constraints
- **Features**: Based on Denis Rothman's Semantic Blueprint concept, converts to structured prompts

### `blueprint/builder.py` & `blueprint/rules.py`

- **Purpose**: Blueprint builders and validation rules

### `config/protocols.py`

- **Purpose**: Configuration source abstraction
- **Key Classes**:
  - `ConfigSource`: Protocol for loading config (files, env vars, remote services)
  - `LLMSettings`, `MemorySettings`, `CacheSettings`: Settings models
- **Features**: Hot-reload via `watch()`, async loading

### `config/loader.py`

- **Purpose**: Configuration loader implementations

---

## Events/Bus/Notifiers (`cemaf/events/`)

### `protocols.py`

- **Purpose**: Event system contracts
- **Key Classes**:
  - `EventType`: Comprehensive event types (task, validation, content, agent, DAG, system, context, tool, replay, memory, execution, moderation, citation)
  - `Event`: Event with type, data, timestamp, metadata
  - `EventBus`: Protocol for event bus
  - `EventHandler`: Protocol for event handlers
- **Features**: Typed events, async handling, metadata support

### `bus.py` & `notifiers.py`

- **Purpose**: Event bus implementation and notifiers

### `mock.py`

- **Purpose**: Mock event bus for testing

---

## Replay (`cemaf/replay/`)

### `replayer.py`

- **Purpose**: Deterministic replay executor for agent runs
- **Key Classes**:
  - `Replayer`: Replays RunRecord
  - `ReplayMode`: PATCH_ONLY, MOCK_TOOLS, LIVE_TOOLS
  - `ReplayResult`: Result with final_context, patches_applied, tools_replayed, divergences
- **Features**:
  - Reproduces final context from RunRecord
  - Multiple replay modes
  - Divergence detection

### `factories.py`

- **Purpose**: Factory functions for replayer creation
- **Key Functions**:
  - `create_replayer()` - Create Replayer with mode configuration
  - Tool executor setup for different replay modes
- **Benefits**: Simplified replay setup with sensible defaults

---

## Generation (`cemaf/generation/`)

### `protocols.py`

- **Purpose**: Generative AI abstractions
- **Key Classes**:
  - Format enums: `ImageFormat`, `AudioFormat`, `VideoFormat`, `DiagramType`, `UIComponentType`, `CodeLanguage`
  - `TextSpec`, `ImageSpec`, `AudioSpec`, `VideoSpec`, `DiagramSpec`, `UISpec`, `CodeSpec`: Immutable specs
  - `TextGenerator`, `ImageGenerator`, `AudioGenerator`, etc.: Protocols for generators
- **Features**: All specs immutable for reproducibility, Protocol-based for pluggability

### `mock.py`

- **Purpose**: Mock generator implementations for testing

---

## Citation (`cemaf/citation/`)

### `tracker.py`

- **Purpose**: Tracks citations through retrieval and generation pipeline
- **Key Classes**:
  - `CitationTracker`: Tracks citations from SearchResults
  - `Citation`, `CitedFact`, `CitationRegistry`: Citation models
- **Features**: Automatic citation creation from retrieval results, citation reports

### `models.py` & `rules.py`

- **Purpose**: Citation models and validation rules

---

## MCP (Model Context Protocol) (`cemaf/mcp/`)

### `protocols.py`

- **Purpose**: JSON-RPC 2.0 message types for MCP communication
- **Key Classes**:
  - `MCPError`: JSON-RPC 2.0 error object
  - `MCPRequest`, `MCPResponse`, `MCPNotification`: JSON-RPC message types
  - `MCPTransport`: Protocol for transport (stdio, SSE, WebSocket)
- **Features**: Standard JSON-RPC 2.0 protocol, transport abstraction

### `adapter.py`

- **Purpose**: MCP adapter implementation

### `bridges/`

- **Purpose**: Bridges for tools, resources, prompts
  - `tool_bridge.py`: Bridge CEMAF tools to MCP tools
  - `resource_bridge.py`: Bridge CEMAF resources to MCP resources
  - `prompt_bridge.py`: Bridge CEMAF prompts to MCP prompts

### `transport/`

- **Purpose**: Transport implementations
  - `stdio.py`: STDIO transport
  - `sse.py`: Server-Sent Events transport
  - `websocket.py`: WebSocket transport
  - `base.py`: Base transport protocol

### `types.py`

- **Purpose**: MCP-specific types

---

## Factory Pattern Overview

CEMAF uses factory functions throughout the codebase to provide convenient creation of complex objects while maintaining dependency injection principles:

**Bootstrap** (`bootstrap.py`):
- `create_executor()` -- composition root wiring all services

**Context Factories** (`context/factories.py`):
- Compiler creation with sensible defaults
- Algorithm selection helpers
- Token estimator configuration

**Orchestration Factories** (`orchestration/factories.py`):
- DAG executor setup
- Orchestrator configuration

**Memory Factories** (`memory/factories.py`):
- Memory store creation (`"memory"`, `"sqlite"` backends)
- Semantic memory store, tiered store, session manager
- Extraction pipeline, scope scorer, deduplicator

**Retrieval Factories** (`retrieval/factories.py`):
- Vector store initialization
- Hybrid retriever setup

**Evals Factories** (`evals/factories.py`):
- Evaluator creation with defaults
- Composite evaluator from config

**Replay Factories** (`replay/factories.py`):
- Replayer mode configuration
- Tool executor setup

This pattern allows engineers to:
- Get started quickly with defaults
- Maintain explicit dependencies for testing
- Customize behavior through parameters
- Follow best practices automatically

---

## Summary

CEMAF is a comprehensive, modular framework for building AI agent systems with:

1. **Type Safety**: Strong typing with NewType IDs and enums
2. **Result Pattern**: Consistent error handling via `Result[T]`
3. **Hierarchy**: Tools -> Skills -> Agents -> DeepAgent
4. **Orchestration**: Dynamic DAGs with parallel execution, routing, and node handlers
5. **Context Engineering**: Immutable context with provenance tracking, pluggable selection algorithms, and type classification
6. **Online Evals**: Three-tier hierarchical evaluation with quality police and halt gates
7. **Memory**: Semantic, tiered, deduplicated memory with scope propagation and post-session extraction
8. **Observability**: Structured logging, Prometheus metrics, full run logging for replay and debugging
9. **Resilience**: Retry, circuit breaker, rate limiting, resilient LLM client
10. **Pluggability**: Protocol-based design for all major components (BYO-X)
11. **Production Backends**: SQLite memory, OpenAI embeddings, Prometheus metrics
12. **Immutability**: Most models are frozen for reproducibility
13. **Modularity**: Each module is independent and composable

The framework emphasizes:

- **Determinism**: Replay-friendly, deterministic context compilation
- **Provenance**: Full audit trail of context changes
- **Type Safety**: Compile-time checks prevent bugs
- **Extensibility**: Protocol-based design allows custom implementations (e.g., custom selection algorithms)
- **Observability**: Comprehensive logging, metrics, and event system
- **Best Practices**: Factory functions encode framework patterns and sensible defaults

---

## Additional Resources

- **Official Documentation**: [docs/README.md](./README.md)
- **Quickstart Guide**: [docs/quickstart.md](./quickstart.md)
- **Architecture Guide**: [docs/architecture.md](./architecture.md)
- **Context Algorithms**: [docs/context_algorithms.md](./context_algorithms.md)
- **Integration Guide**: [docs/integration.md](./integration.md)
