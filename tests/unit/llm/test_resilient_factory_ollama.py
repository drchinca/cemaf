"""create_resilient_llm_client × Ollama (local / tiered / cloud) + the mock factory.

The existing auto-resolution test stubs create_llm_client, so the Ollama branch
bodies never actually execute. These tests run them for real — construction
only, no network: OpenAICompatClient/ModelRouter don't connect until called.
"""

from __future__ import annotations

import pytest

from cemaf.core.defaults import DEFAULT_FREE_LLM_MODEL
from cemaf.llm.factories import (
    DEFAULT_OLLAMA_CLOUD_MODEL,
    OLLAMA_CLOUD_BASE_URL,
    create_llm_client,
    create_mock_llm_client,
    create_resilient_llm_client,
)
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.model_router import ModelRouter
from cemaf.llm.ollama import DEFAULT_LARGE_MODEL, DEFAULT_SMALL_MODEL
from cemaf.llm.resilient import ResilientLLMClient


class TestResilientOllamaLocal:
    def test_explicit_ollama_builds_resilient_local_client(self) -> None:
        client = create_resilient_llm_client(provider="ollama")

        assert isinstance(client, ResilientLLMClient)
        assert client.config.model == DEFAULT_FREE_LLM_MODEL

    def test_explicit_ollama_honors_model_and_runtime_options(self) -> None:
        client = create_resilient_llm_client(
            provider="ollama",
            model="gemma3:12b",
            temperature=0.1,
            max_tokens=512,
            timeout_seconds=30.0,
        )

        assert isinstance(client, ResilientLLMClient)
        assert client.config.model == "gemma3:12b"
        assert client.config.temperature == 0.1
        assert client.config.max_tokens == 512

    def test_env_resolution_auto_to_ollama(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CEMAF_LLM_PROVIDER=ollama drives the auto path into the real branch."""
        monkeypatch.setenv("CEMAF_LLM_PROVIDER", "ollama")

        client = create_resilient_llm_client(provider="auto")

        assert isinstance(client, ResilientLLMClient)
        assert client.config.model == DEFAULT_FREE_LLM_MODEL


class TestResilientOllamaTiered:
    def test_ollama_tiered_wraps_model_router(self) -> None:
        client = create_resilient_llm_client(provider="ollama-tiered")

        assert isinstance(client, ResilientLLMClient)
        assert isinstance(client._client, ModelRouter)  # noqa: SLF001 — wiring assertion

    def test_tiered_router_routes_small_then_large(self) -> None:
        router = create_llm_client("ollama-tiered")

        assert isinstance(router, ModelRouter)
        models = [route.model_name for route in router._routes]  # noqa: SLF001
        assert models == [DEFAULT_SMALL_MODEL, DEFAULT_LARGE_MODEL]


class TestResilientOllamaCloud:
    def test_ollama_cloud_through_generic_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """provider="ollama-cloud" resolves via the generic else-branch and builds
        the bearer-auth OpenAI-compatible client against ollama.com."""
        monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "test-key")

        client = create_resilient_llm_client(provider="ollama-cloud")

        assert isinstance(client, ResilientLLMClient)
        assert client.config.model == DEFAULT_OLLAMA_CLOUD_MODEL

    def test_ollama_cloud_model_override_through_generic_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "test-key")

        client = create_resilient_llm_client(provider="ollama-cloud", model="qwen3:32b-cloud")

        assert client.config.model == "qwen3:32b-cloud"

    def test_ollama_cloud_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OLLAMA_CLOUD_API_KEY", raising=False)

        with pytest.raises(ValueError, match="OLLAMA_CLOUD_API_KEY"):
            create_resilient_llm_client(provider="ollama-cloud")

    def test_cloud_base_url_constant_points_at_ollama_com(self) -> None:
        assert OLLAMA_CLOUD_BASE_URL == "https://ollama.com/v1"


class TestMockFactory:
    def test_create_mock_llm_client_defaults(self) -> None:
        mock = create_mock_llm_client()

        assert isinstance(mock, MockLLMClient)
        assert mock.call_count == 0

    @pytest.mark.asyncio
    async def test_create_mock_llm_client_with_responses(self) -> None:
        from cemaf.llm.protocols import Message

        mock = create_mock_llm_client(responses=["hola"])

        result = await mock.complete([Message.user("hi")])

        assert result.content == "hola"
