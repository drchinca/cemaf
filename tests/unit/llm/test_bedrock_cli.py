"""Tests for the AWS CLI Bedrock client."""

from __future__ import annotations

import json

import pytest

from cemaf.llm.bedrock_cli import BedrockCliLLMClient
from cemaf.llm.factories import create_llm_client
from cemaf.llm.protocols import LLMClient, Message, MessageRole


async def _success_runner(args: list[str]) -> tuple[int, str, str]:
    out_path = args[-1]
    payload = {
        "model": "claude-sonnet-4-6",
        "content": [{"type": "text", "text": '{"ok": true}'}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return 0, "", ""


async def _error_runner(args: list[str]) -> tuple[int, str, str]:
    return 1, "", "AccessDenied"


@pytest.mark.asyncio
async def test_bedrock_complete_success() -> None:
    client = BedrockCliLLMClient(runner=_success_runner)
    result = await client.complete(
        messages=[
            Message(role=MessageRole.SYSTEM, content="Return JSON only."),
            Message(role=MessageRole.USER, content="Say ok."),
        ]
    )

    assert result.success is True
    assert result.content == '{"ok": true}'
    assert result.model == "claude-sonnet-4-6"
    assert int(result.prompt_tokens) == 10
    assert int(result.completion_tokens) == 5


@pytest.mark.asyncio
async def test_bedrock_complete_failure() -> None:
    client = BedrockCliLLMClient(runner=_error_runner)
    result = await client.complete(messages=[Message(role=MessageRole.USER, content="x")])
    assert result.success is False
    assert "AccessDenied" in (result.error or "")


def test_bedrock_factory_creates_llm_client() -> None:
    client = create_llm_client("bedrock")

    assert isinstance(client, LLMClient)
    assert isinstance(client, BedrockCliLLMClient)
