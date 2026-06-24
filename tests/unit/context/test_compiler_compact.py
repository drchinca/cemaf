"""Tests for PriorityContextCompiler.compact() — partial context compaction."""

import pytest

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import CompiledContext, PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.source import ContextSource
from cemaf.core.types import TokenCount


def _source(
    source_id: str,
    content: str,
    priority: int = 0,
    tokens: int | None = None,
) -> ContextSource:
    """Helper to create a ContextSource with sensible defaults."""
    estimator = SimpleTokenEstimator()
    token_count = TokenCount(tokens) if tokens else TokenCount(estimator.estimate(text=content))
    return ContextSource(
        content=content,
        token_count=token_count,
        priority=priority,
        source_type="artifact",
        source_id=source_id,
    )


def _compiled(
    sources: list[ContextSource],
    budget_tokens: int = 10000,
) -> CompiledContext:
    """Helper to build a CompiledContext."""
    total = sum(s.token_count or 0 for s in sources)
    return CompiledContext(
        sources=tuple(sources),
        total_tokens=total,
        budget=TokenBudget(max_tokens=budget_tokens),
    )


@pytest.fixture
def compiler() -> PriorityContextCompiler:
    return PriorityContextCompiler(token_estimator=SimpleTokenEstimator())


async def _shrink(_text: str) -> str:
    """A real (tiny) summarizer so compaction genuinely reduces tokens.

    Without a summarizer, compact()'s truncation fallback only shrinks content
    above ~2000 chars; below that it returns the combined text verbatim, which
    the [type:id] framing makes LARGER — correctly triggering the never-grow
    no-op guard. Tests that verify summary *mechanics* must supply a summarizer
    so the summary path actually runs.
    """
    return "S"


class TestCompactPreserveRecent:
    """compact() preserves the N most recent (by position) sources."""

    @pytest.mark.asyncio
    async def test_preserves_last_n_sources(self, compiler: PriorityContextCompiler) -> None:
        sources = [
            _source("old1", "old content one", priority=10),
            _source("old2", "old content two", priority=10),
            _source("recent1", "recent content one", priority=10),
            _source("recent2", "recent content two", priority=10),
        ]
        ctx = _compiled(sources)

        result = await compiler.compact(compiled=ctx, preserve_recent=2, summarizer=_shrink)

        # recent1 and recent2 should be preserved, old1+old2 compacted into summary
        source_ids = [s.source_id for s in result.sources]
        assert "recent1" in source_ids
        assert "recent2" in source_ids
        assert "old1" not in source_ids
        assert "old2" not in source_ids

    @pytest.mark.asyncio
    async def test_no_compaction_when_few_sources(self, compiler: PriorityContextCompiler) -> None:
        sources = [
            _source("only1", "one source", priority=10),
            _source("only2", "two sources", priority=10),
        ]
        ctx = _compiled(sources)

        result = await compiler.compact(compiled=ctx, preserve_recent=2)

        # Should return original — nothing to compact
        assert result is ctx

    @pytest.mark.asyncio
    async def test_no_compaction_when_equal_to_preserve(self, compiler: PriorityContextCompiler) -> None:
        sources = [_source(f"s{i}", f"content {i}", priority=10) for i in range(3)]
        ctx = _compiled(sources)

        result = await compiler.compact(compiled=ctx, preserve_recent=3)

        assert result is ctx


class TestCompactHighPriorityPreservation:
    """Sources with priority >= 90 are always preserved regardless of position."""

    @pytest.mark.asyncio
    async def test_high_priority_always_preserved(self, compiler: PriorityContextCompiler) -> None:
        sources = [
            _source("system", "system prompt content", priority=100),
            _source("old1", "old stuff", priority=5),
            _source("old2", "more old stuff", priority=5),
            _source("recent", "recent stuff", priority=5),
        ]
        ctx = _compiled(sources)

        result = await compiler.compact(compiled=ctx, preserve_recent=1, summarizer=_shrink)

        source_ids = [s.source_id for s in result.sources]
        assert "system" in source_ids
        assert "recent" in source_ids
        # old1 and old2 should be compacted
        assert "old1" not in source_ids
        assert "old2" not in source_ids

    @pytest.mark.asyncio
    async def test_all_high_priority_no_compaction(self, compiler: PriorityContextCompiler) -> None:
        sources = [
            _source("sys1", "system one", priority=95),
            _source("sys2", "system two", priority=90),
            _source("recent", "recent stuff", priority=10),
        ]
        ctx = _compiled(sources)

        # Only 1 candidate (priority < 90), can't compact below preserve_recent=1
        result = await compiler.compact(compiled=ctx, preserve_recent=1)

        assert result is ctx


class TestCompactSummaryGeneration:
    """compact() produces a summary source from compacted content."""

    @pytest.mark.asyncio
    async def test_summary_source_created(self, compiler: PriorityContextCompiler) -> None:
        # Large content so the truncation fallback genuinely reduces tokens
        # (and preserves the head text), exercising the no-summarizer path while
        # still shrinking — not the never-grow no-op.
        sources = [
            _source("old1", "old content alpha " + "filler " * 400, priority=10),
            _source("old2", "old content beta " + "filler " * 400, priority=10),
            _source("old3", "old content gamma " + "filler " * 400, priority=10),
            _source("recent", "recent content", priority=10),
        ]
        ctx = _compiled(sources)

        result = await compiler.compact(compiled=ctx, preserve_recent=1, summary_budget_tokens=100)

        summary_sources = [s for s in result.sources if s.source_type == "compacted_summary"]
        assert len(summary_sources) == 1
        summary = summary_sources[0]
        assert summary.source_id == "compacted_context"
        assert summary.priority == 50
        assert "old content alpha" in summary.content

    @pytest.mark.asyncio
    async def test_summary_metadata_tracks_originals(self, compiler: PriorityContextCompiler) -> None:
        sources = [
            _source("a", "aaa", priority=10),
            _source("b", "bbb", priority=10),
            _source("c", "ccc", priority=10),
        ]
        ctx = _compiled(sources)

        result = await compiler.compact(compiled=ctx, preserve_recent=1, summarizer=_shrink)

        summary = [s for s in result.sources if s.source_type == "compacted_summary"][0]
        assert "a" in summary.metadata["compacted_from"]
        assert "b" in summary.metadata["compacted_from"]
        assert summary.metadata["original_source_count"] == 2

    @pytest.mark.asyncio
    async def test_compacted_metadata_on_result(self, compiler: PriorityContextCompiler) -> None:
        sources = [_source(f"s{i}", f"content {i}" * 20, priority=10) for i in range(5)]
        ctx = _compiled(sources)

        result = await compiler.compact(compiled=ctx, preserve_recent=2, summarizer=_shrink)

        assert result.metadata["compacted"] is True
        assert result.metadata["compacted_source_count"] == 3
        assert result.metadata["preserved_source_count"] == 2


class TestCompactWithSummarizer:
    """compact() uses a custom summarizer callback when provided."""

    @pytest.mark.asyncio
    async def test_summarizer_called(self, compiler: PriorityContextCompiler) -> None:
        sources = [
            _source("old", "verbose old content " * 50, priority=10),
            _source("recent", "recent content", priority=10),
        ]
        ctx = _compiled(sources)

        async def fake_summarizer(text: str) -> str:
            return "SUMMARIZED"

        result = await compiler.compact(
            compiled=ctx,
            preserve_recent=1,
            summarizer=fake_summarizer,
        )

        summary = [s for s in result.sources if s.source_type == "compacted_summary"][0]
        assert summary.content == "SUMMARIZED"


class TestCompactTruncationFallback:
    """Without a summarizer, compact() truncates to budget."""

    @pytest.mark.asyncio
    async def test_truncation_adds_marker(self, compiler: PriorityContextCompiler) -> None:
        # Create sources with lots of content
        big_content = "x" * 5000
        sources = [
            _source("big", big_content, priority=10),
            _source("recent", "recent", priority=10),
        ]
        ctx = _compiled(sources)

        result = await compiler.compact(
            compiled=ctx,
            preserve_recent=1,
            summary_budget_tokens=100,  # ~400 chars
        )

        summary = [s for s in result.sources if s.source_type == "compacted_summary"][0]
        assert "[...truncated]" in summary.content

    @pytest.mark.asyncio
    async def test_no_truncation_when_within_budget(self, compiler: PriorityContextCompiler) -> None:
        sources = [
            _source("old1", "old content", priority=10),
            _source("old2", "more old content", priority=10),
            _source("recent", "recent", priority=10),
        ]
        ctx = _compiled(sources)

        result = await compiler.compact(
            compiled=ctx,
            preserve_recent=1,
            summary_budget_tokens=1000,
            summarizer=_shrink,
        )

        summary = [s for s in result.sources if s.source_type == "compacted_summary"][0]
        assert "[...truncated]" not in summary.content


class TestCompactTokenAccounting:
    """compact() correctly recalculates total_tokens."""

    @pytest.mark.asyncio
    async def test_total_tokens_recalculated(self, compiler: PriorityContextCompiler) -> None:
        sources = [
            _source("old1", "old content one", priority=10, tokens=100),
            _source("old2", "old content two", priority=10, tokens=100),
            _source("recent", "recent", priority=10, tokens=50),
        ]
        ctx = _compiled(sources)
        assert ctx.total_tokens == 250

        result = await compiler.compact(compiled=ctx, preserve_recent=1)

        # Compaction must shrink (large sources → smaller summary), never grow.
        assert result.total_tokens > 0
        assert result.total_tokens < ctx.total_tokens


class TestCompactNeverGrows:
    """Invariant: compaction must never emit more tokens than the input."""

    @pytest.mark.asyncio
    async def test_small_sources_compaction_is_noop_not_growth(
        self, compiler: PriorityContextCompiler
    ) -> None:
        """With tiny sources, the [type:id] framing would cost more than it saves;
        compaction must return the original unchanged, never a larger context."""
        sources = [_source(f"s{i}", f"fact {i}", priority=10) for i in range(5)]
        ctx = _compiled(sources)

        result = await compiler.compact(compiled=ctx, preserve_recent=2)

        # The bug was emitting MORE tokens here. Never larger than the input.
        assert result.total_tokens <= ctx.total_tokens

    @pytest.mark.asyncio
    async def test_output_never_exceeds_input_for_any_size(self, compiler: PriorityContextCompiler) -> None:
        """Property: across mixed source sizes, compacted tokens <= input tokens."""
        for size in (5, 20, 100, 500):
            sources = [_source(f"s{i}", "x" * size, priority=10) for i in range(6)]
            ctx = _compiled(sources)
            result = await compiler.compact(compiled=ctx, preserve_recent=2)
            assert result.total_tokens <= ctx.total_tokens, f"grew at size={size}"
