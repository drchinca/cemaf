"""Tests for ModelRouter."""

import pytest

from cemaf.core.types import FinishReason
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.model_router import DefaultComplexityEstimator, ModelRoute, ModelRouter
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

    def test_fidelity_floor_derives_from_single_source(self):
        """Router's floor view must match the canonical FIDELITY_FLOOR in agents.selection."""
        from cemaf.agents.selection import FIDELITY_FLOOR
        from cemaf.llm.model_router import _FIDELITY_FLOOR_BY_VALUE

        assert {f.value: floor for f, floor in FIDELITY_FLOOR.items()} == _FIDELITY_FLOOR_BY_VALUE

    def test_fidelity_floor_raises_low_complexity_route(self):
        """SPEC-09 Inv 9: HIGH fidelity floors a trivial prompt's score up to 0.8."""
        from cemaf.llm.model_router import _apply_fidelity_floor

        estimator = DefaultComplexityEstimator()
        raw = estimator.estimate(_msg("hi"), None)
        assert raw < 0.4  # trivial prompt

        floored = _apply_fidelity_floor(score=raw, fidelity="high")
        assert floored == 0.8

        # standard floor; none/unknown leave the score untouched
        assert _apply_fidelity_floor(score=raw, fidelity="standard") == 0.4
        assert _apply_fidelity_floor(score=raw, fidelity=None) == raw
        assert _apply_fidelity_floor(score=raw, fidelity="bogus") == raw
        # never lowers an already-high score
        assert _apply_fidelity_floor(score=0.95, fidelity="high") == 0.95

    @pytest.mark.asyncio
    async def test_fidelity_high_routes_trivial_prompt_to_expensive(self):
        """End-to-end: a one-line prompt with fidelity=high lands on the expensive route."""
        cheap = MockLLMClient(responses=["cheap"])
        expensive = MockLLMClient(responses=["expensive"])
        routes = [
            ModelRoute(threshold=0.4, client=cheap, model_name="cheap-model"),
            ModelRoute(threshold=1.1, client=expensive, model_name="expensive-model"),
        ]
        router = ModelRouter(routes=routes)

        # Without fidelity the trivial prompt would route cheap; HIGH floors it to 0.8.
        result = await router.complete(_msg("hi"), fidelity="high")
        assert result.success
        assert str(result.message.content) == "expensive"

    @pytest.mark.asyncio
    async def test_protocol_hints_forward_to_selected_route(self):
        """Routing hints are for both selection and downstream adapters."""

        class RecordingClient(MockLLMClient):
            seen_hints: dict[str, object | None]

            async def complete(
                self,
                messages,
                tools=None,
                config_override=None,
                *,
                fidelity=None,
                token_budget=None,
                correlation_id=None,
            ):
                self.seen_hints = {
                    "fidelity": fidelity,
                    "token_budget": token_budget,
                    "correlation_id": correlation_id,
                }
                return await super().complete(
                    messages=messages,
                    tools=tools,
                    config_override=config_override,
                    fidelity=fidelity,
                    token_budget=token_budget,
                    correlation_id=correlation_id,
                )

        selected = RecordingClient(responses=["selected"])
        router = ModelRouter(
            routes=[ModelRoute(threshold=1.1, client=selected, model_name="selected-model")],
        )
        budget = object()

        result = await router.complete(
            _msg("hi"),
            fidelity="high",
            token_budget=budget,
            correlation_id="run-123",
        )

        assert result.success
        assert selected.seen_hints == {
            "fidelity": "high",
            "token_budget": budget,
            "correlation_id": "run-123",
        }

    @pytest.mark.asyncio
    async def test_fallback_on_circuit_open(self):
        class BrokenClient:
            @property
            def config(self):
                from cemaf.llm.protocols import LLMConfig

                return LLMConfig()

            async def complete(self, messages, tools=None, config_override=None, **kwargs):
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

    @pytest.mark.asyncio
    async def test_stream_routes_to_selected_client(self):
        cheap = MockLLMClient(responses=["cheap stream"])
        expensive = MockLLMClient(responses=["expensive stream"])
        router = ModelRouter(
            routes=[
                ModelRoute(threshold=0.4, client=cheap, model_name="cheap-model"),
                ModelRoute(threshold=1.1, client=expensive, model_name="expensive-model"),
            ],
        )

        chunks = [chunk async for chunk in router.stream(_msg("hi"))]

        assert "".join(chunk.content for chunk in chunks) == "cheap stream"
        assert chunks[-1].is_final
        assert cheap.call_count == 1
        assert expensive.call_count == 0

    @pytest.mark.asyncio
    async def test_stream_falls_back_on_circuit_open_before_chunks(self):
        class BrokenClient:
            @property
            def config(self):
                from cemaf.llm.protocols import LLMConfig

                return LLMConfig()

            async def complete(self, messages, tools=None, config_override=None, **kwargs):
                raise CircuitOpenError("test circuit open")

            async def stream(self, *a, **kw):
                raise CircuitOpenError("test circuit open")

            def count_tokens(self, text):
                from cemaf.core.types import TokenCount

                return TokenCount(0)

            def count_messages_tokens(self, messages):
                from cemaf.core.types import TokenCount

                return TokenCount(0)

            async def count_tokens_exact(self, messages, tools=None):
                from cemaf.core.types import TokenCount

                return TokenCount(0)

        fallback = MockLLMClient(responses=["fallback stream"])
        router = ModelRouter(
            routes=[
                ModelRoute(threshold=1.1, client=BrokenClient(), model_name="broken"),
                ModelRoute(threshold=2.0, client=fallback, model_name="fallback"),
            ],
        )

        chunks = [chunk async for chunk in router.stream(_msg("hello"))]

        assert "".join(chunk.content for chunk in chunks) == "fallback stream"
        assert chunks[-1].is_final
        assert fallback.call_count == 1

    @pytest.mark.asyncio
    async def test_stream_exhaustion_yields_partial_error_chunk(self):
        class BrokenClient:
            @property
            def config(self):
                from cemaf.llm.protocols import LLMConfig

                return LLMConfig()

            async def complete(self, messages, tools=None, config_override=None, **kwargs):
                raise CircuitOpenError("test circuit open")

            async def stream(self, *a, **kw):
                raise CircuitOpenError("test circuit open")

            def count_tokens(self, text):
                from cemaf.core.types import TokenCount

                return TokenCount(0)

            def count_messages_tokens(self, messages):
                from cemaf.core.types import TokenCount

                return TokenCount(0)

            async def count_tokens_exact(self, messages, tools=None):
                from cemaf.core.types import TokenCount

                return TokenCount(0)

        router = ModelRouter(
            routes=[ModelRoute(threshold=1.1, client=BrokenClient(), model_name="broken")],
        )

        chunks = [chunk async for chunk in router.stream(_msg("hello"))]

        assert len(chunks) == 1
        assert chunks[0].is_final
        assert chunks[0].finish_reason is FinishReason.PARTIAL_ERROR
        assert "All routes exhausted" in chunks[0].content
