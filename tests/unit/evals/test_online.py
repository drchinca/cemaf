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
    run_id: str | None = None,
    workspace_id: str | None = None,
) -> Event:
    """Create a TASK_COMPLETED event."""
    payload: dict[str, object] = {"node_id": node_id, "output": output}
    if run_id is not None:
        payload["run_id"] = run_id
    if workspace_id is not None:
        payload["workspace_id"] = workspace_id
    return Event.create(
        type=EventType.TASK_COMPLETED,
        payload=payload,
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
    await pipeline.flush()

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
    await pipeline.flush()
    # Non-matching node
    await bus.publish(event=_task_completed_event(node_id="other_node"))
    await pipeline.flush()

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
    await pipeline.flush()

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
    await pipeline.flush()

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
    await pipeline.flush()

    assert len(pipeline.results) == 5
    # Each result has required keys
    for result in pipeline.results:
        assert "node_id" in result
        assert "overall_score" in result
        assert "overall_passed" in result
        assert "results" in result
        assert "mode" in result


@pytest.mark.asyncio
async def test_eval_completed_payload_includes_run_and_workspace_ids() -> None:
    """EVAL_STARTED / EVAL_COMPLETED carry explicit run_id and workspace_id for audit/SSE."""
    bus = InMemoryEventBus()
    captured: list[Event] = []

    async def capture_eval(event: Event) -> None:
        captured.append(event)

    bus.subscribe(event_type=EventType.EVAL_STARTED, handler=capture_eval)
    bus.subscribe(event_type=EventType.EVAL_COMPLETED, handler=capture_eval)

    pipeline = OnlineEvalPipeline(
        bindings=(_make_binding(node_pattern="*", mode=EvalMode.OBSERVE),),
        event_bus=bus,
    )
    pipeline.subscribe()

    await bus.publish(
        event=_task_completed_event(
            run_id="run-z",
            workspace_id="ws-z",
        )
    )
    await pipeline.flush()

    started = [e for e in captured if e.type == EventType.EVAL_STARTED]
    completed = [e for e in captured if e.type == EventType.EVAL_COMPLETED]
    assert len(started) == 1
    assert len(completed) == 1
    assert started[0].payload["run_id"] == "run-z"
    assert started[0].payload["workspace_id"] == "ws-z"
    assert completed[0].payload["run_id"] == "run-z"
    assert completed[0].payload["workspace_id"] == "ws-z"


@pytest.mark.asyncio
async def test_observe_mode_does_not_block_publish() -> None:
    """OBSERVE handlers fire-and-forget — publish returns before eval completes.

    Contract: publish() returns promptly; pipeline.flush() deterministically
    awaits every in-flight OBSERVE task this pipeline scheduled. Production
    callers invoke flush() at shutdown to avoid losing telemetry in flight.
    """
    bus = InMemoryEventBus()
    pipeline = OnlineEvalPipeline(
        bindings=(_make_binding(node_pattern="*", mode=EvalMode.OBSERVE),),
        event_bus=bus,
    )
    pipeline.subscribe()

    await bus.publish(event=_task_completed_event())

    # publish returned before the OBSERVE eval ran
    assert len(pipeline.results) == 0

    await pipeline.flush()

    # flush waited for every in-flight eval from this pipeline
    assert len(pipeline.results) == 1


@pytest.mark.asyncio
async def test_flush_is_noop_when_no_pending_tasks() -> None:
    """flush() with no in-flight tasks returns immediately — safe to call at any time."""
    bus = InMemoryEventBus()
    pipeline = OnlineEvalPipeline(bindings=(), event_bus=bus)
    pipeline.subscribe()

    await pipeline.flush()  # no work, no crash, no hang


@pytest.mark.asyncio
async def test_flush_only_awaits_this_pipelines_tasks() -> None:
    """flush() is scoped to this pipeline — unrelated async work is untouched."""
    bus = InMemoryEventBus()
    pipeline = OnlineEvalPipeline(
        bindings=(_make_binding(node_pattern="*", mode=EvalMode.OBSERVE),),
        event_bus=bus,
    )
    pipeline.subscribe()

    import asyncio

    unrelated_done = asyncio.Event()

    async def unrelated_background_work() -> None:
        await asyncio.sleep(10.0)  # would hang the test if flush() awaited this
        unrelated_done.set()

    unrelated_task = asyncio.create_task(unrelated_background_work())
    try:
        await bus.publish(event=_task_completed_event())
        await pipeline.flush()

        assert len(pipeline.results) == 1
        assert not unrelated_done.is_set()  # flush did not drain unrelated tasks
    finally:
        unrelated_task.cancel()
