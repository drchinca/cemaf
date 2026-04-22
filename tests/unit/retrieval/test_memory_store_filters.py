"""Regression tests for InMemoryVectorStore filter semantics.

The semantic store emits filters like `{"scope": {"$in": [...]}}`. Before the
fix, the vector store did scalar equality and silently returned zero results.
"""

from __future__ import annotations

import pytest

from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider
from cemaf.retrieval.protocols import Document


@pytest.fixture
def store() -> InMemoryVectorStore:
    return InMemoryVectorStore(embedding_provider=MockEmbeddingProvider(dimension=3))


async def _seed(store: InMemoryVectorStore) -> None:
    await store.add(
        Document(id="a", content="foo", metadata={"scope": "project", "owner": "u1"}).with_embedding(
            (1.0, 0.0, 0.0)
        )
    )
    await store.add(
        Document(id="b", content="bar", metadata={"scope": "session", "owner": "u1"}).with_embedding(
            (0.0, 1.0, 0.0)
        )
    )
    await store.add(
        Document(id="c", content="baz", metadata={"scope": "global", "owner": "u2"}).with_embedding(
            (0.0, 0.0, 1.0)
        )
    )


@pytest.mark.asyncio
async def test_scalar_equality_filter_still_works(store: InMemoryVectorStore) -> None:
    await _seed(store)
    results = await store.search((1.0, 0.0, 0.0), k=10, filter={"scope": "project"})
    assert {r.document.id for r in results} == {"a"}


@pytest.mark.asyncio
async def test_in_operator_matches_multiple_scopes(store: InMemoryVectorStore) -> None:
    """Regression: semantic.py:221 emits {'scope': {'$in': [...]}}."""
    await _seed(store)
    results = await store.search(
        (1.0, 0.0, 0.0),
        k=10,
        filter={"scope": {"$in": ["project", "session"]}},
    )
    assert {r.document.id for r in results} == {"a", "b"}


@pytest.mark.asyncio
async def test_nin_operator_excludes_listed_values(store: InMemoryVectorStore) -> None:
    await _seed(store)
    results = await store.search(
        (1.0, 0.0, 0.0),
        k=10,
        filter={"scope": {"$nin": ["global"]}},
    )
    assert {r.document.id for r in results} == {"a", "b"}


@pytest.mark.asyncio
async def test_ne_operator_excludes_single_value(store: InMemoryVectorStore) -> None:
    await _seed(store)
    results = await store.search(
        (1.0, 0.0, 0.0),
        k=10,
        filter={"owner": {"$ne": "u2"}},
    )
    assert {r.document.id for r in results} == {"a", "b"}


@pytest.mark.asyncio
async def test_eq_operator_alias_for_scalar_equality(store: InMemoryVectorStore) -> None:
    await _seed(store)
    results = await store.search(
        (1.0, 0.0, 0.0),
        k=10,
        filter={"owner": {"$eq": "u1"}},
    )
    assert {r.document.id for r in results} == {"a", "b"}


@pytest.mark.asyncio
async def test_combined_filters_are_anded(store: InMemoryVectorStore) -> None:
    await _seed(store)
    results = await store.search(
        (1.0, 0.0, 0.0),
        k=10,
        filter={
            "scope": {"$in": ["project", "session"]},
            "owner": "u1",
        },
    )
    assert {r.document.id for r in results} == {"a", "b"}


@pytest.mark.asyncio
async def test_unknown_operator_raises_loudly(store: InMemoryVectorStore) -> None:
    """Silent rejection was the original bug — unknown operators must surface."""
    await _seed(store)
    with pytest.raises(ValueError, match="Unsupported filter operator"):
        await store.search((1.0, 0.0, 0.0), filter={"scope": {"$unknown_op": "x"}})


@pytest.mark.asyncio
async def test_in_operand_must_be_iterable(store: InMemoryVectorStore) -> None:
    await _seed(store)
    with pytest.raises(ValueError, match="\\$in operand must be iterable"):
        await store.search((1.0, 0.0, 0.0), filter={"scope": {"$in": "project"}})
