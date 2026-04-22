"""Anthropic Claude adapter for LLMClient protocol."""

import json
import time
from collections.abc import AsyncIterator

from cemaf.core.types import TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMConfig,
    Message,
    MessageRole,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)


class AnthropicLLMClient:
    """LLMClient implementation using the Anthropic SDK."""

    def __init__(self, *, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError("anthropic package required. Install with: uv add anthropic") from exc
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._config = LLMConfig(model=model)
        self._tokens_per_char = 0.25

    @property
    def config(self) -> LLMConfig:
        """Get client configuration."""
        return self._config

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        """Send messages to Claude and return completion result."""
        cfg = config_override or self._config
        system_msg, api_messages = _convert_messages(messages=messages)

        kwargs: dict[str, object] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "messages": api_messages or [{"role": "user", "content": ""}],
        }
        if system_msg:
            kwargs["system"] = system_msg
        if tools:
            kwargs["tools"] = [t.to_anthropic_format() for t in tools]

        start = time.monotonic()
        try:
            response = await self._client.messages.create(**kwargs)
        except Exception as exc:
            return CompletionResult.fail(error=f"Anthropic API error: {exc}")

        latency_ms = (time.monotonic() - start) * 1000

        content_text = ""
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        message = Message.assistant(
            content_text,
            tuple(tool_calls),
        )

        return CompletionResult.ok(
            message=message,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            model=response.model,
            finish_reason=response.stop_reason or "end_turn",
            latency_ms=latency_ms,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream responses from Claude."""
        cfg = config_override or self._config
        system_msg, api_messages = _convert_messages(messages=messages)

        kwargs: dict[str, object] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "messages": api_messages or [{"role": "user", "content": ""}],
        }
        if system_msg:
            kwargs["system"] = system_msg
        if tools:
            kwargs["tools"] = [t.to_anthropic_format() for t in tools]

        async with self._client.messages.stream(**kwargs) as stream:
            accumulated_text = ""
            tool_calls: list[ToolCall] = []
            current_tool_json = ""
            current_tool_id = ""
            current_tool_name = ""

            async for event in stream:
                if event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        accumulated_text += event.delta.text
                        yield StreamChunk(
                            content=event.delta.text,
                            accumulated_content=accumulated_text,
                        )
                    elif hasattr(event.delta, "partial_json"):
                        current_tool_json += event.delta.partial_json
                elif event.type == "content_block_start":
                    if hasattr(event.content_block, "id"):
                        current_tool_id = event.content_block.id
                        current_tool_name = event.content_block.name
                        current_tool_json = ""
                elif event.type == "content_block_stop" and current_tool_id:
                    try:
                        args = json.loads(current_tool_json) if current_tool_json else {}
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append(
                        ToolCall(
                            id=current_tool_id,
                            name=current_tool_name,
                            arguments=args,
                        )
                    )
                    current_tool_id = ""

            final_message = await stream.get_final_message()
            yield StreamChunk(
                content="",
                accumulated_content=accumulated_text,
                tool_calls=tuple(tool_calls),
                is_final=True,
                finish_reason=final_message.stop_reason or "end_turn",
                prompt_tokens=TokenCount(final_message.usage.input_tokens),
                completion_tokens=TokenCount(final_message.usage.output_tokens),
            )

    def count_tokens(self, text: str) -> TokenCount:
        """Estimate tokens from text using character heuristic."""
        return TokenCount(max(1, int(len(text) * self._tokens_per_char)))

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        """Estimate tokens from messages."""
        total = 0
        for msg in messages:
            total += 4
            if isinstance(msg.content, str):
                total += self.count_tokens(text=msg.content)
            else:
                total += self.count_tokens(text=json.dumps(msg.content))
        return TokenCount(total)


def _convert_messages(
    *,
    messages: list[Message],
) -> tuple[str | None, list[dict[str, object]]]:
    """Extract system message and convert CEMAF messages to Anthropic format."""
    system_msg: str | None = None
    api_messages: list[dict[str, object]] = []

    for msg in messages:
        if msg.role == MessageRole.SYSTEM:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            system_msg = content
        elif msg.role == MessageRole.TOOL:
            api_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": msg.content if isinstance(msg.content, str) else str(msg.content),
                        }
                    ],
                }
            )
        elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
            content_blocks: list[dict[str, object]] = []
            if msg.content:
                content_blocks.append({"type": "text", "text": str(msg.content)})
            for tc in msg.tool_calls:
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                )
            api_messages.append({"role": "assistant", "content": content_blocks})
        else:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            api_messages.append({"role": msg.role.value, "content": content})

    return system_msg, api_messages
