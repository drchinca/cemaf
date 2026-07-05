"""
Prompt-caching decorator for AnthropicLLMClient.

Adds cache_control: {"type": "ephemeral"} to system prompts and
large static message blocks. Cache hits reduce per-token cost by ~90%.
Emits cemaf.llm.cache.hit and cemaf.llm.tokens_saved metrics.
"""

import json
from collections.abc import AsyncIterator, Awaitable
from typing import Any, cast

from cemaf.core.types import LLMProvider, TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    Message,
    StreamChunk,
    ToolDefinition,
)
from cemaf.observability.protocols import MetricsCollector

_CACHE_CONTROL = {"type": "ephemeral"}


class CachedAnthropicLLMClient:
    """
    Wraps any LLMClient and injects Anthropic prompt-caching headers.

    When the inner client is an AnthropicLLMClient, this class rewrites
    the API call to add cache_control breakpoints. For any other client
    type the call is delegated unchanged — caching is silently skipped
    rather than erroring so the same wrapper works in test environments
    with mock clients.

    Coupling note: accessing client._client is an intentional narrow
    coupling to AnthropicLLMClient. The alternative — a broader protocol
    extension — would leak Anthropic details into the protocol boundary.
    """

    def __init__(
        self,
        client: LLMClient,
        cache_threshold_tokens: int = 1_000,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self._client = client
        self._cache_threshold_tokens = cache_threshold_tokens
        self._metrics = metrics

    @property
    def config(self) -> LLMConfig:
        return self._client.config

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
        from cemaf.llm.anthropic import AnthropicLLMClient, _convert_messages

        if not isinstance(self._client, AnthropicLLMClient):
            return await self._client.complete(
                messages=messages,
                tools=tools,
                config_override=config_override,
                fidelity=fidelity,
                token_budget=token_budget,
                correlation_id=correlation_id,
            )

        import time

        cfg = config_override or self._client.config
        system_msg, api_messages = _convert_messages(messages=messages)

        # Inject cache_control on the system prompt when it is large enough.
        system_payload: str | list[dict[str, Any]] | None = None
        if system_msg:
            system_tokens = self._client.count_tokens(system_msg)
            if system_tokens >= self._cache_threshold_tokens:
                system_payload = [{"type": "text", "text": system_msg, "cache_control": _CACHE_CONTROL}]
            else:
                system_payload = system_msg

        # Inject cache_control on the last large user turn (static context prefix).
        if len(api_messages) >= 2:
            second_to_last = api_messages[-2]
            content = second_to_last.get("content", "")
            content_text = content if isinstance(content, str) else json.dumps(content)
            if self._client.count_tokens(content_text) >= self._cache_threshold_tokens and isinstance(
                content, str
            ):
                api_messages[-2] = {
                    **second_to_last,
                    "content": [{"type": "text", "text": content, "cache_control": _CACHE_CONTROL}],
                }

        kwargs: dict[str, object] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "messages": api_messages or [{"role": "user", "content": ""}],
        }
        if system_payload is not None:
            kwargs["system"] = system_payload
        if tools:
            kwargs["tools"] = [t.to_anthropic_format() for t in tools]

        start = time.monotonic()
        try:
            create_message = cast(Any, self._client._client.messages.create)
            response = await create_message(**kwargs)
        except Exception as exc:
            return CompletionResult.fail(error=f"Anthropic API error: {exc}")

        latency_ms = (time.monotonic() - start) * 1000
        self._emit_cache_metrics(response)

        from cemaf.llm.protocols import ToolCall

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

        result = CompletionResult.ok(
            message=message,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            model=response.model,
            finish_reason=response.stop_reason or "end_turn",
            finish_reason_native=response.stop_reason or "end_turn",
            provider=LLMProvider.ANTHROPIC,
            latency_ms=latency_ms,
        )

        # Attach cache usage to metadata so callers can inspect it.
        cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
        cache_created = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        if cache_read or cache_created:
            result = CompletionResult(
                **{
                    **result.__dict__,
                    "metadata": {
                        "cache_read_input_tokens": cache_read,
                        "cache_creation_input_tokens": cache_created,
                    },
                }
            )

        return result

    def _emit_cache_metrics(self, response: Any) -> None:
        if self._metrics is None:
            return
        cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
        cache_created = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
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
        stream_result: Any = self._client.stream(
            messages=messages,
            tools=tools,
            config_override=config_override,
        )
        stream = (
            cast(AsyncIterator[StreamChunk], stream_result)
            if hasattr(stream_result, "__aiter__")
            else await cast(Awaitable[AsyncIterator[StreamChunk]], stream_result)
        )
        async for chunk in stream:
            yield chunk

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
