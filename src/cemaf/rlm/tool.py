"""
RLM tool integration.

Provides RLM as a standard CEMAF tool for recursive context querying.
"""

from typing import Any

from cemaf.context.budget import TokenBudget
from cemaf.core.result import Result
from cemaf.core.types import ToolID
from cemaf.rlm.protocols import ChunkingStrategy, RecursiveQueryEngine
from cemaf.tools.base import Tool, ToolResult, ToolSchema

# Token budget constants
DEFAULT_RESERVED_OUTPUT_TOKENS = 1000  # Reserve tokens for LLM response generation


class RLMQueryTool(Tool):
    """
    Tool for recursive context querying.

    Enables agents to query large context recursively instead of
    loading everything into LLM context window.

    This class inherits from the Tool ABC (cemaf.tools.base.Tool).

    Example:
        rlm_tool = RLMQueryTool(query_engine, chunking_strategy)
        result = await rlm_tool.execute(
            instruction="Find all mentions of X",
            content=large_document,
            max_depth=3,
        )
    """

    def __init__(
        self,
        query_engine: RecursiveQueryEngine,
        chunking_strategy: ChunkingStrategy,
        default_max_depth: int = 3,
        default_max_tokens: int = 4000,
        default_chunk_size: int = 500,
    ) -> None:
        """
        Initialize RLM query tool.

        Args:
            query_engine: Recursive query engine
            chunking_strategy: Chunking strategy
            default_max_depth: Default maximum recursion depth (default=3)
            default_max_tokens: Default token budget (default=4000)
            default_chunk_size: Default chunk size in tokens (default=500)
        """
        self._engine = query_engine
        self._chunking = chunking_strategy
        self._default_max_depth = default_max_depth
        self._default_max_tokens = default_max_tokens
        self._default_chunk_size = default_chunk_size

    @property
    def id(self) -> ToolID:
        """Get tool ID."""
        return ToolID("rlm_query")

    @property
    def schema(self) -> ToolSchema:
        """Get tool schema."""
        return ToolSchema(
            name="rlm_query",
            description=(
                "Query large context recursively using divide-and-conquer. "
                "Breaks content into chunks and queries them recursively, "
                "then aggregates results. Use this when context is too large "
                "to fit in a single LLM call."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": (
                            "Query instruction describing what to find or analyze. "
                            "Examples: 'Find all mentions of X', 'Summarize key points', "
                            "'What are the main themes?'"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to query (can be very large)",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": (
                            f"Maximum recursion depth (default={self._default_max_depth}). "
                            "Higher values allow deeper recursion for very large contexts."
                        ),
                        "minimum": 1,
                        "maximum": 10,
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": (f"Token budget for each query (default={self._default_max_tokens})"),
                        "minimum": 100,
                        "maximum": 200000,
                    },
                    "chunk_size": {
                        "type": "integer",
                        "description": (f"Target tokens per chunk (default={self._default_chunk_size})"),
                        "minimum": 100,
                        "maximum": 10000,
                    },
                },
                "required": ["instruction", "content"],
            },
            required=("instruction", "content"),
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute recursive query.

        Args:
            **kwargs: Keyword arguments containing:
                - instruction (str): Query instruction
                - content (str): Content to query
                - max_depth (int, optional): Maximum recursion depth
                - max_tokens (int, optional): Token budget
                - chunk_size (int, optional): Chunk size

        Returns:
            ToolResult with answer and execution metadata
        """
        # Extract parameters from kwargs
        instruction: str = kwargs["instruction"]
        content: str = kwargs["content"]
        max_depth: int = kwargs.get("max_depth", self._default_max_depth)
        max_tokens: int = kwargs.get("max_tokens", self._default_max_tokens)
        chunk_size: int = kwargs.get("chunk_size", self._default_chunk_size)

        try:
            chunks = self._chunking.chunk(content, max_chunk_tokens=chunk_size)

            if not chunks:
                return Result.fail(
                    "No chunks created from content",
                    metadata={"content_length": len(content)},
                )

            budget = TokenBudget(
                max_tokens=max_tokens,
                reserved_for_output=DEFAULT_RESERVED_OUTPUT_TOKENS,
            )

            result = await self._engine.query(
                instruction=instruction,
                chunks=chunks,
                budget=budget,
                max_depth=max_depth,
            )

            if not result.success:
                return Result.fail(
                    result.error or "Query failed",
                    metadata={
                        "depth_reached": result.depth_reached,
                        "chunks_examined": result.chunks_examined,
                        "llm_calls": result.llm_calls_made,
                    },
                )

            return Result.ok(
                result.answer,
                metadata={
                    "depth_reached": result.depth_reached,
                    "chunks_examined": result.chunks_examined,
                    "llm_calls_made": result.llm_calls_made,
                    "total_tokens_used": int(result.total_tokens_used),
                    "relevant_chunks_count": len(result.relevant_chunks),
                    "total_chunks_created": len(chunks),
                    **result.metadata,
                },
            )

        except Exception as e:
            return Result.fail(
                f"RLM query failed: {str(e)}",
                metadata={"exception_type": type(e).__name__},
            )
