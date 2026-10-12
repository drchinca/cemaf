"""Prompt-caching decorator for AnthropicLLMClient.

Supports:
- Automatic prompt caching via top-level `cache_control`
- Explicit cache breakpoints on tools, system messages, and static message prefixes
- Configurable TTL: 5-minute (default) or 1-hour extended duration
- Metrics emission: cemaf.llm.cache.hit, cemaf.llm.tokens_saved, cemaf.llm.cache.created
- Full streaming support with token cache usage tracking

Reference: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
"""

import json
import time
from collections.abc import AsyncIterator
from typing import Any, cast

from cemaf.core.types import LLMProvider, TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    Message,
    StreamChunk,
    ToolCall,
    ToolDefinition,
    coerce_finish_reason,
)
from cemaf.observability.protocols import MetricsCollector


def make_cache_control(ttl: str | None = None) -> dict[str, str]:
    """Build Anthropic cache_control specification with optional TTL (e.g. '1h' or '5m')."""
    payload: dict[str, str] = {"type": "ephemeral"}
    if ttl:
        payload["ttl"] = ttl
    return payload


class CachedAnthropicLLMClient:
    """Wraps an LLMClient and injects Anthropic prompt-caching headers.

    When the inner client is an AnthropicLLMClient, this class configures
    automatic caching or explicit breakpoints based on settings. For any
    other client type the call is delegated unchanged — caching is silently
    skipped rather than erroring so the same wrapper works with mock clients.

    Coupling note: accessing client._client is an intentional narrow
    coupling to AnthropicLLMClient.
    """

    def __init__(
        self,
        client: LLMClient,
        cache_threshold_tokens: int = 1_000,
        metrics: MetricsCollector | None = None,
        *,
        ttl: str | None = None,
        automatic_caching: bool = True,
        cache_tools: bool = True,
        cache_system: bool = True,
        cache_messages: bool = True,
    ) -> None:
        self._client = client
        self._cache_threshold_tokens = cache_threshold_tokens
        self._metrics = metrics
        self._ttl = ttl
        self._automatic_caching = automatic_caching
        self._cache_tools = cache_tools
        self._cache_system = cache_system
        self._cache_messages = cache_messages
        self._cache_control = make_cache_control(ttl=ttl)

    @property
    def config(self) -> LLMConfig:
        return self._client.config

    @property
    def cache_control(self) -> dict[str, str]:
        """The cache_control header dictionary configured for this client."""
        return dict(self._cache_control)

    def _prepare_anthropic_kwargs(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> dict[str, Any]:
        """Prepare Anthropic API call kwargs with prompt caching injected."""
        from cemaf.llm.anthropic import _convert_messages

        cfg = config_override or self._client.config
        system_msg, api_messages = _convert_messages(messages=messages)

        # 1. System prompt caching
        system_payload: str | list[dict[str, Any]] | None = None
        if system_msg is not None:
            if isinstance(system_msg, list):
                system_payload = system_msg
            elif self._cache_system:
                system_tokens = self._client.count_tokens(str(system_msg))
                if system_tokens >= self._cache_threshold_tokens or self._cache_threshold_tokens == 0:
                    system_payload = [
                        {"type": "text", "text": str(system_msg), "cache_control": self._cache_control}
                    ]
                else:
                    system_payload = system_msg
            else:
                system_payload = system_msg

        # 2. Tool definitions caching (cache on the last tool in the tools array per Anthropic docs)
        formatted_tools: list[dict[str, Any]] | None = None
        if tools:
            formatted_tools = [t.to_anthropic_format() for t in tools]
            if self._cache_tools and formatted_tools and "cache_control" not in formatted_tools[-1]:
                formatted_tools[-1]["cache_control"] = self._cache_control

        # 3. Message turns caching when automatic caching is disabled
        if not self._automatic_caching and self._cache_messages and len(api_messages) >= 2:
            second_to_last = api_messages[-2]
            content = second_to_last.get("content", "")
            if isinstance(content, str):
                content_text = content
                if self._client.count_tokens(content_text) >= self._cache_threshold_tokens:
                    api_messages[-2] = {
                        **second_to_last,
                        "content": [{"type": "text", "text": content, "cache_control": self._cache_control}],
                    }

        kwargs: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "messages": api_messages or [{"role": "user", "content": ""}],
        }
        if system_payload is not None:
            kwargs["system"] = system_payload
        if formatted_tools:
            kwargs["tools"] = formatted_tools
        if cfg.stop_sequences:
            kwargs["stop_sequences"] = list(cfg.stop_sequences)

        # 4. Top-level automatic caching
        if self._automatic_caching:
            kwargs["cache_control"] = self._cache_control
        elif cfg.cache_control:
            kwargs["cache_control"] = cfg.cache_control

        return kwargs

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
        """Complete with prompt-caching applied when the inner client supports it."""
        from cemaf.llm.anthropic import AnthropicLLMClient

        if not isinstance(self._client, AnthropicLLMClient):
            return await self._client.complete(
                messages=messages,
                tools=tools,
                config_override=config_override,
                fidelity=fidelity,
                token_budget=token_budget,
                correlation_id=correlation_id,
            )

        kwargs = self._prepare_anthropic_kwargs(
            messages=messages,
            tools=tools,
            config_override=config_override,
        )

        start = time.monotonic()
        try:
            create_message = cast(Any, self._client._client.messages.create)
            response = await create_message(**kwargs)
        except Exception as exc:
            return CompletionResult.fail(error=f"Anthropic API error: {exc}")

        latency_ms = (time.monotonic() - start) * 1000
        self._emit_cache_metrics(response)

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

        message = Message.assistant(content_text, tuple(tool_calls))
        native = response.stop_reason or "end_turn"

        cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
        cache_created = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        cache_metadata: dict[str, Any] = {}
        if cache_read:
            cache_metadata["cache_read_input_tokens"] = cache_read
        if cache_created:
            cache_metadata["cache_creation_input_tokens"] = cache_created

        result = CompletionResult.ok(
            message=message,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            model=response.model,
            finish_reason=coerce_finish_reason(native),
            finish_reason_native=native,
            provider=LLMProvider.ANTHROPIC,
            latency_ms=latency_ms,
        )
        if cache_metadata:
            import dataclasses

            result = dataclasses.replace(result, metadata={**result.metadata, **cache_metadata})

        return result

    def _emit_cache_metrics(self, response: Any) -> None:
        """Emit cache hit and creation counters to MetricsCollector."""
        if self._metrics is None:
            return
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_created = getattr(usage, "cache_creation_input_tokens", 0) or 0
        if cache_read:
            self._metrics.counter("cemaf.llm.cache.hit", cache_read)
            self._metrics.counter("cemaf.llm.tokens_saved", cache_read)
        if cache_created:
            self._metrics.counter("cemaf.llm.cache.created", cache_created)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream responses with prompt-caching applied and usage metrics recorded."""
        from cemaf.llm.anthropic import AnthropicLLMClient

        if not isinstance(self._client, AnthropicLLMClient):
            async for chunk in self._client.stream(
                messages=messages,
                tools=tools,
                config_override=config_override,
            ):
                yield chunk
            return

        kwargs = self._prepare_anthropic_kwargs(
            messages=messages,
            tools=tools,
            config_override=config_override,
        )

        stream_message = cast(Any, self._client._client.messages.stream)
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
            self._emit_cache_metrics(final_message)

            cache_read = getattr(final_message.usage, "cache_read_input_tokens", 0) or 0
            cache_created = getattr(final_message.usage, "cache_creation_input_tokens", 0) or 0
            final_metadata: dict[str, Any] = {}
            if cache_read:
                final_metadata["cache_read_input_tokens"] = cache_read
            if cache_created:
                final_metadata["cache_creation_input_tokens"] = cache_created

            yield StreamChunk(
                content="",
                accumulated_content=accumulated_text,
                tool_calls=tuple(tool_calls),
                is_final=True,
                finish_reason=coerce_finish_reason(final_message.stop_reason or "end_turn"),
                prompt_tokens=TokenCount(final_message.usage.input_tokens),
                completion_tokens=TokenCount(final_message.usage.output_tokens),
                metadata=final_metadata,
            )

    def count_tokens(self, text: str) -> TokenCount:
        return self._client.count_tokens(text)

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        return self._client.count_messages_tokens(messages)

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        return await self._client.count_tokens_exact(messages=messages, tools=tools)
