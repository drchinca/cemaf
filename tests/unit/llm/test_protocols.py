"""
Tests for LLM protocols and message types.
"""

import pytest

from cemaf.llm.protocols import (
    CompletionResult,
    LLMConfig,
    Message,
    MessageRole,
    ToolCall,
    ToolDefinition,
)


class TestMessage:
    """Tests for Message dataclass."""

    def test_system_message(self):
        """Create system message."""
        msg = Message.system("You are a helpful assistant")

        assert msg.role == MessageRole.SYSTEM
        assert msg.content == "You are a helpful assistant"

    def test_user_message(self):
        """Create user message."""
        msg = Message.user("Hello!")

        assert msg.role == MessageRole.USER
        assert msg.content == "Hello!"

    def test_assistant_message(self):
        """Create assistant message."""
        msg = Message.assistant("Hi there!")

        assert msg.role == MessageRole.ASSISTANT
        assert msg.content == "Hi there!"

    def test_assistant_with_tool_calls(self):
        """Create assistant message with tool calls."""
        tool_call = ToolCall(id="1", name="search", arguments={"query": "test"})
        msg = Message.assistant("", tool_calls=(tool_call,))

        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "search"

    def test_tool_result_message(self):
        """Create tool result message."""
        msg = Message.tool_result("call_123", "Search results here", name="search")

        assert msg.role == MessageRole.TOOL
        assert msg.tool_call_id == "call_123"
        assert msg.name == "search"

    def test_to_dict(self):
        """Message serializes to dict."""
        msg = Message.user("Hello")
        d = msg.to_dict()

        assert d["role"] == "user"
        assert d["content"] == "Hello"


class TestToolCall:
    """Tests for ToolCall."""

    def test_tool_call_creation(self):
        """Create tool call."""
        tc = ToolCall(id="abc", name="calculator", arguments={"x": 1, "y": 2})

        assert tc.id == "abc"
        assert tc.name == "calculator"
        assert tc.arguments == {"x": 1, "y": 2}

    def test_to_dict(self):
        """Tool call serializes to OpenAI format."""
        tc = ToolCall(id="abc", name="calc", arguments={"x": 1})
        d = tc.to_dict()

        assert d["id"] == "abc"
        assert d["type"] == "function"
        assert d["function"]["name"] == "calc"


class TestToolDefinition:
    """Tests for ToolDefinition."""

    def test_tool_definition(self):
        """Create tool definition."""
        td = ToolDefinition(
            name="search",
            description="Search the web",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
            required=("query",),
        )

        assert td.name == "search"
        assert "query" in td.parameters["properties"]

    def test_to_openai_format(self):
        """Convert to OpenAI format."""
        td = ToolDefinition(name="test", description="Test tool")
        openai = td.to_openai_format()

        assert openai["type"] == "function"
        assert openai["function"]["name"] == "test"

    def test_to_anthropic_format(self):
        """Convert to Anthropic format."""
        td = ToolDefinition(name="test", description="Test tool")
        anthropic = td.to_anthropic_format()

        assert anthropic["name"] == "test"
        assert "input_schema" in anthropic


class TestCompletionResult:
    """Tests for CompletionResult."""

    def test_ok_result(self):
        """Create successful result."""
        msg = Message.assistant("Hello!")
        result = CompletionResult.ok(msg, prompt_tokens=10, completion_tokens=5)

        assert result.success
        assert result.content == "Hello!"
        assert result.total_tokens == 15

    def test_fail_result(self):
        """Create failed result."""
        result = CompletionResult.fail("API error")

        assert not result.success
        assert result.error == "API error"
        assert result.content == ""

    def test_tool_calls_property(self):
        """Get tool calls from result."""
        tc = ToolCall(id="1", name="test", arguments={})
        msg = Message.assistant("", tool_calls=(tc,))
        result = CompletionResult.ok(msg)

        assert len(result.tool_calls) == 1


class TestLLMConfig:
    """Tests for LLMConfig."""

    def test_default_config(self):
        """Default configuration."""
        config = LLMConfig()

        assert config.model == "gpt-4"
        assert config.temperature == 0.7
        assert config.max_tokens == 4096

    def test_custom_config(self):
        """Custom configuration."""
        config = LLMConfig(model="claude-3-opus", temperature=0.0)

        assert config.model == "claude-3-opus"
        assert config.temperature == 0.0

    def test_config_is_frozen(self):
        """Config is immutable."""
        config = LLMConfig()

        with pytest.raises(Exception):
            config.model = "other"  # type: ignore
