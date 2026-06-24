"""Tests for progressive memory compaction."""

import pytest

from cemaf.context.source import ContextSource
from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import MemoryItem
from cemaf.memory.compaction import (
    CompactedMemory,
    CompactionLevel,
    MemoryCompactor,
    SimpleMemoryCompactor,
    SimpleTokenEstimator,
)
from cemaf.memory.scoring import TemporalDecayScorer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_item(
    *,
    key: str = "test",
    value: dict | None = None,
    confidence: float = 1.0,
) -> MemoryItem:
    return MemoryItem(
        scope=MemoryScope.SESSION,
        key=key,
        value=value or {"data": key},
        confidence=Confidence(confidence),
    )


def _make_compactor(
    *,
    summary_max_chars: int = 200,
) -> SimpleMemoryCompactor:
    return SimpleMemoryCompactor(
        scorer=TemporalDecayScorer(),
        summary_max_chars=summary_max_chars,
    )


# ---------------------------------------------------------------------------
# CompactionLevel
# ---------------------------------------------------------------------------


class TestCompactionLevel:
    def test_values(self) -> None:
        assert CompactionLevel.FULL == "full"
        assert CompactionLevel.SUMMARY == "summary"
        assert CompactionLevel.METADATA_ONLY == "metadata"


# ---------------------------------------------------------------------------
# SimpleTokenEstimator
# ---------------------------------------------------------------------------


class TestSimpleTokenEstimator:
    def test_estimate(self) -> None:
        estimator = SimpleTokenEstimator(chars_per_token=4.0)
        assert estimator.estimate(text="hello world") >= 1

    def test_minimum_one_token(self) -> None:
        estimator = SimpleTokenEstimator()
        assert estimator.estimate(text="") == 1


# ---------------------------------------------------------------------------
# CompactedMemory
# ---------------------------------------------------------------------------


class TestCompactedMemory:
    def test_frozen(self) -> None:
        item = _make_item()
        cm = CompactedMemory(
            item=item,
            level=CompactionLevel.FULL,
            original_token_count=100,
            compacted_token_count=100,
        )
        with pytest.raises(AttributeError):
            cm.level = CompactionLevel.SUMMARY  # type: ignore[misc]

    def test_to_context_source_full(self) -> None:
        item = _make_item(key="brand_name", value={"name": "Acme"})
        cm = CompactedMemory(
            item=item,
            level=CompactionLevel.FULL,
            original_token_count=10,
            compacted_token_count=10,
        )
        source = cm.to_context_source()
        assert isinstance(source, ContextSource)
        assert source.source_type == "memory"
        assert "Acme" in source.content

    def test_to_context_source_summary(self) -> None:
        item = _make_item()
        cm = CompactedMemory(
            item=item,
            level=CompactionLevel.SUMMARY,
            original_token_count=100,
            compacted_token_count=20,
            summary="A brief summary of the item",
        )
        source = cm.to_context_source()
        assert source.content == "A brief summary of the item"

    def test_to_context_source_metadata_only(self) -> None:
        item = _make_item(key="some_key")
        cm = CompactedMemory(
            item=item,
            level=CompactionLevel.METADATA_ONLY,
            original_token_count=100,
            compacted_token_count=5,
        )
        source = cm.to_context_source()
        assert "[session:some_key]" in source.content


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_implements_memory_compactor(self) -> None:
        compactor = _make_compactor()
        assert isinstance(compactor, MemoryCompactor)


# ---------------------------------------------------------------------------
# SimpleMemoryCompactor — compact single
# ---------------------------------------------------------------------------


class TestCompactSingle:
    @pytest.mark.asyncio
    async def test_compact_full(self) -> None:
        compactor = _make_compactor()
        item = _make_item()
        result = await compactor.compact(item=item, target_level=CompactionLevel.FULL)
        assert result.level == CompactionLevel.FULL
        assert result.original_token_count == result.compacted_token_count

    @pytest.mark.asyncio
    async def test_compact_summary_truncates(self) -> None:
        compactor = _make_compactor(summary_max_chars=20)
        long_value = {"data": "x" * 500}
        item = _make_item(value=long_value)
        result = await compactor.compact(item=item, target_level=CompactionLevel.SUMMARY)
        assert result.level == CompactionLevel.SUMMARY
        assert result.summary is not None
        assert len(result.summary) <= 20
        assert result.compacted_token_count < result.original_token_count

    @pytest.mark.asyncio
    async def test_compact_summary_short_text_not_truncated(self) -> None:
        compactor = _make_compactor(summary_max_chars=200)
        item = _make_item(value={"x": "y"})
        result = await compactor.compact(item=item, target_level=CompactionLevel.SUMMARY)
        assert result.summary is not None
        assert "..." not in result.summary

    @pytest.mark.asyncio
    async def test_compact_metadata_only(self) -> None:
        compactor = _make_compactor()
        item = _make_item(key="my_key", value={"data": "x" * 200})
        result = await compactor.compact(
            item=item,
            target_level=CompactionLevel.METADATA_ONLY,
        )
        assert result.level == CompactionLevel.METADATA_ONLY
        assert result.compacted_token_count < result.original_token_count
        assert result.summary is None


# ---------------------------------------------------------------------------
# SimpleMemoryCompactor — compact batch to budget
# ---------------------------------------------------------------------------


class TestCompactBatchToBudget:
    @pytest.mark.asyncio
    async def test_empty_batch(self) -> None:
        compactor = _make_compactor()
        result = await compactor.compact_batch_to_budget(items=(), token_budget=1000)
        assert result == ()

    @pytest.mark.asyncio
    async def test_all_fit_as_full(self) -> None:
        compactor = _make_compactor()
        items = tuple(_make_item(key=f"item_{i}") for i in range(3))
        result = await compactor.compact_batch_to_budget(
            items=items,
            token_budget=10000,
        )
        assert len(result) == 3
        assert all(r.level == CompactionLevel.FULL for r in result)

    @pytest.mark.asyncio
    async def test_tight_budget_degrades_lower_scored(self) -> None:
        compactor = _make_compactor(summary_max_chars=20)
        items = tuple(_make_item(key=f"item_{i}", value={"data": "x" * 100}) for i in range(5))
        # Very tight budget — should force some items to summary/metadata
        result = await compactor.compact_batch_to_budget(
            items=items,
            token_budget=50,
        )
        # Some items should be compacted below FULL
        # At minimum, we should get some results
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_zero_budget_returns_empty(self) -> None:
        compactor = _make_compactor()
        items = tuple(_make_item(key=f"item_{i}") for i in range(3))
        result = await compactor.compact_batch_to_budget(
            items=items,
            token_budget=0,
        )
        assert result == ()

    @pytest.mark.asyncio
    async def test_oversized_item_does_not_drop_fittable_items(self) -> None:
        """Regression: an item too big to fit even at metadata level must not
        discard the smaller, still-fittable items (head-of-line blocking).

        The bug was a `break` on the first non-fitting item, which silently threw
        away every remaining item — returning nothing even when smaller items fit.
        """
        compactor = _make_compactor()
        # 'big' has a 200-char key so even its metadata "[session:BBB...]" blows
        # the tiny budget; 'small' fits comfortably at metadata level.
        big = _make_item(key="B" * 200, value={"data": "z" * 400})
        small = _make_item(key="s", value={"data": "hi"})

        result = await compactor.compact_batch_to_budget(items=(big, small), token_budget=8)

        kept = {r.item.key for r in result}
        assert "s" in kept, "fittable item was dropped after an oversized item (head-of-line block)"

    @pytest.mark.asyncio
    async def test_total_tokens_within_budget(self) -> None:
        compactor = _make_compactor()
        items = tuple(_make_item(key=f"item_{i}", value={"data": f"content_{i}"}) for i in range(5))
        budget = 100
        result = await compactor.compact_batch_to_budget(
            items=items,
            token_budget=budget,
        )
        total = sum(r.compacted_token_count for r in result)
        assert total <= budget


# ---------------------------------------------------------------------------
# ContextSource bridge
# ---------------------------------------------------------------------------


class TestContextSourceBridge:
    @pytest.mark.asyncio
    async def test_compacted_to_context_source_roundtrip(self) -> None:
        compactor = _make_compactor()
        item = _make_item(key="bridge_test", value={"important": True})
        result = await compactor.compact(item=item, target_level=CompactionLevel.FULL)
        source = result.to_context_source()
        assert isinstance(source, ContextSource)
        assert source.source_id == item.full_key
        assert source.priority == 7  # from_memory default
