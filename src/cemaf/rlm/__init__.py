"""
RLM (Recursive Language Models) module for CEMAF.

Enables infinite context via divide-and-conquer querying.

Key Components:
    - ContextChunk: Immutable chunk of context
    - RecursiveQueryResult: Result of recursive query
    - ChunkingStrategy: Protocol for chunking content
    - RecursiveQueryEngine: Protocol for recursive querying
    - FixedSizeChunkingStrategy: Simple fixed-size chunking
    - DivideAndConquerQueryEngine: Divide-and-conquer query engine
    - RLMQueryTool: RLM as a CEMAF tool

Usage:
    from cemaf.rlm import create_rlm_tool
    from cemaf.llm.anthropic import AnthropicLLMClient

    llm = AnthropicLLMClient(api_key="...")
    rlm_tool = create_rlm_tool(llm, chunk_size=500, max_depth=3)

    result = await rlm_tool.execute(
        instruction="Find all mentions of CEMAF",
        content=large_document,
    )
"""

from cemaf.context.compiler import TokenEstimator
from cemaf.llm.protocols import LLMClient
from cemaf.rlm.chunking import FixedSizeChunkingStrategy
from cemaf.rlm.engine import DivideAndConquerQueryEngine
from cemaf.rlm.protocols import (
    ChunkingStrategy,
    ContextChunk,
    RecursiveQueryEngine,
    RecursiveQueryResult,
)
from cemaf.rlm.tool import RLMQueryTool

__all__ = [
    "ContextChunk",
    "RecursiveQueryResult",
    "ChunkingStrategy",
    "RecursiveQueryEngine",
    "FixedSizeChunkingStrategy",
    "DivideAndConquerQueryEngine",
    "RLMQueryTool",
    "create_rlm_tool",
]


def create_rlm_tool(
    llm_client: LLMClient,
    token_estimator: TokenEstimator | None = None,
    chunk_size: int = 500,
    max_depth: int = 3,
    max_tokens: int = 4000,
) -> RLMQueryTool:
    """
    Create RLM query tool with sensible defaults.

    This is the recommended way to create an RLM tool. It configures
    all the necessary components with sensible defaults.

    Args:
        llm_client: LLM client for queries
        token_estimator: Token estimator (defaults to SimpleTokenEstimator)
        chunk_size: Target tokens per chunk (default=500)
        max_depth: Maximum recursion depth (default=3)
        max_tokens: Default token budget (default=4000)

    Returns:
        Configured RLMQueryTool ready to use

    Example:
        from cemaf.rlm import create_rlm_tool
        from cemaf.llm.anthropic import AnthropicLLMClient

        llm = AnthropicLLMClient(api_key="...")
        rlm_tool = create_rlm_tool(
            llm,
            chunk_size=500,
            max_depth=3,
            max_tokens=4000,
        )

        result = await rlm_tool.execute(
            instruction="Summarize the main themes",
            content=large_document,
        )

        if result.success:
            print(f"Answer: {result.data}")
            print(f"Depth: {result.metadata['depth_reached']}")
            print(f"LLM Calls: {result.metadata['llm_calls_made']}")
    """
    from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator

    estimator = token_estimator or SimpleTokenEstimator()
    compiler = PriorityContextCompiler(estimator)

    chunking = FixedSizeChunkingStrategy(estimator, chunk_size)
    engine = DivideAndConquerQueryEngine(llm_client, compiler, max_depth)

    return RLMQueryTool(
        engine,
        chunking,
        default_max_depth=max_depth,
        default_max_tokens=max_tokens,
        default_chunk_size=chunk_size,
    )
