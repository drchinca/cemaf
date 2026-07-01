# Environment Configuration Guide

This document explains the `.env.example` file and answers common questions about configuration values.

## Why `max_tokens=4096`?

The `CEMAF_LLM_MAX_TOKENS=4096` setting is **NOT** the context window size. It's the maximum number of tokens the LLM can **generate in its response**.

### Key Distinction:

- **Context Window**: How much input the model can process (managed by `TokenBudget`)
  - Default: 8,000 tokens (`DEFAULT_CONTEXT_BUDGET`)
  - Maximum: 128,000 tokens (`MAX_CONTEXT_TOKENS`)
  - Modern models support 128k-200k tokens

- **Max Tokens (Response)**: How much the model can generate in its output
  - Default: 4,096 tokens
  - This is a reasonable default for most use cases
  - You can increase if you need longer responses

### Model Context Windows:

| Model | Context Window | Max Response |
|-------|---------------|--------------|
| GPT-4o | 128,000 | 16,384 |
| GPT-4.1 | 1,000,000 | 32,768 |
| Claude Sonnet 4.6 | 1,000,000 | 64,000 |
| Claude Opus 4.7 | 200,000 | 32,000 |
| Claude Haiku 4.5 | 200,000 | 8,192 |
| Gemini 2.5 Pro | 2,000,000 | 8,192 |

**Note**: CEMAF uses `TokenBudget.for_model()` to automatically set appropriate context budgets based on the model.

## Extensibility Points

CEMAF is designed to be extensible. The `.env.example` includes configuration for:

### 1. LLM Providers

CEMAF supports any LLM provider through the `LLMClient` protocol:

- **OpenAI** (GPT models)
- **Anthropic** (Claude models)
- **Google** (Gemini models)
- **Cohere** (Cohere models)
- **Hugging Face** (Open-source models)
- **Ollama** (Local models)
- **Custom providers** (implement `LLMClient` protocol)

### 2. Vector Stores

CEMAF supports any vector store through the `VectorStore` protocol:

- **Pinecone** (Cloud vector database)
- **Qdrant** (Open-source vector database)
- **Weaviate** (Graph + vector database)
- **Chroma** (Embeddings database)
- **PGVector** (PostgreSQL extension)
- **FAISS** (Local vector search)
- **In-Memory** (Development/testing)
- **Custom stores** (implement `VectorStore` protocol)

### 3. Embedding Providers

CEMAF supports any embedding provider through the `EmbeddingProvider` protocol:

- **OpenAI** (text-embedding-3-small, text-embedding-3-large)
- **Cohere** (embed-english-v3.0, embed-multilingual-v3.0)
- **Sentence Transformers** (all-MiniLM-L6-v2, all-mpnet-base-v2)
- **Hugging Face** (Any Hugging Face embedding model)
- **Custom providers** (implement `EmbeddingProvider` protocol)

### 4. Memory Backends

CEMAF supports different memory storage backends:

- **In-Memory** (Development, default)
- **PostgreSQL** (Production, persistent)
- **Redis** (Fast, distributed)
- **Custom backends** (implement `MemoryStore` protocol)

### 5. Graph Databases (Extensible)

While not in core CEMAF, you can extend it with graph databases:

- **Neo4j** (Graph database)
- **ArangoDB** (Multi-model database)
- **NetworkX** (Python graph library)
- **Custom** (Implement your own graph backend)

### 6. Context Selection Algorithms

CEMAF provides `ContextSelectionAlgorithm` and `TokenEstimator` protocols for custom context assembly:

- **Greedy** (Default, fast, prioritizes high-priority sources)
- **Knapsack** (Optimizes value/priority ratio)
- **Optimal** (Exhaustive search, slower)
- **Custom selection algorithms** (Implement `ContextSelectionAlgorithm`, register with `context_selection_algorithm_registry`, select with `CEMAF_CONTEXT_SELECTION_ALGORITHM`)
- **Custom token estimators** (Implement `TokenEstimator`, register with `token_estimator_registry`, select with `CEMAF_CONTEXT_TOKEN_ESTIMATOR_BACKEND`)

Example custom algorithm:
```python
from cemaf.context import context_selection_algorithm_registry
from cemaf.context.algorithm import SelectionResult
from cemaf.context.budget import TokenBudget

class MyCustomAlgorithm:
    def select_sources(self, sources, budget: TokenBudget) -> SelectionResult:
        # Your custom logic here
        ...

context_selection_algorithm_registry.register(
    backend="my_algorithm",
    factory=lambda **kwargs: MyCustomAlgorithm(),
)
```

### 7. Visualization Tools (Extensible)

CEMAF supports different visualization backends for DAGs:

- **Mermaid** (Default, for DAG export)
- **Graphviz** (Dot format)
- **D3.js** (Interactive visualizations)
- **Custom** (Implement your own visualizer)

### 8. Persistence Backends

CEMAF defines persistence protocols for projects, runs, content, and artifacts. Concrete persistence stores are application-provided: register a backend with the relevant persistence registry, then select it with the `CEMAF_PERSISTENCE_*_STORE_BACKEND` environment variables.

### 9. MCP Transports

CEMAF selects MCP transports through `mcp_transport_registry`:

- **stdio** (Default CLI/server process integration)
- **sse** (HTTP Server-Sent Events; configure with `CEMAF_MCP_SSE_BASE_URL` or `CEMAF_MCP_TRANSPORT_URL`)
- **websocket** (Configure with `CEMAF_MCP_WEBSOCKET_URL` or `CEMAF_MCP_TRANSPORT_URL`)
- **Custom transports** (implement `Transport`, register with `mcp_transport_registry`, select with `CEMAF_MCP_TRANSPORT_TYPE`)

### 10. Model Catalogs

CEMAF selects model catalogs through `catalog_registry`:

- **huggingface** (Default external model catalog)
- **Custom catalogs** (implement `ModelCatalog`, register with `catalog_registry`, select with `CEMAF_CATALOG_BACKEND`)

### 11. Event Buses

CEMAF selects event buses through `event_bus_registry`:

- **async** (Default concurrent in-process event bus)
- **memory** (Sequential in-process event bus)
- **redis** (Durable Redis Streams event bus; configure with `CEMAF_EVENTS_REDIS_URL`)
- **Custom buses** (implement `EventBus`, register with `event_bus_registry`, select with `CEMAF_EVENTS_BACKEND`)

### 12. Evaluators

CEMAF resolves evaluator names through `evaluator_registry`:

- **exact_match**, **contains**, **regex**, **length**, **json_valid** (Deterministic built-ins)
- **groundedness**, **tool_use_success** (Grounding/tool-use built-ins)
- **Custom evaluators** (implement `Evaluator`, register with `evaluator_registry`, resolve by name through eval tools and agents)

### 13. Schedulers

CEMAF selects schedulers through `scheduler_registry`:

- **async** (Default in-process async scheduler)
- **mock** (Testing scheduler)
- **Custom schedulers** (implement `Scheduler`, register with `scheduler_registry`, select with `CEMAF_SCHEDULER_BACKEND`)

### 14. Moderation Rules and Gates

CEMAF composes moderation through `moderation_rule_registry` and `moderation_gate_registry`:

- **keyword**, **pii**, **length**, **pattern** (Built-in moderation rules)
- **pre_flight**, **post_flight**, **composite** (Built-in moderation gates)
- **Custom rules/gates** (implement `ModerationRule` or `ModerationGate`, register with the relevant registry, compose with `create_moderation_rule()` / `create_moderation_gate()`)

### 15. Validation Rules

CEMAF composes validation through `validation_rule_registry`:

- **schema**, **length**, **regex**, **range**, **required_fields** (Built-in validation rules)
- **Custom validation rules** (implement `Rule`, register with `validation_rule_registry`, compose with `create_validation_rule()` or `create_validation_pipeline(rule_specs=...)`)

## Configuration Priority

1. **Environment Variables** (Highest priority)
2. **Config Files** (YAML, JSON, TOML)
3. **Code Defaults** (Lowest priority)

## Adding Custom Configuration

You can add custom settings following the pattern:

```bash
# In .env
CEMAF_CUSTOM_MY_TOOL_API_KEY=your_key
CEMAF_CUSTOM_MY_TOOL_ENABLED=true
```

These will be available in the `Settings.custom` dictionary:

```python
from cemaf.config.loader import SettingsProviderImpl, EnvConfigSource

provider = SettingsProviderImpl()
provider.add_source(EnvConfigSource(prefix="CEMAF"))
settings = await provider.get()

# Access custom settings
my_tool_key = settings.custom.get("my_tool_api_key")
```

## Best Practices

1. **Never commit `.env` files** - Only commit `.env.example`
2. **Use environment-specific values** - Different values for dev/staging/prod
3. **Use secrets management** - For production, use AWS Secrets Manager, HashiCorp Vault, etc.
4. **Document custom settings** - Add comments in `.env.example` for team members
5. **Validate configuration** - Use CEMAF's config validation before running

## Example: Full Production Setup

```bash
# .env.production
CEMAF_ENVIRONMENT=prod
CEMAF_DEBUG=false

# LLM
CEMAF_LLM_DEFAULT_MODEL=claude-3-sonnet
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}  # From secrets manager

# Vector Store
CEMAF_VECTOR_STORE_BACKEND=pinecone
PINECONE_API_KEY=${PINECONE_API_KEY}

# Memory
CEMAF_MEMORY_BACKEND=postgres
CEMAF_POSTGRES_DSN=${DATABASE_URL}
CEMAF_MEMORY_MAX_ITEMS=10000
CEMAF_MEMORY_DEFAULT_TTL_SECONDS=3600

# Observability
CEMAF_OBSERVABILITY_ENABLE_TRACING=true
CEMAF_TRACING_BACKEND=otel
OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_ENDPOINT}
```

## See Also

- [Configuration Documentation](../docs/config.md)
- [Architecture Overview](../docs/architecture.md)
- [How to Use CEMAF](../HOW_TO_USE.md)
