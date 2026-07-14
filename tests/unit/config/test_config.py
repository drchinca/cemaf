"""Tests for configuration module."""

import os
from pathlib import Path

import pytest

from cemaf.config.factories import (
    config_source_registry,
    create_config_source,
    create_settings_provider,
    load_settings_from_env,
)
from cemaf.config.loader import (
    DictConfigSource,
    EnvConfigSource,
    SettingsProviderImpl,
)
from cemaf.config.mock import InMemoryConfigSource
from cemaf.config.protocols import (
    LLMSettings,
    Settings,
)
from cemaf.core.defaults import (
    DEFAULT_FREE_CATALOG_BACKEND,
    DEFAULT_FREE_EMBEDDING_DIMENSION,
    DEFAULT_FREE_EMBEDDING_MODEL,
    DEFAULT_FREE_EMBEDDING_PROVIDER,
    DEFAULT_FREE_LLM_MODEL,
    DEFAULT_FREE_LLM_PROVIDER,
)

# =============================================================================
# EnvConfigSource Tests
# =============================================================================


class TestEnvConfigSource:
    """Tests for EnvConfigSource."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Clear relevant env vars before each test."""
        # Remove any CEMAF_ prefixed vars
        for key in list(os.environ.keys()):
            if key.startswith("CEMAF_"):
                monkeypatch.delenv(key, raising=False)

    async def test_load_empty_env(self) -> None:
        """Test loading with no matching env vars."""
        source = EnvConfigSource(prefix="CEMAF")
        result = await source.load()
        assert result == {}

    async def test_load_simple_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading a simple string value."""
        monkeypatch.setenv("CEMAF_DEBUG", "true")
        source = EnvConfigSource(prefix="CEMAF")
        result = await source.load()
        assert result == {"debug": True}

    async def test_load_nested_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading nested configuration using settings field names."""
        monkeypatch.setenv("CEMAF_LLM_DEFAULT_MODEL", "gpt-4")
        source = EnvConfigSource(prefix="CEMAF")
        result = await source.load()
        assert result == {"llm": {"default_model": "gpt-4"}}

    async def test_load_nested_module_with_underscore(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test environment keys for Settings modules whose name has underscores."""
        monkeypatch.setenv("CEMAF_CONTEXT_AGENTS_LIBRARIAN_TOP_K", "3")
        source = EnvConfigSource(prefix="CEMAF")
        result = await source.load()
        assert result == {"context_agents": {"librarian_top_k": 3}}

    async def test_load_integer_coercion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test integer value coercion."""
        monkeypatch.setenv("CEMAF_MAXTOKENS", "4096")
        source = EnvConfigSource(prefix="CEMAF")
        result = await source.load()
        assert result == {"maxtokens": 4096}
        assert isinstance(result["maxtokens"], int)

    async def test_load_float_coercion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test float value coercion."""
        monkeypatch.setenv("CEMAF_TEMPERATURE", "0.7")
        source = EnvConfigSource(prefix="CEMAF")
        result = await source.load()
        assert result == {"temperature": 0.7}
        assert isinstance(result["temperature"], float)

    async def test_load_boolean_coercion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test boolean value coercion."""
        monkeypatch.setenv("CEMAF_ENABLED", "yes")
        monkeypatch.setenv("CEMAF_DISABLED", "no")
        source = EnvConfigSource(prefix="CEMAF")
        result = await source.load()
        assert result["enabled"] is True
        assert result["disabled"] is False

    async def test_source_name(self) -> None:
        """Test source name property."""
        source = EnvConfigSource(prefix="MYAPP")
        assert source.name == "env:MYAPP"

    async def test_watch_not_supported(self) -> None:
        """Test that watching is not supported (exits immediately)."""
        source = EnvConfigSource(prefix="CEMAF")
        # The watch() returns an async generator that immediately returns
        # Iterating should yield nothing
        items = [item async for item in source.watch()]
        assert items == []


# =============================================================================
# DictConfigSource Tests
# =============================================================================


class TestDictConfigSource:
    """Tests for DictConfigSource."""

    async def test_load_empty_dict(self) -> None:
        """Test loading empty dictionary."""
        source = DictConfigSource({})
        result = await source.load()
        assert result == {}

    async def test_load_simple_dict(self) -> None:
        """Test loading simple dictionary."""
        data = {"key": "value", "number": 42}
        source = DictConfigSource(data)
        result = await source.load()
        assert result == data

    async def test_load_nested_dict(self) -> None:
        """Test loading nested dictionary."""
        data = {"outer": {"inner": {"deep": "value"}}}
        source = DictConfigSource(data)
        result = await source.load()
        assert result == data

    async def test_source_name(self) -> None:
        """Test source name property."""
        source = DictConfigSource({}, name="custom")
        assert source.name == "custom"

    async def test_returns_copy(self) -> None:
        """Test that load returns a copy."""
        data = {"key": "value"}
        source = DictConfigSource(data)
        result = await source.load()
        result["key"] = "modified"

        result2 = await source.load()
        assert result2["key"] == "value"


# =============================================================================
# InMemoryConfigSource Tests
# =============================================================================


class TestInMemoryConfigSource:
    """Tests for InMemoryConfigSource."""

    async def test_load_initial_data(self) -> None:
        """Test loading initial data."""
        source = InMemoryConfigSource({"key": "value"})
        result = await source.load()
        assert result == {"key": "value"}

    async def test_update_data(self) -> None:
        """Test updating configuration."""
        source = InMemoryConfigSource({"key": "value"})
        source.update({"key": "new_value"})
        result = await source.load()
        assert result == {"key": "new_value"}

    async def test_set_nested_key(self) -> None:
        """Test setting a nested key."""
        source = InMemoryConfigSource({})
        source.set("outer.inner.deep", "value")
        result = await source.load()
        assert result == {"outer": {"inner": {"deep": "value"}}}

    async def test_source_name(self) -> None:
        """Test source name property."""
        source = InMemoryConfigSource(name="test")
        assert source.name == "test"


# =============================================================================
# SettingsProviderImpl Tests
# =============================================================================


class TestSettingsProviderImpl:
    """Tests for SettingsProviderImpl."""

    async def test_get_default_settings(self) -> None:
        """Test getting default settings with no sources."""
        provider = SettingsProviderImpl()
        settings = await provider.get()
        assert settings.environment == "dev"
        assert settings.debug is False

    async def test_single_source(self) -> None:
        """Test with a single configuration source."""
        provider = SettingsProviderImpl()
        provider.add_source(DictConfigSource({"environment": "prod"}))
        settings = await provider.get()
        assert settings.environment == "prod"

    async def test_source_priority(self) -> None:
        """Test that higher priority sources override lower."""
        provider = SettingsProviderImpl()
        provider.add_source(DictConfigSource({"debug": True}), priority=1)
        provider.add_source(DictConfigSource({"debug": False}), priority=2)
        settings = await provider.get()
        assert settings.debug is False

    async def test_nested_merge(self) -> None:
        """Test deep merging of nested config."""
        provider = SettingsProviderImpl()
        provider.add_source(
            DictConfigSource({"llm": {"default_model": "gpt-3.5"}}),
            priority=1,
        )
        provider.add_source(
            DictConfigSource({"llm": {"timeout_seconds": 60.0}}),
            priority=2,
        )
        settings = await provider.get()
        assert settings.llm.default_model == "gpt-3.5"
        assert settings.llm.timeout_seconds == 60.0

    async def test_get_raw(self) -> None:
        """Test getting raw merged config."""
        provider = SettingsProviderImpl()
        provider.add_source(DictConfigSource({"key": "value"}))
        raw = await provider.get_raw()
        assert raw == {"key": "value"}


# =============================================================================
# Config Factory Tests
# =============================================================================


class TestConfigFactories:
    """Tests for registry-backed config composition."""

    def test_create_env_config_source(self) -> None:
        source = create_config_source("env", prefix="APP", separator="__", lowercase_keys=False)

        assert isinstance(source, EnvConfigSource)
        assert source.name == "env:APP"

    async def test_create_dict_config_source(self) -> None:
        source = create_config_source("dict", data={"environment": "prod"}, name="defaults")

        assert isinstance(source, DictConfigSource)
        assert source.name == "defaults"
        assert await source.load() == {"environment": "prod"}

    def test_invalid_dict_config_source_data_raises(self) -> None:
        with pytest.raises(ValueError, match="dict config source requires dict data"):
            create_config_source("dict", data=("not", "a", "dict"))

    def test_unknown_config_source_mentions_registry(self) -> None:
        with pytest.raises(ValueError, match="config_source_registry.register"):
            create_config_source("consul")

    async def test_supports_custom_registered_source(self) -> None:
        created: dict[str, object] = {}

        def _factory(**kwargs):
            created["args"] = kwargs
            return DictConfigSource({"environment": "stage"}, name="custom")

        config_source_registry.register(backend="custom-test-config-source", factory=_factory)

        source = create_config_source("custom-test-config-source", endpoint="https://config.example")

        assert source.name == "custom"
        assert await source.load() == {"environment": "stage"}
        assert created["args"]["endpoint"] == "https://config.example"

    async def test_create_settings_provider_from_direct_sources_and_specs(self) -> None:
        provider = create_settings_provider(
            sources=((1, DictConfigSource({"environment": "dev"})),),
            source_specs=(
                {
                    "type": "dict",
                    "priority": 2,
                    "data": {"environment": "prod", "debug": True},
                },
            ),
        )

        settings = await provider.get()

        assert settings.environment == "prod"
        assert settings.debug is True

    def test_source_spec_requires_type(self) -> None:
        with pytest.raises(ValueError, match="requires 'type' or 'source_type'"):
            create_settings_provider(source_specs=({"data": {"debug": True}},))

    async def test_load_settings_from_env_uses_env_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in list(os.environ.keys()):
            if key.startswith("CEMAF_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("CEMAF_ENVIRONMENT", "prod")
        monkeypatch.setenv("CEMAF_DEBUG", "true")
        monkeypatch.setenv("CEMAF_LLM_DEFAULT_MODEL", "gpt-4o")

        settings = await load_settings_from_env()

        assert settings.environment == "prod"
        assert settings.debug is True
        assert settings.llm.default_model == "gpt-4o"

    def test_env_example_keys_are_backed_by_settings_or_code(self) -> None:
        """Active CEMAF_* examples should not advertise ignored configuration knobs."""
        root = Path(__file__).parents[3]
        env_keys: list[str] = []
        for line in (root / ".env.example").read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            if key.startswith("CEMAF_"):
                env_keys.append(key)

        src_text = "\n".join(
            path.read_text(errors="ignore") for path in (root / "src" / "cemaf").rglob("*.py")
        )
        source = EnvConfigSource(prefix="CEMAF")
        unknown: list[str] = []

        for key in env_keys:
            parts = [part.lower() for part in key.removeprefix("CEMAF_").split("_")]
            mapped = source._settings_path_parts(parts)
            maps_to_settings = False
            if mapped and mapped[0] in Settings.model_fields:
                if len(mapped) == 1:
                    maps_to_settings = True
                else:
                    model_cls = Settings.model_fields[mapped[0]].annotation
                    fields = getattr(model_cls, "model_fields", {})
                    maps_to_settings = mapped[1] in fields or mapped[0] == "custom"

            if not maps_to_settings and key not in src_text:
                unknown.append(f"{key} -> {'.'.join(mapped)}")

        assert unknown == []

    def test_env_example_defaults_are_free_first(self) -> None:
        """The published env template must not default to paid/hosted providers."""
        root = Path(__file__).parents[3]
        values: dict[str, str] = {}
        for line in (root / ".env.example").read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()

        assert values["CEMAF_LLM_PROVIDER"] == DEFAULT_FREE_LLM_PROVIDER
        assert values["CEMAF_LLM_DEFAULT_MODEL"] == DEFAULT_FREE_LLM_MODEL
        assert values["CEMAF_EMBEDDING_PROVIDER"] == DEFAULT_FREE_EMBEDDING_PROVIDER
        assert values["CEMAF_EMBEDDING_MODEL"] == DEFAULT_FREE_EMBEDDING_MODEL
        assert values["CEMAF_EMBEDDING_DIMENSION"] == str(DEFAULT_FREE_EMBEDDING_DIMENSION)
        assert values["CEMAF_CATALOG_BACKEND"] == DEFAULT_FREE_CATALOG_BACKEND


# =============================================================================
# Settings Model Tests
# =============================================================================


class TestSettings:
    """Tests for Settings model."""

    def test_default_values(self) -> None:
        """Test default settings values."""
        settings = Settings()
        assert settings.environment == "dev"
        assert settings.debug is False
        assert settings.app_name == "cemaf"

    def test_nested_defaults(self) -> None:
        """Test nested default values."""
        settings = Settings()
        assert settings.llm.provider == DEFAULT_FREE_LLM_PROVIDER
        assert settings.llm.default_model == DEFAULT_FREE_LLM_MODEL
        assert settings.retrieval.embedding_provider == DEFAULT_FREE_EMBEDDING_PROVIDER
        assert settings.retrieval.embedding_model == DEFAULT_FREE_EMBEDDING_MODEL
        assert settings.retrieval.embedding_dimension == DEFAULT_FREE_EMBEDDING_DIMENSION
        assert settings.catalog.backend == DEFAULT_FREE_CATALOG_BACKEND
        assert settings.memory.default_ttl_seconds == 3600
        assert settings.cache.enabled is True

    def test_custom_values(self) -> None:
        """Test custom settings values."""
        settings = Settings(
            environment="prod",
            debug=True,
            llm=LLMSettings(default_model="claude-3"),
        )
        assert settings.environment == "prod"
        assert settings.debug is True
        assert settings.llm.default_model == "claude-3"

    def test_frozen(self) -> None:
        """Test that settings are immutable."""
        settings = Settings()
        with pytest.raises(Exception):  # ValidationError for frozen model
            settings.debug = True  # type: ignore

    def test_custom_dict(self) -> None:
        """Test custom settings storage."""
        settings = Settings(custom={"my_key": "my_value"})
        assert settings.custom["my_key"] == "my_value"
