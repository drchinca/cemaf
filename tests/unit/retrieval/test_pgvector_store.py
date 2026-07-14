"""Unit tests for PgVectorStore behavior that does not require PostgreSQL."""

import pytest

from cemaf.retrieval.pgvector_store import PgVectorStore
from cemaf.retrieval.protocols import SearchResult


class _EmbeddingProvider:
    def __init__(self) -> None:
        self.last_text: str | None = None

    @property
    def dimension(self) -> int:
        return 3

    @property
    def model_name(self) -> str:
        return "test-embedding"

    async def embed(self, text: str) -> tuple[float, ...]:
        self.last_text = text
        return (0.1, 0.2, 0.3)

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [await self.embed(text) for text in texts]


class _CapturingPgVectorStore(PgVectorStore):
    def __init__(self, *, embedding_provider: _EmbeddingProvider) -> None:
        super().__init__(
            dsn="postgresql://localhost/cemaf",
            dimension=embedding_provider.dimension,
            embedding_provider=embedding_provider,
        )
        self.search_calls: list[dict[str, object]] = []

    async def search(
        self,
        query_embedding: tuple[float, ...],
        k: int = 10,
        filter: dict[str, object] | None = None,
    ) -> list[SearchResult]:
        self.search_calls.append(
            {
                "query_embedding": query_embedding,
                "k": k,
                "filter": filter,
            }
        )
        return []


@pytest.mark.asyncio
async def test_search_by_text_embeds_query_and_delegates_to_vector_search() -> None:
    provider = _EmbeddingProvider()
    store = _CapturingPgVectorStore(embedding_provider=provider)

    results = await store.search_by_text("release risk", k=3, filter={"scope": "project"})

    assert results == []
    assert provider.last_text == "release risk"
    assert store.search_calls == [
        {
            "query_embedding": (0.1, 0.2, 0.3),
            "k": 3,
            "filter": {"scope": "project"},
        }
    ]


@pytest.mark.asyncio
async def test_search_by_text_requires_embedding_provider() -> None:
    store = PgVectorStore(dsn="postgresql://localhost/cemaf")

    with pytest.raises(ValueError, match="requires an embedding_provider"):
        await store.search_by_text("release risk")


def test_pgvector_store_rejects_provider_dimension_mismatch() -> None:
    provider = _EmbeddingProvider()

    with pytest.raises(ValueError, match="dimension 4 does not match embedding provider dimension 3"):
        PgVectorStore(
            dsn="postgresql://localhost/cemaf",
            dimension=4,
            embedding_provider=provider,
        )


def test_pgvector_store_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError, match="dimension must be positive, got 0"):
        PgVectorStore(dsn="postgresql://localhost/cemaf", dimension=0)
    with pytest.raises(ValueError, match="dimension must be positive, got -1"):
        PgVectorStore(dsn="postgresql://localhost/cemaf", dimension=-1)


@pytest.mark.asyncio
async def test_pgvector_store_add_requires_embedding_without_provider() -> None:
    from cemaf.retrieval.protocols import Document

    store = PgVectorStore(dsn="postgresql://localhost/cemaf", dimension=3)

    with pytest.raises(ValueError, match="requires document embeddings or an embedding_provider"):
        await store.add(Document(id="missing", content="missing embedding"))


@pytest.mark.asyncio
async def test_pgvector_store_add_rejects_wrong_dimension_embedding() -> None:
    from cemaf.retrieval.protocols import Document

    store = PgVectorStore(dsn="postgresql://localhost/cemaf", dimension=3)

    with pytest.raises(ValueError, match="embedding for document 'bad' has dimension 2; expected 3"):
        await store.add(Document(id="bad", content="bad embedding", embedding=(0.1, 0.2)))


@pytest.mark.asyncio
async def test_pgvector_store_search_rejects_wrong_dimension_query() -> None:
    store = PgVectorStore(dsn="postgresql://localhost/cemaf", dimension=3)

    with pytest.raises(ValueError, match="query embedding has dimension 2; expected 3"):
        await store.search((0.1, 0.2))
