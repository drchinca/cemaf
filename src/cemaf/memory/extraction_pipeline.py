"""Extraction pipeline — extract → deduplicate → store flow."""

from dataclasses import dataclass

from cemaf.core.types import Confidence
from cemaf.events.protocols import Event, EventBus, EventType
from cemaf.memory.base import MemoryItem
from cemaf.memory.deduplication import DeduplicationAction, MemoryDeduplicator
from cemaf.memory.episodic import Episode, EpisodicEvent
from cemaf.memory.extraction import ExtractedMemory, MemoryExtractor
from cemaf.memory.manager import MemoryManager


@dataclass(frozen=True)
class ExtractionReport:
    """Summary of extraction pipeline run."""

    extracted_count: int
    stored_count: int
    deduplicated_count: int
    skipped_count: int
    items: tuple[ExtractedMemory, ...] = ()


class ExtractionPipeline:
    """Extract → deduplicate → store flow."""

    def __init__(
        self,
        *,
        extractor: MemoryExtractor,
        deduplicator: MemoryDeduplicator | None = None,
        memory_manager: MemoryManager,
        event_bus: EventBus | None = None,
    ) -> None:
        self._extractor = extractor
        self._deduplicator = deduplicator
        self._manager = memory_manager
        self._event_bus = event_bus

    async def run(
        self,
        *,
        session_memories: tuple[MemoryItem, ...],
        episodes: tuple[Episode, ...],
        recent_events: tuple[EpisodicEvent, ...],
    ) -> ExtractionReport:
        """Run the full extraction pipeline."""
        # 1. Extract
        extracted = await self._extractor.extract(
            session_memories=session_memories,
            episodes=episodes,
            recent_events=recent_events,
        )

        stored_count = 0
        deduplicated_count = 0
        skipped_count = 0

        # 2. For each extracted memory, create MemoryItem and store
        for mem in extracted:
            item = MemoryItem(
                scope=mem.target_scope,
                key=mem.key,
                value=mem.value,
                confidence=Confidence(mem.confidence),
            )

            # 3. Dedup check if deduplicator available
            if self._deduplicator is not None:
                matches = await self._deduplicator.find_duplicates(candidate=item)
                result = await self._deduplicator.resolve(candidate=item, matches=matches)
                if result.skipped:
                    skipped_count += 1
                    continue
                if result.action == DeduplicationAction.MERGE:
                    deduplicated_count += 1
                item = result.item

            # 4. Store via memory manager
            await self._manager.remember(
                scope=item.scope,
                key=item.key,
                value=item.value,
                confidence=float(item.confidence),
                content_for_embedding=mem.content_for_embedding,
            )
            stored_count += 1

        # 5. Emit event if event bus configured
        if self._event_bus is not None:
            event = Event.create(
                type=EventType.MEMORY_EXTRACTED,
                payload={
                    "extracted_count": len(extracted),
                    "stored_count": stored_count,
                    "deduplicated_count": deduplicated_count,
                    "skipped_count": skipped_count,
                    "output": {
                        "items": [
                            {
                                "key": m.key,
                                "category": m.category.value,
                                "confidence": m.confidence,
                                "target_scope": m.target_scope.value,
                            }
                            for m in extracted
                        ],
                    },
                },
                source="extraction_pipeline",
            )
            await self._event_bus.publish(event=event)

        return ExtractionReport(
            extracted_count=len(extracted),
            stored_count=stored_count,
            deduplicated_count=deduplicated_count,
            skipped_count=skipped_count,
            items=extracted,
        )
