"""
Protocols for context ingestion.

Defines the interfaces for adapting raw data into token-budgeted context.
"""

from typing import Any, Protocol, runtime_checkable

from cemaf.context.budget import TokenBudget
from cemaf.context.source import ContextSource


@runtime_checkable
class ContextAdapter(Protocol):
    """
    Transforms raw data into token-budgeted context sources.

    CEMAF doesn't fetch data - your code does. The adapter's job is to
    make that data fit efficiently into the context window.
    """

    async def adapt(
        self,
        data: Any,
        budget: TokenBudget,
        priority: int = 0,
    ) -> ContextSource:
        """
        Adapt raw data into a context source.

        Args:
            data: Raw data from any source (you fetched it)
            budget: Available token budget for this source
            priority: Importance for selection algorithm (higher = more important)

        Returns:
            ContextSource ready for compilation
        """
        ...

    def estimate_tokens(self, data: Any) -> int:
        """
        Estimate token count before full adaptation.

        Used for budget planning without full processing.

        Args:
            data: Raw data to estimate

        Returns:
            Estimated token count
        """
        ...


@runtime_checkable
class CompressionStrategy(Protocol):
    """
    Strategy for compressing content to fit within token budget.
    """

    async def compress(
        self,
        content: str,
        target_tokens: int,
    ) -> str:
        """
        Compress content to fit within target token count.

        Args:
            content: Original content
            target_tokens: Maximum tokens for output

        Returns:
            Compressed content
        """
        ...

    def can_compress(self, content: str, target_tokens: int) -> bool:
        """
        Check if compression to target is feasible.

        Args:
            content: Content to compress
            target_tokens: Target token count

        Returns:
            True if compression is possible
        """
        ...


@runtime_checkable
class FormatOptimizer(Protocol):
    """
    Optimizes data format for token efficiency.
    """

    def estimate_tokens(self, data: Any, format: str) -> int:
        """
        Estimate tokens for data in a specific format.

        Args:
            data: Data to format
            format: Target format (json, yaml, markdown, csv)

        Returns:
            Estimated token count
        """
        ...

    def format(self, data: Any, format: str) -> str:
        """
        Format data as string.

        Args:
            data: Data to format
            format: Target format

        Returns:
            Formatted string
        """
        ...

    def optimal_format(self, data: Any, formats: list[str]) -> str:
        """
        Find most token-efficient format.

        Args:
            data: Data to format
            formats: Candidate formats to compare

        Returns:
            Name of optimal format
        """
        ...


@runtime_checkable
class PriorityAssigner(Protocol):
    """
    Assigns priority scores to context sources.
    """

    def calculate(self, source: ContextSource) -> int:
        """
        Calculate priority for a source.

        Args:
            source: Context source to evaluate

        Returns:
            Priority score (higher = more important)
        """
        ...
