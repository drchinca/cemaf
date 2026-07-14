"""Opt-in live provider contract tests with bounded token/cost exposure.

Run with:
    CEMAF_RUN_CLOUD_LLM_TESTS=1 uv run pytest -q tests/integration/test_cloud_llm_live.py
"""

from __future__ import annotations

import os

import pytest

from cemaf.llm.factories import create_llm_client
from cemaf.llm.protocols import LLMClient, Message

pytestmark = pytest.mark.skipif(
    os.getenv("CEMAF_RUN_CLOUD_LLM_TESTS") != "1",
    reason="set CEMAF_RUN_CLOUD_LLM_TESTS=1 to execute bounded live-provider proof",
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model", "credential"),
    (
        ("openai", "gpt-4o-mini", "OPENAI_API_KEY"),
        ("gemini", "gemini-2.5-flash", "GEMINI_API_KEY"),
    ),
)
async def test_live_cloud_provider_satisfies_protocol_and_returns_usage(
    provider: str,
    model: str,
    credential: str,
) -> None:
    api_key = os.getenv(credential)
    if not api_key:
        pytest.skip(f"{credential} is not configured")
    client = create_llm_client(provider, api_key=api_key, model=model)
    assert isinstance(client, LLMClient)

    result = await client.complete([Message.user("Reply with exactly CEMAF_PROVIDER_OK")])

    assert result.success, result.error
    assert result.content
    assert result.model
    assert int(result.prompt_tokens) > 0
    assert int(result.completion_tokens) > 0
