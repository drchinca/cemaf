# Retrieval and Vector Stores

The Retrieval module provides vector search, embeddings, and hybrid retrieval capabilities. It enables semantic search over documents, integration with memory stores, and supports various embedding providers.

## Overview

Retrieval in CEMAF provides:

- **Vector Stores**: Pluggable backends for vector similarity search
- **Embedding Providers**: Support for various embedding models
- **Hybrid Retrieval**: Combines vector and keyword search
- **Memory Integration**: Vector stores can be used as memory stores

## Core Components

### VectorStore

The `VectorStore` protocol defines the interface for vector storage:

```python
from cemaf.retrieval import VectorStore, Document, SearchResult

# Store documents
doc = Document(
    id="doc_123",
    content="This is a document about AI",
    metadata={"title": "AI Overview", "author": "Jane Doe"},
)

await vector_store.add([doc])

# Search
results = await vector_store.search(
    query="artificial intelligence",
    k=10,
    filters={"author": "Jane Doe"},
)
```

### EmbeddingProvider

The `EmbeddingProvider` protocol defines embedding generation:

```python
from cemaf.retrieval import EmbeddingProvider

# Generate embedding
embedding = await provider.embed("This is text to embed")

# Batch embedding
embeddings = await provider.embed_batch(["text1", "text2", "text3"])
```

### Document

A document for vector storage:

```python
from cemaf.retrieval import Document

doc = Document(
    id="doc_123",
    content="Document content here",
    embedding=(0.1, 0.2, 0.3, ...),  # Optional embedding
    metadata={"title": "Title", "url": "https://example.com"},
    created_at=datetime.now(),
)
```

### SearchResult

Result of a vector search:

```python
from cemaf.retrieval import SearchResult

result = SearchResult(
    document=doc,
    score=0.95,  # Similarity score (higher = more similar)
    rank=1,  # Position in results
    metadata={},  # Additional metadata
)
```

## Implementations

### InMemoryVectorStore

In-memory vector store for testing and development:

```python
from cemaf.retrieval import InMemoryVectorStore, EmbeddingProvider

store = InMemoryVectorStore(embedding_provider=my_embedding_provider)

# Add documents
await store.add([doc1, doc2])

# Search
results = await store.search("query", k=5)
```

### HybridRetriever

Combines vector and keyword search using Reciprocal Rank Fusion (RRF):

```python
from cemaf.retrieval import HybridRetriever, RetrievalConfig

# Define keyword search function
async def keyword_search(query: str, k: int) -> list[SearchResult]:
    # Implement keyword search
    return results

# Create hybrid retriever
retriever = HybridRetriever(
    vector_store=my_vector_store,
    keyword_search=keyword_search,
    config=RetrievalConfig(
        vector_k=20,
        keyword_k=20,
        final_k=10,
        rrf_k=60,
        vector_weight=0.5,
    ),
)

# Search
results = await retriever.search("query", k=10)
```

## Configuration

Retrieval settings can be configured via environment variables:

```bash
# Vector store settings
CEMAF_RETRIEVAL_VECTOR_STORE_TYPE=in_memory
CEMAF_RETRIEVAL_EMBEDDING_MODEL=text-embedding-3-small
CEMAF_RETRIEVAL_EMBEDDING_DIMENSION=1536

# Hybrid retrieval settings
CEMAF_RETRIEVAL_VECTOR_WEIGHT=0.5
CEMAF_RETRIEVAL_RRF_K=60
```

## Factory Functions

Use factory functions for easy setup:

```python
from cemaf.retrieval import create_vector_store_from_config, create_in_memory_vector_store

# From configuration
store = create_vector_store_from_config()

# In-memory store
store = create_in_memory_vector_store(embedding_provider)
```

## Integration with Memory

Vector stores can be used as memory stores:

```python
from cemaf.retrieval import VectorStore
from cemaf.memory import MemoryStore

# Vector store implements MemoryStore protocol
memory_store: MemoryStore = my_vector_store

# Store memories
await memory_store.store(
    key="conversation_123",
    value="User asked about AI",
    ttl=3600,
)

# Retrieve memories
memory = await memory_store.retrieve("conversation_123")
```

## Integration with RLM

Retrieval can be used for semantic chunking in RLM:

```python
from cemaf.rlm import RecursiveQueryEngine
from cemaf.retrieval import VectorStore

# Use retrieval for semantic chunk boundaries
chunking = SemanticChunkingStrategy(
    retrieval=vector_store,
    estimator=token_estimator,
)

engine = RecursiveQueryEngine(
    llm=llm_client,
    compiler=compiler,
    chunking=chunking,
)
```

## Integration with Citation

Retrieval results can be converted to citations:

```python
from cemaf.citation import CitationTracker
from cemaf.retrieval import VectorStore

tracker = CitationTracker()

# Search and track as citations
results = await vector_store.search("query", k=5)
citations = tracker.track_search_results(results)
```

## Usage Patterns

### Pattern 1: Simple Vector Search

```python
# Add documents
docs = [
    Document(id=f"doc_{i}", content=f"Content {i}")
    for i in range(100)
]
await store.add(docs)

# Search
results = await store.search("query", k=10)
for result in results:
    print(f"{result.score}: {result.content}")
```

### Pattern 2: Filtered Search

```python
# Search with metadata filters
results = await store.search(
    query="AI",
    k=10,
    filters={"category": "technology", "year": 2024},
)
```

### Pattern 3: Hybrid Retrieval

```python
# Combine vector and keyword search
retriever = HybridRetriever(
    vector_store=store,
    keyword_search=keyword_search_fn,
)

results = await retriever.search("query", k=10)
```

### Pattern 4: Batch Operations

```python
# Batch add documents
docs = [doc1, doc2, doc3, ...]
await store.add(docs)

# Batch embedding generation
embeddings = await provider.embed_batch([doc.content for doc in docs])
```

## Embedding Providers

### OpenAIEmbeddingProvider

Production embedding provider backed by the OpenAI text-embedding API. Requires the `cemaf[openai]` extra.

```bash
uv add "cemaf[openai]"
```

```python
from cemaf.retrieval.openai_embeddings import OpenAIEmbeddingProvider

provider = OpenAIEmbeddingProvider(
    api_key="sk-...",
    model="text-embedding-3-small",
    dimension=1536,
)

# Single embed
embedding = await provider.embed(text="What is context engineering?")

# Batch embed — single API call for all non-empty texts
embeddings = await provider.embed_batch(
    texts=["first document", "second document", "third document"]
)
```

**Features**:

- Configurable model and dimension via constructor args
- Empty/whitespace text returns a zero vector (no API call)
- Batch embed sends all non-empty texts in a single API call, maps results back to original indices
- Properties: `provider.dimension` and `provider.model_name`

**Available Models**:

| Model | Default Dimension | Notes |
|-------|-------------------|-------|
| `text-embedding-3-small` | 1536 | Default. Fast, cost-effective |
| `text-embedding-3-large` | 3072 | Higher accuracy, larger vectors |
| `text-embedding-ada-002` | 1536 | Legacy model |

### Sentence Transformers

```python
from sentence_transformers import SentenceTransformer

class SentenceTransformerProvider(EmbeddingProvider):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model = SentenceTransformer(model_name)
        self._dimension = self._model.get_sentence_embedding_dimension()

    async def embed(self, text: str) -> tuple[float, ...]:
        embedding = self._model.encode(text)
        return tuple(embedding.tolist())
```

## Best Practices

1. **Use appropriate embeddings**: Choose embedding model based on domain
2. **Batch operations**: Use batch methods for efficiency
3. **Filter by metadata**: Use metadata filters for precise search
4. **Hybrid retrieval**: Combine vector and keyword search for better results
5. **Store embeddings**: Pre-compute embeddings when possible
6. **Monitor performance**: Track search latency and accuracy
7. **Update documents**: Keep documents up to date
8. **Use filters**: Leverage metadata filters for scoped search

## Performance Considerations

- **Batch operations**: Use `add()` and `embed_batch()` for multiple documents
- **Pre-compute embeddings**: Generate embeddings before storing
- **Index optimization**: Use appropriate indexes for large datasets
- **Caching**: Cache frequent queries
- **Async operations**: Use async/await for concurrent operations

## Testing

Use in-memory stores for testing:

```python
from cemaf.retrieval import InMemoryVectorStore, HashEmbeddingProvider

embedding_provider = HashEmbeddingProvider()
store = InMemoryVectorStore(embedding_provider=embedding_provider)

# Test operations
await store.add([doc1, doc2])
results = await store.search("query", k=5)
assert len(results) > 0
```

## Related Modules

- **Memory**: Vector stores can be used as memory stores
- **Citation**: Search results converted to citations
- **RLM**: Retrieval used for semantic chunking
- **Context**: Retrieval results included in context compilation
- **Ingestion**: Documents ingested into vector stores
