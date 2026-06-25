"""Automatic post-session memory extraction — promote session learnings to long-term memory."""

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from cemaf.core.enums import MemoryScope
from cemaf.core.types import JSON
from cemaf.memory.base import MemoryItem
from cemaf.memory.episodic import Episode, EpisodicEvent


class ExtractionCategory(StrEnum):
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
    content_for_embedding: str | None = None
    source_events: tuple[str, ...] = ()


@dataclass
class PrefixedMemoryEmitter:
    """Helper for building keyed extracted memories with shared metadata."""

    key_prefix: str
    base_fields: dict[str, Any] = field(default_factory=dict)

    def make_key(self, *, kind: str, signal: str) -> str:
        """Build a stable memory key under the configured prefix."""

        return f"{self.key_prefix}:{kind}:{signal}"

    def make_value(
        self,
        *,
        kind: str,
        signal: str,
        summary: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a structured value payload with shared fields."""

        payload = {
            **self.base_fields,
            "kind": kind,
            "signal": signal,
            "summary": summary,
        }
        if extra:
            payload.update(extra)
        return payload

    def emit(
        self,
        *,
        seen: set[str],
        kind: str,
        signal: str,
        summary: str,
        confidence: float,
        category: ExtractionCategory,
        target_scope: MemoryScope = MemoryScope.PROJECT,
        extra: dict[str, Any] | None = None,
        content_for_embedding: str | None = None,
        source_events: tuple[str, ...] = (),
    ) -> ExtractedMemory | None:
        """Create an extracted memory unless the key has already been emitted."""

        key = self.make_key(kind=kind, signal=signal)
        if key in seen:
            return None
        seen.add(key)
        value = self.make_value(kind=kind, signal=signal, summary=summary, extra=extra)
        return ExtractedMemory(
            category=category,
            key=key,
            value=value,
            target_scope=target_scope,
            confidence=confidence,
            content_for_embedding=content_for_embedding or summary,
            source_events=source_events,
        )


def slug_memory_signal(value: str, *, max_length: int = 48) -> str:
    """Normalize free text into a short lowercase signal slug."""

    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned[:max_length] or "item"


def parse_structured_session_output(item: MemoryItem) -> tuple[str, dict[str, Any] | None]:
    """Extract an agent id plus parsed structured output from a session memory item."""

    if not isinstance(item.value, dict):
        return "", None
    agent_name = str(item.value.get("agent", "")).strip()
    raw_output = item.value.get("output")
    if isinstance(raw_output, dict):
        return agent_name, raw_output
    if not isinstance(raw_output, str) or not raw_output.strip():
        return agent_name, None
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        return agent_name, None
    return (agent_name, parsed) if isinstance(parsed, dict) else (agent_name, None)


def normalize_string_list(value: Any, *, limit: int = 3) -> list[str]:
    """Normalize a value into a compact list of non-empty strings."""

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:limit]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_mapping_values(value: Any, *, limit: int = 4) -> list[str]:
    """Normalize mapping values or string lists into a compact list of strings."""

    if isinstance(value, dict):
        return [str(item).strip() for item in value.values() if str(item).strip()][:limit]
    return normalize_string_list(value, limit=limit)


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
