"""SPEC-12 integration — CollisionCoordinator + real EventBus end-to-end.

Two concurrent agents register overlapping intended writes; the coordinator resolves
deterministically and the advisory is surfaced as a CONTEXT_CONFLICT event on a real bus.
"""

import asyncio

import pytest

from cemaf.collision import (
    AdvisoryLevel,
    AgentWriteSet,
    WriteItem,
    create_collision_coordinator,
    emit_advisory,
)
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType


def _ws(agent_id: str, *paths: str, started_at: float = 0.0) -> AgentWriteSet:
    return AgentWriteSet(
        agent_id=agent_id,
        items=tuple(WriteItem(path=p) for p in paths),
        started_at=started_at,
    )


@pytest.mark.asyncio
async def test_concurrent_overlap_resolves_and_emits_event() -> None:
    bus = InMemoryEventBus()
    received: list[Event] = []
    bus.subscribe(EventType.CONTEXT_CONFLICT, lambda e: received.append(e))

    coord = create_collision_coordinator(cohort_size=2)

    async def agent(agent_id: str, started_at: float) -> AdvisoryLevel:
        await coord.register(_ws(agent_id, "draft.body", started_at=started_at))
        advisory = await coord.advise_against_cohort(agent_id)
        await emit_advisory(event_bus=bus, advisory=advisory, agent_id=agent_id)
        return advisory.level

    # Both agents run "concurrently" through the cohort barrier.
    a_level, b_level = await asyncio.gather(
        agent("agent_a", 1.0),
        agent("agent_b", 2.0),
    )

    # Deterministic: both see RESOLUTION_ADVISORY on the shared path.
    assert a_level is AdvisoryLevel.RESOLUTION_ADVISORY
    assert b_level is AdvisoryLevel.RESOLUTION_ADVISORY

    # Earlier-start agent_a holds; agent_b steers — same verdict from both sides.
    assert all(e.payload["hold"] == "agent_a" for e in received)
    assert all(e.payload["steer"] == "agent_b" for e in received)
    assert len(received) == 2  # one event per agent, both at TA+


@pytest.mark.asyncio
async def test_disjoint_writes_emit_no_conflict() -> None:
    bus = InMemoryEventBus()
    received: list[Event] = []
    bus.subscribe(EventType.CONTEXT_CONFLICT, lambda e: received.append(e))

    coord = create_collision_coordinator(cohort_size=2)
    await coord.register(_ws("a", "research.findings"))
    await coord.register(_ws("b", "draft.outline"))

    advisory = await coord.advise_against_cohort("a")
    published = await emit_advisory(event_bus=bus, advisory=advisory, agent_id="a")

    assert advisory.level is AdvisoryLevel.CLEAR
    assert published is False
    assert received == []
