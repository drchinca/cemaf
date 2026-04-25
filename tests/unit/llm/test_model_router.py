"""Tests for ModelRouter."""

import pytest

from cemaf.llm.model_router import DefaultComplexityEstimator, ModelRoute, ModelRouter
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import Message
from cemaf.resilience.circuit_breaker import CircuitOpenError


def _msg(text: str) -> list[Message]:
    return [Message.user(text)]


def _long_messages(n: int, length: int = 5_000) -> list[Message]:
    return [Message.user("x" * length) for _ in range(n)]


class TestModelRouter:
    def test_low_complexity_routes_to_first(self):
        cheap = MockLLMClient(responses=["cheap"])
        expensive = MockLLMClient(responses=["expensive"])
        routes = [
            ModelRoute(threshold=0.4, client=cheap, model_name="cheap-model"),
            ModelRoute(threshold=1.1, client=expensive, model_name="expensive-model"),
        ]
        router = ModelRouter(routes=routes)
        estimator = DefaultComplexityEstimator()

        score = estimator.estimate(_msg("hi"), None)
        assert score < 0.4  # single short message is low complexity

        candidates = router._select_route(score)
        assert candidates[0].model_name == "cheap-model"

    def test_high_complexity_routes_to_last(self):
        cheap = MockLLMClient(responses=["cheap"])
        expensive = MockLLMClient(responses=["expensive"])
        routes = [
            ModelRoute(threshold=0.3, client=cheap, model_name="cheap-model"),
            ModelRoute(threshold=1.1, client=expensive, model_name="expensive-model"),
        ]
        router = ModelRouter(routes=routes)
        estimator = DefaultComplexityEstimator()

        # 50 messages × 5000 chars each → high complexity
        messages = _long_messages(50, 5_000)
        score = estimator.estimate(messages, None)
        assert score > 0.3

        candidates = router._select_route(score)
        assert candidates[0].model_name == "expensive-model"

    @pytest.mark.asyncio
    async def test_fallback_on_circuit_open(self):
        class BrokenClient:
            @property
            def config(self):
                from cemaf.llm.protocols import LLMConfig

                return LLMConfig()

            async def complete(self, messages, tools=None, config_override=None):
                raise CircuitOpenError("test circuit open")

            async def stream(self, *a, **kw):
                raise CircuitOpenError()

            def count_tokens(self, text):
                from cemaf.core.types import TokenCount

                return TokenCount(0)

            def count_messages_tokens(self, messages):
                from cemaf.core.types import TokenCount

                return TokenCount(0)

            async def count_tokens_exact(self, messages, tools=None):
                from cemaf.core.types import TokenCount

                return TokenCount(0)

        fallback = MockLLMClient(responses=["fallback"])
        routes = [
            ModelRoute(threshold=1.1, client=BrokenClient(), model_name="broken"),
            ModelRoute(threshold=2.0, client=fallback, model_name="fallback"),
        ]
        router = ModelRouter(routes=routes)
        result = await router.complete(_msg("hello"))
        assert result.success
        assert "fallback" in str(result.content)
