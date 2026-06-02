"""OpenAI-compatible LLM client — works with OpenAI, Ollama, Groq, Hugging Face, and more.

Any provider that speaks the OpenAI chat completions API can use this adapter.

Usage:
    # OpenAI
    client = OpenAICompatClient(api_key="sk-...", model="gpt-4o")

    # Ollama (local Qwen, Gemma, Llama)
    client = OpenAICompatClient(base_url="http://localhost:11434/v1", model="qwen3.5")

    # Groq
    client = OpenAICompatClient(
        base_url="https://api.groq.com/openai/v1",
        api_key="gsk-...", model="llama-3.3-70b",
    )

    # vLLM
    client = OpenAICompatClient(
        base_url="http://localhost:8000/v1", model="Qwen/Qwen3.5-32B",
    )

    # Together AI
    client = OpenAICompatClient(
        base_url="https://api.together.xyz/v1",
        api_key="...", model="meta-llama/Llama-3.3-70B",
    )

    # Hugging Face router
    client = OpenAICompatClient(
        base_url="https://router.huggingface.co/v1",
        api_key="hf_...",
        model="google/gemma-2-2b-it",
        provider=LLMProvider.HUGGINGFACE,
    )

    # LM Studio
    client = OpenAICompatClient(base_url="http://localhost:1234/v1", model="gemma-4-27b")
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any

from cemaf.core.types import LLMProvider, TokenCount

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment,unused-ignore]

from cemaf.llm.protocols import (
    CompletionResult,
    LLMConfig,
    Message,
    MessageRole,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)

logger = logging.getLogger(__name__)


class OpenAICompatClient:
    """LLM client for any OpenAI-compatible API (OpenAI, Ollama, Groq, Together, Hugging Face, LMStudio)."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout_seconds: float = 120.0,
        default_headers: dict[str, str] | None = None,
        provider: LLMProvider | str = LLMProvider.OPENAI,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._provider = provider if isinstance(provider, LLMProvider) else LLMProvider(provider)
        self._config = LLMConfig(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        self._default_headers = default_headers or {}

    @property
    def config(self) -> LLMConfig:
        return self._config

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        """Send chat completion request to OpenAI-compatible API."""
        if httpx is None:
            return CompletionResult.fail(
                error="httpx is required for OpenAICompatClient. Install with: uv add httpx"
            )

        cfg = config_override or self._config
        start = perf_counter()

        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": [_message_to_dict(m) for m in messages],
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        }
        if cfg.stop_sequences:
            payload["stop"] = list(cfg.stop_sequences)
        if tools:
            payload["tools"] = [t.to_openai_format() for t in tools]

        headers = {
            "Content-Type": "application/json",
            **self._default_headers,
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )

            latency_ms = (perf_counter() - start) * 1000

            if response.status_code != 200:
                return CompletionResult.fail(error=f"API error {response.status_code}: {response.text[:500]}")

            data = response.json()
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            usage = data.get("usage", {})

            # Parse tool calls if present
            tool_calls = tuple(
                ToolCall(
                    id=tc.get("id", ""),
                    name=tc.get("function", {}).get("name", ""),
                    arguments=_parse_arguments(tc.get("function", {}).get("arguments", "{}")),
                )
                for tc in msg.get("tool_calls", [])
            )

            return CompletionResult.ok(
                message=Message(
                    role=MessageRole.ASSISTANT,
                    content=msg.get("content") or "",
                    tool_calls=tool_calls,
                ),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                model=data.get("model", cfg.model),
                finish_reason=choice.get("finish_reason", "") or "stop",
                finish_reason_native=choice.get("finish_reason", "") or "",
                provider=self._provider,
                latency_ms=latency_ms,
            )

        except Exception as e:
            return CompletionResult.fail(error=f"Request failed: {e}")

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream chat completion from OpenAI-compatible API."""
        if httpx is None:
            yield StreamChunk(content="Error: httpx required", is_final=True)
            return

        cfg = config_override or self._config

        payload: dict[str, Any] = {
            "model": cfg.model,
            "messages": [_message_to_dict(m) for m in messages],
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "stream": True,
        }

        headers = {"Content-Type": "application/json", **self._default_headers}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        accumulated = ""
        async with (
            httpx.AsyncClient(timeout=cfg.timeout_seconds) as client,
            client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
            ) as response,
        ):
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    yield StreamChunk(content="", is_final=True, accumulated_content=accumulated)
                    return

                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        accumulated += content
                        yield StreamChunk(content=content, accumulated_content=accumulated)
                except json.JSONDecodeError:
                    continue

    def count_tokens(self, text: str) -> TokenCount:
        """Heuristic token count (3.5 chars/token, calibrated for OpenAI tokenizers)."""
        if not text:
            return TokenCount(0)
        return TokenCount(max(1, round(len(text) / 3.5)))

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        """Heuristic total for a message list (adds 4 tokens per message for role overhead)."""
        total = sum(self.count_tokens(text=str(m.content)) + 4 for m in messages)
        return TokenCount(max(1, total))

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        """Exact token count via tiktoken.

        OpenAI-compatible providers (OpenAI, Groq, Together, Fireworks, many
        open-model gateways following the OpenAI schema: Qwen, DeepSeek,
        Llama-family) all use a tiktoken-compatible BPE. When tiktoken is
        installed we compute exact counts; otherwise we fall back to the
        heuristic with a log warning so the caller knows the number is
        approximate.
        """
        try:
            import tiktoken
        except ImportError:
            # No tiktoken → heuristic fallback. Caller sees a real number,
            # not a crash — and accepts the ~5% under-count as the cost of
            # not installing an extra.
            total = 0
            for msg in messages:
                total += self.count_tokens(text=str(msg.content)) + 4
            if tools:
                total += sum(self.count_tokens(text=str(t.parameters)) + len(t.name) for t in tools)
            return TokenCount(max(1, total))

        # Pick the right encoder for the model; fall back to cl100k_base.
        try:
            encoder = tiktoken.encoding_for_model(self._config.model)
        except (KeyError, Exception):
            encoder = tiktoken.get_encoding("cl100k_base")

        total = 0
        for msg in messages:
            total += 4  # OpenAI's per-message overhead
            content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
            total += len(encoder.encode(content_str))
            if msg.name:
                total += len(encoder.encode(msg.name))
        total += 2  # Priming tokens
        if tools:
            for tool in tools:
                tool_text = f"{tool.name}\n{tool.description}\n{tool.parameters}"
                total += len(encoder.encode(tool_text))
        return TokenCount(total)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _message_to_dict(msg: Message) -> dict[str, Any]:
    """Convert CEMAF Message to OpenAI-compatible dict."""
    d: dict[str, Any] = {"role": msg.role.value, "content": msg.content}
    if msg.name:
        d["name"] = msg.name
    if msg.tool_call_id:
        d["tool_call_id"] = msg.tool_call_id
    if msg.tool_calls:
        d["tool_calls"] = [tc.to_dict() for tc in msg.tool_calls]
    return d


def _parse_arguments(args: str | dict[str, Any]) -> dict[str, Any]:
    """Parse tool call arguments (may be string or dict)."""
    if isinstance(args, dict):
        return args
    try:
        parsed: dict[str, Any] = json.loads(args)
        return parsed
    except (json.JSONDecodeError, TypeError):
        return {"raw": args}
