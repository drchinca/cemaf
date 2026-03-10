"""Tests for EventBus -> episodic memory subscriber bridge."""

import pytest

from cemaf.events.memory_subscriber import (
    RECORDABLE_EVENTS,
    record_event_to_memory,
    subscribe_memory_recording,
)
from cemaf.events.mock import MockEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.memory.base import InMemoryStore
from cemaf.memory.episodic import InMemoryEpisodicStore
from cemaf.memory.manager import DefaultMemoryManager
from cemaf.memory.scoring import TemporalDecayScorer
from cemaf.memory.semantic import DefaultSemanticMemoryStore
from cemaf.retrieval.memory_store import InMemoryVectorStore, MockEmbeddingProvider


def _make_memory_manager() -> DefaultMemoryManager:
    """Build a DefaultMemoryManager backed by in-memory stores."""
    embedding_provider = MockEmbeddingProvider()
    semantic_store = DefaultSemanticMemoryStore(
        memory_store=InMemoryStore(),
        vector_store=InMemoryVectorStore(embedding_provider=embedding_provider),
        embedding_provider=embedding_provider,
        scorer=TemporalDecayScorer(),
    )
    return DefaultMemoryManager(
        semantic_store=semantic_store,
        episodic_store=InMemoryEpisodicStore(),
    )


@pytest.mark.asyncio
async def test_recordable_event_creates_episodic_event() -> None:
    """record_event_to_memory writes an EpisodicEvent to the store."""
    manager = _make_memory_manager()
    episode = await manager.start_episode(session_id="sess-1")

    event = Event.create(
        type=EventType.DAG_STARTED,
        payload={"dag_name": "my-dag", "run_id": "r1"},
        source="dag_executor",
    )

    await record_event_to_memory(
        event,
        memory_manager=manager,
        episode_id=episode.id,
    )

    history = await manager.get_recent_history(session_id="sess-1", limit=10)
    assert len(history) == 1
    recorded = history[0]
    assert recorded.event_type == EventType.DAG_STARTED.value
    assert recorded.actor == "dag_executor"
    assert recorded.content == {"dag_name": "my-dag", "run_id": "r1"}


@pytest.mark.asyncio
async def test_subscribe_memory_recording_wires_handlers() -> None:
    """subscribe_memory_recording registers handlers for all RECORDABLE_EVENTS."""
    bus = MockEventBus()
    manager = _make_memory_manager()
    episode = await manager.start_episode(session_id="sess-2")

    subscribe_memory_recording(
        event_bus=bus,
        memory_manager=manager,
        episode_id=episode.id,
    )

    # Publish a recordable event
    event = Event.create(
        type=EventType.DAG_COMPLETED,
        payload={"dag_name": "pipeline", "run_id": "r2"},
        source="dag_executor",
    )
    await bus.publish(event=event)

    history = await manager.get_recent_history(session_id="sess-2", limit=10)
    assert len(history) == 1
    assert history[0].event_type == EventType.DAG_COMPLETED.value

    # Publish a non-recordable event — should NOT appear in history
    non_recordable = Event.create(
        type=EventType.CONTEXT_COMPILED,
        payload={},
        source="compiler",
    )
    await bus.publish(event=non_recordable)

    history_after = await manager.get_recent_history(session_id="sess-2", limit=10)
    assert len(history_after) == 1  # still just the one from before


@pytest.mark.asyncio
async def test_recordable_events_tuple_contains_expected_types() -> None:
    """RECORDABLE_EVENTS includes the lifecycle event types we care about."""
    assert EventType.DAG_STARTED in RECORDABLE_EVENTS
    assert EventType.DAG_COMPLETED in RECORDABLE_EVENTS
    assert EventType.TASK_FAILED in RECORDABLE_EVENTS
    assert EventType.SYSTEM_ERROR in RECORDABLE_EVENTS
    assert EventType.MEMORY_ITEM_SET in RECORDABLE_EVENTS
