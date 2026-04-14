"""Factory functions for LLM client components.

Supports 6 providers out of the box:
    client = create_llm_client("ollama", model="qwen3.5")
    client = create_llm_client("openai", api_key="sk-...")
    client = create_llm_client("anthropic", api_key="sk-ant-...")
    client = create_llm_client("gemini", api_key="AIza...")
    client = create_llm_client("groq", api_key="gsk-...")
    client = create_llm_client("together", api_key="...")
"""

import os
from typing import Any

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import LLMClient

# Global LLM provider registry — extend with your own providers
llm_registry: ProviderRegistry[LLMClient] = ProviderRegistry(name="llm")


# ---------------------------------------------------------------------------
# Provider factories
# ---------------------------------------------------------------------------


def _create_mock(**kwargs: Any) -> LLMClient:
    return MockLLMClient(responses=kwargs.get("responses"))  # type: ignore[return-value]


def _create_anthropic(**kwargs: Any) -> LLMClient:
    from cemaf.llm.anthropic import AnthropicLLMClient

    api_key = kwargs.get("api_key") or os.getenv("ANTHROPIC_API_KEY", "")
    model = kwargs.get("model", "claude-sonnet-4-20250514")
    if not api_key:
        raise ValueError("api_key required for Anthropic (or set ANTHROPIC_API_KEY)")
    return AnthropicLLMClient(api_key=api_key, model=model)  # type: ignore[return-value]


def _create_openai(**kwargs: Any) -> LLMClient:
    from cemaf.llm.openai_compat import OpenAICompatClient

    api_key: str = str(kwargs.get("api_key") or os.getenv("OPENAI_API_KEY", ""))
    return OpenAICompatClient(  # type: ignore[return-value]
        api_key=api_key,
        base_url=kwargs.get("base_url", "https://api.openai.com/v1"),
        model=kwargs.get("model", "gpt-4o"),
    )


def _create_ollama(**kwargs: Any) -> LLMClient:
    from cemaf.llm.openai_compat import OpenAICompatClient

    return OpenAICompatClient(  # type: ignore[return-value]
        base_url=kwargs.get("base_url", "http://localhost:11434/v1"),
        model=kwargs.get("model", "qwen3.5"),
        api_key="",
    )


def _create_groq(**kwargs: Any) -> LLMClient:
    from cemaf.llm.openai_compat import OpenAICompatClient

    api_key: str = str(kwargs.get("api_key") or os.getenv("GROQ_API_KEY", ""))
    return OpenAICompatClient(  # type: ignore[return-value]
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key,
        model=kwargs.get("model", "llama-3.3-70b-versatile"),
    )


def _create_together(**kwargs: Any) -> LLMClient:
    from cemaf.llm.openai_compat import OpenAICompatClient

    api_key: str = str(kwargs.get("api_key") or os.getenv("TOGETHER_API_KEY", ""))
    return OpenAICompatClient(  # type: ignore[return-value]
        base_url="https://api.together.xyz/v1",
        api_key=api_key,
        model=kwargs.get("model", "Llama-3.3-70B-Instruct-Turbo"),
    )


def _create_gemini(**kwargs: Any) -> LLMClient:
    from cemaf.llm.gemini import GeminiClient

    api_key = kwargs.get("api_key") or os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("api_key required for Gemini (or set GEMINI_API_KEY)")
    return GeminiClient(  # type: ignore[return-value]
        api_key=api_key,
        model=kwargs.get("model", "gemini-2.5-flash"),
    )


# Register all providers
llm_registry.register(backend="mock", factory=_create_mock)
llm_registry.register(backend="anthropic", factory=_create_anthropic)
llm_registry.register(backend="openai", factory=_create_openai)
llm_registry.register(backend="ollama", factory=_create_ollama)
llm_registry.register(backend="groq", factory=_create_groq)
llm_registry.register(backend="together", factory=_create_together)
llm_registry.register(backend="gemini", factory=_create_gemini)


# ---------------------------------------------------------------------------
# Convenience factories
# ---------------------------------------------------------------------------


def create_llm_client(
    provider: str,
    **kwargs: Any,
) -> LLMClient:
    """Create an LLM client for any supported provider.

    Args:
        provider: One of: openai, anthropic, ollama, gemini, groq, together, mock
        **kwargs: Provider-specific args (api_key, model, base_url, etc.)

    Examples:
        client = create_llm_client("ollama", model="qwen3.5")
        client = create_llm_client("openai", api_key="sk-...", model="gpt-4o")
        client = create_llm_client("gemini", api_key="AIza...", model="gemini-2.5-flash")
    """
    return llm_registry.create(backend=provider, **kwargs)


def create_mock_llm_client(
    responses: list[str] | None = None,
) -> MockLLMClient:
    """Factory for MockLLMClient with sensible defaults."""
    return MockLLMClient(responses=responses)


def create_llm_client_from_config(
    provider: str | None = None,
    settings: Settings | None = None,
) -> LLMClient:
    """Create LLM client from Settings configuration."""
    cfg = settings or load_settings_from_env_sync()
    provider = provider or cfg.llm.provider
    return llm_registry.create(backend=provider)
