"""Integration test: create_blueprint_harvester() — the surfaced learn-from-runs flywheel.

Proves the base-layer factory wires the harvest loop in one call (no meta layer):
a high-scoring run flowing through a real EventBus is distilled into a reusable
blueprint that lands in the library and is retrievable by search. This is the
"research patterns from runs" capability, no longer buried behind opt-in meta wiring.
"""

from __future__ import annotations

import pytest

from cemaf.blueprint import (
    BlueprintLibrary,
    InMemoryWritableBlueprintSource,
    create_blueprint_harvester,
)
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType


async def _fire_run(
    *, bus: InMemoryEventBus, run_id: str, node_id: str, goal_text: str, output: str, score: float
) -> None:
    for event in (
        Event.create(
            type=EventType.TASK_STARTED,
            payload={
                "run_id": run_id,
                "node_id": node_id,
                "goal_text": goal_text,
                "inputs": {"objective": goal_text},
            },
            correlation_id=run_id,
        ),
        Event.create(
            type=EventType.TASK_COMPLETED,
            payload={"run_id": run_id, "node_id": node_id, "output": output, "success": True},
            correlation_id=run_id,
        ),
        Event.create(
            type=EventType.EVAL_COMPLETED,
            payload={
                "run_id": run_id,
                "node_id": node_id,
                "overall_score": score,
                "overall_passed": True,
                "results": [],
            },
            correlation_id=run_id,
        ),
    ):
        await bus.publish(event)


@pytest.mark.asyncio
async def test_factory_wires_flywheel_and_harvests_high_quality_run() -> None:
    bus = InMemoryEventBus()
    source = InMemoryWritableBlueprintSource()
    library = BlueprintLibrary()

    # One call surfaces the whole loop — subscribes to the bus by default.
    engine = create_blueprint_harvester(
        writable_source=source,
        event_bus=bus,
        library=library,
        threshold=0.8,
    )

    await _fire_run(
        bus=bus,
        run_id="r1",
        node_id="writer",
        goal_text="Write a product launch announcement",
        output="# Launch\nWe shipped it.",
        score=0.95,
    )

    # The high-scoring run became a reusable blueprint in the library.
    results = library.search(query="product launch announcement", k=3)
    assert results, "harvested blueprint should be discoverable by search"
    engine.unsubscribe()


@pytest.mark.asyncio
async def test_factory_skips_low_quality_run() -> None:
    bus = InMemoryEventBus()
    source = InMemoryWritableBlueprintSource()
    library = BlueprintLibrary()
    engine = create_blueprint_harvester(writable_source=source, event_bus=bus, library=library, threshold=0.8)

    await _fire_run(
        bus=bus,
        run_id="r2",
        node_id="writer",
        goal_text="A mediocre run",
        output="meh",
        score=0.4,  # below threshold
    )

    assert not list(source.load())  # nothing harvested
    engine.unsubscribe()


@pytest.mark.asyncio
async def test_factory_no_subscribe_defers_wiring() -> None:
    bus = InMemoryEventBus()
    source = InMemoryWritableBlueprintSource()
    engine = create_blueprint_harvester(writable_source=source, event_bus=bus, subscribe=False)

    # Not subscribed → a run fires but nothing is observed/harvested.
    await _fire_run(
        bus=bus,
        run_id="r3",
        node_id="writer",
        goal_text="unobserved",
        output="x",
        score=0.99,
    )
    assert not list(source.load())

    # Caller wires it explicitly later.
    engine.subscribe(event_bus=bus)
    await _fire_run(
        bus=bus,
        run_id="r4",
        node_id="writer",
        goal_text="now observed",
        output="y",
        score=0.99,
    )
    assert list(source.load())  # harvested after explicit subscribe
    engine.unsubscribe()
