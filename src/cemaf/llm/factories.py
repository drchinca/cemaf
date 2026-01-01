"""
Factory functions for LLM client components.

Provides convenient ways to create LLM clients with sensible defaults
while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. The create_llm_client_from_config()
    function includes a clear "EXTEND HERE" section where you can add
    your own LLM provider implementations (OpenAI, Anthropic, local models, etc.).
"""

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import LLMClient


def create_mock_llm_client(
    responses: list[str] | None = None,
) -> MockLLMClient:
    """
    Factory for MockLLMClient with sensible defaults.

    Args:
        responses: List of responses to return (optional)

    Returns:
        Configured MockLLMClient instance

    Example:
        # Basic mock
        client = create_mock_llm_client()

        # With custom responses
        client = create_mock_llm_client(
            responses=["Response 1", "Response 2"]
        )
    """
    return MockLLMClient(responses=responses)


def create_llm_client_from_config(
    provider: str | None = None,
    settings: Settings | None = None,
) -> LLMClient:
    """
    Create LLM client from Settings configuration.

    Reads from Settings (which loads from environment variables):
    - CEMAF_LLM_PROVIDER: Provider name (default: "mock")
    - CEMAF_LLM_DEFAULT_MODEL: Model name (provider-specific)
    - CEMAF_LLM_API_KEY: API key for provider
    - CEMAF_LLM_BASE_URL: Custom base URL (optional)
    - CEMAF_LLM_TIMEOUT_SECONDS: Request timeout (default: 30.0)
    - CEMAF_LLM_MAX_RETRIES: Max retry attempts (default: 3)

    Args:
        provider: Provider name (overrides settings)
        settings: Settings instance (loads from env if None)

    Returns:
        Configured LLMClient instance

    Example:
        # From environment (via Settings)
        client = create_llm_client_from_config()

        # Explicit provider
        client = create_llm_client_from_config(provider="openai")

        # With explicit settings
        settings = Settings(...)
        client = create_llm_client_from_config(settings=settings)
    """
    cfg = settings or load_settings_from_env_sync()  # noqa: F841
    provider = provider or cfg.llm.provider

    # BUILT-IN IMPLEMENTATIONS
    if provider == "mock":
        return create_mock_llm_client()

    # ============================================================================
    # EXTEND HERE: Bring Your Own LLM Provider
    # ============================================================================
    # This is the extension point for custom LLM providers.
    #
    # To add your own implementation:
    # 1. Implement the LLMClient protocol (see cemaf.llm.protocols)
    # 2. Add your provider case below
    # 3. Read configuration from settings or environment variables
    #
    # Example (OpenAI):
    #   elif provider == "openai":
    #       from openai import AsyncOpenAI
    #       from your_package import OpenAILLMClient
    #
    #       api_key = cfg.llm.api_key or os.getenv("OPENAI_API_KEY")
    #       model = cfg.llm.default_model
    #       timeout = cfg.llm.timeout_seconds
    #
    #       client = AsyncOpenAI(api_key=api_key, timeout=timeout)
    #       return OpenAILLMClient(client=client, model=model)
    #
    # Example (Anthropic):
    #   elif provider == "anthropic":
    #       from anthropic import AsyncAnthropic
    #       from your_package import AnthropicLLMClient
    #
    #       api_key = cfg.llm.api_key or os.getenv("ANTHROPIC_API_KEY")
    #       model = cfg.llm.default_model
    #       timeout = cfg.llm.timeout_seconds
    #
    #       client = AsyncAnthropic(api_key=api_key, timeout=timeout)
    #       return AnthropicLLMClient(client=client, model=model)
    #
    # Example (Local/Ollama):
    #   elif provider == "ollama":
    #       from your_package import OllamaLLMClient
    #
    #       base_url = cfg.llm.base_url or "http://localhost:11434"
    #       model = cfg.llm.default_model
    #
    #       return OllamaLLMClient(base_url=base_url, model=model)
    # ============================================================================

    raise ValueError(
        f"Unsupported LLM provider: {provider}. "
        f"Supported: mock. "
        f"To add your own, extend create_llm_client_from_config() "
        f"in cemaf/llm/factories.py"
    )
