"""Anthropic prompt caching composed through the public LLMClient protocol.

Automatic caching and explicit breakpoints support the default five-minute TTL
or a one-hour TTL. Completion and streaming cache usage flows through the base
adapter into metrics, run logging, and token budgets.
"""

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from cemaf.core.types import TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    Message,
    MessageRole,
    StreamChunk,
    ToolDefinition,
)
from cemaf.observability.protocols import MetricsCollector


def make_cache_control(ttl: str | None = None) -> dict[str, str]:
    """Build an Anthropic cache marker, validating the supported TTLs."""
    if ttl not in (None, "5m", "1h"):
        raise ValueError("cache TTL must be '5m', '1h', or None")
    payload = {"type": "ephemeral"}
    if ttl is not None:
        payload["ttl"] = ttl
    return payload


class CachedAnthropicLLMClient:
    """Add cache policy to an Anthropic adapter without bypassing its methods.

    Other LLMClient implementations receive calls unchanged. Caller-supplied
    breakpoints take precedence over generated ones. Automatic caching reserves
    a breakpoint slot and yields to explicit markers that would conflict with it.
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
        if cache_threshold_tokens < 0:
            raise ValueError("cache_threshold_tokens must be nonnegative")
        self._client = client
        self._cache_threshold_tokens = cache_threshold_tokens
        self._metrics = metrics
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
        """Return a copy of the configured cache marker."""
        return dict(self._cache_control)

    def _prepare_request(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        config_override: LLMConfig | None,
    ) -> tuple[list[Message], list[ToolDefinition] | None, LLMConfig | None]:
        from cemaf.llm.anthropic import AnthropicLLMClient, _convert_messages

        if not isinstance(self._client, AnthropicLLMClient):
            return messages, tools, config_override

        cfg = config_override or self.config
        control = cfg.cache_control if cfg.cache_control is not None else self._cache_control
        system, api_messages = _convert_messages(messages=messages)
        # Inspect the adapter's actual block layout, including markers embedded
        # in structured content, so caller breakpoints retain their semantics.
        blocks = [tool.to_anthropic_format() for tool in tools or []]
        if isinstance(system, list):
            blocks.extend(system)
        elif system:
            blocks.append({"type": "text", "text": system})
        for api_message in api_messages:
            content = api_message["content"]
            if isinstance(content, list):
                blocks.extend(content)
            else:
                blocks.append({"type": "text", "text": content})
        explicit = [block["cache_control"] for block in blocks if block.get("cache_control")]

        automatic = self._automatic_caching or bool(cfg.cache_control)
        if explicit:
            # The API allows four slots including automatic caching. A one-hour
            # marker cannot follow a five-minute marker, and automatic caching
            # cannot replace the final block's explicit marker with another TTL.
            last_control = None
            for block in reversed(blocks):
                if block.get("type") in {"thinking", "redacted_thinking"}:
                    continue
                if block.get("type") == "text" and not block.get("text"):
                    continue
                last_control = block.get("cache_control")
                break
            automatic = automatic and len(explicit) < 4
            if control.get("ttl", "5m") == "1h" and any(
                marker.get("ttl", "5m") == "5m" for marker in explicit
            ):
                automatic = False
            if last_control and last_control.get("ttl", "5m") != control.get("ttl", "5m"):
                automatic = False
        else:
            messages = list(messages)
            if self._cache_tools and tools:
                tools = [*tools[:-1], replace(tools[-1], cache_control=dict(control))]
            if self._cache_system:
                system_indices = [
                    i for i, message in enumerate(messages) if message.role == MessageRole.SYSTEM
                ]
                system_tokens = sum(self._client.count_messages_tokens([messages[i]]) for i in system_indices)
                if system_indices and system_tokens >= self._cache_threshold_tokens:
                    i = system_indices[-1]
                    if messages[i].content:
                        messages[i] = self._with_breakpoint(messages[i], control)
            if not automatic and self._cache_messages:
                turn_indices = [i for i, message in enumerate(messages) if message.role != MessageRole.SYSTEM]
                if len(turn_indices) >= 2:
                    i = turn_indices[-2]
                    message = messages[i]
                    if (
                        message.content
                        and self._client.count_messages_tokens([message]) >= self._cache_threshold_tokens
                    ):
                        messages[i] = self._with_breakpoint(message, control)

        cfg = cfg.model_copy(update={"cache_control": dict(control) if automatic else None})
        return messages, tools, cfg

    @staticmethod
    def _with_breakpoint(message: Message, control: dict[str, Any]) -> Message:
        return replace(message, metadata={**message.metadata, "cache_control": dict(control)})

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
        """Complete through the inner adapter, then report cache usage."""
        messages, tools, cfg = self._prepare_request(messages, tools, config_override)
        result = await self._client.complete(
            messages=messages,
            tools=tools,
            config_override=cfg,
            fidelity=fidelity,
            token_budget=token_budget,
            correlation_id=correlation_id,
        )
        if result.success:
            self._emit_cache_metrics(result.metadata)
        return result

    def _emit_cache_metrics(self, metadata: dict[str, Any]) -> None:
        if self._metrics is None:
            return
        cache_read = metadata.get("cache_read_input_tokens", 0) or 0
        cache_created = metadata.get("cache_creation_input_tokens", 0) or 0
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
        """Stream through the inner adapter, reporting usage on the final chunk."""
        messages, tools, cfg = self._prepare_request(messages, tools, config_override)
        async for chunk in self._client.stream(messages=messages, tools=tools, config_override=cfg):
            if chunk.is_final:
                self._emit_cache_metrics(chunk.metadata)
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
