"""Memory deduplication — detect and resolve near-duplicate memory items."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from cemaf.core.types import Confidence
from cemaf.memory.base import MemoryItem
from cemaf.memory.semantic import MemoryQuery, MemorySearchResult, SemanticMemoryStore


class MatchType(str, Enum):
    """How a duplicate was detected."""

    EXACT_KEY = "exact_key"
    SEMANTIC = "semantic"
    PARTIAL_KEY = "partial_key"


class DeduplicationAction(str, Enum):
    """What to do with a candidate after dedup check."""

    STORE_NEW = "store_new"
    SKIP = "skip"
    MERGE = "merge"


@dataclass(frozen=True)
class DuplicateMatch:
    """A detected duplicate of a candidate item."""

    existing: MemoryItem
    similarity: float
    match_type: MatchType


@dataclass(frozen=True)
class DeduplicationResult:
    """Outcome of deduplication resolution."""

    action: DeduplicationAction
    item: MemoryItem
    skipped: bool
    merged_from: tuple[str, ...] = ()


@runtime_checkable
class MemoryDeduplicator(Protocol):
    """Protocol for memory deduplication strategies."""

    async def find_duplicates(
        self,
        candidate: MemoryItem,
        *,
        threshold: float = 0.85,
    ) -> tuple[DuplicateMatch, ...]: ...

    async def resolve(
        self,
        candidate: MemoryItem,
        matches: tuple[DuplicateMatch, ...],
    ) -> DeduplicationResult: ...


class SemanticDeduplicator:
    """Uses embedding similarity to detect near-duplicates."""

    def __init__(
        self,
        *,
        semantic_store: SemanticMemoryStore,
        similarity_threshold: float = 0.85,
    ) -> None:
        self._store = semantic_store
        self._threshold = similarity_threshold

    async def find_duplicates(
        self,
        candidate: MemoryItem,
        *,
        threshold: float = 0.85,
    ) -> tuple[DuplicateMatch, ...]:
        """Find duplicates via exact key check, then semantic search in same scope."""
        effective_threshold = min(threshold, self._threshold)
        matches: list[DuplicateMatch] = []

        # 1. Exact key match
        existing = await self._store.get(scope=candidate.scope, key=candidate.key)
        if existing is not None:
            matches.append(
                DuplicateMatch(
                    existing=existing,
                    similarity=1.0,
                    match_type=MatchType.EXACT_KEY,
                )
            )
            return tuple(matches)

        # 2. Semantic search in same scope
        import json

        embed_text = f"{candidate.key}: {json.dumps(candidate.value, default=str)}"
        results: tuple[MemorySearchResult, ...] = await self._store.search(
            query=MemoryQuery(
                text=embed_text,
                scope=candidate.scope,
                limit=5,
            ),
        )

        for result in results:
            if result.similarity >= effective_threshold:
                matches.append(
                    DuplicateMatch(
                        existing=result.item,
                        similarity=result.similarity,
                        match_type=MatchType.SEMANTIC,
                    )
                )

        return tuple(matches)

    async def resolve(
        self,
        candidate: MemoryItem,
        matches: tuple[DuplicateMatch, ...],
    ) -> DeduplicationResult:
        """Resolve duplicates: no matches → STORE_NEW; exact key → MERGE; semantic → confidence-based."""
        if not matches:
            return DeduplicationResult(
                action=DeduplicationAction.STORE_NEW,
                item=candidate,
                skipped=False,
            )

        best_match = max(matches, key=lambda m: m.similarity)

        if best_match.match_type == MatchType.EXACT_KEY:
            # Exact key: merge, keeping higher confidence
            merged = self._merge_items(candidate=candidate, existing=best_match.existing)
            return DeduplicationResult(
                action=DeduplicationAction.MERGE,
                item=merged,
                skipped=False,
                merged_from=(best_match.existing.full_key,),
            )

        # Semantic match: skip if existing has higher confidence, else merge
        if float(best_match.existing.confidence) >= float(candidate.confidence):
            return DeduplicationResult(
                action=DeduplicationAction.SKIP,
                item=candidate,
                skipped=True,
            )

        merged = self._merge_items(candidate=candidate, existing=best_match.existing)
        return DeduplicationResult(
            action=DeduplicationAction.MERGE,
            item=merged,
            skipped=False,
            merged_from=(best_match.existing.full_key,),
        )

    @staticmethod
    def _merge_items(*, candidate: MemoryItem, existing: MemoryItem) -> MemoryItem:
        """Merge two items, keeping the higher-confidence value."""
        if float(candidate.confidence) >= float(existing.confidence):
            return candidate
        return existing.with_update(
            value=existing.value,
            confidence=Confidence(max(float(candidate.confidence), float(existing.confidence))),
        )
