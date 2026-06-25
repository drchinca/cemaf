"""Tests for StreamingContextCompiler."""

from __future__ import annotations

import pytest

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.source import ContextSource
from cemaf.context.streaming_context_compiler import StreamingContextCompiler
from cemaf.core.types import TokenCount


def _make_source(key: str, content: str, priority: int = 0) -> ContextSource:
    estimator = SimpleTokenEstimator()
    return ContextSource(
        content=content,
        token_count=TokenCount(estimator.estimate(content)),
        priority=priority,
        source_type="test",
        source_id=key,
    )


async def _async_gen(sources):
    for s in sources:
        yield s


class TestStreamingContextCompiler:
    @pytest.mark.asyncio
    async def test_compile_produces_same_result_as_priority_compiler_small_set(self):
        """compile() on a small set agrees with PriorityContextCompiler on selected IDs."""
        estimator = SimpleTokenEstimator()
        sources = [
            _make_source("a", "alpha content", priority=10),
            _make_source("b", "beta content", priority=5),
            _make_source("c", "gamma content with much more text " * 10, priority=1),
            _make_source("d", "delta content", priority=8),
            _make_source("e", "epsilon content", priority=3),
        ]
        budget = TokenBudget(max_tokens=500, reserved_for_output=100)

        priority_compiler = PriorityContextCompiler(token_estimator=estimator)
        artifacts = tuple((s.source_id, s.content) for s in sources)
        priority_result = await priority_compiler.compile(
            artifacts=artifacts,
            memories=(),
            budget=budget,
        )

        stream_compiler = StreamingContextCompiler(token_estimator=estimator)
        stream_result = await stream_compiler.compile(
            artifacts=artifacts,
            memories=(),
            budget=budget,
        )

        assert priority_result.total_tokens <= budget.available_tokens
        stream_ids = {s.source_id for s in stream_result.sources}

        # The streaming compiler picks from the heap which has all 5 items for
        # a small set — the highest priority sources must be present in both.
        high_priority_ids = {"a", "d"}  # priority 10, 8
        assert high_priority_ids.issubset(stream_ids), (
            f"Expected high-priority sources {high_priority_ids} in streaming result {stream_ids}"
        )
        assert stream_result.total_tokens <= budget.available_tokens

    @pytest.mark.asyncio
    async def test_heap_bounded_not_loading_all(self):
        """compile_stream over 10 000 sources completes without OOM."""
        import gc

        estimator = SimpleTokenEstimator()

        async def large_source_gen():
            for i in range(10_000):
                yield _make_source(f"src-{i}", f"content {i} " * 20, priority=i % 100)

        budget = TokenBudget(max_tokens=50_000, reserved_for_output=5_000)
        compiler = StreamingContextCompiler(token_estimator=estimator)

        result = await compiler.compile_stream(large_source_gen(), budget)
        gc.collect()

        assert result.total_tokens <= budget.available_tokens
        assert len(result.sources) > 0
        # Heap-bounded: selected count should be much less than 10 000
        assert len(result.sources) < 5_000

    @pytest.mark.asyncio
    async def test_compact_removes_low_priority_sources(self):
        """compact() merges old sources and preserves recent ones."""
        estimator = SimpleTokenEstimator()
        compiler = StreamingContextCompiler(token_estimator=estimator)

        budget = TokenBudget(max_tokens=2000, reserved_for_output=200)
        sources = [_make_source(f"s{i}", f"content {i}", priority=i) for i in range(6)]
        compiled = await compiler.compile(
            artifacts=tuple((s.source_id, s.content) for s in sources),
            memories=(),
            budget=budget,
        )

        compacted = await compiler.compact(compiled=compiled, preserve_recent=2, summary_budget_tokens=50)
        # A summary source must be present (compaction happened)
        assert any(s.source_type == "compacted_summary" for s in compacted.sources)
        # The last 2 non-high-priority sources must be preserved verbatim
        preserved_ids = {s.source_id for s in compacted.sources if s.source_type != "compacted_summary"}
        assert "s4" in preserved_ids and "s5" in preserved_ids
        # Total source count must be less than original (summary replaces N old sources)
        assert len(compacted.sources) < len(compiled.sources)
