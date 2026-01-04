"""
Factory functions for context compilers.

Provides convenient ways to create context compiler instances
with sensible defaults while maintaining dependency injection principles.

All factories follow the DI-friendly pattern:
- Accept explicit dependencies for testing/customization
- Support config objects for structured configuration
- Support overrides dict for partial customization
- Provide from_config() variants for environment-based setup

Example:
    # Explicit injection (testing)
    compiler = create_priority_compiler(
        token_estimator=MockTokenEstimator(),
        algorithm=MockAlgorithm(),
    )

    # Config-based (production)
    compiler = create_priority_compiler(
        config=CompilerConfig(chars_per_token=3.5),
    )

    # Environment-based
    compiler = create_context_compiler_from_config()
"""

import os
from dataclasses import dataclass, field
from typing import Any

from cemaf.context.algorithm import (
    ContextSelectionAlgorithm,
    GreedySelectionAlgorithm,
    KnapsackSelectionAlgorithm,
    OptimalSelectionAlgorithm,
)
from cemaf.context.compiler import (
    ContextCompiler,
    PriorityContextCompiler,
    SimpleTokenEstimator,
    TokenEstimator,
)


@dataclass
class CompilerConfig:
    """Configuration for context compilers."""

    chars_per_token: float = 4.0
    algorithm: str = "greedy"
    max_sources_for_optimal: int = 20


@dataclass
class FactoryOverrides:
    """
    Override specific factory dependencies.

    Use this to inject mocks or custom implementations
    while keeping other defaults.
    """

    token_estimator: TokenEstimator | None = None
    algorithm: ContextSelectionAlgorithm | None = None
    llm_client: Any | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def create_priority_compiler(
    token_estimator: TokenEstimator | None = None,
    chars_per_token: float = 4.0,
    algorithm: ContextSelectionAlgorithm | None = None,
    config: CompilerConfig | None = None,
    overrides: FactoryOverrides | None = None,
) -> PriorityContextCompiler:
    """
    Factory for PriorityContextCompiler with sensible defaults.

    Supports three usage patterns:
    1. Explicit injection: Pass dependencies directly
    2. Config-based: Use CompilerConfig for structured settings
    3. Override-based: Use FactoryOverrides for partial customization

    Args:
        token_estimator: Custom token estimation strategy (optional)
        chars_per_token: Characters per token for default estimator
        algorithm: Selection algorithm to use (defaults to GreedySelectionAlgorithm)
        config: Structured configuration (optional)
        overrides: Dependency overrides for testing (optional)

    Returns:
        Configured PriorityContextCompiler instance

    Example:
        # Simple usage with defaults
        compiler = create_priority_compiler()

        # Explicit injection (for testing)
        compiler = create_priority_compiler(
            token_estimator=MockTokenEstimator(),
            algorithm=MockAlgorithm(),
        )

        # Config-based
        compiler = create_priority_compiler(
            config=CompilerConfig(chars_per_token=3.5, algorithm="knapsack"),
        )

        # Override-based (for testing with partial mocks)
        compiler = create_priority_compiler(
            overrides=FactoryOverrides(token_estimator=MockEstimator()),
        )
    """
    # Apply config if provided
    if config:
        chars_per_token = config.chars_per_token

    # Apply overrides if provided
    if overrides:
        token_estimator = overrides.token_estimator or token_estimator
        algorithm = overrides.algorithm or algorithm

    # Build with defaults for missing dependencies
    estimator = token_estimator or SimpleTokenEstimator(chars_per_token)
    return PriorityContextCompiler(estimator, algorithm=algorithm)


def create_advanced_compiler(
    llm_client,  # LLMClient type (avoid circular import)
    token_estimator: TokenEstimator | None = None,
    config=None,  # AdvancedCompilerConfig type (avoid circular import)
    algorithm: ContextSelectionAlgorithm | None = None,
) -> ContextCompiler:
    """
    Factory for AdvancedContextCompiler with sensible defaults.

    Args:
        llm_client: LLM client for summarization
        token_estimator: Custom token estimation strategy (optional)
        config: Compiler configuration (optional)
        algorithm: Selection algorithm (optional)
            - If None (default): Pure summarization mode (includes all sources)
            - If provided: Two-stage mode (algorithm selects, then summarization fallback)

    Returns:
        Configured AdvancedContextCompiler instance

    Example:
        # Mode 1: Pure summarization (default)
        compiler = create_advanced_compiler(llm_client=llm)

        # Mode 2: Two-stage with knapsack algorithm
        algorithm = KnapsackSelectionAlgorithm()
        compiler = create_advanced_compiler(llm_client=llm, algorithm=algorithm)
    """
    from cemaf.context.advanced_compiler import AdvancedContextCompiler

    estimator = token_estimator or SimpleTokenEstimator()
    return AdvancedContextCompiler(llm_client, estimator, config, algorithm=algorithm)


def create_greedy_compiler(
    token_estimator: TokenEstimator | None = None,
    chars_per_token: float = 4.0,
) -> PriorityContextCompiler:
    """
    Factory for PriorityContextCompiler with greedy selection algorithm.

    Convenience factory that explicitly uses GreedySelectionAlgorithm.

    Args:
        token_estimator: Custom token estimation strategy (optional)
        chars_per_token: Characters per token for default estimator

    Returns:
        PriorityContextCompiler with greedy algorithm

    Example:
        compiler = create_greedy_compiler()
    """
    estimator = token_estimator or SimpleTokenEstimator(chars_per_token)
    return PriorityContextCompiler(estimator, algorithm=GreedySelectionAlgorithm())


def create_knapsack_compiler(
    token_estimator: TokenEstimator | None = None,
    chars_per_token: float = 4.0,
) -> PriorityContextCompiler:
    """
    Factory for PriorityContextCompiler with knapsack selection algorithm.

    Uses 0/1 knapsack dynamic programming for optimal priority maximization.

    Args:
        token_estimator: Custom token estimation strategy (optional)
        chars_per_token: Characters per token for default estimator

    Returns:
        PriorityContextCompiler with knapsack algorithm

    Example:
        compiler = create_knapsack_compiler()
    """
    estimator = token_estimator or SimpleTokenEstimator(chars_per_token)
    return PriorityContextCompiler(estimator, algorithm=KnapsackSelectionAlgorithm())


def create_optimal_compiler(
    token_estimator: TokenEstimator | None = None,
    chars_per_token: float = 4.0,
    max_sources: int = 20,
) -> PriorityContextCompiler:
    """
    Factory for PriorityContextCompiler with optimal selection algorithm.

    Uses brute force for small sets, falls back to knapsack for larger sets.

    Args:
        token_estimator: Custom token estimation strategy (optional)
        chars_per_token: Characters per token for default estimator
        max_sources: Maximum sources to use brute force on (default: 20)

    Returns:
        PriorityContextCompiler with optimal algorithm

    Example:
        compiler = create_optimal_compiler(max_sources=15)
    """
    estimator = token_estimator or SimpleTokenEstimator(chars_per_token)
    return PriorityContextCompiler(estimator, algorithm=OptimalSelectionAlgorithm(max_sources=max_sources))


def create_context_compiler_from_config(
    algorithm_name: str | None = None,
    token_estimator: TokenEstimator | None = None,
) -> ContextCompiler:
    """
    Create context compiler from environment configuration.

    Reads from environment variables:
    - CEMAF_CONTEXT_SELECTION_ALGORITHM: Algorithm type (greedy, knapsack, optimal)

    Args:
        algorithm_name: Algorithm type (overrides env var)
        token_estimator: Custom token estimator (optional)

    Returns:
        Configured ContextCompiler instance

    Example:
        # From environment
        compiler = create_context_compiler_from_config()

        # Explicit algorithm
        compiler = create_context_compiler_from_config(algorithm_name="knapsack")
    """
    algorithm = algorithm_name or os.getenv("CEMAF_CONTEXT_SELECTION_ALGORITHM", "greedy")

    if algorithm == "greedy":
        return create_greedy_compiler(token_estimator=token_estimator)
    elif algorithm == "knapsack":
        return create_knapsack_compiler(token_estimator=token_estimator)
    elif algorithm == "optimal":
        max_sources = int(os.getenv("CEMAF_CONTEXT_OPTIMAL_MAX_SOURCES", "20"))
        return create_optimal_compiler(token_estimator=token_estimator, max_sources=max_sources)
    else:
        raise ValueError(
            f"Unsupported context selection algorithm: {algorithm}. Supported: greedy, knapsack, optimal"
        )
