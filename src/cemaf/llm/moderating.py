"""ModeratingLLMClient — wraps any LLMClient and sanitizes tool-result messages.

Post-tool-result moderation is the prompt-injection defense boundary: a
retrieved document or MCP tool response containing 'ignore previous
instructions' reaches the model via a MessageRole.TOOL message, and
without this wrapper lands untouched. Pipeline-level check_input /
check_output only see the pipeline's input and output, not the tool
round-trip in between.

This wrapper runs the ModerationPipeline's pre-flight gate on every
MessageRole.TOOL content before forwarding to the underlying client.
Blocked content is replaced with a stub message that carries the
violation codes in metadata; the tool_call_id is preserved so the
model can correlate the turn, but the poisoned payload is gone.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import AsyncIterator
from typing import Any

from cemaf.llm.protocols import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    Message,
    MessageRole,
    StreamChunk,
    ToolDefinition,
)
from cemaf.moderation.pipeline import ModerationPipeline

_BLOCKED_STUB = "[blocked by moderation: tool result contained disallowed content]"

# Invisible / formatting Unicode categories commonly used to smuggle
# instructions past keyword gates: zero-width chars, bidi controls,
# tag characters. We strip them before moderation.
_ZERO_WIDTH_RE = re.compile(
    "["
    "​-‏"  # ZWSP/ZWNJ/ZWJ + LRM/RLM
    "‪-‮"  # LRE/RLE/PDF/LRO/RLO
    "⁦-⁩"  # LRI/RLI/FSI/PDI
    "﻿"  # BOM / ZWNBSP
    "️"  # Variation selector
    "]"
)


def _normalize_text(text: str) -> str:
    """Unicode-normalize + strip invisible chars so moderation sees real content.

    Defense against: homoglyph attacks (Cyrillic а vs Latin a), zero-width
    char smuggling ('ignore​previous​instructions'), bidi tricks.
    """
    normalized = unicodedata.normalize("NFKC", text)
    return _ZERO_WIDTH_RE.sub("", normalized)


def _flatten_content(*, content: Any) -> str:
    """Extract text from a Message.content that may be str or structured."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        parts: list[str] = []
        for value in content.values():
            parts.append(_flatten_content(content=value))
        return "\n".join(parts)
    if isinstance(content, (list, tuple)):
        return "\n".join(_flatten_content(content=item) for item in content)
    return str(content)


class ModeratingLLMClient:
    """LLMClient decorator that sanitizes tool-result messages.

    Only MessageRole.TOOL messages are checked — user and assistant
    messages are the caller's responsibility and already flow through
    the pipeline-level boundaries.
    """

    def __init__(
        self,
        *,
        inner: LLMClient,
        moderation: ModerationPipeline,
    ) -> None:
        self._inner = inner
        self._moderation = moderation

    @property
    def config(self) -> LLMConfig:
        return self._inner.config

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        sanitized = await self._sanitize_messages(messages=messages)
        return await self._inner.complete(
            messages=sanitized,
            tools=tools,
            config_override=config_override,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        sanitized = await self._sanitize_messages(messages=messages)
        # LLMClient protocol types stream() as returning a coroutine that
        # yields an AsyncIterator; real implementations are async generators
        # (directly iterable). Handle both shapes.
        stream_call: Any = self._inner.stream(
            messages=sanitized,
            tools=tools,
            config_override=config_override,
        )
        iterator: AsyncIterator[StreamChunk] = (
            await stream_call if hasattr(stream_call, "__await__") else stream_call
        )
        async for chunk in iterator:
            yield chunk

    def count_tokens(self, text: str) -> int:
        return self._inner.count_tokens(text=text)

    async def _sanitize_messages(self, *, messages: list[Message]) -> list[Message]:
        """Replace any blocked tool-result messages with a stub."""
        out: list[Message] = []
        for msg in messages:
            if msg.role is not MessageRole.TOOL:
                out.append(msg)
                continue
            # Normalize + flatten structured content. Raw `str(dict)` gives
            # Python repr (drowns semantic text in noise). Unicode NFKC
            # normalization collapses homoglyphs and invisible chars that
            # would otherwise bypass keyword/regex moderation gates.
            content_text = _normalize_text(_flatten_content(content=msg.content))
            result = await self._moderation.check_input(content=content_text)
            if result.allowed:
                out.append(msg)
                continue
            violation_codes = [v.code for v in result.violations]
            blocked_metadata = dict(msg.metadata or {})
            blocked_metadata["moderation_blocked"] = True
            blocked_metadata["moderation_violations"] = violation_codes
            out.append(
                Message(
                    role=MessageRole.TOOL,
                    content=_BLOCKED_STUB,
                    name=msg.name,
                    tool_call_id=msg.tool_call_id,
                    tool_calls=msg.tool_calls,
                    metadata=blocked_metadata,
                )
            )
        return out


def wrap_with_moderation(
    *,
    inner: LLMClient,
    moderation: ModerationPipeline | None,
) -> LLMClient:
    """Return inner unchanged if no pipeline, else a ModeratingLLMClient wrapping it."""
    if moderation is None:
        return inner
    return ModeratingLLMClient(inner=inner, moderation=moderation)  # type: ignore[return-value]


__all__ = ["ModeratingLLMClient", "wrap_with_moderation"]
