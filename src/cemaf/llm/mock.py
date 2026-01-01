"""
Mock LLM client for testing.

Provides deterministic responses for unit tests.
"""

from collections.abc import AsyncIterator

from cemaf.core.types import TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMConfig,
    Message,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)


class MockLLMClient:
    """
    Mock LLM client for testing.

    Returns predefined responses or generates deterministic outputs.

    Usage:
        mock = MockLLMClient(responses=["Hello!", "How can I help?"])
        result = await mock.complete([Message.user("Hi")])
        assert result.content == "Hello!"
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        tool_calls: list[list[ToolCall]] | None = None,
        config: LLMConfig | None = None,
        tokens_per_char: float = 0.25,
    ) -> None:
        self._responses = list(responses or ["Mock response"])
        self._tool_calls = list(tool_calls or [])
        self._config = config or LLMConfig(model="mock-model")
        self._tokens_per_char = tokens_per_char
        self._call_count = 0
        self._calls: list[list[Message]] = []

    @property
    def config(self) -> LLMConfig:
        """Get client configuration."""
        return self._config

    @property
    def call_count(self) -> int:
        """Number of complete/stream calls made."""
        return self._call_count

    @property
    def calls(self) -> list[list[Message]]:
        """All message lists passed to complete/stream."""
        return self._calls

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        """Generate a mock completion."""
        self._calls.append(list(messages))

        # Get response based on call count
        response_idx = self._call_count % len(self._responses)
        response_text = self._responses[response_idx]

        # Get tool calls if provided
        tool_calls_for_response: tuple[ToolCall, ...] = ()
        if self._tool_calls and self._call_count < len(self._tool_calls):
            tool_calls_for_response = tuple(self._tool_calls[self._call_count])

        self._call_count += 1

        # Calculate tokens
        prompt_tokens = self.count_messages_tokens(messages)
        completion_tokens = self.count_tokens(response_text)

        message = Message.assistant(response_text, tool_calls_for_response)

        return CompletionResult.ok(
            message=message,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=self._config.model,
            finish_reason="tool_calls" if tool_calls_for_response else "stop",
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a mock streaming completion."""
        self._calls.append(list(messages))

        response_idx = self._call_count % len(self._responses)
        response_text = self._responses[response_idx]
        self._call_count += 1

        # Stream word by word
        words = response_text.split()
        accumulated = ""

        for i, word in enumerate(words):
            chunk_content = word + (" " if i < len(words) - 1 else "")
            accumulated += chunk_content

            yield StreamChunk(
                content=chunk_content,
                accumulated_content=accumulated,
                is_final=i == len(words) - 1,
                finish_reason="stop" if i == len(words) - 1 else None,
            )

    def count_tokens(self, text: str) -> TokenCount:
        """Estimate tokens from text."""
        return TokenCount(max(1, int(len(text) * self._tokens_per_char)))

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        """Estimate tokens from messages."""
        total = 0
        for msg in messages:
            # Add overhead per message
            total += 4  # role, content separators
            total += self.count_tokens(msg.content)
        return TokenCount(total)

    def add_response(self, response: str) -> None:
        """Add a response to the queue."""
        self._responses.append(response)

    def add_tool_calls(self, tool_calls: list[ToolCall]) -> None:
        """Add tool calls for next response."""
        self._tool_calls.append(tool_calls)

    def reset(self) -> None:
        """Reset call tracking."""
        self._call_count = 0
        self._calls.clear()
