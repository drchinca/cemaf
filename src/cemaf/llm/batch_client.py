"""
Anthropic Message Batches API client for offline/high-volume processing.

Submits up to 10,000 requests per batch. Use for non-latency-sensitive
workloads — batch processing reduces cost by ~50% vs real-time API.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, cast

from cemaf.core.types import LLMProvider, TokenCount
from cemaf.core.utils import utc_now
from cemaf.llm.protocols import (
    CompletionResult,
    LLMConfig,
    Message,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)


@dataclass(frozen=True, slots=True)
class BatchRequest:
    """Single item to include in a batch submission."""

    custom_id: str
    messages: list[Message]
    tools: list[ToolDefinition] | None = None
    config_override: LLMConfig | None = None


class BatchStatus(StrEnum):
    """Lifecycle state of a submitted batch."""

    QUEUED = "queued"
    PROCESSING = "in_progress"
    COMPLETED = "ended"
    FAILED = "errored"


@dataclass(frozen=True, slots=True)
class BatchJob:
    """Summary of a submitted Anthropic batch."""

    id: str
    status: BatchStatus
    request_counts: dict[str, int]
    created_at: datetime


class BatchLLMClient:
    """
    LLMClient that routes requests through the Anthropic Message Batches API.

    Suitable for large-scale offline workloads (nightly jobs, dataset
    annotation, bulk evaluations). Not suitable for user-facing latency
    requirements — batches process asynchronously over minutes to hours.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        rate_limiter: Any | None = None,
    ) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "anthropic package required for BatchLLMClient. Install with: uv add anthropic"
            ) from exc
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._config = LLMConfig(model=model)
        self._rate_limiter = rate_limiter

    @property
    def config(self) -> LLMConfig:
        return self._config

    async def submit_batch(
        self,
        requests: list[BatchRequest],
        description: str | None = None,
    ) -> BatchJob:
        """Submit up to 10,000 requests as a single Anthropic batch."""
        from cemaf.llm.anthropic import _convert_messages

        formatted: list[dict[str, Any]] = []
        for req in requests:
            cfg = req.config_override or self._config
            system_msg, api_messages = _convert_messages(messages=req.messages)
            params: dict[str, Any] = {
                "model": cfg.model,
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "messages": api_messages or [{"role": "user", "content": ""}],
            }
            if system_msg:
                params["system"] = system_msg
            if req.tools:
                params["tools"] = [t.to_anthropic_format() for t in req.tools]

            formatted.append(
                {
                    "custom_id": req.custom_id,
                    "params": params,
                }
            )

        # Batch request params are assembled from provider-neutral CEMAF
        # models; contain the dynamic shape at the Anthropic SDK boundary.
        create_batch = cast(Any, self._client.beta.messages.batches.create)
        response = await create_batch(requests=formatted)

        return BatchJob(
            id=response.id,
            status=BatchStatus(response.processing_status),
            request_counts=dict(vars(response.request_counts)) if hasattr(response, "request_counts") else {},
            created_at=utc_now(),
        )

    async def poll_batch(
        self,
        batch_id: str,
        poll_interval_seconds: float = 30.0,
    ) -> AsyncIterator[tuple[str, CompletionResult]]:
        """Poll until the batch ends, then yield (custom_id, CompletionResult) pairs."""
        return self._poll_batch_impl(batch_id, poll_interval_seconds)

    async def _poll_batch_impl(
        self,
        batch_id: str,
        poll_interval_seconds: float,
    ) -> AsyncIterator[tuple[str, CompletionResult]]:
        while True:
            batch = await self._client.beta.messages.batches.retrieve(batch_id)
            if batch.processing_status == "ended":
                break
            await asyncio.sleep(poll_interval_seconds)

        async for result in await self._client.beta.messages.batches.results(batch_id):
            custom_id = result.custom_id
            if result.result.type == "succeeded":
                msg_result = result.result.message
                content_text = ""
                tool_calls: list[ToolCall] = []
                for block in msg_result.content:
                    if block.type == "text":
                        content_text += block.text
                    elif block.type == "tool_use":
                        tool_calls.append(
                            ToolCall(
                                id=block.id,
                                name=block.name,
                                arguments=block.input if isinstance(block.input, dict) else {},
                            )
                        )
                message = Message.assistant(content_text, tuple(tool_calls))
                completion = CompletionResult.ok(
                    message=message,
                    prompt_tokens=msg_result.usage.input_tokens,
                    completion_tokens=msg_result.usage.output_tokens,
                    model=msg_result.model,
                    finish_reason=msg_result.stop_reason or "end_turn",
                    finish_reason_native=msg_result.stop_reason or "end_turn",
                    provider=LLMProvider.ANTHROPIC,
                )
            else:
                error_detail = getattr(result.result, "error", None)
                error_msg = str(error_detail) if error_detail else "Batch request failed"
                completion = CompletionResult.fail(error=error_msg)

            yield custom_id, completion

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        """Submit a single-item batch and return the result synchronously."""
        batch_req = BatchRequest(
            custom_id="single",
            messages=messages,
            tools=tools,
            config_override=config_override,
        )
        job = await self.submit_batch([batch_req])
        async for custom_id, result in self._poll_batch_impl(job.id, poll_interval_seconds=5.0):
            if custom_id == "single":
                return result
        return CompletionResult.fail(error="Batch completed but result not found")

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        raise NotImplementedError("BatchLLMClient does not support streaming — use complete()")

    def count_tokens(self, text: str) -> TokenCount:
        if not text:
            return TokenCount(0)
        return TokenCount(max(1, round(len(text) / 3.5)))

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        import json as _json

        total = 0
        for msg in messages:
            total += 4
            if isinstance(msg.content, str):
                total += self.count_tokens(msg.content)
            else:
                total += self.count_tokens(_json.dumps(msg.content))
        return TokenCount(total)

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        raise NotImplementedError(
            "BatchLLMClient does not implement exact token counting — use AnthropicLLMClient"
        )
