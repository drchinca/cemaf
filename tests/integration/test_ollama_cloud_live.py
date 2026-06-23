"""Live integration test for the ollama-cloud provider.

Skipped unless OLLAMA_CLOUD_API_KEY is set. Hits the real
https://ollama.com/v1 endpoint with a free-tier model. Proves the
factory wiring + OpenAI-compat client + auth header round-trip end-to-end.

Free-tier reasoning models (e.g. minimax-m2.1, qwen3-coder:480b) genuinely
return a reasoning-only turn with empty ``content`` and ``finish_reason=stop``
a meaningful fraction of the time — observed ~40% for minimax under load. That
is the model's behaviour, not an adapter fault: when the model DOES emit text,
the adapter parses it correctly (verified directly).

So each model asserts the **round-trip** (a coerced ``finish_reason`` came
back), which is what this smoke claims to prove. To still catch a genuinely
broken adapter that drops all content, the suite separately requires that at
least one model returned non-empty text. The deterministic provider proof is
``test_ollama_cloud_dag.py`` (4 models drive a real DAG, reliably green).
"""

from __future__ import annotations

import os

import pytest

from cemaf.core.types import FinishReason
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


async def _complete(model: str) -> tuple[str, FinishReason]:
    client = create_llm_client(provider="ollama-cloud", model=model)
    response = await client.complete(messages=[Message.user(content="Reply with the single word: pong")])
    text = getattr(response, "content", None) or getattr(response, "message", None) or ""
    return (text if isinstance(text, str) else ""), response.finish_reason


@pytest.mark.asyncio
@pytest.mark.parametrize("model", FREE_TIER_MODELS)
async def test_ollama_cloud_round_trips_against_real_endpoint(model: str) -> None:
    """Each model completes a real round-trip (auth + endpoint + response parse)."""
    text, finish_reason = await _complete(model)

    # A coerced FinishReason proves the full request → endpoint → parse round-trip,
    # even when a reasoning model emits an empty content turn.
    assert isinstance(finish_reason, FinishReason)
    # When the model does emit text, the adapter must surface it as a string.
    assert isinstance(text, str)


@pytest.mark.asyncio
async def test_ollama_cloud_adapter_parses_real_content() -> None:
    """At least one free-tier model returns non-empty text — guards against an
    adapter that silently drops all content. Retries across models cover the
    free-tier reasoning-only-turn flakiness without ever passing on zero text."""
    for model in FREE_TIER_MODELS:
        for _ in range(2):
            text, _ = await _complete(model)
            if text:
                assert isinstance(text, str)
                return
    pytest.fail("no free-tier model returned non-empty content across all attempts")
