"""Tests for LLM factory helpers."""

import pytest

from cemaf.llm.factories import create_instrumented_client, create_resilient_llm_client
from cemaf.llm.mock import MockLLMClient
from cemaf.observability.run_logger import InMemoryRunLogger


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


def test_create_resilient_llm_client_auto_prefers_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}
    base_client = object()
    wrapped_client = object()

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
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
    assert created["provider"] == "openai"
    assert created["kwargs"] == {"api_key": "test-openai", "model": "gpt-4o-mini"}
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
