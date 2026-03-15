"""Automatic post-session memory extraction — promote session learnings to long-term memory."""

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON
from cemaf.memory.base import MemoryItem
from cemaf.memory.episodic import Episode, EpisodicEvent


class ExtractionCategory(str, Enum):
    """Category of extracted memory."""

    PREFERENCE = "preference"
    FACT = "fact"
    PROCEDURE = "procedure"
    CORRECTION = "correction"
    RELATIONSHIP = "relationship"
    CONSTRAINT = "constraint"
    PERFORMANCE = "performance"
    PATTERN = "pattern"


@dataclass(frozen=True)
class ExtractedMemory:
    """A memory extracted from session data for promotion to long-term storage."""

    category: ExtractionCategory
    key: str
    value: JSON
    target_scope: MemoryScope
    confidence: float
    source_events: tuple[str, ...] = ()


@runtime_checkable
class MemoryExtractor(Protocol):
    """Protocol for extracting memories from session data."""

    async def extract(
        self,
        *,
        session_memories: tuple[MemoryItem, ...],
        episodes: tuple[Episode, ...],
        recent_events: tuple[EpisodicEvent, ...],
    ) -> tuple[ExtractedMemory, ...]: ...


class RuleBasedExtractor:
    """Heuristic extraction without LLM dependency."""

    def __init__(
        self,
        *,
        min_confidence: float = 0.6,
        min_event_importance: float = 0.7,
    ) -> None:
        self._min_confidence = min_confidence
        self._min_event_importance = min_event_importance

    async def extract(
        self,
        *,
        session_memories: tuple[MemoryItem, ...],
        episodes: tuple[Episode, ...],
        recent_events: tuple[EpisodicEvent, ...],
    ) -> tuple[ExtractedMemory, ...]:
        """Extract memories using heuristic rules."""
        extracted: list[ExtractedMemory] = []

        # Rule 1: High-confidence SESSION items → promote to PROJECT
        extracted.extend(self._extract_high_confidence(session_memories=session_memories))

        # Rule 2: Repeated event patterns → PATTERN extraction
        extracted.extend(self._extract_patterns(recent_events=recent_events))

        # Rule 3: Error/correction events → CORRECTION extraction
        extracted.extend(self._extract_corrections(recent_events=recent_events))

        return tuple(extracted)

    def _extract_high_confidence(
        self,
        *,
        session_memories: tuple[MemoryItem, ...],
    ) -> list[ExtractedMemory]:
        """Promote high-confidence SESSION items to PROJECT scope."""
        results: list[ExtractedMemory] = []
        for item in session_memories:
            if item.scope == MemoryScope.SESSION and float(item.confidence) >= self._min_confidence:
                results.append(
                    ExtractedMemory(
                        category=ExtractionCategory.FACT,
                        key=f"promoted:{item.key}",
                        value=item.value,
                        target_scope=MemoryScope.PROJECT,
                        confidence=float(item.confidence),
                    )
                )
        return results

    def _extract_patterns(
        self,
        *,
        recent_events: tuple[EpisodicEvent, ...],
    ) -> list[ExtractedMemory]:
        """Detect repeated action patterns (same action 3+ times)."""
        action_counts: Counter[str] = Counter()
        for event in recent_events:
            action_counts[event.action] += 1

        results: list[ExtractedMemory] = []
        for action, count in action_counts.items():
            if count >= 3:
                results.append(
                    ExtractedMemory(
                        category=ExtractionCategory.PATTERN,
                        key=f"pattern:{action}",
                        value={"action": action, "count": count},
                        target_scope=MemoryScope.PROJECT,
                        confidence=min(1.0, count / 5.0),
                    )
                )
        return results

    def _extract_corrections(
        self,
        *,
        recent_events: tuple[EpisodicEvent, ...],
    ) -> list[ExtractedMemory]:
        """Extract error/correction events as lessons learned."""
        results: list[ExtractedMemory] = []
        for event in recent_events:
            if event.importance >= self._min_event_importance and event.event_type in (
                "error",
                "correction",
                "task.failed",
            ):
                results.append(
                    ExtractedMemory(
                        category=ExtractionCategory.CORRECTION,
                        key=f"correction:{event.action}",
                        value={"event_type": event.event_type, "content": event.content},
                        target_scope=MemoryScope.PROJECT,
                        confidence=event.importance,
                        source_events=(event.event_type,),
                    )
                )
        return results
