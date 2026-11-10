"""Replay a real, captured model call through the production LLM adapter (SPEC-25).

The cassette in tests/cassettes/ was recorded from a local Ollama running qwen2.5:7b.
CI replays it, so the adapter's parsing is proven against the shape a real model
actually returns — not a hand-typed fixture.

Re-capture (needs `ollama serve` with qwen2.5:7b pulled):
    CEMAF_RECORD_CASSETTES=1 uv run pytest -q tests/integration/test_llm_recorded_replay.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from cemaf.llm.ollama import create_ollama_client
from cemaf.llm.protocols import Message, MessageRole

CASSETTE = Path(__file__).parent.parent / "cassettes" / "ollama_qwen2.5_7b_completion.json"
RECORDING = os.getenv("CEMAF_RECORD_CASSETTES") == "1"
MODEL = "qwen2.5:7b"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
PROMPT = "Name the capital of France in one word."
_BODY_FRAMING_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})


class RecordingTransport(httpx.AsyncBaseTransport):
    """Forwards to the real server and writes the exchange to a cassette."""

    def __init__(self, *, cassette: Path) -> None:
        self._cassette = cassette
        self._network = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._network.handle_async_request(request)
        body = await response.aread()
        self._cassette.write_text(
            json.dumps(
                {
                    "recorded_with": {"provider": "ollama", "model": MODEL},
                    "request": {
                        "method": request.method,
                        "path": request.url.path,
                        "json": json.loads(request.content),
                    },
                    "response": {"status": response.status_code, "json": json.loads(body)},
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        # aread() already decoded the body, so encoding/length headers no longer describe it.
        headers = {k: v for k, v in response.headers.items() if k.lower() not in _BODY_FRAMING_HEADERS}
        return httpx.Response(status_code=response.status_code, headers=headers, content=body)


class ReplayTransport(httpx.AsyncBaseTransport):
    """Answers with the recorded response, and only for the exact recorded request."""

    def __init__(self, *, cassette: Path) -> None:
        self._recording: dict[str, Any] = json.loads(cassette.read_text())

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        recorded = self._recording["request"]
        sent = {"method": request.method, "path": request.url.path, "json": json.loads(request.content)}
        if sent != recorded:
            raise AssertionError(
                f"request differs from the recording:\nsent:     {sent}\nrecorded: {recorded}"
            )
        return httpx.Response(
            status_code=self._recording["response"]["status"], json=self._recording["response"]["json"]
        )


def _transport() -> httpx.AsyncBaseTransport:
    if RECORDING:
        return RecordingTransport(cassette=CASSETTE)
    return ReplayTransport(cassette=CASSETTE)


def _client(*, transport: httpx.AsyncBaseTransport) -> Any:
    return create_ollama_client(
        model=MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0.0,
        max_tokens=16,
        transport=transport,
    )


@pytest.mark.asyncio
async def test_a_captured_ollama_completion_parses_through_the_real_adapter() -> None:
    """The production adapter turns the model's real response into a successful CompletionResult."""
    result = await _client(transport=_transport()).complete(
        messages=[Message(role=MessageRole.USER, content=PROMPT)],
    )
    recorded = json.loads(CASSETTE.read_text())["response"]["json"]

    assert result.success, result.error
    assert result.message is not None
    assert result.message.content == recorded["choices"][0]["message"]["content"]
    assert "paris" in result.message.content.lower()
    assert result.prompt_tokens == recorded["usage"]["prompt_tokens"] > 0
    assert result.completion_tokens == recorded["usage"]["completion_tokens"] > 0
    assert result.model == recorded["model"]


@pytest.mark.skipif(RECORDING, reason="only meaningful when replaying")
@pytest.mark.asyncio
async def test_a_changed_request_does_not_get_the_recorded_answer() -> None:
    """If the adapter's wire request drifts from the recording, the replay refuses instead of answering."""
    with pytest.raises(AssertionError, match="differs from the recording"):
        await ReplayTransport(cassette=CASSETTE).handle_async_request(
            httpx.Request(
                "POST",
                f"{OLLAMA_BASE_URL}/chat/completions",
                json={"model": MODEL, "messages": [{"role": "user", "content": "Something else"}]},
            )
        )


@pytest.mark.skipif(RECORDING, reason="only meaningful when replaying")
@pytest.mark.asyncio
async def test_the_ollama_registry_backend_sends_requests_through_the_transport() -> None:
    """create_llm_client("ollama", transport=...) must not fall back to the real network."""
    from cemaf.llm.factories import create_llm_client

    client = create_llm_client(
        provider="ollama",
        model=MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0.0,
        max_tokens=16,
        transport=ReplayTransport(cassette=CASSETTE),
    )
    result = await client.complete(messages=[Message(role=MessageRole.USER, content=PROMPT)])

    assert result.success, result.error
    assert "paris" in (result.message.content if result.message else "").lower()
