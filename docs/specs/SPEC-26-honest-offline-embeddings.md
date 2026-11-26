---
title: Honest Offline Embeddings
spec_id: SPEC-26
status: Implemented
last_reviewed: 2026-11-06
owner: drchinca
parent: none
depends_on: []
---

# SPEC-26: Honest Offline Embeddings

> With no embedding provider configured, CEMAF still runs, but it says plainly
> that recall is character matching, not semantic search.

## 1. Context

`create_memory_manager`, `create_tiered_store`, `create_in_memory_vector_store`
and the SQLite vector store silently fell back to `CharacterHashEmbeddingProvider`, a test
double whose vector is a character-position hash. `create_memory_runtime`
defaulted to the `"mock"` backend, which was an alias for `HashEmbeddingProvider`
(SHA-256 of the whole text: only exact duplicates are similar). A user who never
configured an embedder got "semantic memory" that understood nothing, with no sign.

## 2. Interface Contract (MDE)

```python
class CharacterHashEmbeddingProvider:          # was CharacterHashEmbeddingProvider
    model_name = "character-hash"               # similarity = shared characters, not meaning

def offline_embedding_provider(*, dimension: int = 384) -> CharacterHashEmbeddingProvider: ...
    # The one fallback every factory uses; logs a warning once per process.
def warn_non_semantic_embeddings(*, provider_name: str, matches: str) -> None: ...
    # Once per process and provider. The "hash" backend (SHA-256 of the whole text,
    # identical text only) calls it too: it is the configured default
    # (DEFAULT_FREE_EMBEDDING_PROVIDER) and would otherwise stay silent.

embedding_provider_registry: "character_hash" -> offline_embedding_provider   # "mock" key removed
create_memory_runtime(*, embedding_provider_name: str = "character_hash", ...)
EmbeddingSettings.embedding_provider: Literal["hash", "character_hash", "openai", "huggingface", "sentence-transformers"]
```

## 3. Invariants (DbC)

1. `WHEN a factory needs an embedding provider and none was configured, THE System SHALL use CharacterHashEmbeddingProvider through offline_embedding_provider().`
2. `THE first such fallback in a process SHALL log a warning naming the provider and saying recall is not semantic`; later fallbacks SHALL NOT repeat it.
3. `WHEN a caller passes an embedding provider explicitly, THE System SHALL NOT warn.`
4. `No registry key SHALL be named "mock"` for a provider that ships as a default.
5. `WHEN the "hash" backend is created, THE System SHALL warn once that it matches identical text only.`

Budget: 5 invariants.

## 4. Acceptance Criteria (BDD)

```gherkin
Feature: Honest offline embeddings

  Scenario: Falling back warns once
    Given a fresh process
    When create_memory_manager() is called twice without an embedding provider
    Then exactly one warning says recall is character matching, not semantic

  Scenario: An explicit provider stays quiet
    When create_memory_manager(embedding_provider=CharacterHashEmbeddingProvider()) is called
    Then no warning is logged

  Scenario: The runtime default is named for what it does
    When create_memory_runtime() is called with no embedding provider name
    Then its embedding provider is a CharacterHashEmbeddingProvider
```

## 5. Out of Scope

- Shipping a real local embedder as the default (e.g. Ollama `nomic-embed-text`).
- Changing what `HashEmbeddingProvider` (`"hash"`) computes, or moving the configured default off it.

## 10. Test Coverage Update

- **Unit** (`tests/unit/retrieval/test_vector_store.py`): warn-once, explicit-is-quiet,
  and the `create_memory_runtime()` default.
