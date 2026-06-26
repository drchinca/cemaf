"""Tests for orchestration factory helpers."""

from cemaf.orchestration.factories import create_executor_config, create_runtime_services


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


def test_create_runtime_services_preserves_dependencies() -> None:
    run_logger = object()
    event_bus = object()

    services = create_runtime_services(
        run_logger=run_logger,  # type: ignore[arg-type]
        event_bus=event_bus,  # type: ignore[arg-type]
        max_recovery_attempts=5,
    )

    assert services.run_logger is run_logger
    assert services.event_bus is event_bus
    assert services.max_recovery_attempts == 5
