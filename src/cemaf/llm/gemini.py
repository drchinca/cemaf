"""Google Gemini and Vertex AI LLM client adapter.

Usage:
    client = GeminiClient(api_key="AIza...", model="gemini-2.5-flash")
    client = GeminiClient(use_vertex=True, gcp_project="my-project", model="gemini-2.5-flash")
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from importlib import import_module
from time import perf_counter
from typing import Any, cast

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment,unused-ignore]

from cemaf.core.types import FinishReason, LLMProvider, TokenCount
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

_GEMINI_FILTER_FINISH_REASONS = {
    "SAFETY",
    "RECITATION",
    "LANGUAGE",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPII",
    "IMAGE_SAFETY",
    "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_RECITATION",
}

_GEMINI_ERROR_FINISH_REASONS = {
    "OTHER",
    "MALFORMED_FUNCTION_CALL",
    "UNEXPECTED_TOOL_CALL",
    "TOO_MANY_TOOL_CALLS",
    "MISSING_THOUGHT_SIGNATURE",
    "MALFORMED_RESPONSE",
    "IMAGE_OTHER",
    "NO_IMAGE",
}


class GeminiClient:
    """LLM client for Google Gemini (AI Studio & Vertex AI) APIs."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float = 1.0,
        timeout_seconds: float = 120.0,
        use_vertex: bool | None = None,
        gcp_project: str | None = None,
        location: str | None = None,
        access_token: str | None = None,
        provider: LLMProvider | str | None = None,
    ) -> None:
        self._api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self._config = LLMConfig(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            timeout_seconds=timeout_seconds,
        )
        self._use_vertex = use_vertex
        self._gcp_project = gcp_project
        self._location = location
        self._access_token = access_token
        self._provider = LLMProvider(provider) if provider is not None else None

    @property
    def config(self) -> LLMConfig:
        return self._config

    def _get_request_details(self, action: str, cfg: LLMConfig) -> tuple[str, dict[str, str]]:
        """Resolve the target request URL and headers based on the environment and config."""
        use_vertex = self._use_vertex
        if use_vertex is None:
            # Auto-detect Vertex vs. Studio
            has_gcp_env = any(os.getenv(v) for v in ["VERTEX_PROJECT", "GCP_PROJECT", "GOOGLE_CLOUD_PROJECT"])
            has_gemini_key = bool(self._api_key)
            use_vertex = has_gcp_env and not has_gemini_key

        if use_vertex:
            project = self._gcp_project
            if not project:
                for env_var in ["VERTEX_PROJECT", "GCP_PROJECT", "GOOGLE_CLOUD_PROJECT"]:
                    project = os.getenv(env_var)
                    if project:
                        break
                if not project:
                    try:
                        google_auth = cast(Any, import_module("google.auth"))

                        _, gcp_proj = google_auth.default()
                        if gcp_proj:
                            project = gcp_proj
                    except Exception as exc:
                        logger.debug("Could not discover GCP project via google-auth: %s", exc)

            if not project:
                raise ValueError(
                    "GCP project ID is required for Vertex AI Gemini. "
                    "Set gcp_project parameter or "
                    "VERTEX_PROJECT / GCP_PROJECT / GOOGLE_CLOUD_PROJECT environment variable."
                )

            location = self._location
            if not location:
                for env_var in ["VERTEX_LOCATION", "GCP_LOCATION", "GOOGLE_CLOUD_REGION"]:
                    location = os.getenv(env_var)
                    if location:
                        break
                if not location:
                    location = "us-central1"

            # Resolve access token
            token = self._access_token
            if not token:
                for env_var in ["VERTEX_ACCESS_TOKEN", "GCP_ACCESS_TOKEN", "GCLOUD_ACCESS_TOKEN"]:
                    token = os.getenv(env_var)
                    if token:
                        break

            # Try google-auth library
            if not token:
                try:
                    google_auth = cast(Any, import_module("google.auth"))
                    google_requests = cast(Any, import_module("google.auth.transport.requests"))

                    credentials, _ = google_auth.default(
                        scopes=["https://www.googleapis.com/auth/cloud-platform"]
                    )
                    auth_request = google_requests.Request()
                    credentials.refresh(auth_request)
                    token = credentials.token
                except Exception as e:
                    logger.debug(f"Could not load GCP credentials via google-auth: {e}")

            # Try gcloud CLI
            if not token:
                try:
                    import shutil
                    import subprocess

                    if shutil.which("gcloud"):
                        result = subprocess.run(
                            ["gcloud", "auth", "print-access-token"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )
                        if result.returncode == 0:
                            token = result.stdout.strip()
                except Exception as e:
                    logger.debug(f"Could not retrieve GCP token via gcloud CLI: {e}")

            if not token and self._api_key:
                # Fallback to API Key header if available
                headers = {
                    "Content-Type": "application/json",
                    "x-goog-api-key": self._api_key,
                }
                url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models/{cfg.model}:{action}"
                if action == "streamGenerateContent":
                    url += "?alt=sse"
                return url, headers

            if not token:
                raise ValueError(
                    "Authentication token or credentials are required for Vertex AI. "
                    "Set access_token, VERTEX_ACCESS_TOKEN, or set up "
                    "Application Default Credentials / gcloud login."
                )

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            }
            url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models/{cfg.model}:{action}"
            if action == "streamGenerateContent":
                url += "?alt=sse"
            return url, headers

        else:
            api_key = self._api_key
            if not api_key:
                raise ValueError(
                    "api_key required for Google AI Studio Gemini (or set GEMINI_API_KEY or GOOGLE_API_KEY)"
                )
            headers = {"Content-Type": "application/json"}
            url = f"{_GEMINI_API_BASE}/models/{cfg.model}:{action}?key={api_key}"
            if action == "streamGenerateContent":
                url += "&alt=sse"
            return url, headers

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
        """Send request to Gemini generateContent API."""
        del fidelity, token_budget, correlation_id

        if httpx is None:
            return CompletionResult.fail(error="httpx required for GeminiClient")

        cfg = config_override or self._config
        start = perf_counter()
        payload = _generate_content_payload(messages=messages, tools=tools, config=cfg)

        try:
            url, headers = self._get_request_details(action="generateContent", cfg=cfg)
        except ValueError as e:
            return CompletionResult.fail(error=str(e))

        try:
            async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)

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

            tool_calls = tuple(
                _tool_call_from_gemini_function_call(p["functionCall"], call_id=f"call_{i}")
                for i, p in enumerate(parts)
                if "functionCall" in p
            )

            usage = data.get("usageMetadata", {})

            native_finish_reason = str(candidates[0].get("finishReason", "") or "")

            return CompletionResult.ok(
                message=Message(
                    role=MessageRole.ASSISTANT,
                    content=content,
                    tool_calls=tool_calls,
                ),
                prompt_tokens=usage.get("promptTokenCount", 0),
                completion_tokens=usage.get("candidatesTokenCount", 0),
                model=cfg.model,
                finish_reason=_gemini_finish_reason(
                    native_finish_reason,
                    has_tool_calls=bool(tool_calls),
                ),
                finish_reason_native=native_finish_reason,
                provider=self._provider_family(),
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
            yield StreamChunk(
                content="Error: httpx required",
                finish_reason=FinishReason.PARTIAL_ERROR,
                is_final=True,
            )
            return

        cfg = config_override or self._config
        payload = _generate_content_payload(messages=messages, tools=tools, config=cfg)

        try:
            url, headers = self._get_request_details(action="streamGenerateContent", cfg=cfg)
        except ValueError as e:
            yield StreamChunk(
                content=f"Error: {e}",
                finish_reason=FinishReason.PARTIAL_ERROR,
                is_final=True,
            )
            return

        accumulated = ""
        tool_calls: list[ToolCall] = []
        native_finish_reason = ""
        prompt_tokens = 0
        completion_tokens = 0

        try:
            async with (
                httpx.AsyncClient(timeout=cfg.timeout_seconds) as client,
                client.stream("POST", url, headers=headers, json=payload) as response,
            ):
                if response.status_code != 200:
                    yield StreamChunk(
                        content=f"Error: Gemini streaming API error {response.status_code}",
                        finish_reason=FinishReason.PARTIAL_ERROR,
                        is_final=True,
                    )
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        payload_line = line[6:].strip()
                        if not payload_line or payload_line == "[DONE]":
                            continue
                        data = json.loads(payload_line)
                        usage = data.get("usageMetadata", {})
                        prompt_tokens = _usage_int(usage, "promptTokenCount", prompt_tokens)
                        completion_tokens = _usage_int(
                            usage,
                            "candidatesTokenCount",
                            completion_tokens,
                        )
                        candidate = data.get("candidates", [{}])[0]
                        native_finish_reason = str(candidate.get("finishReason") or native_finish_reason)
                        parts = candidate.get("content", {}).get("parts", [])
                        for part in parts:
                            text = part.get("text", "")
                            if text:
                                accumulated += text
                                yield StreamChunk(content=text, accumulated_content=accumulated)
                            if "functionCall" in part:
                                tool_calls.append(
                                    _tool_call_from_gemini_function_call(
                                        part["functionCall"],
                                        call_id=f"call_{len(tool_calls)}",
                                    )
                                )
                    except json.JSONDecodeError as exc:
                        yield StreamChunk(
                            content=f"Error: Gemini stream returned malformed JSON: {exc.msg}",
                            finish_reason=FinishReason.PARTIAL_ERROR,
                            is_final=True,
                            accumulated_content=accumulated,
                        )
                        return
        except Exception as e:
            yield StreamChunk(
                content=f"Error: {e}",
                finish_reason=FinishReason.PARTIAL_ERROR,
                is_final=True,
                accumulated_content=accumulated,
            )
            return

        yield StreamChunk(
            content="",
            tool_calls=tuple(tool_calls),
            finish_reason=_gemini_finish_reason(
                native_finish_reason,
                has_tool_calls=bool(tool_calls),
            ),
            is_final=True,
            accumulated_content=accumulated,
            prompt_tokens=TokenCount(prompt_tokens),
            completion_tokens=TokenCount(completion_tokens),
        )

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
        """Exact token count via Gemini's countTokens API."""
        if httpx is None:
            raise RuntimeError("httpx required for GeminiClient.count_tokens_exact")
        try:
            url, headers = self._get_request_details(action="countTokens", cfg=self._config)
        except ValueError as e:
            raise RuntimeError(f"Failed to resolve request details: {e}") from e

        payload = _count_tokens_payload(messages=messages, tools=tools, config=self._config)
        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as http_client:
            response = await http_client.post(
                url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return TokenCount(int(data.get("totalTokens", 0)))

    def _provider_family(self) -> LLMProvider:
        """Report the provider family independently from the shared wire format."""
        if self._provider is not None:
            return self._provider
        if self._use_vertex is True:
            return LLMProvider.VERTEX
        if self._use_vertex is False:
            return LLMProvider.GEMINI

        has_gcp_env = any(os.getenv(v) for v in ["VERTEX_PROJECT", "GCP_PROJECT", "GOOGLE_CLOUD_PROJECT"])
        has_gemini_key = bool(self._api_key)
        return LLMProvider.VERTEX if has_gcp_env and not has_gemini_key else LLMProvider.GEMINI


# ---------------------------------------------------------------------------
# Gemini format converters
# ---------------------------------------------------------------------------


def _messages_to_gemini(*, messages: list[Message]) -> list[dict[str, Any]]:
    """Convert CEMAF messages to Gemini contents format."""
    contents: list[dict[str, Any]] = []
    system_parts: list[str] = []

    for msg in messages:
        if msg.role == MessageRole.SYSTEM:
            system_parts.append(_content_to_text(msg.content))
            continue

        if msg.role == MessageRole.TOOL:
            # Tool responses in Gemini belong to the 'user' role with a 'functionResponse' part
            if not msg.name:
                raise ValueError("Gemini tool result messages require a tool name")
            resp_data: Any = msg.content
            if isinstance(resp_data, str):
                try:
                    resp_data = json.loads(resp_data)
                except Exception:
                    resp_data = {"result": resp_data}
            if not isinstance(resp_data, dict):
                resp_data = {"result": resp_data}

            parts: list[dict[str, Any]] = [
                {
                    "functionResponse": {
                        "name": msg.name,
                        "response": resp_data,
                    }
                }
            ]
            contents.append({"role": "user", "parts": parts})
            continue

        if msg.role == MessageRole.ASSISTANT and msg.tool_calls:
            # Model assistant turn containing one or more functionCalls
            parts = []
            if msg.content:
                parts.extend(_content_to_parts(msg.content))
            for tc in msg.tool_calls:
                parts.append(
                    {
                        "functionCall": {
                            "name": tc.name,
                            "args": tc.arguments,
                        }
                    }
                )
            contents.append({"role": "model", "parts": parts})
            continue

        # Standard user or model content
        role = "user" if msg.role == MessageRole.USER else "model"
        parts = _content_to_parts(msg.content)

        # Prepend system instructions to first user message
        if role == "user" and system_parts:
            system_text = "\n".join(system_parts)
            parts = _prepend_system_text(parts=parts, system_text=system_text)
            system_parts.clear()

        contents.append({"role": role, "parts": parts})

    if system_parts:
        contents.append({"role": "user", "parts": [{"text": "\n".join(system_parts)}]})

    return contents


def _tool_to_gemini(tool: ToolDefinition) -> dict[str, Any]:
    """Convert CEMAF ToolDefinition to Gemini function declaration."""
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }


def _tool_call_from_gemini_function_call(function_call: object, *, call_id: str) -> ToolCall:
    """Convert Gemini functionCall payloads without dropping non-dict arguments."""
    if not isinstance(function_call, dict):
        raise ValueError("Gemini functionCall payload must be an object")

    name = str(function_call.get("name") or "")
    if not name:
        raise ValueError("Gemini functionCall payload is missing name")

    return ToolCall(
        id=call_id,
        name=name,
        arguments=function_call.get("args", {}),
    )


def _generate_content_payload(
    *,
    messages: list[Message],
    tools: list[ToolDefinition] | None,
    config: LLMConfig,
) -> dict[str, Any]:
    """Build a Gemini generateContent-compatible request body."""
    payload: dict[str, Any] = {
        "contents": _messages_to_gemini(messages=messages),
        "generationConfig": _generation_config(config),
    }
    if tools:
        payload["tools"] = [{"functionDeclarations": [_tool_to_gemini(t) for t in tools]}]
    return payload


def _count_tokens_payload(
    *,
    messages: list[Message],
    tools: list[ToolDefinition] | None,
    config: LLMConfig,
) -> dict[str, Any]:
    """Build a countTokens request body, preserving tool schemas when present."""
    if not tools:
        return {"contents": _messages_to_gemini(messages=messages)}
    return {
        "generateContentRequest": _generate_content_payload(
            messages=messages,
            tools=tools,
            config=config,
        )
    }


def _generation_config(config: LLMConfig) -> dict[str, Any]:
    generation_config: dict[str, Any] = {
        "temperature": config.temperature,
        "maxOutputTokens": config.max_tokens,
        "topP": config.top_p,
    }
    if config.stop_sequences:
        generation_config["stopSequences"] = list(config.stop_sequences)
    return generation_config


def _gemini_finish_reason(raw: str | None, *, has_tool_calls: bool = False) -> FinishReason:
    """Normalize Gemini/Vertex finish reasons into CEMAF's closed enum."""
    if has_tool_calls:
        return FinishReason.TERMINAL_TOOL

    native = (raw or "STOP").removeprefix("FINISH_REASON_").upper()
    if native == "STOP":
        return FinishReason.TERMINAL_STOP
    if native == "MAX_TOKENS":
        return FinishReason.PARTIAL_LENGTH
    if native in _GEMINI_FILTER_FINISH_REASONS:
        return FinishReason.PARTIAL_FILTER
    if native in _GEMINI_ERROR_FINISH_REASONS:
        return FinishReason.PARTIAL_ERROR
    return FinishReason.PARTIAL_ERROR


def _content_to_parts(content: object) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content}]
    if not isinstance(content, list):
        return [{"text": _content_to_text(content)}]

    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            parts.append({"text": _content_to_text(item)})
            continue
        if "type" in item and item.get("type") == "text" and "text" in item:
            parts.append({"text": str(item["text"])})
            continue
        if any(
            key in item
            for key in (
                "text",
                "inline_data",
                "inlineData",
                "file_data",
                "fileData",
                "functionCall",
                "functionResponse",
            )
        ):
            parts.append(dict(item))
            continue
        parts.append({"text": _content_to_text(item)})
    return parts or [{"text": ""}]


def _prepend_system_text(*, parts: list[dict[str, Any]], system_text: str) -> list[dict[str, Any]]:
    """Attach system text without flattening multimodal user content."""
    if not parts:
        return [{"text": system_text}]

    first = parts[0]
    if set(first) == {"text"}:
        return [{"text": f"{system_text}\n\n{first['text']}"}, *parts[1:]]

    return [{"text": system_text}, *parts]


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _usage_int(usage: dict[str, Any], key: str, default: int) -> int:
    value = usage.get(key, default)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
