"""Contract tests for the online evaluation pipeline."""

import pytest

from cemaf.evals.evaluators import ContainsEvaluator, LengthEvaluator
from cemaf.evals.online import EvalMode, NodeEvalBinding, OnlineEvalPipeline
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType


def _make_binding(
    *,
    node_pattern: str = "summarize",
    mode: EvalMode = EvalMode.OBSERVE,
    expected: str | None = "hello",
    min_length: int = 1,
    max_length: int = 500,
) -> NodeEvalBinding:
    """Create a NodeEvalBinding with deterministic evaluators."""
    return NodeEvalBinding(
        node_pattern=node_pattern,
        evaluators=(
            ContainsEvaluator(),
            LengthEvaluator(min_length=min_length, max_length=max_length),
        ),
        mode=mode,
        expected=expected,
    )


def _task_completed_event(
    *,
    node_id: str = "summarize",
    output: str = "hello world",
    correlation_id: str = "corr-1",
) -> Event:
    """Create a TASK_COMPLETED event."""
    return Event.create(
        type=EventType.TASK_COMPLETED,
        payload={"node_id": node_id, "output": output},
        source="test",
        correlation_id=correlation_id,
    )


@pytest.mark.asyncio
async def test_subscribes_to_task_completed() -> None:
    """Pipeline subscribes to TASK_COMPLETED and handles events."""
    bus = InMemoryEventBus()
    pipeline = OnlineEvalPipeline(
        bindings=(_make_binding(),),
        event_bus=bus,
    )
    pipeline.subscribe()

    await bus.publish(event=_task_completed_event())

    assert len(pipeline.results) == 1
    assert pipeline.results[0]["node_id"] == "summarize"


@pytest.mark.asyncio
async def test_evaluates_matching_node() -> None:
    """Binding matches specific node_id and runs evaluators."""
    bus = InMemoryEventBus()
    pipeline = OnlineEvalPipeline(
        bindings=(_make_binding(node_pattern="summarize"),),
        event_bus=bus,
    )
    pipeline.subscribe()

    # Matching node
    await bus.publish(event=_task_completed_event(node_id="summarize"))
    # Non-matching node
    await bus.publish(event=_task_completed_event(node_id="other_node"))

    assert len(pipeline.results) == 1
    assert pipeline.results[0]["node_id"] == "summarize"


@pytest.mark.asyncio
async def test_wildcard_binding_matches_all() -> None:
    """Wildcard '*' binding evaluates every node."""
    bus = InMemoryEventBus()
    pipeline = OnlineEvalPipeline(
        bindings=(_make_binding(node_pattern="*"),),
        event_bus=bus,
    )
    pipeline.subscribe()

    await bus.publish(event=_task_completed_event(node_id="node_a"))
    await bus.publish(event=_task_completed_event(node_id="node_b"))
    await bus.publish(event=_task_completed_event(node_id="node_c"))

    assert len(pipeline.results) == 3
    result_nodes = {r["node_id"] for r in pipeline.results}
    assert result_nodes == {"node_a", "node_b", "node_c"}


@pytest.mark.asyncio
async def test_gate_mode_emits_quality_alert_on_failure() -> None:
    """GATE mode emits QUALITY_ALERT when eval fails."""
    bus = InMemoryEventBus()
    alerts: list[Event] = []

    async def capture_alert(event: Event) -> None:
        alerts.append(event)

    bus.subscribe(event_type=EventType.QUALITY_ALERT, handler=capture_alert)

    # Use a contains evaluator that will fail — output won't contain "impossible_string"
    binding = NodeEvalBinding(
        node_pattern="summarize",
        evaluators=(ContainsEvaluator(),),
        mode=EvalMode.GATE,
        expected="impossible_string_not_in_output",
    )
    pipeline = OnlineEvalPipeline(
        bindings=(binding,),
        event_bus=bus,
    )
    pipeline.subscribe()

    await bus.publish(event=_task_completed_event(output="hello world"))

    assert len(alerts) == 1
    assert alerts[0].payload["level"] == "halt"
    assert alerts[0].payload["node_id"] == "summarize"
    assert pipeline.results[0]["overall_passed"] is False


@pytest.mark.asyncio
async def test_observe_mode_no_alert_on_failure() -> None:
    """OBSERVE mode does not emit QUALITY_ALERT even when eval fails."""
    bus = InMemoryEventBus()
    alerts: list[Event] = []

    async def capture_alert(event: Event) -> None:
        alerts.append(event)

    bus.subscribe(event_type=EventType.QUALITY_ALERT, handler=capture_alert)

    binding = NodeEvalBinding(
        node_pattern="summarize",
        evaluators=(ContainsEvaluator(),),
        mode=EvalMode.OBSERVE,
        expected="impossible_string_not_in_output",
    )
    pipeline = OnlineEvalPipeline(
        bindings=(binding,),
        event_bus=bus,
    )
    pipeline.subscribe()

    await bus.publish(event=_task_completed_event(output="hello world"))

    assert len(alerts) == 0
    assert len(pipeline.results) == 1
    assert pipeline.results[0]["overall_passed"] is False


@pytest.mark.asyncio
async def test_no_eval_when_no_output() -> None:
    """Events with no output in payload are skipped."""
    bus = InMemoryEventBus()
    pipeline = OnlineEvalPipeline(
        bindings=(_make_binding(node_pattern="*"),),
        event_bus=bus,
    )
    pipeline.subscribe()

    event = Event.create(
        type=EventType.TASK_COMPLETED,
        payload={"node_id": "summarize"},  # no "output" key
        source="test",
        correlation_id="corr-1",
    )
    await bus.publish(event=event)

    assert len(pipeline.results) == 0


@pytest.mark.asyncio
async def test_results_accumulated() -> None:
    """Results accumulate across multiple events."""
    bus = InMemoryEventBus()
    pipeline = OnlineEvalPipeline(
        bindings=(_make_binding(node_pattern="*"),),
        event_bus=bus,
    )
    pipeline.subscribe()

    for i in range(5):
        await bus.publish(
            event=_task_completed_event(
                node_id=f"node_{i}",
                output="hello world",
            )
        )

    assert len(pipeline.results) == 5
    # Each result has required keys
    for result in pipeline.results:
        assert "node_id" in result
        assert "overall_score" in result
        assert "overall_passed" in result
        assert "results" in result
        assert "mode" in result
