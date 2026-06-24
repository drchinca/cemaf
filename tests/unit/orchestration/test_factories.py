"""Tests for orchestration factory helpers."""

from cemaf.orchestration.factories import create_executor_config


def test_create_executor_config_preserves_overrides() -> None:
    config = create_executor_config(
        max_parallel=4,
        enable_logging=False,
        enable_events=False,
        enable_moderation=True,
        node_timeout_seconds=12.5,
    )

    assert config.max_parallel == 4
    assert config.enable_logging is False
    assert config.enable_events is False
    assert config.enable_moderation is True
    assert config.node_timeout_seconds == 12.5
