"""
Unit tests for the Tools layer.

Tests:
- Tool execution
- ToolResult creation
- ToolSchema serialization

Uses fixtures from conftest.py:
- mock_tool: Basic MockTool that succeeds
- failing_tool: MockTool that returns failure
- raising_tool: MockTool that raises exception
"""

import pytest

from cemaf.tools.base import Tool, ToolResult, ToolSchema, tool_decorator


class TestToolResult:
    """Tests for ToolResult."""

    def test_ok_creates_success_result(self):
        """ToolResult.ok creates successful result."""
        result = ToolResult.ok(data=42)

        assert result.success is True
        assert result.data == 42
        assert result.error is None

    def test_fail_creates_failure_result(self):
        """ToolResult.fail creates failed result."""
        result = ToolResult.fail(error="Something went wrong")

        assert result.success is False
        assert result.data is None
        assert result.error == "Something went wrong"

    def test_result_is_immutable(self):
        """ToolResult is frozen/immutable."""
        result = ToolResult.ok(data=42)

        with pytest.raises((TypeError, AttributeError)):
            result.data = 100  # type: ignore

    def test_ok_with_metadata(self):
        """ToolResult.ok accepts metadata."""
        result = ToolResult.ok(data="test", metadata={"tokens": 100})

        assert result.metadata == {"tokens": 100}


class TestToolSchema:
    """Tests for ToolSchema."""

    def test_schema_creation(self):
        """ToolSchema can be created with parameters."""
        schema = ToolSchema(
            name="test_tool",
            description="A test tool",
            parameters={
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                },
            },
            required=("input",),
        )

        assert schema.name == "test_tool"
        assert schema.description == "A test tool"
        assert "input" in schema.parameters["properties"]

    def test_to_openai_format(self):
        """ToolSchema converts to OpenAI format."""
        schema = ToolSchema(
            name="my_tool",
            description="Does something",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                },
            },
            required=("x",),
        )

        openai = schema.to_openai_format()

        assert openai["type"] == "function"
        assert openai["function"]["name"] == "my_tool"
        assert openai["function"]["parameters"]["required"] == ["x"]

    def test_to_anthropic_format(self):
        """ToolSchema converts to Anthropic format."""
        schema = ToolSchema(
            name="my_tool",
            description="Does something",
            required=("x",),
        )

        anthropic = schema.to_anthropic_format()

        assert anthropic["name"] == "my_tool"
        assert anthropic["input_schema"]["required"] == ["x"]

    def test_schema_validates_json_serializable(self):
        """ToolSchema validates that parameters are JSON-serializable."""
        # Valid JSON-serializable parameters should work
        schema = ToolSchema(
            name="valid_tool",
            description="Valid tool",
            parameters={
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                },
            },
        )
        assert schema.name == "valid_tool"

    def test_schema_rejects_non_serializable_parameters(self):
        """ToolSchema rejects non-JSON-serializable parameters."""
        # Function objects are not JSON-serializable
        with pytest.raises(ValueError, match="JSON-serializable"):
            ToolSchema(
                name="invalid_tool",
                description="Invalid tool",
                parameters={
                    "type": "object",
                    "properties": {
                        "callback": lambda x: x,  # Not JSON-serializable
                    },
                },
            )


class TestTool:
    """Tests for Tool base class."""

    @pytest.mark.asyncio
    async def test_tool_execution(self, mock_tool):
        """Tool can be executed with kwargs."""
        result = await mock_tool.execute(input="test")

        assert result.success is True
        assert mock_tool.call_count == 1

    @pytest.mark.asyncio
    async def test_tool_has_schema(self, mock_tool):
        """Tool has schema property."""
        schema = mock_tool.schema

        assert schema.name == "Mock Tool"
        assert "input" in schema.parameters["properties"]

    @pytest.mark.asyncio
    async def test_failing_tool(self, failing_tool):
        """Failing tool returns failure result."""
        result = await failing_tool.execute()

        assert result.success is False
        assert result.error is not None


class TestToolDecorator:
    """Tests for tool_decorator."""

    @pytest.mark.asyncio
    async def test_decorator_creates_tool(self):
        """tool_decorator creates a Tool from function."""

        @tool_decorator(
            name="add",
            description="Add numbers",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                },
            },
            required=("x", "y"),
        )
        async def add(x: float, y: float) -> ToolResult:
            return ToolResult.ok(x + y)

        # Decorator returns a Tool instance
        assert isinstance(add, Tool)
        assert add.id == "add"

        # Can execute
        result = await add.execute(x=10, y=5)
        assert result.success
        assert result.data == 15
