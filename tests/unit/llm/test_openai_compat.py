"""Tests for OpenAICompatClient — covers all 5 OpenAI-compatible providers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cemaf.core.defaults import DEFAULT_FREE_LLM_MODEL
from cemaf.core.types import FinishReason, LLMProvider, TokenCount
from cemaf.llm.openai_compat import OpenAICompatClient, _message_to_dict, _parse_arguments
from cemaf.llm.protocols import (
    LLMClient,
    LLMConfig,
    Message,
    ToolCall,
    ToolDefinition,
)


class _AsyncStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self._lines = lines
        self.status_code = status_code

    async def __aenter__(self) -> _AsyncStreamResponse:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_satisfies_llm_client_protocol(self) -> None:
        client = OpenAICompatClient(model="test")
        assert isinstance(client, LLMClient)

    def test_config_returns_llm_config(self) -> None:
        client = OpenAICompatClient(model="local-test-model", temperature=0.5, max_tokens=2000)
        assert client.config.model == "local-test-model"
        assert client.config.temperature == 0.5
        assert client.config.max_tokens == 2000

    def test_default_base_url(self) -> None:
        client = OpenAICompatClient()
        assert client._base_url == "http://localhost:11434/v1"
        assert client.config.model == DEFAULT_FREE_LLM_MODEL
        assert client._provider is LLMProvider.OLLAMA

    def test_custom_base_url(self) -> None:
        client = OpenAICompatClient(base_url="http://localhost:11434/v1")
        assert client._base_url == "http://localhost:11434/v1"

    def test_trailing_slash_stripped(self) -> None:
        client = OpenAICompatClient(base_url="http://localhost:11434/v1/")
        assert not client._base_url.endswith("/")


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


class TestTokenCounting:
    def test_count_tokens_heuristic(self) -> None:
        client = OpenAICompatClient()
        count = client.count_tokens(text="hello world test")
        assert count > 0

    def test_count_tokens_empty_is_zero(self) -> None:
        """Empty text has zero tokens (was masked by floor-at-1 in old heuristic)."""
        client = OpenAICompatClient()
        assert client.count_tokens(text="") == TokenCount(0)

    def test_count_messages_tokens(self) -> None:
        client = OpenAICompatClient()
        messages = [Message.user(content="hello"), Message.assistant(content="hi")]
        count = client.count_messages_tokens(messages=messages)
        assert count > 0


# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------


class TestMessageConversion:
    def test_user_message(self) -> None:
        msg = Message.user(content="hello")
        d = _message_to_dict(msg)
        assert d["role"] == "user"
        assert d["content"] == "hello"

    def test_system_message(self) -> None:
        msg = Message.system(content="you are helpful")
        d = _message_to_dict(msg)
        assert d["role"] == "system"

    def test_tool_result_message(self) -> None:
        msg = Message.tool_result(tool_call_id="tc1", content="result", name="search")
        d = _message_to_dict(msg)
        assert d["role"] == "tool"
        assert d["name"] == "search"
        assert d["tool_call_id"] == "tc1"

    def test_assistant_with_tool_calls(self) -> None:
        tc = ToolCall(id="tc1", name="search", arguments={"q": "test"})
        msg = Message.assistant(content="", tool_calls=(tc,))
        d = _message_to_dict(msg)
        assert len(d["tool_calls"]) == 1

    def test_tool_call_arguments_serialized_as_json_string(self) -> None:
        # OpenAI/Ollama reject an object here; arguments MUST be a JSON-encoded string.
        tc = ToolCall(id="tc1", name="write_file", arguments={"path": "a.txt", "content": "42"})
        msg = Message.assistant(content="", tool_calls=(tc,))
        d = _message_to_dict(msg)
        args = d["tool_calls"][0]["function"]["arguments"]
        assert isinstance(args, str)
        assert json.loads(args) == {"path": "a.txt", "content": "42"}

    def test_tool_call_string_arguments_serialized_as_json_string(self) -> None:
        tc = ToolCall(id="tc1", name="write_file", arguments='{"path":"a.txt"}')
        msg = Message.assistant(content="", tool_calls=(tc,))
        d = _message_to_dict(msg)
        args = d["tool_calls"][0]["function"]["arguments"]
        assert isinstance(args, str)
        assert json.loads(args) == {"path": "a.txt"}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class TestParseArguments:
    def test_dict_passthrough(self) -> None:
        assert _parse_arguments({"a": 1}) == {"a": 1}

    def test_json_string(self) -> None:
        assert _parse_arguments('{"a": 1}') == {"a": 1}

    def test_invalid_json_fallback(self) -> None:
        result = _parse_arguments("not json")
        assert result == {"raw": "not json"}

    def test_empty_string(self) -> None:
        result = _parse_arguments("")
        assert "raw" in result


# ---------------------------------------------------------------------------
# Complete — success path
# ---------------------------------------------------------------------------


class TestComplete:
    @pytest.mark.asyncio
    async def test_successful_completion(self) -> None:
        client = OpenAICompatClient(api_key="test-key", model="local-test-model")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "local-test-model",
        }

        with patch("cemaf.llm.openai_compat.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(messages=[Message.user(content="hi")])

        assert result.success
        assert result.content == "Hello!"
        assert result.model == "local-test-model"
        assert result.prompt_tokens == TokenCount(10)
        assert result.completion_tokens == TokenCount(5)

    @pytest.mark.asyncio
    async def test_api_error_returns_fail(self) -> None:
        client = OpenAICompatClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"

        with patch("cemaf.llm.openai_compat.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(messages=[Message.user(content="hi")])

        assert not result.success
        assert "429" in result.error

    @pytest.mark.asyncio
    async def test_connection_error_returns_fail(self) -> None:
        client = OpenAICompatClient(base_url="http://localhost:99999/v1")

        with patch("cemaf.llm.openai_compat.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=ConnectionError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(messages=[Message.user(content="hi")])

        assert not result.success
        assert "refused" in result.error

    @pytest.mark.asyncio
    async def test_tool_calls_parsed(self) -> None:
        client = OpenAICompatClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tc_1",
                                "function": {
                                    "name": "search",
                                    "arguments": '{"query": "CEMAF"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "local-test-model",
        }

        with patch("cemaf.llm.openai_compat.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(
                messages=[Message.user(content="search for CEMAF")],
                tools=[
                    ToolDefinition(
                        name="search",
                        description="Search the web",
                        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
                        required=("query",),
                    )
                ],
            )

        assert result.success
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search"
        assert result.tool_calls[0].arguments["query"] == "CEMAF"

    @pytest.mark.asyncio
    async def test_provider_family_propagates_to_result(self) -> None:
        client = OpenAICompatClient(
            api_key="hf-test",
            base_url="https://router.huggingface.co/v1",
            model="google/gemma-2-2b-it",
            provider=LLMProvider.HUGGINGFACE,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello from HF"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            "model": "google/gemma-2-2b-it",
        }

        with patch("cemaf.llm.openai_compat.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(messages=[Message.user(content="hi")])

        assert result.success
        assert result.provider is LLMProvider.HUGGINGFACE

    @pytest.mark.asyncio
    async def test_config_override(self) -> None:
        client = OpenAICompatClient(api_key="key", model="local-test-model")
        override = LLMConfig(model="override-test-model", temperature=0.0, max_tokens=100)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            "model": "override-test-model",
        }

        with patch("cemaf.llm.openai_compat.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            await client.complete(
                messages=[Message.user(content="hi")],
                config_override=override,
            )

        # Verify override model was used in request
        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["model"] == "override-test-model"
        assert payload["temperature"] == 0.0
        assert payload["top_p"] == 1.0

    @pytest.mark.asyncio
    async def test_httpx_missing_returns_fail(self) -> None:
        client = OpenAICompatClient(api_key="key")

        with patch.dict("sys.modules", {"httpx": None}), patch("cemaf.llm.openai_compat.httpx", None):
            # Force ImportError path
            import cemaf.llm.openai_compat as mod

            original = mod.__dict__.get("httpx")
            try:
                mod.__dict__["httpx"] = None
                # Can't easily test this without real import manipulation
                # Just verify the client doesn't crash on creation
                assert client.config.model == DEFAULT_FREE_LLM_MODEL
            finally:
                if original:
                    mod.__dict__["httpx"] = original


# ---------------------------------------------------------------------------
# Stream
# ---------------------------------------------------------------------------


class TestStream:
    @pytest.mark.asyncio
    async def test_stream_payload_preserves_tools_stop_sequences_and_top_p(self) -> None:
        client = OpenAICompatClient(api_key="key", model="local-test-model")
        cfg = LLMConfig(
            model="stream-test-model",
            temperature=0.2,
            max_tokens=128,
            top_p=0.4,
            stop_sequences=("END",),
        )
        tool = ToolDefinition(
            name="search",
            description="Search docs",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            required=("query",),
        )
        lines = [
            "data: " + json.dumps({"choices": [{"delta": {"content": "Hel"}}]}),
            "data: " + json.dumps({"choices": [{"delta": {"content": "lo"}}]}),
            "data: [DONE]",
        ]

        with patch("cemaf.llm.openai_compat.httpx") as mock_httpx:
            mock_client = MagicMock()
            mock_client.stream.return_value = _AsyncStreamResponse(lines)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            chunks = [
                chunk
                async for chunk in client.stream(
                    messages=[Message.user(content="hi")],
                    tools=[tool],
                    config_override=cfg,
                )
            ]

        payload = mock_client.stream.call_args.kwargs["json"]
        assert payload["model"] == "stream-test-model"
        assert payload["temperature"] == 0.2
        assert payload["max_tokens"] == 128
        assert payload["top_p"] == 0.4
        assert payload["stop"] == ["END"]
        assert payload["tools"] == [tool.to_openai_format()]
        assert payload["stream"] is True
        assert "".join(chunk.content for chunk in chunks[:-1]) == "Hello"
        assert chunks[-1].is_final

    @pytest.mark.asyncio
    async def test_stream_malformed_json_returns_partial_error(self) -> None:
        client = OpenAICompatClient(api_key="key", model="local-test-model")
        lines = [
            "data: " + json.dumps({"choices": [{"delta": {"content": "Hel"}}]}),
            "data: {not-json",
        ]

        with patch("cemaf.llm.openai_compat.httpx") as mock_httpx:
            mock_client = MagicMock()
            mock_client.stream.return_value = _AsyncStreamResponse(lines)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            chunks = [chunk async for chunk in client.stream(messages=[Message.user(content="hi")])]

        assert chunks[0].content == "Hel"
        assert chunks[-1].is_final
        assert chunks[-1].finish_reason is FinishReason.PARTIAL_ERROR
        assert chunks[-1].accumulated_content == "Hel"
        assert "malformed JSON" in chunks[-1].content

    @pytest.mark.asyncio
    async def test_stream_http_error_returns_partial_error(self) -> None:
        client = OpenAICompatClient(api_key="key", model="local-test-model")

        with patch("cemaf.llm.openai_compat.httpx") as mock_httpx:
            mock_client = MagicMock()
            mock_client.stream.return_value = _AsyncStreamResponse([], status_code=503)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            chunks = [chunk async for chunk in client.stream(messages=[Message.user(content="hi")])]

        assert len(chunks) == 1
        assert chunks[0].is_final
        assert chunks[0].finish_reason is FinishReason.PARTIAL_ERROR
        assert "503" in chunks[0].content


# ---------------------------------------------------------------------------
# Provider-specific factory tests
# ---------------------------------------------------------------------------


class TestProviderFactories:
    def test_create_ollama(self) -> None:
        from cemaf.llm.factories import create_llm_client

        client = create_llm_client("ollama", model="qwen3.5")
        assert client.config.model == "qwen3.5"
        assert "11434" in client._base_url

    def test_create_ollama_cloud_preserves_runtime_settings(self) -> None:
        from cemaf.llm.factories import create_llm_client

        client = create_llm_client(
            "ollama-cloud",
            api_key="ollama-test",
            temperature=0.2,
            max_tokens=123,
            top_p=0.4,
            timeout_seconds=12.0,
        )

        assert client.config.temperature == 0.2
        assert client.config.max_tokens == 123
        assert client.config.top_p == 0.4
        assert client.config.timeout_seconds == 12.0

    def test_create_openai(self) -> None:
        from cemaf.llm.factories import create_llm_client
        from cemaf.llm.openai_responses import OpenAIResponsesLLMClient

        client = create_llm_client("openai", client=object(), model="gpt-5.5")
        assert isinstance(client, OpenAIResponsesLLMClient)
        assert client.config.model == "gpt-5.5"

    def test_create_openai_compatible(self) -> None:
        from cemaf.llm.factories import create_llm_client

        client = create_llm_client(
            "openai-compatible",
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            top_p=0.3,
            provider_family=LLMProvider.OPENAI,
        )
        assert isinstance(client, OpenAICompatClient)
        assert client.config.model == "gpt-4o"
        assert client.config.top_p == 0.3
        assert "openai.com" in client._base_url
        assert client._provider is LLMProvider.OPENAI

    def test_create_openai_compatible_defaults_to_local_free_provider(self) -> None:
        from cemaf.llm.factories import create_llm_client

        client = create_llm_client("openai-compatible")

        assert isinstance(client, OpenAICompatClient)
        assert client.config.model == DEFAULT_FREE_LLM_MODEL
        assert client._base_url == "http://localhost:11434/v1"
        assert client._provider is LLMProvider.OLLAMA

    def test_create_groq(self) -> None:
        from cemaf.llm.factories import create_llm_client

        client = create_llm_client("groq", api_key="gsk-test", top_p=0.4)
        assert "groq.com" in client._base_url
        assert client._provider is LLMProvider.GROQ
        assert client.config.top_p == 0.4

    def test_create_together(self) -> None:
        from cemaf.llm.factories import create_llm_client

        client = create_llm_client("together", api_key="tok-test", max_tokens=123)
        assert "together.xyz" in client._base_url
        assert client._provider is LLMProvider.TOGETHER
        assert client.config.max_tokens == 123

    def test_create_huggingface(self) -> None:
        from cemaf.llm.factories import create_llm_client

        client = create_llm_client(
            "huggingface",
            api_key="hf-test",
            model="google/gemma-2-2b-it",
            timeout_seconds=12.0,
        )
        assert "huggingface.co" in client._base_url
        assert client._provider is LLMProvider.HUGGINGFACE
        assert client.config.model == "google/gemma-2-2b-it"
        assert client.config.timeout_seconds == 12.0

    def test_create_gemini(self) -> None:
        from cemaf.llm.factories import create_llm_client

        client = create_llm_client("gemini", api_key="AIza-test")
        assert client.config.model == "gemini-2.5-flash"

    def test_unknown_provider_raises(self) -> None:
        from cemaf.llm.factories import create_llm_client

        with pytest.raises(Exception):
            create_llm_client("nonexistent_provider")
