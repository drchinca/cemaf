"""Unit tests for hierarchical scope propagation."""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import InMemoryStore, MemoryItem
from cemaf.memory.scope_hierarchy import (
    PropagatingScorer,
    ScopePath,
    ScopeScorer,
)
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, MemoryQuery
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider


class TestScopePath:
    """Contract: ScopePath parsing and navigation."""

    def test_from_string_basic(self) -> None:
        path = ScopePath.from_string(path="project/campaign/assets")
        assert path.root == "project"
        assert path.depth == 3
        assert str(path) == "project/campaign/assets"

    def test_parent_navigation(self) -> None:
        path = ScopePath.from_string(path="project/campaign/assets")
        parent = path.parent
        assert parent is not None
        assert str(parent) == "project/campaign"
        assert parent.parent is not None
        assert str(parent.parent) == "project"
        assert parent.parent.parent is None

    def test_is_ancestor_of(self) -> None:
        root = ScopePath.from_string(path="project")
        child = ScopePath.from_string(path="project/campaign")
        grandchild = ScopePath.from_string(path="project/campaign/assets")
        other = ScopePath.from_string(path="other/path")

        assert root.is_ancestor_of(other=child)
        assert root.is_ancestor_of(other=grandchild)
        assert child.is_ancestor_of(other=grandchild)
        assert not grandchild.is_ancestor_of(other=root)
        assert not root.is_ancestor_of(other=other)

    def test_empty_path_raises(self) -> None:
        with pytest.raises(ValueError):
            ScopePath.from_string(path="")

    def test_single_segment(self) -> None:
        path = ScopePath.from_string(path="project")
        assert path.root == "project"
        assert path.depth == 1
        assert path.parent is None


class TestPropagatingScorer:
    """Contract: score propagation from parent to child."""

    def test_satisfies_protocol(self) -> None:
        store = InMemoryStore()
        embedding_provider = MockEmbeddingProvider()
        semantic_store = DefaultSemanticMemoryStore(
            memory_store=store,
            vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
            embedding_provider=embedding_provider,
            scorer=TemporalDecayScorer(),
        )
        scorer = PropagatingScorer(semantic_store=semantic_store)
        assert isinstance(scorer, ScopeScorer)

    @pytest.mark.asyncio
    async def test_empty_scopes_returns_empty(self) -> None:
        store = InMemoryStore()
        embedding_provider = MockEmbeddingProvider()
        semantic_store = DefaultSemanticMemoryStore(
            memory_store=store,
            vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
            embedding_provider=embedding_provider,
            scorer=TemporalDecayScorer(),
        )
        scorer = PropagatingScorer(semantic_store=semantic_store)

        result = await scorer.score_scopes(
            query=MemoryQuery(text="test"),
            scope_paths=(),
        )
        assert result == ()


class TestQueryWithScopePath:
    """Contract: scope_path filtering in semantic search."""

    @pytest.mark.asyncio
    async def test_scope_path_narrows_results(self) -> None:
        """Items at 'project/a' and 'project/b', query for 'project/a' → only 'a' items."""
        store = InMemoryStore()
        embedding_provider = MockEmbeddingProvider()
        semantic_store = DefaultSemanticMemoryStore(
            memory_store=store,
            vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
            embedding_provider=embedding_provider,
            scorer=TemporalDecayScorer(),
        )

        item_a = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="item-a",
            value={"data": "alpha content"},
            confidence=Confidence(0.8),
            scope_path="project/a",
        )
        item_b = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="item-b",
            value={"data": "beta content"},
            confidence=Confidence(0.8),
            scope_path="project/b",
        )
        await semantic_store.store(item=item_a)
        await semantic_store.store(item=item_b)

        results = await semantic_store.search(
            query=MemoryQuery(
                scope=MemoryScope.PROJECT,
                scope_path="project/a",
                limit=100,
            ),
        )

        keys = {r.item.key for r in results}
        assert "item-a" in keys
        assert "item-b" not in keys

    @pytest.mark.asyncio
    async def test_no_scope_path_returns_all(self) -> None:
        """Without scope_path filter, all items returned."""
        store = InMemoryStore()
        embedding_provider = MockEmbeddingProvider()
        semantic_store = DefaultSemanticMemoryStore(
            memory_store=store,
            vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
            embedding_provider=embedding_provider,
            scorer=TemporalDecayScorer(),
        )

        item_a = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="item-a",
            value={"data": "alpha"},
            scope_path="project/a",
        )
        item_b = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="item-b",
            value={"data": "beta"},
            scope_path="project/b",
        )
        await semantic_store.store(item=item_a)
        await semantic_store.store(item=item_b)

        results = await semantic_store.search(
            query=MemoryQuery(scope=MemoryScope.PROJECT, limit=100),
        )

        keys = {r.item.key for r in results}
        assert "item-a" in keys
        assert "item-b" in keys

    @pytest.mark.asyncio
    async def test_with_update_preserves_scope_path(self) -> None:
        """MemoryItem.with_update() preserves scope_path."""
        item = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="test",
            value={"v": 1},
            scope_path="project/campaign",
        )
        updated = item.with_update(value={"v": 2})
        assert updated.scope_path == "project/campaign"
