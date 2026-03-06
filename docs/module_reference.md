# CEMAF Module Reference Guide

**Last Updated**: February 2026

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
  - `NodeType` (tool, skill, agent, router, parallel, conditional)
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

### `execution.py` & `storage.py`

- **Purpose**: Execution context and storage abstractions
- **Status**: Core components for execution management

---

## Tools/Skills/Agents Hierarchy

### `tools/base.py`

- **Purpose**: Atomic, stateless functions
- **Key Classes**:
  - `ToolSchema`: JSON Schema for tool parameters (OpenAI/Anthropic format conversion)
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
  - `Node`: Workflow node (tool/skill/agent/router/parallel/conditional)
  - `Edge`: Connection with conditions (ALWAYS, ON_SUCCESS, ON_FAILURE, JSON_RULE)
  - `Condition`: Serializable condition with operators (equals, contains, etc.)
  - `DAG`: Graph with nodes, edges, validation, cycle detection
- **Features**:
  - Dynamic construction at runtime
  - Composable (nests DAGs)
  - Mermaid export
  - JSON serialization

### `executor.py`

- **Purpose**: Executes DAGs with dependency resolution
- **Key Classes**:
  - `DAGExecutor`: Main executor
  - `NodeResult`: Result of single node execution
  - `ExecutionResult`: Complete DAG execution result
- **Features**:
  - Topological sort for dependency resolution
  - Parallel execution for PARALLEL nodes
  - Conditional routing for ROUTER nodes
  - Context propagation
  - Checkpointing for resume
  - Context patch emission
  - Run logging integration

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

### `checkpointer.py`

- **Purpose**: Save/restore execution state for resumability
- **Key Components**: Checkpoint protocol and implementations

### `context_node_executor.py`

- **Purpose**: Bridge between DAG nodes and agents via dynamic registry
- **Key Classes**:
  - `ContextNodeExecutor(NodeExecutor)`: Resolves node ref_id → agent via registry
- **Features**:
  - Builds GoalT from resolved inputs
  - Threads DomainContext + provenance through AgentContext
  - Records LLMCall/ContextPatch/Citation via RunLogger
  - Builds ProvenanceLink per execution

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

## Context Engine (`cemaf/context/`)

### `context.py`

- **Purpose**: Immutable context object for agentic workflows
- **Key Class**: `Context`
- **Features**:
  - Immutable (all mutations return new instance)
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

### `compiler.py`

- **Purpose**: Assembles context for LLM calls
- **Key Classes**:
  - `ContextSource`: Source of context (artifact, memory, message, tool_result)
  - `CompiledContext`: Compiled context with deterministic hash
  - `ContextCompiler`: Protocol for compiling context
  - `PriorityContextCompiler`: Priority-based selection with pluggable algorithms
- **Features**:
  - Gathers artifacts and memories
  - Respects token budget
  - Deterministic output (same inputs → same hash)
  - Converts to LLM message format
  - Pluggable selection algorithms

### `algorithm.py`

- **Purpose**: Extensible context selection algorithms for token budget optimization
- **Key Classes**:
  - `ContextSelectionAlgorithm`: Protocol for selection strategies
  - `SelectionResult`: Immutable result with selected sources and metadata
  - `GreedySelectionAlgorithm`: O(n) fast selection by priority (default)
  - `KnapsackSelectionAlgorithm`: O(n × budget) optimal priority maximization via dynamic programming
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
  - Future: hierarchical summarization support

### `engine.py`

- **Purpose**: Recursive query engine with divide-and-conquer strategy
- **Key Class**: `DivideAndConquerQueryEngine`
- **Algorithm**:
  1. Base case: If chunks fit in budget → single LLM call
  2. Recursive case: Split chunks, query each, aggregate results
  3. Fallback: Max depth reached or single large chunk → query first chunk only
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
# → depth_reached, chunks_examined, llm_calls_made, total_tokens_used
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

### `protocols.py` & `simple.py`

- **Purpose**: Additional observability protocols and simple implementations

---

## Memory & Retrieval

### `memory/base.py`

- **Purpose**: Memory storage with scoping and TTL
- **Key Classes**:
  - `MemoryItem`: Immutable memory item (scope, key, value, confidence, TTL, expires_at)
  - `MemoryStore`: Abstract store with redaction/serialization hooks
  - `InMemoryStore`: In-memory implementation
- **Features**:
  - Scoped memory (brand, project, session, etc.)
  - TTL support
  - Redaction hooks for PII
  - Serialization hooks
  - Expiration cleanup

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

### `tiktoken_estimator.py`

- **Purpose**: Precise token counting for OpenAI models using tiktoken

### `mock.py`

- **Purpose**: Mock LLM client for testing

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

## Evals (`cemaf/evals/`)

### `protocols.py`

- **Purpose**: Output evaluation abstraction
- **Key Classes**:
  - `EvalMetric`: PASS_FAIL, EXACT_MATCH, SEMANTIC_SIMILARITY, COHERENCE, RELEVANCE, TOXICITY, etc.
  - `EvalResult`: Result with score (0.0-1.0), passed, reason, expected/actual, confidence
  - `Evaluator`: Protocol for evaluators
- **Features**: Multi-metric evaluation, confidence scores

### `semantic.py` & `llm_judge.py`

- **Purpose**: Semantic similarity and LLM-based evaluators

### `composite.py` & `evaluators.py`

- **Purpose**: Composite evaluators and implementations

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

**Context Factories** (`context/factories.py`):
- Compiler creation with sensible defaults
- Algorithm selection helpers
- Token estimator configuration

**Orchestration Factories** (`orchestration/factories.py`):
- DAG executor setup
- Orchestrator configuration

**Retrieval Factories** (`retrieval/factories.py`):
- Vector store initialization
- Hybrid retriever setup

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
3. **Hierarchy**: Tools → Skills → Agents → DeepAgent
4. **Orchestration**: Dynamic DAGs with parallel execution and routing
5. **Context Engineering**: Immutable context with provenance tracking and pluggable selection algorithms
6. **Observability**: Full run logging for replay and debugging
7. **Resilience**: Retry, circuit breaker, rate limiting
8. **Pluggability**: Protocol-based design for all major components
9. **Immutability**: Most models are frozen for reproducibility
10. **Modularity**: Each module is independent and composable

The framework emphasizes:

- **Determinism**: Replay-friendly, deterministic context compilation
- **Provenance**: Full audit trail of context changes
- **Type Safety**: Compile-time checks prevent bugs
- **Extensibility**: Protocol-based design allows custom implementations (e.g., custom selection algorithms)
- **Observability**: Comprehensive logging and event system
- **Best Practices**: Factory functions encode framework patterns and sensible defaults

---

## Additional Resources

- **Official Documentation**: [docs/README.md](./README.md)
- **Quickstart Guide**: [docs/quickstart.md](./quickstart.md)
- **Architecture Guide**: [docs/architecture.md](./architecture.md)
- **Context Algorithms**: [docs/context_algorithms.md](./context_algorithms.md)
- **Integration Guide**: [docs/integration.md](./integration.md)
