"""Tests for the SQLite-backed vector store."""

from pathlib import Path

import pytest

from cemaf.retrieval.embedding_providers import HashEmbeddingProvider
from cemaf.retrieval.protocols import Document
from cemaf.retrieval.sqlite_vector_store import SqliteVectorStore


class _ZeroDimensionProvider:
    @property
    def dimension(self) -> int:
        return 0

    @property
    def model_name(self) -> str:
        return "zero-dimension"

    async def embed(self, text: str) -> tuple[float, ...]:
        return ()

    async def embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [() for _ in texts]


@pytest.fixture
def provider() -> HashEmbeddingProvider:
    return HashEmbeddingProvider(dimension=32)


def test_sqlite_vector_store_rejects_non_positive_provider_dimension(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="embedding provider dimension must be positive, got 0"):
        SqliteVectorStore(
            db_path=str(tmp_path / "zero-dimension.db"),
            embedding_provider=_ZeroDimensionProvider(),
        )


@pytest.mark.asyncio
async def test_sqlite_vector_store_persists_across_instances(
    tmp_path: Path, provider: HashEmbeddingProvider
) -> None:
    db_path = tmp_path / "vectors.db"
    store = SqliteVectorStore(db_path=str(db_path), embedding_provider=provider)
    await store.add(
        Document(
            id="doc-1",
            content="brand consistency and audience trust",
            metadata={"scope": "project", "kind": "research"},
        )
    )
    await store.close()

    reopened = SqliteVectorStore(db_path=str(db_path), embedding_provider=provider)
    retrieved = await reopened.get("doc-1")
    results = await reopened.search_by_text("audience trust", k=5)

    assert retrieved is not None
    assert retrieved.content == "brand consistency and audience trust"
    assert any(result.document.id == "doc-1" for result in results)
    await reopened.close()


@pytest.mark.asyncio
async def test_sqlite_vector_store_search_supports_metadata_filters(
    tmp_path: Path, provider: HashEmbeddingProvider
) -> None:
    store = SqliteVectorStore(db_path=str(tmp_path / "filters.db"), embedding_provider=provider)
    await store.add_batch(
        [
            Document(id="a", content="content strategy", metadata={"scope": "project"}),
            Document(id="b", content="system level knowledge", metadata={"scope": "global"}),
        ]
    )

    results = await store.search_by_text(
        "strategy",
        k=5,
        filter={"scope": "project"},
    )

    assert [result.document.id for result in results] == ["a"]
    await store.close()


@pytest.mark.asyncio
async def test_sqlite_vector_store_delete_removes_document(
    tmp_path: Path, provider: HashEmbeddingProvider
) -> None:
    store = SqliteVectorStore(db_path=str(tmp_path / "delete.db"), embedding_provider=provider)
    await store.add(Document(id="doc-1", content="delete me"))

    deleted = await store.delete("doc-1")
    missing = await store.get("doc-1")

    assert deleted is True
    assert missing is None
    assert await store.count() == 0
    await store.close()


@pytest.mark.asyncio
async def test_sqlite_vector_store_rejects_wrong_dimension_embedding(
    tmp_path: Path, provider: HashEmbeddingProvider
) -> None:
    store = SqliteVectorStore(db_path=str(tmp_path / "bad-embedding.db"), embedding_provider=provider)

    with pytest.raises(ValueError, match="embedding for document 'bad' has dimension 2; expected 32"):
        await store.add(Document(id="bad", content="bad", embedding=(0.1, 0.2)))

    assert await store.count() == 0
    await store.close()


@pytest.mark.asyncio
async def test_sqlite_vector_store_rejects_wrong_dimension_query(
    tmp_path: Path, provider: HashEmbeddingProvider
) -> None:
    store = SqliteVectorStore(db_path=str(tmp_path / "bad-query.db"), embedding_provider=provider)
    await store.add(Document(id="doc-1", content="query target"))

    with pytest.raises(ValueError, match="query embedding has dimension 2; expected 32"):
        await store.search((0.1, 0.2))

    await store.close()
