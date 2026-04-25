"""Tests for CachedAnthropicLLMClient."""

import pytest

from cemaf.llm.anthropic_cached import CachedAnthropicLLMClient
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import Message


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

        # MockLLMClient uses a heuristic; just verify the call doesn't raise
        count = cached.count_tokens("some text here")
        assert count > 0

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
