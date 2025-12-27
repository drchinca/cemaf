"""
Context Compiler - Assembles context for LLM calls.

The compiler:
- Gathers relevant artifacts
- Retrieves relevant memories
- Respects token budget
- Produces deterministic output (same inputs → same hash)
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cemaf.core.types import JSON
from cemaf.core.enums import ContextArtifactType, MemoryScope
from cemaf.core.utils import utc_now
from cemaf.context.budget import TokenBudget


@dataclass(frozen=True)
class ContextSource:
    """A source of context (artifact, memory, etc.)."""

    type: str  # "artifact", "memory", "message", "tool_result"
    key: str
    content: str
    token_count: int
    priority: int = 0  # Higher = more important
    metadata: JSON = field(default_factory=dict)


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
            messages.append({
                "role": "system",
                "content": "\n\n".join(system_parts),
            })
        
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


class ContextCompiler(ABC):
    """
    Abstract context compiler.
    
    Subclass to implement custom context compilation strategies.
    
    Example:
        class MyCompiler(ContextCompiler):
            async def compile(
                self, request: ContextRequest
            ) -> CompiledContext:
                sources = []
                # Gather artifacts
                # Gather memories
                # Respect budget
                return CompiledContext(...)
    """

    def __init__(
        self,
        token_estimator: TokenEstimator | None = None,
    ) -> None:
        self._estimator = token_estimator or SimpleTokenEstimator()

    @abstractmethod
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


class PriorityContextCompiler(ContextCompiler):
    """
    Context compiler that prioritizes sources by importance.
    
    Higher priority sources are included first until budget exhausted.
    """

    async def compile(
        self,
        artifacts: tuple[tuple[str, str], ...],
        memories: tuple[tuple[str, str], ...],
        budget: TokenBudget,
        priorities: dict[str, int] | None = None,
    ) -> CompiledContext:
        """Compile context using priority ordering."""
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

        # Sort by priority (descending)
        sources.sort(key=lambda s: s.priority, reverse=True)

        # Filter sources to fit within budget
        selected_sources: list[ContextSource] = []
        total_tokens = 0
        available_tokens = budget.available_tokens

        for source in sources:
            if total_tokens + source.token_count <= available_tokens:
                selected_sources.append(source)
                total_tokens += source.token_count
            # Skip sources that don't fit

        return CompiledContext(
            sources=tuple(selected_sources),
            total_tokens=total_tokens,
            budget=budget,
        )

