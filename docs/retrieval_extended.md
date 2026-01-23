# Retrieval Module - Extended Documentation

## Overview

The retrieval module provides vector search, keyword search, and hybrid retrieval for semantic information retrieval, enabling agents to find relevant sources from large document collections efficiently.

**What it does**: Interfaces with vector stores for embedding-based semantic search, supports keyword/BM25 search for exact matching, and combines both via HybridRetriever. Provides VectorStore and EmbeddingProvider protocols for pluggability. Built-in InMemoryVectorStore for testing and development.

**Key use cases**:
- Search document collections for relevant context
- Semantic search (find similar content by meaning, not exact words)
- Combine semantic and keyword search for robustness
- Find relevant sources during context retrieval
- Retrieve examples for few-shot learning
- Search across embeddings from multiple domains

**When to use vs. alternatives**: Use retrieval when you need to find relevant documents from large collections. Use vector search for semantic relevance. Use hybrid for robustness. Don't use for structured queries (use SQL), or when you have small datasets (pre-compute all).

## Core Concepts

### Vector Search

Documents are converted to embeddings (dense vectors capturing semantic meaning). Query is also embedded. Similarity (cosine, L2, dot product) finds nearest vectors.

**Advantages**: Semantic relevance, handles synonyms, works across languages
**Disadvantages**: Requires embeddings, can't search structured fields directly

### Keyword Search

Traditional full-text search using BM25 or inverted indexes. Queries find documents with matching terms.

**Advantages**: Exact matching, works with special characters/numbers, fast on small datasets
**Disadvantages**: Doesn't understand meaning, fails on synonyms

### Hybrid Retrieval

Combines vector and keyword search. Queries both, reranks results. Gets benefits of both.

```
Query → Split into vector + keyword → Search both → Merge results → Rerank → Top K
```

### Embeddings

VectorStore uses EmbeddingProvider to convert text to vectors. Built-in providers wrap OpenAI, Anthropic, local models. Choose provider based on:
- **Latency**: Local fast, cloud slower
- **Quality**: Larger models better, trade-off cost
- **Privacy**: Local keeps data private, cloud sends to provider

## Usage Examples

### Basic Vector Search

```python
from cemaf.retrieval import InMemoryVectorStore, VectorStore
from cemaf.retrieval.protocols import EmbeddingProvider

# Create store with embedding provider
class OpenAIEmbeddings(EmbeddingProvider):
    async def embed(self, text: str) -> list[float]:
        response = await openai.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        return response.data[0].embedding

store = InMemoryVectorStore(
    embedding_provider=OpenAIEmbeddings()
)

# Add documents
documents = [
    "Climate change affects global weather patterns",
    "Machine learning improves with more data",
    "Python is great for data science"
]

for doc in documents:
    await store.add(id=f"doc_{i}", text=doc, metadata={"source": "example"})

# Search
query = "How does ML improve?"
results = await store.search(query, limit=2)

for result in results:
    print(f"{result.id}: {result.text} (score: {result.score:.3f})")
```

### Hybrid Search Combining Vector and Keyword

```python
from cemaf.retrieval import HybridRetriever

# Hybrid retriever combines both search types
retriever = HybridRetriever(
    vector_store=vector_store,
    keyword_store=keyword_store,
    vector_weight=0.7,  # 70% from vector search
    keyword_weight=0.3  # 30% from keyword search
)

# Query uses both methods
results = await retriever.retrieve(
    query="machine learning data",
    limit=5
)

# Results combine both semantic and exact matches
for result in results:
    print(f"{result.text} (combined_score: {result.score:.3f})")
```

### With Metadata Filtering

```python
# Add documents with rich metadata
documents = [
    {
        "id": "doc1",
        "text": "Climate change article",
        "metadata": {
            "source": "nature.com",
            "date": "2024-01-15",
            "category": "climate",
            "author": "Dr. Smith"
        }
    },
    ...
]

for doc in documents:
    await store.add(
        id=doc["id"],
        text=doc["text"],
        metadata=doc["metadata"]
    )

# Search with filtering
results = await store.search(
    query="climate impacts",
    limit=5,
    filters={
        "category": "climate",
        "date__gte": "2024-01-01"  # After Jan 1
    }
)
```

### Context Retrieval for Generation

```python
from cemaf.context.context import Context

class ContextAwareRetriever:
    """Retrieve relevant context for generation."""

    async def retrieve_for_context(
        self,
        query: str,
        context: Context,
        limit: int = 5
    ) -> list[str]:
        """Retrieve sources relevant to query and context."""
        # Combine query with context info
        enhanced_query = f"{query}. Context: {context.summary}"

        # Search
        results = await self.retriever.retrieve(enhanced_query, limit=limit)

        # Filter by context constraints
        valid_results = [
            r for r in results
            if not self._conflicts_with_context(r, context)
        ]

        return valid_results

    def _conflicts_with_context(self, result, context):
        """Check if result contradicts context."""
        # Implementation: compare with decisions, facts in context
        return False
```

### Batch Retrieval

```python
from concurrent.futures import ThreadPoolExecutor

# Retrieve for multiple queries efficiently
queries = [
    "climate change impacts",
    "renewable energy",
    "carbon emissions",
    "sustainable development"
]

# Parallel retrieval
import asyncio
results = await asyncio.gather(*[
    retriever.retrieve(query, limit=3)
    for query in queries
])

# results is list of lists
for query, query_results in zip(queries, results):
    print(f"Query: {query}")
    for result in query_results:
        print(f"  - {result.text}")
```

### Iterative Refinement

```python
# Start with broad query, refine based on results
initial_query = "AI and society"
refined_queries = [
    "AI impact on employment",
    "AI bias and fairness",
    "AI regulation frameworks"
]

# Get initial results
initial_results = await retriever.retrieve(initial_query, limit=10)

# Refine search based on initial results
all_results = initial_results

for refined_query in refined_queries:
    additional_results = await retriever.retrieve(refined_query, limit=5)
    all_results.extend(additional_results)

# Deduplicate and rerank
unique_results = _deduplicate(all_results)
ranked = _rerank(unique_results, initial_query)

return ranked[:10]
```

### Common Mistake: Ignoring Embedding Staleness

```python
# ❌ WRONG - Embeddings don't update
store.add(id="doc1", text="Old content", embed=old_embed)
# Document changes, but embedding is stale
store.update(id="doc1", text="New content")
# Old embedding still used! Inconsistent.

# ✅ CORRECT - Regenerate embedding when content changes
store.update(
    id="doc1",
    text="New content",
    embed=await embedding_provider.embed("New content")
)

# Or better, let store handle it
store.add(
    id="doc1",
    text="New content"
    # Store generates embedding automatically
)
```

## Integration

### With Context Module

```python
from cemaf.context.context import Context
from cemaf.retrieval import HybridRetriever

# Retrieval populates context sources
class ContextBuilder:
    def __init__(self, retriever: HybridRetriever):
        self.retriever = retriever

    async def build_context(self, query: str) -> Context:
        # Retrieve sources
        results = await self.retriever.retrieve(query, limit=10)

        # Convert to context sources
        sources = [
            ContextSource(
                id=r.id,
                content=r.text,
                url=r.metadata.get("url"),
                confidence=r.score,
                source_type="retrieval"
            )
            for r in results
        ]

        # Create context with sources
        context = Context(sources=sources)
        return context
```

### With Generation Module

```python
# Generate with retrieved context
async def generate_with_retrieval(prompt: str):
    # Retrieve relevant sources
    context = await context_builder.build_context(prompt)

    # Add sources to generation prompt
    full_prompt = f"""
    Context:
    {context.format_sources()}

    Task: {prompt}
    """

    # Generate
    response = await llm.generate(full_prompt)
    return response
```

### With Persistence Module

```python
from cemaf.persistence.entities import ContextArtifact

# Store retrieved artifacts
async def store_retrieval_results(query: str, results):
    artifact = ContextArtifact(
        project_id=project_id,
        type=ContextArtifactType.SOURCES,
        content=json.dumps([
            {
                "id": r.id,
                "text": r.text,
                "score": r.score,
                "source": r.metadata
            }
            for r in results
        ]),
        source=f"retrieval_query:{query}"
    )

    await artifact_store.create(artifact)
```

## API Reference

### SearchResult

```python
@dataclass
class SearchResult:
    id: str
    text: str
    score: float              # 0-1, higher is more relevant
    metadata: dict = Field(default_factory=dict)
    embedded: bool = True     # Whether text is embedded
```

### VectorStore Protocol

```python
@runtime_checkable
class VectorStore(Protocol):
    async def add(
        self,
        id: str,
        text: str,
        metadata: dict | None = None,
        embed: list[float] | None = None
    ) -> None:
        """Add document to store."""

    async def search(
        self,
        query: str,
        limit: int = 10,
        filters: dict | None = None
    ) -> list[SearchResult]:
        """Search store."""

    async def get(self, id: str) -> SearchResult | None:
        """Get specific document."""

    async def delete(self, id: str) -> bool:
        """Delete document."""

    async def list_all(self, limit: int = 100) -> list[SearchResult]:
        """List all documents."""
```

### EmbeddingProvider Protocol

```python
@runtime_checkable
class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]:
        """Convert text to embedding."""

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Convert multiple texts to embeddings."""

    @property
    def embedding_dim(self) -> int:
        """Dimension of embeddings."""
```

### HybridRetriever

```python
class HybridRetriever:
    def __init__(
        self,
        vector_store: VectorStore,
        keyword_store: KeywordStore,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
        reranker: Reranker | None = None
    ): ...

    async def retrieve(
        self,
        query: str,
        limit: int = 10,
        filters: dict | None = None
    ) -> list[SearchResult]: ...
```

## Best Practices

### Embedding Selection

```python
# Trade-offs: quality vs speed vs cost
OPTIONS = {
    "text-embedding-3-small": {
        "quality": "good",
        "speed": "fast",
        "cost": "cheap",
        "use_case": "general web search"
    },
    "text-embedding-3-large": {
        "quality": "excellent",
        "speed": "slower",
        "cost": "more",
        "use_case": "semantic retrieval, RAG"
    },
    "local_llm": {
        "quality": "medium",
        "speed": "variable",
        "cost": "low",
        "use_case": "privacy-critical"
    }
}
```

### Performance Tips

- **Batch embeddings**: Embed many texts together, not one at a time
- **Cache embeddings**: Don't recompute same embeddings
- **Index optimization**: Use HNSW or other efficient indexes for large stores
- **Pagination**: Retrieve in pages, not all at once

### Common Pitfalls

**Relevance collapse**: If all queries return same results, maybe scores are broken. Check scoring function.

**Embedding drift**: When you update embedding model, old embeddings become incompatible. Re-embed everything.

**No null safety**: Handle documents with missing metadata gracefully.

**Irrelevant results**: Hybrid weight tuning is important. Start at 0.5/0.5, adjust based on results.

### When NOT to Use

- **Exact phrase search**: Use keyword search
- **Structured queries**: Use SQL
- **Real-time updates**: Embedding index updates are slow
- **Tiny datasets**: Pre-compute with all pairs

### Reranking Strategy

```python
# Retrieve broad set, rerank with stricter metric
results = await retriever.retrieve(query, limit=50)  # Broad

# Rerank with cross-encoder (more expensive, higher quality)
reranked = await reranker.rerank(query, results)

# Return top K
return reranked[:10]
```
