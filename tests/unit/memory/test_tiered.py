"""Unit tests for tiered progressive memory loading."""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.memory.base import MemoryItem
from cemaf.memory.compaction import CompactionLevel
from cemaf.memory.tiered import (
    LoadingTier,
    TierGenerator,
    TruncationTierGenerator,
)


def _make_item(*, key: str = "test-key", value_size: int = 100) -> MemoryItem:
    """Create a test memory item with variable-size content."""
    return MemoryItem(
        scope=MemoryScope.PROJECT,
        key=key,
        value={"content": "x" * value_size, "detail": "y" * value_size},
        confidence=Confidence(0.8),
    )


class TestTruncationTierGeneratorProtocol:
    def test_satisfies_protocol(self) -> None:
        gen = TruncationTierGenerator()
        assert isinstance(gen, TierGenerator)


class TestTierGeneration:
    """Contract tests for tier generation."""

    @pytest.mark.asyncio
    async def test_produces_all_tiers_with_ascending_tokens(self) -> None:
        """L0 < L1 < L2 in token count."""
        gen = TruncationTierGenerator(l0_max_chars=100, l1_max_chars=500)
        item = _make_item(value_size=2000)

        tiered = await gen.generate_tiers(item=item)

        assert tiered.l0_token_count > 0
        assert tiered.l1_token_count > 0
        assert tiered.l2_token_count > 0
        assert tiered.l0_token_count <= tiered.l1_token_count
        assert tiered.l1_token_count <= tiered.l2_token_count

    @pytest.mark.asyncio
    async def test_l0_contains_key(self) -> None:
        """L0 abstract includes the item key."""
        gen = TruncationTierGenerator()
        item = _make_item(key="brand-guidelines")

        tiered = await gen.generate_tiers(item=item)

        assert "brand-guidelines" in tiered.l0_abstract

    @pytest.mark.asyncio
    async def test_small_item_l1_equals_l2(self) -> None:
        """For small items, L1 and L2 have same content (no truncation needed)."""
        gen = TruncationTierGenerator(l0_max_chars=10000, l1_max_chars=20000)
        item = _make_item(value_size=10)

        tiered = await gen.generate_tiers(item=item)

        assert tiered.l1_token_count == tiered.l2_token_count


class TestTieredMemoryItemBridge:
    """Contract: to_compacted bridges correctly to CompactedMemory."""

    @pytest.mark.asyncio
    async def test_l0_to_compacted_is_metadata_only(self) -> None:
        gen = TruncationTierGenerator()
        item = _make_item(value_size=500)
        tiered = await gen.generate_tiers(item=item)

        compacted = tiered.to_compacted(tier=LoadingTier.L0)
        assert compacted.level == CompactionLevel.METADATA_ONLY

    @pytest.mark.asyncio
    async def test_l1_to_compacted_is_summary(self) -> None:
        gen = TruncationTierGenerator()
        item = _make_item(value_size=500)
        tiered = await gen.generate_tiers(item=item)

        compacted = tiered.to_compacted(tier=LoadingTier.L1)
        assert compacted.level == CompactionLevel.SUMMARY

    @pytest.mark.asyncio
    async def test_l2_to_compacted_is_full(self) -> None:
        gen = TruncationTierGenerator()
        item = _make_item(value_size=500)
        tiered = await gen.generate_tiers(item=item)

        compacted = tiered.to_compacted(tier=LoadingTier.L2)
        assert compacted.level == CompactionLevel.FULL

    @pytest.mark.asyncio
    async def test_content_at_tier_returns_correct_level(self) -> None:
        gen = TruncationTierGenerator(l0_max_chars=50, l1_max_chars=200)
        item = _make_item(value_size=500)
        tiered = await gen.generate_tiers(item=item)

        l0_content = tiered.content_at_tier(tier=LoadingTier.L0)
        l1_content = tiered.content_at_tier(tier=LoadingTier.L1)
        l2_content = tiered.content_at_tier(tier=LoadingTier.L2)

        assert len(l0_content) <= len(l1_content)
        assert len(l1_content) <= len(l2_content)
