"""OpenAI Responses API adapter for the LLMClient protocol."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any

from cemaf.core.types import LLMProvider, TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMConfig,
    Message,
    MessageRole,
    StreamChunk,
    ToolCall,
    ToolDefinition,
    coerce_finish_reason,
)

DEFAULT_OPENAI_RESPONSES_MODEL = "gpt-5.5"
OPENAI_BASE_URL = "https://api.openai.com/v1"


class OpenAIResponsesLLMClient:
    """LLM client backed by OpenAI's Responses API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_OPENAI_RESPONSES_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float = 1.0,
        timeout_seconds: float = 120.0,
        base_url: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._config = LLMConfig(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            timeout_seconds=timeout_seconds,
        )
        self._base_url = (base_url or OPENAI_BASE_URL).rstrip("/")
        self._client = client or _create_openai_client(
            api_key=api_key,
            base_url=base_url,
            organization=organization,
            project=project,
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
        *,
        fidelity: object | None = None,
        token_budget: object | None = None,
        correlation_id: str | None = None,
    ) -> CompletionResult:
        """Send a request through OpenAI Responses and return a CEMAF result."""
        del fidelity, token_budget  # forward-compat; opaque to this adapter
        cfg = config_override or self._config
        request = _build_responses_request(
            messages=messages,
            tools=tools,
            config=cfg,
            correlation_id=correlation_id,
        )

        start = perf_counter()
        try:
            response = await self._client.responses.create(**request)
        except Exception as exc:
            return CompletionResult.fail(error=f"OpenAI Responses API error: {exc}")
        latency_ms = (perf_counter() - start) * 1000

        failure_error = _response_failure_error(response)
        if failure_error:
            return CompletionResult.fail(error=f"OpenAI Responses API {failure_error}")

        content = _response_text(response)
        tool_calls = tuple(_response_tool_calls(response))
        native_finish_reason = _response_finish_reason(response, tool_calls=tool_calls)
        prompt_tokens, completion_tokens = _response_usage(response)

        return CompletionResult(
            success=True,
            message=Message(
                role=MessageRole.ASSISTANT,
                content=content,
                tool_calls=tool_calls,
            ),
            prompt_tokens=TokenCount(prompt_tokens),
            completion_tokens=TokenCount(completion_tokens),
            total_tokens=TokenCount(prompt_tokens + completion_tokens),
            model=str(_get(response, "model", cfg.model) or cfg.model),
            finish_reason=coerce_finish_reason(native_finish_reason),
            finish_reason_native=native_finish_reason,
            provider=LLMProvider.OPENAI,
            latency_ms=latency_ms,
            metadata={
                "response_id": _get(response, "id", ""),
                "status": _get(response, "status", ""),
            },
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream text deltas from OpenAI Responses."""
        cfg = config_override or self._config
        request = _build_responses_request(
            messages=messages,
            tools=tools,
            config=cfg,
            correlation_id=None,
        )
        stream_method = getattr(self._client.responses, "stream", None)
        if stream_method is None:
            async for chunk in self._stream_via_complete(
                messages=messages,
                tools=tools,
                config_override=config_override,
            ):
                yield chunk
            return

        accumulated = ""
        final_response: Any | None = None
        collected_tool_calls: tuple[ToolCall, ...] = ()

        try:
            async with stream_method(**request) as stream:
                async for event in stream:
                    event_type = str(_get(event, "type", "") or "")
                    if event_type == "response.output_text.delta":
                        delta = str(_get(event, "delta", "") or "")
                        if delta:
                            accumulated += delta
                            yield StreamChunk(
                                content=delta,
                                accumulated_content=accumulated,
                            )
                        continue

                    if event_type == "response.output_item.done":
                        item = _get(event, "item", None)
                        tool_call = _tool_call_from_response_item(item)
                        if tool_call is not None:
                            collected_tool_calls = (*collected_tool_calls, tool_call)
                        continue

                    if event_type in {"response.completed", "response.incomplete", "response.failed"}:
                        final_response = _get(event, "response", None)

                if final_response is None:
                    final_response = await _get_final_stream_response(stream)
        except Exception:
            yield StreamChunk(
                content="",
                accumulated_content=accumulated,
                is_final=True,
                finish_reason=coerce_finish_reason("error"),
            )
            return

        response_text = _response_text(final_response) if final_response is not None else ""
        if response_text and not accumulated:
            accumulated = response_text
            yield StreamChunk(content=response_text, accumulated_content=accumulated)

        response_tool_calls = (
            tuple(_response_tool_calls(final_response)) if final_response is not None else ()
        )
        tool_calls = response_tool_calls or collected_tool_calls
        prompt_tokens, completion_tokens = _response_usage(final_response)
        if final_response is not None:
            finish_reason_native = _response_finish_reason(final_response, tool_calls=tool_calls)
        else:
            finish_reason_native = "stop"
        failure_error = _response_failure_error(final_response)

        yield StreamChunk(
            content=f"Error: OpenAI Responses stream {failure_error}" if failure_error else "",
            accumulated_content=accumulated,
            tool_calls=tool_calls,
            is_final=True,
            finish_reason=coerce_finish_reason(finish_reason_native),
            prompt_tokens=TokenCount(prompt_tokens),
            completion_tokens=TokenCount(completion_tokens),
        )

    def count_tokens(self, text: str) -> TokenCount:
        if not text:
            return TokenCount(0)
        try:
            import tiktoken
        except ImportError:
            return TokenCount(max(1, round(len(text) / 3.5)))

        try:
            encoder = tiktoken.encoding_for_model(self._config.model)
        except (KeyError, Exception):
            encoder = tiktoken.get_encoding("cl100k_base")
        return TokenCount(max(1, len(encoder.encode(text))))

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        total = 0
        for msg in messages:
            total += 4
            total += self.count_tokens(_content_to_text(msg.content))
            if msg.name:
                total += self.count_tokens(msg.name)
        return TokenCount(max(1, total))

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        counter = getattr(getattr(self._client.responses, "input_tokens", None), "count", None)
        if counter is None:
            return self._count_tokens_local(messages=messages, tools=tools)

        request = _build_responses_request(
            messages=messages,
            tools=tools,
            config=self._config,
            include_generation_options=False,
            correlation_id=None,
        )
        try:
            response = await counter(**request)
        except Exception:
            return self._count_tokens_local(messages=messages, tools=tools)
        return TokenCount(int(_get(response, "input_tokens", 0) or 0))

    async def _stream_via_complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        result = await self.complete(
            messages=messages,
            tools=tools,
            config_override=config_override,
        )
        if not result.success:
            yield StreamChunk(
                content="",
                accumulated_content="",
                is_final=True,
                finish_reason=coerce_finish_reason("error"),
            )
            return

        content = _content_to_text(result.content)
        if content:
            yield StreamChunk(content=content, accumulated_content=content)
        yield StreamChunk(
            content="",
            accumulated_content=content,
            tool_calls=result.tool_calls,
            is_final=True,
            finish_reason=result.finish_reason,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )

    def _count_tokens_local(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        total = self.count_messages_tokens(messages)
        if tools:
            for tool in tools:
                tool_text = f"{tool.name}\n{tool.description}\n{json.dumps(tool.parameters, sort_keys=True)}"
                total = TokenCount(total + self.count_tokens(tool_text))
        return total


def _create_openai_client(
    *,
    api_key: str | None,
    base_url: str | None,
    organization: str | None,
    project: str | None,
    timeout_seconds: float,
) -> Any:
    try:
        import openai
    except ImportError as exc:
        raise ImportError("openai package required. Install with: uv add 'cemaf[openai]'") from exc

    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": timeout_seconds,
    }
    if base_url:
        kwargs["base_url"] = base_url
    if organization:
        kwargs["organization"] = organization
    if project:
        kwargs["project"] = project
    return openai.AsyncOpenAI(**kwargs)


def _messages_to_responses_input(messages: list[Message]) -> tuple[str, str | list[dict[str, Any]]]:
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == MessageRole.SYSTEM:
            instructions.append(_content_to_text(msg.content))
            continue

        if msg.role == MessageRole.TOOL:
            if not msg.tool_call_id:
                raise ValueError("OpenAI Responses tool result messages require tool_call_id")
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.tool_call_id,
                    "output": _content_to_text(msg.content),
                }
            )
            continue

        if msg.role == MessageRole.ASSISTANT and msg.tool_calls:
            if msg.content:
                item: dict[str, Any] = {
                    "role": MessageRole.ASSISTANT.value,
                    "content": _content_to_responses_content(msg.content, role=msg.role),
                }
                phase = _assistant_phase(msg)
                if phase:
                    item["phase"] = phase
                input_items.append(item)
            for tool_call in msg.tool_calls:
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": _arguments_to_json(tool_call.arguments),
                    }
                )
            continue

        item = {
            "role": msg.role.value,
            "content": _content_to_responses_content(msg.content, role=msg.role),
        }
        phase = _assistant_phase(msg)
        if phase:
            item["phase"] = phase
        input_items.append(item)

    instructions_text = "\n\n".join(part for part in instructions if part)
    if not input_items:
        return instructions_text, ""
    return instructions_text, input_items


def _build_responses_request(
    *,
    messages: list[Message],
    tools: list[ToolDefinition] | None,
    config: LLMConfig,
    include_generation_options: bool = True,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    instructions, input_payload = _messages_to_responses_input(messages)
    request: dict[str, Any] = {
        "model": config.model,
        "input": input_payload,
    }
    if instructions:
        request["instructions"] = instructions
    if tools:
        request["tools"] = [_tool_to_responses_format(t) for t in tools]
    if include_generation_options:
        request["max_output_tokens"] = config.max_tokens
        request["temperature"] = config.temperature
        request["top_p"] = config.top_p
    if correlation_id:
        request["metadata"] = {"correlation_id": correlation_id}
    return request


def _tool_to_responses_format(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": {
            **tool.parameters,
            "required": list(tool.required),
        },
        "strict": False,
    }


def _response_text(response: Any) -> str:
    output_text = _get(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text

    parts: list[str] = []
    for item in _as_list(_get(response, "output", [])):
        if _get(item, "type", "") != "message":
            continue
        for content_part in _as_list(_get(item, "content", [])):
            text = _get(content_part, "text", "")
            if isinstance(text, str) and text:
                parts.append(text)
    return "".join(parts)


def _response_tool_calls(response: Any) -> list[ToolCall]:
    tool_calls: list[ToolCall] = []
    for item in _as_list(_get(response, "output", [])):
        tool_call = _tool_call_from_response_item(item)
        if tool_call is not None:
            tool_calls.append(tool_call)
    return tool_calls


def _tool_call_from_response_item(item: Any) -> ToolCall | None:
    item_type = _get(item, "type", "")
    if item_type not in {"function_call", "custom_tool_call"}:
        return None
    return ToolCall(
        id=str(_get(item, "call_id", "") or _get(item, "id", "")),
        name=str(_get(item, "name", "")),
        arguments=_parse_arguments(_get(item, "arguments", "{}")),
    )


def _response_usage(response: Any) -> tuple[int, int]:
    usage = _get(response, "usage", {}) or {}
    prompt_tokens = int(_get(usage, "input_tokens", _get(usage, "prompt_tokens", 0)) or 0)
    completion_tokens = int(_get(usage, "output_tokens", _get(usage, "completion_tokens", 0)) or 0)
    return prompt_tokens, completion_tokens


def _response_finish_reason(response: Any, *, tool_calls: tuple[ToolCall, ...]) -> str:
    if tool_calls:
        return "tool_calls"

    status = str(_get(response, "status", "") or "")
    if status == "completed":
        return "stop"
    if status == "incomplete":
        details = _get(response, "incomplete_details", {}) or {}
        reason = str(_get(details, "reason", "") or "")
        if reason == "max_output_tokens":
            return "max_tokens"
        if reason == "content_filter":
            return "content_filter"
        return reason or "error"
    if status in {"cancelled", "failed"}:
        return "error"
    return status or "stop"


def _response_failure_error(response: Any) -> str:
    status = str(_get(response, "status", "") or "")
    if status not in {"cancelled", "failed"}:
        return ""

    error = _get(response, "error", None)
    message = str(_get(error, "message", "") or _get(error, "code", "") or "").strip()
    if message:
        return f"returned status {status}: {message}"
    return f"returned status {status}"


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return list(value) if isinstance(value, tuple) else [value]


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False)


def _content_to_responses_content(
    content: object,
    *,
    role: MessageRole,
) -> str | list[dict[str, Any]]:
    """Normalize framework message content into Responses content parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return [_content_part_to_responses(part, role=role) for part in content]
    return _content_to_text(content)


def _content_part_to_responses(part: object, *, role: MessageRole) -> dict[str, Any]:
    text_type = "output_text" if role == MessageRole.ASSISTANT else "input_text"
    if not isinstance(part, dict):
        return {"type": text_type, "text": _content_to_text(part)}

    part_type = part.get("type")
    if part_type in {
        "input_text",
        "output_text",
        "input_image",
        "input_file",
        "input_audio",
        "refusal",
    }:
        return dict(part)

    if part_type == "text" or (part_type is None and "text" in part):
        return {"type": text_type, "text": str(part.get("text", ""))}

    if part_type == "image_url":
        image_url = part.get("image_url")
        detail = part.get("detail")
        if isinstance(image_url, dict):
            detail = detail or image_url.get("detail")
            image_url = image_url.get("url")
        if not image_url:
            raise ValueError("OpenAI Responses image content requires image_url")
        normalized: dict[str, Any] = {
            "type": "input_image",
            "image_url": str(image_url),
        }
        if detail:
            normalized["detail"] = detail
        return normalized

    if part_type is not None:
        return dict(part)

    return {"type": text_type, "text": _content_to_text(part)}


def _assistant_phase(message: Message) -> str | None:
    if message.role != MessageRole.ASSISTANT:
        return None
    phase = message.metadata.get("phase")
    if phase is None:
        return None
    if phase not in {"commentary", "final_answer"}:
        raise ValueError("OpenAI Responses assistant phase must be 'commentary' or 'final_answer'")
    return str(phase)


def _arguments_to_json(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments)


def _parse_arguments(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return args
    if not isinstance(args, str):
        return {"raw": args}
    try:
        parsed = json.loads(args)
    except json.JSONDecodeError:
        return {"raw": args}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


async def _get_final_stream_response(stream: Any) -> Any | None:
    get_final_response = getattr(stream, "get_final_response", None)
    if get_final_response is None:
        return None
    try:
        return await get_final_response()
    except RuntimeError:
        return None
