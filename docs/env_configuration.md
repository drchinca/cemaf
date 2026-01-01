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
| GPT-4 | 8,192 | 4,096 (default) |
| GPT-4 Turbo | 128,000 | 16,384 |
| GPT-4o | 128,000 | 16,384 |
| Claude 3 Opus | 200,000 | 4,096 |
| Claude 3 Sonnet | 200,000 | 4,096 |
| Gemini Pro | 32,000 | 8,192 |

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

CEMAF provides a `ContextSelectionAlgorithm` protocol for custom selection strategies:

- **Greedy** (Default, fast, prioritizes high-priority sources)
- **Knapsack** (Optimizes value/priority ratio)
- **Optimal** (Exhaustive search, slower)
- **Custom** (Implement `ContextSelectionAlgorithm` protocol)

Example custom algorithm:
```python
from cemaf.context.algorithm import ContextSelectionAlgorithm, SelectionResult
from cemaf.context.budget import TokenBudget

class MyCustomAlgorithm:
    def select_sources(self, sources, budget: TokenBudget) -> SelectionResult:
        # Your custom logic here
        ...
```

### 7. Visualization Tools (Extensible)

CEMAF supports different visualization backends for DAGs:

- **Mermaid** (Default, for DAG export)
- **Graphviz** (Dot format)
- **D3.js** (Interactive visualizations)
- **Custom** (Implement your own visualizer)

### 8. Persistence Backends

CEMAF supports different persistence backends for projects, runs, and artifacts:

- **None** (In-memory, default for development)
- **PostgreSQL** (Production, full-featured)
- **SQLite** (Development, file-based)
- **Custom** (Implement persistence protocols)

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
MEMORY_POSTGRES_CONNECTION_STRING=${DATABASE_URL}

# Observability
CEMAF_OBSERVABILITY_ENABLE_TRACING=true
CEMAF_TRACING_BACKEND=otel
OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_ENDPOINT}
```

## See Also

- [Configuration Documentation](../docs/config.md)
- [Architecture Overview](../docs/architecture.md)
- [How to Use CEMAF](../HOW_TO_USE.md)
