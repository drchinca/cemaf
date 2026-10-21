"""Full-request token preflight with explicitly labeled counting guarantees."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from cemaf.context.manifest import ImmutableModel, canonical_json
from cemaf.llm.protocols import LLMClient, LLMConfig, Message, ToolDefinition
from cemaf.observability.budget_guard import BudgetExhaustedError


class ProviderPreflightError(RuntimeError):
    """Public error omitting credential-bearing URLs and provider response bodies."""

    def __init__(self, *, provider: str, status_code: int | None = None) -> None:
        self.provider, self.status_code = provider, status_code
        super().__init__(f"{provider} request preflight failed (HTTP {status_code or 'unavailable'})")


class RequestTokenCount(ImmutableModel):
    input_tokens: int = Field(ge=0)
    method: str
    counter_version: str
    exact: bool


class PreflightReceipt(ImmutableModel):
    count: RequestTokenCount
    estimated_input_tokens: int = Field(ge=0)
    context_window: int = Field(gt=0)
    reserved_output_tokens: int = Field(gt=0)
    provider_reported_input_tokens: int | None = Field(default=None, ge=0)


@runtime_checkable
class RequestTokenCounter(Protocol):
    async def count_request(
        self, *, messages: list[Message], tools: list[ToolDefinition], config: LLMConfig
    ) -> RequestTokenCount: ...


class LLMRequestTokenCounter:
    """Adapt the public counter; exactness must be certified by the caller.

    Several adapters use local estimates behind count_tokens_exact. The default
    therefore makes no exactness claim. An uncertified counter cannot pass a
    preflight configured with require_exact=True.
    """

    def __init__(self, client: LLMClient, *, exact: bool = False, version: str = "adapter-v1") -> None:
        self.client, self.exact, self.version = client, exact, version

    async def count_request(
        self,
        *,
        messages: list[Message],
        tools: list[ToolDefinition],
        config: LLMConfig,
    ) -> RequestTokenCount:
        if config.model != self.client.config.model:
            raise ValueError("Token counter model differs from requested model")
        tokens = await self.client.count_tokens_exact(messages=messages, tools=tools or None)
        return RequestTokenCount(
            input_tokens=int(tokens),
            method="llm.count_tokens_exact",
            counter_version=self.version,
            exact=self.exact,
        )


async def preflight_request(
    *,
    client: LLMClient,
    counter: RequestTokenCounter,
    messages: list[Message],
    tools: list[ToolDefinition] | None,
    config: LLMConfig,
    context_window: int,
    require_exact: bool = True,
) -> PreflightReceipt:
    """Count all messages/tools/framing through a provider-specific port before dispatch."""
    if context_window <= 0 or config.max_tokens <= 0 or config.max_tokens >= context_window:
        raise BudgetExhaustedError("No input allowance remains after the output reservation")
    count = await counter.count_request(messages=messages, tools=tools or [], config=config)
    if require_exact and not count.exact:
        raise ValueError("This request requires a certified provider-specific token counter")
    if count.input_tokens + config.max_tokens > context_window:
        raise BudgetExhaustedError("Complete rendered request exceeds the model context window")
    estimate = int(client.count_messages_tokens(messages))
    if tools:
        estimate += int(client.count_tokens(canonical_json([tool.to_openai_format() for tool in tools])))
    return PreflightReceipt(
        count=count,
        estimated_input_tokens=estimate,
        context_window=context_window,
        reserved_output_tokens=config.max_tokens,
    )
