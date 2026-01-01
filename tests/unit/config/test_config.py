"""Tests for configuration module."""

from __future__ import annotations

import os

import pytest

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
        """Test loading nested configuration (splits on all underscores)."""
        monkeypatch.setenv("CEMAF_LLM_MODEL", "gpt-4")
        source = EnvConfigSource(prefix="CEMAF")
        result = await source.load()
        assert result == {"llm": {"model": "gpt-4"}}

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
        assert settings.llm.default_model == "gpt-4"
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
