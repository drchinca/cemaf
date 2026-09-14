"""Tests for orchestration factory helpers."""

from cemaf.context.budget import TokenBudget
from cemaf.datasources.registry import DataSourceRegistry
from cemaf.interceptors.pull import PullInterceptor
from cemaf.orchestration.factories import (
    create_executor_config,
    create_pull_interceptor,
    create_runtime_services,
)


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


def test_create_runtime_services_preserves_data_source_registry() -> None:
    registry = DataSourceRegistry()

    services = create_runtime_services(data_source_registry=registry)

    assert services.data_source_registry is registry


def test_create_pull_interceptor_wires_from_runtime_services() -> None:
    """Closes the gap where RuntimeServices.data_source_registry had no
    composition-root consumer — proves the factory actually reads it."""
    registry = DataSourceRegistry()
    knowledge_graph = object()
    services = create_runtime_services(
        data_source_registry=registry,
        knowledge_graph=knowledge_graph,  # type: ignore[arg-type]
    )

    interceptor = create_pull_interceptor(services=services, pull_tokens=1000)

    assert isinstance(interceptor, PullInterceptor)
    assert interceptor._registry is registry
    assert interceptor._knowledge_graph is knowledge_graph


def test_create_pull_interceptor_forwards_extra_kwargs() -> None:
    services = create_runtime_services()

    interceptor = create_pull_interceptor(services=services, pull_tokens=500, node_pattern="specific_node")

    assert interceptor._pattern == "specific_node"


def test_create_pull_interceptor_wires_token_budget_for_reconciliation() -> None:
    """Closes the token-budget reconciliation gap: PullInterceptor must read
    RuntimeServices.token_budget through the composition-root factory, not
    just knowledge_graph/data_source_registry."""
    budget = TokenBudget(max_tokens=50_000)
    services = create_runtime_services(token_budget=budget)

    interceptor = create_pull_interceptor(services=services, pull_tokens=1000)

    assert interceptor._token_budget is budget
