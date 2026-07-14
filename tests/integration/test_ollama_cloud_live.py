"""Integration test for the ollama-cloud provider endpoint shape.

Uses a fake OpenAI-compatible HTTP endpoint so the default suite proves factory
wiring, URL construction, auth headers, payload shape, and response parsing
without requiring external credentials.
"""

from __future__ import annotations

from typing import Any

import pytest

from cemaf.llm.factories import DEFAULT_OLLAMA_CLOUD_MODEL, create_llm_client
from cemaf.llm.protocols import Message


class _FakeResponse:
    status_code = 200
    text = ""

    def json(self) -> dict[str, Any]:
        return {
            "model": DEFAULT_OLLAMA_CLOUD_MODEL,
            "choices": [
                {
                    "message": {"role": "assistant", "content": "pong"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }


class _FakeAsyncClient:
    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout
        self.requests: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        self.requests.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse()


@pytest.mark.asyncio
async def test_ollama_cloud_completes_against_endpoint_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeAsyncClient(timeout=120.0)
    monkeypatch.setattr(
        "cemaf.llm.openai_compat.httpx.AsyncClient",
        lambda *, timeout: fake_client,
    )

    client = create_llm_client(
        provider="ollama-cloud",
        api_key="test-ollama-key",
        model=DEFAULT_OLLAMA_CLOUD_MODEL,
    )
    response = await client.complete(messages=[Message.user(content="Reply with the single word: pong")])

    assert response.success
    assert response.content == "pong"
    assert response.model == DEFAULT_OLLAMA_CLOUD_MODEL
    assert fake_client.requests == [
        {
            "url": "https://ollama.com/v1/chat/completions",
            "json": {
                "model": DEFAULT_OLLAMA_CLOUD_MODEL,
                "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
                "temperature": 0.7,
                "max_tokens": 4096,
                "top_p": 1.0,
            },
            "headers": {
                "Content-Type": "application/json",
                "Authorization": "Bearer test-ollama-key",
            },
        }
    ]
