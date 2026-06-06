"""Unit tests for the default harvest impls (policy, correlator, distiller)."""

from __future__ import annotations

import pytest

from cemaf.blueprint.harvest import HarvestContext
from cemaf.blueprint.harvest_defaults import (
    InMemoryRunCorrelator,
    RecipeBlueprintDistiller,
    ScoreThresholdHarvestPolicy,
)
from cemaf.blueprint.library import BlueprintEntryKind
from cemaf.events.protocols import Event, EventType


def _eval_event(
    *,
    score: float = 0.95,
    passed: bool = True,
    run_id: str = "r1",
    node_id: str = "n1",
) -> Event:
    return Event.create(
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
    )


class TestScoreThresholdPolicy:
    def test_above_threshold_passes(self) -> None:
        policy = ScoreThresholdHarvestPolicy(threshold=0.8)
        assert policy.should_harvest(event=_eval_event(score=0.95)) is True

    def test_below_threshold_rejects(self) -> None:
        policy = ScoreThresholdHarvestPolicy(threshold=0.8)
        assert policy.should_harvest(event=_eval_event(score=0.5)) is False

    def test_exactly_at_threshold_passes(self) -> None:
        policy = ScoreThresholdHarvestPolicy(threshold=0.8)
        assert policy.should_harvest(event=_eval_event(score=0.8)) is True

    def test_require_passed_blocks_failed_eval(self) -> None:
        policy = ScoreThresholdHarvestPolicy(threshold=0.8, require_passed=True)
        assert policy.should_harvest(event=_eval_event(score=0.99, passed=False)) is False

    def test_require_passed_false_allows_unflagged(self) -> None:
        policy = ScoreThresholdHarvestPolicy(threshold=0.8, require_passed=False)
        assert policy.should_harvest(event=_eval_event(score=0.9, passed=False)) is True

    def test_missing_score_rejects(self) -> None:
        event = Event.create(type=EventType.EVAL_COMPLETED, payload={})
        policy = ScoreThresholdHarvestPolicy(threshold=0.8)
        assert policy.should_harvest(event=event) is False

    def test_invalid_threshold_raises(self) -> None:
        with pytest.raises(ValueError, match=r"\[0.0, 1.0\]"):
            ScoreThresholdHarvestPolicy(threshold=1.5)

    def test_threshold_below_min_raises(self) -> None:
        with pytest.raises(ValueError, match="min_threshold"):
            ScoreThresholdHarvestPolicy(threshold=0.1)


class TestInMemoryRunCorrelator:
    @pytest.mark.asyncio
    async def test_captures_goal_and_output(self) -> None:
        c = InMemoryRunCorrelator()
        await c.observe(
            event=Event.create(
                type=EventType.TASK_STARTED,
                payload={
                    "run_id": "r1",
                    "node_id": "n1",
                    "goal_text": "write a launch post",
                    "inputs": {"objective": "write a launch post"},
                },
            )
        )
        await c.observe(
            event=Event.create(
                type=EventType.TASK_COMPLETED,
                payload={
                    "run_id": "r1",
                    "node_id": "n1",
                    "output": "launched!",
                },
            )
        )

        ctx = await c.lookup(run_id="r1", node_id="n1")
        assert ctx is not None
        assert ctx.goal_text == "write a launch post"
        assert ctx.output_text == "launched!"

    @pytest.mark.asyncio
    async def test_goal_text_derived_from_inputs_when_absent(self) -> None:
        c = InMemoryRunCorrelator()
        await c.observe(
            event=Event.create(
                type=EventType.TASK_STARTED,
                payload={
                    "run_id": "r1",
                    "node_id": "n1",
                    "inputs": {"objective": "derived goal"},
                },
            )
        )
        await c.observe(
            event=Event.create(
                type=EventType.TASK_COMPLETED,
                payload={"run_id": "r1", "node_id": "n1", "output": "ok"},
            )
        )
        ctx = await c.lookup(run_id="r1", node_id="n1")
        assert ctx is not None
        assert ctx.goal_text == "derived goal"

    @pytest.mark.asyncio
    async def test_lookup_missing_returns_none(self) -> None:
        c = InMemoryRunCorrelator()
        assert await c.lookup(run_id="ghost", node_id="ghost") is None

    @pytest.mark.asyncio
    async def test_event_without_ids_is_ignored(self) -> None:
        c = InMemoryRunCorrelator()
        await c.observe(event=Event.create(type=EventType.TASK_STARTED, payload={}))
        assert await c.lookup(run_id="", node_id="") is None

    @pytest.mark.asyncio
    async def test_ttl_evicts_stale_entries(self) -> None:
        import time

        c = InMemoryRunCorrelator(ttl_seconds=0.05)
        # Feed both TASK_STARTED (goal) + TASK_COMPLETED (output) — lookup now
        # requires both to be populated.
        await c.observe(
            event=Event.create(
                type=EventType.TASK_STARTED,
                payload={"run_id": "r1", "node_id": "n1", "goal_text": "g"},
            )
        )
        await c.observe(
            event=Event.create(
                type=EventType.TASK_COMPLETED,
                payload={"run_id": "r1", "node_id": "n1", "output": "o"},
            )
        )
        assert await c.lookup(run_id="r1", node_id="n1") is not None
        time.sleep(0.1)
        assert await c.lookup(run_id="r1", node_id="n1") is None

    @pytest.mark.asyncio
    async def test_max_entries_cap(self) -> None:
        c = InMemoryRunCorrelator(max_entries=2, ttl_seconds=3600)
        # 3 distinct (run, node) pairs → oldest evicted. Feed both signals.
        for i in range(3):
            await c.observe(
                event=Event.create(
                    type=EventType.TASK_STARTED,
                    payload={"run_id": f"r{i}", "node_id": "n", "goal_text": f"g{i}"},
                )
            )
            await c.observe(
                event=Event.create(
                    type=EventType.TASK_COMPLETED,
                    payload={"run_id": f"r{i}", "node_id": "n", "output": f"o{i}"},
                )
            )
        # First one should have been evicted.
        assert await c.lookup(run_id="r0", node_id="n") is None
        assert await c.lookup(run_id="r2", node_id="n") is not None

    @pytest.mark.asyncio
    async def test_lookup_requires_both_goal_and_output(self) -> None:
        """Partial context (goal-only or output-only) returns None — prevents
        half-populated harvests when EVAL races ahead of TASK_COMPLETED."""
        c = InMemoryRunCorrelator()
        await c.observe(
            event=Event.create(
                type=EventType.TASK_STARTED,
                payload={"run_id": "r1", "node_id": "n1", "goal_text": "g"},
            )
        )
        # Only goal captured — lookup must return None.
        assert await c.lookup(run_id="r1", node_id="n1") is None

        await c.observe(
            event=Event.create(
                type=EventType.TASK_COMPLETED,
                payload={"run_id": "r1", "node_id": "n1", "output": "o"},
            )
        )
        # Both captured now — lookup succeeds.
        assert await c.lookup(run_id="r1", node_id="n1") is not None


class TestRecipeBlueprintDistiller:
    @pytest.mark.asyncio
    async def test_produces_recipe_entry(self) -> None:
        d = RecipeBlueprintDistiller()
        event = _eval_event(score=0.9)
        ctx = HarvestContext(
            run_id="r1",
            node_id="n1",
            goal_text="write a product launch announcement",
            output_text="# Launch\nhello world",
        )
        entry = await d.distill(event=event, context=ctx)
        assert entry is not None
        assert entry.kind is BlueprintEntryKind.RECIPE
        assert entry.id.startswith("harvest/")
        assert "harvested" in entry.tags
        assert entry.recipe is not None
        assert entry.recipe["goal"] == "write a product launch announcement"

    @pytest.mark.asyncio
    async def test_content_addressed_id_is_stable(self) -> None:
        d = RecipeBlueprintDistiller()
        ctx1 = HarvestContext(run_id="r1", node_id="n1", goal_text="same goal text")
        ctx2 = HarvestContext(run_id="r2", node_id="n2", goal_text="same goal text")
        e1 = await d.distill(event=_eval_event(), context=ctx1)
        e2 = await d.distill(event=_eval_event(), context=ctx2)
        assert e1 is not None and e2 is not None
        assert e1.id == e2.id  # same goal text → same id → idempotent upsert

    @pytest.mark.asyncio
    async def test_empty_goal_yields_none(self) -> None:
        d = RecipeBlueprintDistiller()
        ctx = HarvestContext(run_id="r1", node_id="n1", goal_text="   ")
        entry = await d.distill(event=_eval_event(), context=ctx)
        assert entry is None

    @pytest.mark.asyncio
    async def test_output_attached_as_style_example_when_short(self) -> None:
        d = RecipeBlueprintDistiller()
        ctx = HarvestContext(
            run_id="r1",
            node_id="n1",
            goal_text="g",
            output_text="short output",
        )
        entry = await d.distill(event=_eval_event(), context=ctx)
        assert entry is not None
        assert entry.recipe is not None
        assert entry.recipe["style"]["examples"] == ["short output"]

    @pytest.mark.asyncio
    async def test_long_output_omits_style_example(self) -> None:
        d = RecipeBlueprintDistiller()
        ctx = HarvestContext(
            run_id="r1",
            node_id="n1",
            goal_text="g",
            output_text="x" * 5000,
        )
        entry = await d.distill(event=_eval_event(), context=ctx)
        assert entry is not None
        assert entry.recipe is not None
        assert "style" not in entry.recipe
