"""
RLM (Recursive Language Models) protocols.

Provides core abstractions for treating context as external state and
enabling recursive self-query with divide-and-conquer strategies.

Key Concepts:
- Context chunks: Immutable units of context suitable for recursive processing
- Recursive query: Break large context into chunks, query recursively, aggregate
- Token budget enforcement: Respect token limits at every recursion level
- Divide-and-conquer: Query chunks independently, aggregate results

Usage:
    # Create chunks from large content
    chunks = chunking_strategy.chunk(content, max_chunk_tokens=500)

    # Recursively query with budget
    result = await query_engine.query(
        instruction="Find all mentions of X",
        chunks=chunks,
        budget=TokenBudget.from_total(max_tokens=4000),
    )

Extension Points:
    - ChunkingStrategy: Implement custom chunking (semantic, hierarchical, etc.)
    - RecursiveQueryEngine: Implement custom query strategies (parallel, cached, etc.)
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from cemaf.context.budget import TokenBudget
from cemaf.context.source import ContextSource
from cemaf.core.types import JSON, TokenCount


@dataclass(frozen=True)
class ContextChunk:
    """
    Immutable chunk of context suitable for recursive processing.

    A chunk is a self-contained unit of content with metadata for:
    - Token budget enforcement
    - Hierarchical organization (parent/child relationships)
    - Recursion depth tracking

    Attributes:
        chunk_id: Unique identifier for this chunk
        content: The actual content text
        token_count: Token count for budget calculations
        parent_id: Optional parent chunk ID for hierarchical chunking
        depth: Recursion depth level (0 = root level)
        metadata: Additional chunk-specific metadata

    Example:
        chunk = ContextChunk(
            chunk_id="chunk_0",
            content="Large document content...",
            token_count=TokenCount(500),
            depth=0,
        )
    """

    chunk_id: str
    content: str
    token_count: TokenCount
    parent_id: str | None = None
    depth: int = 0
    metadata: JSON = field(default_factory=dict)

    def to_context_source(self, priority: int = 0) -> ContextSource:
        """
        Convert chunk to ContextSource for compilation.

        Enables reuse of existing CEMAF context compilation infrastructure.

        Args:
            priority: Priority level for context selection (default=0)

        Returns:
            ContextSource instance ready for compilation
        """
        return ContextSource(
            content=self.content,
            token_count=self.token_count,
            priority=priority,
            timestamp=datetime.now(UTC),
            source_type="rlm_chunk",
            source_id=self.chunk_id,
            compressible=True,
            metadata={
                **self.metadata,
                "parent_id": self.parent_id,
                "depth": self.depth,
            },
        )


@dataclass(frozen=True)
class RecursiveQueryResult:
    """
    Result of recursive LLM query with execution metadata.

    Contains the answer along with detailed metadata about the recursive
    query execution for observability and debugging.

    Attributes:
        success: Whether query succeeded
        answer: The answer from the query (if successful)
        relevant_chunks: Chunks that contributed to the answer
        error: Error message (if failed)
        depth_reached: Maximum recursion depth reached
        chunks_examined: Total number of chunks examined
        llm_calls_made: Total number of LLM API calls made
        total_tokens_used: Total tokens consumed across all calls
        metadata: Additional execution metadata

    Example:
        result = RecursiveQueryResult.ok(
            answer="Found 5 mentions of X",
            relevant_chunks=(chunk1, chunk2),
            depth_reached=2,
            chunks_examined=10,
            llm_calls_made=3,
        )
    """

    success: bool
    answer: str | None = None
    relevant_chunks: tuple[ContextChunk, ...] = ()
    error: str | None = None
    depth_reached: int = 0
    chunks_examined: int = 0
    llm_calls_made: int = 0
    total_tokens_used: TokenCount = TokenCount(0)
    metadata: JSON = field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        answer: str,
        relevant_chunks: tuple[ContextChunk, ...] = (),
        depth_reached: int = 0,
        chunks_examined: int = 0,
        llm_calls_made: int = 0,
        total_tokens_used: TokenCount | None = None,
        metadata: JSON | None = None,
    ) -> RecursiveQueryResult:
        """Create a successful query result."""
        return cls(
            success=True,
            answer=answer,
            relevant_chunks=relevant_chunks,
            depth_reached=depth_reached,
            chunks_examined=chunks_examined,
            llm_calls_made=llm_calls_made,
            total_tokens_used=total_tokens_used if total_tokens_used is not None else TokenCount(0),
            metadata=metadata or {},
        )

    @classmethod
    def fail(
        cls,
        error: str,
        depth_reached: int = 0,
        chunks_examined: int = 0,
        llm_calls_made: int = 0,
        metadata: JSON | None = None,
    ) -> RecursiveQueryResult:
        """Create a failed query result."""
        return cls(
            success=False,
            error=error,
            depth_reached=depth_reached,
            chunks_examined=chunks_examined,
            llm_calls_made=llm_calls_made,
            metadata=metadata or {},
        )


@runtime_checkable
class ChunkingStrategy(Protocol):
    """
    Protocol for breaking content into chunks.

    Implementations define how to split large content into processable chunks
    that respect token budgets and enable recursive querying.

    Extension Point:
        Implement this protocol for custom chunking strategies:
        - Fixed-size chunking (simple token-based splitting)
        - Semantic chunking (paragraph/section aware)
        - Hierarchical chunking (parent summaries + child details)
        - Sliding window chunking (overlapping chunks)

    Example:
        class MyChunkingStrategy:
            def chunk(
                self,
                content: str,
                max_chunk_tokens: int,
            ) -> tuple[ContextChunk, ...]:
                # Split content into chunks
                return (chunk1, chunk2, ...)

            def create_hierarchy(
                self,
                chunks: tuple[ContextChunk, ...],
            ) -> tuple[ContextChunk, ...]:
                # Add parent summaries
                return (parent, *chunks)
    """

    def chunk(
        self,
        content: str,
        max_chunk_tokens: int,
    ) -> tuple[ContextChunk, ...]:
        """
        Break content into chunks.

        Args:
            content: Content to chunk
            max_chunk_tokens: Maximum tokens per chunk

        Returns:
            Tuple of context chunks
        """
        ...

    def create_hierarchy(
        self,
        chunks: tuple[ContextChunk, ...],
    ) -> tuple[ContextChunk, ...]:
        """
        Create hierarchical structure from flat chunks.

        Args:
            chunks: Flat list of chunks

        Returns:
            Tuple of chunks with parent-child relationships
        """
        ...


@runtime_checkable
class RecursiveQueryEngine(Protocol):
    """
    Protocol for recursive query execution.

    Implements divide-and-conquer strategy for querying large context:
    1. Base case: If chunks fit in budget, make single LLM call
    2. Recursive case: Split chunks, query each, aggregate results
    3. Respect max_depth to prevent infinite recursion

    Extension Point:
        Implement this protocol for custom query strategies:
        - Simple divide-and-conquer (map-reduce)
        - Parallel chunk processing (asyncio.gather)
        - Cached query engine (memoize chunk results)
        - Binary search (O(log N) for sorted content)

    Example:
        class MyQueryEngine:
            async def query(
                self,
                instruction: str,
                chunks: tuple[ContextChunk, ...],
                budget: TokenBudget,
                max_depth: int = 3,
            ) -> RecursiveQueryResult:
                # Implement divide-and-conquer logic
                return RecursiveQueryResult.ok(answer="...")
    """

    async def query(
        self,
        instruction: str,
        chunks: tuple[ContextChunk, ...],
        budget: TokenBudget,
        max_depth: int = 3,
    ) -> RecursiveQueryResult:
        """
        Execute recursive query with divide-and-conquer.

        Args:
            instruction: Query instruction for the LLM
            chunks: Chunks to query
            budget: Token budget to respect
            max_depth: Maximum recursion depth (default=3)

        Returns:
            RecursiveQueryResult with answer and metadata
        """
        ...
