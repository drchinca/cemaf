"""Unit tests for `BlueprintHarvesterEngine` — pure orchestration semantics."""

from __future__ import annotations

import pytest

from cemaf.blueprint.core import Blueprint, SceneGoal
from cemaf.blueprint.harvest import (
    BlueprintHarvesterEngine,
    HarvestContext,
    HarvestOutcome,
)
from cemaf.blueprint.library import BlueprintEntry, BlueprintLibrary
from cemaf.blueprint.sources import InMemoryWritableBlueprintSource
from cemaf.events.protocols import Event, EventType


class _FakePolicy:
    def __init__(self, *, decision: bool) -> None:
        self._decision = decision
        self.calls = 0

    def should_harvest(self, *, event: Event) -> bool:
        self.calls += 1
        return self._decision


class _FakeCorrelator:
    def __init__(self, *, context: HarvestContext | None) -> None:
        self._context = context
        self.observed: list[Event] = []

    async def observe(self, *, event: Event) -> None:
        self.observed.append(event)

    async def lookup(self, *, run_id: str, node_id: str) -> HarvestContext | None:
        return self._context


class _FakeDistiller:
    def __init__(self, *, entry: BlueprintEntry | None) -> None:
        self._entry = entry
        self.calls = 0

    async def distill(
        self,
        *,
        event: Event,
        context: HarvestContext,
    ) -> BlueprintEntry | None:
        self.calls += 1
        return self._entry


class _RaisingDistiller:
    async def distill(self, *, event: Event, context: HarvestContext) -> BlueprintEntry | None:
        raise RuntimeError("kaboom")


def _eval_event(score: float = 0.9, run_id: str = "r1", node_id: str = "n1") -> Event:
    return Event.create(
        type=EventType.EVAL_COMPLETED,
        payload={
            "run_id": run_id,
            "node_id": node_id,
            "overall_score": score,
            "overall_passed": True,
        },
        correlation_id=run_id,
    )


def _sample_entry() -> BlueprintEntry:
    bp = Blueprint(id="h", name="H", scene_goal=SceneGoal(objective="harvested"))
    return BlueprintEntry.snapshot_entry(id="harvest/abc", title="H", blueprint=bp)


class TestEngineOrchestration:
    @pytest.mark.asyncio
    async def test_policy_reject_short_circuits(self) -> None:
        source = InMemoryWritableBlueprintSource()
        distiller = _FakeDistiller(entry=_sample_entry())
        outcomes: list[HarvestOutcome] = []

        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=_FakePolicy(decision=False),
            correlator=_FakeCorrelator(context=HarvestContext(run_id="r1", node_id="n1")),
            distiller=distiller,
            on_outcome=outcomes.append,
        )

        # Manually drive trigger handler (no bus wiring needed for this test).
        await engine._trigger_handler(_eval_event())

        assert list(source.load()) == []
        assert distiller.calls == 0
        assert outcomes == [HarvestOutcome(accepted=False, reason="policy_rejected")]

    @pytest.mark.asyncio
    async def test_missing_run_or_node_id_short_circuits(self) -> None:
        source = InMemoryWritableBlueprintSource()
        outcomes: list[HarvestOutcome] = []
        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=_FakePolicy(decision=True),
            correlator=_FakeCorrelator(context=None),
            distiller=_FakeDistiller(entry=_sample_entry()),
            on_outcome=outcomes.append,
        )

        await engine._trigger_handler(
            Event.create(type=EventType.EVAL_COMPLETED, payload={"overall_score": 0.9}),
        )
        assert outcomes[-1].reason == "missing_run_or_node_id"

    @pytest.mark.asyncio
    async def test_no_correlation_skips(self) -> None:
        source = InMemoryWritableBlueprintSource()
        outcomes: list[HarvestOutcome] = []
        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=_FakePolicy(decision=True),
            correlator=_FakeCorrelator(context=None),
            distiller=_FakeDistiller(entry=_sample_entry()),
            on_outcome=outcomes.append,
        )
        await engine._trigger_handler(_eval_event())
        assert outcomes[-1].reason == "no_correlation"
        assert list(source.load()) == []

    @pytest.mark.asyncio
    async def test_distiller_none_skips(self) -> None:
        source = InMemoryWritableBlueprintSource()
        outcomes: list[HarvestOutcome] = []
        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=_FakePolicy(decision=True),
            correlator=_FakeCorrelator(context=HarvestContext(run_id="r1", node_id="n1")),
            distiller=_FakeDistiller(entry=None),
            on_outcome=outcomes.append,
        )
        await engine._trigger_handler(_eval_event())
        assert outcomes[-1].reason == "distiller_skipped"
        assert list(source.load()) == []

    @pytest.mark.asyncio
    async def test_distiller_exception_wrapped_as_outcome(self) -> None:
        source = InMemoryWritableBlueprintSource()
        outcomes: list[HarvestOutcome] = []
        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=_FakePolicy(decision=True),
            correlator=_FakeCorrelator(context=HarvestContext(run_id="r1", node_id="n1")),
            distiller=_RaisingDistiller(),
            on_outcome=outcomes.append,
        )
        await engine._trigger_handler(_eval_event())
        assert outcomes[-1].accepted is False
        assert "distiller_error" in outcomes[-1].reason
        assert list(source.load()) == []  # engine didn't swallow the error silently

    @pytest.mark.asyncio
    async def test_success_persists_to_source_and_library(self) -> None:
        source = InMemoryWritableBlueprintSource()
        library = BlueprintLibrary()
        entry = _sample_entry()
        outcomes: list[HarvestOutcome] = []

        engine = BlueprintHarvesterEngine(
            writable_source=source,
            library=library,
            policy=_FakePolicy(decision=True),
            correlator=_FakeCorrelator(context=HarvestContext(run_id="r1", node_id="n1")),
            distiller=_FakeDistiller(entry=entry),
            on_outcome=outcomes.append,
        )
        await engine._trigger_handler(_eval_event())

        loaded = list(source.load())
        assert len(loaded) == 1
        assert loaded[0].id == entry.id
        assert library.get(entry.id) is not None
        assert outcomes[-1].accepted is True
        assert outcomes[-1].entry_id == entry.id

    @pytest.mark.asyncio
    async def test_library_optional(self) -> None:
        """Engine works without a library — append goes only to the writable source."""
        source = InMemoryWritableBlueprintSource()
        entry = _sample_entry()
        engine = BlueprintHarvesterEngine(
            writable_source=source,
            library=None,
            policy=_FakePolicy(decision=True),
            correlator=_FakeCorrelator(context=HarvestContext(run_id="r1", node_id="n1")),
            distiller=_FakeDistiller(entry=entry),
        )
        await engine._trigger_handler(_eval_event())
        assert len(list(source.load())) == 1

    @pytest.mark.asyncio
    async def test_observe_forwards_to_correlator(self) -> None:
        source = InMemoryWritableBlueprintSource()
        correlator = _FakeCorrelator(context=None)
        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=_FakePolicy(decision=True),
            correlator=correlator,
            distiller=_FakeDistiller(entry=None),
        )
        started = Event.create(type=EventType.TASK_STARTED, payload={"run_id": "r1"})
        await engine._observe_handler(started)
        assert correlator.observed == [started]


class _EventuallyReadyCorrelator:
    """Correlator that returns None for the first N lookups, then returns a context.

    Simulates the race where EVAL_COMPLETED arrives before TASK_COMPLETED —
    the engine must retry `lookup` so late-arriving output_text still wins.
    """

    def __init__(self, *, ready_after: int, context: HarvestContext) -> None:
        self._ready_after = ready_after
        self._context = context
        self._calls = 0

    async def observe(self, *, event: Event) -> None:
        return None

    async def lookup(self, *, run_id: str, node_id: str) -> HarvestContext | None:
        self._calls += 1
        if self._calls > self._ready_after:
            return self._context
        return None


class _NeverReadyCorrelator:
    """Always returns None — simulates a genuinely orphaned eval."""

    def __init__(self) -> None:
        self.calls = 0

    async def observe(self, *, event: Event) -> None:
        return None

    async def lookup(self, *, run_id: str, node_id: str) -> HarvestContext | None:
        self.calls += 1
        return None


class TestCorrelationRetry:
    @pytest.mark.asyncio
    async def test_retry_catches_late_correlation(self) -> None:
        """Engine re-polls the correlator and wins if the data arrives mid-retry."""
        source = InMemoryWritableBlueprintSource()
        ctx = HarvestContext(run_id="r1", node_id="n1", goal_text="g", output_text="o")
        correlator = _EventuallyReadyCorrelator(ready_after=2, context=ctx)
        outcomes: list[HarvestOutcome] = []
        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=_FakePolicy(decision=True),
            correlator=correlator,
            distiller=_FakeDistiller(entry=_sample_entry()),
            on_outcome=outcomes.append,
            correlation_retry_attempts=3,
            correlation_retry_delay_s=0.0,  # fast test
        )
        await engine._trigger_handler(_eval_event())
        assert outcomes[-1].accepted is True
        assert correlator._calls == 3  # 1 initial + 2 retries until ready

    @pytest.mark.asyncio
    async def test_retry_gives_up_after_bounded_attempts(self) -> None:
        """Orphaned eval (no correlation ever arrives) fails after retries are spent."""
        source = InMemoryWritableBlueprintSource()
        correlator = _NeverReadyCorrelator()
        outcomes: list[HarvestOutcome] = []
        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=_FakePolicy(decision=True),
            correlator=correlator,
            distiller=_FakeDistiller(entry=_sample_entry()),
            on_outcome=outcomes.append,
            correlation_retry_attempts=3,
            correlation_retry_delay_s=0.0,
        )
        await engine._trigger_handler(_eval_event())
        assert outcomes[-1].accepted is False
        assert outcomes[-1].reason == "no_correlation"
        assert correlator.calls == 4  # 1 initial + 3 retries

    @pytest.mark.asyncio
    async def test_zero_retries_is_one_attempt(self) -> None:
        """retry_attempts=0 means try once, don't retry."""
        source = InMemoryWritableBlueprintSource()
        correlator = _NeverReadyCorrelator()
        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=_FakePolicy(decision=True),
            correlator=correlator,
            distiller=_FakeDistiller(entry=_sample_entry()),
            correlation_retry_attempts=0,
            correlation_retry_delay_s=0.0,
        )
        await engine._trigger_handler(_eval_event())
        assert correlator.calls == 1

    @pytest.mark.asyncio
    async def test_negative_retry_attempts_rejected(self) -> None:
        with pytest.raises(ValueError, match="correlation_retry_attempts"):
            BlueprintHarvesterEngine(
                writable_source=InMemoryWritableBlueprintSource(),
                policy=_FakePolicy(decision=True),
                correlator=_FakeCorrelator(context=None),
                distiller=_FakeDistiller(entry=None),
                correlation_retry_attempts=-1,
            )

    @pytest.mark.asyncio
    async def test_negative_retry_delay_rejected(self) -> None:
        with pytest.raises(ValueError, match="correlation_retry_delay_s"):
            BlueprintHarvesterEngine(
                writable_source=InMemoryWritableBlueprintSource(),
                policy=_FakePolicy(decision=True),
                correlator=_FakeCorrelator(context=None),
                distiller=_FakeDistiller(entry=None),
                correlation_retry_delay_s=-0.1,
            )


class TestEngineSubscription:
    @pytest.mark.asyncio
    async def test_subscribe_and_unsubscribe_on_real_bus(self) -> None:
        from cemaf.events.bus import InMemoryEventBus

        bus = InMemoryEventBus()
        source = InMemoryWritableBlueprintSource()
        entry = _sample_entry()
        correlator = _FakeCorrelator(context=HarvestContext(run_id="r1", node_id="n1"))

        engine = BlueprintHarvesterEngine(
            writable_source=source,
            policy=_FakePolicy(decision=True),
            correlator=correlator,
            distiller=_FakeDistiller(entry=entry),
        )
        engine.subscribe(event_bus=bus)

        # Publish an observe event — correlator sees it.
        await bus.publish(
            Event.create(type=EventType.TASK_STARTED, payload={"run_id": "r1", "node_id": "n1"}),
        )
        assert len(correlator.observed) == 1

        # Publish a trigger event — entry is harvested.
        await bus.publish(_eval_event())
        assert len(list(source.load())) == 1

        # Unsubscribe — further events do nothing.
        engine.unsubscribe()
        await bus.publish(
            Event.create(type=EventType.TASK_STARTED, payload={"run_id": "r2", "node_id": "n2"}),
        )
        assert len(correlator.observed) == 1  # no new observation after unsubscribe

    @pytest.mark.asyncio
    async def test_unsubscribe_is_idempotent(self) -> None:
        from cemaf.events.bus import InMemoryEventBus

        bus = InMemoryEventBus()
        engine = BlueprintHarvesterEngine(
            writable_source=InMemoryWritableBlueprintSource(),
            policy=_FakePolicy(decision=False),
            correlator=_FakeCorrelator(context=None),
            distiller=_FakeDistiller(entry=None),
        )
        engine.subscribe(event_bus=bus)
        engine.unsubscribe()
        engine.unsubscribe()  # must not raise
