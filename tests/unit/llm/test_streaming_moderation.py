"""Tests for streaming-aware moderation in ModeratingLLMClient.stream().

Without chunk-level gates, streaming UIs displayed unsafe content to users
before any moderation check fired. This suite verifies:
- Clean streams pass through
- A single bad sentence truncates the stream with a [BLOCKED] marker
- Earlier clean sentences still emit before the block
- Post-flight=None shortcut just passes through
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from cemaf.core.types import FinishReason
from cemaf.llm.moderating import ModeratingLLMClient
from cemaf.llm.protocols import (
    CompletionResult,
    LLMConfig,
    Message,
    MessageRole,
    StreamChunk,
    ToolDefinition,
)
from cemaf.moderation.pipeline import ModerationPipeline
from cemaf.moderation.protocols import (
    ModerationContent,
    ModerationResult,
    ModerationViolation,
)


class _ScriptedStreamClient:
    """Client that emits a fixed list of StreamChunks."""

    def __init__(self, chunks: list[StreamChunk]) -> None:
        self._config = LLMConfig(model="test")
        self._chunks = chunks

    @property
    def config(self) -> LLMConfig:
        return self._config

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        return CompletionResult.ok(message=Message(role=MessageRole.ASSISTANT, content="ok"))

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        for chunk in self._chunks:
            yield chunk

    def count_tokens(self, text: str) -> int:
        return len(text)


class _BadWordGate:
    """Blocks content containing 'FORBIDDEN'."""

    @property
    def name(self) -> str:
        return "bad_word_gate"

    async def check(
        self,
        content: ModerationContent,
        context: Any | None = None,
    ) -> ModerationResult:
        text = content if isinstance(content, str) else str(content)
        if "FORBIDDEN" in text:
            return ModerationResult.blocked(
                violations=(
                    ModerationViolation(
                        code="keyword.forbidden",
                        message="Found FORBIDDEN",
                        severity="error",
                    ),
                )
            )
        return ModerationResult.success()


@pytest.mark.asyncio
async def test_clean_stream_passes_through() -> None:
    pipeline = ModerationPipeline(post_flight=_BadWordGate())
    client = ModeratingLLMClient(
        inner=_ScriptedStreamClient(
            [
                StreamChunk(content="Hello world. "),
                StreamChunk(content="How are you? "),
                StreamChunk(content="", is_final=True, finish_reason=FinishReason.TERMINAL_STOP),
            ]
        ),
        moderation=pipeline,
    )
    chunks = [c async for c in client.stream(messages=[Message.user(content="hi")])]
    full = "".join(c.content for c in chunks)
    assert "Hello world" in full
    assert "How are you" in full
    assert not any("BLOCKED" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_blocked_sentence_truncates_stream() -> None:
    """Regression: streaming UI must never show disallowed content to the user."""
    pipeline = ModerationPipeline(post_flight=_BadWordGate())
    client = ModeratingLLMClient(
        inner=_ScriptedStreamClient(
            [
                StreamChunk(content="Safe start. "),
                StreamChunk(content="FORBIDDEN word here. "),
                StreamChunk(content="Never emitted. "),
                StreamChunk(content="", is_final=True),
            ]
        ),
        moderation=pipeline,
    )
    chunks = [c async for c in client.stream(messages=[Message.user(content="hi")])]
    # Stream ends at the blocked sentence with BLOCKED marker
    assert chunks[-1].is_final is True
    assert "BLOCKED" in chunks[-1].content
    # The earlier safe sentence did emit
    first_payload = chunks[0].content
    assert "Safe start" in first_payload
    # But the sentence AFTER "FORBIDDEN" never reached the caller
    assert not any("Never emitted" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_no_post_flight_shortcuts_passthrough() -> None:
    """If no post_flight gate, streaming is free (no buffering overhead)."""
    pipeline = ModerationPipeline(post_flight=None)
    client = ModeratingLLMClient(
        inner=_ScriptedStreamClient(
            [
                StreamChunk(content="FORBIDDEN in shortcut. ", is_final=True),
            ]
        ),
        moderation=pipeline,
    )
    chunks = [c async for c in client.stream(messages=[Message.user(content="hi")])]
    # With no gate, even bad content flows through
    assert any("FORBIDDEN" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_trailing_unterminated_sentence_still_moderated() -> None:
    """Final chunk without a sentence terminator still gets moderated."""
    pipeline = ModerationPipeline(post_flight=_BadWordGate())
    client = ModeratingLLMClient(
        inner=_ScriptedStreamClient(
            [
                StreamChunk(content="A safe clause FORBIDDEN tail", is_final=True),
            ]
        ),
        moderation=pipeline,
    )
    chunks = [c async for c in client.stream(messages=[Message.user(content="hi")])]
    assert chunks[-1].is_final is True
    # Tail with FORBIDDEN was caught even without sentence terminator
    assert any("BLOCKED" in c.content for c in chunks)
