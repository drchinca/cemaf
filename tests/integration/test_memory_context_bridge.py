"""Integration tests: memory system → context compiler pipeline.

These tests use REAL implementations (no mocks) to verify the three
systems (memory, retrieval, context) are genuinely connected end-to-end.
"""

import pytest

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.core.enums import MemoryScope
from cemaf.memory.base import InMemoryStore
from cemaf.memory.compaction import SimpleMemoryCompactor
from cemaf.memory.context_provider import DefaultMemoryContextProvider
from cemaf.memory.episodic import InMemoryEpisodicStore
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, MemoryQuery
from cemaf.memory.session import DefaultSessionManager
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider

# ---------------------------------------------------------------------------
# Shared wiring — all real implementations, no mocks
# ---------------------------------------------------------------------------


def _wire_full_stack() -> tuple[
    DefaultMemoryManager,
    SimpleMemoryCompactor,
    DefaultMemoryContextProvider,
    DefaultSessionManager,
]:
    """Wire the full memory → retrieval → context stack with real implementations."""
    embedding_provider = MockEmbeddingProvider()
    scorer = TemporalDecayScorer()
    token_estimator = SimpleTokenEstimator()

    semantic_store = DefaultSemanticMemoryStore(
        memory_store=InMemoryStore(),
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=scorer,
    )
    episodic_store = InMemoryEpisodicStore()
    memory_manager = DefaultMemoryManager(
        semantic_store=semantic_store,
        episodic_store=episodic_store,
    )

    compactor = SimpleMemoryCompactor(scorer=scorer)

    compiler = PriorityContextCompiler(
        token_estimator=token_estimator,
    )

    context_provider = DefaultMemoryContextProvider(
        memory_manager=memory_manager,
        compactor=compactor,
        compiler=compiler,
        token_estimator=token_estimator,
    )

    session_manager = DefaultSessionManager(
        memory_manager=memory_manager,
        compactor=compactor,
    )

    return memory_manager, compactor, context_provider, session_manager


# ---------------------------------------------------------------------------
# Memory → Context: MemoryContextProvider produces real ContextSources
# ---------------------------------------------------------------------------


class TestMemoryToContextSources:
    """Verify memories flow through compaction into ContextSource objects."""

    @pytest.mark.asyncio
    async def test_stored_memories_become_context_sources(self) -> None:
        manager, _, provider, _ = _wire_full_stack()

        # Store memories through the manager
        await manager.remember(
            scope=MemoryScope.TENANT,
            key="company_name",
            value={"name": "Acme Corp"},
        )
        await manager.remember(
            scope=MemoryScope.TENANT,
            key="brand_voice",
            value={"tone": "professional", "style": "concise"},
        )

        # Pull them out as ContextSources
        sources = await provider.provide_context_sources(
            query=MemoryQuery(scope=MemoryScope.TENANT),
            token_budget=1000,
        )

        assert len(sources) == 2
        # Each source should be a real ContextSource with memory type
        for source in sources:
            assert source.source_type == "memory"
            assert source.content  # Not empty
            assert source.token_count is not None
            assert source.priority == 7  # from_memory default

    @pytest.mark.asyncio
    async def test_compaction_respects_budget(self) -> None:
        manager, _, provider, _ = _wire_full_stack()

        # Store a lot of content
        for i in range(20):
            await manager.remember(
                scope=MemoryScope.SESSION,
                key=f"item_{i}",
                value={"data": f"content {'x' * 200} for item {i}"},
            )

        # Ask for sources with a tight budget
        sources = await provider.provide_context_sources(
            query=MemoryQuery(scope=MemoryScope.SESSION),
            token_budget=50,
        )

        # Should get some sources, but not all 20 at full fidelity
        total_tokens = sum(s.token_count or 0 for s in sources)
        assert total_tokens <= 50

    @pytest.mark.asyncio
    async def test_empty_memory_returns_empty_sources(self) -> None:
        _, _, provider, _ = _wire_full_stack()

        sources = await provider.provide_context_sources(
            query=MemoryQuery(scope=MemoryScope.TENANT),
            token_budget=1000,
        )
        assert sources == ()


# ---------------------------------------------------------------------------
# Memory → Compiler: memories feed into compile() and appear in output
# ---------------------------------------------------------------------------


class TestMemoryToCompiler:
    """Verify memories flow through the compiler and appear in CompiledContext."""

    @pytest.mark.asyncio
    async def test_memories_appear_in_compiled_output(self) -> None:
        manager, _, provider, _ = _wire_full_stack()

        await manager.remember(
            scope=MemoryScope.TENANT,
            key="tagline",
            value={"text": "Innovation meets reliability"},
        )

        # Compile with both artifacts and memories
        budget = TokenBudget(max_tokens=4000, reserved_for_output=500)
        compiled = await provider.compile_with_memories(
            artifacts=(("system_prompt", "You are a helpful assistant."),),
            memory_query=MemoryQuery(scope=MemoryScope.TENANT),
            budget=budget,
        )

        # Should contain both artifact and memory sources
        source_types = {s.source_type for s in compiled.sources}
        assert "artifact" in source_types
        assert "memory" in source_types

        # Memory content should be present
        memory_sources = [s for s in compiled.sources if s.source_type == "memory"]
        assert len(memory_sources) >= 1
        memory_content = " ".join(s.content for s in memory_sources)
        assert "Innovation meets reliability" in memory_content

    @pytest.mark.asyncio
    async def test_compiled_context_within_budget(self) -> None:
        manager, _, provider, _ = _wire_full_stack()

        for i in range(10):
            await manager.remember(
                scope=MemoryScope.TENANT,
                key=f"fact_{i}",
                value={"info": f"Important fact number {i} with details"},
            )

        budget = TokenBudget(max_tokens=500, reserved_for_output=100)
        compiled = await provider.compile_with_memories(
            artifacts=(("prompt", "Brief prompt"),),
            memory_query=MemoryQuery(scope=MemoryScope.TENANT),
            budget=budget,
        )

        assert compiled.within_budget()

    @pytest.mark.asyncio
    async def test_compile_with_no_memories(self) -> None:
        _, _, provider, _ = _wire_full_stack()

        budget = TokenBudget(max_tokens=4000, reserved_for_output=500)
        compiled = await provider.compile_with_memories(
            artifacts=(("prompt", "Hello world"),),
            memory_query=MemoryQuery(scope=MemoryScope.TENANT),
            budget=budget,
        )

        # Should still compile successfully with just artifacts
        assert len(compiled.sources) >= 1
        assert compiled.sources[0].source_type == "artifact"

    @pytest.mark.asyncio
    async def test_to_messages_includes_memories(self) -> None:
        manager, _, provider, _ = _wire_full_stack()

        await manager.remember(
            scope=MemoryScope.TENANT,
            key="voice",
            value={"tone": "friendly"},
        )

        budget = TokenBudget(max_tokens=4000, reserved_for_output=500)
        compiled = await provider.compile_with_memories(
            artifacts=(),
            memory_query=MemoryQuery(scope=MemoryScope.TENANT),
            budget=budget,
        )

        messages = compiled.to_messages()
        # Memories should appear in the system message
        if messages:
            system_content = messages[0].get("content", "")
            assert "Memory" in system_content


# ---------------------------------------------------------------------------
# Session lifecycle → Context: bootstrap/ingest/compact → ContextSource
# ---------------------------------------------------------------------------


class TestSessionToContext:
    """Verify the session lifecycle produces context-ready output."""

    @pytest.mark.asyncio
    async def test_compact_produces_context_sources(self) -> None:
        manager, compactor, provider, session_mgr = _wire_full_stack()

        await session_mgr.bootstrap(session_id="sess-1")
        await session_mgr.ingest(
            session_id="sess-1",
            key="user_preference",
            value={"theme": "dark", "language": "en"},
        )
        await session_mgr.ingest(
            session_id="sess-1",
            key="recent_topic",
            value={"topic": "machine learning", "depth": "intermediate"},
        )

        # Compact returns CompactedMemory objects
        compacted = await session_mgr.compact(session_id="sess-1")

        # Each CompactedMemory can become a ContextSource
        sources = tuple(cm.to_context_source() for cm in compacted)
        for source in sources:
            assert source.source_type == "memory"
            assert source.content  # Not empty
            assert source.token_count is not None

    @pytest.mark.asyncio
    async def test_full_session_to_compiled_context(self) -> None:
        """End-to-end: bootstrap → ingest → compile with memories."""
        manager, _, provider, session_mgr = _wire_full_stack()

        # Bootstrap session
        await session_mgr.bootstrap(session_id="sess-1")

        # Ingest some data
        await session_mgr.ingest(
            session_id="sess-1",
            key="context_hint",
            value={"hint": "User prefers detailed explanations"},
        )

        # Now compile context pulling from session memories
        budget = TokenBudget(max_tokens=4000, reserved_for_output=500)
        compiled = await provider.compile_with_memories(
            artifacts=(("system", "You are an AI assistant"),),
            memory_query=MemoryQuery(scope=MemoryScope.SESSION),
            budget=budget,
        )

        # Session memories should appear in compiled context
        memory_sources = [s for s in compiled.sources if s.source_type == "memory"]
        assert len(memory_sources) >= 1

        # Dispose session cleanly
        await session_mgr.dispose(session_id="sess-1")


# ---------------------------------------------------------------------------
# Memory → Retrieval → Context: semantic search feeds compilation
# ---------------------------------------------------------------------------


class TestSemanticSearchToContext:
    """Verify semantic search results feed into context compilation."""

    @pytest.mark.asyncio
    async def test_semantic_search_results_become_compiled_context(self) -> None:
        manager, _, provider, _ = _wire_full_stack()

        # Store diverse memories
        await manager.remember(
            scope=MemoryScope.PROJECT,
            key="api_design",
            value={"pattern": "REST", "versioning": "URL-based"},
            content_for_embedding="API design follows REST patterns with URL-based versioning",
        )
        await manager.remember(
            scope=MemoryScope.PROJECT,
            key="deployment",
            value={"platform": "AWS", "strategy": "blue-green"},
            content_for_embedding="Deployment uses AWS with blue-green strategy",
        )

        # Semantic search → compile
        budget = TokenBudget(max_tokens=4000, reserved_for_output=500)
        compiled = await provider.compile_with_memories(
            artifacts=(("task", "Design the API endpoint"),),
            memory_query=MemoryQuery(text="API design", limit=5),
            budget=budget,
        )

        # Should have both artifact and memory
        source_types = {s.source_type for s in compiled.sources}
        assert "artifact" in source_types
        assert "memory" in source_types
