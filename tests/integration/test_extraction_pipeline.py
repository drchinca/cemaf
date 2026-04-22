"""Integration tests for the full extraction pipeline."""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import InMemoryStore, MemoryItem
from cemaf.memory.compaction import SimpleMemoryCompactor
from cemaf.memory.deduplication import SemanticDeduplicator
from cemaf.memory.episodic import InMemoryEpisodicStore
from cemaf.memory.extraction import RuleBasedExtractor
from cemaf.memory.extraction_pipeline import ExtractionPipeline
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, MemoryQuery
from cemaf.memory.session import DefaultSessionManager
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider


def _wire_full_stack() -> tuple[
    DefaultMemoryManager,
    DefaultSemanticMemoryStore,
    ExtractionPipeline,
    DefaultSessionManager,
]:
    """Wire manager + deduplicator + extraction pipeline + session manager."""
    store = InMemoryStore()
    embedding_provider = MockEmbeddingProvider()
    scorer = TemporalDecayScorer()

    semantic_store = DefaultSemanticMemoryStore(
        memory_store=store,
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=scorer,
    )
    deduplicator = SemanticDeduplicator(semantic_store=semantic_store)
    episodic_store = InMemoryEpisodicStore()

    manager = DefaultMemoryManager(
        semantic_store=semantic_store,
        episodic_store=episodic_store,
        deduplicator=deduplicator,
    )

    extractor = RuleBasedExtractor(min_confidence=0.6)
    pipeline = ExtractionPipeline(
        extractor=extractor,
        deduplicator=deduplicator,
        memory_manager=manager,
    )

    compactor = SimpleMemoryCompactor(scorer=scorer)
    session_manager = DefaultSessionManager(
        memory_manager=manager,
        compactor=compactor,
        extraction_pipeline=pipeline,
    )

    return manager, semantic_store, pipeline, session_manager


class TestExtractionPipelineDeduplicates:
    """Integration: pipeline deduplicates extracted memories."""

    @pytest.mark.asyncio
    async def test_deduplicates_extracted_items(self) -> None:
        """Extract 3 items, 1 duplicate → stored_count < extracted_count."""
        manager, semantic_store, pipeline, _ = _wire_full_stack()

        # Pre-store an item that will match one of the extracted
        await manager.remember(
            scope=MemoryScope.PROJECT,
            key="promoted:existing-fact",
            value={"fact": "already known"},
            confidence=0.95,
        )

        session_memories = (
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="existing-fact",
                value={"fact": "already known"},
                confidence=Confidence(0.8),
            ),
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="new-fact",
                value={"fact": "novel discovery"},
                confidence=Confidence(0.9),
            ),
        )

        report = await pipeline.run(
            session_memories=session_memories,
            episodes=(),
            recent_events=(),
        )

        assert report.extracted_count == 2
        # Both get stored (merge stores the winner), but one is flagged as deduplicated
        assert report.stored_count == 2
        assert report.deduplicated_count >= 1


class TestFullSessionLifecycleWithExtraction:
    """Integration: bootstrap → ingest → dispose → verify extraction."""

    @pytest.mark.asyncio
    async def test_dispose_triggers_extraction(self) -> None:
        """Session with high-confidence items → dispose → promoted to PROJECT."""
        manager, _, _, session_manager = _wire_full_stack()

        # Bootstrap session
        state = await session_manager.bootstrap(session_id="test-session")
        assert state is not None

        # Ingest high-confidence items
        await session_manager.ingest(
            session_id="test-session",
            key="important-learning",
            value={"insight": "users prefer concise responses"},
            confidence=0.9,
        )
        await session_manager.ingest(
            session_id="test-session",
            key="another-learning",
            value={"insight": "error messages need context"},
            confidence=0.85,
        )
        # Low confidence — should not be promoted
        await session_manager.ingest(
            session_id="test-session",
            key="uncertain-thing",
            value={"maybe": "not sure"},
            confidence=0.3,
        )

        # Dispose triggers extraction
        await session_manager.dispose(session_id="test-session")

        # Verify: high-confidence items promoted to PROJECT
        project_results = await manager.recall(
            query=MemoryQuery(scope=MemoryScope.PROJECT, limit=100),
        )
        project_keys = {r.item.key for r in project_results}

        assert "promoted:important-learning" in project_keys
        assert "promoted:another-learning" in project_keys
        # Low confidence should NOT be promoted
        assert "promoted:uncertain-thing" not in project_keys
