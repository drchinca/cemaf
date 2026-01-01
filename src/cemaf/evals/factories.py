"""
Factory functions for evaluation components.

Provides convenient ways to create evaluators with sensible defaults
while maintaining dependency injection principles.
"""

import os

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.evals.composite import CompositeEvaluator
from cemaf.evals.evaluators import ExactMatchEvaluator, NumericEvaluator
from cemaf.evals.protocols import Evaluator


def create_exact_match_evaluator(
    case_sensitive: bool = False,
) -> ExactMatchEvaluator:
    """
    Factory for ExactMatchEvaluator with sensible defaults.

    Args:
        case_sensitive: Enable case-sensitive matching

    Returns:
        Configured ExactMatchEvaluator instance

    Example:
        # Case-insensitive (default)
        evaluator = create_exact_match_evaluator()

        # Case-sensitive
        evaluator = create_exact_match_evaluator(case_sensitive=True)
    """
    return ExactMatchEvaluator(case_sensitive=case_sensitive)


def create_numeric_evaluator(
    tolerance: float = 0.01,
) -> NumericEvaluator:
    """
    Factory for NumericEvaluator with sensible defaults.

    Args:
        tolerance: Tolerance for numeric comparison

    Returns:
        Configured NumericEvaluator instance

    Example:
        # With defaults
        evaluator = create_numeric_evaluator()

        # Higher tolerance
        evaluator = create_numeric_evaluator(tolerance=0.1)
    """
    return NumericEvaluator(tolerance=tolerance)


def create_composite_evaluator(
    evaluators: list[Evaluator] | None = None,
    pass_threshold: float = 0.5,
) -> CompositeEvaluator:
    """
    Factory for CompositeEvaluator with sensible defaults.

    Args:
        evaluators: List of evaluators to compose
        pass_threshold: Minimum score to pass

    Returns:
        Configured CompositeEvaluator instance

    Example:
        # With defaults
        evaluator = create_composite_evaluator()

        # With evaluators
        evals = [create_exact_match_evaluator(), create_numeric_evaluator()]
        evaluator = create_composite_evaluator(evaluators=evals)
    """
    return CompositeEvaluator(
        evaluators=evaluators or [],
        pass_threshold=pass_threshold,
    )


def create_composite_evaluator_from_config(
    evaluators: list[Evaluator] | None = None,
    settings: Settings | None = None,
) -> CompositeEvaluator:
    """
    Create CompositeEvaluator from environment configuration.

    Reads from environment variables:
    - CEMAF_EVALS_PASS_THRESHOLD: Pass threshold (default: 0.5)

    Args:
        evaluators: List of evaluators (overrides defaults)

    Returns:
        Configured CompositeEvaluator instance

    Example:
        # From environment
        evaluator = create_composite_evaluator_from_config()

        # With custom evaluators
        evaluator = create_composite_evaluator_from_config(evaluators=[my_eval])
    """
    cfg = settings or load_settings_from_env_sync()  # noqa: F841

    pass_threshold = float(os.getenv("CEMAF_EVALS_PASS_THRESHOLD", "0.5"))

    return create_composite_evaluator(
        evaluators=evaluators,
        pass_threshold=pass_threshold,
    )
