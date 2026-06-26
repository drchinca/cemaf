"""
CEMAF Collision Avoidance — TCAS-style coordination over ContextPatch write paths (SPEC-12).

Two concurrent agents intend to write the SAME context path. The collision coordinator
computes a continuous risk and, at resolution level, deterministically steers the
lower-priority agent away while the higher-priority one holds — so they never clobber each
other at merge time. Priority is a total order: committed-progress, then earlier start, then
stable agent id.

Usage:
    uv run python examples/collision_avoidance.py
"""

import asyncio

from cemaf.collision import (
    AdvisoryLevel,
    AgentWriteSet,
    WriteItem,
    create_collision_coordinator,
    emit_advisory,
)
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import EventType


def _write_set(agent_id: str, path: str, *, started_at: float) -> AgentWriteSet:
    """An agent's intended write — one path, with a start time for the priority tiebreak."""
    return AgentWriteSet(
        agent_id=agent_id,
        items=(WriteItem(path=path),),
        started_at=started_at,
    )


async def main() -> None:
    # An EventBus so we can observe the CONTEXT_CONFLICT event the coordinator surfaces.
    bus = InMemoryEventBus()
    conflicts: list[str] = []
    bus.subscribe(EventType.CONTEXT_CONFLICT, lambda e: conflicts.append(e.payload["steer"]))

    # A run-scoped coordinator expecting a cohort of 2 agents.
    coordinator = create_collision_coordinator(cohort_size=2)

    # Two agents both intend to write "draft.body". 'researcher' started earlier → holds.
    researcher = _write_set("researcher", "draft.body", started_at=1.0)
    writer = _write_set("writer", "draft.body", started_at=2.0)

    async def run_agent(write_set: AgentWriteSet) -> None:
        await coordinator.register(write_set)
        advisory = await coordinator.advise_against_cohort(write_set.agent_id)
        await emit_advisory(event_bus=bus, advisory=advisory, agent_id=write_set.agent_id)
        if advisory.level is AdvisoryLevel.RESOLUTION_ADVISORY and advisory.steer == write_set.agent_id:
            print(f"  {write_set.agent_id}: STEER — defer (yield 'draft.body' to {advisory.hold})")
        elif advisory.level is AdvisoryLevel.RESOLUTION_ADVISORY:
            print(f"  {write_set.agent_id}: HOLD — right-of-way, proceeding to write 'draft.body'")
        else:
            print(f"  {write_set.agent_id}: CLEAR — no collision ({advisory.level.value})")

    # Both agents race concurrently through the coordinator's cohort barrier.
    print("Two agents both want to write 'draft.body':")
    await asyncio.gather(run_agent(researcher), run_agent(writer))

    print(f"\nSteered agents (deterministic): {conflicts}")
    print("→ 'researcher' holds (earlier start); 'writer' steers. Same result every run.")


if __name__ == "__main__":
    asyncio.run(main())
