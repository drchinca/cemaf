"""SPEC-13 e2e — scoped harvest through the REAL BlueprintHarvesterEngine flywheel.

The lighter promotion test calls the distiller directly. This drives the full production loop —
EventBus → ScoreThresholdHarvestPolicy → InMemoryRunCorrelator → ProjectScopedRecipeDistiller →
WritableBlueprintSource.append → library.register_async(overwrite=True) — for two projects that
harvest the SAME goal, and proves the no-clobber fix holds end-to-end (the contamination bug
lived in that overwrite=True register path). Persistence is a real SqliteBlueprintSource, and
promotion is evaluated over what was durably written.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cemaf.blueprint.core import BlueprintScope
from cemaf.blueprint.factories import create_blueprint_harvester
from cemaf.blueprint.harvest_defaults import ProjectScopedRecipeDistiller, evaluate_promotion
from cemaf.blueprint.library import BlueprintLibrary
from cemaf.blueprint.sqlite_source import SqliteBlueprintSource
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType

_GOAL = "summarize the quarterly report"


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
) -> None:
    """Publish the real TASK_STARTED → TASK_COMPLETED → EVAL_COMPLETED sequence."""
    await bus.publish(
        Event.create(
            type=EventType.TASK_STARTED,
            payload={"run_id": run_id, "node_id": node_id, "goal_text": goal_text},
            correlation_id=run_id,
        )
    )
    await bus.publish(
        Event.create(
            type=EventType.TASK_COMPLETED,
            payload={"run_id": run_id, "node_id": node_id, "output": output, "success": True},
            correlation_id=run_id,
        )
    )
    await bus.publish(
        Event.create(
            type=EventType.EVAL_COMPLETED,
            payload={
                "run_id": run_id,
                "node_id": node_id,
                "overall_score": score,
                "overall_passed": True,
            },
            correlation_id=run_id,
        )
    )


class TestScopedHarvestE2E:
    @pytest.mark.asyncio
    async def test_two_projects_same_goal_no_clobber_through_real_engine(self, db_path: str) -> None:
        """Two project-scoped engines harvest the same goal via the real flywheel; both entries
        coexist in the durable source despite register(overwrite=True)."""
        bus = InMemoryEventBus()
        source = SqliteBlueprintSource(db_path=db_path)
        library = BlueprintLibrary()

        # One engine per project, each with its own project-scoped distiller, on the same bus.
        # Each engine harvests only the run whose goal it's told to — but here both projects
        # legitimately harvest their OWN run of the same goal, so we run one engine at a time.
        alpha = create_blueprint_harvester(
            writable_source=source,
            event_bus=bus,
            library=library,
            distiller=ProjectScopedRecipeDistiller(project_id="alpha"),
        )
        await _fire_run(
            bus=bus, run_id="r-alpha", node_id="n", goal_text=_GOAL, output="A's summary", score=0.88
        )
        alpha.unsubscribe()

        beta = create_blueprint_harvester(
            writable_source=source,
            event_bus=bus,
            library=library,
            distiller=ProjectScopedRecipeDistiller(project_id="beta"),
        )
        await _fire_run(
            bus=bus, run_id="r-beta", node_id="n", goal_text=_GOAL, output="B's summary", score=0.82
        )
        beta.unsubscribe()
        await source.close()

        # Reload from a fresh SQLite handle (simulated restart) — both survived, no clobber.
        reloaded = tuple(SqliteBlueprintSource(db_path=db_path).load())
        project_ids = {e.project_id for e in reloaded}
        assert project_ids == {"alpha", "beta"}
        assert len({e.id for e in reloaded}) == 2  # distinct ids, not one overwritten record
        assert all(e.scope is BlueprintScope.PROJECT for e in reloaded)

    @pytest.mark.asyncio
    async def test_promotion_over_durably_harvested_entries(self, db_path: str) -> None:
        """Promotion fires over what the real engine durably wrote (≥2 projects, mean ≥0.8)."""
        bus = InMemoryEventBus()
        source = SqliteBlueprintSource(db_path=db_path)

        for project_id, run_id, score in (("alpha", "ra", 0.9), ("beta", "rb", 0.85)):
            engine = create_blueprint_harvester(
                writable_source=source,
                event_bus=bus,
                distiller=ProjectScopedRecipeDistiller(project_id=project_id),
            )
            await _fire_run(
                bus=bus, run_id=run_id, node_id="n", goal_text=_GOAL, output=f"out-{project_id}", score=score
            )
            engine.unsubscribe()
        await source.close()

        durable = tuple(SqliteBlueprintSource(db_path=db_path).load())
        decisions = [d for d in evaluate_promotion(durable) if d.promote]
        assert len(decisions) == 1
        assert decisions[0].project_ids == ("alpha", "beta")
        assert decisions[0].mean_confidence == pytest.approx(0.875)

    @pytest.mark.asyncio
    async def test_low_score_run_not_harvested(self, db_path: str) -> None:
        """The real ScoreThresholdHarvestPolicy (default 0.8) blocks a low-scoring run —
        confidence wiring doesn't bypass the harvest gate."""
        bus = InMemoryEventBus()
        source = SqliteBlueprintSource(db_path=db_path)
        engine = create_blueprint_harvester(
            writable_source=source,
            event_bus=bus,
            distiller=ProjectScopedRecipeDistiller(project_id="alpha"),
        )
        await _fire_run(bus=bus, run_id="r", node_id="n", goal_text=_GOAL, output="meh", score=0.5)
        engine.unsubscribe()
        await source.close()
        assert tuple(SqliteBlueprintSource(db_path=db_path).load()) == ()
