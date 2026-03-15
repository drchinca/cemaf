"""Unit tests for memory deduplication."""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import MemoryItem
from cemaf.memory.deduplication import (
    DeduplicationAction,
    DuplicateMatch,
    MatchType,
    MemoryDeduplicator,
    SemanticDeduplicator,
)
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider


def _create_semantic_store() -> DefaultSemanticMemoryStore:
    """Wire up a real semantic store for testing."""
    from cemaf.memory.base import InMemoryStore

    embedding_provider = MockEmbeddingProvider()
    return DefaultSemanticMemoryStore(
        memory_store=InMemoryStore(),
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=TemporalDecayScorer(),
    )


class TestSemanticDeduplicatorProtocol:
    """Verify SemanticDeduplicator satisfies the MemoryDeduplicator protocol."""

    def test_satisfies_protocol(self) -> None:
        store = _create_semantic_store()
        dedup = SemanticDeduplicator(semantic_store=store)
        assert isinstance(dedup, MemoryDeduplicator)


class TestFindDuplicates:
    """Contract tests for find_duplicates."""

    @pytest.mark.asyncio
    async def test_returns_empty_for_novel_item(self) -> None:
        """No existing items → empty tuple."""
        store = _create_semantic_store()
        dedup = SemanticDeduplicator(semantic_store=store)

        candidate = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="unique-item",
            value={"data": "completely novel"},
        )
        matches = await dedup.find_duplicates(candidate=candidate)
        assert matches == ()

    @pytest.mark.asyncio
    async def test_detects_exact_key_duplicate(self) -> None:
        """Same scope:key → exact key match."""
        store = _create_semantic_store()
        dedup = SemanticDeduplicator(semantic_store=store)

        existing = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="brand-guidelines",
            value={"tone": "professional"},
            confidence=Confidence(0.9),
        )
        await store.store(item=existing)

        candidate = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="brand-guidelines",
            value={"tone": "casual"},
            confidence=Confidence(0.7),
        )
        matches = await dedup.find_duplicates(candidate=candidate)

        assert len(matches) == 1
        assert matches[0].match_type == MatchType.EXACT_KEY
        assert matches[0].similarity == 1.0
        assert matches[0].existing.key == "brand-guidelines"

    @pytest.mark.asyncio
    async def test_detects_semantic_near_duplicate(self) -> None:
        """Store item, candidate with similar value → returns match above threshold."""
        store = _create_semantic_store()
        dedup = SemanticDeduplicator(semantic_store=store, similarity_threshold=0.0)

        existing = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="brand-voice",
            value={"description": "professional and authoritative tone"},
            confidence=Confidence(0.8),
        )
        await store.store(item=existing)

        candidate = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="voice-guidelines",
            value={"description": "professional authoritative communication style"},
            confidence=Confidence(0.6),
        )
        matches = await dedup.find_duplicates(candidate=candidate, threshold=0.0)

        assert len(matches) >= 1
        assert all(m.match_type == MatchType.SEMANTIC for m in matches)


class TestResolve:
    """Contract tests for resolve."""

    @pytest.mark.asyncio
    async def test_store_new_when_no_matches(self) -> None:
        """No matches → STORE_NEW."""
        store = _create_semantic_store()
        dedup = SemanticDeduplicator(semantic_store=store)

        candidate = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="novel-item",
            value={"data": "new"},
        )
        result = await dedup.resolve(candidate=candidate, matches=())

        assert result.action == DeduplicationAction.STORE_NEW
        assert result.item == candidate
        assert result.skipped is False

    @pytest.mark.asyncio
    async def test_merge_on_exact_key(self) -> None:
        """Exact key match → MERGE."""
        store = _create_semantic_store()
        dedup = SemanticDeduplicator(semantic_store=store)

        existing = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="guidelines",
            value={"tone": "old"},
            confidence=Confidence(0.5),
        )
        candidate = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="guidelines",
            value={"tone": "new"},
            confidence=Confidence(0.9),
        )

        matches = (DuplicateMatch(existing=existing, similarity=1.0, match_type=MatchType.EXACT_KEY),)
        result = await dedup.resolve(candidate=candidate, matches=matches)

        assert result.action == DeduplicationAction.MERGE
        assert result.skipped is False
        assert result.merged_from == (existing.full_key,)

    @pytest.mark.asyncio
    async def test_skips_when_existing_has_higher_confidence(self) -> None:
        """Semantic match with existing confidence=0.9, candidate=0.5 → SKIP."""
        store = _create_semantic_store()
        dedup = SemanticDeduplicator(semantic_store=store)

        existing = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="high-conf",
            value={"data": "existing"},
            confidence=Confidence(0.9),
        )
        candidate = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="low-conf",
            value={"data": "candidate"},
            confidence=Confidence(0.5),
        )

        matches = (DuplicateMatch(existing=existing, similarity=0.9, match_type=MatchType.SEMANTIC),)
        result = await dedup.resolve(candidate=candidate, matches=matches)

        assert result.action == DeduplicationAction.SKIP
        assert result.skipped is True

    @pytest.mark.asyncio
    async def test_merges_when_candidate_has_higher_confidence(self) -> None:
        """Semantic match with candidate confidence > existing → MERGE."""
        store = _create_semantic_store()
        dedup = SemanticDeduplicator(semantic_store=store)

        existing = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="low-conf",
            value={"data": "existing"},
            confidence=Confidence(0.3),
        )
        candidate = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="high-conf",
            value={"data": "candidate"},
            confidence=Confidence(0.9),
        )

        matches = (DuplicateMatch(existing=existing, similarity=0.9, match_type=MatchType.SEMANTIC),)
        result = await dedup.resolve(candidate=candidate, matches=matches)

        assert result.action == DeduplicationAction.MERGE
        assert result.skipped is False
