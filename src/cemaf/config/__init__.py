"""
Configuration management module.

Provides YAML, JSON, and environment variable configuration loading
with support for hot-reload and multi-source merging.
"""

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
    # Implementations
    "EnvConfigSource",
    "DictConfigSource",
    "SettingsProviderImpl",
    # Mock
    "InMemoryConfigSource",
]
