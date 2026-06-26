"""Bridges EventBus events to episodic memory recording."""

from __future__ import annotations

from cemaf.core.utils import utc_now
from cemaf.events.protocols import Event, EventBus, EventType
from cemaf.memory.episodic import EpisodicEvent
from cemaf.memory.manager import MemoryManager
from cemaf.memory.session import SessionManager

RECORDABLE_EVENTS: tuple[EventType, ...] = (
    EventType.DAG_STARTED,
    EventType.DAG_COMPLETED,
    EventType.TASK_FAILED,
    EventType.SYSTEM_ERROR,
    EventType.MEMORY_ITEM_SET,
)
RUN_SCOPED_RECORDABLE_EVENTS: tuple[EventType, ...] = (
    EventType.DAG_STARTED,
    EventType.DAG_COMPLETED,
    EventType.TASK_COMPLETED,
    EventType.TASK_FAILED,
    EventType.SYSTEM_ERROR,
    EventType.MEMORY_ITEM_SET,
)


async def record_event_to_memory(
    event: Event,
    *,
    memory_manager: MemoryManager,
    episode_id: str,
) -> None:
    """Record a bus event as an episodic event."""
    episodic_event = EpisodicEvent(
        timestamp=utc_now(),
        event_type=event.type,
        actor=event.source,
        action=event.type,
        content=event.payload,
    )
    await memory_manager.record_event(episode_id=episode_id, event=episodic_event)


def subscribe_memory_recording(
    *,
    event_bus: EventBus,
    memory_manager: MemoryManager,
    episode_id: str,
) -> None:
    """Subscribe to recordable events and auto-record them."""

    async def handler(event: Event) -> None:
        await record_event_to_memory(
            event,
            memory_manager=memory_manager,
            episode_id=episode_id,
        )

    for event_type in RECORDABLE_EVENTS:
        event_bus.subscribe(event_type=event_type, handler=handler)


async def record_event_to_session_memory(
    event: Event,
    *,
    memory_manager: MemoryManager,
    session_manager: SessionManager,
) -> None:
    """Record a run-scoped bus event into its active session episode."""

    run_id = str(event.payload.get("run_id") or event.correlation_id or "").strip()
    if not run_id:
        return
    state = await session_manager.get_state(run_id)
    if state is None or state.episode_id is None:
        return
    await record_event_to_memory(
        event,
        memory_manager=memory_manager,
        episode_id=state.episode_id,
    )


def subscribe_session_memory_recording(
    *,
    event_bus: EventBus,
    memory_manager: MemoryManager,
    session_manager: SessionManager,
    event_types: tuple[EventType, ...] = RUN_SCOPED_RECORDABLE_EVENTS,
) -> None:
    """Subscribe to run-scoped events and write them to the active session episode."""

    async def handler(event: Event) -> None:
        await record_event_to_session_memory(
            event,
            memory_manager=memory_manager,
            session_manager=session_manager,
        )

    for event_type in event_types:
        event_bus.subscribe(event_type=event_type, handler=handler)
