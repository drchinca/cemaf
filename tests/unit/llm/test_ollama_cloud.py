"""Unit tests for the ollama-cloud provider factory."""

from __future__ import annotations

import pytest

from cemaf.llm.factories import (
    DEFAULT_OLLAMA_CLOUD_MODEL,
    OLLAMA_CLOUD_BASE_URL,
    create_llm_client,
    llm_registry,
)
from cemaf.llm.openai_compat import OpenAICompatClient


class TestOllamaCloudFactory:
    def test_ollama_cloud_backend_registered(self) -> None:
        assert "ollama-cloud" in llm_registry._factories  # type: ignore[attr-defined]

    def test_factory_uses_ollama_cloud_base_url(self) -> None:
        client = create_llm_client(provider="ollama-cloud", api_key="test-key")
        assert isinstance(client, OpenAICompatClient)
        assert client._base_url == OLLAMA_CLOUD_BASE_URL  # type: ignore[attr-defined]

    def test_factory_default_model_is_named_constant(self) -> None:
        client = create_llm_client(provider="ollama-cloud", api_key="test-key")
        assert isinstance(client, OpenAICompatClient)
        assert client.config.model == DEFAULT_OLLAMA_CLOUD_MODEL

    def test_factory_accepts_custom_model(self) -> None:
        client = create_llm_client(
            provider="ollama-cloud",
            api_key="test-key",
            model="kimi-k2.7-code:cloud",
        )
        assert isinstance(client, OpenAICompatClient)
        assert client.config.model == "kimi-k2.7-code:cloud"

    def test_factory_reads_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "env-key-abc123")
        client = create_llm_client(provider="ollama-cloud")
        assert isinstance(client, OpenAICompatClient)
        assert client._api_key == "env-key-abc123"  # type: ignore[attr-defined]

    def test_factory_kwarg_api_key_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "env-key")
        client = create_llm_client(provider="ollama-cloud", api_key="kwarg-key")
        assert isinstance(client, OpenAICompatClient)
        assert client._api_key == "kwarg-key"  # type: ignore[attr-defined]

    def test_factory_raises_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OLLAMA_CLOUD_API_KEY", raising=False)
        with pytest.raises(ValueError, match="api_key required for Ollama Cloud"):
            create_llm_client(provider="ollama-cloud")

    def test_factory_accepts_custom_base_url(self) -> None:
        client = create_llm_client(
            provider="ollama-cloud",
            api_key="test-key",
            base_url="https://custom.ollama.example/v1",
        )
        assert isinstance(client, OpenAICompatClient)
        assert client._base_url == "https://custom.ollama.example/v1"  # type: ignore[attr-defined]
