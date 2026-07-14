"""Tests for evaluation factory functions."""

from cemaf.config.protocols import EvalsSettings, Settings
from cemaf.evals.evaluators import ContainsEvaluator, ExactMatchEvaluator
from cemaf.evals.factories import (
    create_composite_evaluator_from_config,
    create_evaluator,
    create_node_eval_binding,
    create_online_eval_pipeline,
    create_quality_police,
    create_single_node_eval_pipeline,
    evaluator_registry,
)
from cemaf.evals.online import EvalMode, EvalTrigger, OnlineEvalPipeline
from cemaf.evals.police import QualityPolice
from cemaf.evals.protocols import EvalMetric, EvalResult
from cemaf.evals.tools import resolve_evaluators
from cemaf.events.bus import InMemoryEventBus


class CustomEvaluator:
    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.CUSTOM

    @property
    def name(self) -> str:
        return "custom"

    async def evaluate(self, output, expected=None, context=None):  # noqa: ANN001, ANN201
        return EvalResult.passed_result(metric=EvalMetric.CUSTOM, reason="custom")


def test_create_evaluator_uses_builtin_registry() -> None:
    evaluator = create_evaluator("exact_match")

    assert isinstance(evaluator, ExactMatchEvaluator)


def test_create_evaluator_supports_custom_registered_backend() -> None:
    created: dict[str, object] = {}

    def _factory(**kwargs):
        created["args"] = kwargs
        return CustomEvaluator()

    evaluator_registry.register(backend="custom-eval", factory=_factory)

    evaluator = create_evaluator("custom-eval", threshold=0.9)

    assert isinstance(evaluator, CustomEvaluator)
    assert created["args"]["threshold"] == 0.9


def test_create_composite_evaluator_from_config_uses_settings(
    monkeypatch,
) -> None:
    monkeypatch.delenv("CEMAF_EVALS_PASS_THRESHOLD", raising=False)
    settings = Settings(evals=EvalsSettings(pass_threshold=0.82))

    evaluator = create_composite_evaluator_from_config(settings=settings)

    assert evaluator._config.pass_threshold == 0.82


def test_resolve_evaluators_uses_custom_registered_backend() -> None:
    evaluator_registry.register(backend="tool-custom-eval", factory=lambda **_: CustomEvaluator())

    evaluators = resolve_evaluators(["tool-custom-eval"])

    assert len(evaluators) == 1
    assert isinstance(evaluators[0], CustomEvaluator)


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


def test_create_single_node_eval_pipeline_builds_single_binding() -> None:
    bus = InMemoryEventBus()
    evaluator = ContainsEvaluator()

    pipeline = create_single_node_eval_pipeline(
        node_pattern="quality",
        evaluators=(evaluator,),
        event_bus=bus,
        trigger=EvalTrigger.CHECKPOINT_ONLY,
    )

    assert isinstance(pipeline, OnlineEvalPipeline)
    assert len(pipeline._bindings) == 1
    binding = pipeline._bindings[0]
    assert binding.node_pattern == "quality"
    assert binding.evaluators == (evaluator,)
    assert binding.trigger == EvalTrigger.CHECKPOINT_ONLY
