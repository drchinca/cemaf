"""Integration test for the ollama-cloud provider endpoint shape.

Uses httpx.MockTransport as the OpenAI-compatible endpoint so the default suite proves factory
wiring, URL construction, auth headers, payload shape, and response parsing
without requiring external credentials.
"""

from __future__ import annotations

import json

import httpx
import pytest

from cemaf.llm.factories import DEFAULT_OLLAMA_CLOUD_MODEL, create_llm_client
from cemaf.llm.protocols import Message

_PONG_RESPONSE = {
    "model": DEFAULT_OLLAMA_CLOUD_MODEL,
    "choices": [{"message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 1},
}


@pytest.mark.asyncio
async def test_ollama_cloud_completes_against_endpoint_shape() -> None:
    sent: list[httpx.Request] = []

    def endpoint(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=_PONG_RESPONSE)

    client = create_llm_client(
        provider="ollama-cloud",
        api_key="test-ollama-key",
        model=DEFAULT_OLLAMA_CLOUD_MODEL,
        transport=httpx.MockTransport(endpoint),
    )
    response = await client.complete(messages=[Message.user(content="Reply with the single word: pong")])

    assert response.success
    assert response.content == "pong"
    assert response.model == DEFAULT_OLLAMA_CLOUD_MODEL
    assert len(sent) == 1
    assert str(sent[0].url) == "https://ollama.com/v1/chat/completions"
    assert json.loads(sent[0].content) == {
        "model": DEFAULT_OLLAMA_CLOUD_MODEL,
        "messages": [{"role": "user", "content": "Reply with the single word: pong"}],
        "temperature": 0.7,
        "max_tokens": 4096,
        "top_p": 1.0,
    }
    assert sent[0].headers["Content-Type"] == "application/json"
    assert sent[0].headers["Authorization"] == "Bearer test-ollama-key"
