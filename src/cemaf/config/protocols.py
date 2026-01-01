"""
Configuration protocols and base types.

Defines the contracts for configuration sources and settings management.
"""

from collections.abc import AsyncIterator
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cemaf.core.types import JSON


@runtime_checkable
class ConfigSource(Protocol):
    """
    Protocol for configuration sources.

    A ConfigSource can load configuration from any source:
    - Files (YAML, JSON, TOML)
    - Environment variables
    - Remote services (Consul, etcd)
    - Databases
    """

    @property
    def name(self) -> str:
        """Unique identifier for this source."""
        ...

    async def load(self) -> JSON:
        """
        Load configuration from this source.

        Returns:
            Configuration dictionary.

        Raises:
            ConfigLoadError: If loading fails.
        """
        ...

    async def watch(self) -> AsyncIterator[JSON]:
        """
        Watch for configuration changes (hot-reload).

        Yields:
            Updated configuration when changes occur.

        Note:
            This is an infinite async iterator. Use `async for` to consume.
            Implementations may raise StopAsyncIteration if watching is not supported.
        """
        ...


class LLMSettings(BaseModel):
    """Settings for LLM configuration."""

    model_config = {"frozen": True}

    provider: Literal["mock", "openai", "anthropic", "azure", "bedrock", "vertex", "ollama"] = "mock"
    default_model: str = "gpt-4"
    api_key: str = ""
    base_url: str = ""
    default_temperature: float = 0.7
    max_tokens: int = 4096
    timeout_seconds: float = 30.0
    max_retries: int = 3


class MemorySettings(BaseModel):
    """Settings for memory configuration."""

    model_config = {"frozen": True}

    default_ttl_seconds: int = 3600
    max_items: int = 10000


class CacheSettings(BaseModel):
    """Settings for cache configuration."""

    model_config = {"frozen": True}

    enabled: bool = True
    backend: Literal["memory", "ttl", "redis", "memcached"] = "memory"
    default_ttl_seconds: int = 3600
    max_size: int = 1000


class ObservabilitySettings(BaseModel):
    """Settings for observability configuration."""

    model_config = {"frozen": True}

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    enable_tracing: bool = False
    enable_metrics: bool = False


class RetrievalSettings(BaseModel):
    """Settings for retrieval/vector store configuration."""

    model_config = {"frozen": True}

    # Vector store backend: memory, pinecone, qdrant, weaviate, chroma, pgvector, faiss
    vector_store_backend: Literal[
        "memory", "pinecone", "qdrant", "weaviate", "chroma", "pgvector", "faiss"
    ] = "memory"

    # Embedding provider: openai, cohere, sentence-transformers, huggingface
    embedding_provider: str = "openai"

    # Embedding model name
    embedding_model: str = "text-embedding-3-small"

    # Embedding dimension (auto-detected for most providers)
    embedding_dimension: int = 1536


class ResilienceSettings(BaseModel):
    """Settings for resilience patterns (retry, circuit breaker, rate limiting)."""

    model_config = {"frozen": True}

    # Retry configuration
    max_retries: int = 3
    initial_retry_delay_seconds: float = 1.0
    max_retry_delay_seconds: float = 60.0
    retry_backoff_strategy: Literal["constant", "linear", "exponential", "fibonacci"] = "exponential"
    retry_backoff_multiplier: float = 2.0
    retry_jitter: bool = True

    # Circuit breaker configuration
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_failure_window_seconds: float = 60.0
    circuit_breaker_recovery_timeout_seconds: float = 30.0
    circuit_breaker_success_threshold: int = 2

    # Rate limiter configuration
    rate_limit_requests_per_second: float = 10.0
    rate_limit_burst: int = 10
    rate_limit_wait_on_limit: bool = True
    rate_limit_max_wait_seconds: float = 30.0


class AgentsSettings(BaseModel):
    """Settings for agent execution."""

    model_config = {"frozen": True}

    max_iterations: int = 10
    max_skill_calls: int = 50
    timeout_seconds: float = 300.0

    # DeepAgent configuration
    deep_agent_max_depth: int = 5
    deep_agent_max_children: int = 10
    deep_agent_max_total: int = 100
    deep_agent_timeout_seconds: float = 600.0


class SchedulerSettings(BaseModel):
    """Settings for task scheduling."""

    model_config = {"frozen": True}

    max_concurrent_jobs: int = 10
    default_job_timeout_seconds: float = 300.0
    default_max_retries: int = 3
    enable_persistence: bool = False
    check_interval_seconds: float = 1.0


class MCPSettings(BaseModel):
    """Settings for Model Context Protocol."""

    model_config = {"frozen": True}

    transport_type: Literal["stdio", "sse", "websocket"] = "stdio"
    server_timeout_seconds: float = 30.0
    max_message_size_bytes: int = 1_048_576  # 1MB
    enable_tool_bridge: bool = True
    enable_resource_bridge: bool = True
    enable_prompt_bridge: bool = True


class ModerationSettings(BaseModel):
    """Settings for content moderation."""

    model_config = {"frozen": True}

    enabled: bool = True
    fail_on_violation: bool = True
    enable_pii_detection: bool = True
    enable_profanity_filter: bool = True
    enable_toxicity_check: bool = False
    toxicity_threshold: float = 0.7
    llm_model: str = "gpt-4"


class OrchestrationSettings(BaseModel):
    """Settings for DAG orchestration."""

    model_config = {"frozen": True}

    max_parallel_nodes: int = 10
    max_dag_depth: int = 50
    default_checkpoint_interval: int = 1
    enable_cycle_detection: bool = True
    cycle_detection_limit: int = 1000
    enable_logging: bool = True
    enable_events: bool = True
    enable_moderation: bool = False


class EventsSettings(BaseModel):
    """Settings for event bus."""

    model_config = {"frozen": True}

    enable_event_bus: bool = True
    max_queue_size: int = 10000
    enable_async_handlers: bool = True
    enable_batch_publish: bool = True
    batch_size: int = 100
    batch_timeout_seconds: float = 1.0


class StreamingSettings(BaseModel):
    """Settings for streaming."""

    model_config = {"frozen": True}

    buffer_size: int = 1000
    enable_progress_callbacks: bool = True
    chunk_timeout_seconds: float = 30.0
    enable_cancellation: bool = True


class ValidationSettings(BaseModel):
    """Settings for validation pipeline."""

    model_config = {"frozen": True}

    strict_mode: bool = False
    fail_fast: bool = False
    enable_warnings: bool = True
    enable_suggestions: bool = True


class BlueprintSettings(BaseModel):
    """Settings for blueprint management."""

    model_config = {"frozen": True}

    strict_validation: bool = False
    require_all_fields: bool = False
    enable_content_quality_check: bool = True
    min_scene_goal_length: int = 10


class CitationSettings(BaseModel):
    """Settings for citation tracking."""

    model_config = {"frozen": True}

    enable_tracking: bool = True
    require_citations: bool = False
    citation_format: Literal["apa", "mla", "chicago", "ieee"] = "apa"
    enable_validation: bool = True


class ToolsSettings(BaseModel):
    """Settings for tool execution."""

    model_config = {"frozen": True}

    enable_call_recording: bool = True
    max_tool_timeout_seconds: float = 60.0
    enable_moderation: bool = False
    enable_caching: bool = True


class GenerationSettings(BaseModel):
    """Settings for media/code generation."""

    model_config = {"frozen": True}

    # Image generation
    default_image_width: int = 1024
    default_image_height: int = 1024
    default_image_format: Literal["png", "jpeg", "webp", "svg", "gif"] = "png"

    # Audio generation
    default_audio_format: Literal["mp3", "wav", "ogg", "flac"] = "mp3"
    default_sample_rate: int = 44100

    # Video generation
    default_video_width: int = 1920
    default_video_height: int = 1080
    default_video_fps: int = 24
    default_video_format: Literal["mp4", "webm", "mov", "gif"] = "mp4"

    # Code generation
    default_code_language: Literal[
        "python", "typescript", "javascript", "rust", "go", "java", "sql", "html", "css", "shell"
    ] = "python"
    include_tests: bool = False
    include_docs: bool = True


class EvalsSettings(BaseModel):
    """Settings for evaluation."""

    model_config = {"frozen": True}

    pass_threshold: float = 0.5
    fail_fast: bool = False
    include_reasoning: bool = True
    llm_model: str = "gpt-4"
    max_tokens: int = 1000
    temperature: float = 0.0
    enable_semantic_similarity: bool = True
    similarity_threshold: float = 0.8


class Settings(BaseModel):
    """
    Main application settings.

    Validated, typed settings container that can be populated
    from multiple configuration sources.
    """

    model_config = {"frozen": True}

    # Environment
    environment: Literal["dev", "staging", "prod"] = "dev"
    debug: bool = False

    # Application
    app_name: str = "cemaf"
    version: str = "0.1.0"

    # Nested settings
    llm: LLMSettings = Field(default_factory=LLMSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)

    # NEW: Additional module settings
    resilience: ResilienceSettings = Field(default_factory=ResilienceSettings)
    agents: AgentsSettings = Field(default_factory=AgentsSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    moderation: ModerationSettings = Field(default_factory=ModerationSettings)
    orchestration: OrchestrationSettings = Field(default_factory=OrchestrationSettings)
    events: EventsSettings = Field(default_factory=EventsSettings)
    streaming: StreamingSettings = Field(default_factory=StreamingSettings)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    blueprint: BlueprintSettings = Field(default_factory=BlueprintSettings)
    citation: CitationSettings = Field(default_factory=CitationSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    generation: GenerationSettings = Field(default_factory=GenerationSettings)
    evals: EvalsSettings = Field(default_factory=EvalsSettings)

    # Custom settings (extensible)
    custom: JSON = Field(default_factory=dict)


@runtime_checkable
class SettingsProvider(Protocol):
    """
    Protocol for settings providers.

    A SettingsProvider merges configuration from multiple sources
    and returns validated Settings objects.
    """

    def add_source(self, source: ConfigSource, priority: int = 0) -> None:
        """
        Add a configuration source.

        Args:
            source: The configuration source to add.
            priority: Higher priority sources override lower priority ones.
        """
        ...

    async def get(self) -> Settings:
        """
        Load and merge all sources, returning validated settings.

        Returns:
            Merged and validated Settings object.

        Raises:
            ConfigLoadError: If any source fails to load.
            ValidationError: If merged config is invalid.
        """
        ...

    async def get_raw(self) -> JSON:
        """
        Load and merge all sources without validation.

        Returns:
            Raw merged configuration dictionary.
        """
        ...


class ConfigLoadError(Exception):
    """Raised when configuration loading fails."""

    def __init__(self, source: str, message: str) -> None:
        self.source = source
        self.message = message
        super().__init__(f"Failed to load config from '{source}': {message}")
