"""Progressive compaction — budget-aware memory degradation."""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from cemaf.context.source import ContextSource
from cemaf.core.types import TokenCount
from cemaf.memory.base import MemoryItem
from cemaf.memory.scoring import MemoryScorer


class CompactionLevel(str, Enum):
    """How aggressively a memory item has been compacted."""

    FULL = "full"
    SUMMARY = "summary"
    METADATA_ONLY = "metadata"


@dataclass(frozen=True)
class CompactedMemory:
    """A memory item after compaction."""

    item: MemoryItem
    level: CompactionLevel
    original_token_count: int
    compacted_token_count: int
    summary: str | None = None

    def to_context_source(self) -> ContextSource:
        """Bridge into the context compiler pipeline."""
        if self.level == CompactionLevel.FULL:
            content = json.dumps(self.item.value, default=str)
        elif self.level == CompactionLevel.SUMMARY and self.summary:
            content = self.summary
        else:
            content = f"[{self.item.scope.value}:{self.item.key}]"

        return ContextSource.from_memory(
            content=content,
            memory_key=self.item.full_key,
            token_count=TokenCount(self.compacted_token_count),
            timestamp=self.item.updated_at,
        )


@runtime_checkable
class MemoryCompactor(Protocol):
    """Compacts memory items to fit within token budgets."""

    async def compact(
        self,
        item: MemoryItem,
        *,
        target_level: CompactionLevel,
    ) -> CompactedMemory: ...

    async def compact_batch_to_budget(
        self,
        items: tuple[MemoryItem, ...],
        *,
        token_budget: int,
    ) -> tuple[CompactedMemory, ...]: ...


class SimpleTokenEstimator:
    """Estimate token count from text length."""

    def __init__(self, *, chars_per_token: float = 4.0) -> None:
        self._chars_per_token = chars_per_token

    def estimate(self, text: str) -> int:
        return max(1, int(len(text) / self._chars_per_token))


class SimpleMemoryCompactor:
    """Compactor using truncation (no LLM required)."""

    def __init__(
        self,
        *,
        scorer: MemoryScorer,
        token_estimator: SimpleTokenEstimator | None = None,
        summary_max_chars: int = 200,
    ) -> None:
        self._scorer = scorer
        self._estimator = token_estimator or SimpleTokenEstimator()
        self._summary_max_chars = summary_max_chars

    def _item_text(self, item: MemoryItem) -> str:
        return json.dumps(item.value, default=str)

    def _estimate(self, text: str) -> int:
        return self._estimator.estimate(text=text)

    async def compact(
        self,
        item: MemoryItem,
        *,
        target_level: CompactionLevel,
    ) -> CompactedMemory:
        """Compact a single item to the target level."""
        full_text = self._item_text(item=item)
        original_tokens = self._estimate(text=full_text)

        if target_level == CompactionLevel.FULL:
            return CompactedMemory(
                item=item,
                level=CompactionLevel.FULL,
                original_token_count=original_tokens,
                compacted_token_count=original_tokens,
            )

        if target_level == CompactionLevel.SUMMARY:
            summary = self._truncate_summary(text=full_text)
            compacted_tokens = self._estimate(text=summary)
            return CompactedMemory(
                item=item,
                level=CompactionLevel.SUMMARY,
                original_token_count=original_tokens,
                compacted_token_count=compacted_tokens,
                summary=summary,
            )

        # METADATA_ONLY
        meta_text = f"[{item.scope.value}:{item.key}]"
        compacted_tokens = self._estimate(text=meta_text)
        return CompactedMemory(
            item=item,
            level=CompactionLevel.METADATA_ONLY,
            original_token_count=original_tokens,
            compacted_token_count=compacted_tokens,
        )

    async def compact_batch_to_budget(
        self,
        items: tuple[MemoryItem, ...],
        *,
        token_budget: int,
    ) -> tuple[CompactedMemory, ...]:
        """Compact items to fit within budget, highest-scored items kept fullest."""
        if not items:
            return ()

        scored = self._scorer.score_batch(items=items)
        ordered_items = [s.item for s in scored]

        results: list[CompactedMemory] = []
        remaining_budget = token_budget

        for item in ordered_items:
            full_text = self._item_text(item=item)
            full_tokens = self._estimate(text=full_text)

            if full_tokens <= remaining_budget:
                compacted = await self.compact(
                    item=item,
                    target_level=CompactionLevel.FULL,
                )
                results.append(compacted)
                remaining_budget -= compacted.compacted_token_count
                continue

            # Try summary
            summary = self._truncate_summary(text=full_text)
            summary_tokens = self._estimate(text=summary)
            if summary_tokens <= remaining_budget:
                compacted = await self.compact(
                    item=item,
                    target_level=CompactionLevel.SUMMARY,
                )
                results.append(compacted)
                remaining_budget -= compacted.compacted_token_count
                continue

            # Try metadata only
            meta_text = f"[{item.scope.value}:{item.key}]"
            meta_tokens = self._estimate(text=meta_text)
            if meta_tokens <= remaining_budget:
                compacted = await self.compact(
                    item=item,
                    target_level=CompactionLevel.METADATA_ONLY,
                )
                results.append(compacted)
                remaining_budget -= compacted.compacted_token_count
                continue

            # Doesn't fit at all — skip
            break

        return tuple(results)

    def _truncate_summary(self, text: str) -> str:
        """Truncate text to summary length."""
        if len(text) <= self._summary_max_chars:
            return text
        return text[: self._summary_max_chars - 3] + "..."
