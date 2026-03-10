"""Tests for DefaultMemoryContextProvider."""

import pytest

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.source import ContextSource
from cemaf.core.enums import MemoryScope
from cemaf.memory.base import InMemoryStore
from cemaf.memory.compaction import SimpleMemoryCompactor
from cemaf.memory.context_provider import (
    DefaultMemoryContextProvider,
    MemoryContextProvider,
)
from cemaf.memory.episodic import InMemoryEpisodicStore
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore, MemoryQuery
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider

# ---------------------------------------------------------------------------
# Wiring helper — real implementations, no mocks
# ---------------------------------------------------------------------------


def _make_provider() -> tuple[DefaultMemoryManager, DefaultMemoryContextProvider]:
    """Wire a DefaultMemoryContextProvider with real implementations."""
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
    compiler = PriorityContextCompiler(token_estimator=token_estimator)

    provider = DefaultMemoryContextProvider(
        memory_manager=memory_manager,
        compactor=compactor,
        compiler=compiler,
        token_estimator=token_estimator,
    )

    return memory_manager, provider


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_satisfies_memory_context_provider_protocol(self) -> None:
        _, provider = _make_provider()
        assert isinstance(provider, MemoryContextProvider)


# ---------------------------------------------------------------------------
# _allocate_memory_budget
# ---------------------------------------------------------------------------


class TestAllocateMemoryBudget:
    def test_with_explicit_section_budget_returns_that_budget(self) -> None:
        _, provider = _make_provider()
        budget = TokenBudget(
            max_tokens=4000,
            reserved_for_output=500,
        ).with_allocation(section="memory", max_tokens=800)

        result = provider._allocate_memory_budget(
            total_budget=budget,
            artifact_count=2,
        )
        assert result == 800

    def test_without_section_budget_returns_30_percent_of_available(self) -> None:
        _, provider = _make_provider()
        budget = TokenBudget(max_tokens=4000, reserved_for_output=1000)
        # available = 4000 - 1000 = 3000, 30% = 900

        result = provider._allocate_memory_budget(
            total_budget=budget,
            artifact_count=0,
        )
        assert result == 900

    def test_zero_available_tokens_returns_zero(self) -> None:
        _, provider = _make_provider()
        budget = TokenBudget(max_tokens=500, reserved_for_output=500)
        # available = 0, 30% = 0

        result = provider._allocate_memory_budget(
            total_budget=budget,
            artifact_count=0,
        )
        assert result == 0


# ---------------------------------------------------------------------------
# provide_context_sources
# ---------------------------------------------------------------------------


class TestProvideContextSources:
    @pytest.mark.asyncio
    async def test_with_memories_returns_context_source_objects(self) -> None:
        manager, provider = _make_provider()

        await manager.remember(
            scope=MemoryScope.BRAND,
            key="name",
            value={"name": "TestCorp"},
        )

        sources = await provider.provide_context_sources(
            query=MemoryQuery(scope=MemoryScope.BRAND),
            token_budget=1000,
        )

        assert len(sources) == 1
        assert isinstance(sources[0], ContextSource)
        assert sources[0].source_type == "memory"
        assert sources[0].content  # non-empty

    @pytest.mark.asyncio
    async def test_empty_memories_returns_empty_tuple(self) -> None:
        _, provider = _make_provider()

        sources = await provider.provide_context_sources(
            query=MemoryQuery(scope=MemoryScope.BRAND),
            token_budget=1000,
        )

        assert sources == ()


# ---------------------------------------------------------------------------
# provide_memories_for_compiler
# ---------------------------------------------------------------------------


class TestProvideMemoriesForCompiler:
    @pytest.mark.asyncio
    async def test_returns_key_content_pairs(self) -> None:
        manager, provider = _make_provider()

        await manager.remember(
            scope=MemoryScope.PROJECT,
            key="api_style",
            value={"style": "REST"},
        )

        pairs = await provider.provide_memories_for_compiler(
            query=MemoryQuery(scope=MemoryScope.PROJECT),
            token_budget=1000,
        )

        assert len(pairs) == 1
        source_id, content = pairs[0]
        assert isinstance(source_id, str)
        assert isinstance(content, str)
        assert content  # non-empty

    @pytest.mark.asyncio
    async def test_empty_memories_returns_empty_tuple(self) -> None:
        _, provider = _make_provider()

        pairs = await provider.provide_memories_for_compiler(
            query=MemoryQuery(scope=MemoryScope.SESSION),
            token_budget=1000,
        )

        assert pairs == ()


# ---------------------------------------------------------------------------
# compile_with_memories
# ---------------------------------------------------------------------------


class TestCompileWithMemories:
    @pytest.mark.asyncio
    async def test_with_artifacts_and_memories_returns_both_types(self) -> None:
        manager, provider = _make_provider()

        await manager.remember(
            scope=MemoryScope.BRAND,
            key="tagline",
            value={"text": "Build better things"},
        )

        budget = TokenBudget(max_tokens=4000, reserved_for_output=500)
        compiled = await provider.compile_with_memories(
            artifacts=(("system_prompt", "You are a helpful assistant."),),
            memory_query=MemoryQuery(scope=MemoryScope.BRAND),
            budget=budget,
        )

        source_types = {s.source_type for s in compiled.sources}
        assert "artifact" in source_types
        assert "memory" in source_types

    @pytest.mark.asyncio
    async def test_with_zero_artifacts_works(self) -> None:
        manager, provider = _make_provider()

        await manager.remember(
            scope=MemoryScope.BRAND,
            key="voice",
            value={"tone": "casual"},
        )

        budget = TokenBudget(max_tokens=4000, reserved_for_output=500)
        compiled = await provider.compile_with_memories(
            artifacts=(),
            memory_query=MemoryQuery(scope=MemoryScope.BRAND),
            budget=budget,
        )

        memory_sources = [s for s in compiled.sources if s.source_type == "memory"]
        assert len(memory_sources) >= 1

    @pytest.mark.asyncio
    async def test_with_zero_memories_works(self) -> None:
        _, provider = _make_provider()

        budget = TokenBudget(max_tokens=4000, reserved_for_output=500)
        compiled = await provider.compile_with_memories(
            artifacts=(("prompt", "Hello world"),),
            memory_query=MemoryQuery(scope=MemoryScope.BRAND),
            budget=budget,
        )

        assert len(compiled.sources) >= 1
        assert compiled.sources[0].source_type == "artifact"

    @pytest.mark.asyncio
    async def test_compiled_context_respects_budget(self) -> None:
        manager, provider = _make_provider()

        for i in range(5):
            await manager.remember(
                scope=MemoryScope.SESSION,
                key=f"item_{i}",
                value={"data": f"content for item {i}"},
            )

        budget = TokenBudget(max_tokens=2000, reserved_for_output=500)
        compiled = await provider.compile_with_memories(
            artifacts=(("system", "Be helpful"),),
            memory_query=MemoryQuery(scope=MemoryScope.SESSION),
            budget=budget,
        )

        assert compiled.within_budget()
