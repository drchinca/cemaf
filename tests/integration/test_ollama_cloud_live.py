"""Live integration test for the ollama-cloud provider.

Skipped unless OLLAMA_CLOUD_API_KEY is set. Hits the real
https://ollama.com/v1 endpoint with a free-tier model. Proves the
factory wiring + OpenAI-compat client + auth header round-trip end-to-end.
"""

from __future__ import annotations

import os

import pytest

from cemaf.llm.factories import create_llm_client
from cemaf.llm.protocols import Message

pytestmark = pytest.mark.skipif(
    not os.getenv("OLLAMA_CLOUD_API_KEY"),
    reason="OLLAMA_CLOUD_API_KEY not set; skipping live ollama-cloud test",
)

FREE_TIER_MODELS = [
    "gpt-oss:20b-cloud",
    "gpt-oss:120b-cloud",
    "qwen3-coder:480b-cloud",
    "minimax-m2.1:cloud",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("model", FREE_TIER_MODELS)
async def test_ollama_cloud_completes_against_real_endpoint(model: str) -> None:
    client = create_llm_client(provider="ollama-cloud", model=model)
    response = await client.complete(messages=[Message.user(content="Reply with the single word: pong")])
    text = getattr(response, "content", None) or getattr(response, "message", None) or ""
    assert text, f"empty response from {model}"
    assert isinstance(text, str)
