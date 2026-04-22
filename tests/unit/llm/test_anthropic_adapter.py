"""Tests for Anthropic LLM adapter."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cemaf.llm.anthropic import AnthropicLLMClient, _convert_messages
from cemaf.llm.protocols import (
    Message,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)

# --- Fixtures ---


def _make_usage(*, input_tokens: int = 10, output_tokens: int = 20) -> SimpleNamespace:
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


def _make_text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _make_tool_block(
    *,
    id: str,
    name: str,
    input: dict[str, Any],
) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def _make_response(
    *,
    content_blocks: list[SimpleNamespace] | None = None,
    model: str = "claude-sonnet-4-20250514",
    stop_reason: str = "end_turn",
    input_tokens: int = 10,
    output_tokens: int = 20,
) -> SimpleNamespace:
    return SimpleNamespace(
        content=content_blocks or [_make_text_block(text="Hello from Claude")],
        model=model,
        stop_reason=stop_reason,
        usage=_make_usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


@pytest.fixture
def mock_anthropic_module() -> MagicMock:
    """Provide a mock anthropic module with AsyncAnthropic."""
    module = MagicMock()
    module.AsyncAnthropic.return_value = AsyncMock()
    return module


# --- Tests ---


class TestImportError:
    def test_import_error_without_anthropic_package(self) -> None:
        """Raise ImportError with helpful message when anthropic not installed."""
        with (
            patch.dict("sys.modules", {"anthropic": None}),
            pytest.raises(ImportError, match="anthropic package required"),
        ):
            AnthropicLLMClient(api_key="test-key")


class TestMessageConversion:
    def test_extracts_system_message(self) -> None:
        """System messages are extracted separately for Anthropic API."""
        messages = [
            Message.system("Be helpful"),
            Message.user("Hello"),
        ]
        system_msg, api_msgs = _convert_messages(messages=messages)
        assert system_msg == "Be helpful"
        assert len(api_msgs) == 1
        assert api_msgs[0]["role"] == "user"
        assert api_msgs[0]["content"] == "Hello"

    def test_no_system_message(self) -> None:
        """Handle conversations without system messages."""
        messages = [Message.user("Hello")]
        system_msg, api_msgs = _convert_messages(messages=messages)
        assert system_msg is None
        assert len(api_msgs) == 1

    def test_preserves_message_order(self) -> None:
        """Multi-turn messages maintain order."""
        messages = [
            Message.user("Hi"),
            Message.assistant("Hello!"),
            Message.user("How are you?"),
        ]
        _, api_msgs = _convert_messages(messages=messages)
        assert len(api_msgs) == 3
        assert api_msgs[0]["role"] == "user"
        assert api_msgs[1]["role"] == "assistant"
        assert api_msgs[2]["role"] == "user"

    def test_tool_result_message_converted_to_user_role(self) -> None:
        """Tool result messages become user messages with tool_result content blocks."""
        messages = [
            Message.tool_result(
                tool_call_id="call_123",
                content="The result is 42",
                name="calculator",
            ),
        ]
        _, api_msgs = _convert_messages(messages=messages)
        assert len(api_msgs) == 1
        assert api_msgs[0]["role"] == "user"
        content = api_msgs[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 1
        assert content[0]["type"] == "tool_result"
        assert content[0]["tool_use_id"] == "call_123"
        assert content[0]["content"] == "The result is 42"

    def test_assistant_message_with_tool_calls(self) -> None:
        """Assistant messages with tool_calls include tool_use content blocks."""
        tc = ToolCall(id="call_456", name="search", arguments={"q": "cats"})
        messages = [
            Message.assistant("Let me search.", (tc,)),
        ]
        _, api_msgs = _convert_messages(messages=messages)
        assert len(api_msgs) == 1
        assert api_msgs[0]["role"] == "assistant"
        content = api_msgs[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0] == {"type": "text", "text": "Let me search."}
        assert content[1] == {
            "type": "tool_use",
            "id": "call_456",
            "name": "search",
            "input": {"q": "cats"},
        }

    def test_assistant_tool_calls_no_text(self) -> None:
        """Assistant with tool_calls but empty content omits text block."""
        tc = ToolCall(id="call_789", name="lookup", arguments={})
        messages = [
            Message.assistant("", (tc,)),
        ]
        _, api_msgs = _convert_messages(messages=messages)
        content = api_msgs[0]["content"]
        assert isinstance(content, list)
        # Empty string is falsy, so no text block
        assert len(content) == 1
        assert content[0]["type"] == "tool_use"


class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_converts_messages(self) -> None:
        """Verify message format conversion and response parsing."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            client = AnthropicLLMClient(api_key="test-key")

        mock_response = _make_response()
        client._client.messages.create = AsyncMock(return_value=mock_response)

        messages = [
            Message.system("Be helpful"),
            Message.user("What is 2+2?"),
        ]
        result = await client.complete(messages=messages)

        assert result.success is True
        assert result.content == "Hello from Claude"
        assert result.model == "claude-sonnet-4-20250514"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20
        assert result.finish_reason == "end_turn"

        # Verify API was called with correct format
        call_kwargs = client._client.messages.create.call_args[1]
        assert call_kwargs["system"] == "Be helpful"
        assert call_kwargs["messages"] == [
            {"role": "user", "content": "What is 2+2?"},
        ]

    @pytest.mark.asyncio
    async def test_complete_with_tool_calls(self) -> None:
        """Parse tool_use blocks from response."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            client = AnthropicLLMClient(api_key="test-key")

        mock_response = _make_response(
            content_blocks=[
                _make_text_block(text="Let me check."),
                _make_tool_block(
                    id="tool_1",
                    name="calculator",
                    input={"expression": "2+2"},
                ),
            ],
            stop_reason="tool_use",
        )
        client._client.messages.create = AsyncMock(return_value=mock_response)

        result = await client.complete(messages=[Message.user("What is 2+2?")])

        assert result.success is True
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "calculator"
        assert result.tool_calls[0].arguments == {"expression": "2+2"}
        assert result.finish_reason == "tool_use"

    @pytest.mark.asyncio
    async def test_complete_handles_api_error(self) -> None:
        """Return failed CompletionResult on API error."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            client = AnthropicLLMClient(api_key="test-key")

        client._client.messages.create = AsyncMock(side_effect=RuntimeError("rate limited"))

        result = await client.complete(messages=[Message.user("Hello")])

        assert result.success is False
        assert "rate limited" in (result.error or "")

    @pytest.mark.asyncio
    async def test_complete_passes_tools(self) -> None:
        """Tool definitions are converted to Anthropic format."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            client = AnthropicLLMClient(api_key="test-key")

        mock_response = _make_response()
        client._client.messages.create = AsyncMock(return_value=mock_response)

        tool = ToolDefinition(
            name="search",
            description="Search the web",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            required=("query",),
        )

        await client.complete(
            messages=[Message.user("Search for cats")],
            tools=[tool],
        )

        call_kwargs = client._client.messages.create.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tools"][0]["name"] == "search"


class TestStream:
    @pytest.mark.asyncio
    async def test_stream_yields_text_chunks(self) -> None:
        """Verify streaming produces StreamChunk objects with accumulated content."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            client = AnthropicLLMClient(api_key="test-key")

        final_message = _make_response(
            content_blocks=[_make_text_block(text="Hello world")],
            input_tokens=5,
            output_tokens=2,
        )

        # Build event stream matching Anthropic's event types
        async def _event_stream() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(text="Hello"),
            )
            yield SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(text=" world"),
            )

        stream_cm = AsyncMock()
        stream_cm.__aenter__ = AsyncMock(return_value=stream_cm)
        stream_cm.__aexit__ = AsyncMock(return_value=False)
        stream_cm.__aiter__ = lambda self: _event_stream()
        stream_cm.get_final_message = AsyncMock(return_value=final_message)

        client._client.messages.stream = MagicMock(return_value=stream_cm)

        chunks: list[StreamChunk] = []
        async for chunk in client.stream(messages=[Message.user("Hi")]):
            chunks.append(chunk)

        # Text chunks + final chunk
        assert len(chunks) == 3
        assert chunks[0].content == "Hello"
        assert chunks[0].accumulated_content == "Hello"
        assert chunks[1].content == " world"
        assert chunks[1].accumulated_content == "Hello world"
        assert chunks[2].is_final is True
        assert chunks[2].finish_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_stream_yields_tool_calls(self) -> None:
        """Verify streaming captures tool_use events as ToolCalls."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            client = AnthropicLLMClient(api_key="test-key")

        final_message = _make_response(
            content_blocks=[
                _make_tool_block(id="tool_1", name="search", input={"q": "cats"}),
            ],
            input_tokens=10,
            output_tokens=15,
            stop_reason="tool_use",
        )

        async def _event_stream() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(
                type="content_block_start",
                content_block=SimpleNamespace(id="tool_1", name="search"),
            )
            yield SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(partial_json='{"q": "cats"}'),
            )
            yield SimpleNamespace(type="content_block_stop")

        stream_cm = AsyncMock()
        stream_cm.__aenter__ = AsyncMock(return_value=stream_cm)
        stream_cm.__aexit__ = AsyncMock(return_value=False)
        stream_cm.__aiter__ = lambda self: _event_stream()
        stream_cm.get_final_message = AsyncMock(return_value=final_message)

        client._client.messages.stream = MagicMock(return_value=stream_cm)

        chunks: list[StreamChunk] = []
        async for chunk in client.stream(messages=[Message.user("Search cats")]):
            chunks.append(chunk)

        # Only the final chunk (no text deltas)
        assert len(chunks) == 1
        assert chunks[0].is_final is True
        assert len(chunks[0].tool_calls) == 1
        assert chunks[0].tool_calls[0].name == "search"
        assert chunks[0].tool_calls[0].arguments == {"q": "cats"}


class TestTokenCounting:
    def test_count_tokens(self) -> None:
        """Token counting uses character heuristic."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            client = AnthropicLLMClient(api_key="test-key")

        count = client.count_tokens(text="Hello world")
        assert count >= 1

    def test_count_messages_tokens(self) -> None:
        """Message token count includes overhead."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            client = AnthropicLLMClient(api_key="test-key")

        messages = [Message.user("Hello")]
        count = client.count_messages_tokens(messages=messages)
        assert count > 0


class TestConfig:
    def test_config_property(self) -> None:
        """Config reflects model passed at init."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            client = AnthropicLLMClient(
                api_key="test-key",
                model="claude-opus-4-20250514",
            )

        assert client.config.model == "claude-opus-4-20250514"


class TestFactory:
    def test_factory_creates_anthropic(self) -> None:
        """Registry creates AnthropicLLMClient via 'anthropic' backend."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            from cemaf.llm.factories import llm_registry

            client = llm_registry.create(
                backend="anthropic",
                api_key="test-key",
                model="claude-sonnet-4-20250514",
            )

        assert isinstance(client, AnthropicLLMClient)

    def test_factory_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Factory raises ValueError without api_key."""
        from cemaf.llm.factories import llm_registry

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="api_key required"):
            llm_registry.create(backend="anthropic")
