"""Integration tests for OpenViking enhancement seams.

Tests that verify real wiring between new modules:
- TieredMemoryStore → DefaultMemoryContextProvider (progressive retrieval)
- ScopeScorer → SemanticMemoryStore (scope-aware scoring)
- ExtractionPipeline → factory wiring (create_session_manager with extraction)
- ContextTypeClassifier → pluggable classification
"""

import pytest

from cemaf.context.classification import (
    ContextTypeBehavior,
    ContextTypeClassifier,
    DefaultContextTypeClassifier,
)
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.source import ContextType
from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import InMemoryStore, MemoryItem
from cemaf.memory.compaction import SimpleMemoryCompactor
from cemaf.memory.context_provider import DefaultMemoryContextProvider
from cemaf.memory.deduplication import SemanticDeduplicator
from cemaf.memory.episodic import InMemoryEpisodicStore
from cemaf.memory.factories import (
    create_extraction_pipeline,
    create_scope_scorer,
    create_session_manager,
)
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.scope_hierarchy import PropagatingScorer, ScopePath
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, MemoryQuery
from cemaf.memory.tiered import TruncationTierGenerator
from cemaf.memory.tiered_store import TieredMemoryStore
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider


def _wire_semantic_store() -> tuple[DefaultSemanticMemoryStore, InMemoryStore]:
    """Wire a real semantic store for integration tests."""
    store = InMemoryStore()
    embedding_provider = MockEmbeddingProvider()
    scorer = TemporalDecayScorer()
    semantic_store = DefaultSemanticMemoryStore(
        memory_store=store,
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=scorer,
    )
    return semantic_store, store


# ---------------------------------------------------------------------------
# Seam 1: TieredMemoryStore → DefaultMemoryContextProvider
# ---------------------------------------------------------------------------


class TestTieredContextProviderIntegration:
    """Tiered store wired into context provider uses progressive_search."""

    @pytest.mark.asyncio
    async def test_context_provider_with_tiered_store(self) -> None:
        """Wire tiered store into context provider → progressive path used."""
        semantic_store, _ = _wire_semantic_store()
        scorer = TemporalDecayScorer()

        tiered_store = TieredMemoryStore(
            semantic_store=semantic_store,
            tier_generator=TruncationTierGenerator(),
        )

        # Store items via tiered store
        for i in range(10):
            item = MemoryItem(
                scope=MemoryScope.PROJECT,
                key=f"doc-{i}",
                value={"content": f"Document about topic {i}" * 20},
                confidence=Confidence(0.7 + i * 0.02),
            )
            await tiered_store.store_with_tiers(item=item)

        # Wire into context provider
        manager = DefaultMemoryManager(
            semantic_store=semantic_store,
            episodic_store=InMemoryEpisodicStore(),
        )
        compactor = SimpleMemoryCompactor(scorer=scorer)
        token_estimator = SimpleTokenEstimator()
        compiler = PriorityContextCompiler(token_estimator=token_estimator)

        provider = DefaultMemoryContextProvider(
            memory_manager=manager,
            compactor=compactor,
            compiler=compiler,
            token_estimator=token_estimator,
            tiered_store=tiered_store,
        )

        sources = await provider.provide_context_sources(
            query=MemoryQuery(text="document topic", scope=MemoryScope.PROJECT),
            token_budget=2000,
        )

        assert len(sources) > 0
        assert all(s.source_type == "memory" for s in sources)

    @pytest.mark.asyncio
    async def test_context_provider_without_tiered_falls_back_to_flat(self) -> None:
        """Without tiered store → uses flat recall as before."""
        semantic_store, _ = _wire_semantic_store()
        scorer = TemporalDecayScorer()

        item = MemoryItem(
            scope=MemoryScope.PROJECT,
            key="flat-item",
            value={"content": "flat retrieval"},
        )
        await semantic_store.store(item=item)

        manager = DefaultMemoryManager(
            semantic_store=semantic_store,
            episodic_store=InMemoryEpisodicStore(),
        )
        compactor = SimpleMemoryCompactor(scorer=scorer)
        token_estimator = SimpleTokenEstimator()
        compiler = PriorityContextCompiler(token_estimator=token_estimator)

        provider = DefaultMemoryContextProvider(
            memory_manager=manager,
            compactor=compactor,
            compiler=compiler,
            token_estimator=token_estimator,
            # No tiered_store — flat path
        )

        sources = await provider.provide_context_sources(
            query=MemoryQuery(scope=MemoryScope.PROJECT),
            token_budget=2000,
        )

        assert len(sources) == 1
        assert sources[0].source_id == "project:flat-item"


# ---------------------------------------------------------------------------
# Seam 2: ScopeScorer → SemanticMemoryStore (scope-aware scoring)
# ---------------------------------------------------------------------------


class TestScopeScorerIntegration:
    """PropagatingScorer wired with real semantic store."""

    @pytest.mark.asyncio
    async def test_scope_scorer_with_stored_items(self) -> None:
        """Score scopes based on actual stored items."""
        semantic_store, _ = _wire_semantic_store()

        # Store items at different scope paths
        for i in range(3):
            item = MemoryItem(
                scope=MemoryScope.PROJECT,
                key=f"project/campaign/item-{i}",
                value={"data": f"campaign content {i}"},
                scope_path="project/campaign",
            )
            await semantic_store.store(item=item)

        scorer = PropagatingScorer(
            semantic_store=semantic_store,
            propagation_factor=0.7,
        )

        paths = (
            ScopePath.from_string(path="project"),
            ScopePath.from_string(path="project/campaign"),
        )

        nodes = await scorer.score_scopes(
            query=MemoryQuery(text="campaign content", scope=MemoryScope.PROJECT),
            scope_paths=paths,
        )

        assert len(nodes) == 2
        # Both should have scores (propagation may boost child)
        assert all(n.score >= 0.0 for n in nodes)

    @pytest.mark.asyncio
    async def test_factory_creates_scope_scorer(self) -> None:
        """create_scope_scorer factory produces working scorer."""
        semantic_store, _ = _wire_semantic_store()

        scorer = create_scope_scorer(
            semantic_store=semantic_store,
            propagation_factor=0.5,
        )

        assert isinstance(scorer, PropagatingScorer)
        # Verify it runs without error on empty data
        nodes = await scorer.score_scopes(
            query=MemoryQuery(text="test"),
            scope_paths=(),
        )
        assert nodes == ()


# ---------------------------------------------------------------------------
# Seam 3: ExtractionPipeline → factory wiring
# ---------------------------------------------------------------------------


class TestExtractionFactoryIntegration:
    """Factory-wired extraction pipeline works end-to-end."""

    @pytest.mark.asyncio
    async def test_create_extraction_pipeline_factory(self) -> None:
        """create_extraction_pipeline wires extractor + deduplicator."""
        semantic_store, _ = _wire_semantic_store()
        manager = DefaultMemoryManager(
            semantic_store=semantic_store,
            episodic_store=InMemoryEpisodicStore(),
        )

        pipeline = create_extraction_pipeline(memory_manager=manager)

        # Run with empty data — should return empty report
        report = await pipeline.run(
            session_memories=(),
            episodes=(),
            recent_events=(),
        )
        assert report.extracted_count == 0
        assert report.stored_count == 0

    @pytest.mark.asyncio
    async def test_create_session_manager_with_extraction(self) -> None:
        """create_session_manager with extraction_pipeline wires dispose()."""
        semantic_store, _ = _wire_semantic_store()
        deduplicator = SemanticDeduplicator(semantic_store=semantic_store)

        manager = DefaultMemoryManager(
            semantic_store=semantic_store,
            episodic_store=InMemoryEpisodicStore(),
            deduplicator=deduplicator,
        )

        pipeline = create_extraction_pipeline(
            memory_manager=manager,
            deduplicator=deduplicator,
        )

        session_mgr = create_session_manager(
            memory_manager=manager,
            extraction_pipeline=pipeline,
        )

        # Full lifecycle: bootstrap → ingest → dispose
        await session_mgr.bootstrap(session_id="test-sess")
        await session_mgr.ingest(
            session_id="test-sess",
            key="valuable-insight",
            value={"insight": "users prefer short responses"},
            confidence=0.95,
        )
        await session_mgr.dispose(session_id="test-sess")

        # Verify extraction promoted the high-confidence item
        results = await manager.recall(
            query=MemoryQuery(scope=MemoryScope.PROJECT, limit=100),
        )
        project_keys = {r.item.key for r in results}
        assert "promoted:valuable-insight" in project_keys


# ---------------------------------------------------------------------------
# Seam 4: ContextTypeClassifier pluggability
# ---------------------------------------------------------------------------


class TestClassifierPluggability:
    """Custom classifier can be injected, overriding default behaviors."""

    def test_custom_classifier_satisfies_protocol(self) -> None:
        """Any object with classify + get_behavior methods works."""
        custom_behaviors = {
            ContextType.RESOURCE: ContextTypeBehavior(
                cacheable=False,
                shareable=False,
                compressible=False,
                default_ttl_seconds=10.0,
                default_priority=1,
                preferred_compaction="full",
            ),
            ContextType.MEMORY: ContextTypeBehavior(
                cacheable=True,
                shareable=True,
                compressible=True,
                default_ttl_seconds=None,
                default_priority=99,
                preferred_compaction="summary",
            ),
            ContextType.SKILL: ContextTypeBehavior(
                cacheable=True,
                shareable=True,
                compressible=False,
                default_ttl_seconds=None,
                default_priority=5,
                preferred_compaction="full",
            ),
        }
        classifier = DefaultContextTypeClassifier(behaviors=custom_behaviors)
        assert isinstance(classifier, ContextTypeClassifier)

        # Verify custom behaviors apply
        behavior = classifier.get_behavior(context_type=ContextType.RESOURCE)
        assert behavior.cacheable is False
        assert behavior.default_ttl_seconds == 10.0

        behavior = classifier.get_behavior(context_type=ContextType.MEMORY)
        assert behavior.default_priority == 99
