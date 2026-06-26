"""Factory functions for LLM client components.

Supports 9 providers out of the box:
    client = create_llm_client("ollama", model="qwen3.5")
    client = create_llm_client("ollama-cloud", model="gpt-oss:120b-cloud")
    client = create_llm_client("openai", api_key="sk-...")
    client = create_llm_client("anthropic", api_key="sk-ant-...")
    client = create_llm_client("gemini", api_key="AIza...")
    client = create_llm_client("groq", api_key="gsk-...")
    client = create_llm_client("together", api_key="...")
    client = create_llm_client("huggingface", api_key="hf_...")
    client = create_llm_client("bedrock", model="global.anthropic.claude-sonnet-4-6")
"""

import os
from typing import Any

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.core.types import LLMProvider
from cemaf.llm.instrumented import InstrumentedLLMClient
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import LLMClient
from cemaf.observability.run_logger import RunLogger
from cemaf.resilience.retry import RetryPolicy

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
    from cemaf.llm.ollama import DEFAULT_BASE_URL, create_ollama_client

    return create_ollama_client(
        model=kwargs.get("model", "gemma3:4b"),
        base_url=kwargs.get("base_url", DEFAULT_BASE_URL),
        timeout_seconds=kwargs.get("timeout_seconds", 300.0),
    )


def _create_ollama_tiered(**kwargs: Any) -> LLMClient:
    from cemaf.llm.ollama import (
        DEFAULT_BASE_URL,
        DEFAULT_ESCALATION_CHARS,
        DEFAULT_LARGE_MODEL,
        DEFAULT_SMALL_MODEL,
        create_tiered_ollama_router,
    )

    return create_tiered_ollama_router(
        small_model=kwargs.get("small_model", DEFAULT_SMALL_MODEL),
        large_model=kwargs.get("large_model", DEFAULT_LARGE_MODEL),
        base_url=kwargs.get("base_url", DEFAULT_BASE_URL),
        escalation_chars=kwargs.get("escalation_chars", DEFAULT_ESCALATION_CHARS),
        timeout_seconds=kwargs.get("timeout_seconds", 300.0),
    )


def _create_ollama_cloud(**kwargs: Any) -> LLMClient:
    """Ollama Cloud (https://ollama.com/v1) — OpenAI-compatible bearer auth.

    Free-tier models (verified): gpt-oss:20b-cloud, gpt-oss:120b-cloud,
    qwen3-coder:480b-cloud, minimax-m2.1:cloud.
    Subscription-only: glm-5.2:cloud, deepseek-v4-*:cloud, kimi-k2.*:cloud.
    """
    from cemaf.llm.openai_compat import OpenAICompatClient

    api_key: str = str(kwargs.get("api_key") or os.getenv("OLLAMA_CLOUD_API_KEY", ""))
    if not api_key:
        raise ValueError("api_key required for Ollama Cloud (or set OLLAMA_CLOUD_API_KEY)")
    return OpenAICompatClient(  # type: ignore[return-value]
        base_url=kwargs.get("base_url", "https://ollama.com/v1"),
        api_key=api_key,
        model=kwargs.get("model", "gpt-oss:120b-cloud"),
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


def _create_huggingface(**kwargs: Any) -> LLMClient:
    from cemaf.llm.openai_compat import OpenAICompatClient

    api_key: str = str(
        kwargs.get("api_key")
        or os.getenv("HF_TOKEN")
        or os.getenv("HUGGINGFACE_API_KEY")
        or os.getenv("HUGGINGFACEHUB_API_TOKEN", "")
    )
    return OpenAICompatClient(  # type: ignore[return-value]
        base_url=kwargs.get("base_url", "https://router.huggingface.co/v1"),
        api_key=api_key,
        model=kwargs.get("model", "google/gemma-2-2b-it"),
        provider=LLMProvider.HUGGINGFACE,
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


def _create_bedrock(**kwargs: Any) -> LLMClient:
    from cemaf.llm.bedrock_cli import BedrockCliLLMClient

    return BedrockCliLLMClient(  # type: ignore[return-value]
        model=kwargs.get("model", os.getenv("BEDROCK_MODEL", "global.anthropic.claude-sonnet-4-6")),
        region=kwargs.get("region", os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))),
        profile=kwargs.get("profile", os.getenv("AWS_PROFILE") or None),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        timeout_seconds=kwargs.get("timeout_seconds", 120.0),
        runner=kwargs.get("runner"),
    )


# Register all providers
llm_registry.register(backend="mock", factory=_create_mock)
llm_registry.register(backend="anthropic", factory=_create_anthropic)
llm_registry.register(backend="openai", factory=_create_openai)
llm_registry.register(backend="ollama", factory=_create_ollama)
llm_registry.register(backend="ollama-tiered", factory=_create_ollama_tiered)
llm_registry.register(backend="ollama-cloud", factory=_create_ollama_cloud)
llm_registry.register(backend="groq", factory=_create_groq)
llm_registry.register(backend="together", factory=_create_together)
llm_registry.register(backend="huggingface", factory=_create_huggingface)
llm_registry.register(backend="gemini", factory=_create_gemini)
llm_registry.register(backend="bedrock", factory=_create_bedrock)


# ---------------------------------------------------------------------------
# Convenience factories
# ---------------------------------------------------------------------------


def create_llm_client(
    provider: str,
    **kwargs: Any,
) -> LLMClient:
    """Create an LLM client for any supported provider.

    Args:
        provider: One of: openai, anthropic, ollama, ollama-cloud, gemini,
            groq, together, huggingface, bedrock, mock
        **kwargs: Provider-specific args (api_key, model, base_url, etc.)

    Examples:
        client = create_llm_client("ollama", model="qwen3.5")
        client = create_llm_client("openai", api_key="sk-...", model="gpt-4o")
        client = create_llm_client("gemini", api_key="AIza...", model="gemini-2.5-flash")
        client = create_llm_client("huggingface", api_key="hf_...", model="google/gemma-2-2b-it")
        client = create_llm_client("bedrock", model="global.anthropic.claude-sonnet-4-6")
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


def create_resilient_llm_client(
    *,
    provider: str = "auto",
    model: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout_seconds: float = 120.0,
    region: str | None = None,
    profile: str | None = None,
    fallback_model: str | None = None,
    enable_caching: bool = False,
    cache_threshold_tokens: int = 1_000,
    metrics: Any | None = None,
) -> LLMClient:
    """Create a resilient text LLM client with provider auto-selection.

    `provider="auto"` prefers OpenAI, then Gemini, then Anthropic based on
    available credentials. Explicit providers delegate to `create_llm_client`.
    """
    resolved_provider = provider.lower()
    if resolved_provider == "auto":
        if os.getenv("OPENAI_API_KEY"):
            resolved_provider = "openai"
        elif os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            resolved_provider = "gemini"
        elif os.getenv("ANTHROPIC_API_KEY"):
            resolved_provider = "anthropic"
        else:
            raise ValueError(
                "No text LLM credentials found. Set OPENAI_API_KEY, GEMINI_API_KEY/GOOGLE_API_KEY, "
                "or ANTHROPIC_API_KEY."
            )

    if resolved_provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        client = create_llm_client(
            "openai",
            api_key=api_key,
            model=model or "gpt-4o-mini",
        )
    elif resolved_provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        if not api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable is required")
        client = create_llm_client(
            "gemini",
            api_key=api_key,
            model=model or "gemini-2.5-flash",
        )
    elif resolved_provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
        client = create_llm_client(
            "anthropic",
            api_key=api_key,
            model=model or "claude-sonnet-4-20250514",
        )
    elif resolved_provider == "bedrock":
        client = create_llm_client(
            "bedrock",
            model=model or os.getenv("BEDROCK_MODEL", "global.anthropic.claude-sonnet-4-6"),
            region=region or os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
            profile=profile if profile is not None else (os.getenv("AWS_PROFILE") or None),
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
    else:
        client = create_llm_client(
            resolved_provider,
            model=model or None,
            timeout_seconds=timeout_seconds,
        )

    return create_resilient_client(
        client=client,
        metrics=metrics,
        fallback_model=fallback_model,
        enable_caching=enable_caching,
        cache_threshold_tokens=cache_threshold_tokens,
    )


def create_model_router(
    routes: list[Any],
    estimator: Any | None = None,
    logger: Any | None = None,
) -> Any:
    """Create a ModelRouter from a list of ModelRoute objects."""
    from cemaf.llm.model_router import ModelRouter

    return ModelRouter(routes=routes, estimator=estimator, logger=logger)


def create_batch_client(
    api_key: str,
    model: str = "claude-sonnet-4-6",
) -> Any:
    """Create a BatchLLMClient for offline high-volume processing."""
    from cemaf.llm.batch_client import BatchLLMClient

    return BatchLLMClient(api_key=api_key, model=model)


def create_resilient_client(
    *,
    client: LLMClient,
    metrics: Any | None = None,
    fallback_model: str | None = None,
    enable_caching: bool = False,
    cache_threshold_tokens: int = 1_000,
) -> LLMClient:
    """Create ResilientLLMClient with sensible defaults.

    Args:
        client: The inner LLMClient to wrap.
        metrics: Optional MetricsCollector for observability.
        fallback_model: Model name to fall back to after repeated failures.
        enable_caching: Wrap with CachedAnthropicLLMClient for prompt caching.
        cache_threshold_tokens: Minimum token count to mark a block cacheable.

    Returns:
        LLMClient (ResilientLLMClient, optionally wrapped in CachedAnthropicLLMClient).
    """
    from cemaf.llm.resilient import ResilientLLMClient
    from cemaf.resilience.circuit_breaker import CircuitBreaker, CircuitConfig
    from cemaf.resilience.rate_limiter import RateLimitConfig, RateLimiter
    from cemaf.resilience.retry import BackoffStrategy, RetryConfig, RetryPolicy

    inner: LLMClient = client
    if enable_caching:
        from cemaf.llm.anthropic_cached import CachedAnthropicLLMClient

        inner = CachedAnthropicLLMClient(
            client=inner,
            cache_threshold_tokens=cache_threshold_tokens,
            metrics=metrics,
        )

    return ResilientLLMClient(
        client=inner,
        retry=RetryPolicy(
            config=RetryConfig(
                max_attempts=3,
                initial_delay_seconds=1.0,
                backoff_strategy=BackoffStrategy.EXPONENTIAL,
            ),
        ),
        circuit_breaker=CircuitBreaker(
            config=CircuitConfig(failure_threshold=5),
        ),
        rate_limiter=RateLimiter(
            config=RateLimitConfig(rate=10.0, burst=20),
        ),
        metrics=metrics,
        fallback_model=fallback_model,
    )


def create_instrumented_client(
    *,
    client: LLMClient,
    run_logger: RunLogger,
    node_id: str | None = None,
    agent_id: str | None = None,
    retry_policy: RetryPolicy | None = None,
) -> InstrumentedLLMClient:
    """Wrap an LLMClient so all calls are recorded to the run logger."""
    return InstrumentedLLMClient(
        client=client,
        run_logger=run_logger,
        node_id=node_id,
        agent_id=agent_id,
        retry_policy=retry_policy,
    )
