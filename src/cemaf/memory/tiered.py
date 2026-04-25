"""Three-tier progressive memory loading (L0/L1/L2)."""

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from cemaf.memory.base import MemoryItem
from cemaf.memory.compaction import CompactedMemory, CompactionLevel, SimpleTokenEstimator


class LoadingTier(StrEnum):
    """Progressive loading tiers for memory items."""

    L0 = "l0"  # ~100 tokens: one-sentence abstract
    L1 = "l1"  # ~2K tokens: overview for planning
    L2 = "l2"  # Full content


@dataclass(frozen=True)
class TieredMemoryItem:
    """A memory item with pre-computed tier abstracts."""

    item: MemoryItem
    l0_abstract: str
    l0_token_count: int
    l1_overview: str
    l1_token_count: int
    l2_token_count: int

    def content_at_tier(self, tier: LoadingTier) -> str:
        """Return content at the requested tier."""
        if tier == LoadingTier.L0:
            return self.l0_abstract
        if tier == LoadingTier.L1:
            return self.l1_overview
        return json.dumps(self.item.value, default=str)

    def to_compacted(self, tier: LoadingTier) -> CompactedMemory:
        """Bridge to CompactedMemory at the given tier."""
        if tier == LoadingTier.L0:
            return CompactedMemory(
                item=self.item,
                level=CompactionLevel.METADATA_ONLY,
                original_token_count=self.l2_token_count,
                compacted_token_count=self.l0_token_count,
                summary=self.l0_abstract,
            )
        if tier == LoadingTier.L1:
            return CompactedMemory(
                item=self.item,
                level=CompactionLevel.SUMMARY,
                original_token_count=self.l2_token_count,
                compacted_token_count=self.l1_token_count,
                summary=self.l1_overview,
            )
        return CompactedMemory(
            item=self.item,
            level=CompactionLevel.FULL,
            original_token_count=self.l2_token_count,
            compacted_token_count=self.l2_token_count,
        )


@runtime_checkable
class TierGenerator(Protocol):
    """Protocol for generating tiered abstracts from memory items."""

    async def generate_tiers(self, item: MemoryItem) -> TieredMemoryItem: ...


class TruncationTierGenerator:
    """No-LLM tier generator using truncation heuristics."""

    def __init__(
        self,
        *,
        token_estimator: SimpleTokenEstimator | None = None,
        l0_max_chars: int = 400,
        l1_max_chars: int = 8000,
    ) -> None:
        self._estimator = token_estimator or SimpleTokenEstimator()
        self._l0_max_chars = l0_max_chars
        self._l1_max_chars = l1_max_chars

    async def generate_tiers(self, item: MemoryItem) -> TieredMemoryItem:
        """Generate L0/L1/L2 tiers via truncation."""
        full_text = json.dumps(item.value, default=str)
        l2_tokens = self._estimator.estimate(text=full_text)

        # L0: key + first sentence, truncated
        l0_text = self._generate_l0(key=item.key, full_text=full_text)
        l0_tokens = self._estimator.estimate(text=l0_text)

        # L1: truncated overview
        l1_text = self._generate_l1(full_text=full_text)
        l1_tokens = self._estimator.estimate(text=l1_text)

        return TieredMemoryItem(
            item=item,
            l0_abstract=l0_text,
            l0_token_count=l0_tokens,
            l1_overview=l1_text,
            l1_token_count=l1_tokens,
            l2_token_count=l2_tokens,
        )

    def _generate_l0(self, *, key: str, full_text: str) -> str:
        """Generate L0 abstract: key + first sentence."""
        first_sentence = full_text.split(".")[0] if "." in full_text else full_text
        abstract = f"{key}: {first_sentence}"
        if len(abstract) > self._l0_max_chars:
            return abstract[: self._l0_max_chars - 3] + "..."
        return abstract

    def _generate_l1(self, *, full_text: str) -> str:
        """Generate L1 overview: truncated to l1_max_chars."""
        if len(full_text) <= self._l1_max_chars:
            return full_text
        return full_text[: self._l1_max_chars - 3] + "..."
