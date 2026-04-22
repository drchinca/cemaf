"""Instrumented LLM client that auto-records every call into RunLogger."""

import time
from collections.abc import AsyncIterator
from typing import Any

from cemaf.core.types import TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    Message,
    StreamChunk,
    ToolDefinition,
)
from cemaf.observability.run_logger import LLMCall, RunLogger
from cemaf.resilience.retry import RetryPolicy


class InstrumentedLLMClient:
    """Wraps any LLMClient and auto-records every complete()/stream() call into a RunLogger."""

    def __init__(
        self,
        client: LLMClient,
        run_logger: RunLogger,
        node_id: str | None = None,
        agent_id: str | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._client = client
        self._run_logger = run_logger
        self._node_id = node_id
        self._agent_id = agent_id
        self._retry_policy = retry_policy

    @property
    def config(self) -> LLMConfig:
        """Delegate to inner client."""
        return self._client.config

    async def _do_complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        config_override: LLMConfig | None,
    ) -> CompletionResult:
        """Execute a single completion call against the inner client."""
        return await self._client.complete(
            messages=messages,
            tools=tools,
            config_override=config_override,
        )

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        """Complete and record the LLM call, with optional retry and error telemetry."""
        start_ns = time.perf_counter_ns()

        try:
            if self._retry_policy:
                retry_result = await self._retry_policy.execute(
                    self._do_complete,
                    messages,
                    tools,
                    config_override,
                )
                if retry_result.error:
                    raise retry_result.error
                result: CompletionResult = retry_result.result
            else:
                result = await self._do_complete(
                    messages=messages,
                    tools=tools,
                    config_override=config_override,
                )
        except Exception as exc:
            duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            llm_call = LLMCall(
                model=self.config.model,
                input_messages=[_message_to_dict(msg=m) for m in messages],
                output="",
                duration_ms=duration_ms,
                node_id=self._node_id,
                agent_id=self._agent_id,
                error=str(exc),
            )
            self._run_logger.record_llm_call(call=llm_call)
            raise

        duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        llm_call = LLMCall(
            model=result.model or self.config.model,
            input_messages=[_message_to_dict(msg=m) for m in messages],
            output=str(result.content) if result.success else "",
            input_tokens=int(result.prompt_tokens),
            output_tokens=int(result.completion_tokens),
            duration_ms=duration_ms,
            node_id=self._node_id,
            agent_id=self._agent_id,
        )

        self._run_logger.record_llm_call(call=llm_call)

        return result

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream and record the LLM call, with error telemetry on failure."""
        start_ns = time.perf_counter_ns()
        accumulated = ""
        prompt_tokens = 0
        completion_tokens = 0

        try:
            stream_result = self._client.stream(
                messages=messages,
                tools=tools,
                config_override=config_override,
            )
            # Handle both async generators and coroutines returning AsyncIterator
            aiter: AsyncIterator[StreamChunk] = (
                stream_result if hasattr(stream_result, "__aiter__") else await stream_result  # type: ignore[assignment]
            )
            async for chunk in aiter:
                accumulated = chunk.accumulated_content or accumulated + chunk.content
                prompt_tokens = int(chunk.prompt_tokens) if chunk.prompt_tokens else prompt_tokens
                completion_tokens = (
                    int(chunk.completion_tokens) if chunk.completion_tokens else completion_tokens
                )
                yield chunk
        except Exception as exc:
            duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            llm_call = LLMCall(
                model=self.config.model,
                input_messages=[_message_to_dict(msg=m) for m in messages],
                output=accumulated,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                duration_ms=duration_ms,
                node_id=self._node_id,
                agent_id=self._agent_id,
                error=str(exc),
            )
            self._run_logger.record_llm_call(call=llm_call)
            raise

        duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        llm_call = LLMCall(
            model=self.config.model,
            input_messages=[_message_to_dict(msg=m) for m in messages],
            output=accumulated,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            duration_ms=duration_ms,
            node_id=self._node_id,
            agent_id=self._agent_id,
        )

        self._run_logger.record_llm_call(call=llm_call)

    def count_tokens(self, text: str) -> TokenCount:
        """Delegate to inner client."""
        return self._client.count_tokens(text=text)

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        """Delegate to inner client."""
        return self._client.count_messages_tokens(messages=messages)

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        """Delegate to inner client's exact counter."""
        return await self._client.count_tokens_exact(messages=messages, tools=tools)


def _message_to_dict(msg: Message) -> dict[str, Any]:
    """Serialize a Message for the LLMCall record."""
    return {
        "role": msg.role.value,
        "content": msg.content,
    }
