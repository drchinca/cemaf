"""
Context protocols - Abstract interfaces for context compilation.

Supports:
- Token budget management
- Priority-based selection
- Multiple selection algorithms (greedy, knapsack, optimal)
- Context patching and provenance tracking

## Protocol-First Design

This module provides structural typing via @runtime_checkable protocols.
Any class that implements the required methods is automatically compatible.

Extension Point:
    Implement these protocols for custom context compilation strategies.
    No registration needed - structural typing ensures compatibility.
"""

from typing import Any, Protocol, runtime_checkable

# Re-export data classes (not changed)
from cemaf.context.budget import BudgetAllocation, TokenBudget
from cemaf.context.compiler import CompiledContext
from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch, PatchLog

__all__ = [
    "ContextCompiler",
    "ContextSelectionAlgorithm",
    # Data classes
    "TokenBudget",
    "BudgetAllocation",
    "Context",
    "CompiledContext",
    "ContextPatch",
    "PatchLog",
]


@runtime_checkable
class ContextCompiler(Protocol):
    """
    Protocol for context compiler implementations.

    A ContextCompiler assembles relevant context for LLM operations:
    - Manages token budgets
    - Selects and prioritizes context sources
    - Tracks context patches and provenance
    - Ensures context fits within model limits

    Extension Point:
        - Simple compilers (concatenate all sources)
        - Budget-aware compilers (fit within token limits)
        - Priority-based compilers (select by importance)
        - Semantic compilers (select by relevance)
        - Adaptive compilers (learn from feedback)

    Example:
        >>> class SimpleContextCompiler:
        ...     async def compile(self, sources: list, budget: TokenBudget) -> CompiledContext:
        ...         # Your compilation logic
        ...         ...
        >>>
        >>> compiler = SimpleContextCompiler()
        >>> assert isinstance(compiler, ContextCompiler)
    """

    async def compile(
        self,
        sources: list,
        budget: TokenBudget,
    ) -> CompiledContext:
        """
        Compile context from sources within token budget.

        Args:
            sources: List of context sources (documents, memories, etc.)
            budget: Token budget constraints

        Returns:
            CompiledContext with selected sources and metadata

        Example:
            >>> budget = TokenBudget(max_tokens=4000, reserved_for_output=1000)
            >>> sources = [doc1, doc2, doc3]
            >>> compiled = await compiler.compile(sources, budget)
            >>> print(f"Used {compiled.total_tokens}/{budget.max_tokens} tokens")
        """
        ...


@runtime_checkable
class ContextSelectionAlgorithm(Protocol):
    """
    Protocol for context selection algorithm implementations.

    A selection algorithm decides which context sources to include
    when total context exceeds available budget.

    Extension Point:
        - Greedy (select highest priority until budget full)
        - Knapsack (optimal selection for budget)
        - Semantic (select by relevance to query)
        - Learned (ML-based selection)
        - Hybrid (combine multiple strategies)

    Example:
        >>> class GreedyAlgorithm:
        ...     def select(self, sources: list, budget: int) -> SelectionResult:
        ...         # Sort by priority, select until budget full
        ...         ...
        >>>
        >>> algo = GreedyAlgorithm()
        >>> assert isinstance(algo, ContextSelectionAlgorithm)
    """

    def select(self, sources: list, budget: int) -> Any:
        """
        Select context sources that fit within budget.

        Args:
            sources: Available context sources
            budget: Token budget available

        Returns:
            SelectionResult with selected sources and metadata

        Example:
            >>> sources = [
            ...     {"content": "...", "priority": 10, "tokens": 100},
            ...     {"content": "...", "priority": 5, "tokens": 200},
            ... ]
            >>> result = algorithm.select(sources, budget=250)
            >>> print(f"Selected {len(result.selected)} sources")
        """
        ...
