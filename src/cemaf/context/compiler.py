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
from collections.abc import Callable, Coroutine
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
from cemaf.context.patch import SecurityLevel
from cemaf.context.source import ContextSource
from cemaf.core.types import JSON, TokenCount
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
    """Character-based token estimator.

    Default 3.5 chars/token matches current-generation tokenizers (Claude,
    GPT-4) for English prose. The previous default of 4.0 under-counted
    Unicode, code, and JSON by 15-30% and let compilers pack context over
    the model's real limit.

    Callers who need exactness should inject an LLMClient-backed estimator
    — this class is the fallback for hot paths where a network call would
    be prohibitive.
    """

    def __init__(self, chars_per_token: float = 3.5) -> None:
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")
        self._chars_per_token = chars_per_token

    def estimate(self, text: str) -> int:
        """Estimate tokens as chars / chars_per_token (ceiling-rounded)."""
        if not text:
            return 0
        # Round to nearest rather than floor — keeps the estimate honest at
        # short lengths where floor would under-count systematically.
        return max(1, round(len(text) / self._chars_per_token))


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

    async def compact(
        self,
        *,
        compiled: CompiledContext,
        preserve_recent: int = 2,
        summary_budget_tokens: int = 500,
        summarizer: Callable[[str], Coroutine[None, None, str]] | None = None,
    ) -> CompiledContext:
        """Compact old sources while preserving the most recent ones."""
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
        *,
        source_levels: dict[str, SecurityLevel] | None = None,
        clearance: SecurityLevel | None = None,
    ) -> CompiledContext:
        """
        Compile context using priority ordering and selection algorithm.

        Args:
            artifacts: Context artifacts as (key, content) pairs
            memories: Memory items as (key, content) pairs
            budget: Token budget constraints
            priorities: Optional priority overrides by key
            source_levels: Optional security level per key (absent ⇒ INTERNAL)
            clearance: Caller clearance; None ⇒ no security gating (SPEC-11)

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
                    token_count=TokenCount(tokens) if isinstance(tokens, int) else tokens,
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
                    token_count=TokenCount(tokens) if isinstance(tokens, int) else tokens,
                    priority=priority,
                )
            )

        # SPEC-11 security gate — drop sources above the caller's clearance BEFORE
        # the priority sort. clearance=None preserves the pre-SPEC-11 behavior exactly.
        security_excluded: list[str] = []
        if clearance is not None:
            levels = source_levels or {}
            kept: list[ContextSource] = []
            for source in sources:
                level = levels.get(source.key, SecurityLevel.INTERNAL)
                if level.rank > clearance.rank:
                    security_excluded.append(source.key)
                else:
                    kept.append(source)
            sources = kept

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
                "security_excluded": security_excluded,
            },
        )

    async def compact(
        self,
        *,
        compiled: CompiledContext,
        preserve_recent: int = 2,
        summary_budget_tokens: int = 500,
        summarizer: Callable[[str], Coroutine[None, None, str]] | None = None,
    ) -> CompiledContext:
        """Compact old sources while preserving the most recent ones."""
        sources = list(compiled.sources)

        if len(sources) <= preserve_recent:
            return compiled

        # Partition: high-priority sources (>= 90) are always preserved
        high_priority_threshold = 90
        to_preserve: list[ContextSource] = []
        candidates: list[ContextSource] = []

        for source in sources:
            if source.priority >= high_priority_threshold:
                to_preserve.append(source)
            else:
                candidates.append(source)

        # From the remaining candidates, preserve the last N (most recent by position)
        if len(candidates) <= preserve_recent:
            # Nothing meaningful to compact
            return compiled

        to_summarize = candidates[:-preserve_recent]
        to_preserve.extend(candidates[-preserve_recent:])

        # Build combined text from sources that will be summarized
        combined_text = "\n\n".join(f"[{s.source_type}:{s.source_id}] {s.content}" for s in to_summarize)

        # Produce summary content
        if summarizer is not None:
            summary_content = await summarizer(combined_text)
        else:
            # Simple truncation fallback: keep chars proportional to budget
            char_budget = summary_budget_tokens * 4  # rough chars-per-token estimate
            if len(combined_text) > char_budget:
                summary_content = combined_text[:char_budget] + "\n[...truncated]"
            else:
                summary_content = combined_text

        summary_tokens = self._estimator.estimate(text=summary_content)

        # Invariant: compaction must never grow the context. For small sources
        # the per-source "[type:id] " framing + separators can cost more tokens
        # than they save (especially with no real summarizer). If the summary is
        # not strictly smaller than the sources it replaces, compaction is a
        # no-op — return the original unchanged rather than emit a larger context.
        original_summarized_tokens = sum((s.token_count or 0) for s in to_summarize)
        if summary_tokens >= original_summarized_tokens:
            return compiled

        summary_source = ContextSource(
            content=summary_content,
            token_count=TokenCount(summary_tokens),
            priority=50,
            source_type="compacted_summary",
            source_id="compacted_context",
            compressible=True,
            metadata={
                "compacted_from": [s.source_id for s in to_summarize],
                "original_source_count": len(to_summarize),
            },
        )

        # Assemble: summary first, then preserved sources in original order
        final_sources = [summary_source, *to_preserve]
        total_tokens = sum((s.token_count or 0) for s in final_sources)

        return CompiledContext(
            sources=tuple(final_sources),
            total_tokens=total_tokens,
            budget=compiled.budget,
            metadata={
                **compiled.metadata,
                "compacted": True,
                "compacted_source_count": len(to_summarize),
                "preserved_source_count": len(to_preserve),
            },
        )
