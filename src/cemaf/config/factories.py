"""
Factory functions for configuration loading.

Provides convenient ways to load CEMAF settings from various sources
while maintaining the dependency injection principle.
"""

from cemaf.config.loader import EnvConfigSource, SettingsProviderImpl
from cemaf.config.protocols import Settings


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
    provider = SettingsProviderImpl()
    provider.add_source(EnvConfigSource())
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
