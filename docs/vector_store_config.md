# Vector Store Configuration

## Overview

CEMAF now has a **configuration layer** that connects the `.env.example` vector store settings to the `VectorStore` protocol layer.

## What Was Added

### 1. `RetrievalSettings` in Config Protocol

Added `RetrievalSettings` to `cemaf/src/cemaf/config/protocols.py`:

```python
class RetrievalSettings(BaseModel):
    """Settings for retrieval/vector store configuration."""

    vector_store_backend: Literal[
        "memory", "pinecone", "qdrant", "weaviate", "chroma", "pgvector", "faiss"
    ] = "memory"

    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536
```

This is now part of the main `Settings` class:

```python
class Settings(BaseModel):
    # ... other settings ...
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
```

### 2. Factory Function

Added `create_vector_store_from_config()` to `cemaf/src/cemaf/retrieval/factories.py`:

```python
def create_vector_store_from_config(
    backend: str | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> VectorStore:
    """
    Create a vector store from configuration.

    Reads from environment variables:
    - CEMAF_VECTOR_STORE_BACKEND: Backend type (default: "memory")
    - CEMAF_EMBEDDING_DIMENSION: Embedding dimension
    """
```

## How It Works

### Environment Variable → Protocol Layer

```
.env.example (lines 88-89)
    ↓
CEMAF_VECTOR_STORE_BACKEND=memory
    ↓
create_vector_store_from_config()
    ↓
VectorStore Protocol
    ↓
InMemoryVectorStore (or Pinecone, Qdrant, etc.)
```

### Usage Examples

**From environment variables:**
```python
from cemaf.retrieval import create_vector_store_from_config

# Reads CEMAF_VECTOR_STORE_BACKEND from .env
store = create_vector_store_from_config()
```

**From Settings object:**
```python
from cemaf.config.loader import SettingsProviderImpl, EnvConfigSource
from cemaf.retrieval import create_vector_store_from_config

provider = SettingsProviderImpl()
provider.add_source(EnvConfigSource(prefix="CEMAF"))
settings = await provider.get()

# Use settings.retrieval.vector_store_backend
store = create_vector_store_from_config(
    backend=settings.retrieval.vector_store_backend
)
```

**Explicit backend:**
```python
# Override env var
store = create_vector_store_from_config(backend="memory")
```

## Configuration Mapping

| Environment Variable | Settings Path | Default |
|---------------------|---------------|---------|
| `CEMAF_VECTOR_STORE_BACKEND` | `settings.retrieval.vector_store_backend` | `"memory"` |
| `CEMAF_EMBEDDING_PROVIDER` | `settings.retrieval.embedding_provider` | `"openai"` |
| `CEMAF_EMBEDDING_MODEL` | `settings.retrieval.embedding_model` | `"text-embedding-3-small"` |
| `CEMAF_EMBEDDING_DIMENSION` | `settings.retrieval.embedding_dimension` | `1536` |

## Protocol Layer Reference

The `VectorStore` protocol is defined in `cemaf/src/cemaf/retrieval/protocols.py`:

```python
@runtime_checkable
class VectorStore(Protocol):
    """Protocol for vector stores."""

    async def add(self, document: Document) -> None: ...
    async def search(self, query_embedding: tuple[float, ...], k: int = 10) -> list[SearchResult]: ...
    # ... other methods ...
```

All implementations (InMemoryVectorStore, future Pinecone, Qdrant, etc.) conform to this protocol.

## Current Status

✅ **Implemented:**
- `RetrievalSettings` in config protocol
- `create_vector_store_from_config()` factory
- Environment variable reading
- In-memory vector store support

🚧 **Future (Extensible):**
- Pinecone implementation
- Qdrant implementation
- Weaviate implementation
- Chroma implementation
- PGVector implementation
- FAISS implementation

## Extending

To add a new vector store backend:

1. **Implement the protocol:**
```python
class PineconeVectorStore:
    def __init__(self, api_key: str, index_name: str):
        # Initialize Pinecone client
        ...

    async def add(self, document: Document) -> None:
        # Implement protocol method
        ...
```

2. **Add to factory:**
```python
def create_vector_store_from_config(...):
    # ...
    elif backend == "pinecone":
        api_key = os.getenv("PINECONE_API_KEY")
        index_name = os.getenv("PINECONE_INDEX_NAME")
        return PineconeVectorStore(api_key=api_key, index_name=index_name)
```

3. **Update `.env.example`:**
```bash
CEMAF_VECTOR_STORE_BACKEND=pinecone
PINECONE_API_KEY=your_key
PINECONE_INDEX_NAME=cemaf-index
```

## See Also

- [Vector Store Protocol](../src/cemaf/retrieval/protocols.py)
- [Factory Functions](../src/cemaf/retrieval/factories.py)
- [Configuration Guide](./config.md)
- [Environment Configuration](./env_configuration.md)
