"""
Factory functions for configuration loading.

Provides convenient ways to load CEMAF settings from various sources
while maintaining the dependency injection principle.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from cemaf.config.loader import EnvConfigSource, SettingsProviderImpl
from cemaf.config.protocols import ConfigSource, Settings
from cemaf.core.provider_registry import ProviderRegistry

config_source_registry: ProviderRegistry[ConfigSource] = ProviderRegistry(name="config_source")


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"true", "yes", "1", "on"}


def _create_env_config_source(**kwargs: Any) -> ConfigSource:
    return EnvConfigSource(
        prefix=str(kwargs.get("prefix", "CEMAF")),
        separator=str(kwargs.get("separator", "_")),
        lowercase_keys=_coerce_bool(kwargs.get("lowercase_keys"), default=True),
    )


def _create_dict_config_source(**kwargs: Any) -> ConfigSource:
    from cemaf.config.loader import DictConfigSource

    data = kwargs.get("data", {})
    if not isinstance(data, dict):
        raise ValueError("dict config source requires dict data.")
    return DictConfigSource(
        data=data,
        name=str(kwargs.get("name") or "dict"),
    )


config_source_registry.register(backend="env", factory=_create_env_config_source)
config_source_registry.register(backend="dict", factory=_create_dict_config_source)


def create_config_source(
    source_type: str,
    **source_options: Any,
) -> ConfigSource:
    """Build a `ConfigSource` through the registry."""
    return config_source_registry.create(backend=source_type, **source_options)


def create_settings_provider(
    *,
    sources: Sequence[ConfigSource | tuple[int, ConfigSource]] = (),
    source_specs: Sequence[dict[str, Any]] | None = None,
) -> SettingsProviderImpl:
    """Build a settings provider from direct sources and declarative source specs."""
    provider = SettingsProviderImpl()
    for source_entry in sources:
        if isinstance(source_entry, tuple):
            priority, source = source_entry
        else:
            priority, source = 0, source_entry
        provider.add_source(source, priority=priority)

    for spec in source_specs or ():
        spec_copy = dict(spec)
        source_type = str(spec_copy.pop("type", spec_copy.pop("source_type", "")))
        if not source_type:
            raise ValueError("Config source spec requires 'type' or 'source_type'.")
        priority = int(spec_copy.pop("priority", 0))
        provider.add_source(
            create_config_source(source_type, **spec_copy),
            priority=priority,
        )
    return provider


async def load_settings_from_env() -> Settings:
    """
    Load settings from environment variables.

    Reads all CEMAF_* environment variables and constructs Settings object.
    Uses the EnvConfigSource to parse environment variables following the
    CEMAF_<MODULE>_<KEY> naming pattern.

    Returns:
        Configured Settings instance with all 19 modules configured.

    Example:
        >>> settings = await load_settings_from_env()
        >>> print(settings.llm.default_model)
        'gpt-4'
        >>> print(settings.agents.max_iterations)
        10
        >>> print(settings.resilience.max_retries)
        3

    Note:
        This function is async because it uses the SettingsProvider protocol
        which supports async configuration sources (e.g., remote config servers).
    """
    provider = create_settings_provider(source_specs=({"type": "env"},))
    return await provider.get()


def load_settings_from_env_sync() -> Settings:
    """
    Synchronous wrapper for load_settings_from_env().

    Convenience function for contexts where async/await is not available.
    Uses asyncio.run() to execute the async function.

    Returns:
        Configured Settings instance from environment variables.

    Example:
        >>> settings = load_settings_from_env_sync()
        >>> print(settings.cache.enabled)
        True

    Warning:
        This should not be called from within an existing event loop.
        Use load_settings_from_env() if you're already in an async context.
    """
    import asyncio

    return asyncio.run(load_settings_from_env())


# Convenience alias for backward compatibility
get_settings = load_settings_from_env_sync
