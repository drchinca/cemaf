"""
Complexity-based model router.

Routes LLM requests to the most cost-effective model based on a
complexity score derived from message count, token estimate, and
tool count. Falls back to next model if the primary's circuit is OPEN.
"""

from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from cemaf.agents.selection import FIDELITY_FLOOR, Fidelity
from cemaf.core.types import FinishReason, TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    Message,
    StreamChunk,
    ToolDefinition,
)
from cemaf.observability.protocols import Logger
from cemaf.resilience.circuit_breaker import CircuitOpenError

# String-keyed view of the single-source FIDELITY_FLOOR (SPEC-09 Invariant 9), so
# a `Fidelity` StrEnum or a raw value string ("high") both resolve. agents.selection
# imports neither llm nor model_router, so this import introduces no cycle.
_FIDELITY_FLOOR_BY_VALUE: dict[str, float] = {f.value: floor for f, floor in FIDELITY_FLOOR.items()}


def _apply_fidelity_floor(*, score: float, fidelity: object | None) -> float:
    """Raise the route score to the fidelity tier's floor, if a known fidelity is given."""
    if fidelity is None:
        return score
    key = fidelity.value if isinstance(fidelity, Fidelity) else str(fidelity).lower()
    floor = _FIDELITY_FLOOR_BY_VALUE.get(key)
    return max(score, floor) if floor is not None else score


@runtime_checkable
class ComplexityEstimator(Protocol):
    """Returns a 0.0–1.0 complexity score for a request."""

    def estimate(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
    ) -> float: ...


class DefaultComplexityEstimator:
    """
    Heuristic estimator combining message count, total characters, and tool count.

    Weights: 40% message count (normalised to 50), 40% characters (100 k),
    20% tool count (normalised to 10). Clamped to [0.0, 1.0].
    """

    def estimate(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
    ) -> float:
        import json

        msg_score = min(len(messages) / 50.0, 1.0)

        total_chars = 0
        for msg in messages:
            if isinstance(msg.content, str):
                total_chars += len(msg.content)
            else:
                total_chars += len(json.dumps(msg.content))
        char_score = min(total_chars / 100_000.0, 1.0)

        tool_score = min(len(tools) / 10.0, 1.0) if tools else 0.0

        return min(0.4 * msg_score + 0.4 * char_score + 0.2 * tool_score, 1.0)


@dataclass(frozen=True)
class ModelRoute:
    """Associates a complexity threshold with an LLM client."""

    threshold: float
    client: LLMClient
    model_name: str


class ModelRouter:
    """
    Routes each request to the cheapest model whose threshold covers the complexity.

    Routes are sorted ascending by threshold at init time. The first route
    whose threshold exceeds the complexity score is selected. If the selected
    client's circuit breaker is OPEN, the router tries the next route in order.
    """

    def __init__(
        self,
        routes: list[ModelRoute],
        estimator: ComplexityEstimator | None = None,
        logger: Logger | None = None,
    ) -> None:
        if not routes:
            raise ValueError("ModelRouter requires at least one route")
        self._routes = sorted(routes, key=lambda r: r.threshold)
        self._estimator = estimator or DefaultComplexityEstimator()
        self._logger = logger

    @property
    def config(self) -> LLMConfig:
        return self._routes[0].client.config

    def _select_route(self, score: float) -> list[ModelRoute]:
        """Return routes in preference order starting from the best match."""
        for i, route in enumerate(self._routes):
            if score < route.threshold:
                return self._routes[i:]
        return [self._routes[-1]]

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
        score = self._estimator.estimate(messages, tools)
        score = _apply_fidelity_floor(score=score, fidelity=fidelity)
        candidates = self._select_route(score)

        last_error: str = "No route available"
        for route in candidates:
            if self._logger:
                self._logger.info(
                    "ModelRouter selected %s",
                    route.model_name,
                    complexity_score=score,
                    model=route.model_name,
                )
            try:
                return await route.client.complete(
                    messages=messages,
                    tools=tools,
                    config_override=config_override,
                    fidelity=fidelity,
                    token_budget=token_budget,
                    correlation_id=correlation_id,
                )
            except CircuitOpenError as exc:
                last_error = str(exc)
                if self._logger:
                    self._logger.warning(
                        "Circuit open for %s, trying next route",
                        route.model_name,
                    )
                continue

        return CompletionResult.fail(error=f"All routes exhausted: {last_error}")

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        score = self._estimator.estimate(messages, tools)
        candidates = self._select_route(score)

        last_error = "No route available"
        for route in candidates:
            if self._logger:
                self._logger.info(
                    "ModelRouter selected %s",
                    route.model_name,
                    complexity_score=score,
                    model=route.model_name,
                )

            accumulated = ""
            emitted = False
            try:
                stream_result: Any = route.client.stream(
                    messages=messages,
                    tools=tools,
                    config_override=config_override,
                )
                stream = (
                    cast(AsyncIterator[StreamChunk], stream_result)
                    if hasattr(stream_result, "__aiter__")
                    else await cast(Awaitable[AsyncIterator[StreamChunk]], stream_result)
                )
                async for chunk in stream:
                    emitted = True
                    accumulated = chunk.accumulated_content or accumulated + chunk.content
                    yield chunk
                return
            except CircuitOpenError as exc:
                last_error = str(exc)
                if self._logger:
                    self._logger.warning(
                        "Circuit open for %s, trying next route",
                        route.model_name,
                    )
                if emitted:
                    yield StreamChunk(
                        content=f"Stream interrupted: {last_error}",
                        finish_reason=FinishReason.PARTIAL_ERROR,
                        is_final=True,
                        accumulated_content=accumulated,
                    )
                    return
                continue

        yield StreamChunk(
            content=f"All routes exhausted: {last_error}",
            finish_reason=FinishReason.PARTIAL_ERROR,
            is_final=True,
        )

    def count_tokens(self, text: str) -> TokenCount:
        return self._routes[0].client.count_tokens(text)

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        return self._routes[0].client.count_messages_tokens(messages)

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        return await self._routes[0].client.count_tokens_exact(messages=messages, tools=tools)
