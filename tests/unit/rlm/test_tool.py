"""
Unit tests for RLM tool integration.

Tests RLM as a CEMAF tool.
"""

import pytest

from cemaf.context.budget import TokenBudget
from cemaf.core.types import TokenCount, ToolID
from cemaf.rlm.protocols import ContextChunk, RecursiveQueryResult
from cemaf.rlm.tool import RLMQueryTool
from cemaf.tools.base import ToolSchema


class MockChunkingStrategy:
    """Mock chunking strategy for testing."""

    def __init__(self, chunks: tuple[ContextChunk, ...]) -> None:
        """Initialize with predefined chunks."""
        self.chunks = chunks
        self.chunk_calls: list[tuple[str, int]] = []

    def chunk(self, content: str, max_chunk_tokens: int) -> tuple[ContextChunk, ...]:
        """Mock chunk method."""
        self.chunk_calls.append((content, max_chunk_tokens))
        return self.chunks

    def create_hierarchy(self, chunks: tuple[ContextChunk, ...]) -> tuple[ContextChunk, ...]:
        """Mock hierarchy creation."""
        return chunks


class MockQueryEngine:
    """Mock query engine for testing."""

    def __init__(self, result: RecursiveQueryResult | None = None) -> None:
        """Initialize with predefined result."""
        self.result = result or RecursiveQueryResult.ok(
            answer="Mock answer",
            depth_reached=1,
            chunks_examined=2,
            llm_calls_made=1,
            total_tokens_used=TokenCount(100),
        )
        self.query_calls: list[tuple[str, tuple[ContextChunk, ...], TokenBudget, int]] = []

    async def query(
        self,
        instruction: str,
        chunks: tuple[ContextChunk, ...],
        budget: TokenBudget,
        max_depth: int = 3,
    ) -> RecursiveQueryResult:
        """Mock query method."""
        self.query_calls.append((instruction, chunks, budget, max_depth))
        return self.result


class TestRLMQueryTool:
    """Tests for RLMQueryTool."""

    @pytest.fixture
    def sample_chunks(self) -> tuple[ContextChunk, ...]:
        """Create sample chunks."""
        return tuple(
            ContextChunk(
                chunk_id=f"chunk_{i}",
                content=f"Content {i}",
                token_count=TokenCount(10),
            )
            for i in range(3)
        )

    @pytest.fixture
    def chunking_strategy(self, sample_chunks: tuple[ContextChunk, ...]) -> MockChunkingStrategy:
        """Create mock chunking strategy."""
        return MockChunkingStrategy(sample_chunks)

    @pytest.fixture
    def query_engine(self) -> MockQueryEngine:
        """Create mock query engine."""
        return MockQueryEngine()

    @pytest.fixture
    def tool(
        self,
        query_engine: MockQueryEngine,
        chunking_strategy: MockChunkingStrategy,
    ) -> RLMQueryTool:
        """Create RLM tool."""
        return RLMQueryTool(
            query_engine,
            chunking_strategy,
            default_max_depth=3,
            default_max_tokens=4000,
            default_chunk_size=500,
        )

    def test_tool_id(self, tool: RLMQueryTool) -> None:
        """Test tool ID."""
        assert tool.id == ToolID("rlm_query")

    def test_tool_schema(self, tool: RLMQueryTool) -> None:
        """Test tool schema."""
        schema = tool.schema

        assert isinstance(schema, ToolSchema)
        assert schema.name == "rlm_query"
        assert "recursive" in schema.description.lower()
        assert "instruction" in schema.parameters["properties"]
        assert "content" in schema.parameters["properties"]
        assert "max_depth" in schema.parameters["properties"]
        assert "instruction" in schema.required
        assert "content" in schema.required

    def test_schema_parameter_defaults(self, tool: RLMQueryTool) -> None:
        """Test that schema includes default values."""
        schema = tool.schema
        params = schema.parameters["properties"]

        assert "default=3" in params["max_depth"]["description"]
        assert "default=4000" in params["max_tokens"]["description"]
        assert "default=500" in params["chunk_size"]["description"]

    @pytest.mark.asyncio
    async def test_execute_success(
        self,
        tool: RLMQueryTool,
        chunking_strategy: MockChunkingStrategy,
        query_engine: MockQueryEngine,
    ) -> None:
        """Test successful execution."""
        result = await tool.execute(
            instruction="Find mentions of X",
            content="Large content to analyze",
        )

        assert result.success is True
        assert result.data == "Mock answer"
        assert "depth_reached" in result.metadata
        assert "chunks_examined" in result.metadata
        assert "llm_calls_made" in result.metadata
        assert result.metadata["depth_reached"] == 1
        assert result.metadata["chunks_examined"] == 2
        assert result.metadata["llm_calls_made"] == 1

    @pytest.mark.asyncio
    async def test_execute_with_custom_params(
        self,
        tool: RLMQueryTool,
        chunking_strategy: MockChunkingStrategy,
        query_engine: MockQueryEngine,
    ) -> None:
        """Test execution with custom parameters."""
        await tool.execute(
            instruction="Analyze",
            content="Content",
            max_depth=5,
            max_tokens=8000,
            chunk_size=1000,
        )

        assert len(query_engine.query_calls) == 1
        call_instruction, call_chunks, call_budget, call_max_depth = query_engine.query_calls[0]

        assert call_instruction == "Analyze"
        assert call_max_depth == 5
        assert call_budget.max_tokens == 8000

        assert len(chunking_strategy.chunk_calls) == 1
        chunk_content, chunk_max_tokens = chunking_strategy.chunk_calls[0]
        assert chunk_max_tokens == 1000

    @pytest.mark.asyncio
    async def test_execute_with_defaults(
        self,
        tool: RLMQueryTool,
        query_engine: MockQueryEngine,
    ) -> None:
        """Test execution uses default parameters."""
        await tool.execute(
            instruction="Test",
            content="Content",
        )

        assert len(query_engine.query_calls) == 1
        _, _, call_budget, call_max_depth = query_engine.query_calls[0]

        assert call_max_depth == 3
        assert call_budget.max_tokens == 4000

    @pytest.mark.asyncio
    async def test_execute_empty_chunks(
        self,
        query_engine: MockQueryEngine,
    ) -> None:
        """Test execution with empty chunks."""
        empty_chunking = MockChunkingStrategy(())
        tool = RLMQueryTool(query_engine, empty_chunking)

        result = await tool.execute(
            instruction="Test",
            content="Content",
        )

        assert result.success is False
        assert "No chunks" in result.error

    @pytest.mark.asyncio
    async def test_execute_query_failure(
        self,
        chunking_strategy: MockChunkingStrategy,
    ) -> None:
        """Test execution when query fails."""
        failing_engine = MockQueryEngine(
            result=RecursiveQueryResult.fail(
                error="Query failed",
                depth_reached=1,
                chunks_examined=2,
                llm_calls_made=1,
            )
        )
        tool = RLMQueryTool(failing_engine, chunking_strategy)

        result = await tool.execute(
            instruction="Test",
            content="Content",
        )

        assert result.success is False
        assert "Query failed" in result.error
        assert "depth_reached" in result.metadata
        assert result.metadata["depth_reached"] == 1

    @pytest.mark.asyncio
    async def test_execute_exception_handling(
        self,
        query_engine: MockQueryEngine,
    ) -> None:
        """Test execution handles exceptions."""

        class FailingChunking:
            def chunk(self, content: str, max_chunk_tokens: int) -> tuple[ContextChunk, ...]:
                raise ValueError("Chunking failed")

            def create_hierarchy(self, chunks: tuple[ContextChunk, ...]) -> tuple[ContextChunk, ...]:
                return chunks

        tool = RLMQueryTool(query_engine, FailingChunking())  # type: ignore[arg-type]

        result = await tool.execute(
            instruction="Test",
            content="Content",
        )

        assert result.success is False
        assert "RLM query failed" in result.error
        assert "exception_type" in result.metadata
        assert result.metadata["exception_type"] == "ValueError"

    @pytest.mark.asyncio
    async def test_metadata_includes_all_info(
        self,
        tool: RLMQueryTool,
        sample_chunks: tuple[ContextChunk, ...],
    ) -> None:
        """Test that result metadata includes all execution info."""
        result = await tool.execute(
            instruction="Test",
            content="Content",
        )

        assert result.success is True
        metadata = result.metadata

        assert "depth_reached" in metadata
        assert "chunks_examined" in metadata
        assert "llm_calls_made" in metadata
        assert "total_tokens_used" in metadata
        assert "relevant_chunks_count" in metadata
        assert "total_chunks_created" in metadata
        assert metadata["total_chunks_created"] == len(sample_chunks)

    def test_tool_parameter_validation(self, tool: RLMQueryTool) -> None:
        """Test that tool schema has proper validation."""
        schema = tool.schema
        params = schema.parameters["properties"]

        assert params["max_depth"]["minimum"] == 1
        assert params["max_depth"]["maximum"] == 10
        assert params["max_tokens"]["minimum"] == 100
        assert params["max_tokens"]["maximum"] == 200000
        assert params["chunk_size"]["minimum"] == 100
        assert params["chunk_size"]["maximum"] == 10000
