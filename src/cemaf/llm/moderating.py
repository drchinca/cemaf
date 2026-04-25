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
_BLOCKED_OUTPUT_STUB = "\n[BLOCKED by moderation — output truncated]"

# Sentence terminators that trigger a boundary-flush. We only moderate
# completed sentences so the gate sees coherent units, not token fragments.
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?][\"')\]]?\s+|\n\n")


def _find_sentence_boundary(*, text: str) -> int | None:
    """Return the index one-past the first sentence terminator, or None."""
    match = _SENTENCE_BOUNDARY_RE.search(text)
    if match is None:
        return None
    return match.end()


# Invisible / formatting Unicode categories commonly used to smuggle
# instructions past keyword gates: zero-width chars, bidi controls,
# tag characters. We strip them before moderation.
#
# This regex deliberately CONTAINS bidi controls (LRM/RLM, LRE/RLE/PDF,
# LRI/RLI/FSI/PDI) in a character class so we can match-and-remove them.
# Bandit's B613 trojan-source check fires here because the source file
# contains these bytes — but their inclusion is the security feature,
# not a vulnerability. Without them, the regex couldn't strip them.
_ZERO_WIDTH_RE = re.compile(
    "["
    "​-‏"  # ZWSP/ZWNJ/ZWJ + LRM/RLM  # nosec B613 - intentional, see module-level note above
    "‪-‮"  # LRE/RLE/PDF/LRO/RLO  # nosec B613
    "⁦-⁩"  # LRI/RLI/FSI/PDI  # nosec B613
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
        """Stream completion with chunk-level output moderation.

        Sanitizes inbound tool-result messages (same as complete()), THEN
        buffers outbound chunks by sentence boundary and runs the pipeline's
        post-flight gate on each boundary. On violation, the stream is
        truncated with a [BLOCKED] marker and `is_final=True` — the caller
        can never have received more than one sentence of disallowed content.

        Without this, a streaming client showed users partial unsafe output
        before the (non-existent) end-of-stream moderation check. Now every
        emitted chunk has been cleared by moderation.
        """
        sanitized = await self._sanitize_messages(messages=messages)
        stream_call: Any = self._inner.stream(
            messages=sanitized,
            tools=tools,
            config_override=config_override,
        )
        iterator: AsyncIterator[StreamChunk] = (
            await stream_call if hasattr(stream_call, "__await__") else stream_call
        )

        # If no post-flight gate, pass through unchanged (cheap path).
        if self._moderation.post_flight is None:
            async for chunk in iterator:
                yield chunk
            return

        # Buffered path: accumulate by sentence boundary, moderate each
        # finalized sentence before emission.
        pending = ""
        emitted_total = ""
        async for chunk in iterator:
            pending += chunk.content
            emitted_chunks: list[str] = []
            while True:
                boundary = _find_sentence_boundary(text=pending)
                if boundary is None:
                    break
                sentence, pending = pending[:boundary], pending[boundary:]
                moderation_result = await self._moderation.check_output(content=sentence)
                if not moderation_result.allowed:
                    # Emit blocked marker and stop the stream.
                    emitted_total += _BLOCKED_OUTPUT_STUB
                    yield StreamChunk(
                        content=_BLOCKED_OUTPUT_STUB,
                        is_final=True,
                        accumulated_content=emitted_total,
                    )
                    return
                emitted_chunks.append(sentence)
                emitted_total += sentence
            if emitted_chunks:
                yield StreamChunk(
                    content="".join(emitted_chunks),
                    accumulated_content=emitted_total,
                    is_final=False,
                )
            if chunk.is_final:
                # Flush any trailing unterminated sentence through moderation too.
                if pending:
                    moderation_result = await self._moderation.check_output(content=pending)
                    if not moderation_result.allowed:
                        emitted_total += _BLOCKED_OUTPUT_STUB
                        yield StreamChunk(
                            content=_BLOCKED_OUTPUT_STUB,
                            is_final=True,
                            accumulated_content=emitted_total,
                        )
                        return
                    emitted_total += pending
                    yield StreamChunk(
                        content=pending,
                        is_final=True,
                        accumulated_content=emitted_total,
                        finish_reason=chunk.finish_reason,
                    )
                    return
                yield StreamChunk(
                    content="",
                    is_final=True,
                    accumulated_content=emitted_total,
                    finish_reason=chunk.finish_reason,
                )
                return

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
