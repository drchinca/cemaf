"""Instrumented LLM client that auto-records every call into RunLogger."""

import copy
import time
from collections.abc import AsyncIterator, Awaitable
from dataclasses import asdict
from typing import Any, cast

from cemaf.core.types import TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    Message,
    StreamChunk,
    ToolDefinition,
)
from cemaf.observability.budget_guard import check_runtime_budget, record_runtime_usage
from cemaf.observability.cost_tracking import ModelPricingRegistry
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
        *,
        fidelity: object | None = None,
        token_budget: object | None = None,
        correlation_id: str | None = None,
    ) -> CompletionResult:
        """Execute a single completion call against the inner client."""
        return await self._client.complete(
            messages=messages,
            tools=tools,
            config_override=config_override,
            fidelity=fidelity,
            token_budget=token_budget,
            correlation_id=correlation_id,
        )

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
        """Complete and record the LLM call, with optional retry and error telemetry."""
        check_runtime_budget()
        recorded_messages = copy.deepcopy([m.to_dict() for m in messages])
        recorded_tools = tuple(copy.deepcopy(asdict(tool)) for tool in tools or [])
        recorded_config = (config_override or self.config).model_dump(mode="json")
        start_ns = time.perf_counter_ns()

        try:
            if self._retry_policy:
                retry_result = await self._retry_policy.execute(
                    self._do_complete,
                    messages,
                    tools,
                    config_override,
                    fidelity=fidelity,
                    token_budget=token_budget,
                    correlation_id=correlation_id,
                )
                if retry_result.error:
                    raise retry_result.error
                result: CompletionResult = retry_result.result
            else:
                result = await self._do_complete(
                    messages=messages,
                    tools=tools,
                    config_override=config_override,
                    fidelity=fidelity,
                    token_budget=token_budget,
                    correlation_id=correlation_id,
                )
        except Exception as exc:
            duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            llm_call = LLMCall(
                model=(config_override or self.config).model,
                input_messages=recorded_messages,
                output="",
                duration_ms=duration_ms,
                correlation_id=correlation_id or "",
                node_id=self._node_id,
                agent_id=self._agent_id,
                error=str(exc),
                input_tools=recorded_tools,
                model_config=recorded_config,
            )
            self._run_logger.record_llm_call(call=llm_call)
            raise

        duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        model_id = result.model or (config_override or self.config).model
        prompt_tokens = int(result.prompt_tokens)
        completion_tokens = int(result.completion_tokens)
        llm_call = LLMCall(
            model=model_id,
            input_messages=recorded_messages,
            output=str(result.content) if result.success else "",
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            duration_ms=duration_ms,
            correlation_id=correlation_id or "",
            node_id=self._node_id,
            agent_id=self._agent_id,
            cost_usd=ModelPricingRegistry.compute_cost_usd(model_id, prompt_tokens, completion_tokens),
            error=result.error if not result.success else None,
            input_tools=recorded_tools,
            model_config=recorded_config,
            evidence_id=str(result.message.metadata["evidence_id"])
            if result.message and "evidence_id" in result.message.metadata
            else None,
            request_id=str(result.message.metadata["request_id"])
            if result.message and "request_id" in result.message.metadata
            else None,
        )

        self._run_logger.record_llm_call(call=llm_call)

        record_runtime_usage(tokens=prompt_tokens + completion_tokens, cost_usd=llm_call.cost_usd)

        return result

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream and record the LLM call, with error telemetry on failure."""
        check_runtime_budget()
        recorded_messages = copy.deepcopy([m.to_dict() for m in messages])
        recorded_tools = tuple(copy.deepcopy(asdict(tool)) for tool in tools or [])
        recorded_config = (config_override or self.config).model_dump(mode="json")
        start_ns = time.perf_counter_ns()
        accumulated = ""
        prompt_tokens = 0
        completion_tokens = 0

        try:
            stream_result: Any = self._client.stream(
                messages=messages,
                tools=tools,
                config_override=config_override,
            )
            # Handle both async generators and coroutines returning AsyncIterator
            aiter: AsyncIterator[StreamChunk] = (
                cast(AsyncIterator[StreamChunk], stream_result)
                if hasattr(stream_result, "__aiter__")
                else await cast(Awaitable[AsyncIterator[StreamChunk]], stream_result)
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
                model=(config_override or self.config).model,
                input_messages=recorded_messages,
                output=accumulated,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                duration_ms=duration_ms,
                node_id=self._node_id,
                agent_id=self._agent_id,
                error=str(exc),
                input_tools=recorded_tools,
                model_config=recorded_config,
                cost_usd=ModelPricingRegistry.compute_cost_usd(
                    (config_override or self.config).model,
                    prompt_tokens,
                    completion_tokens,
                ),
            )
            self._run_logger.record_llm_call(call=llm_call)
            record_runtime_usage(tokens=prompt_tokens + completion_tokens, cost_usd=llm_call.cost_usd)
            raise

        duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        model_id = (config_override or self.config).model
        llm_call = LLMCall(
            model=model_id,
            input_messages=recorded_messages,
            output=accumulated,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            duration_ms=duration_ms,
            node_id=self._node_id,
            agent_id=self._agent_id,
            input_tools=recorded_tools,
            model_config=recorded_config,
            cost_usd=ModelPricingRegistry.compute_cost_usd(model_id, prompt_tokens, completion_tokens),
        )

        self._run_logger.record_llm_call(call=llm_call)
        record_runtime_usage(tokens=prompt_tokens + completion_tokens, cost_usd=llm_call.cost_usd)

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
    return msg.to_dict()
