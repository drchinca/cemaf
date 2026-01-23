"""
Integration tests for RLM with large contexts (1M+ tokens).

Tests the complete flow from large context → chunking → recursive query → aggregation.
"""

import pytest

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import SimpleTokenEstimator
from cemaf.core.types import TokenCount
from cemaf.llm.mock import MockLLMClient
from cemaf.rlm import create_rlm_tool
from cemaf.rlm.engine import DivideAndConquerQueryEngine
from cemaf.rlm.protocols import ContextChunk


class TestRLMLargeContext:
    """Integration tests for RLM with large contexts."""

    @pytest.fixture
    def estimator(self) -> SimpleTokenEstimator:
        """Create token estimator."""
        return SimpleTokenEstimator(chars_per_token=4.0)

    @pytest.fixture
    def llm_client(self) -> MockLLMClient:
        """Create mock LLM client with realistic responses."""
        # Simulate responses for recursive queries
        responses = [
            "Found 3 mentions in section A",
            "Found 2 mentions in section B",
            "Found 4 mentions in section C",
            "Found 1 mention in section D",
            "Aggregated: Found 5 mentions total in sections A and B",
            "Aggregated: Found 5 mentions total in sections C and D",
            "Final: Found 10 mentions total across all sections",
        ]
        return MockLLMClient(responses=responses)

    @pytest.fixture
    def rlm_tool(self, llm_client: MockLLMClient, estimator: SimpleTokenEstimator) -> object:
        """Create RLM tool configured for large contexts."""
        return create_rlm_tool(
            llm_client=llm_client,
            token_estimator=estimator,
            chunk_size=500,  # 500 tokens per chunk
            max_depth=5,  # Deep recursion
            max_tokens=4000,  # Budget per query
        )

    def test_simulate_1m_token_context(self, rlm_tool: object, estimator: SimpleTokenEstimator) -> None:
        """
        Test RLM with simulated 1M token context.

        This simulates a large document by creating many chunks.
        """
        # Simulate 1M tokens: ~2000 chunks of 500 tokens each
        # Each chunk is ~2000 characters (500 tokens * 4 chars/token)
        chunk_content = "word " * 500  # ~2000 chars = ~500 tokens
        large_document = "\n\n".join([chunk_content] * 2000)  # 2000 chunks

        # Verify size
        estimated_tokens = estimator.estimate(large_document)
        assert estimated_tokens >= 900_000  # Should be close to 1M

        # This would be an async test in real scenario
        # For now, we verify the setup is correct
        assert rlm_tool is not None

    @pytest.mark.asyncio
    async def test_rlm_with_many_chunks(self, rlm_tool: object, llm_client: MockLLMClient) -> None:
        """Test RLM query with many chunks (simulating large context)."""
        # Create large content that will be chunked
        # Each paragraph is ~500 tokens
        paragraphs = []
        for i in range(100):  # 100 paragraphs = ~50K tokens
            paragraphs.append(f"Section {i}: " + "word " * 500)

        large_content = "\n\n".join(paragraphs)

        result = await rlm_tool.execute(
            instruction="Find all mentions of 'important'",
            content=large_content,
        )

        assert result.success is True
        assert result.data is not None
        assert "depth_reached" in result.metadata
        assert "chunks_examined" in result.metadata
        assert "llm_calls_made" in result.metadata
        assert "total_tokens_used" in result.metadata

        # Should have examined chunks (may or may not need recursion depending on budget)
        assert result.metadata["chunks_examined"] > 0
        assert result.metadata["llm_calls_made"] >= 1  # At least one call

    @pytest.mark.asyncio
    async def test_rlm_recursive_aggregation(
        self, llm_client: MockLLMClient, estimator: SimpleTokenEstimator
    ) -> None:
        """Test that RLM properly aggregates results from recursive queries."""
        from cemaf.context.compiler import PriorityContextCompiler

        compiler = PriorityContextCompiler(estimator)
        engine = DivideAndConquerQueryEngine(llm_client, compiler, max_depth=3)

        # Create chunks that will require recursion
        chunks = tuple(
            ContextChunk(
                chunk_id=f"chunk_{i}",
                content=f"Section {i}: important content here",
                token_count=TokenCount(1000),  # Large chunks
            )
            for i in range(8)  # 8 chunks, each 1000 tokens = 8000 tokens total
        )

        budget = TokenBudget(max_tokens=2000)  # Small budget forces recursion

        result = await engine.query(
            instruction="Find all mentions of 'important'",
            chunks=chunks,
            budget=budget,
            max_depth=3,
        )

        assert result.success is True
        assert result.answer is not None
        assert result.depth_reached > 0  # Should have recursed
        assert result.llm_calls_made > 1  # Multiple calls for aggregation

        # Verify aggregation happened - check metadata for divide_and_conquer strategy
        assert result.metadata.get("strategy") == "divide_and_conquer"
        # The answer should be from one of the mock responses (which include aggregation responses)
        assert result.answer is not None

    @pytest.mark.asyncio
    async def test_rlm_metadata_tracking(self, rlm_tool: object, llm_client: MockLLMClient) -> None:
        """Test that RLM tracks complete execution metadata."""
        content = "\n\n".join([f"Section {i}: content" for i in range(50)])

        result = await rlm_tool.execute(
            instruction="Summarize key points",
            content=content,
        )

        assert result.success is True
        metadata = result.metadata

        # Verify all metadata fields are present
        required_fields = [
            "depth_reached",
            "chunks_examined",
            "llm_calls_made",
            "total_tokens_used",
            "relevant_chunks_count",
            "total_chunks_created",
        ]

        for field in required_fields:
            assert field in metadata, f"Missing metadata field: {field}"

        # Verify metadata values are reasonable
        assert metadata["depth_reached"] >= 0
        assert metadata["chunks_examined"] > 0
        assert metadata["llm_calls_made"] > 0
        assert metadata["total_tokens_used"] > 0
        assert metadata["total_chunks_created"] > 0

    @pytest.mark.asyncio
    async def test_rlm_max_depth_enforcement(
        self, llm_client: MockLLMClient, estimator: SimpleTokenEstimator
    ) -> None:
        """Test that max depth is properly enforced even with very large contexts."""
        from cemaf.context.compiler import PriorityContextCompiler

        compiler = PriorityContextCompiler(estimator)
        engine = DivideAndConquerQueryEngine(llm_client, compiler, max_depth=2)

        # Create many large chunks
        chunks = tuple(
            ContextChunk(
                chunk_id=f"chunk_{i}",
                content="word " * 2000,  # Large chunk
                token_count=TokenCount(2000),
            )
            for i in range(20)  # 20 chunks
        )

        budget = TokenBudget(max_tokens=1000)  # Very small budget

        result = await engine.query(
            instruction="Analyze",
            chunks=chunks,
            budget=budget,
            max_depth=2,
        )

        assert result.success is True
        assert result.depth_reached <= 2  # Should not exceed max depth

    @pytest.mark.asyncio
    async def test_rlm_fallback_strategy(
        self, llm_client: MockLLMClient, estimator: SimpleTokenEstimator
    ) -> None:
        """Test fallback when max depth is reached or single large chunk."""
        from cemaf.context.compiler import PriorityContextCompiler

        compiler = PriorityContextCompiler(estimator)
        engine = DivideAndConquerQueryEngine(llm_client, compiler, max_depth=1)

        # Single very large chunk that doesn't fit in budget
        chunk = ContextChunk(
            chunk_id="chunk_0",
            content="word " * 10000,  # Very large
            token_count=TokenCount(10000),
        )

        budget = TokenBudget(max_tokens=100)  # Very small budget

        result = await engine.query(
            instruction="Summarize",
            chunks=(chunk,),
            budget=budget,
            max_depth=1,
        )

        assert result.success is True
        # Should use fallback strategy (query first chunk only)
        assert "strategy" in result.metadata
        assert result.metadata.get("strategy") in ["fallback", "single_query"]
