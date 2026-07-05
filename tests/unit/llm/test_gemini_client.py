"""Tests for GeminiClient — Google Gemini API adapter."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cemaf.core.types import FinishReason, LLMProvider, TokenCount
from cemaf.llm.gemini import GeminiClient, _messages_to_gemini, _tool_to_gemini
from cemaf.llm.protocols import (
    LLMClient,
    Message,
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
        client = GeminiClient(api_key="test")
        assert isinstance(client, LLMClient)

    def test_config(self) -> None:
        client = GeminiClient(api_key="test", model="gemini-2.5-pro", temperature=0.3)
        assert client.config.model == "gemini-2.5-pro"
        assert client.config.temperature == 0.3


# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------


class TestMessageConversion:
    def test_user_message(self) -> None:
        messages = [Message.user(content="hello")]
        contents = _messages_to_gemini(messages=messages)
        assert len(contents) == 1
        assert contents[0]["role"] == "user"
        assert contents[0]["parts"][0]["text"] == "hello"

    def test_assistant_message(self) -> None:
        messages = [Message.assistant(content="hi back")]
        contents = _messages_to_gemini(messages=messages)
        assert contents[0]["role"] == "model"

    def test_system_prepended_to_first_user(self) -> None:
        messages = [
            Message.system(content="You are helpful"),
            Message.user(content="hello"),
        ]
        contents = _messages_to_gemini(messages=messages)
        # System merged into first user message
        assert len(contents) == 1
        assert "You are helpful" in contents[0]["parts"][0]["text"]
        assert "hello" in contents[0]["parts"][0]["text"]

    def test_system_prepended_without_flattening_structured_user_parts(self) -> None:
        image_part = {
            "inlineData": {
                "mimeType": "image/png",
                "data": "base64-image",
            }
        }
        messages = [
            Message.system(content="Inspect the image."),
            Message.user(content=[{"type": "text", "text": "What changed?"}, image_part]),
        ]

        contents = _messages_to_gemini(messages=messages)

        assert contents == [
            {
                "role": "user",
                "parts": [
                    {"text": "Inspect the image.\n\nWhat changed?"},
                    image_part,
                ],
            }
        ]

    def test_system_prepended_before_non_text_structured_user_part(self) -> None:
        image_part = {
            "inlineData": {
                "mimeType": "image/png",
                "data": "base64-image",
            }
        }
        messages = [
            Message.system(content="Inspect the image."),
            Message.user(content=[image_part]),
        ]

        contents = _messages_to_gemini(messages=messages)

        assert contents == [
            {
                "role": "user",
                "parts": [
                    {"text": "Inspect the image."},
                    image_part,
                ],
            }
        ]

    def test_system_only_message_is_preserved(self) -> None:
        contents = _messages_to_gemini(messages=[Message.system(content="You are helpful")])
        assert contents == [{"role": "user", "parts": [{"text": "You are helpful"}]}]

    def test_structured_text_content_uses_gemini_parts(self) -> None:
        messages = [Message.user(content=[{"type": "text", "text": "hello"}, {"text": "world"}])]
        contents = _messages_to_gemini(messages=messages)
        assert contents[0]["parts"] == [{"text": "hello"}, {"text": "world"}]

    def test_multi_turn(self) -> None:
        messages = [
            Message.user(content="hi"),
            Message.assistant(content="hello"),
            Message.user(content="how are you"),
        ]
        contents = _messages_to_gemini(messages=messages)
        assert len(contents) == 3
        assert contents[0]["role"] == "user"
        assert contents[1]["role"] == "model"
        assert contents[2]["role"] == "user"

    def test_tool_response_message(self) -> None:
        from cemaf.llm.protocols import MessageRole

        messages = [
            Message(
                role=MessageRole.TOOL,
                content='{"result": "success"}',
                name="my_tool",
            )
        ]
        contents = _messages_to_gemini(messages=messages)
        assert len(contents) == 1
        assert contents[0]["role"] == "user"
        assert "functionResponse" in contents[0]["parts"][0]
        f_resp = contents[0]["parts"][0]["functionResponse"]
        assert f_resp["name"] == "my_tool"
        assert f_resp["response"] == {"result": "success"}

    def test_tool_response_message_requires_name(self) -> None:
        with pytest.raises(ValueError, match="Gemini tool result messages require a tool name"):
            _messages_to_gemini(messages=[Message.tool_result(tool_call_id="call_1", content="ok")])

    def test_assistant_tool_calls_message(self) -> None:
        from cemaf.llm.protocols import MessageRole, ToolCall

        messages = [
            Message(
                role=MessageRole.ASSISTANT,
                content="I will run the tool",
                tool_calls=(ToolCall(id="call_1", name="search", arguments={"q": "GCP"}),),
            )
        ]
        contents = _messages_to_gemini(messages=messages)
        assert len(contents) == 1
        assert contents[0]["role"] == "model"
        assert len(contents[0]["parts"]) == 2
        assert contents[0]["parts"][0]["text"] == "I will run the tool"
        assert "functionCall" in contents[0]["parts"][1]
        f_call = contents[0]["parts"][1]["functionCall"]
        assert f_call["name"] == "search"
        assert f_call["args"] == {"q": "GCP"}


# ---------------------------------------------------------------------------
# Tool conversion
# ---------------------------------------------------------------------------


class TestToolConversion:
    def test_tool_to_gemini_format(self) -> None:
        tool = ToolDefinition(
            name="search",
            description="Search the web",
            parameters={"type": "object", "properties": {"q": {"type": "string"}}},
        )
        result = _tool_to_gemini(tool)
        assert result["name"] == "search"
        assert result["description"] == "Search the web"
        assert "properties" in result["parameters"]


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


class TestTokenCounting:
    def test_count_tokens(self) -> None:
        client = GeminiClient(api_key="test")
        assert client.count_tokens(text="hello world") > 0

    def test_count_messages_tokens(self) -> None:
        client = GeminiClient(api_key="test")
        messages = [Message.user(content="test")]
        assert client.count_messages_tokens(messages=messages) > 0


# ---------------------------------------------------------------------------
# Complete
# ---------------------------------------------------------------------------


class TestComplete:
    @pytest.mark.asyncio
    async def test_successful_completion(self) -> None:
        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello from Gemini!"}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 8,
                "candidatesTokenCount": 4,
            },
        }

        with patch("cemaf.llm.gemini.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(messages=[Message.user(content="hi")])

        assert result.success
        assert result.content == "Hello from Gemini!"
        assert result.prompt_tokens == TokenCount(8)
        assert result.completion_tokens == TokenCount(4)
        assert result.finish_reason is FinishReason.TERMINAL_STOP
        assert result.finish_reason_native == "STOP"
        assert result.provider is LLMProvider.GEMINI

        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["generationConfig"] == {
            "temperature": 0.7,
            "maxOutputTokens": 4096,
            "topP": 1.0,
        }

    @pytest.mark.asyncio
    async def test_api_error(self) -> None:
        client = GeminiClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"

        with patch("cemaf.llm.gemini.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(messages=[Message.user(content="hi")])

        assert not result.success
        assert "400" in result.error

    @pytest.mark.asyncio
    async def test_empty_candidates(self) -> None:
        client = GeminiClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"candidates": []}

        with patch("cemaf.llm.gemini.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(messages=[Message.user(content="hi")])

        assert not result.success
        assert "No candidates" in result.error

    @pytest.mark.asyncio
    async def test_function_call_parsed(self) -> None:
        client = GeminiClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "search",
                                    "args": {"query": "CEMAF"},
                                }
                            }
                        ],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {},
        }

        with patch("cemaf.llm.gemini.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(messages=[Message.user(content="search")])

        assert result.success
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search"
        assert result.tool_calls[0].arguments["query"] == "CEMAF"
        assert result.finish_reason is FinishReason.TERMINAL_TOOL

    @pytest.mark.asyncio
    async def test_function_call_string_args_are_preserved(self) -> None:
        client = GeminiClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "search",
                                    "args": '{"query": "CEMAF"}',
                                }
                            }
                        ],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {},
        }

        with patch("cemaf.llm.gemini.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(messages=[Message.user(content="search")])

        assert result.success
        assert result.tool_calls[0].arguments == {"query": "CEMAF"}

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        client = GeminiClient(api_key="test-key")

        with patch("cemaf.llm.gemini.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=ConnectionError("timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(messages=[Message.user(content="hi")])

        assert not result.success
        assert "timeout" in result.error

    @pytest.mark.asyncio
    async def test_max_tokens_finish_reason_normalized(self) -> None:
        client = GeminiClient(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "partial"}]},
                    "finishReason": "MAX_TOKENS",
                }
            ],
            "usageMetadata": {},
        }

        with patch("cemaf.llm.gemini.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(messages=[Message.user(content="hi")])

        assert result.success
        assert result.finish_reason is FinishReason.PARTIAL_LENGTH


# ---------------------------------------------------------------------------
# Streaming and exact counting
# ---------------------------------------------------------------------------


class TestStreamingAndCounting:
    @pytest.mark.asyncio
    async def test_stream_sends_tools_and_returns_final_metadata(self) -> None:
        client = GeminiClient(
            api_key="test-key",
            temperature=0.2,
            max_tokens=123,
            top_p=0.8,
            timeout_seconds=12.0,
        )
        tool = ToolDefinition(
            name="search",
            description="Search",
            parameters={"type": "object", "properties": {"q": {"type": "string"}}},
        )
        lines = [
            "data: "
            + json.dumps(
                {
                    "candidates": [{"content": {"parts": [{"text": "Hel"}]}}],
                    "usageMetadata": {"promptTokenCount": 3},
                }
            ),
            "data: "
            + json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": "lo"},
                                    {"functionCall": {"name": "search", "args": {"q": "CEMAF"}}},
                                ]
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
                }
            ),
        ]

        with patch("cemaf.llm.gemini.httpx") as mock_httpx:
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
                )
            ]

        assert "".join(chunk.content for chunk in chunks[:-1]) == "Hello"
        final = chunks[-1]
        assert final.is_final
        assert final.accumulated_content == "Hello"
        assert final.finish_reason is FinishReason.TERMINAL_TOOL
        assert final.prompt_tokens == TokenCount(3)
        assert final.completion_tokens == TokenCount(2)
        assert final.tool_calls[0].name == "search"
        assert final.tool_calls[0].arguments == {"q": "CEMAF"}

        payload = mock_client.stream.call_args.kwargs["json"]
        assert payload["generationConfig"] == {
            "temperature": 0.2,
            "maxOutputTokens": 123,
            "topP": 0.8,
        }
        assert payload["tools"][0]["functionDeclarations"][0]["name"] == "search"

    @pytest.mark.asyncio
    async def test_stream_preserves_string_function_call_args(self) -> None:
        client = GeminiClient(api_key="test-key")
        lines = [
            "data: "
            + json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": "search",
                                            "args": '{"q": "CEMAF"}',
                                        }
                                    }
                                ]
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {},
                }
            )
        ]

        with patch("cemaf.llm.gemini.httpx") as mock_httpx:
            mock_client = MagicMock()
            mock_client.stream.return_value = _AsyncStreamResponse(lines)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            chunks = [chunk async for chunk in client.stream(messages=[Message.user(content="hi")])]

        assert chunks[-1].is_final
        assert chunks[-1].tool_calls[0].arguments == {"q": "CEMAF"}

    @pytest.mark.asyncio
    async def test_stream_malformed_json_returns_partial_error(self) -> None:
        client = GeminiClient(api_key="test-key")
        lines = [
            "data: "
            + json.dumps(
                {
                    "candidates": [{"content": {"parts": [{"text": "Hel"}]}}],
                    "usageMetadata": {"promptTokenCount": 3},
                }
            ),
            "data: {not-json",
        ]

        with patch("cemaf.llm.gemini.httpx") as mock_httpx:
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
    async def test_count_tokens_exact_uses_tool_aware_payload_and_timeout(self) -> None:
        client = GeminiClient(api_key="test-key", timeout_seconds=12.0)
        tool = ToolDefinition(
            name="lookup",
            description="Lookup",
            parameters={"type": "object", "properties": {}},
        )
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"totalTokens": 77}

        with patch("cemaf.llm.gemini.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            count = await client.count_tokens_exact(
                messages=[Message.user(content="hi")],
                tools=[tool],
            )

        assert count == TokenCount(77)
        assert mock_httpx.AsyncClient.call_args.kwargs["timeout"] == 12.0
        payload = mock_client.post.call_args.kwargs["json"]
        declarations = payload["generateContentRequest"]["tools"][0]["functionDeclarations"]
        assert declarations[0]["name"] == "lookup"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestGeminiFactory:
    def test_create_via_factory(self) -> None:
        from cemaf.llm.factories import create_llm_client

        client = create_llm_client("gemini", api_key="AIza-test", model="gemini-2.5-pro")
        assert client.config.model == "gemini-2.5-pro"

    def test_create_via_factory_applies_runtime_settings(self) -> None:
        from cemaf.llm.factories import create_llm_client

        client = create_llm_client(
            "gemini",
            api_key="AIza-test",
            temperature=0.2,
            max_tokens=123,
            top_p=0.8,
            timeout_seconds=12.0,
        )
        assert client.config.temperature == 0.2
        assert client.config.max_tokens == 123
        assert client.config.top_p == 0.8
        assert client.config.timeout_seconds == 12.0

    def test_create_via_factory_uses_google_api_key_without_vertex(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from cemaf.llm.factories import create_llm_client

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
        monkeypatch.setenv("GCP_PROJECT", "project-that-should-not-force-vertex")

        client = create_llm_client("gemini")
        url, headers = client._get_request_details(action="generateContent", cfg=client.config)

        assert "generativelanguage.googleapis.com" in url
        assert "key=google-key" in url
        assert "Authorization" not in headers

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cemaf.llm.factories import create_llm_client

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("VERTEX_PROJECT", raising=False)
        monkeypatch.delenv("GCP_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        with pytest.raises(ValueError, match="api_key required"):
            create_llm_client("gemini")


# ---------------------------------------------------------------------------
# Vertex AI Specific Tests
# ---------------------------------------------------------------------------


class TestVertexGemini:
    def test_vertex_initialization_explicit(self) -> None:
        client = GeminiClient(
            use_vertex=True,
            gcp_project="my-gcp-project",
            location="us-central1",
            access_token="fake-token",
        )
        assert client._use_vertex is True
        assert client._gcp_project == "my-gcp-project"
        assert client._location == "us-central1"
        assert client._access_token == "fake-token"

    def test_vertex_url_generation(self) -> None:
        client = GeminiClient(
            use_vertex=True,
            gcp_project="my-gcp-project",
            location="europe-west3",
            access_token="fake-token",
        )
        url, headers = client._get_request_details(action="generateContent", cfg=client.config)
        assert "europe-west3-aiplatform.googleapis.com" in url
        assert "projects/my-gcp-project" in url
        assert "locations/europe-west3" in url
        assert headers["Authorization"] == "Bearer fake-token"

    def test_vertex_streaming_url_generation(self) -> None:
        client = GeminiClient(
            use_vertex=True,
            gcp_project="my-gcp-project",
            location="us-central1",
            access_token="fake-token",
        )
        url, headers = client._get_request_details(action="streamGenerateContent", cfg=client.config)
        assert url.endswith("streamGenerateContent?alt=sse")

    def test_vertex_missing_project_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Clear environment variables
        for var in ["VERTEX_PROJECT", "GCP_PROJECT", "GOOGLE_CLOUD_PROJECT"]:
            monkeypatch.delenv(var, raising=False)

        client = GeminiClient(use_vertex=True, access_token="fake-token")
        with pytest.raises(ValueError, match="project ID is required"):
            client._get_request_details(action="generateContent", cfg=client.config)

    def test_vertex_missing_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Clear environment variables
        for var in [
            "VERTEX_ACCESS_TOKEN",
            "GCP_ACCESS_TOKEN",
            "GCLOUD_ACCESS_TOKEN",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
        ]:
            monkeypatch.delenv(var, raising=False)

        # Mock shutil.which to return None so gcloud CLI won't be tried
        with patch("shutil.which", return_value=None):
            client = GeminiClient(use_vertex=True, gcp_project="my-project")
            client._api_key = ""  # Ensure no fallback api_key is available
            with pytest.raises(ValueError, match="token or credentials are required"):
                client._get_request_details(action="generateContent", cfg=client.config)

    @pytest.mark.asyncio
    async def test_vertex_successful_completion(self) -> None:
        client = GeminiClient(
            use_vertex=True,
            gcp_project="my-project",
            access_token="fake-token",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello from Vertex Gemini!"}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 5,
                "candidatesTokenCount": 5,
            },
        }

        with patch("cemaf.llm.gemini.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await client.complete(messages=[Message.user(content="hi")])

        assert result.success
        assert result.content == "Hello from Vertex Gemini!"
        assert result.prompt_tokens == TokenCount(5)
        assert result.completion_tokens == TokenCount(5)
        assert result.provider is LLMProvider.VERTEX

    def test_create_vertex_via_factory(self) -> None:
        from cemaf.llm.factories import create_llm_client

        # Explicit "vertex" backend creation
        client = create_llm_client(
            "vertex",
            gcp_project="my-gcp-project",
            access_token="my-token",
            model="gemini-2.5-pro",
        )
        assert client._use_vertex is True
        assert client.config.model == "gemini-2.5-pro"
        assert client._gcp_project == "my-gcp-project"
        assert client._provider is LLMProvider.VERTEX
