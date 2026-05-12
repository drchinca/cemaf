"""Contract tests for Ollama helpers — pure unit tests, no Ollama required."""

from __future__ import annotations

import pytest

from cemaf.llm.factories import create_llm_client, llm_registry
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.model_router import ModelRoute, ModelRouter
from cemaf.llm.ollama import (
    DEFAULT_ESCALATION_CHARS,
    CharBasedEstimator,
    create_ollama_client,
    create_tiered_ollama_router,
)
from cemaf.llm.openai_compat import OpenAICompatClient
from cemaf.llm.protocols import LLMClient, Message
from cemaf.resilience.circuit_breaker import CircuitOpenError


class TestCharBasedEstimator:
    def test_short_prompt_scores_zero(self) -> None:
        estimator = CharBasedEstimator()
        score = estimator.estimate(messages=[Message.user(content="hi")], tools=None)
        assert score == 0.0

    def test_long_prompt_scores_one(self) -> None:
        estimator = CharBasedEstimator(escalation_chars=100)
        score = estimator.estimate(
            messages=[Message.user(content="x" * 200)],
            tools=None,
        )
        assert score == 1.0

    def test_tool_presence_always_escalates(self) -> None:
        from cemaf.llm.protocols import ToolDefinition

        estimator = CharBasedEstimator(escalation_chars=10_000)
        tool = ToolDefinition(name="t", description="d", parameters={})
        score = estimator.estimate(
            messages=[Message.user(content="short")],
            tools=[tool],
        )
        assert score == 1.0

    def test_char_count_sums_across_messages(self) -> None:
        estimator = CharBasedEstimator(escalation_chars=100)
        score = estimator.estimate(
            messages=[
                Message.system(content="x" * 60),
                Message.user(content="y" * 60),
            ],
            tools=None,
        )
        assert score == 1.0


class TestCreateOllamaClient:
    def test_returns_openai_compat_client(self) -> None:
        client = create_ollama_client(model="gemma3:4b")
        assert isinstance(client, OpenAICompatClient)

    def test_model_set_on_config(self) -> None:
        client = create_ollama_client(model="gemma3:12b")
        assert client.config.model == "gemma3:12b"

    def test_default_base_url_is_local_ollama(self) -> None:
        client = create_ollama_client()
        assert "11434" in client._base_url  # type: ignore[attr-defined]

    def test_default_timeout_absorbs_cold_load(self) -> None:
        client = create_ollama_client()
        assert client.config.timeout_seconds >= 120.0


class TestCreateTieredOllamaRouter:
    def test_returns_model_router(self) -> None:
        router = create_tiered_ollama_router()
        assert isinstance(router, ModelRouter)

    def test_has_two_routes_ordered_small_then_large(self) -> None:
        router = create_tiered_ollama_router(
            small_model="gemma3:4b",
            large_model="gemma3:12b",
        )
        routes = router._routes  # type: ignore[attr-defined]
        assert [r.model_name for r in routes] == ["gemma3:4b", "gemma3:12b"]

    def test_escalates_above_char_threshold(self) -> None:
        router = create_tiered_ollama_router(escalation_chars=50)
        score = router._estimator.estimate(  # type: ignore[attr-defined]
            messages=[Message.user(content="x" * 100)],
            tools=None,
        )
        candidates = router._select_route(score=score)  # type: ignore[attr-defined]
        assert candidates[0].model_name.endswith("12b")

    def test_small_model_picked_for_short_prompt(self) -> None:
        router = create_tiered_ollama_router()
        score = router._estimator.estimate(  # type: ignore[attr-defined]
            messages=[Message.user(content="hi")],
            tools=None,
        )
        candidates = router._select_route(score=score)  # type: ignore[attr-defined]
        assert candidates[0].model_name.endswith("4b")


class TestFactoryIntegration:
    def test_ollama_backend_registered(self) -> None:
        assert "ollama" in llm_registry._factories  # type: ignore[attr-defined]

    def test_ollama_tiered_backend_registered(self) -> None:
        assert "ollama-tiered" in llm_registry._factories  # type: ignore[attr-defined]

    def test_create_llm_client_ollama_returns_llm_client(self) -> None:
        client = create_llm_client(provider="ollama", model="gemma3:4b")
        assert isinstance(client, LLMClient)

    def test_create_llm_client_ollama_tiered_returns_router(self) -> None:
        client = create_llm_client(provider="ollama-tiered")
        assert isinstance(client, ModelRouter)

    def test_tiered_default_escalation_chars_matches_module_default(self) -> None:
        router = create_tiered_ollama_router()
        assert (
            router._estimator.escalation_chars  # type: ignore[attr-defined]
            == DEFAULT_ESCALATION_CHARS
        )


class TestTieredRouterResilience:
    """Router behavior under circuit-breaker failures — fallback path."""

    @staticmethod
    def _broken_client() -> LLMClient:
        from cemaf.core.types import TokenCount
        from cemaf.llm.protocols import LLMConfig

        class BrokenClient:
            @property
            def config(self) -> LLMConfig:
                return LLMConfig()

            async def complete(self, messages, tools=None, config_override=None):  # type: ignore[no-untyped-def]
                raise CircuitOpenError("large model circuit open")

            async def stream(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise CircuitOpenError("large model circuit open")

            def count_tokens(self, text: str) -> TokenCount:
                return TokenCount(0)

            def count_messages_tokens(self, messages) -> TokenCount:  # type: ignore[no-untyped-def]
                return TokenCount(0)

            async def count_tokens_exact(self, messages, tools=None) -> TokenCount:  # type: ignore[no-untyped-def]
                return TokenCount(0)

        return BrokenClient()  # type: ignore[return-value]

    @pytest.mark.asyncio
    async def test_small_falls_through_to_large_when_small_breaker_open(self) -> None:
        """Low-complexity request: if small-tier breaker is OPEN, large tier answers."""
        from cemaf.llm.model_router import ModelRouter

        large = MockLLMClient(responses=["from-large"])
        router = ModelRouter(
            routes=[
                ModelRoute(threshold=0.5, client=self._broken_client(), model_name="small"),
                ModelRoute(threshold=1.0, client=large, model_name="large"),
            ],
            estimator=CharBasedEstimator(escalation_chars=100),
        )
        result = await router.complete(messages=[Message.user(content="hi")])
        assert result.success
        assert result.message is not None
        assert "from-large" in str(result.message.content)

    @pytest.mark.asyncio
    async def test_all_routes_failed_surfaces_error(self) -> None:
        from cemaf.llm.model_router import ModelRouter

        router = ModelRouter(
            routes=[
                ModelRoute(threshold=0.5, client=self._broken_client(), model_name="small"),
                ModelRoute(threshold=1.0, client=self._broken_client(), model_name="large"),
            ],
            estimator=CharBasedEstimator(),
        )
        result = await router.complete(messages=[Message.user(content="hi")])
        assert not result.success
        assert "exhausted" in (result.error or "").lower()


class TestTieredRouterStreamingSelection:
    """Route selection for streaming — exercises the same scorer/selector.

    NOTE: `ModelRouter.stream()` (src/cemaf/llm/model_router.py:153) has a
    pre-existing bug — it `await`s an async generator. Until that is fixed,
    we verify selection only.
    """

    def test_stream_small_for_short_prompt(self) -> None:
        from cemaf.llm.model_router import ModelRouter

        small = MockLLMClient(responses=["s"])
        large = MockLLMClient(responses=["l"])
        router = ModelRouter(
            routes=[
                ModelRoute(threshold=0.5, client=small, model_name="gemma3:4b"),
                ModelRoute(threshold=1.0, client=large, model_name="gemma3:12b"),
            ],
            estimator=CharBasedEstimator(escalation_chars=50),
        )
        score = router._estimator.estimate(  # type: ignore[attr-defined]
            messages=[Message.user(content="hi")],
            tools=None,
        )
        candidates = router._select_route(score=score)  # type: ignore[attr-defined]
        assert candidates[0].model_name == "gemma3:4b"

    def test_stream_large_for_long_prompt(self) -> None:
        from cemaf.llm.model_router import ModelRouter

        small = MockLLMClient(responses=["s"])
        large = MockLLMClient(responses=["l"])
        router = ModelRouter(
            routes=[
                ModelRoute(threshold=0.5, client=small, model_name="gemma3:4b"),
                ModelRoute(threshold=1.0, client=large, model_name="gemma3:12b"),
            ],
            estimator=CharBasedEstimator(escalation_chars=50),
        )
        score = router._estimator.estimate(  # type: ignore[attr-defined]
            messages=[Message.user(content="x" * 200)],
            tools=None,
        )
        candidates = router._select_route(score=score)  # type: ignore[attr-defined]
        assert candidates[0].model_name == "gemma3:12b"


class TestConfigSettingsIntegration:
    def test_ollama_tiered_is_valid_settings_provider(self) -> None:
        """LLMSettings.provider accepts ollama-tiered without ValidationError."""
        from cemaf.config.protocols import LLMSettings

        settings = LLMSettings(provider="ollama-tiered")
        assert settings.provider == "ollama-tiered"

    def test_ollama_is_valid_settings_provider(self) -> None:
        from cemaf.config.protocols import LLMSettings

        settings = LLMSettings(provider="ollama")
        assert settings.provider == "ollama"
