"""Bridge between memory system and context compiler pipeline."""

from typing import Protocol, runtime_checkable

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import CompiledContext, ContextCompiler, TokenEstimator
from cemaf.context.source import ContextSource
from cemaf.memory.compaction import MemoryCompactor
from cemaf.memory.manager import MemoryManager
from cemaf.memory.semantic import MemoryQuery
from cemaf.memory.tiered_store import TieredMemoryStore


@runtime_checkable
class MemoryContextProvider(Protocol):
    """Pulls memories and formats them for the context compiler."""

    async def provide_context_sources(
        self,
        query: MemoryQuery,
        *,
        token_budget: int,
    ) -> tuple[ContextSource, ...]: ...

    async def provide_memories_for_compiler(
        self,
        query: MemoryQuery,
        *,
        token_budget: int,
    ) -> tuple[tuple[str, str], ...]: ...

    async def compile_with_memories(
        self,
        artifacts: tuple[tuple[str, str], ...],
        memory_query: MemoryQuery,
        budget: TokenBudget,
        *,
        priorities: dict[str, int] | None = None,
    ) -> CompiledContext: ...


class DefaultMemoryContextProvider:
    """Fetches memories, compacts them, and feeds them into the context compiler."""

    def __init__(
        self,
        *,
        memory_manager: MemoryManager,
        compactor: MemoryCompactor,
        compiler: ContextCompiler,
        token_estimator: TokenEstimator,
        tiered_store: TieredMemoryStore | None = None,
    ) -> None:
        self._memory_manager = memory_manager
        self._compactor = compactor
        self._compiler = compiler
        self._token_estimator = token_estimator
        self._tiered_store = tiered_store

    async def provide_context_sources(
        self,
        query: MemoryQuery,
        *,
        token_budget: int,
    ) -> tuple[ContextSource, ...]:
        """Fetch, compact, and return as ContextSource objects."""
        if self._tiered_store is not None:
            return await self._provide_via_tiered(query=query, token_budget=token_budget)
        return await self._provide_via_flat(query=query, token_budget=token_budget)

    async def provide_memories_for_compiler(
        self,
        query: MemoryQuery,
        *,
        token_budget: int,
    ) -> tuple[tuple[str, str], ...]:
        """Fetch, compact, and return as (key, content) pairs for the compiler."""
        sources = await self.provide_context_sources(
            query=query,
            token_budget=token_budget,
        )
        return tuple((source.source_id, source.content) for source in sources)

    async def compile_with_memories(
        self,
        artifacts: tuple[tuple[str, str], ...],
        memory_query: MemoryQuery,
        budget: TokenBudget,
        *,
        priorities: dict[str, int] | None = None,
    ) -> CompiledContext:
        """Compile context with memories automatically pulled and compacted."""
        memory_budget = self._allocate_memory_budget(
            total_budget=budget,
            artifact_count=len(artifacts),
        )

        memories = await self.provide_memories_for_compiler(
            query=memory_query,
            token_budget=memory_budget,
        )

        return await self._compiler.compile(
            artifacts=artifacts,
            memories=memories,
            budget=budget,
            priorities=priorities,
        )

    async def _provide_via_tiered(
        self,
        *,
        query: MemoryQuery,
        token_budget: int,
    ) -> tuple[ContextSource, ...]:
        """Progressive retrieval via TieredMemoryStore.

        Uses tier-aware retrieval so lower-ranked items load at cheaper L1/L0
        abstracts rather than full content — breadth without full-fidelity cost.
        """
        assert self._tiered_store is not None
        compacted = await self._tiered_store.progressive_search_compacted(query=query)
        if not compacted:
            return ()

        # Pack the already-tier-compacted items into the budget.
        sources: list[ContextSource] = []
        remaining = token_budget
        for cm in compacted:
            cost = cm.compacted_token_count or 0
            if cost > remaining:
                continue
            sources.append(cm.to_context_source())
            remaining -= cost
        return tuple(sources)

    async def _provide_via_flat(
        self,
        *,
        query: MemoryQuery,
        token_budget: int,
    ) -> tuple[ContextSource, ...]:
        """Flat retrieval via MemoryManager.recall()."""
        results = await self._memory_manager.recall(query=query)
        if not results:
            return ()

        items = tuple(r.item for r in results)
        compacted = await self._compactor.compact_batch_to_budget(
            items=items,
            token_budget=token_budget,
        )
        return tuple(cm.to_context_source() for cm in compacted)

    def _allocate_memory_budget(
        self,
        *,
        total_budget: TokenBudget,
        artifact_count: int,
    ) -> int:
        """Allocate a portion of the token budget to memories."""
        available = total_budget.available_tokens
        section_budget = total_budget.get_section_budget(section="memory")
        if section_budget > 0:
            return section_budget
        return int(available * 0.3)
