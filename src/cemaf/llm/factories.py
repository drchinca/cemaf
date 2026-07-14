"""Factory functions for LLM client components.

The default path is local/free-first:
    client = create_llm_client("ollama")

Cloud and paid providers remain available through explicit provider names,
credentials, and model choices.
"""

import os
from typing import Any

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import LLMSettings, Settings
from cemaf.core.defaults import DEFAULT_FREE_LLM_MODEL, DEFAULT_FREE_LLM_PROVIDER
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.core.types import LLMProvider
from cemaf.llm.instrumented import InstrumentedLLMClient
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import LLMClient
from cemaf.observability.run_logger import RunLogger
from cemaf.resilience.retry import RetryPolicy

# Global LLM provider registry — extend with your own providers
llm_registry: ProviderRegistry[LLMClient] = ProviderRegistry(name="llm")

OLLAMA_CLOUD_BASE_URL = "https://ollama.com/v1"
DEFAULT_OLLAMA_CLOUD_MODEL = "gpt-oss:120b-cloud"


# ---------------------------------------------------------------------------
# Provider factories
# ---------------------------------------------------------------------------


def _create_mock(**kwargs: Any) -> LLMClient:
    return MockLLMClient(responses=kwargs.get("responses"))


def _create_anthropic(**kwargs: Any) -> LLMClient:
    from cemaf.llm.anthropic import AnthropicLLMClient

    api_key = kwargs.get("api_key") or os.getenv("ANTHROPIC_API_KEY", "")
    model = kwargs.get("model", "claude-sonnet-4-20250514")
    if not api_key:
        raise ValueError("api_key required for Anthropic (or set ANTHROPIC_API_KEY)")
    return AnthropicLLMClient(api_key=api_key, model=model)


def _create_openai(**kwargs: Any) -> LLMClient:
    from cemaf.llm.openai_responses import OpenAIResponsesLLMClient

    api_key: str = str(kwargs.get("api_key") or os.getenv("OPENAI_API_KEY", ""))
    injected_client = kwargs.get("client")
    if not api_key and injected_client is None:
        raise ValueError("api_key required for OpenAI (or set OPENAI_API_KEY)")
    return OpenAIResponsesLLMClient(
        api_key=api_key,
        model=kwargs.get("model", "gpt-5.5"),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        top_p=kwargs.get("top_p", 1.0),
        timeout_seconds=kwargs.get("timeout_seconds", 120.0),
        base_url=kwargs.get("base_url"),
        organization=kwargs.get("organization"),
        project=kwargs.get("project"),
        client=injected_client,
    )


def _create_openai_compatible(**kwargs: Any) -> LLMClient:
    from cemaf.llm.openai_compat import DEFAULT_OPENAI_COMPAT_BASE_URL, OpenAICompatClient

    api_key: str = str(kwargs.get("api_key") or os.getenv("OPENAI_API_KEY", ""))
    return OpenAICompatClient(
        api_key=api_key,
        base_url=kwargs.get("base_url", DEFAULT_OPENAI_COMPAT_BASE_URL),
        model=kwargs.get("model", DEFAULT_FREE_LLM_MODEL),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        top_p=kwargs.get("top_p", 1.0),
        timeout_seconds=kwargs.get("timeout_seconds", 120.0),
        provider=kwargs.get("provider_family", kwargs.get("provider", LLMProvider.OLLAMA)),
    )


def _create_ollama(**kwargs: Any) -> LLMClient:
    from cemaf.llm.ollama import DEFAULT_BASE_URL, create_ollama_client

    return create_ollama_client(
        model=kwargs.get("model", DEFAULT_FREE_LLM_MODEL),
        base_url=kwargs.get("base_url", DEFAULT_BASE_URL),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
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

    Model availability and billing tiers are controlled by Ollama. CEMAF keeps
    one practical default and lets callers override `model` for their account.
    """
    from cemaf.llm.openai_compat import OpenAICompatClient

    api_key: str = str(kwargs.get("api_key") or os.getenv("OLLAMA_CLOUD_API_KEY", ""))
    if not api_key:
        raise ValueError("api_key required for Ollama Cloud (or set OLLAMA_CLOUD_API_KEY)")
    return OpenAICompatClient(
        base_url=kwargs.get("base_url", OLLAMA_CLOUD_BASE_URL),
        api_key=api_key,
        model=kwargs.get("model", DEFAULT_OLLAMA_CLOUD_MODEL),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        top_p=kwargs.get("top_p", 1.0),
        timeout_seconds=kwargs.get("timeout_seconds", 120.0),
        provider=LLMProvider.OLLAMA,
    )


def _create_groq(**kwargs: Any) -> LLMClient:
    from cemaf.llm.openai_compat import OpenAICompatClient

    api_key: str = str(kwargs.get("api_key") or os.getenv("GROQ_API_KEY", ""))
    return OpenAICompatClient(
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key,
        model=kwargs.get("model", "llama-3.3-70b-versatile"),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        top_p=kwargs.get("top_p", 1.0),
        timeout_seconds=kwargs.get("timeout_seconds", 120.0),
        provider=LLMProvider.GROQ,
    )


def _create_together(**kwargs: Any) -> LLMClient:
    from cemaf.llm.openai_compat import OpenAICompatClient

    api_key: str = str(kwargs.get("api_key") or os.getenv("TOGETHER_API_KEY", ""))
    return OpenAICompatClient(
        base_url="https://api.together.xyz/v1",
        api_key=api_key,
        model=kwargs.get("model", "Llama-3.3-70B-Instruct-Turbo"),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        top_p=kwargs.get("top_p", 1.0),
        timeout_seconds=kwargs.get("timeout_seconds", 120.0),
        provider=LLMProvider.TOGETHER,
    )


def _create_huggingface(**kwargs: Any) -> LLMClient:
    from cemaf.llm.openai_compat import OpenAICompatClient

    api_key: str = str(
        kwargs.get("api_key")
        or os.getenv("HF_TOKEN")
        or os.getenv("HUGGINGFACE_API_KEY")
        or os.getenv("HUGGINGFACEHUB_API_TOKEN", "")
    )
    return OpenAICompatClient(
        base_url=kwargs.get("base_url", "https://router.huggingface.co/v1"),
        api_key=api_key,
        model=kwargs.get("model", "google/gemma-2-2b-it"),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        top_p=kwargs.get("top_p", 1.0),
        timeout_seconds=kwargs.get("timeout_seconds", 120.0),
        provider=LLMProvider.HUGGINGFACE,
    )


def _create_gemini(**kwargs: Any) -> LLMClient:
    from cemaf.llm.gemini import GeminiClient

    # Check if we are running in Vertex mode
    use_vertex = kwargs.get("use_vertex")
    if use_vertex is None:
        has_gcp_env = any(os.getenv(v) for v in ["VERTEX_PROJECT", "GCP_PROJECT", "GOOGLE_CLOUD_PROJECT"])
        has_gemini_key = bool(
            kwargs.get("api_key") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        )
        use_vertex = has_gcp_env and not has_gemini_key

    if use_vertex:
        return _create_vertex(**kwargs)

    api_key = kwargs.get("api_key") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    if not api_key:
        raise ValueError("api_key required for Gemini (or set GEMINI_API_KEY)")
    return GeminiClient(
        api_key=api_key,
        model=kwargs.get("model", "gemini-2.5-flash"),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        top_p=kwargs.get("top_p", 1.0),
        timeout_seconds=kwargs.get("timeout_seconds", 120.0),
        provider=LLMProvider.GEMINI,
    )


def _create_vertex(**kwargs: Any) -> LLMClient:
    from cemaf.llm.gemini import GeminiClient

    return GeminiClient(
        api_key=kwargs.get("api_key"),
        model=kwargs.get("model", "gemini-2.5-flash"),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 4096),
        top_p=kwargs.get("top_p", 1.0),
        timeout_seconds=kwargs.get("timeout_seconds", 120.0),
        use_vertex=True,
        gcp_project=kwargs.get("gcp_project"),
        location=kwargs.get("location"),
        access_token=kwargs.get("access_token"),
        provider=LLMProvider.VERTEX,
    )


def _create_bedrock(**kwargs: Any) -> LLMClient:
    from cemaf.llm.bedrock_cli import BedrockCliLLMClient

    return BedrockCliLLMClient(
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
llm_registry.register(backend="openai-responses", factory=_create_openai)
llm_registry.register(backend="openai-compatible", factory=_create_openai_compatible)
llm_registry.register(backend="openai-compat", factory=_create_openai_compatible)
llm_registry.register(backend="ollama", factory=_create_ollama)
llm_registry.register(backend="ollama-tiered", factory=_create_ollama_tiered)
llm_registry.register(backend="ollama-cloud", factory=_create_ollama_cloud)
llm_registry.register(backend="groq", factory=_create_groq)
llm_registry.register(backend="together", factory=_create_together)
llm_registry.register(backend="huggingface", factory=_create_huggingface)
llm_registry.register(backend="gemini", factory=_create_gemini)
llm_registry.register(backend="vertex", factory=_create_vertex)
llm_registry.register(backend="vertex-ai", factory=_create_vertex)
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
        provider: Any backend registered in `llm_registry`.
        **kwargs: Provider-specific args (api_key, model, base_url, etc.)

    Examples:
        client = create_llm_client("ollama")
        client = create_llm_client("openai-compatible", base_url="http://localhost:8000/v1", model="qwen")

        # Cloud/paid adapters are explicit opt-in:
        client = create_llm_client("openai", api_key="...", model="...")
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
    return llm_registry.create(
        backend=provider,
        **_llm_settings_kwargs(cfg.llm),
    )


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

    `provider="auto"` uses the project's free-first default unless
    `CEMAF_LLM_PROVIDER` explicitly names another backend. Explicit providers
    delegate to `create_llm_client`.
    """
    resolved_provider = provider.lower()
    if resolved_provider == "auto":
        configured_provider = os.getenv("CEMAF_LLM_PROVIDER", "").strip().lower()
        resolved_provider = (
            configured_provider
            if configured_provider and configured_provider != "auto"
            else DEFAULT_FREE_LLM_PROVIDER
        )

    if resolved_provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        client = create_llm_client(
            "openai",
            api_key=api_key,
            model=model or "gpt-5.5",
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
    elif resolved_provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        if not api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable is required")
        client = create_llm_client(
            "gemini",
            api_key=api_key,
            model=model or "gemini-2.5-flash",
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
    elif resolved_provider in ("vertex", "vertex-ai"):
        client = create_llm_client(
            "vertex",
            model=model or "gemini-2.5-flash",
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            gcp_project=(
                os.getenv("VERTEX_PROJECT") or os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
            ),
            location=(
                os.getenv("VERTEX_LOCATION") or os.getenv("GCP_LOCATION") or os.getenv("GOOGLE_CLOUD_REGION")
            ),
            access_token=(
                os.getenv("VERTEX_ACCESS_TOKEN")
                or os.getenv("GCP_ACCESS_TOKEN")
                or os.getenv("GCLOUD_ACCESS_TOKEN")
            ),
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
    elif resolved_provider == "ollama":
        client = create_llm_client(
            "ollama",
            model=model or DEFAULT_FREE_LLM_MODEL,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
    elif resolved_provider == "ollama-tiered":
        client = create_llm_client(
            "ollama-tiered",
            timeout_seconds=timeout_seconds,
        )
    else:
        kwargs: dict[str, Any] = {"timeout_seconds": timeout_seconds}
        if model:
            kwargs["model"] = model
        client = create_llm_client(resolved_provider, **kwargs)

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
    model: str,
) -> Any:
    """Create an Anthropic BatchLLMClient with an explicit provider model."""
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


def _llm_settings_kwargs(settings: LLMSettings) -> dict[str, Any]:
    """Convert configured LLM settings into provider kwargs without leaking class defaults."""
    defaults = LLMSettings()
    kwargs: dict[str, Any] = {}
    if settings.api_key:
        kwargs["api_key"] = settings.api_key
    if settings.default_model and settings.default_model != defaults.default_model:
        kwargs["model"] = settings.default_model
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    if settings.default_temperature != defaults.default_temperature:
        kwargs["temperature"] = settings.default_temperature
    if settings.max_tokens != defaults.max_tokens:
        kwargs["max_tokens"] = settings.max_tokens
    if settings.timeout_seconds != defaults.timeout_seconds:
        kwargs["timeout_seconds"] = settings.timeout_seconds
    return kwargs
