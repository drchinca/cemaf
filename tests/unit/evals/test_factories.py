"""Tests for evaluation factory functions."""

from cemaf.evals.evaluators import ContainsEvaluator
from cemaf.evals.factories import (
    create_node_eval_binding,
    create_online_eval_pipeline,
    create_quality_police,
)
from cemaf.evals.online import EvalMode, EvalTrigger, OnlineEvalPipeline
from cemaf.evals.police import QualityPolice
from cemaf.events.bus import InMemoryEventBus


def test_create_node_eval_binding_preserves_fields() -> None:
    evaluator = ContainsEvaluator()

    binding = create_node_eval_binding(
        node_pattern="quality",
        evaluators=(evaluator,),
        mode=EvalMode.OBSERVE,
        trigger=EvalTrigger.CHECKPOINT_ONLY,
    )

    assert binding.node_pattern == "quality"
    assert binding.evaluators == (evaluator,)
    assert binding.mode == EvalMode.OBSERVE
    assert binding.trigger == EvalTrigger.CHECKPOINT_ONLY


def test_create_online_eval_pipeline_wires_bus_without_auto_subscribe() -> None:
    bus = InMemoryEventBus()
    binding = create_node_eval_binding(node_pattern="*", evaluators=(ContainsEvaluator(),))

    pipeline = create_online_eval_pipeline(bindings=(binding,), event_bus=bus)

    assert isinstance(pipeline, OnlineEvalPipeline)
    assert pipeline.results == []


def test_create_quality_police_uses_thresholds() -> None:
    police = create_quality_police(window_size=3, warn_threshold=0.8, anomaly_drop=1.0)

    assert isinstance(police, QualityPolice)
    for _ in range(3):
        alert = police.record_score(score=0.7)

    assert alert is not None
    assert alert.level.value == "warn"
