"""Tests for CachedAnthropicLLMClient."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cemaf.llm.anthropic import AnthropicLLMClient
from cemaf.llm.anthropic_cached import CachedAnthropicLLMClient, make_cache_control
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import Message, ToolDefinition


def _make_usage(
    *,
    input_tokens: int = 10,
    output_tokens: int = 20,
    cache_read: int = 0,
    cache_creation: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
    )


def _make_response(
    *,
    text: str = "Hello from Claude",
    input_tokens: int = 10,
    output_tokens: int = 20,
    cache_read: int = 0,
    cache_creation: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        model="claude-sonnet-4-20250514",
        stop_reason="end_turn",
        usage=_make_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read=cache_read,
            cache_creation=cache_creation,
        ),
    )


def _create_mock_anthropic_client() -> AnthropicLLMClient:
    with patch.dict("sys.modules", {"anthropic": MagicMock()}):
        client = AnthropicLLMClient(api_key="test-key")
        client._client.messages = MagicMock()
        client._client.messages.create = AsyncMock(return_value=_make_response())
        return client


class TestMakeCacheControl:
    def test_default_ephemeral(self):
        assert make_cache_control() == {"type": "ephemeral"}

    def test_with_1h_ttl(self):
        assert make_cache_control(ttl="1h") == {"type": "ephemeral", "ttl": "1h"}

    def test_with_5m_ttl(self):
        assert make_cache_control(ttl="5m") == {"type": "ephemeral", "ttl": "5m"}


class TestCachedAnthropicLLMClient:
    @pytest.mark.asyncio
    async def test_delegates_to_inner_for_non_anthropic_client(self):
        """Non-Anthropic inner client receives the call unchanged (no cache_control)."""
        inner = MockLLMClient(responses=["hello"])
        cached = CachedAnthropicLLMClient(client=inner, cache_threshold_tokens=10)

        messages = [Message.user("test message")]
        result = await cached.complete(messages)

        assert result.success
        assert "hello" in str(result.content)

    def test_count_tokens_delegates(self):
        """count_tokens calls are forwarded to the inner client."""
        inner = MockLLMClient()
        cached = CachedAnthropicLLMClient(client=inner)

        count = cached.count_tokens("some text here")
        assert count > 0

    @pytest.mark.asyncio
    async def test_stream_delegates_to_inner_async_iterator(self):
        inner = MockLLMClient(responses=["hello stream"])
        cached = CachedAnthropicLLMClient(client=inner)

        chunks = [chunk async for chunk in cached.stream(messages=[Message.user("hi")])]

        assert "".join(chunk.content for chunk in chunks) == "hello stream"
        assert chunks[-1].is_final
        assert inner.call_count == 1

    def test_count_messages_tokens_delegates(self):
        inner = MockLLMClient()
        cached = CachedAnthropicLLMClient(client=inner)
        messages = [Message.user("hello"), Message.user("world")]
        count = cached.count_messages_tokens(messages)
        assert count > 0

    def test_config_delegates(self):
        inner = MockLLMClient()
        cached = CachedAnthropicLLMClient(client=inner)
        assert cached.config == inner.config

    @pytest.mark.asyncio
    async def test_automatic_caching_top_level(self):
        """Verify top-level cache_control is injected when automatic_caching is enabled."""
        inner = _create_mock_anthropic_client()
        cached = CachedAnthropicLLMClient(client=inner, automatic_caching=True)

        messages = [Message.user("Tell me a story")]
        result = await cached.complete(messages=messages)

        assert result.success is True
        call_kwargs = inner._client.messages.create.call_args[1]
        assert call_kwargs["cache_control"] == {"type": "ephemeral"}

    @pytest.mark.asyncio
    async def test_automatic_caching_with_1h_ttl(self):
        """Verify 1-hour TTL is passed in top-level cache_control."""
        inner = _create_mock_anthropic_client()
        cached = CachedAnthropicLLMClient(client=inner, ttl="1h", automatic_caching=True)

        messages = [Message.user("Tell me a story")]
        result = await cached.complete(messages=messages)

        assert result.success is True
        call_kwargs = inner._client.messages.create.call_args[1]
        assert call_kwargs["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    @pytest.mark.asyncio
    async def test_system_prompt_cached_when_above_threshold(self):
        """System prompt meeting cache_threshold_tokens gets cache_control."""
        inner = _create_mock_anthropic_client()
        cached = CachedAnthropicLLMClient(
            client=inner,
            cache_threshold_tokens=5,
            cache_system=True,
            ttl="1h",
        )

        long_system = "You are a very knowledgeable assistant specialized in software architecture."
        messages = [Message.system(long_system), Message.user("Hello")]
        await cached.complete(messages=messages)

        call_kwargs = inner._client.messages.create.call_args[1]
        assert isinstance(call_kwargs["system"], list)
        assert call_kwargs["system"][0]["type"] == "text"
        assert call_kwargs["system"][0]["text"] == long_system
        assert call_kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    @pytest.mark.asyncio
    async def test_system_prompt_not_cached_when_below_threshold(self):
        """System prompt under cache_threshold_tokens stays plain string without cache_control."""
        inner = _create_mock_anthropic_client()
        cached = CachedAnthropicLLMClient(
            client=inner,
            cache_threshold_tokens=10_000,
            cache_system=True,
        )

        messages = [Message.system("Be concise"), Message.user("Hello")]
        await cached.complete(messages=messages)

        call_kwargs = inner._client.messages.create.call_args[1]
        assert call_kwargs["system"] == "Be concise"

    @pytest.mark.asyncio
    async def test_tools_cached_on_last_tool(self):
        """Tool definitions receive cache_control on the last item per Anthropic guidelines."""
        inner = _create_mock_anthropic_client()
        cached = CachedAnthropicLLMClient(client=inner, cache_tools=True, ttl="1h")

        tool1 = ToolDefinition(name="search", description="Search")
        tool2 = ToolDefinition(name="calculator", description="Calculate")

        messages = [Message.user("Help me")]
        await cached.complete(messages=messages, tools=[tool1, tool2])

        call_kwargs = inner._client.messages.create.call_args[1]
        tools_payload = call_kwargs["tools"]
        assert len(tools_payload) == 2
        assert "cache_control" not in tools_payload[0]
        assert tools_payload[1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    @pytest.mark.asyncio
    async def test_explicit_message_breakpoint_preserved(self):
        """Explicit cache_control in Message metadata is converted and preserved."""
        inner = _create_mock_anthropic_client()
        cached = CachedAnthropicLLMClient(client=inner)

        messages = [
            Message.user(
                "Static reference document here",
                metadata={"cache_control": {"type": "ephemeral", "ttl": "1h"}},
            ),
            Message.user("Now answer my query"),
        ]
        await cached.complete(messages=messages)

        call_kwargs = inner._client.messages.create.call_args[1]
        first_msg = call_kwargs["messages"][0]
        assert isinstance(first_msg["content"], list)
        assert first_msg["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    @pytest.mark.asyncio
    async def test_emits_cache_metrics_and_captures_usage(self):
        """Cache hit and creation tokens are recorded in metadata and emitted to MetricsCollector."""
        inner = _create_mock_anthropic_client()
        inner._client.messages.create = AsyncMock(
            return_value=_make_response(
                input_tokens=50,
                output_tokens=25,
                cache_read=1200,
                cache_creation=450,
            )
        )
        metrics = MagicMock()
        cached = CachedAnthropicLLMClient(client=inner, metrics=metrics)

        result = await cached.complete(messages=[Message.user("Hi")])

        assert result.metadata["cache_read_input_tokens"] == 1200
        assert result.metadata["cache_creation_input_tokens"] == 450

        metrics.counter.assert_any_call("cemaf.llm.cache.hit", 1200)
        metrics.counter.assert_any_call("cemaf.llm.tokens_saved", 1200)
        metrics.counter.assert_any_call("cemaf.llm.cache.created", 450)

    @pytest.mark.asyncio
    async def test_stream_emits_metrics_and_yields_cache_metadata(self):
        """Streaming with Anthropic client records cache usage on the final chunk."""
        inner = _create_mock_anthropic_client()

        final_msg = _make_response(
            text="Streaming answer",
            input_tokens=20,
            output_tokens=10,
            cache_read=800,
            cache_creation=100,
        )

        async def _event_stream() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(text="Streaming answer"),
            )

        stream_cm = AsyncMock()
        stream_cm.__aenter__ = AsyncMock(return_value=stream_cm)
        stream_cm.__aexit__ = AsyncMock(return_value=False)
        stream_cm.__aiter__ = lambda self: _event_stream()
        stream_cm.get_final_message = AsyncMock(return_value=final_msg)
        inner._client.messages.stream = MagicMock(return_value=stream_cm)

        metrics = MagicMock()
        cached = CachedAnthropicLLMClient(client=inner, metrics=metrics, ttl="1h")

        chunks = [chunk async for chunk in cached.stream(messages=[Message.user("Hello")])]

        assert len(chunks) == 2
        final_chunk = chunks[1]
        assert final_chunk.is_final is True
        assert final_chunk.metadata["cache_read_input_tokens"] == 800
        assert final_chunk.metadata["cache_creation_input_tokens"] == 100

        metrics.counter.assert_any_call("cemaf.llm.cache.hit", 800)
        metrics.counter.assert_any_call("cemaf.llm.tokens_saved", 800)
        metrics.counter.assert_any_call("cemaf.llm.cache.created", 100)
