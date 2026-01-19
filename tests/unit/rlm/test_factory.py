"""
Unit tests for RLM factory function.

Tests the create_rlm_tool() factory for creating configured RLM tools.
"""

import pytest

from cemaf.context.compiler import SimpleTokenEstimator
from cemaf.core.types import ToolID
from cemaf.llm.protocols import CompletionResult, LLMConfig, Message
from cemaf.rlm import create_rlm_tool
from cemaf.rlm.tool import RLMQueryTool


class MockLLMClient:
    """Mock LLM client for factory tests."""

    def __init__(self) -> None:
        """Initialize mock client."""
        self.call_count = 0

    @property
    def config(self) -> LLMConfig:
        """Get mock config."""
        return LLMConfig(model="mock", temperature=0.7)

    async def complete(
        self,
        messages: list[Message],
        tools: list | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        """Mock completion."""
        self.call_count += 1
        return CompletionResult.ok(
            message=Message.assistant("Mock response"),
            prompt_tokens=10,
            completion_tokens=5,
            model="mock",
        )

    def count_tokens(self, text: str) -> int:
        """Mock token counting."""
        return len(text) // 4

    def count_messages_tokens(self, messages: list[Message]) -> int:
        """Mock message token counting."""
        return 10


class TestCreateRLMTool:
    """Tests for create_rlm_tool() factory function."""

    @pytest.fixture
    def llm_client(self) -> MockLLMClient:
        """Create mock LLM client."""
        return MockLLMClient()

    def test_factory_creates_tool(self, llm_client: MockLLMClient) -> None:
        """Test that factory creates an RLMQueryTool instance."""
        tool = create_rlm_tool(llm_client)

        assert isinstance(tool, RLMQueryTool)
        assert tool.id == ToolID("rlm_query")

    def test_factory_default_parameters(self, llm_client: MockLLMClient) -> None:
        """Test factory uses default parameters."""
        tool = create_rlm_tool(llm_client)

        # Verify defaults through tool schema
        schema = tool.schema
        assert "default=3" in schema.parameters["properties"]["max_depth"]["description"]
        assert "default=4000" in schema.parameters["properties"]["max_tokens"]["description"]
        assert "default=500" in schema.parameters["properties"]["chunk_size"]["description"]

    def test_factory_custom_chunk_size(self, llm_client: MockLLMClient) -> None:
        """Test factory with custom chunk size."""
        tool = create_rlm_tool(llm_client, chunk_size=1000)

        schema = tool.schema
        assert "default=1000" in schema.parameters["properties"]["chunk_size"]["description"]

    def test_factory_custom_max_depth(self, llm_client: MockLLMClient) -> None:
        """Test factory with custom max depth."""
        tool = create_rlm_tool(llm_client, max_depth=5)

        schema = tool.schema
        assert "default=5" in schema.parameters["properties"]["max_depth"]["description"]

    def test_factory_custom_max_tokens(self, llm_client: MockLLMClient) -> None:
        """Test factory with custom max tokens."""
        tool = create_rlm_tool(llm_client, max_tokens=8000)

        schema = tool.schema
        assert "default=8000" in schema.parameters["properties"]["max_tokens"]["description"]

    def test_factory_with_custom_token_estimator(self, llm_client: MockLLMClient) -> None:
        """Test factory with custom token estimator."""
        custom_estimator = SimpleTokenEstimator(chars_per_token=5.0)
        tool = create_rlm_tool(llm_client, token_estimator=custom_estimator)

        assert isinstance(tool, RLMQueryTool)

    def test_factory_all_custom_params(self, llm_client: MockLLMClient) -> None:
        """Test factory with all custom parameters."""
        tool = create_rlm_tool(
            llm_client,
            chunk_size=750,
            max_depth=4,
            max_tokens=6000,
        )

        schema = tool.schema
        assert "default=750" in schema.parameters["properties"]["chunk_size"]["description"]
        assert "default=4" in schema.parameters["properties"]["max_depth"]["description"]
        assert "default=6000" in schema.parameters["properties"]["max_tokens"]["description"]

    @pytest.mark.asyncio
    async def test_factory_tool_executes(self, llm_client: MockLLMClient) -> None:
        """Test that tool created by factory can execute queries."""
        tool = create_rlm_tool(llm_client, chunk_size=100, max_depth=2)

        result = await tool.execute(
            instruction="Test query",
            content="Small test content that should work.",
        )

        assert result.success is True
        assert llm_client.call_count > 0

    def test_factory_creates_new_instances(self, llm_client: MockLLMClient) -> None:
        """Test that factory creates new instances each time."""
        tool1 = create_rlm_tool(llm_client, chunk_size=100)
        tool2 = create_rlm_tool(llm_client, chunk_size=200)

        # Different tools should be different instances
        assert tool1 is not tool2

        # With different configurations
        assert "default=100" in tool1.schema.parameters["properties"]["chunk_size"]["description"]
        assert "default=200" in tool2.schema.parameters["properties"]["chunk_size"]["description"]

    def test_factory_components_integration(self, llm_client: MockLLMClient) -> None:
        """Test that factory integrates components correctly."""
        tool = create_rlm_tool(llm_client, chunk_size=500)

        # Verify the tool has the expected structure
        # We can't directly inspect private attributes, but we can verify behavior
        schema = tool.schema

        assert schema.name == "rlm_query"
        assert "instruction" in schema.parameters["properties"]
        assert "content" in schema.parameters["properties"]
        assert "max_depth" in schema.parameters["properties"]
