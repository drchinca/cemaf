"""Google Gemini LLM client adapter.

Usage:
    client = GeminiClient(api_key="AIza...", model="gemini-2.5-flash")
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment,unused-ignore]

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

logger = logging.getLogger(__name__)

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiClient:
    """LLM client for Google Gemini API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._config = LLMConfig(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )

    @property
    def config(self) -> LLMConfig:
        return self._config

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        """Send request to Gemini generateContent API."""
        if httpx is None:
            return CompletionResult.fail(error="httpx required for GeminiClient")

        cfg = config_override or self._config
        start = perf_counter()

        # Convert messages to Gemini format
        contents = _messages_to_gemini(messages=messages)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": cfg.temperature,
                "maxOutputTokens": cfg.max_tokens,
            },
        }

        if tools:
            payload["tools"] = [{"functionDeclarations": [_tool_to_gemini(t) for t in tools]}]

        url = f"{_GEMINI_API_BASE}/models/{cfg.model}:generateContent?key={self._api_key}"

        try:
            async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
                response = await client.post(url, json=payload)

            latency_ms = (perf_counter() - start) * 1000

            if response.status_code != 200:
                return CompletionResult.fail(
                    error=f"Gemini API error {response.status_code}: {response.text[:500]}"
                )

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return CompletionResult.fail(error="No candidates in Gemini response")

            parts = candidates[0].get("content", {}).get("parts", [])
            text_parts = [p.get("text", "") for p in parts if "text" in p]
            content = "".join(text_parts)

            # Parse function calls
            tool_calls = tuple(
                ToolCall(
                    id=f"call_{i}",
                    name=p["functionCall"]["name"],
                    arguments=p["functionCall"].get("args", {}),
                )
                for i, p in enumerate(parts)
                if "functionCall" in p
            )

            usage = data.get("usageMetadata", {})

            return CompletionResult.ok(
                message=Message(
                    role=MessageRole.ASSISTANT,
                    content=content,
                    tool_calls=tool_calls,
                ),
                prompt_tokens=usage.get("promptTokenCount", 0),
                completion_tokens=usage.get("candidatesTokenCount", 0),
                model=cfg.model,
                finish_reason=candidates[0].get("finishReason", "") or "stop",
                finish_reason_native=candidates[0].get("finishReason", "") or "",
                latency_ms=latency_ms,
            )

        except Exception as e:
            return CompletionResult.fail(error=f"Gemini request failed: {e}")

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream from Gemini streamGenerateContent API."""
        if httpx is None:
            yield StreamChunk(content="Error: httpx required", is_final=True)
            return

        cfg = config_override or self._config
        contents = _messages_to_gemini(messages=messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": cfg.temperature,
                "maxOutputTokens": cfg.max_tokens,
            },
        }

        url = f"{_GEMINI_API_BASE}/models/{cfg.model}:streamGenerateContent?key={self._api_key}&alt=sse"
        accumulated = ""

        async with (
            httpx.AsyncClient(timeout=cfg.timeout_seconds) as client,
            client.stream("POST", url, json=payload) as response,
        ):
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    data = json.loads(line[6:])
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            accumulated += text
                            yield StreamChunk(content=text, accumulated_content=accumulated)
                except json.JSONDecodeError:
                    continue

        yield StreamChunk(content="", is_final=True, accumulated_content=accumulated)

    def count_tokens(self, text: str) -> TokenCount:
        """Heuristic count (~3.5 chars/token) calibrated for Gemini/Gamma tokenizers."""
        if not text:
            return TokenCount(0)
        return TokenCount(max(1, round(len(text) / 3.5)))

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        total = sum(self.count_tokens(text=str(m.content)) + 4 for m in messages)
        return TokenCount(max(1, total))

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        """Exact token count via Gemini's countTokens API.

        POSTs to `https://generativelanguage.googleapis.com/v1beta/models/<model>:countTokens`
        Free to call. Returns the totalTokens field.
        """
        if httpx is None:
            raise RuntimeError("httpx required for GeminiClient.count_tokens_exact")
        contents = _messages_to_gemini(messages=messages)
        url = f"{_GEMINI_API_BASE}/models/{self._config.model}:countTokens"
        payload: dict[str, Any] = {"contents": contents}
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            response = await http_client.post(
                url,
                params={"key": self._api_key},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return TokenCount(int(data.get("totalTokens", 0)))


# ---------------------------------------------------------------------------
# Gemini format converters
# ---------------------------------------------------------------------------


def _messages_to_gemini(*, messages: list[Message]) -> list[dict[str, Any]]:
    """Convert CEMAF messages to Gemini contents format."""
    contents: list[dict[str, Any]] = []
    system_parts: list[str] = []

    for msg in messages:
        if msg.role == MessageRole.SYSTEM:
            system_parts.append(str(msg.content))
            continue

        role = "user" if msg.role == MessageRole.USER else "model"
        parts: list[dict[str, str]] = [{"text": str(msg.content)}]

        # Prepend system instructions to first user message
        if role == "user" and system_parts:
            system_text = "\n".join(system_parts)
            parts = [{"text": f"{system_text}\n\n{msg.content}"}]
            system_parts.clear()

        contents.append({"role": role, "parts": parts})

    return contents


def _tool_to_gemini(tool: ToolDefinition) -> dict[str, Any]:
    """Convert CEMAF ToolDefinition to Gemini function declaration."""
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }
