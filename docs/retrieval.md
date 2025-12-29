# Retrieval

Vector stores and embedding providers for semantic search.

## Retrieval Architecture

```mermaid
flowchart TB
    subgraph Input
        QUERY[Query<br/>Text input]
        DOC[Documents<br/>Content to index]
    end

    subgraph Embedding
        EMBED[EmbeddingProvider<br/>Text to vectors]
    end

    subgraph Storage
        VECTOR[VectorStore<br/>Vector storage]
        INDEX[Index<br/>Similarity search]
    end

    subgraph Retrieval
        HYBRID[HybridRetriever<br/>Combined search]
        RESULTS[Results<br/>Ranked documents]
    end

    DOC --> EMBED
    EMBED --> VECTOR
    VECTOR --> INDEX
    QUERY --> EMBED
    EMBED --> INDEX
    INDEX --> RESULTS
    QUERY --> HYBRID
    HYBRID --> RESULTS
```

## Search Flow

```mermaid
sequenceDiagram
    participant Client
    participant Retriever as HybridRetriever
    participant Embedder as EmbeddingProvider
    participant Store as VectorStore

    Note over Client,Store: Indexing
    Client->>Retriever: add(document)
    Retriever->>Embedder: embed(content)
    Embedder-->>Retriever: vector
    Retriever->>Store: add(id, vector)

    Note over Client,Store: Searching
    Client->>Retriever: retrieve(query, top_k)
    Retriever->>Embedder: embed(query)
    Embedder-->>Retriever: query_vector
    Retriever->>Store: search(query_vector, top_k)
    Store-->>Retriever: Results
    Retriever-->>Client: Ranked documents
```

## Vector Store

```python
from cemaf.retrieval.protocols import VectorStore, Document

store: VectorStore = InMemoryVectorStore()

# Add documents
doc = Document(id="1", content="text", metadata={})
await store.add(doc)

# Search
results = await store.search(query_vector, top_k=5)
```

## Hybrid Retriever

Combines vector and keyword search:

```python
from cemaf.retrieval.hybrid import HybridRetriever

retriever = HybridRetriever(
    vector_store=my_vector_store,
    embedding_provider=my_embeddings
)

results = await retriever.retrieve("query", top_k=10)
```

