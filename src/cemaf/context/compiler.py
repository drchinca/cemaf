"""
Context Compiler - Assembles context for LLM calls.

The compiler:
- Gathers relevant artifacts
- Retrieves relevant memories
- Respects token budget
- Produces deterministic output (same inputs → same hash)
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cemaf.context.algorithm import (
    ContextSelectionAlgorithm,
    GreedySelectionAlgorithm,
    SelectionResult,
)
from cemaf.context.budget import TokenBudget
from cemaf.context.source import ContextSource
from cemaf.core.types import JSON
from cemaf.core.utils import utc_now


@dataclass(frozen=True)
class CompiledContext:
    """
    Compiled context ready for LLM consumption.

    Immutable, hashable, deterministic.
    """

    sources: tuple[ContextSource, ...]
    total_tokens: int
    budget: TokenBudget
    compiled_at: datetime = field(default_factory=utc_now)
    metadata: JSON = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """
        Deterministic hash of context content.

        Same inputs always produce same hash.
        """
        # Sort sources by key for determinism
        sorted_sources = sorted(self.sources, key=lambda s: (s.type, s.key))
        content = json.dumps(
            [(s.type, s.key, s.content) for s in sorted_sources],
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_messages(self) -> list[JSON]:
        """Convert context to message format for LLM."""
        messages: list[JSON] = []

        # Group by type
        system_parts: list[str] = []

        for source in self.sources:
            if source.type == "artifact":
                system_parts.append(f"[{source.key}]\n{source.content}")
            elif source.type == "memory":
                system_parts.append(f"[Memory: {source.key}]\n{source.content}")

        if system_parts:
            messages.append(
                {
                    "role": "system",
                    "content": "\n\n".join(system_parts),
                }
            )

        return messages

    def within_budget(self) -> bool:
        """Check if context is within token budget (respecting output reservation)."""
        return self.total_tokens <= self.budget.available_tokens


@runtime_checkable
class TokenEstimator(Protocol):
    """Protocol for estimating token counts."""

    def estimate(self, text: str) -> int:
        """Estimate token count for text."""
        ...


class SimpleTokenEstimator:
    """Simple token estimator using character/word heuristics."""

    def __init__(self, chars_per_token: float = 4.0) -> None:
        self._chars_per_token = chars_per_token

    def estimate(self, text: str) -> int:
        """Estimate tokens as chars / chars_per_token."""
        return max(1, int(len(text) / self._chars_per_token))


class AdvancedCompilerConfig(BaseModel):
    """
    Configuration for AdvancedContextCompiler.

    Controls summarization and fallback behavior for context compilation.
    """

    model_config = {"frozen": True}

    target_summary_tokens: int = Field(
        default=50,
        description="Target token count for summarized content",
    )
    max_summarization_retries: int = Field(
        default=3,
        description="Maximum retry attempts for LLM summarization",
    )
    fallback_on_error: bool = Field(
        default=True,
        description="Fall back to base compiler on summarization failure",
    )


@runtime_checkable
class ContextCompiler(Protocol):
    """
    Protocol for context compilation strategies.

    Implementations must provide the compile() method to assemble
    context from artifacts and memories within token budget.

    Example:
        class MyCompiler:
            async def compile(
                self,
                artifacts: tuple[tuple[str, str], ...],
                memories: tuple[tuple[str, str], ...],
                budget: TokenBudget,
                priorities: dict[str, int] | None = None,
            ) -> CompiledContext:
                sources = []
                # Gather artifacts
                # Gather memories
                # Respect budget
                return CompiledContext(...)
    """

    async def compile(
        self,
        artifacts: tuple[tuple[str, str], ...],  # (key, content) pairs
        memories: tuple[tuple[str, str], ...],  # (key, content) pairs
        budget: TokenBudget,
        priorities: dict[str, int] | None = None,
    ) -> CompiledContext:
        """
        Compile context from sources.

        Args:
            artifacts: Context artifacts as (key, content) pairs
            memories: Memory items as (key, content) pairs
            budget: Token budget constraints
            priorities: Optional priority overrides by key

        Returns:
            CompiledContext ready for LLM
        """
        ...


class PriorityContextCompiler:
    """
    Context compiler that prioritizes sources by importance.

    Uses a pluggable selection algorithm to choose which sources to include.
    Defaults to greedy algorithm if not specified.
    """

    def __init__(
        self,
        token_estimator: TokenEstimator,
        algorithm: ContextSelectionAlgorithm | None = None,
    ) -> None:
        """
        Initialize priority-based context compiler.

        Args:
            token_estimator: Token estimation strategy (required)
            algorithm: Selection algorithm to use (defaults to GreedySelectionAlgorithm)
        """
        self._estimator = token_estimator
        self._algorithm = algorithm or GreedySelectionAlgorithm()

    async def compile(
        self,
        artifacts: tuple[tuple[str, str], ...],
        memories: tuple[tuple[str, str], ...],
        budget: TokenBudget,
        priorities: dict[str, int] | None = None,
    ) -> CompiledContext:
        """
        Compile context using priority ordering and selection algorithm.

        Args:
            artifacts: Context artifacts as (key, content) pairs
            memories: Memory items as (key, content) pairs
            budget: Token budget constraints
            priorities: Optional priority overrides by key

        Returns:
            CompiledContext ready for LLM
        """
        priorities = priorities or {}
        sources: list[ContextSource] = []

        # Create sources from artifacts and memories
        for key, content in artifacts:
            tokens = self._estimator.estimate(content)
            priority = priorities.get(key, 0)
            sources.append(
                ContextSource(
                    type="artifact",
                    key=key,
                    content=content,
                    token_count=tokens,
                    priority=priority,
                )
            )

        for key, content in memories:
            tokens = self._estimator.estimate(content)
            priority = priorities.get(key, -1)
            sources.append(
                ContextSource(
                    type="memory",
                    key=key,
                    content=content,
                    token_count=tokens,
                    priority=priority,
                )
            )

        # Sort by priority (descending) - most algorithms expect this
        sources.sort(key=lambda s: s.priority, reverse=True)

        # Use algorithm to select sources within budget
        selection_result: SelectionResult = self._algorithm.select_sources(sources, budget)

        return CompiledContext(
            sources=selection_result.selected_sources,
            total_tokens=selection_result.total_tokens,
            budget=budget,
            metadata={
                **selection_result.metadata,
                "algorithm_used": selection_result.selection_method,
            },
        )
