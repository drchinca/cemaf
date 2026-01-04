"""
Configuration loaders and settings provider implementation.

Provides concrete implementations for loading configuration
from environment variables, dictionaries, and files.
"""

import os
from collections.abc import AsyncIterator
from typing import Any

from cemaf.config.protocols import (
    ConfigLoadError,
    ConfigSource,
    Settings,
)
from cemaf.core.types import JSON


class EnvConfigSource:
    """
    Load configuration from environment variables.

    Environment variables are loaded with a prefix and converted
    to nested dictionaries using underscore as separator.

    Example:
        CEMAF_LLM_DEFAULT_MODEL=gpt-4 -> {"llm": {"default_model": "gpt-4"}}
    """

    def __init__(
        self,
        prefix: str = "CEMAF",
        separator: str = "_",
        lowercase_keys: bool = True,
    ) -> None:
        """
        Initialize environment config source.

        Args:
            prefix: Environment variable prefix (e.g., "CEMAF").
            separator: Separator for nested keys (default: "_").
            lowercase_keys: Convert keys to lowercase.
        """
        self._prefix = prefix
        self._separator = separator
        self._lowercase_keys = lowercase_keys

    @property
    def name(self) -> str:
        return f"env:{self._prefix}"

    async def load(self) -> JSON:
        """Load configuration from environment variables."""
        result: dict[str, Any] = {}
        prefix_with_sep = f"{self._prefix}{self._separator}"

        for key, value in os.environ.items():
            if not key.startswith(prefix_with_sep):
                continue

            # Remove prefix
            key_without_prefix = key[len(prefix_with_sep) :]

            # Split into parts
            parts = key_without_prefix.split(self._separator)
            if self._lowercase_keys:
                parts = [p.lower() for p in parts]

            # Build nested dict
            current = result
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]

            # Set value (with type coercion)
            current[parts[-1]] = self._coerce_value(value)

        return result

    async def watch(self) -> AsyncIterator[JSON]:
        """Environment variables don't support watching."""
        # Return immediately - no watching support
        return
        yield {}  # noqa: E501 - unreachable code required for generator type

    def _coerce_value(self, value: str) -> Any:
        """Coerce string value to appropriate type."""
        # Boolean
        if value.lower() in ("true", "yes", "1", "on"):
            return True
        if value.lower() in ("false", "no", "0", "off"):
            return False

        # Integer
        try:
            return int(value)
        except ValueError:
            pass

        # Float
        try:
            return float(value)
        except ValueError:
            pass

        # String
        return value


class DictConfigSource:
    """
    Load configuration from a dictionary.

    Useful for testing or providing default values.
    """

    def __init__(self, data: JSON, name: str = "dict") -> None:
        """
        Initialize dictionary config source.

        Args:
            data: Configuration dictionary.
            name: Source identifier.
        """
        self._data = data
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def load(self) -> JSON:
        """Return the dictionary."""
        return dict(self._data)

    async def watch(self) -> AsyncIterator[JSON]:
        """Dictionaries don't change."""
        # Return immediately - no watching support
        return
        yield {}  # noqa: E501 - unreachable code required for generator type


class SettingsProviderImpl:
    """
    Default settings provider implementation.

    Merges configuration from multiple sources in priority order
    and returns validated Settings objects.
    """

    def __init__(self) -> None:
        """Initialize the settings provider."""
        self._sources: list[tuple[int, ConfigSource]] = []
        self._cached_settings: Settings | None = None

    def add_source(self, source: ConfigSource, priority: int = 0) -> None:
        """
        Add a configuration source.

        Args:
            source: The configuration source to add.
            priority: Higher priority sources override lower priority ones.
        """
        self._sources.append((priority, source))
        self._sources.sort(key=lambda x: x[0])
        self._cached_settings = None

    async def get(self) -> Settings:
        """
        Load and merge all sources, returning validated settings.

        Returns:
            Merged and validated Settings object.
        """
        raw = await self.get_raw()
        return Settings.model_validate(raw)

    async def get_raw(self) -> JSON:
        """
        Load and merge all sources without validation.

        Returns:
            Raw merged configuration dictionary.
        """
        merged: dict[str, Any] = {}

        for _, source in self._sources:
            try:
                data = await source.load()
                merged = self._deep_merge(merged, data)
            except Exception as e:
                raise ConfigLoadError(source.name, str(e)) from e

        return merged

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """
        Deep merge two dictionaries.

        Args:
            base: Base dictionary.
            override: Dictionary to merge (takes precedence).

        Returns:
            Merged dictionary.
        """
        result = dict(base)

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result
