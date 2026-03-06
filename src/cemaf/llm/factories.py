"""Factory functions for LLM client components."""

from typing import Any

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import LLMClient

# Global LLM provider registry — extend with your own providers
llm_registry: ProviderRegistry[LLMClient] = ProviderRegistry(name="llm")


def _create_mock(**kwargs: Any) -> LLMClient:
    """Factory for mock LLM client."""
    return MockLLMClient(responses=kwargs.get("responses"))  # type: ignore[return-value]


# Register built-in providers
llm_registry.register(backend="mock", factory=_create_mock)


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
