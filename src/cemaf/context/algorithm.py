"""
Context Selection Algorithm Protocol - Extensible algorithm interface for context compilation.

This module provides:
- ContextSelectionAlgorithm: Protocol for implementing selection strategies
- SelectionResult: Immutable result of algorithm execution
- Built-in implementations: Greedy, Knapsack, Optimal algorithms

Engineers can implement custom algorithms by conforming to the protocol.

Note: Uses PEP 563 (from __future__ import annotations) to defer annotation evaluation
and avoid circular imports with cemaf.context.source.
Type imports happen at runtime within methods that need them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from cemaf.context.budget import TokenBudget
from cemaf.core.types import JSON


@dataclass(frozen=True)
class SelectionResult:
    """
    Immutable result of context selection algorithm execution.

    Contains selected sources, token count, and algorithm-specific metadata.
    """

    selected_sources: tuple[ContextSource, ...]  # noqa: F821
    total_tokens: int
    metadata: JSON = field(default_factory=dict)

    @property
    def excluded_count(self) -> int:
        """Number of sources that were excluded (if available in metadata)."""
        return self.metadata.get("excluded_count", 0)

    @property
    def excluded_keys(self) -> list[str]:
        """Keys of sources that were excluded (if available in metadata)."""
        return self.metadata.get("excluded_keys", [])

    @property
    def selection_method(self) -> str:
        """Algorithm method used (e.g., 'greedy', 'knapsack', 'optimal')."""
        return self.metadata.get("selection_method", "unknown")


@runtime_checkable
class ContextSelectionAlgorithm(Protocol):
    """
    Protocol for context selection algorithms.

    Implementations select which sources to include within token budget constraints.

    Example:
        class MyAlgorithm:
            def select_sources(
                self,
                sources: list[ContextSource],  # noqa: F821
                budget: TokenBudget,
            ) -> SelectionResult:
                # Custom selection logic
                selected = [...]
                return SelectionResult(
                    selected_sources=tuple(selected),
                    total_tokens=sum(s.token_count for s in selected),
                    metadata={"selection_method": "my_algorithm"},
                )
    """

    def select_sources(
        self,
        sources: list[ContextSource],  # noqa: F821
        budget: TokenBudget,
    ) -> SelectionResult:
        """
        Select sources that fit within token budget.

        Args:
            sources: All available context sources (may be pre-sorted)
            budget: Token budget constraints

        Returns:
            SelectionResult with selected sources and metadata
        """
        ...


class GreedySelectionAlgorithm:
    """
    Greedy selection algorithm: includes highest priority sources first.

    Strategy:
    1. Sources should be pre-sorted by priority (descending)
    2. Includes sources in order until budget exhausted
    3. Skips sources that don't fit

    Time Complexity: O(n) where n = number of sources
    Space Complexity: O(n)

    Optimality: Not guaranteed - may miss better combinations
    """

    def select_sources(
        self,
        sources: list[ContextSource],  # noqa: F821
        budget: TokenBudget,
    ) -> SelectionResult:
        """
        Select sources using greedy algorithm.

        Assumes sources are already sorted by priority (descending).
        If not sorted, results may be suboptimal.
        """
        selected_sources: list[ContextSource] = []  # noqa: F821
        total_tokens = 0
        available_tokens = budget.available_tokens

        excluded_keys: list[str] = []

        for source in sources:
            if total_tokens + source.token_count <= available_tokens:
                selected_sources.append(source)
                total_tokens += source.token_count
            else:
                excluded_keys.append(source.key)

        return SelectionResult(
            selected_sources=tuple(selected_sources),
            total_tokens=total_tokens,
            metadata={
                "selection_method": "greedy",
                "excluded_count": len(excluded_keys),
                "excluded_keys": excluded_keys,
                "sources_considered": len(sources),
                "sources_included": len(selected_sources),
            },
        )


class KnapsackSelectionAlgorithm:
    """
    Knapsack-based selection algorithm: maximizes priority value within budget.

    Strategy:
    1. Uses 0/1 knapsack dynamic programming
    2. Maximizes sum(priority) within token budget
    3. More optimal than greedy for certain scenarios

    Time Complexity: O(n × budget) where n = number of sources
    Space Complexity: O(n × budget)

    Optimality: Optimal for 0/1 knapsack problem (maximizes priority sum)

    Note: For large budgets or many sources, may be slower than greedy.
    """

    def select_sources(
        self,
        sources: list[ContextSource],  # noqa: F821
        budget: TokenBudget,
    ) -> SelectionResult:
        """
        Select sources using 0/1 knapsack dynamic programming.

        Maximizes sum of priorities within token budget.
        """
        if not sources:
            return SelectionResult(
                selected_sources=(),
                total_tokens=0,
                metadata={"selection_method": "knapsack", "excluded_count": 0},
            )

        available_tokens = budget.available_tokens

        # For very large budgets, use greedy as optimization
        if available_tokens > 100000:
            # Use greedy for performance
            greedy = GreedySelectionAlgorithm()
            # Sort by priority first
            sorted_sources = sorted(sources, key=lambda s: s.priority, reverse=True)
            result = greedy.select_sources(sorted_sources, budget)
            return SelectionResult(
                selected_sources=result.selected_sources,
                total_tokens=result.total_tokens,
                metadata={
                    **result.metadata,
                    "selection_method": "knapsack_greedy_fallback",
                    "reason": "Budget too large for DP, using greedy",
                },
            )

        # 0/1 Knapsack DP: dp[i][w] = max priority using first i items with weight w
        n = len(sources)
        max_weight = available_tokens

        # Use 1D DP array for space optimization
        # dp[w] = max priority achievable with weight w
        dp: list[int] = [0] * (max_weight + 1)
        # Keep track of which items were selected
        choices: list[list[int]] = [[] for _ in range(max_weight + 1)]

        for i, source in enumerate(sources):
            weight = source.token_count
            value = source.priority

            # Skip if item doesn't fit
            if weight > max_weight:
                continue

            # Update DP backwards to avoid using same item twice
            for w in range(max_weight, weight - 1, -1):
                if dp[w - weight] + value > dp[w]:
                    dp[w] = dp[w - weight] + value
                    choices[w] = choices[w - weight] + [i]

        # Find best weight (may not use full budget)
        best_weight = max(range(max_weight + 1), key=lambda w: dp[w])
        selected_indices = choices[best_weight]

        selected_sources = [sources[i] for i in selected_indices]
        excluded_indices = set(range(n)) - set(selected_indices)
        excluded_keys = [sources[i].key for i in excluded_indices]

        total_tokens = sum(s.token_count for s in selected_sources)

        return SelectionResult(
            selected_sources=tuple(selected_sources),
            total_tokens=total_tokens,
            metadata={
                "selection_method": "knapsack",
                "excluded_count": len(excluded_keys),
                "excluded_keys": excluded_keys,
                "sources_considered": len(sources),
                "sources_included": len(selected_sources),
                "max_priority_sum": dp[best_weight],
                "budget_utilization": total_tokens / available_tokens if available_tokens > 0 else 0,
            },
        )


class OptimalSelectionAlgorithm:
    """
    Optimal selection algorithm: finds truly optimal solution for small sets.

    Strategy:
    1. For small sets (< max_sources), uses brute force to find optimal
    2. For larger sets, falls back to knapsack or greedy
    3. Guarantees optimal solution when applicable

    Time Complexity: O(2^n) for brute force, O(n × budget) for fallback
    Space Complexity: O(2^n) for brute force

    Optimality: Guaranteed optimal for small sets, approximate for large sets
    """

    def __init__(self, max_sources: int = 20):
        """
        Initialize optimal selection algorithm.

        Args:
            max_sources: Maximum number of sources to use brute force on.
                        For larger sets, falls back to knapsack.
        """
        self._max_sources = max_sources

    def select_sources(
        self,
        sources: list[ContextSource],  # noqa: F821
        budget: TokenBudget,
    ) -> SelectionResult:
        """
        Select sources using optimal algorithm.

        For small sets, uses brute force to find optimal solution.
        For larger sets, falls back to knapsack algorithm.
        """
        if len(sources) <= self._max_sources:
            return self._brute_force_optimal(sources, budget)
        else:
            # Fall back to knapsack for larger sets
            knapsack = KnapsackSelectionAlgorithm()
            result = knapsack.select_sources(sources, budget)
            return SelectionResult(
                selected_sources=result.selected_sources,
                total_tokens=result.total_tokens,
                metadata={
                    **result.metadata,
                    "selection_method": "optimal_knapsack_fallback",
                    "reason": f"Set size {len(sources)} > {self._max_sources}, using knapsack",
                },
            )

    def _brute_force_optimal(
        self,
        sources: list[ContextSource],  # noqa: F821
        budget: TokenBudget,
    ) -> SelectionResult:
        """Find optimal solution using brute force (all subsets)."""
        available_tokens = budget.available_tokens
        n = len(sources)

        best_priority = -1
        best_selection: list[ContextSource] = []  # noqa: F821
        best_tokens = 0

        # Try all 2^n subsets
        for mask in range(1 << n):  # 2^n combinations
            selected: list[ContextSource] = []  # noqa: F821
            total_tokens = 0
            total_priority = 0

            for i in range(n):
                if mask & (1 << i):
                    source = sources[i]
                    if total_tokens + source.token_count <= available_tokens:
                        selected.append(source)
                        total_tokens += source.token_count
                        total_priority += source.priority
                    else:
                        # This subset doesn't fit, skip it
                        break
            else:
                # All selected items fit
                if total_priority > best_priority:
                    best_priority = total_priority
                    best_selection = selected
                    best_tokens = total_tokens

        excluded_keys = [s.key for s in sources if s not in best_selection]

        return SelectionResult(
            selected_sources=tuple(best_selection),
            total_tokens=best_tokens,
            metadata={
                "selection_method": "optimal_brute_force",
                "excluded_count": len(excluded_keys),
                "excluded_keys": excluded_keys,
                "sources_considered": len(sources),
                "sources_included": len(best_selection),
                "max_priority_sum": best_priority,
                "guaranteed_optimal": True,
            },
        )
