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
from cemaf.evals.protocols import EvalConfig, Evaluator


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
