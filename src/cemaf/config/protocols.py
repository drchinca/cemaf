"""
Configuration protocols and base types.

Defines the contracts for configuration sources and settings management.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol, runtime_checkable

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
    
    default_model: str = "gpt-4"
    default_temperature: float = 0.7
    max_tokens: int = 4096
    timeout_seconds: float = 30.0


class MemorySettings(BaseModel):
    """Settings for memory configuration."""
    
    model_config = {"frozen": True}
    
    default_ttl_seconds: int = 3600
    max_items: int = 10000


class CacheSettings(BaseModel):
    """Settings for cache configuration."""
    
    model_config = {"frozen": True}
    
    enabled: bool = True
    default_ttl_seconds: int = 3600
    max_size: int = 1000


class ObservabilitySettings(BaseModel):
    """Settings for observability configuration."""
    
    model_config = {"frozen": True}
    
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    enable_tracing: bool = False
    enable_metrics: bool = False


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

