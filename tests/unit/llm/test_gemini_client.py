"""Tests for GeminiClient — Google Gemini API adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cemaf.core.types import TokenCount
from cemaf.llm.gemini import GeminiClient, _messages_to_gemini, _tool_to_gemini
from cemaf.llm.protocols import (
    LLMClient,
    Message,
    ToolDefinition,
)

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


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestGeminiFactory:
    def test_create_via_factory(self) -> None:
        from cemaf.llm.factories import create_llm_client

        client = create_llm_client("gemini", api_key="AIza-test", model="gemini-2.5-pro")
        assert client.config.model == "gemini-2.5-pro"

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cemaf.llm.factories import create_llm_client

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="api_key required"):
            create_llm_client("gemini")
