"""ProviderRegistry — extensible backend/provider selection without if/elif chains."""

from collections.abc import Callable
from typing import Any


class ProviderRegistry[T]:
    """Maps backend names to factory callables for extensible provider selection."""

    def __init__(self, *, name: str) -> None:
        self._name = name
        self._factories: dict[str, Callable[..., T]] = {}

    def register(self, *, backend: str, factory: Callable[..., T]) -> None:
        """Register a factory for a backend name."""
        self._factories[backend] = factory

    def create(self, *, backend: str, **kwargs: Any) -> T:
        """Create an instance using the registered factory for the given backend."""
        factory = self._factories.get(backend)
        if factory is None:
            available = ", ".join(sorted(self._factories.keys())) or "(none)"
            raise ValueError(
                f"Unsupported {self._name} backend: {backend}. "
                f"Available: {available}. "
                f"Register your own with {self._name}_registry.register(backend=..., factory=...)"
            )
        return factory(**kwargs)

    def has(self, *, backend: str) -> bool:
        """Check if a backend is registered."""
        return backend in self._factories

    def list_backends(self) -> list[str]:
        """List all registered backend names."""
        return list(self._factories.keys())

    def __repr__(self) -> str:
        return f"ProviderRegistry(name={self._name!r}, backends={self.list_backends()})"
