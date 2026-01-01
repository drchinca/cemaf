"""
Tests for MockLLMClient.

Uses fixtures from conftest.py:
- mock_llm: MockLLMClient with default responses
- mock_llm_with_tools: MockLLMClient that returns tool calls
- user_message: Standard user message
- conversation: Multi-turn conversation
"""

import pytest

from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import Message


class TestMockLLMClient:
    """Tests for MockLLMClient."""

    @pytest.mark.asyncio
    async def test_complete_returns_response(self, mock_llm: MockLLMClient, user_message: Message):
        """Complete returns configured response."""
        result = await mock_llm.complete([user_message])

        assert result.success
        assert result.content == "Test response"

    @pytest.mark.asyncio
    async def test_complete_cycles_responses(self, user_message: Message):
        """Complete cycles through responses."""
        mock = MockLLMClient(responses=["First", "Second"])

        r1 = await mock.complete([user_message])
        r2 = await mock.complete([user_message])
        r3 = await mock.complete([user_message])

        assert r1.content == "First"
        assert r2.content == "Second"
        assert r3.content == "First"  # Cycles back

    @pytest.mark.asyncio
    async def test_complete_with_tool_calls(self, mock_llm_with_tools: MockLLMClient, user_message: Message):
        """Complete returns tool calls."""
        result = await mock_llm_with_tools.complete([user_message])

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "test_tool"
        assert result.finish_reason == "tool_calls"

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self, user_message: Message):
        """Stream yields word-by-word chunks."""
        mock = MockLLMClient(responses=["Hello world test"])

        chunks = []
        async for chunk in mock.stream([user_message]):
            chunks.append(chunk)

        assert len(chunks) == 3  # "Hello ", "world ", "test"
        assert chunks[-1].is_final
        assert chunks[-1].accumulated_content == "Hello world test"

    @pytest.mark.asyncio
    async def test_call_tracking(self, conversation: list[Message]):
        """Calls are tracked."""
        mock = MockLLMClient(responses=["Response"])

        await mock.complete(conversation[:2])  # First two messages
        await mock.complete(conversation)  # Full conversation

        assert mock.call_count == 2
        assert len(mock.calls) == 2

    @pytest.mark.asyncio
    async def test_reset(self, mock_llm: MockLLMClient, user_message: Message):
        """Reset clears tracking."""
        await mock_llm.complete([user_message])

        mock_llm.reset()

        assert mock_llm.call_count == 0
        assert len(mock_llm.calls) == 0

    def test_count_tokens(self):
        """Token counting works."""
        mock = MockLLMClient(tokens_per_char=0.25)

        # 10 chars * 0.25 = 2.5 -> 2 tokens
        tokens = mock.count_tokens("0123456789")

        assert tokens == 2

    def test_count_messages_tokens(self):
        """Message token counting includes overhead."""
        mock = MockLLMClient(tokens_per_char=0.25)

        messages = [
            Message.system("System prompt"),  # 13 chars
            Message.user("User message"),  # 12 chars
        ]

        tokens = mock.count_messages_tokens(messages)

        # (4 overhead + chars * 0.25) per message
        assert tokens > 0
