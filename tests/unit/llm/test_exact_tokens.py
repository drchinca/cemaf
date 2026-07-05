"""Tests for count_tokens_exact on the LLMClient protocol."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from cemaf.core.types import TokenCount
from cemaf.llm.protocols import Message, MessageRole


@pytest.mark.asyncio
async def test_anthropic_count_tokens_exact_delegates_to_api() -> None:
    """AnthropicLLMClient.count_tokens_exact calls the SDK count_tokens endpoint."""
    # Avoid real SDK: monkey-patch the client post-init.
    from cemaf.llm.anthropic import AnthropicLLMClient

    client = AnthropicLLMClient(api_key="test-key", model="claude-test")

    captured: dict[str, Any] = {}

    class _FakeMessages:
        async def count_tokens(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return SimpleNamespace(input_tokens=12345)

    client._client = SimpleNamespace(messages=_FakeMessages())  # type: ignore[assignment]

    messages = [
        Message.system(content="system prompt"),
        Message.user(content="hello world"),
    ]
    result = await client.count_tokens_exact(messages=messages)

    assert result == TokenCount(12345)
    assert captured["model"] == "claude-test"
    assert captured["system"] == "system prompt"
    assert isinstance(captured["messages"], list)
    assert captured["messages"][0]["role"] == MessageRole.USER.value


@pytest.mark.asyncio
async def test_anthropic_count_tokens_exact_forwards_tools() -> None:
    from cemaf.llm.anthropic import AnthropicLLMClient
    from cemaf.llm.protocols import ToolDefinition

    client = AnthropicLLMClient(api_key="test-key", model="claude-test")
    captured: dict[str, Any] = {}

    class _FakeMessages:
        async def count_tokens(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return SimpleNamespace(input_tokens=500)

    client._client = SimpleNamespace(messages=_FakeMessages())  # type: ignore[assignment]

    tool = ToolDefinition(
        name="search",
        description="Search the web",
        parameters={"type": "object", "properties": {"q": {"type": "string"}}},
        required=("q",),
    )
    await client.count_tokens_exact(
        messages=[Message.user(content="search for cats")],
        tools=[tool],
    )
    assert captured["tools"][0]["name"] == "search"
