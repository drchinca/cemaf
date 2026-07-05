# Vector Store Configuration

## Overview

CEMAF's retrieval layer is protocol-first. The built-in configuration path wires
documented environment variables to registered `VectorStore` and
`EmbeddingProvider` backends. External services are supported by implementing
the protocol and registering an adapter.

## Built-In Backends

Built-in vector stores:

- `memory` - in-process development and tests.
- `sqlite` - local durable vector storage.
- `pgvector` - PostgreSQL with pgvector. Pass an `EmbeddingProvider` when
  callers use `search_by_text()`; callers with precomputed vectors can call
  `search()` directly.

Built-in embedding providers:

- `hash` and `mock` - deterministic offline providers.
- `openai` - OpenAI embeddings.
- `huggingface` and `sentence-transformers` - Hugging Face embedding providers.

## Environment Variables

```bash
CEMAF_VECTOR_STORE_BACKEND=memory
CEMAF_RETRIEVAL_SQLITE_PATH=./data/retrieval.db
CEMAF_POSTGRES_DSN=postgresql://user:password@localhost:5432/cemaf

CEMAF_EMBEDDING_PROVIDER=hash
CEMAF_EMBEDDING_MODEL=hash-embedding
CEMAF_EMBEDDING_DIMENSION=384
```

`CEMAF_VECTOR_STORE_BACKEND` accepts `memory`, `sqlite`, or `pgvector` for the
built-in configuration model. Custom backends should be selected through direct
factory calls after registration.

## Usage

```python
from cemaf.retrieval import create_embedding_provider_from_config
from cemaf.retrieval import create_vector_store_from_config

embedding_provider = create_embedding_provider_from_config()
store = create_vector_store_from_config(embedding_provider=embedding_provider)
```

Explicit construction bypasses environment-backed settings and can use any
registered backend:

```python
from cemaf.retrieval.factories import create_vector_store

store = create_vector_store(
    backend="sqlite",
    embedding_provider=embedding_provider,
    db_path="./data/retrieval.db",
)
```

## Extending

Register custom vector stores instead of editing CEMAF factory code:

```python
from cemaf.retrieval.factories import vector_store_registry


class ExternalVectorStore:
    async def add(self, document):
        ...

    async def add_batch(self, documents):
        ...

    async def get(self, document_id):
        ...

    async def search(self, query_embedding, k=10, filter=None):
        ...

    async def search_by_text(self, query_text, k=10, filter=None):
        ...

    async def delete(self, document_id):
        ...

    async def count(self):
        ...

    async def clear(self):
        ...


def create_external_vector_store(**kwargs):
    return ExternalVectorStore(...)


vector_store_registry.register(
    backend="external",
    factory=create_external_vector_store,
)
```

Then construct it directly:

```python
store = create_vector_store(backend="external", embedding_provider=embedding_provider)
```

## See Also

- [Retrieval](retrieval.md)
- [Factory Functions](../src/cemaf/retrieval/factories.py)
- [Environment Configuration](env_configuration.md)
