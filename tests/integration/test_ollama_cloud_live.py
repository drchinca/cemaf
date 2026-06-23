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


# Free-tier reasoning models occasionally return a reasoning-only turn with empty
# content under load. That is a model quirk, not an adapter fault, so the live
# smoke retries a couple times before asserting — the DAG-level test
# (test_ollama_cloud_dag.py) is the deterministic provider proof.
_MAX_ATTEMPTS = 3


@pytest.mark.asyncio
@pytest.mark.parametrize("model", FREE_TIER_MODELS)
async def test_ollama_cloud_completes_against_real_endpoint(model: str) -> None:
    client = create_llm_client(provider="ollama-cloud", model=model)
    text = ""
    for _ in range(_MAX_ATTEMPTS):
        response = await client.complete(messages=[Message.user(content="Reply with the single word: pong")])
        text = getattr(response, "content", None) or getattr(response, "message", None) or ""
        if text:
            break
    assert text, f"empty response from {model} after {_MAX_ATTEMPTS} attempts"
    assert isinstance(text, str)
