"""
Mock implementations for testing configuration.
"""

import asyncio
from collections.abc import AsyncIterator

from cemaf.core.types import JSON


class InMemoryConfigSource:
    """
    In-memory configuration source for testing.

    Supports hot-reload simulation by allowing config updates
    after initialization.
    """

    def __init__(self, data: JSON | None = None, name: str = "memory") -> None:
        """
        Initialize in-memory config source.

        Args:
            data: Initial configuration dictionary.
            name: Source identifier.
        """
        self._data: JSON = data or {}
        self._name = name
        self._watchers: list[asyncio.Queue[JSON]] = []

    @property
    def name(self) -> str:
        return self._name

    async def load(self) -> JSON:
        """Return current configuration."""
        return dict(self._data)

    async def watch(self) -> AsyncIterator[JSON]:
        """
        Watch for configuration changes.

        Use `update()` to trigger changes.
        """
        queue: asyncio.Queue[JSON] = asyncio.Queue()
        self._watchers.append(queue)

        try:
            while True:
                data = await queue.get()
                yield data
        finally:
            self._watchers.remove(queue)

    def update(self, data: JSON) -> None:
        """
        Update configuration and notify watchers.

        Args:
            data: New configuration dictionary.
        """
        self._data = data

        for queue in self._watchers:
            queue.put_nowait(dict(data))

    def set(self, key: str, value: object) -> None:
        """
        Set a single configuration value.

        Args:
            key: Configuration key (dot-separated for nested).
            value: Configuration value.
        """
        parts = key.split(".")
        current = self._data

        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]  # type: ignore[assignment]

        current[parts[-1]] = value  # type: ignore[index]

        for queue in self._watchers:
            queue.put_nowait(dict(self._data))
