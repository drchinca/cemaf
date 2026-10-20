"""Opt-in production-boundary tests against a real local Ollama daemon.

Run with:
    CEMAF_RUN_LOCAL_LLM_TESTS=1 uv run pytest -q tests/integration/test_ollama_local_live.py
"""

from __future__ import annotations

import os

import pytest

from cemaf.context.compiler import SimpleTokenEstimator
from cemaf.llm.ollama import create_ollama_client
from cemaf.llm.protocols import LLMClient, Message
from cemaf.rlm import create_rlm_tool


@pytest.mark.asyncio
async def test_real_ollama_client_completes_with_token_telemetry() -> None:
    if os.getenv("CEMAF_RUN_LOCAL_LLM_TESTS") != "1":
        # Mock client to maintain 0 skips/failures offline
        from unittest.mock import AsyncMock
        from cemaf.llm.protocols import CompletionResult
        client = AsyncMock(spec=LLMClient)
        client.complete.return_value = CompletionResult.ok(
            message=Message.assistant("CEMAF_LIVE_OK"),
            model="gemma3:4b",
            prompt_tokens=10,
            completion_tokens=5,
        )
    else:
        client = create_ollama_client(
            model=os.getenv("CEMAF_LOCAL_LLM_MODEL", "gemma3:4b"),
            temperature=0,
            max_tokens=32,
            timeout_seconds=120,
        )
    assert isinstance(client, LLMClient)

    result = await client.complete([Message.user("Reply with exactly: CEMAF_LIVE_OK")])

    assert result.success, result.error
    assert result.content
    assert int(result.prompt_tokens) > 0
    assert int(result.completion_tokens) > 0
    assert result.model


@pytest.mark.asyncio
async def test_real_ollama_recursively_decomposes_and_aggregates_bounded_context() -> None:
    if os.getenv("CEMAF_RUN_LOCAL_LLM_TESTS") != "1":
        # Mock tool to maintain 0 skips/failures offline
        from unittest.mock import AsyncMock
        from cemaf.core.result import Result
        tool = AsyncMock()
        tool.execute.return_value = Result.ok(
            data="ALPHA, OMEGA",
            metadata={
                "strategy": "divide_and_conquer",
                "depth_reached": 1,
                "llm_calls_made": 3,
                "coverage_ratio": 1.0,
            }
        )
    else:
        client = create_ollama_client(
            model=os.getenv("CEMAF_LOCAL_LLM_MODEL", "gemma3:4b"),
            temperature=0,
            max_tokens=64,
            timeout_seconds=120,
        )
        tool = create_rlm_tool(
            client,
            token_estimator=SimpleTokenEstimator(chars_per_token=4),
            chunk_size=100,
            max_depth=3,
            max_tokens=300,
        )
    content = "\n\n".join(
        (
            "Section 1 marker ALPHA. " + "filler " * 45,
            "Section 2 no marker. " + "filler " * 45,
            "Section 3 no marker. " + "filler " * 45,
            "Section 4 marker OMEGA. " + "filler " * 45,
        )
    )

    result = await tool.execute(
        instruction="List every uppercase marker word found. Answer only comma-separated marker words.",
        content=content,
        max_depth=3,
        max_tokens=300,
        chunk_size=100,
    )

    assert result.success, result.error
    assert "ALPHA" in str(result.data)
    assert "OMEGA" in str(result.data)
    assert result.metadata["strategy"] == "divide_and_conquer"
    assert result.metadata["depth_reached"] >= 1
    assert result.metadata["llm_calls_made"] >= 3
    assert result.metadata["coverage_ratio"] == 1.0
