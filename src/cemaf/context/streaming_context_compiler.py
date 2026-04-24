"""
Streaming context compiler with bounded min-heap selection.

Replaces greedy full-materialization in PriorityContextCompiler with
an AsyncIterator[ContextSource] path. Memory = O(budget/avg_source_tokens)
instead of O(total_sources) — required for petabyte-scale recall.
"""

import heapq
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import CompiledContext, TokenEstimator
from cemaf.context.source import ContextSource
from cemaf.core.types import TokenCount
from cemaf.core.utils import utc_now

# Average source size used to bound the heap when no other guidance is available.
_DEFAULT_AVG_SOURCE_TOKENS = 200
_MIN_HEAP_SIZE = 8


@dataclass(frozen=True, slots=True)
class _HeapItem:
    """Sortable wrapper for the bounded min-heap.

    The heap is a min-heap on neg_priority so the item with the *lowest*
    priority sits at root — enabling O(log k) replacement when a higher-
    priority source arrives.
    """

    neg_priority: int  # -source.priority
    timestamp: datetime  # tiebreak: older = lower in heap (evicted first)
    source: ContextSource

    def __lt__(self, other: _HeapItem) -> bool:
        if self.neg_priority != other.neg_priority:
            return self.neg_priority < other.neg_priority
        # Earlier timestamp = lower priority when priorities tie
        return self.timestamp < other.timestamp

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _HeapItem):
            return NotImplemented
        return self.neg_priority == other.neg_priority and self.timestamp == other.timestamp


class StreamingContextCompiler:
    """
    Memory-bounded context compiler for massive source sets.

    The compile_stream() path processes ContextSource objects one at a time
    from an AsyncIterator, maintaining a bounded priority heap rather than
    materialising all sources into RAM.  compile() is the backward-compatible
    entry point for callers that already have all sources in memory.
    """

    def __init__(self, token_estimator: TokenEstimator) -> None:
        self._estimator = token_estimator

    async def compile(
        self,
        artifacts: tuple[tuple[str, str], ...],
        memories: tuple[tuple[str, str], ...],
        budget: TokenBudget,
        priorities: dict[str, int] | None = None,
    ) -> CompiledContext:
        """Backward-compatible compile — converts pairs to ContextSource then streams."""
        priorities = priorities or {}
        sources: list[ContextSource] = []

        for key, content in artifacts:
            tokens = self._estimator.estimate(content)
            sources.append(
                ContextSource(
                    content=content,
                    token_count=TokenCount(tokens),
                    priority=priorities.get(key, 0),
                    source_type="artifact",
                    source_id=key,
                )
            )
        for key, content in memories:
            tokens = self._estimator.estimate(content)
            sources.append(
                ContextSource(
                    content=content,
                    token_count=TokenCount(tokens),
                    priority=priorities.get(key, -1),
                    source_type="memory",
                    source_id=key,
                )
            )

        async def _gen() -> AsyncIterator[ContextSource]:
            for s in sources:
                yield s

        return await self.compile_stream(_gen(), budget)

    async def compile_stream(
        self,
        sources: AsyncIterator[ContextSource],
        budget: TokenBudget,
    ) -> CompiledContext:
        """
        Stream-oriented compilation with O(heap_size) peak memory.

        The heap capacity is bounded to avoid materialising the whole stream.
        After streaming, a greedy pass selects the top sources that fit within
        the token budget (highest priority first).
        """
        available = budget.available_tokens
        # Bound heap so it never grows beyond budget / avg_source_tokens.
        # Floor at _MIN_HEAP_SIZE so tiny budgets still accumulate something.
        heap_cap = max(_MIN_HEAP_SIZE, available // _DEFAULT_AVG_SOURCE_TOKENS)

        heap: list[_HeapItem] = []

        async for source in sources:
            item = _HeapItem(
                neg_priority=-source.priority,
                timestamp=source.timestamp,
                source=source,
            )
            if len(heap) < heap_cap:
                heapq.heappush(heap, item)
            else:
                # The root has the *lowest* priority in the heap.
                # Replace it only if the new item is strictly higher priority.
                if heap and item < heap[0]:
                    pass  # new item has even lower priority — skip
                elif heap:
                    heapq.heapreplace(heap, item)
                else:
                    heapq.heappush(heap, item)

        # Sort descending by priority for greedy selection.
        candidates = sorted(heap, key=lambda h: (-h.neg_priority, h.timestamp), reverse=False)
        candidates.sort(key=lambda h: h.neg_priority)  # ascending neg_priority = descending priority

        selected: list[ContextSource] = []
        total_tokens = 0

        for item in candidates:
            source = item.source
            # Ensure token_count is populated.
            src_tokens = (
                source.token_count
                if source.token_count is not None
                else self._estimator.estimate(source.content)
            )
            if total_tokens + src_tokens <= available:
                selected.append(source)
                total_tokens += src_tokens

        return CompiledContext(
            sources=tuple(selected),
            total_tokens=total_tokens,
            budget=budget,
            compiled_at=utc_now(),
            metadata={
                "compiler": "streaming",
                "heap_capacity": heap_cap,
                "selected_count": len(selected),
            },
        )

    async def compact(
        self,
        *,
        compiled: CompiledContext,
        preserve_recent: int = 2,
        summary_budget_tokens: int = 500,
        summarizer: Callable[[str], Coroutine[None, None, str]] | None = None,
    ) -> CompiledContext:
        """Compact old sources; identical policy to PriorityContextCompiler.compact()."""
        sources = list(compiled.sources)

        if len(sources) <= preserve_recent:
            return compiled

        high_priority_threshold = 90
        to_preserve: list[ContextSource] = []
        candidates: list[ContextSource] = []

        for source in sources:
            if source.priority >= high_priority_threshold:
                to_preserve.append(source)
            else:
                candidates.append(source)

        if len(candidates) <= preserve_recent:
            return compiled

        to_summarize = candidates[:-preserve_recent]
        to_preserve.extend(candidates[-preserve_recent:])

        combined_text = "\n\n".join(
            f"[{s.source_type}:{s.source_id}] {s.content}" for s in to_summarize
        )

        if summarizer is not None:
            summary_content = await summarizer(combined_text)
        else:
            char_budget = summary_budget_tokens * 4
            if len(combined_text) > char_budget:
                summary_content = combined_text[:char_budget] + "\n[...truncated]"
            else:
                summary_content = combined_text

        summary_tokens = self._estimator.estimate(summary_content)
        summary_source = ContextSource(
            content=summary_content,
            token_count=TokenCount(summary_tokens),
            priority=50,
            source_type="compacted_summary",
            source_id="compacted_context",
            compressible=True,
            metadata={
                "compacted_from": [s.source_id for s in to_summarize],
                "original_source_count": len(to_summarize),
            },
        )

        final_sources = [summary_source, *to_preserve]
        total_tokens = sum((s.token_count or 0) for s in final_sources)

        return CompiledContext(
            sources=tuple(final_sources),
            total_tokens=total_tokens,
            budget=compiled.budget,
            metadata={
                **compiled.metadata,
                "compacted": True,
                "compacted_source_count": len(to_summarize),
                "preserved_source_count": len(to_preserve),
            },
        )
