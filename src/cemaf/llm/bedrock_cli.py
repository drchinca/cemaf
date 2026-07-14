"""AWS Bedrock text LLM client via the AWS CLI.

This keeps CEMAF compatible with AWS SSO sessions already configured on the
machine without introducing a hard dependency on boto3/botocore.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from time import perf_counter
from typing import Any

from cemaf.core.types import LLMProvider, TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMConfig,
    Message,
    MessageRole,
    StreamChunk,
    ToolCall,
    ToolDefinition,
    coerce_finish_reason,
)

_BEDROCK_ANTHROPIC_VERSION = "bedrock-2023-05-31"


class BedrockCliLLMClient:
    """LLM client that invokes Bedrock through `aws bedrock-runtime invoke-model`."""

    def __init__(
        self,
        *,
        model: str = "global.anthropic.claude-sonnet-4-6",
        region: str = "us-east-1",
        profile: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout_seconds: float = 120.0,
        runner: Callable[[list[str]], Awaitable[tuple[int, str, str]]] | None = None,
    ) -> None:
        self._config = LLMConfig(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        self._region = region
        self._profile = profile
        self._runner = runner

    @property
    def config(self) -> LLMConfig:
        return self._config

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
        *,
        fidelity: object | None = None,
        token_budget: object | None = None,
        correlation_id: str | None = None,
    ) -> CompletionResult:
        del tools  # AWS CLI invoke-model path is text-only here.
        del fidelity, token_budget, correlation_id
        cfg = config_override or self._config

        payload = {
            "anthropic_version": _BEDROCK_ANTHROPIC_VERSION,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "messages": _messages_to_bedrock(messages),
        }

        start = perf_counter()
        try:
            response = await self._invoke_model(model=cfg.model, payload=payload)
        except Exception as exc:
            return CompletionResult.fail(error=f"Bedrock CLI error: {exc}")
        latency_ms = (perf_counter() - start) * 1000

        content, tool_calls = _parse_bedrock_content(response)
        usage = response.get("usage", {})

        return CompletionResult.ok(
            message=Message(
                role=MessageRole.ASSISTANT,
                content=content,
                tool_calls=tuple(tool_calls),
            ),
            prompt_tokens=int(usage.get("input_tokens", 0)),
            completion_tokens=int(usage.get("output_tokens", 0)),
            model=str(response.get("model", cfg.model)),
            finish_reason=response.get("stop_reason", "stop"),
            finish_reason_native=str(response.get("stop_reason", "")),
            provider=LLMProvider.BEDROCK,
            latency_ms=latency_ms,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        result = await self.complete(
            messages=messages,
            tools=tools,
            config_override=config_override,
        )
        if not result.success:
            yield StreamChunk(
                content="",
                accumulated_content="",
                is_final=True,
                finish_reason=coerce_finish_reason("error"),
            )
            return

        yield StreamChunk(
            content=str(result.content),
            accumulated_content=str(result.content),
        )
        yield StreamChunk(
            content="",
            accumulated_content=str(result.content),
            tool_calls=result.tool_calls,
            is_final=True,
            finish_reason=result.finish_reason,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )

    def count_tokens(self, text: str) -> TokenCount:
        return TokenCount(max(1, round(len(text) / 4))) if text else TokenCount(0)

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        total = sum(self.count_tokens(text=str(m.content)) + 4 for m in messages)
        return TokenCount(max(1, total))

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        del tools
        return self.count_messages_tokens(messages)

    async def _invoke_model(self, *, model: str, payload: dict[str, object]) -> dict[str, Any]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as req_file:
            json.dump(payload, req_file)
            req_path = Path(req_file.name)
        with tempfile.NamedTemporaryFile("w+b", suffix=".json", delete=False) as resp_file:
            resp_path = Path(resp_file.name)

        try:
            args = [
                "aws",
                "bedrock-runtime",
                "invoke-model",
                "--region",
                self._region,
                "--model-id",
                model,
                "--body",
                f"fileb://{req_path}",
                "--content-type",
                "application/json",
                "--accept",
                "application/json",
                str(resp_path),
            ]
            if self._profile:
                args[1:1] = ["--profile", self._profile]

            if self._runner is not None:
                code, stdout, stderr = await self._runner(args)
            else:
                code, stdout, stderr = await _run_subprocess(args)

            if code != 0:
                error_text = stderr.strip() or stdout.strip() or f"aws exited with code {code}"
                raise RuntimeError(error_text)

            try:
                parsed = json.loads(resp_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Bedrock response payload was not valid JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise RuntimeError("Bedrock response payload was not a JSON object")
            return parsed
        finally:
            req_path.unlink(missing_ok=True)
            resp_path.unlink(missing_ok=True)


async def _run_subprocess(args: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )
    stdout_b, stderr_b = await proc.communicate()
    return int(proc.returncode or 0), stdout_b.decode(), stderr_b.decode()


def _messages_to_bedrock(messages: list[Message]) -> list[dict[str, object]]:
    system_parts: list[str] = []
    contents: list[dict[str, object]] = []

    for msg in messages:
        if msg.role == MessageRole.SYSTEM:
            system_parts.append(str(msg.content))
            continue

        role = "user" if msg.role == MessageRole.USER else "assistant"
        text = str(msg.content)
        if role == "user" and system_parts:
            text = "\n".join(system_parts) + "\n\n" + text
            system_parts = []
        contents.append(
            {
                "role": role,
                "content": [{"type": "text", "text": text}],
            }
        )

    if not contents and system_parts:
        contents.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": "\n".join(system_parts)}],
            }
        )
    return contents


def _parse_bedrock_content(response: dict[str, Any]) -> tuple[str, list[ToolCall]]:
    blocks = response.get("content", []) or []
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text_parts.append(str(block.get("text", "")))
        if block.get("type") == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=str(block.get("id", f"tool_{idx}")),
                    name=str(block.get("name", "")),
                    arguments=block.get("input", {}) if isinstance(block.get("input"), dict) else {},
                )
            )

    return "".join(text_parts), tool_calls
