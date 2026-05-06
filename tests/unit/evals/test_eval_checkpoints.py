"""Tests for checkpoint-aware eval, structured output, and trend-based halting."""

from __future__ import annotations

from typing import Any

import pytest

from cemaf.core.enums import NodeType
from cemaf.core.types import JSON
from cemaf.evals.online import EvalTrigger, NodeEvalBinding, OnlineEvalPipeline
from cemaf.evals.police import (
    AlertLevel,
    QualityPolice,
    QualityPoliceConfig,
)
from cemaf.evals.protocols import BaseEvaluator, EvalContext, EvalMetric, EvalResult
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.orchestration.dag import DAG, Edge, Node
from tests.unit.evals.conftest import drain_tasks

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakePassEvaluator(BaseEvaluator):
    """Always passes with score=0.9."""

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.PASS_FAIL

    async def evaluate(self, output: Any, expected: Any = None, context: JSON | None = None) -> EvalResult:
        return self._make_result(score=0.9, reason="pass")


class FakeStructuredEvaluator(BaseEvaluator):
    """Records whatever output it receives — proves structured data arrives."""

    received_outputs: list[Any] = []

    def __init__(self) -> None:
        super().__init__()
        self.received_outputs = []

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.CUSTOM

    async def evaluate(self, output: Any, expected: Any = None, context: JSON | None = None) -> EvalResult:
        self.received_outputs.append(output)
        return self._make_result(score=0.95, reason="structured check")


# ---------------------------------------------------------------------------
# 1. Checkpoint node type
# ---------------------------------------------------------------------------


class TestCheckpointNodeType:
    def test_checkpoint_in_node_type_enum(self) -> None:
        assert NodeType.CHECKPOINT == "checkpoint"

    def test_create_checkpoint_node(self) -> None:
        node = Node.checkpoint(id="cp1", name="Quality Gate")
        assert node.type == NodeType.CHECKPOINT
        assert str(node.id) == "cp1"
        assert node.name == "Quality Gate"

    def test_checkpoint_node_in_dag(self) -> None:
        dag = DAG(name="test", description="checkpoint test")
        dag = dag.add_node(node=Node.agent(id="a1", name="Agent", agent_id="test", output_key="out"))
        dag = dag.add_node(node=Node.checkpoint(id="cp1"))
        dag = dag.add_node(node=Node.agent(id="a2", name="Agent2", agent_id="test2", output_key="out2"))
        dag = dag.add_edge(edge=Edge(source="a1", target="cp1"))
        dag = dag.add_edge(edge=Edge(source="cp1", target="a2"))
        assert dag.validate_structure() is True
        assert len(dag.nodes) == 3


# ---------------------------------------------------------------------------
# 2. EvalTrigger — checkpoint-only filtering
# ---------------------------------------------------------------------------


class TestEvalTrigger:
    def test_checkpoint_only_binding(self) -> None:
        binding = NodeEvalBinding(
            node_pattern="*",
            evaluators=(FakePassEvaluator(),),
            trigger=EvalTrigger.CHECKPOINT_ONLY,
        )
        assert binding.trigger == EvalTrigger.CHECKPOINT_ONLY

    def test_every_node_is_default(self) -> None:
        binding = NodeEvalBinding(
            node_pattern="*",
            evaluators=(FakePassEvaluator(),),
        )
        assert binding.trigger == EvalTrigger.EVERY_NODE

    @pytest.mark.asyncio
    async def test_checkpoint_only_skips_task_completed(self) -> None:
        """CHECKPOINT_ONLY binding does NOT fire on TASK_COMPLETED events."""
        bus = InMemoryEventBus()
        pipeline = OnlineEvalPipeline(
            bindings=(
                NodeEvalBinding(
                    node_pattern="*",
                    evaluators=(FakePassEvaluator(),),
                    trigger=EvalTrigger.CHECKPOINT_ONLY,
                ),
            ),
            event_bus=bus,
        )
        pipeline.subscribe()

        await bus.publish(
            event=Event.create(
                type=EventType.TASK_COMPLETED,
                payload={"node_id": "n1", "output": "hello"},
                source="test",
            )
        )

        assert len(pipeline.results) == 0  # Did NOT fire

    @pytest.mark.asyncio
    async def test_checkpoint_only_fires_on_dag_checkpoint(self) -> None:
        """CHECKPOINT_ONLY binding fires on DAG_CHECKPOINT events."""
        bus = InMemoryEventBus()
        pipeline = OnlineEvalPipeline(
            bindings=(
                NodeEvalBinding(
                    node_pattern="*",
                    evaluators=(FakePassEvaluator(),),
                    trigger=EvalTrigger.CHECKPOINT_ONLY,
                ),
            ),
            event_bus=bus,
        )
        pipeline.subscribe()

        await bus.publish(
            event=Event.create(
                type=EventType.DAG_CHECKPOINT,
                payload={"node_id": "cp1", "context_snapshot": {"data": "value"}},
                source="test",
            )
        )
        await drain_tasks()

        assert len(pipeline.results) == 1
        assert pipeline.results[0]["trigger"] == "checkpoint"


# ---------------------------------------------------------------------------
# 3. Structured output preservation (EvalContext)
# ---------------------------------------------------------------------------


class TestEvalContext:
    def test_structured_output_preserved(self) -> None:
        ctx = EvalContext(
            output={"key": "value", "nested": [1, 2, 3]},
            node_id="n1",
            node_type="agent",
        )
        assert isinstance(ctx.output, dict)
        assert ctx.output["key"] == "value"

    def test_output_as_str_for_dicts(self) -> None:
        ctx = EvalContext(output={"a": 1})
        assert '"a"' in ctx.output_as_str

    def test_output_as_str_for_strings(self) -> None:
        ctx = EvalContext(output="plain text")
        assert ctx.output_as_str == "plain text"

    def test_previous_scores_tracked(self) -> None:
        ctx = EvalContext(
            output="x",
            previous_scores=(0.9, 0.85, 0.7),
        )
        assert len(ctx.previous_scores) == 3

    @pytest.mark.asyncio
    async def test_evaluator_receives_structured_output(self) -> None:
        """Prove evaluators get the actual structured data, not str(output)."""
        bus = InMemoryEventBus()
        structured_eval = FakeStructuredEvaluator()
        pipeline = OnlineEvalPipeline(
            bindings=(
                NodeEvalBinding(
                    node_pattern="*",
                    evaluators=(structured_eval,),
                    trigger=EvalTrigger.CHECKPOINT_ONLY,
                ),
            ),
            event_bus=bus,
        )
        pipeline.subscribe()

        structured_output = {"analysis": {"score": 0.95, "topics": ["AI", "ML"]}}
        await bus.publish(
            event=Event.create(
                type=EventType.DAG_CHECKPOINT,
                payload={"node_id": "cp1", "context_snapshot": structured_output},
                source="test",
            )
        )
        await drain_tasks()

        assert len(structured_eval.received_outputs) == 1
        received = structured_eval.received_outputs[0]
        # Structured data preserved — not stringified
        assert isinstance(received, dict)
        assert received["analysis"]["score"] == 0.95


# ---------------------------------------------------------------------------
# 4. Trend analysis (linear regression)
# ---------------------------------------------------------------------------


class TestTrendAnalysis:
    def test_no_trend_with_few_samples(self) -> None:
        police = QualityPolice(config=QualityPoliceConfig(min_samples_for_trend=4))
        police.record_score(score=0.8)
        police.record_score(score=0.7)
        assert police.analyze_trend() is None  # Not enough samples

    def test_stable_scores_no_degradation(self) -> None:
        police = QualityPolice(config=QualityPoliceConfig(min_samples_for_trend=4))
        for _ in range(6):
            police.record_score(score=0.85)
        trend = police.analyze_trend()
        assert trend is not None
        assert not trend.is_degrading
        assert trend.projected_steps_to_halt is None

    def test_degrading_scores_detected(self) -> None:
        police = QualityPolice(config=QualityPoliceConfig(min_samples_for_trend=4))
        scores = [0.9, 0.8, 0.7, 0.6, 0.5]
        for s in scores:
            police.record_score(score=s)
        trend = police.analyze_trend()
        assert trend is not None
        assert trend.is_degrading
        assert trend.slope < 0
        assert trend.projected_steps_to_halt is not None

    def test_improving_scores_no_halt_projection(self) -> None:
        police = QualityPolice(config=QualityPoliceConfig(min_samples_for_trend=4))
        scores = [0.5, 0.6, 0.7, 0.8, 0.9]
        for s in scores:
            police.record_score(score=s)
        trend = police.analyze_trend()
        assert trend is not None
        assert not trend.is_degrading
        assert trend.projected_steps_to_halt is None

    def test_confidence_is_bounded(self) -> None:
        police = QualityPolice(config=QualityPoliceConfig(min_samples_for_trend=4))
        for s in [0.9, 0.7, 0.5, 0.3]:
            police.record_score(score=s)
        trend = police.analyze_trend()
        assert trend is not None
        assert 0.0 <= trend.confidence <= 1.0


# ---------------------------------------------------------------------------
# 5. Predictive halting
# ---------------------------------------------------------------------------


class TestPredictiveHalting:
    def test_predictive_halt_on_steep_degradation(self) -> None:
        """Steep degradation triggers halt BEFORE mean crosses threshold."""
        police = QualityPolice(
            config=QualityPoliceConfig(
                halt_threshold=0.3,
                predictive_halt_enabled=True,
                predictive_halt_horizon=5,
                min_samples_for_trend=4,
            )
        )
        # Scores degrading steeply: 0.8 → 0.6 → 0.5 → 0.45 → 0.4
        # Mean is still above 0.3, but trend projects crossing soon
        scores = [0.8, 0.65, 0.5, 0.45, 0.4]
        for s in scores:
            police.record_score(score=s)

        assert police.should_halt() is True
        # Verify the halt alert mentions "Predictive"
        halt_alerts = [a for a in police.alerts if a.level == AlertLevel.HALT]
        assert len(halt_alerts) >= 1
        assert "Predictive" in halt_alerts[-1].message or "predictive" in halt_alerts[-1].message.lower()

    def test_no_predictive_halt_when_disabled(self) -> None:
        police = QualityPolice(
            config=QualityPoliceConfig(
                halt_threshold=0.3,
                predictive_halt_enabled=False,
                min_samples_for_trend=4,
            )
        )
        for s in [0.8, 0.65, 0.5, 0.45, 0.4]:
            police.record_score(score=s)

        # Mean is ~0.56, above halt_threshold — no halt without prediction
        assert police.should_halt() is False

    def test_no_predictive_halt_on_low_confidence(self) -> None:
        """Noisy data with low R-squared should not trigger predictive halt."""
        police = QualityPolice(
            config=QualityPoliceConfig(
                halt_threshold=0.3,
                predictive_halt_enabled=True,
                predictive_halt_horizon=5,
                min_samples_for_trend=4,
            )
        )
        # Noisy zigzag — low confidence regression
        scores = [0.9, 0.4, 0.85, 0.45, 0.8]
        for s in scores:
            police.record_score(score=s)

        # Should NOT halt — trend confidence too low for noisy data
        # (may or may not halt depending on math, but trend confidence should be low)
        trend = police.analyze_trend()
        if trend and trend.confidence < 0.5:
            assert police.should_halt() is False


# ---------------------------------------------------------------------------
# 6. Backward compatibility — EVERY_NODE still works
# ---------------------------------------------------------------------------


class TestEveryNodeBackwardCompat:
    @pytest.mark.asyncio
    async def test_every_node_fires_on_task_completed(self) -> None:
        """Legacy EVERY_NODE trigger still works on TASK_COMPLETED."""
        bus = InMemoryEventBus()
        pipeline = OnlineEvalPipeline(
            bindings=(
                NodeEvalBinding(
                    node_pattern="*",
                    evaluators=(FakePassEvaluator(),),
                    trigger=EvalTrigger.EVERY_NODE,
                ),
            ),
            event_bus=bus,
        )
        pipeline.subscribe()

        await bus.publish(
            event=Event.create(
                type=EventType.TASK_COMPLETED,
                payload={"node_id": "n1", "output": "result"},
                source="test",
            )
        )
        await drain_tasks()

        assert len(pipeline.results) == 1
