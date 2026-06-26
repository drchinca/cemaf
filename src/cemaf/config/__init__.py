"""
Configuration management module.

Provides YAML, JSON, and environment variable configuration loading
with support for hot-reload and multi-source merging.
"""

from cemaf.config.factories import (
    config_source_registry,
    create_config_source,
    create_settings_provider,
    get_settings,
    load_settings_from_env,
    load_settings_from_env_sync,
)
from cemaf.config.loader import (
    DictConfigSource,
    EnvConfigSource,
    SettingsProviderImpl,
)
from cemaf.config.mock import InMemoryConfigSource
from cemaf.config.protocols import (
    ConfigSource,
    Settings,
    SettingsProvider,
)

__all__ = [
    # Protocols
    "ConfigSource",
    "Settings",
    "SettingsProvider",
    # Factories
    "config_source_registry",
    "create_config_source",
    "create_settings_provider",
    "get_settings",
    "load_settings_from_env",
    "load_settings_from_env_sync",
    # Implementations
    "EnvConfigSource",
    "DictConfigSource",
    "SettingsProviderImpl",
    # Mock
    "InMemoryConfigSource",
]
