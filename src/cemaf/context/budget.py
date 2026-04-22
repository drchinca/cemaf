"""
Token Budget - Managing context token limits.

Budgets define:
- Maximum tokens for context
- Allocation for different sections
- Reserved tokens for output
"""

from dataclasses import dataclass, field

from cemaf.core.constants import (
    DEFAULT_CONTEXT_BUDGET,
    RESERVED_OUTPUT_TOKENS,
)
from cemaf.core.types import JSON


@dataclass(frozen=True)
class BudgetAllocation:
    """Allocation of budget to a specific section."""

    section: str
    max_tokens: int
    priority: int = 0  # Higher = filled first
    min_tokens: int = 0  # Minimum allocation


@dataclass(frozen=True)
class TokenBudget:
    """
    Token budget for context compilation.

    Defines how many tokens can be used and how they're allocated.
    """

    max_tokens: int = DEFAULT_CONTEXT_BUDGET
    reserved_for_output: int = RESERVED_OUTPUT_TOKENS
    allocations: tuple[BudgetAllocation, ...] = field(default_factory=tuple)
    metadata: JSON = field(default_factory=dict)

    @property
    def available_tokens(self) -> int:
        """Tokens available after reserving for output."""
        return self.max_tokens - self.reserved_for_output

    @classmethod
    def default(cls) -> TokenBudget:
        """Create default budget."""
        return cls()

    @property
    def utilization(self) -> float:
        """Fraction of available tokens allocated (0.0 - 1.0)."""
        if self.available_tokens <= 0:
            return 1.0
        allocated = sum(a.max_tokens for a in self.allocations)
        return min(allocated / self.available_tokens, 1.0)

    @property
    def headroom(self) -> int:
        """Unallocated tokens remaining."""
        allocated = sum(a.max_tokens for a in self.allocations)
        return max(self.available_tokens - allocated, 0)

    @classmethod
    def for_model(cls, model: str) -> TokenBudget:
        """Create budget appropriate for a model."""
        limits = {
            # Claude 4.x
            "claude-opus-4-6": 200_000,
            "claude-sonnet-4-6": 200_000,
            # Claude 4.5
            "claude-opus-4-5": 200_000,
            "claude-sonnet-4-5": 200_000,
            "claude-haiku-4-5": 200_000,
            # Claude 3
            "claude-3-opus": 200_000,
            "claude-3-sonnet": 200_000,
            "claude-3-haiku": 200_000,
            # OpenAI
            "gpt-4o": 128_000,
            "o1": 200_000,
            "o3": 200_000,
            "gpt-4-turbo": 128_000,
            "gpt-4": 8_192,
        }

        max_tokens = limits.get(model, DEFAULT_CONTEXT_BUDGET)
        return cls(max_tokens=max_tokens)

    def with_allocation(
        self,
        section: str,
        max_tokens: int,
        priority: int = 0,
        min_tokens: int = 0,
    ) -> TokenBudget:
        """Add an allocation and return new budget."""
        allocation = BudgetAllocation(
            section=section,
            max_tokens=max_tokens,
            priority=priority,
            min_tokens=min_tokens,
        )
        return TokenBudget(
            max_tokens=self.max_tokens,
            reserved_for_output=self.reserved_for_output,
            allocations=self.allocations + (allocation,),
            metadata=self.metadata,
        )

    def get_section_budget(self, section: str) -> int:
        """Get max tokens for a section."""
        for alloc in self.allocations:
            if alloc.section == section:
                return alloc.max_tokens
        return 0
