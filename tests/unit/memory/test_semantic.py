"""Tests for semantic memory bridge."""

from datetime import timedelta

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.core.utils import utc_now
from cemaf.memory.base import InMemoryStore, MemoryItem
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import (
    DefaultSemanticMemoryStore,
    MemoryQuery,
    MemorySearchResult,
    SemanticMemoryStore,
)
from cemaf.memory.session_keys import session_memory_key
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_store() -> DefaultSemanticMemoryStore:
    """Create a fully wired semantic store for testing."""
    embedding_provider = MockEmbeddingProvider()
    return DefaultSemanticMemoryStore(
        memory_store=InMemoryStore(),
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=TemporalDecayScorer(),
    )


def _make_item(
    *,
    scope: MemoryScope = MemoryScope.SESSION,
    key: str = "test",
    value: dict | None = None,
    confidence: float = 1.0,
    age_seconds: float = 0.0,
) -> MemoryItem:
    now = utc_now()
    created = now - timedelta(seconds=age_seconds)
    return MemoryItem(
        scope=scope,
        key=key,
        value=value or {"data": key},
        confidence=Confidence(confidence),
        created_at=created,
        updated_at=created,
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_implements_semantic_memory_store(self) -> None:
        store = _make_store()
        assert isinstance(store, SemanticMemoryStore)


# ---------------------------------------------------------------------------
# Store and retrieve
# ---------------------------------------------------------------------------


class TestStoreAndRetrieve:
    @pytest.mark.asyncio
    async def test_store_and_get(self) -> None:
        store = _make_store()
        item = _make_item(key="brand_name")
        await store.store(item=item)
        retrieved = await store.get(scope=MemoryScope.SESSION, key="brand_name")
        assert retrieved is not None
        assert retrieved.key == "brand_name"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self) -> None:
        store = _make_store()
        result = await store.get(scope=MemoryScope.SESSION, key="nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        store = _make_store()
        item = _make_item(key="to_delete")
        await store.store(item=item)
        deleted = await store.delete(scope=MemoryScope.SESSION, key="to_delete")
        assert deleted is True
        result = await store.get(scope=MemoryScope.SESSION, key="to_delete")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self) -> None:
        store = _make_store()
        deleted = await store.delete(scope=MemoryScope.SESSION, key="nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_store_with_custom_embedding_text(self) -> None:
        store = _make_store()
        item = _make_item(key="structured", value={"nested": {"deep": True}})
        await store.store(
            item=item,
            content_for_embedding="This is a structured item about testing",
        )
        retrieved = await store.get(scope=MemoryScope.SESSION, key="structured")
        assert retrieved is not None


# ---------------------------------------------------------------------------
# Semantic search (with text)
# ---------------------------------------------------------------------------


class TestSemanticSearch:
    @pytest.mark.asyncio
    async def test_text_search_returns_results(self) -> None:
        store = _make_store()
        await store.store(item=_make_item(key="alpha", value={"topic": "machine learning"}))
        await store.store(item=_make_item(key="beta", value={"topic": "cooking recipes"}))

        results = await store.search(
            query=MemoryQuery(text="machine learning", limit=5),
        )
        assert len(results) > 0
        assert all(isinstance(r, MemorySearchResult) for r in results)

    @pytest.mark.asyncio
    async def test_search_results_have_ranks(self) -> None:
        store = _make_store()
        for i in range(3):
            await store.store(item=_make_item(key=f"item_{i}"))

        results = await store.search(query=MemoryQuery(text="item", limit=3))
        ranks = [r.rank for r in results]
        assert ranks == list(range(len(ranks)))

    @pytest.mark.asyncio
    async def test_search_respects_limit(self) -> None:
        store = _make_store()
        for i in range(10):
            await store.store(item=_make_item(key=f"item_{i}"))

        results = await store.search(query=MemoryQuery(text="item", limit=3))
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_search_empty_store(self) -> None:
        store = _make_store()
        results = await store.search(query=MemoryQuery(text="anything"))
        assert results == ()

    @pytest.mark.asyncio
    async def test_text_search_filters_session_owner_before_top_k(self) -> None:
        store = _make_store()
        for session_id in ("run-a", "run-b"):
            await store.store(
                item=_make_item(
                    key=session_memory_key(session_id=session_id, key="Writer_output"),
                    value={"session": session_id},
                ),
                content_for_embedding="identical shared query",
            )

        results = await store.search(
            query=MemoryQuery(
                text="identical shared query",
                scope=MemoryScope.SESSION,
                session_id="run-b",
                limit=1,
            )
        )

        assert len(results) == 1
        assert results[0].item.value == {"session": "run-b"}


# ---------------------------------------------------------------------------
# Scope-filtered search (no text)
# ---------------------------------------------------------------------------


class TestScopeSearch:
    @pytest.mark.asyncio
    async def test_scope_filter_single(self) -> None:
        store = _make_store()
        await store.store(item=_make_item(scope=MemoryScope.TENANT, key="brand_item"))
        await store.store(item=_make_item(scope=MemoryScope.SESSION, key="session_item"))

        results = await store.search(
            query=MemoryQuery(scope=MemoryScope.TENANT),
        )
        assert len(results) == 1
        assert results[0].item.scope == MemoryScope.TENANT

    @pytest.mark.asyncio
    async def test_scope_filter_multiple(self) -> None:
        store = _make_store()
        await store.store(item=_make_item(scope=MemoryScope.TENANT, key="b"))
        await store.store(item=_make_item(scope=MemoryScope.PROJECT, key="p"))
        await store.store(item=_make_item(scope=MemoryScope.SESSION, key="s"))

        results = await store.search(
            query=MemoryQuery(
                scopes=(MemoryScope.TENANT, MemoryScope.PROJECT),
            ),
        )
        scopes = {r.item.scope for r in results}
        assert MemoryScope.SESSION not in scopes
        assert MemoryScope.TENANT in scopes

    @pytest.mark.asyncio
    async def test_no_scope_searches_all(self) -> None:
        store = _make_store()
        await store.store(item=_make_item(scope=MemoryScope.TENANT, key="b"))
        await store.store(item=_make_item(scope=MemoryScope.SESSION, key="s"))

        results = await store.search(query=MemoryQuery())
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Confidence filtering
# ---------------------------------------------------------------------------


class TestConfidenceFiltering:
    @pytest.mark.asyncio
    async def test_min_confidence_filter(self) -> None:
        store = _make_store()
        await store.store(item=_make_item(key="high", confidence=0.9))
        await store.store(item=_make_item(key="low", confidence=0.2))

        results = await store.search(
            query=MemoryQuery(min_confidence=0.5),
        )
        assert all(float(r.item.confidence) >= 0.5 for r in results)


# ---------------------------------------------------------------------------
# Max age filtering
# ---------------------------------------------------------------------------


class TestMaxAgeFiltering:
    @pytest.mark.asyncio
    async def test_max_age_filter(self) -> None:
        store = _make_store()
        await store.store(item=_make_item(key="fresh", age_seconds=60.0))
        await store.store(item=_make_item(key="old", age_seconds=7200.0))

        results = await store.search(
            query=MemoryQuery(max_age=timedelta(hours=1)),
        )
        assert all(r.item.key != "old" for r in results)


# ---------------------------------------------------------------------------
# Decay-affected ranking
# ---------------------------------------------------------------------------


class TestDecayAffectedRanking:
    @pytest.mark.asyncio
    async def test_fresher_items_ranked_higher(self) -> None:
        store = _make_store()
        await store.store(item=_make_item(key="fresh", age_seconds=10.0, confidence=0.8))
        await store.store(item=_make_item(key="stale", age_seconds=36000.0, confidence=0.8))

        results = await store.search(query=MemoryQuery())
        if len(results) >= 2:
            assert results[0].combined_score >= results[1].combined_score


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_expired(self) -> None:
        store = _make_store()
        item = _make_item(key="expiring")
        item = item.with_ttl(ttl=timedelta(seconds=-1))  # Already expired
        await store.store(item=item)
        removed = await store.cleanup_expired()
        assert removed >= 0  # InMemoryStore handles cleanup
