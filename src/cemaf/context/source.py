"""
Context sources - Abstraction for content sources with metadata.

Provides a unified way to represent different sources of context
(documents, API responses, tool outputs) with priority and recency
information for token-aware compilation.

Usage:
    # Create sources with metadata
    source1 = ContextSource(
        content="User profile data...",
        priority=10,  # High priority
        timestamp=datetime.now(),
        source_type="user_data"
    )

    source2 = ContextSource(
        content="Historical analysis...",
        priority=5,  # Lower priority
        timestamp=old_timestamp,
        source_type="history"
    )

    # Use with token-aware compiler
    compiled = await compiler.compile([source1, source2])
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from cemaf.core.types import JSON, TokenCount


@dataclass(frozen=True)
class ContextSource:
    """
    A source of context content with associated metadata.

    Used for token-aware compilation to prioritize and select
    the most relevant context within budget constraints.

    Attributes:
        content: The actual content text
        token_count: Token count (required for budget calculations)
        priority: Priority level (higher = more important, default=0)
        timestamp: When this content was created/updated
        source_type: Type of source (e.g., "tool_output", "document", "memory")
        source_id: Unique identifier for this source
        compressible: Whether this source can be summarized if needed
        min_tokens: Minimum tokens to preserve even when compressed
        metadata: Additional source-specific metadata

    Legacy compatibility:
        - `type` field maps to `source_type`
        - `key` field maps to `source_id`
    """

    content: str
    token_count: TokenCount | None = None  # Optional, can be computed later
    priority: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    source_type: str = "unknown"
    source_id: str = ""
    compressible: bool = True
    min_tokens: int = 0
    metadata: JSON = field(default_factory=dict)

    # Legacy field aliases for backward compatibility
    @property
    def type(self) -> str:
        """Legacy alias for source_type."""
        return self.source_type

    @property
    def key(self) -> str:
        """Legacy alias for source_id."""
        return self.source_id

    def __init__(
        self,
        content: str,
        token_count: TokenCount | None = None,
        priority: int = 0,
        timestamp: datetime | None = None,
        source_type: str = "unknown",
        source_id: str = "",
        compressible: bool = True,
        min_tokens: int = 0,
        metadata: JSON | None = None,
        # Legacy parameters for backward compatibility
        type: str | None = None,  # noqa: A002
        key: str | None = None,
    ) -> None:
        """Initialize ContextSource with backward compatibility for old parameters."""
        # Handle legacy parameters
        if type is not None:
            source_type = type
        if key is not None:
            source_id = key

        object.__setattr__(self, "content", content)
        object.__setattr__(self, "token_count", token_count)
        object.__setattr__(self, "priority", priority)
        object.__setattr__(self, "timestamp", timestamp or datetime.now(UTC))
        object.__setattr__(self, "source_type", source_type)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "compressible", compressible)
        object.__setattr__(self, "min_tokens", min_tokens)
        object.__setattr__(self, "metadata", metadata or {})

    @classmethod
    def from_tool_output(
        cls,
        content: str,
        tool_name: str,
        *,
        token_count: TokenCount | None = None,
        priority: int = 5,
        compressible: bool = True,
    ) -> ContextSource:
        """
        Create a ContextSource from tool output.

        Args:
            content: Tool output content
            tool_name: Name of the tool that produced this
            token_count: Pre-computed token count (default=0, should be computed)
            priority: Priority level (default=5)
            compressible: Whether content can be summarized

        Returns:
            ContextSource instance
        """
        return cls(
            content=content,
            token_count=token_count,
            priority=priority,
            timestamp=datetime.now(UTC),
            source_type="tool_output",
            source_id=tool_name,
            compressible=compressible,
            metadata={"tool": tool_name},
        )

    @classmethod
    def from_document(
        cls,
        content: str,
        document_id: str,
        *,
        token_count: TokenCount | None = None,
        priority: int = 3,
        timestamp: datetime | None = None,
        compressible: bool = True,
    ) -> ContextSource:
        """
        Create a ContextSource from a document.

        Args:
            content: Document content
            document_id: Document identifier
            token_count: Pre-computed token count (default=0, should be computed)
            priority: Priority level (default=3)
            timestamp: Document timestamp (defaults to now)
            compressible: Whether content can be summarized

        Returns:
            ContextSource instance
        """
        return cls(
            content=content,
            token_count=token_count,
            priority=priority,
            timestamp=timestamp or datetime.now(UTC),
            source_type="document",
            source_id=document_id,
            compressible=compressible,
            metadata={"document_id": document_id},
        )

    @classmethod
    def from_memory(
        cls,
        content: str,
        memory_key: str,
        *,
        token_count: TokenCount | None = None,
        priority: int = 7,
        timestamp: datetime | None = None,
        compressible: bool = False,
    ) -> ContextSource:
        """
        Create a ContextSource from memory.

        Args:
            content: Memory content
            memory_key: Memory key/identifier
            token_count: Pre-computed token count (default=0, should be computed)
            priority: Priority level (default=7, higher for memories)
            timestamp: Memory timestamp (defaults to now)
            compressible: Whether content can be summarized (default=False for memories)

        Returns:
            ContextSource instance
        """
        return cls(
            content=content,
            token_count=token_count,
            priority=priority,
            timestamp=timestamp or datetime.now(UTC),
            source_type="memory",
            source_id=memory_key,
            compressible=compressible,
            metadata={"memory_key": memory_key},
        )

    @classmethod
    def from_system_prompt(
        cls,
        content: str,
        *,
        token_count: TokenCount | None = None,
        priority: int = 100,
        compressible: bool = False,
        min_tokens: int = 0,
    ) -> ContextSource:
        """
        Create a ContextSource from a system prompt.

        System prompts typically have highest priority and shouldn't be compressed.

        Args:
            content: System prompt content
            token_count: Pre-computed token count (default=0, should be computed)
            priority: Priority level (default=100, highest)
            compressible: Whether content can be summarized (default=False)
            min_tokens: Minimum tokens to preserve

        Returns:
            ContextSource instance
        """
        return cls(
            content=content,
            token_count=token_count,
            priority=priority,
            timestamp=datetime.now(UTC),
            source_type="system",
            source_id="system_prompt",
            compressible=compressible,
            min_tokens=min_tokens,
            metadata={"critical": True},
        )

    def with_priority(self, priority: int) -> ContextSource:
        """
        Create a new source with updated priority.

        Args:
            priority: New priority value

        Returns:
            New ContextSource instance
        """
        return ContextSource(
            content=self.content,
            priority=priority,
            timestamp=self.timestamp,
            source_type=self.source_type,
            source_id=self.source_id,
            token_count=self.token_count,
            compressible=self.compressible,
            min_tokens=self.min_tokens,
            metadata=self.metadata,
        )

    def with_token_count(self, token_count: TokenCount) -> ContextSource:
        """
        Create a new source with pre-computed token count.

        Args:
            token_count: Number of tokens in content

        Returns:
            New ContextSource instance
        """
        return ContextSource(
            content=self.content,
            priority=self.priority,
            timestamp=self.timestamp,
            source_type=self.source_type,
            source_id=self.source_id,
            token_count=token_count,
            compressible=self.compressible,
            min_tokens=self.min_tokens,
            metadata=self.metadata,
        )

    def age_seconds(self, reference_time: datetime | None = None) -> float:
        """
        Calculate age of source in seconds.

        Args:
            reference_time: Reference time (defaults to now)

        Returns:
            Age in seconds
        """
        ref = reference_time or datetime.now(UTC)
        return (ref - self.timestamp).total_seconds()

    def __lt__(self, other: ContextSource) -> bool:
        """
        Compare sources for sorting.

        Sorts by priority (descending) then timestamp (descending - newer first).
        """
        if not isinstance(other, ContextSource):
            return NotImplemented
        # Higher priority first
        if self.priority != other.priority:
            return self.priority > other.priority
        # Newer timestamp first
        return self.timestamp > other.timestamp

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        token_info = f", tokens={self.token_count}" if self.token_count else ""
        return (
            f"ContextSource(type={self.source_type}, "
            f"id={self.source_id}, priority={self.priority}{token_info})"
        )


@dataclass(frozen=True)
class CompiledContext:
    """
    Result of compiling multiple context sources within a budget.

    Contains the selected and potentially compressed sources that fit
    within the token budget.

    Attributes:
        sources: Selected sources that were included
        total_tokens: Total token count of compiled context
        excluded_sources: Sources that didn't fit in budget
        compressed_sources: Sources that were summarized
        metadata: Compilation metadata
    """

    sources: tuple[ContextSource, ...]
    total_tokens: TokenCount
    excluded_sources: tuple[ContextSource, ...] = field(default_factory=tuple)
    compressed_sources: tuple[ContextSource, ...] = field(default_factory=tuple)
    metadata: JSON = field(default_factory=dict)

    @property
    def content(self) -> str:
        """
        Get concatenated content from all sources.

        Returns:
            Combined content string
        """
        return "\n\n".join(source.content for source in self.sources)

    @property
    def source_count(self) -> int:
        """Get number of included sources."""
        return len(self.sources)

    @property
    def utilization_ratio(self) -> float:
        """
        Get budget utilization ratio.

        Returns:
            Ratio of used tokens to budget (requires budget in metadata)
        """
        budget = self.metadata.get("budget")
        if budget and isinstance(budget, (int, float)):
            return float(self.total_tokens) / float(budget)
        return 0.0

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (
            f"CompiledContext(sources={self.source_count}, "
            f"tokens={self.total_tokens}, "
            f"excluded={len(self.excluded_sources)})"
        )
