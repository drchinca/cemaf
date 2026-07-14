"""Tests for the native OpenAI Responses API LLM adapter."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cemaf.core.types import FinishReason, LLMProvider, TokenCount
from cemaf.llm.openai_responses import (
    OpenAIResponsesLLMClient,
    _messages_to_responses_input,
)
from cemaf.llm.protocols import LLMClient, LLMConfig, Message, MessageRole, ToolCall, ToolDefinition


class _FakeStream:
    def __init__(self, events: list[object], final_response: object | None = None) -> None:
        self._events = events
        self._final_response = final_response

    def __aiter__(self):
        self._iter = iter(self._events)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def get_final_response(self) -> object | None:
        return self._final_response


class _FakeStreamManager:
    def __init__(self, stream: _FakeStream) -> None:
        self._stream = stream

    async def __aenter__(self) -> _FakeStream:
        return self._stream

    async def __aexit__(self, *args: object) -> None:
        return None


def _fake_openai_client(
    response: object,
    *,
    token_count: object | None = None,
    stream: _FakeStream | None = None,
) -> SimpleNamespace:
    responses = SimpleNamespace(
        create=AsyncMock(return_value=response),
    )
    if token_count is not None:
        responses.input_tokens = SimpleNamespace(
            count=AsyncMock(return_value=token_count),
        )
    if stream is not None:
        responses.stream = MagicMock(return_value=_FakeStreamManager(stream))
    return SimpleNamespace(
        responses=responses,
    )


class TestProtocolCompliance:
    def test_satisfies_llm_client_protocol(self) -> None:
        client = OpenAIResponsesLLMClient(client=_fake_openai_client({"status": "completed"}))
        assert isinstance(client, LLMClient)

    def test_config_returns_llm_config(self) -> None:
        client = OpenAIResponsesLLMClient(
            client=_fake_openai_client({"status": "completed"}),
            model="gpt-5.5",
            temperature=0.2,
            max_tokens=2048,
        )
        assert client.config.model == "gpt-5.5"
        assert client.config.temperature == 0.2
        assert client.config.max_tokens == 2048


class TestCompatibilityImport:
    def test_legacy_openai_client_name_uses_responses_adapter(self) -> None:
        from cemaf.llm.openai import OpenAILLMClient

        client = OpenAILLMClient(
            client=_fake_openai_client({"status": "completed"}),
            model="gpt-5.5",
            temperature=0.2,
        )

        assert isinstance(client, OpenAIResponsesLLMClient)
        assert client.config.model == "gpt-5.5"
        assert client.config.temperature == 0.2


class TestMessageConversion:
    def test_system_instruction_is_separate_from_input(self) -> None:
        instructions, input_payload = _messages_to_responses_input(
            [
                Message.system("Be concise."),
                Message.user("What is CEMAF?"),
            ]
        )

        assert instructions == "Be concise."
        assert input_payload == [{"role": "user", "content": "What is CEMAF?"}]

    def test_tool_turns_use_responses_items(self) -> None:
        tool_call = ToolCall(id="call_1", name="search", arguments={"query": "CEMAF"})
        instructions, input_payload = _messages_to_responses_input(
            [
                Message.assistant("", tool_calls=(tool_call,)),
                Message.tool_result("call_1", "CEMAF is a framework", name="search"),
            ]
        )

        assert instructions == ""
        assert input_payload == [
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "search",
                "arguments": '{"query": "CEMAF"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "CEMAF is a framework",
            },
        ]

    def test_tool_result_requires_tool_call_id(self) -> None:
        with pytest.raises(ValueError, match="tool result messages require tool_call_id"):
            _messages_to_responses_input(
                [
                    Message(
                        role=MessageRole.TOOL,
                        content="CEMAF is a framework",
                        name="search",
                    )
                ]
            )

    def test_structured_text_content_uses_responses_content_parts(self) -> None:
        instructions, input_payload = _messages_to_responses_input(
            [
                Message.user(
                    [
                        {"type": "text", "text": "hello"},
                        {"text": "world"},
                    ]
                )
            ]
        )

        assert instructions == ""
        assert input_payload == [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "hello"},
                    {"type": "input_text", "text": "world"},
                ],
            }
        ]

    def test_chat_style_image_content_uses_responses_image_parts(self) -> None:
        _, input_payload = _messages_to_responses_input(
            [
                Message.user(
                    [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,abc",
                                "detail": "high",
                            },
                        }
                    ]
                )
            ]
        )

        assert input_payload == [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,abc",
                        "detail": "high",
                    }
                ],
            }
        ]

    def test_assistant_phase_metadata_is_preserved(self) -> None:
        _, input_payload = _messages_to_responses_input(
            [
                Message.assistant(
                    [{"type": "text", "text": "I will check the docs."}],
                    metadata={"phase": "commentary"},
                )
            ]
        )

        assert input_payload == [
            {
                "role": "assistant",
                "content": [{"type": "output_text", "text": "I will check the docs."}],
                "phase": "commentary",
            }
        ]

    def test_invalid_assistant_phase_fails_loudly(self) -> None:
        with pytest.raises(ValueError, match="assistant phase must be 'commentary' or 'final_answer'"):
            _messages_to_responses_input(
                [
                    Message.assistant(
                        "working",
                        metadata={"phase": "draft"},
                    )
                ]
            )


class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_sends_responses_payload_and_parses_tool_call(self) -> None:
        response = SimpleNamespace(
            id="resp_1",
            model="gpt-5.5",
            status="completed",
            output_text="",
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="call_1",
                    name="search",
                    arguments='{"query": "CEMAF"}',
                )
            ],
            usage=SimpleNamespace(input_tokens=12, output_tokens=7),
        )
        fake_client = _fake_openai_client(response)
        client = OpenAIResponsesLLMClient(client=fake_client)

        result = await client.complete(
            messages=[
                Message.system("Be precise."),
                Message.user("Search for CEMAF"),
            ],
            tools=[
                ToolDefinition(
                    name="search",
                    description="Search docs",
                    parameters={"type": "object", "properties": {"query": {"type": "string"}}},
                    required=("query",),
                )
            ],
            correlation_id="run_123",
        )

        request = fake_client.responses.create.call_args.kwargs
        assert request["model"] == "gpt-5.5"
        assert request["instructions"] == "Be precise."
        assert request["input"] == [{"role": "user", "content": "Search for CEMAF"}]
        assert request["max_output_tokens"] == 4096
        assert request["top_p"] == 1.0
        assert request["metadata"] == {"correlation_id": "run_123"}
        assert request["tools"] == [
            {
                "type": "function",
                "name": "search",
                "description": "Search docs",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "strict": False,
            }
        ]

        assert result.success
        assert result.provider is LLMProvider.OPENAI
        assert result.finish_reason is FinishReason.TERMINAL_TOOL
        assert result.finish_reason_native == "tool_calls"
        assert result.prompt_tokens == TokenCount(12)
        assert result.completion_tokens == TokenCount(7)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search"
        assert result.tool_calls[0].arguments == {"query": "CEMAF"}
        assert result.metadata["response_id"] == "resp_1"

    @pytest.mark.asyncio
    async def test_complete_parses_output_message_parts(self) -> None:
        response = {
            "id": "resp_2",
            "model": "gpt-5.5",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Hello from Responses.",
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 4, "output_tokens": 3},
        }
        client = OpenAIResponsesLLMClient(client=_fake_openai_client(response))

        result = await client.complete(messages=[Message.user("hi")])

        assert result.success
        assert result.content == "Hello from Responses."
        assert result.finish_reason is FinishReason.TERMINAL_STOP

    @pytest.mark.asyncio
    async def test_config_override_uses_response_token_name(self) -> None:
        response = {"status": "completed", "output_text": "ok"}
        fake_client = _fake_openai_client(response)
        client = OpenAIResponsesLLMClient(client=fake_client)
        override = LLMConfig(model="gpt-5.5", temperature=0.0, max_tokens=99, top_p=0.5)

        result = await client.complete(
            messages=[Message.user("hi")],
            config_override=override,
        )

        assert result.success
        request = fake_client.responses.create.call_args.kwargs
        assert request["temperature"] == 0.0
        assert request["top_p"] == 0.5
        assert request["max_output_tokens"] == 99

    @pytest.mark.asyncio
    async def test_error_returns_failed_result(self) -> None:
        fake_client = SimpleNamespace(
            responses=SimpleNamespace(
                create=AsyncMock(side_effect=RuntimeError("rate limited")),
            )
        )
        client = OpenAIResponsesLLMClient(client=fake_client)

        result = await client.complete(messages=[Message.user("hi")])

        assert not result.success
        assert "rate limited" in str(result.error)

    @pytest.mark.asyncio
    async def test_failed_response_status_returns_failed_result(self) -> None:
        response = {
            "id": "resp_failed",
            "model": "gpt-5.5",
            "status": "failed",
            "error": {"message": "quota exceeded"},
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }
        client = OpenAIResponsesLLMClient(client=_fake_openai_client(response))

        result = await client.complete(messages=[Message.user("hi")])

        assert not result.success
        assert result.message is None
        assert "status failed" in str(result.error)
        assert "quota exceeded" in str(result.error)

    @pytest.mark.asyncio
    async def test_incomplete_response_status_preserves_partial_result(self) -> None:
        response = {
            "id": "resp_incomplete",
            "model": "gpt-5.5",
            "status": "incomplete",
            "output_text": "partial",
            "incomplete_details": {"reason": "max_output_tokens"},
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }
        client = OpenAIResponsesLLMClient(client=_fake_openai_client(response))

        result = await client.complete(messages=[Message.user("hi")])

        assert result.success
        assert result.content == "partial"
        assert result.finish_reason is FinishReason.PARTIAL_LENGTH
        assert result.finish_reason_native == "max_tokens"


class TestStreaming:
    @pytest.mark.asyncio
    async def test_stream_uses_responses_streaming_events(self) -> None:
        final_response = {
            "id": "resp_3",
            "model": "gpt-5.5",
            "status": "completed",
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }
        fake_stream = _FakeStream(
            events=[
                SimpleNamespace(type="response.output_text.delta", delta="hel"),
                SimpleNamespace(type="response.output_text.delta", delta="lo"),
                SimpleNamespace(type="response.completed", response=final_response),
            ],
            final_response=final_response,
        )
        fake_client = _fake_openai_client(final_response, stream=fake_stream)
        client = OpenAIResponsesLLMClient(client=fake_client)

        chunks = [chunk async for chunk in client.stream(messages=[Message.user("hi")])]

        request = fake_client.responses.stream.call_args.kwargs
        assert request["model"] == "gpt-5.5"
        assert request["input"] == [{"role": "user", "content": "hi"}]
        assert request["max_output_tokens"] == 4096
        fake_client.responses.create.assert_not_called()

        assert chunks[0].content == "hel"
        assert chunks[1].content == "lo"
        assert chunks[-1].is_final
        assert chunks[-1].accumulated_content == "hello"
        assert chunks[-1].prompt_tokens == TokenCount(1)
        assert chunks[-1].completion_tokens == TokenCount(2)

    @pytest.mark.asyncio
    async def test_stream_failed_response_status_returns_error_final_chunk(self) -> None:
        final_response = {
            "id": "resp_failed",
            "model": "gpt-5.5",
            "status": "failed",
            "error": {"message": "quota exceeded"},
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }
        fake_stream = _FakeStream(
            events=[
                SimpleNamespace(type="response.output_text.delta", delta="hel"),
                SimpleNamespace(type="response.failed", response=final_response),
            ],
            final_response=final_response,
        )
        fake_client = _fake_openai_client(final_response, stream=fake_stream)
        client = OpenAIResponsesLLMClient(client=fake_client)

        chunks = [chunk async for chunk in client.stream(messages=[Message.user("hi")])]

        assert chunks[0].content == "hel"
        assert chunks[-1].is_final
        assert chunks[-1].finish_reason is FinishReason.PARTIAL_ERROR
        assert chunks[-1].accumulated_content == "hel"
        assert "status failed" in chunks[-1].content
        assert "quota exceeded" in chunks[-1].content


class TestExactTokenCounting:
    @pytest.mark.asyncio
    async def test_count_tokens_exact_uses_openai_input_tokens_endpoint(self) -> None:
        response = {"status": "completed", "output_text": "ok"}
        token_count = SimpleNamespace(object="response.input_tokens", input_tokens=27)
        fake_client = _fake_openai_client(response, token_count=token_count)
        client = OpenAIResponsesLLMClient(client=fake_client)

        result = await client.count_tokens_exact(
            messages=[
                Message.system("Be precise."),
                Message.user("Search for CEMAF"),
            ],
            tools=[
                ToolDefinition(
                    name="search",
                    description="Search docs",
                    parameters={"type": "object", "properties": {"query": {"type": "string"}}},
                    required=("query",),
                )
            ],
        )

        request = fake_client.responses.input_tokens.count.call_args.kwargs
        assert result == TokenCount(27)
        assert request == {
            "model": "gpt-5.5",
            "input": [{"role": "user", "content": "Search for CEMAF"}],
            "instructions": "Be precise.",
            "tools": [
                {
                    "type": "function",
                    "name": "search",
                    "description": "Search docs",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                    "strict": False,
                }
            ],
        }

    @pytest.mark.asyncio
    async def test_count_tokens_exact_falls_back_when_openai_counting_fails(self) -> None:
        response = {"status": "completed", "output_text": "ok"}
        fake_client = _fake_openai_client(response, token_count=SimpleNamespace(input_tokens=0))
        fake_client.responses.input_tokens.count = AsyncMock(side_effect=RuntimeError("bad request"))
        client = OpenAIResponsesLLMClient(client=fake_client)

        result = await client.count_tokens_exact(messages=[Message.user("hi")])

        assert result == TokenCount(5)
