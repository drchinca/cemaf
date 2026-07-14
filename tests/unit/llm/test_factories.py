"""Tests for LLM factory helpers."""

from typing import get_args

import pytest

from cemaf.config.protocols import LLMSettings, Settings
from cemaf.core.defaults import DEFAULT_FREE_LLM_MODEL, DEFAULT_FREE_LLM_PROVIDER
from cemaf.core.types import LLMProvider
from cemaf.llm.factories import (
    create_instrumented_client,
    create_llm_client_from_config,
    create_resilient_llm_client,
    llm_registry,
)
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.openai_compat import OpenAICompatClient
from cemaf.observability.run_logger import InMemoryRunLogger


def test_configured_llm_providers_are_registered() -> None:
    provider_annotation = LLMSettings.model_fields["provider"].annotation
    configured = set(get_args(provider_annotation))
    registered = set(llm_registry.list_backends())

    assert configured == registered


def test_create_instrumented_client_wraps_client() -> None:
    inner = MockLLMClient(responses=["ok"])
    logger = InMemoryRunLogger()

    wrapped = create_instrumented_client(
        client=inner,
        run_logger=logger,
        node_id="writer",
        agent_id="writer",
    )

    assert wrapped.config.model == inner.config.model


def test_create_resilient_llm_client_auto_prefers_free_local_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}
    base_client = object()
    wrapped_client = object()

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.delenv("CEMAF_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _fake_create_llm_client(provider: str, **kwargs):
        created["provider"] = provider
        created["kwargs"] = kwargs
        return base_client

    def _fake_create_resilient_client(*, client, **kwargs):
        created["wrapped_client"] = client
        created["wrapper_kwargs"] = kwargs
        return wrapped_client

    monkeypatch.setattr("cemaf.llm.factories.create_llm_client", _fake_create_llm_client)
    monkeypatch.setattr("cemaf.llm.factories.create_resilient_client", _fake_create_resilient_client)

    client = create_resilient_llm_client()

    assert client is wrapped_client
    assert created["provider"] == DEFAULT_FREE_LLM_PROVIDER
    assert created["kwargs"] == {
        "model": DEFAULT_FREE_LLM_MODEL,
        "temperature": 0.7,
        "max_tokens": 4096,
        "timeout_seconds": 120.0,
    }
    assert created["wrapped_client"] is base_client
    assert created["wrapper_kwargs"] == {
        "metrics": None,
        "fallback_model": None,
        "enable_caching": False,
        "cache_threshold_tokens": 1000,
    }


def test_create_resilient_llm_client_bedrock_passes_runtime_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}
    base_client = object()

    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL", raising=False)

    def _fake_create_llm_client(provider: str, **kwargs):
        created["provider"] = provider
        created["kwargs"] = kwargs
        return base_client

    monkeypatch.setattr("cemaf.llm.factories.create_llm_client", _fake_create_llm_client)
    monkeypatch.setattr(
        "cemaf.llm.factories.create_resilient_client",
        lambda **kwargs: kwargs["client"],
    )

    client = create_resilient_llm_client(
        provider="bedrock",
        temperature=0.2,
        max_tokens=2048,
        timeout_seconds=33.0,
    )

    assert client is base_client
    assert created["provider"] == "bedrock"
    assert created["kwargs"] == {
        "model": "global.anthropic.claude-sonnet-4-6",
        "region": "us-east-1",
        "profile": None,
        "temperature": 0.2,
        "max_tokens": 2048,
        "timeout_seconds": 33.0,
    }


def test_create_resilient_llm_client_gemini_passes_runtime_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}
    base_client = object()

    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")

    def _fake_create_llm_client(provider: str, **kwargs):
        created["provider"] = provider
        created["kwargs"] = kwargs
        return base_client

    monkeypatch.setattr("cemaf.llm.factories.create_llm_client", _fake_create_llm_client)
    monkeypatch.setattr(
        "cemaf.llm.factories.create_resilient_client",
        lambda **kwargs: kwargs["client"],
    )

    client = create_resilient_llm_client(
        provider="gemini",
        temperature=0.2,
        max_tokens=2048,
        timeout_seconds=33.0,
    )

    assert client is base_client
    assert created["provider"] == "gemini"
    assert created["kwargs"] == {
        "api_key": "test-gemini",
        "model": "gemini-2.5-flash",
        "temperature": 0.2,
        "max_tokens": 2048,
        "timeout_seconds": 33.0,
    }


def test_create_llm_client_from_config_passes_llm_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}
    fake_client = object()
    settings = Settings(
        llm=LLMSettings(
            provider="openai-compatible",
            default_model="gpt-4o",
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
            default_temperature=0.1,
            max_tokens=123,
            timeout_seconds=45.0,
        )
    )

    def _fake_create(*, backend: str, **kwargs):
        created["backend"] = backend
        created["kwargs"] = kwargs
        return fake_client

    monkeypatch.setattr(llm_registry, "create", _fake_create)

    client = create_llm_client_from_config(settings=settings)

    assert client is fake_client
    assert created["backend"] == "openai-compatible"
    assert created["kwargs"] == {
        "api_key": "sk-test",
        "model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "temperature": 0.1,
        "max_tokens": 123,
        "timeout_seconds": 45.0,
    }


def test_create_llm_client_from_default_config_is_free_first() -> None:
    client = create_llm_client_from_config(settings=Settings())

    assert isinstance(client, OpenAICompatClient)
    assert client.config.model == DEFAULT_FREE_LLM_MODEL
    assert client._provider is LLMProvider.OLLAMA
    assert DEFAULT_FREE_LLM_PROVIDER == "ollama"


def test_create_llm_client_from_config_does_not_leak_class_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}
    fake_client = object()
    settings = Settings(
        llm=LLMSettings(
            provider="openai-compatible",
            api_key="sk-test",
        )
    )

    def _fake_create(*, backend: str, **kwargs):
        created["backend"] = backend
        created["kwargs"] = kwargs
        return fake_client

    monkeypatch.setattr(llm_registry, "create", _fake_create)

    client = create_llm_client_from_config(settings=settings)

    assert client is fake_client
    assert created["backend"] == "openai-compatible"
    assert created["kwargs"] == {"api_key": "sk-test"}


def test_create_llm_client_from_config_reads_documented_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}
    fake_client = object()

    monkeypatch.setenv("CEMAF_LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("CEMAF_LLM_DEFAULT_MODEL", "gpt-4o")
    monkeypatch.setenv("CEMAF_LLM_API_KEY", "sk-env")
    monkeypatch.setenv("CEMAF_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("CEMAF_LLM_DEFAULT_TEMPERATURE", "0.2")
    monkeypatch.setenv("CEMAF_LLM_MAX_TOKENS", "456")
    monkeypatch.setenv("CEMAF_LLM_TIMEOUT_SECONDS", "67")

    def _fake_create(*, backend: str, **kwargs):
        created["backend"] = backend
        created["kwargs"] = kwargs
        return fake_client

    monkeypatch.setattr(llm_registry, "create", _fake_create)

    client = create_llm_client_from_config()

    assert client is fake_client
    assert created["backend"] == "openai-compatible"
    assert created["kwargs"] == {
        "api_key": "sk-env",
        "model": "gpt-4o",
        "base_url": "https://example.test/v1",
        "temperature": 0.2,
        "max_tokens": 456,
        "timeout_seconds": 67.0,
    }
