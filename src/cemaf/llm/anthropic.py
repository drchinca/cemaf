"""Anthropic Claude adapter for LLMClient protocol."""

import json
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any, cast

from cemaf.core.types import LLMProvider, TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMConfig,
    Message,
    MessageRole,
    StreamChunk,
    ToolCall,
    ToolDefinition,
    coerce_finish_reason,
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

    @property
    def config(self) -> LLMConfig:
        """Get client configuration."""
        return self._config

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
        *,
        fidelity: object | None = None,
        token_budget: object | None = None,
        correlation_id: str | None = None,
    ) -> CompletionResult:
        """Send messages to Claude and return completion result."""
        del fidelity, token_budget, correlation_id
        cfg = config_override or self._config
        system_msg, api_messages = _convert_messages(messages=messages)

        kwargs: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "messages": api_messages or [{"role": "user", "content": ""}],
        }
        if system_msg:
            kwargs["system"] = system_msg
        if tools:
            kwargs["tools"] = [t.to_anthropic_format() for t in tools]
        if cfg.cache_control:
            # extra_body also supports SDK versions predating automatic caching.
            kwargs["extra_body"] = {"cache_control": cfg.cache_control}
        if cfg.stop_sequences:
            kwargs["stop_sequences"] = list(cfg.stop_sequences)

        start = time.monotonic()
        try:
            # Optional SDK fields are assembled dynamically from CEMAF's
            # provider-neutral config. Cast only at the typed SDK boundary;
            # the Anthropic client still validates the request at runtime.
            create_message = cast(Any, self._client.messages.create)
            response = await create_message(**kwargs)
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

        native = response.stop_reason or "end_turn"
        cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
        cache_created = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        cache_metadata = _cache_usage(response.usage)

        result = CompletionResult.ok(
            message=message,
            prompt_tokens=response.usage.input_tokens + cache_read + cache_created,
            completion_tokens=response.usage.output_tokens,
            model=response.model,
            finish_reason=coerce_finish_reason(native),
            finish_reason_native=native,
            provider=LLMProvider.ANTHROPIC,
            latency_ms=latency_ms,
        )
        if cache_metadata:
            result = replace(result, metadata=cache_metadata)
        return result

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream responses from Claude."""
        cfg = config_override or self._config
        system_msg, api_messages = _convert_messages(messages=messages)

        kwargs: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "messages": api_messages or [{"role": "user", "content": ""}],
        }
        if system_msg:
            kwargs["system"] = system_msg
        if tools:
            kwargs["tools"] = [t.to_anthropic_format() for t in tools]
        if cfg.cache_control:
            kwargs["extra_body"] = {"cache_control": cfg.cache_control}
        if cfg.stop_sequences:
            kwargs["stop_sequences"] = list(cfg.stop_sequences)

        stream_message = cast(Any, self._client.messages.stream)
        async with stream_message(**kwargs) as stream:
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
                    content_block = cast(Any, event.content_block)
                    if getattr(content_block, "type", "tool_use") == "tool_use" and hasattr(
                        content_block, "id"
                    ):
                        current_tool_id = content_block.id
                        current_tool_name = content_block.name
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
            cache_read = getattr(final_message.usage, "cache_read_input_tokens", 0) or 0
            cache_created = getattr(final_message.usage, "cache_creation_input_tokens", 0) or 0
            final_metadata = _cache_usage(final_message.usage)

            yield StreamChunk(
                content="",
                accumulated_content=accumulated_text,
                tool_calls=tuple(tool_calls),
                is_final=True,
                finish_reason=coerce_finish_reason(final_message.stop_reason or "end_turn"),
                prompt_tokens=TokenCount(final_message.usage.input_tokens + cache_read + cache_created),
                completion_tokens=TokenCount(final_message.usage.output_tokens),
                metadata=final_metadata,
            )

    def count_tokens(self, text: str) -> TokenCount:
        """Estimate tokens for English-ASCII text.

        Uses a refined heuristic (~3.5 chars/token) calibrated for Claude
        tokenization across prose, code, and JSON. The original 4 chars/token
        estimate (0.25 tokens/char) under-counted Unicode, code, and JSON by
        30-50% and silently drove context-window overruns.

        For exact counts, callers should use Anthropic's `count_tokens` API
        directly — this method stays heuristic because it's called hot in
        budget guards and context compilers where an async network call
        would be prohibitive.
        """
        if not text:
            return TokenCount(0)
        # 3.5 chars/token is the documented average for Claude across
        # English prose. Slightly conservative for code/JSON which skew
        # shorter per token; accepting the small over-estimate keeps the
        # budget guard honest.
        estimated = max(1, round(len(text) / 3.5))
        return TokenCount(estimated)

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

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        """Exact token count via the Anthropic /messages/count_tokens endpoint.

        Use before long-context requests where a 30% heuristic under-estimate
        would cause a 400 context_length_exceeded. The API is free to call
        and caches server-side.
        """
        system_msg, api_messages = _convert_messages(messages=messages)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
        }
        if system_msg:
            kwargs["system"] = system_msg
        if tools:
            kwargs["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]
        count_tokens = cast(Any, self._client.messages.count_tokens)
        response = await count_tokens(**kwargs)
        return TokenCount(response.input_tokens)


def _convert_messages(
    *,
    messages: list[Message],
) -> tuple[str | list[dict[str, Any]] | None, list[dict[str, Any]]]:
    """Extract system message and convert CEMAF messages to Anthropic format.

    Preserves explicit prompt caching breakpoints from `Message.metadata["cache_control"]`.
    """
    system_blocks: list[dict[str, Any]] = []
    api_messages: list[dict[str, Any]] = []

    for msg in messages:
        cc = msg.metadata.get("cache_control")
        if msg.role == MessageRole.SYSTEM:
            blocks = _content_blocks(msg.content)
            if cc:
                _mark_cache_breakpoint(blocks, cc)
            system_blocks.extend(blocks)
        elif msg.role == MessageRole.TOOL:
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": msg.tool_call_id,
                "content": msg.content,
            }
            if cc:
                block["cache_control"] = cc
            api_messages.append(
                {
                    "role": "user",
                    "content": [block],
                }
            )
        elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
            content_blocks = _content_blocks(msg.content) if msg.content else []
            for tc in msg.tool_calls:
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                )
            if cc and content_blocks:
                _mark_cache_breakpoint(content_blocks, cc)
            api_messages.append({"role": "assistant", "content": content_blocks})
        else:
            if cc or isinstance(msg.content, list):
                blocks = _content_blocks(msg.content)
                if cc:
                    _mark_cache_breakpoint(blocks, cc)
                api_messages.append({"role": msg.role.value, "content": blocks})
            else:
                api_messages.append({"role": msg.role.value, "content": msg.content})

    system_msg: str | list[dict[str, Any]] | None = system_blocks or None
    if len(system_blocks) == 1 and set(system_blocks[0]) == {"type", "text"}:
        system_msg = system_blocks[0]["text"]
    return system_msg, api_messages


def _content_blocks(content: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy blocks so adding cache markers never mutates caller messages."""
    return [{"type": "text", "text": content}] if isinstance(content, str) else [dict(b) for b in content]


def _mark_cache_breakpoint(blocks: list[dict[str, Any]], cache_control: Any) -> None:
    """Mark the last eligible block; thinking and empty text cannot be cached."""
    for block in reversed(blocks):
        if block.get("type") in {"thinking", "redacted_thinking"}:
            continue
        if block.get("type") == "text" and not block.get("text"):
            continue
        block["cache_control"] = cache_control
        return


def _cache_usage(usage: Any) -> dict[str, Any]:
    """Keep the provider's input breakdown alongside total prompt token usage."""
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    if not (cache_read or cache_created):
        return {}
    return {
        "input_tokens": usage.input_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_created,
    }
