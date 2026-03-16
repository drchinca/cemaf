"""Tests for Audit 6 fixes — scope_path propagation, event payload, session cleanup."""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import InMemoryStore, MemoryItem
from cemaf.memory.compaction import SimpleMemoryCompactor
from cemaf.memory.episodic import InMemoryEpisodicStore
from cemaf.memory.extraction import RuleBasedExtractor
from cemaf.memory.extraction_pipeline import ExtractionPipeline
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.scope_hierarchy import PropagatingScorer, ScopePath
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, MemoryQuery
from cemaf.memory.session import DefaultSessionManager
from cemaf.memory.tiered import TruncationTierGenerator
from cemaf.memory.tiered_store import TieredMemoryStore
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider


def _wire_semantic_store() -> DefaultSemanticMemoryStore:
    store = InMemoryStore()
    embedding_provider = MockEmbeddingProvider()
    return DefaultSemanticMemoryStore(
        memory_store=store,
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=TemporalDecayScorer(),
    )


class TestPropagatingScoperScopePathQuery:
    """P0 fix: PropagatingScorer now uses scope_path in query, not key-based filter."""

    @pytest.mark.asyncio
    async def test_scores_scopes_using_scope_path_field(self) -> None:
        """Items with scope_path='project/a' are found when scoring 'project/a'."""
        semantic_store = _wire_semantic_store()

        # Store items with scope_path set (but keys DON'T match path)
        item_a = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="brand-guidelines",
            value={"tone": "professional"},
            confidence=Confidence(0.9),
            scope_path="project/campaign-a",
        )
        item_b = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="audience-data",
            value={"demo": "millennials"},
            confidence=Confidence(0.8),
            scope_path="project/campaign-b",
        )
        await semantic_store.store(item=item_a)
        await semantic_store.store(item=item_b)

        scorer = PropagatingScorer(semantic_store=semantic_store)
        nodes = await scorer.score_scopes(
            query=MemoryQuery(scope=MemoryScope.PROJECT),
            scope_paths=(
                ScopePath.from_string(path="project/campaign-a"),
                ScopePath.from_string(path="project/campaign-b"),
            ),
        )

        # Both paths should have scores (items exist in each scope_path)
        scores_by_path = {str(n.path): n.score for n in nodes}
        assert "project/campaign-a" in scores_by_path
        assert "project/campaign-b" in scores_by_path


class TestTieredStoreScopePathPropagation:
    """P1 fix: TieredMemoryStore.progressive_search propagates scope_path."""

    @pytest.mark.asyncio
    async def test_progressive_search_respects_scope_path(self) -> None:
        """Query with scope_path filters results in progressive search."""
        semantic_store = _wire_semantic_store()
        tiered = TieredMemoryStore(
            semantic_store=semantic_store,
            tier_generator=TruncationTierGenerator(),
        )

        item_a = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="item-in-a",
            value={"data": "belongs to scope a"},
            scope_path="project/a",
        )
        item_b = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="item-in-b",
            value={"data": "belongs to scope b"},
            scope_path="project/b",
        )
        await tiered.store_with_tiers(item=item_a)
        await tiered.store_with_tiers(item=item_b)

        # Search with scope_path filter → only "project/a" items
        results = await tiered.progressive_search(
            query=MemoryQuery(
                scope=MemoryScope.PROJECT,
                scope_path="project/a",
            ),
        )

        keys = {r.item.key for r in results}
        assert "item-in-a" in keys
        assert "item-in-b" not in keys


class TestExtractionEventPayload:
    """P1 fix: MEMORY_EXTRACTED event includes output field with extracted items."""

    @pytest.mark.asyncio
    async def test_event_payload_has_output_field(self) -> None:
        """Pipeline emits event with output containing extracted item details."""
        semantic_store = _wire_semantic_store()
        manager = DefaultMemoryManager(
            semantic_store=semantic_store,
            episodic_store=InMemoryEpisodicStore(),
        )

        # Capture published events
        from cemaf.events.bus import InMemoryEventBus

        bus = InMemoryEventBus()
        captured_events: list = []

        def capture(event: object) -> None:
            captured_events.append(event)

        bus.subscribe(event_type="memory.extracted", handler=capture)

        pipeline = ExtractionPipeline(
            extractor=RuleBasedExtractor(min_confidence=0.5),
            memory_manager=manager,
            event_bus=bus,
        )

        session_memories = (
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="learned-thing",
                value={"insight": "test"},
                confidence=Confidence(0.9),
            ),
        )

        await pipeline.run(
            session_memories=session_memories,
            episodes=(),
            recent_events=(),
        )

        assert len(captured_events) == 1
        payload = captured_events[0].payload
        assert "output" in payload
        assert "items" in payload["output"]
        assert len(payload["output"]["items"]) >= 1
        assert payload["output"]["items"][0]["key"] == "promoted:learned-thing"


class TestSessionDisposeScoped:
    """P2 fix: dispose() only cleans SESSION-scoped items, not global cleanup."""

    @pytest.mark.asyncio
    async def test_dispose_preserves_project_memories(self) -> None:
        """PROJECT memories survive session dispose."""
        semantic_store = _wire_semantic_store()
        manager = DefaultMemoryManager(
            semantic_store=semantic_store,
            episodic_store=InMemoryEpisodicStore(),
        )
        scorer = TemporalDecayScorer()
        compactor = SimpleMemoryCompactor(scorer=scorer)

        session_mgr = DefaultSessionManager(
            memory_manager=manager,
            compactor=compactor,
        )

        # Store a PROJECT memory directly
        await manager.remember(
            scope=MemoryScope.PROJECT,
            key="important-project-data",
            value={"data": "must survive"},
        )

        # Run session lifecycle
        await session_mgr.bootstrap(session_id="test-sess")
        await session_mgr.ingest(
            session_id="test-sess",
            key="session-only",
            value={"temp": True},
        )
        await session_mgr.dispose(session_id="test-sess")

        # PROJECT memory must still exist
        project_item = await manager.recall_by_key(
            scope=MemoryScope.PROJECT,
            key="important-project-data",
        )
        assert project_item is not None
        assert project_item.value == {"data": "must survive"}
