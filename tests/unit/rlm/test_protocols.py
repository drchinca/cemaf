"""
Unit tests for RLM protocols.

Tests core protocol implementations and data structures.
"""

import pytest

from cemaf.context.source import ContextSource
from cemaf.core.types import TokenCount
from cemaf.rlm.protocols import ContextChunk, RecursiveQueryResult


class TestContextChunk:
    """Tests for ContextChunk dataclass."""

    def test_chunk_creation(self) -> None:
        """Test basic chunk creation."""
        chunk = ContextChunk(
            chunk_id="chunk_0",
            content="Test content",
            token_count=TokenCount(10),
        )

        assert chunk.chunk_id == "chunk_0"
        assert chunk.content == "Test content"
        assert chunk.token_count == TokenCount(10)
        assert chunk.parent_id is None
        assert chunk.depth == 0
        assert chunk.metadata == {}

    def test_chunk_with_hierarchy(self) -> None:
        """Test chunk with parent-child relationship."""
        chunk = ContextChunk(
            chunk_id="chunk_1",
            content="Child content",
            token_count=TokenCount(5),
            parent_id="chunk_0",
            depth=1,
        )

        assert chunk.parent_id == "chunk_0"
        assert chunk.depth == 1

    def test_chunk_with_metadata(self) -> None:
        """Test chunk with custom metadata."""
        chunk = ContextChunk(
            chunk_id="chunk_0",
            content="Test",
            token_count=TokenCount(5),
            metadata={"source": "test", "priority": 10},
        )

        assert chunk.metadata["source"] == "test"
        assert chunk.metadata["priority"] == 10

    def test_chunk_immutability(self) -> None:
        """Test that chunks are immutable."""
        chunk = ContextChunk(
            chunk_id="chunk_0",
            content="Test",
            token_count=TokenCount(5),
        )

        with pytest.raises(AttributeError):
            chunk.content = "Modified"  # type: ignore[misc]

    def test_to_context_source(self) -> None:
        """Test conversion to ContextSource."""
        chunk = ContextChunk(
            chunk_id="chunk_0",
            content="Test content",
            token_count=TokenCount(10),
            parent_id="parent",
            depth=1,
            metadata={"custom": "value"},
        )

        source = chunk.to_context_source(priority=5)

        assert isinstance(source, ContextSource)
        assert source.content == "Test content"
        assert source.token_count == TokenCount(10)
        assert source.priority == 5
        assert source.source_type == "rlm_chunk"
        assert source.source_id == "chunk_0"
        assert source.compressible is True
        assert source.metadata["parent_id"] == "parent"
        assert source.metadata["depth"] == 1
        assert source.metadata["custom"] == "value"

    def test_to_context_source_default_priority(self) -> None:
        """Test conversion with default priority."""
        chunk = ContextChunk(
            chunk_id="chunk_0",
            content="Test",
            token_count=TokenCount(5),
        )

        source = chunk.to_context_source()
        assert source.priority == 0


class TestRecursiveQueryResult:
    """Tests for RecursiveQueryResult dataclass."""

    def test_successful_result(self) -> None:
        """Test creation of successful result."""
        result = RecursiveQueryResult.ok(
            answer="Found 3 matches",
            depth_reached=2,
            chunks_examined=5,
            llm_calls_made=3,
            total_tokens_used=TokenCount(1000),
        )

        assert result.success is True
        assert result.answer == "Found 3 matches"
        assert result.error is None
        assert result.depth_reached == 2
        assert result.chunks_examined == 5
        assert result.llm_calls_made == 3
        assert result.total_tokens_used == TokenCount(1000)
        assert result.relevant_chunks == ()

    def test_successful_result_with_chunks(self) -> None:
        """Test successful result with relevant chunks."""
        chunk1 = ContextChunk(
            chunk_id="chunk_0",
            content="Content 1",
            token_count=TokenCount(10),
        )
        chunk2 = ContextChunk(
            chunk_id="chunk_1",
            content="Content 2",
            token_count=TokenCount(10),
        )

        result = RecursiveQueryResult.ok(
            answer="Found matches",
            relevant_chunks=(chunk1, chunk2),
            depth_reached=1,
            chunks_examined=2,
            llm_calls_made=1,
        )

        assert result.success is True
        assert len(result.relevant_chunks) == 2
        assert result.relevant_chunks[0].chunk_id == "chunk_0"
        assert result.relevant_chunks[1].chunk_id == "chunk_1"

    def test_successful_result_defaults(self) -> None:
        """Test successful result with default values."""
        result = RecursiveQueryResult.ok(answer="Test answer")

        assert result.success is True
        assert result.answer == "Test answer"
        assert result.depth_reached == 0
        assert result.chunks_examined == 0
        assert result.llm_calls_made == 0
        assert result.total_tokens_used == TokenCount(0)
        assert result.relevant_chunks == ()
        assert result.metadata == {}

    def test_failed_result(self) -> None:
        """Test creation of failed result."""
        result = RecursiveQueryResult.fail(
            error="Query failed",
            depth_reached=1,
            chunks_examined=3,
            llm_calls_made=2,
        )

        assert result.success is False
        assert result.error == "Query failed"
        assert result.answer is None
        assert result.depth_reached == 1
        assert result.chunks_examined == 3
        assert result.llm_calls_made == 2

    def test_failed_result_defaults(self) -> None:
        """Test failed result with default values."""
        result = RecursiveQueryResult.fail(error="Error occurred")

        assert result.success is False
        assert result.error == "Error occurred"
        assert result.depth_reached == 0
        assert result.chunks_examined == 0
        assert result.llm_calls_made == 0

    def test_result_with_metadata(self) -> None:
        """Test result with custom metadata."""
        result = RecursiveQueryResult.ok(
            answer="Test",
            metadata={"strategy": "divide_and_conquer", "custom": "value"},
        )

        assert result.metadata["strategy"] == "divide_and_conquer"
        assert result.metadata["custom"] == "value"

    def test_result_immutability(self) -> None:
        """Test that results are immutable."""
        result = RecursiveQueryResult.ok(answer="Test")

        with pytest.raises(AttributeError):
            result.answer = "Modified"  # type: ignore[misc]
