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

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from cemaf.context.algorithm import (
    ContextSelectionAlgorithm,
    GreedySelectionAlgorithm,
    KnapsackSelectionAlgorithm,
    OptimalSelectionAlgorithm,
)
from cemaf.context.budget import BudgetAllocation, TokenBudget
from cemaf.context.compiler import (
    AdvancedCompilerConfig,
    ContextCompiler,
    PriorityContextCompiler,
    SimpleTokenEstimator,
    TokenEstimator,
)
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.llm.protocols import LLMClient


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
    llm_client: LLMClient | None = None
    extra: dict[str, Any] = field(default_factory=dict)


token_estimator_registry: ProviderRegistry[TokenEstimator] = ProviderRegistry(name="token_estimator")
context_selection_algorithm_registry: ProviderRegistry[ContextSelectionAlgorithm] = ProviderRegistry(
    name="context_selection_algorithm"
)


def _create_simple_token_estimator(**kwargs: Any) -> TokenEstimator:
    return SimpleTokenEstimator(chars_per_token=float(kwargs.get("chars_per_token", 4.0)))


def _create_tiktoken_estimator(**kwargs: Any) -> TokenEstimator:
    model = kwargs.get("model")
    if not model:
        raise ValueError("tiktoken token estimator requires model.")

    from cemaf.llm.tiktoken_estimator import TiktokenEstimator

    return TiktokenEstimator(model=str(model))


token_estimator_registry.register(backend="simple", factory=_create_simple_token_estimator)
token_estimator_registry.register(backend="tiktoken", factory=_create_tiktoken_estimator)


def _create_greedy_algorithm(**kwargs: Any) -> ContextSelectionAlgorithm:
    return GreedySelectionAlgorithm()


def _create_knapsack_algorithm(**kwargs: Any) -> ContextSelectionAlgorithm:
    return KnapsackSelectionAlgorithm()


def _create_optimal_algorithm(**kwargs: Any) -> ContextSelectionAlgorithm:
    return OptimalSelectionAlgorithm(max_sources=int(kwargs.get("max_sources", 20)))


context_selection_algorithm_registry.register(backend="greedy", factory=_create_greedy_algorithm)
context_selection_algorithm_registry.register(backend="knapsack", factory=_create_knapsack_algorithm)
context_selection_algorithm_registry.register(backend="optimal", factory=_create_optimal_algorithm)


def create_context_selection_algorithm(
    algorithm_name: str = "greedy",
    **algorithm_options: Any,
) -> ContextSelectionAlgorithm:
    """Create a context selection algorithm through the registry."""
    return context_selection_algorithm_registry.create(
        backend=algorithm_name,
        **algorithm_options,
    )


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
        if algorithm is None:
            algorithm = create_context_selection_algorithm(
                config.algorithm,
                max_sources=config.max_sources_for_optimal,
            )

    # Apply overrides if provided
    if overrides:
        token_estimator = overrides.token_estimator or token_estimator
        algorithm = overrides.algorithm or algorithm

    # Build with defaults for missing dependencies
    estimator = token_estimator or create_token_estimator(chars_per_token=chars_per_token)
    return PriorityContextCompiler(estimator, algorithm=algorithm)


def create_advanced_compiler(
    llm_client: LLMClient,
    token_estimator: TokenEstimator | None = None,
    config: AdvancedCompilerConfig | None = None,
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

    estimator = token_estimator or create_token_estimator(chars_per_token=3.5)
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
    estimator = token_estimator or create_token_estimator(chars_per_token=chars_per_token)
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
    estimator = token_estimator or create_token_estimator(chars_per_token=chars_per_token)
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
    estimator = token_estimator or create_token_estimator(chars_per_token=chars_per_token)
    return PriorityContextCompiler(estimator, algorithm=OptimalSelectionAlgorithm(max_sources=max_sources))


# Global context compiler registry — extend with your own algorithms
context_compiler_registry: ProviderRegistry[ContextCompiler] = ProviderRegistry(name="context_compiler")

context_compiler_registry.register(
    backend="greedy",
    factory=lambda **kw: PriorityContextCompiler(
        kw["token_estimator"],
        algorithm=create_context_selection_algorithm("greedy"),
    ),
)
context_compiler_registry.register(
    backend="knapsack",
    factory=lambda **kw: PriorityContextCompiler(
        kw["token_estimator"],
        algorithm=create_context_selection_algorithm("knapsack"),
    ),
)
context_compiler_registry.register(
    backend="optimal",
    factory=lambda **kw: PriorityContextCompiler(
        kw["token_estimator"],
        algorithm=create_context_selection_algorithm(
            "optimal",
            max_sources=int(kw.get("max_sources", 20)),
        ),
    ),
)


def create_context_compiler_from_config(
    algorithm_name: str | None = None,
    token_estimator: TokenEstimator | None = None,
) -> ContextCompiler:
    """Create context compiler from environment configuration."""
    algorithm = algorithm_name or os.getenv("CEMAF_CONTEXT_SELECTION_ALGORITHM", "greedy")
    assert algorithm is not None  # always set by getenv default
    resolved_token_estimator = token_estimator or create_token_estimator_from_config()

    return context_compiler_registry.create(
        backend=algorithm,
        token_estimator=resolved_token_estimator,
        max_sources=int(os.getenv("CEMAF_CONTEXT_OPTIMAL_MAX_SOURCES", "20")),
    )


def create_token_estimator(
    model: str | None = None,
    chars_per_token: float = 4.0,
    estimator_type: str | None = None,
    **estimator_options: Any,
) -> TokenEstimator:
    """Create a token estimator, preferring tiktoken when a known model is provided."""
    options = {
        "model": model,
        "chars_per_token": chars_per_token,
        **estimator_options,
    }
    if estimator_type:
        return token_estimator_registry.create(backend=estimator_type, **options)

    if model:
        estimator = token_estimator_registry.create(backend="tiktoken", **options)
        if bool(getattr(estimator, "is_accurate", False)):
            return estimator
    return token_estimator_registry.create(backend="simple", **options)


def create_token_estimator_from_config(**estimator_options: Any) -> TokenEstimator:
    """Create a token estimator from environment configuration."""
    estimator_type = os.getenv("CEMAF_CONTEXT_TOKEN_ESTIMATOR_BACKEND")
    model = os.getenv("CEMAF_CONTEXT_TOKEN_ESTIMATOR_MODEL")
    chars_per_token = float(os.getenv("CEMAF_CONTEXT_CHARS_PER_TOKEN", "4.0"))
    return create_token_estimator(
        model=model,
        chars_per_token=chars_per_token,
        estimator_type=estimator_type,
        **estimator_options,
    )


def create_token_budget(
    *,
    max_tokens: int | None = None,
    reserved_for_output: int | None = None,
    allocations: tuple[BudgetAllocation, ...] = (),
    metadata: dict[str, Any] | None = None,
    model: str | None = None,
) -> TokenBudget:
    """Create a TokenBudget, optionally deriving defaults from a model name."""
    budget = TokenBudget.for_model(model) if model else TokenBudget.default()
    return TokenBudget(
        max_tokens=max_tokens if max_tokens is not None else budget.max_tokens,
        reserved_for_output=(
            reserved_for_output if reserved_for_output is not None else budget.reserved_for_output
        ),
        allocations=allocations,
        metadata=metadata or {},
    )
