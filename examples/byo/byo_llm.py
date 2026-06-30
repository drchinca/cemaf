"""BYO LLM — drive your own model behind CEMAF's LLMClient protocol.

Use-case: your company exposes an internal LLM gateway with a fixed contract.
You do not need an adapter SDK — implement the `LLMClient` protocol and CEMAF
drives it. The protocol IS the only integration contract.

Best practice shown: implement the FULL protocol signature (including the
keyword-only params real call sites pass), prove conformance with
`isinstance`, then wire through `RuntimeServices` — never special-case the client.

Usage:
    uv run python examples/byo/byo_llm.py
"""

import asyncio
from collections.abc import AsyncIterator

from cemaf.core.types import FinishReason, TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    Message,
    StreamChunk,
    ToolDefinition,
)


class EchoGatewayClient:
    """A protocol-correct LLMClient backed by a trivial internal 'gateway'."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self._config = config or LLMConfig(model="internal-gateway")

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
        last_user = next((str(m.content) for m in reversed(messages) if m.role.value == "user"), "")
        reply = f"[gateway:{self._config.model}] {last_user}"
        return CompletionResult.ok(
            message=Message.assistant(reply),
            prompt_tokens=self.count_messages_tokens(messages),
            completion_tokens=self.count_tokens(reply),
            model=self._config.model,
            finish_reason=FinishReason.TERMINAL_STOP,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        result = await self.complete(messages, tools, config_override)
        content = str(result.content)
        yield StreamChunk(
            content=content,
            accumulated_content=content,
            finish_reason=FinishReason.TERMINAL_STOP,
            is_final=True,
        )

    def count_tokens(self, text: str) -> TokenCount:
        return TokenCount(max(1, len(text) // 4))

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        return TokenCount(sum(self.count_tokens(str(m.content)) for m in messages))

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        return self.count_messages_tokens(messages)


async def main() -> None:
    client = EchoGatewayClient()

    # The contract is structural: conformance is checkable, no base class needed.
    assert isinstance(client, LLMClient), "EchoGatewayClient must satisfy LLMClient"

    result = await client.complete([Message.user("ping")])

    print(f"protocol conformance : {isinstance(client, LLMClient)}")
    print(f"completion           : {result.content}")
    print(f"tokens (in/out)      : {result.prompt_tokens}/{result.completion_tokens}")
    print(f"model                : {result.model}")


if __name__ == "__main__":
    asyncio.run(main())
