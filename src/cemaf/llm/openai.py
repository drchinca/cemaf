"""OpenAI GPT adapter for LLMClient protocol."""

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


class OpenAILLMClient:
    """LLMClient implementation using the OpenAI SDK."""

    def __init__(self, *, api_key: str, model: str = "gpt-4o") -> None:
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "openai package required. Install with: pip install openai"
            ) from exc
        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._model = model
        self._config = LLMConfig(model=model)
        self._tiktoken_available = _check_tiktoken()

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
        """Send messages to OpenAI and return completion result."""
        cfg = config_override or self._config
        api_messages = _convert_messages(messages)

        kwargs: dict[str, object] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "messages": api_messages or [{"role": "user", "content": ""}],
        }
        if tools:
            kwargs["tools"] = [t.to_openai_format() for t in tools]

        start = time.monotonic()
        try:
            response = await self._client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
        except Exception as exc:
            return CompletionResult.fail(error=f"OpenAI API error: {exc}")

        latency_ms = (time.monotonic() - start) * 1000

        choice = response.choices[0]
        msg = choice.message

        content_text = msg.content or ""
        tool_calls: list[ToolCall] = []

        if msg.tool_calls:
            for tc in msg.tool_calls:
                raw_args = tc.function.arguments
                try:
                    args: dict[str, object] = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        message = Message.assistant(content_text, tuple(tool_calls))

        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0

        return CompletionResult.ok(
            message=message,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=response.model,
            finish_reason=choice.finish_reason or "stop",
            latency_ms=latency_ms,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream responses from OpenAI."""
        cfg = config_override or self._config
        api_messages = _convert_messages(messages)

        kwargs: dict[str, object] = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "messages": api_messages or [{"role": "user", "content": ""}],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = [t.to_openai_format() for t in tools]

        accumulated_text = ""
        tool_calls_map: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        prompt_tokens = 0
        completion_tokens = 0

        try:
            stream = await self._client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
        except Exception as exc:
            yield StreamChunk(
                content="",
                accumulated_content="",
                is_final=True,
                finish_reason="error",
            )
            return

        async for chunk in stream:  # type: ignore[union-attr]
            if not chunk.choices and chunk.usage:
                # Final usage chunk when stream_options.include_usage=True
                prompt_tokens = chunk.usage.prompt_tokens
                completion_tokens = chunk.usage.completion_tokens
                continue

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            chunk_finish = chunk.choices[0].finish_reason

            if chunk_finish:
                finish_reason = chunk_finish

            # Text delta
            if delta.content:
                accumulated_text += delta.content
                yield StreamChunk(
                    content=delta.content,
                    accumulated_content=accumulated_text,
                )

            # Tool call deltas
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {
                            "id": tc_delta.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    if tc_delta.id:
                        tool_calls_map[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls_map[idx]["name"] += tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls_map[idx]["arguments"] += tc_delta.function.arguments

        # Build final tool calls
        final_tool_calls: list[ToolCall] = []
        for tc_data in tool_calls_map.values():
            raw_args = tc_data["arguments"]
            try:
                parsed_args: dict[str, object] = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                parsed_args = {}
            final_tool_calls.append(
                ToolCall(
                    id=tc_data["id"],
                    name=tc_data["name"],
                    arguments=parsed_args,
                )
            )

        yield StreamChunk(
            content="",
            accumulated_content=accumulated_text,
            tool_calls=tuple(final_tool_calls),
            is_final=True,
            finish_reason=finish_reason or "stop",
            prompt_tokens=TokenCount(prompt_tokens),
            completion_tokens=TokenCount(completion_tokens),
        )

    def count_tokens(self, text: str) -> TokenCount:
        """Estimate tokens in text, using tiktoken when available."""
        if self._tiktoken_available:
            return _count_with_tiktoken(text, self._model)
        return TokenCount(max(1, int(len(text) * 0.25)))

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        """Estimate tokens in a list of messages."""
        total = 0
        for msg in messages:
            total += 4  # per-message overhead (role + framing tokens)
            if isinstance(msg.content, str):
                total += self.count_tokens(msg.content)
            else:
                total += self.count_tokens(json.dumps(msg.content))
        return TokenCount(total)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_tiktoken() -> bool:
    """Return True if tiktoken is importable."""
    try:
        import tiktoken  # noqa: F401
        return True
    except ImportError:
        return False


def _count_with_tiktoken(text: str, model: str) -> TokenCount:
    """Use tiktoken for accurate token counting."""
    import tiktoken

    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        # Fall back to cl100k_base (used by gpt-4, gpt-4o, etc.)
        enc = tiktoken.get_encoding("cl100k_base")
    return TokenCount(max(1, len(enc.encode(text))))


def _convert_messages(messages: list[Message]) -> list[dict[str, object]]:
    """Convert CEMAF messages to OpenAI API format.

    OpenAI accepts system messages directly as role="system" in the messages
    array — no separate system extraction needed (unlike Anthropic).
    """
    api_messages: list[dict[str, object]] = []

    for msg in messages:
        if msg.role == MessageRole.SYSTEM:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            api_messages.append({"role": "system", "content": content})

        elif msg.role == MessageRole.TOOL:
            # OpenAI tool result format
            api_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id or "",
                    "content": (
                        msg.content if isinstance(msg.content, str) else str(msg.content)
                    ),
                }
            )

        elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
            # Assistant message with tool calls
            tool_calls_payload: list[dict[str, object]] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]
            api_msg: dict[str, object] = {
                "role": "assistant",
                "tool_calls": tool_calls_payload,
            }
            if msg.content:
                api_msg["content"] = (
                    msg.content if isinstance(msg.content, str) else str(msg.content)
                )
            api_messages.append(api_msg)

        else:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            api_messages.append({"role": msg.role.value, "content": content})

    return api_messages
