"""Unit tests for post-session memory extraction."""

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.types import Confidence
from cemaf.core.utils import utc_now
from cemaf.memory.base import MemoryItem
from cemaf.memory.episodic import EpisodicEvent
from cemaf.memory.extraction import (
    ExtractionCategory,
    MemoryExtractor,
    RuleBasedExtractor,
)


class TestRuleBasedExtractorProtocol:
    def test_satisfies_protocol(self) -> None:
        extractor = RuleBasedExtractor()
        assert isinstance(extractor, MemoryExtractor)


class TestHighConfidenceExtraction:
    """Contract: high-confidence SESSION items get promoted."""

    @pytest.mark.asyncio
    async def test_promotes_high_confidence_session_items(self) -> None:
        """SESSION item confidence=0.9 → extracted with target_scope=PROJECT."""
        extractor = RuleBasedExtractor(min_confidence=0.6)

        session_memories = (
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="learned-fact",
                value={"fact": "important"},
                confidence=Confidence(0.9),
            ),
        )

        results = await extractor.extract(
            session_memories=session_memories,
            episodes=(),
            recent_events=(),
        )

        assert len(results) >= 1
        promoted = [r for r in results if r.category == ExtractionCategory.FACT]
        assert len(promoted) == 1
        assert promoted[0].target_scope == MemoryScope.PROJECT
        assert promoted[0].confidence == 0.9

    @pytest.mark.asyncio
    async def test_skips_low_confidence_items(self) -> None:
        """SESSION item confidence=0.3 (below threshold) → not extracted."""
        extractor = RuleBasedExtractor(min_confidence=0.6)

        session_memories = (
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="uncertain",
                value={"maybe": True},
                confidence=Confidence(0.3),
            ),
        )

        results = await extractor.extract(
            session_memories=session_memories,
            episodes=(),
            recent_events=(),
        )

        facts = [r for r in results if r.category == ExtractionCategory.FACT]
        assert len(facts) == 0

    @pytest.mark.asyncio
    async def test_skips_non_session_items(self) -> None:
        """PROJECT items should not be re-promoted."""
        extractor = RuleBasedExtractor(min_confidence=0.6)

        session_memories = (
            MemoryItem(
                scope=MemoryScope.PROJECT,
                key="existing",
                value={"v": 1},
                confidence=Confidence(0.9),
            ),
        )

        results = await extractor.extract(
            session_memories=session_memories,
            episodes=(),
            recent_events=(),
        )

        facts = [r for r in results if r.category == ExtractionCategory.FACT]
        assert len(facts) == 0


class TestPatternExtraction:
    """Contract: repeated actions get extracted as patterns."""

    @pytest.mark.asyncio
    async def test_extracts_repeated_patterns(self) -> None:
        """Same action 3+ times → PATTERN extraction."""
        extractor = RuleBasedExtractor()

        events = tuple(
            EpisodicEvent(
                timestamp=utc_now(),
                event_type="tool.call",
                actor="agent",
                action="search_documents",
                content={},
            )
            for _ in range(4)
        )

        results = await extractor.extract(
            session_memories=(),
            episodes=(),
            recent_events=events,
        )

        patterns = [r for r in results if r.category == ExtractionCategory.PATTERN]
        assert len(patterns) == 1
        assert patterns[0].value["action"] == "search_documents"
        assert patterns[0].value["count"] == 4


class TestCorrectionExtraction:
    """Contract: error events get extracted as corrections."""

    @pytest.mark.asyncio
    async def test_extracts_high_importance_errors(self) -> None:
        """Error event with high importance → CORRECTION extraction."""
        extractor = RuleBasedExtractor(min_event_importance=0.7)

        events = (
            EpisodicEvent(
                timestamp=utc_now(),
                event_type="task.failed",
                actor="agent",
                action="generate_report",
                content={"error": "timeout"},
                importance=0.9,
            ),
        )

        results = await extractor.extract(
            session_memories=(),
            episodes=(),
            recent_events=events,
        )

        corrections = [r for r in results if r.category == ExtractionCategory.CORRECTION]
        assert len(corrections) == 1
        assert corrections[0].source_events == ("task.failed",)
