"""
Factory functions for evaluation components.

Provides convenient ways to create evaluators with sensible defaults
while maintaining dependency injection principles.
"""

import os

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.evals.composite import CompositeEvaluator
from cemaf.evals.evaluators import ExactMatchEvaluator
from cemaf.evals.online import EvalMode, EvalTrigger, NodeEvalBinding, OnlineEvalPipeline
from cemaf.evals.police import QualityPolice, QualityPoliceConfig
from cemaf.evals.protocols import EvalConfig, Evaluator
from cemaf.events.protocols import EventBus


def create_exact_match_evaluator(
    case_sensitive: bool = False,
) -> ExactMatchEvaluator:
    """Create an ExactMatchEvaluator with common defaults."""
    return ExactMatchEvaluator(case_sensitive=case_sensitive)


def create_composite_evaluator(
    evaluators: list[Evaluator] | None = None,
    pass_threshold: float = 0.5,
) -> CompositeEvaluator:
    """Create a CompositeEvaluator from a list of evaluators."""
    return CompositeEvaluator(
        evaluators=evaluators or [],
        config=EvalConfig(pass_threshold=pass_threshold),
    )


def create_composite_evaluator_from_config(
    evaluators: list[Evaluator] | None = None,
    settings: Settings | None = None,
) -> CompositeEvaluator:
    """Create a CompositeEvaluator from environment configuration."""
    cfg = settings or load_settings_from_env_sync()  # noqa: F841

    pass_threshold = float(os.getenv("CEMAF_EVALS_PASS_THRESHOLD", "0.5"))

    return create_composite_evaluator(
        evaluators=evaluators,
        pass_threshold=pass_threshold,
    )


def create_node_eval_binding(
    *,
    node_pattern: str,
    evaluators: tuple[Evaluator, ...],
    mode: EvalMode = EvalMode.OBSERVE,
    expected: str | None = None,
    trigger: EvalTrigger = EvalTrigger.EVERY_NODE,
) -> NodeEvalBinding:
    """Create a NodeEvalBinding with explicit evaluator wiring."""
    return NodeEvalBinding(
        node_pattern=node_pattern,
        evaluators=evaluators,
        mode=mode,
        expected=expected,
        trigger=trigger,
    )


def create_online_eval_pipeline(
    *,
    bindings: tuple[NodeEvalBinding, ...],
    event_bus: EventBus,
    subscribe: bool = False,
) -> OnlineEvalPipeline:
    """Create an OnlineEvalPipeline and optionally subscribe it to the event bus."""
    pipeline = OnlineEvalPipeline(bindings=bindings, event_bus=event_bus)
    if subscribe:
        pipeline.subscribe()
    return pipeline


def create_quality_police(
    *,
    config: QualityPoliceConfig | None = None,
    event_bus: EventBus | None = None,
    subscribe: bool = False,
    window_size: int = 20,
    warn_threshold: float = 0.7,
    critical_threshold: float = 0.5,
    halt_threshold: float = 0.3,
    anomaly_drop: float = 0.3,
    predictive_halt_enabled: bool = True,
    predictive_halt_horizon: int = 5,
    min_samples_for_trend: int = 4,
) -> QualityPolice:
    """Create a QualityPolice monitor with optional event-bus subscription."""
    resolved_config = config or QualityPoliceConfig(
        window_size=window_size,
        warn_threshold=warn_threshold,
        critical_threshold=critical_threshold,
        halt_threshold=halt_threshold,
        anomaly_drop=anomaly_drop,
        predictive_halt_enabled=predictive_halt_enabled,
        predictive_halt_horizon=predictive_halt_horizon,
        min_samples_for_trend=min_samples_for_trend,
    )
    police = QualityPolice(config=resolved_config)
    if subscribe and event_bus is not None:
        police.subscribe(event_bus=event_bus)
    return police
