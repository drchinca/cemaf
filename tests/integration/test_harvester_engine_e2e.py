"""End-to-end harvester — real EventBus + default impls + SQLite writable source.

Simulates the full protocol sequence that runs in production:

  TASK_STARTED  (goal text captured by correlator)
  TASK_COMPLETED (output captured by correlator)
  EVAL_COMPLETED (policy passes → distiller builds RECIPE → source appends)

Then reopens the SQLite file in a fresh process-shaped `SqliteBlueprintSource`
and verifies the harvested entry persisted across the simulated restart.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cemaf.blueprint.harvest import BlueprintHarvesterEngine
from cemaf.blueprint.library import BlueprintEntryKind, BlueprintLibrary
from cemaf.blueprint.sqlite_source import SqliteBlueprintSource
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.meta.harvest_defaults import (
    InMemoryRunCorrelator,
    RecipeBlueprintDistiller,
    ScoreThresholdHarvestPolicy,
)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "blueprints.db")


async def _fire_run(
    *,
    bus: InMemoryEventBus,
    run_id: str,
    node_id: str,
    goal_text: str,
    output: str,
    score: float,
    passed: bool = True,
) -> None:
    """Publish the full TASK_STARTED → TASK_COMPLETED → EVAL_COMPLETED sequence."""
    await bus.publish(
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
    )
    await bus.publish(
        Event.create(
            type=EventType.TASK_COMPLETED,
            payload={
                "run_id": run_id,
                "node_id": node_id,
                "output": output,
                "success": True,
            },
            correlation_id=run_id,
        ),
    )
    await bus.publish(
        Event.create(
            type=EventType.EVAL_COMPLETED,
            payload={
                "run_id": run_id,
                "node_id": node_id,
                "overall_score": score,
                "overall_passed": passed,
                "mode": "observe",
                "trigger": "task_completed",
                "results": [],
            },
            correlation_id=run_id,
        ),
    )


class TestHarvesterEndToEnd:
    @pytest.mark.asyncio
    async def test_high_quality_run_is_persisted_and_reloadable(self, db_path: str) -> None:
        bus = InMemoryEventBus()
        source = SqliteBlueprintSource(db_path=db_path)
        library = BlueprintLibrary()

        engine = BlueprintHarvesterEngine(
            writable_source=source,
            library=library,
            policy=ScoreThresholdHarvestPolicy(threshold=0.8),
            correlator=InMemoryRunCorrelator(),
            distiller=RecipeBlueprintDistiller(),
        )
        engine.subscribe(event_bus=bus)

        await _fire_run(
            bus=bus,
            run_id="r1",
            node_id="writer",
            goal_text="Write a product launch announcement",
            output="# Launch\nWe shipped it.",
            score=0.95,
        )

        engine.unsubscribe()
        await source.close()

        # Reopen in a fresh source handle — proves persistence, not just state.
        reopened = SqliteBlueprintSource(db_path=db_path)
        entries = list(reopened.load())
        assert len(entries) == 1
        got = entries[0]
        assert got.kind is BlueprintEntryKind.RECIPE
        assert got.id.startswith("harvest/")
        assert got.recipe is not None
        assert got.recipe["goal"] == "Write a product launch announcement"
        # Library saw it too.
        assert library.get(got.id) is not None

    @pytest.mark.asyncio
    async def test_low_quality_run_does_not_harvest(self, db_path: str) -> None:
        bus = InMemoryEventBus()
        source = SqliteBlueprintSource(db_path=db_path)

        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=ScoreThresholdHarvestPolicy(threshold=0.8),
            correlator=InMemoryRunCorrelator(),
            distiller=RecipeBlueprintDistiller(),
        )
        engine.subscribe(event_bus=bus)

        await _fire_run(
            bus=bus,
            run_id="r_fail",
            node_id="writer",
            goal_text="some goal",
            output="meh",
            score=0.5,
        )

        engine.unsubscribe()
        await source.close()

        assert list(SqliteBlueprintSource(db_path=db_path).load()) == []

    @pytest.mark.asyncio
    async def test_content_addressed_upsert_across_runs(self, db_path: str) -> None:
        """Same goal text harvested twice → single entry (idempotent upsert)."""
        bus = InMemoryEventBus()
        source = SqliteBlueprintSource(db_path=db_path)

        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=ScoreThresholdHarvestPolicy(threshold=0.8),
            correlator=InMemoryRunCorrelator(),
            distiller=RecipeBlueprintDistiller(),
        )
        engine.subscribe(event_bus=bus)

        for run_id in ("r1", "r2"):
            await _fire_run(
                bus=bus,
                run_id=run_id,
                node_id="writer",
                goal_text="same goal every time",
                output=f"output for {run_id}",
                score=0.9,
            )

        engine.unsubscribe()
        await source.close()

        entries = list(SqliteBlueprintSource(db_path=db_path).load())
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_failed_eval_does_not_harvest(self, db_path: str) -> None:
        bus = InMemoryEventBus()
        source = SqliteBlueprintSource(db_path=db_path)

        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=ScoreThresholdHarvestPolicy(threshold=0.8, require_passed=True),
            correlator=InMemoryRunCorrelator(),
            distiller=RecipeBlueprintDistiller(),
        )
        engine.subscribe(event_bus=bus)

        await _fire_run(
            bus=bus,
            run_id="r_not_passed",
            node_id="writer",
            goal_text="x",
            output="y",
            score=0.99,
            passed=False,
        )

        engine.unsubscribe()
        await source.close()

        assert list(SqliteBlueprintSource(db_path=db_path).load()) == []

    @pytest.mark.asyncio
    async def test_eval_without_task_events_skips_gracefully(self, db_path: str) -> None:
        """If correlator never saw TASK_STARTED/TASK_COMPLETED, harvest is skipped — no crash."""
        bus = InMemoryEventBus()
        source = SqliteBlueprintSource(db_path=db_path)

        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=ScoreThresholdHarvestPolicy(threshold=0.8),
            correlator=InMemoryRunCorrelator(),
            distiller=RecipeBlueprintDistiller(),
        )
        engine.subscribe(event_bus=bus)

        # Only publish EVAL_COMPLETED — no TASK_STARTED/TASK_COMPLETED arrived first.
        await bus.publish(
            Event.create(
                type=EventType.EVAL_COMPLETED,
                payload={
                    "run_id": "orphan",
                    "node_id": "writer",
                    "overall_score": 0.99,
                    "overall_passed": True,
                },
                correlation_id="orphan",
            ),
        )

        engine.unsubscribe()
        await source.close()
        assert list(SqliteBlueprintSource(db_path=db_path).load()) == []
