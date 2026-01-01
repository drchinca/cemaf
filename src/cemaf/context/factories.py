"""
Factory functions for context compilers.

Provides convenient ways to create context compiler instances
with sensible defaults while maintaining dependency injection principles.
"""

import os

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


def create_priority_compiler(
    token_estimator: TokenEstimator | None = None,
    chars_per_token: float = 4.0,
    algorithm: ContextSelectionAlgorithm | None = None,
) -> PriorityContextCompiler:
    """
    Factory for PriorityContextCompiler with sensible defaults.

    Args:
        token_estimator: Custom token estimation strategy (optional)
        chars_per_token: Characters per token for default estimator
        algorithm: Selection algorithm to use (defaults to GreedySelectionAlgorithm)

    Returns:
        Configured PriorityContextCompiler instance

    Example:
        # With defaults (greedy algorithm)
        compiler = create_priority_compiler()

        # With custom estimator
        estimator = TiktokenEstimator()
        compiler = create_priority_compiler(token_estimator=estimator)

        # With knapsack algorithm
        algorithm = KnapsackSelectionAlgorithm()
        compiler = create_priority_compiler(algorithm=algorithm)
    """
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
