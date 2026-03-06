"""Contract tests for ProviderRegistry."""

import pytest


class TestProviderRegistryContract:
    """Contract: ProviderRegistry maps backend names to factory callables."""

    def test_register_and_create(self) -> None:
        """Registered factory must be callable via create()."""
        from cemaf.core.provider_registry import ProviderRegistry

        registry: ProviderRegistry[str] = ProviderRegistry(name="test")
        registry.register(backend="mock", factory=lambda **kw: "mock-instance")

        result = registry.create(backend="mock")
        assert result == "mock-instance"

    def test_unknown_backend_raises(self) -> None:
        """Unknown backend must raise ValueError with available backends listed."""
        from cemaf.core.provider_registry import ProviderRegistry

        registry: ProviderRegistry[str] = ProviderRegistry(name="test")
        registry.register(backend="mock", factory=lambda **kw: "mock")

        with pytest.raises(ValueError, match="mock"):
            registry.create(backend="unknown")

    def test_kwargs_forwarded_to_factory(self) -> None:
        """All kwargs passed to create() must be forwarded to the factory."""
        from cemaf.core.provider_registry import ProviderRegistry

        received: dict = {}

        def capture_factory(**kwargs: object) -> str:
            received.update(kwargs)
            return "ok"

        registry: ProviderRegistry[str] = ProviderRegistry(name="test")
        registry.register(backend="custom", factory=capture_factory)

        registry.create(backend="custom", api_key="secret", model="gpt-4")
        assert received == {"api_key": "secret", "model": "gpt-4"}

    def test_list_backends(self) -> None:
        """list_backends() must return all registered backend names."""
        from cemaf.core.provider_registry import ProviderRegistry

        registry: ProviderRegistry[str] = ProviderRegistry(name="test")
        registry.register(backend="a", factory=lambda **kw: "a")
        registry.register(backend="b", factory=lambda **kw: "b")

        assert sorted(registry.list_backends()) == ["a", "b"]

    def test_duplicate_register_overwrites(self) -> None:
        """Re-registering a backend must overwrite the previous factory."""
        from cemaf.core.provider_registry import ProviderRegistry

        registry: ProviderRegistry[str] = ProviderRegistry(name="test")
        registry.register(backend="x", factory=lambda **kw: "old")
        registry.register(backend="x", factory=lambda **kw: "new")

        assert registry.create(backend="x") == "new"

    def test_has_backend(self) -> None:
        """has() must return True for registered backends."""
        from cemaf.core.provider_registry import ProviderRegistry

        registry: ProviderRegistry[str] = ProviderRegistry(name="test")
        registry.register(backend="mock", factory=lambda **kw: "mock")

        assert registry.has(backend="mock") is True
        assert registry.has(backend="missing") is False
