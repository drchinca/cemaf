"""
Integration tests for DAG orchestration health checks.

Tests that health checks properly detect unavailable dependencies
and prevent execution before wasting computational resources.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from cemaf.context.context import Context
from cemaf.core.enums import RunStatus
from cemaf.observability.health import (
    HealthStatus,
    reset_health_monitor,
)
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import DAGExecutor
from cemaf.orchestration.health_checks import (
    OrchestrationHealthRegistry,
    create_cache_health_check,
    create_event_bus_health_check,
    create_llm_health_check,
    create_memory_health_check,
    create_persistence_health_check,
    create_tool_registry_health_check,
)


@pytest.fixture(autouse=True)
def reset_health():
    """Reset health monitor before each test."""
    reset_health_monitor()
    yield
    reset_health_monitor()


@pytest.fixture
def simple_dag():
    """Create a simple DAG for testing."""
    dag = DAG(name="test_dag")
    dag = dag.add_node(Node.tool(id="node1", name="Node 1", tool_id="test_tool", output_key="out"))
    return dag


@pytest.fixture
def mock_node_executor():
    """Create a mock node executor."""
    executor = Mock()
    executor.execute_node = AsyncMock(
        return_value=(Mock(success=True, output={"result": "success"}), Context())
    )
    return executor


class TestHealthCheckCreators:
    """Test health check factory functions."""

    def test_create_llm_health_check_healthy(self):
        """Test LLM health check when service is healthy."""
        llm_client = Mock()
        llm_client.model_id = "gpt-4"

        check = create_llm_health_check(llm_client)
        result = check()

        assert result.status == HealthStatus.HEALTHY
        assert result.name == "llm"
        assert "available" in result.message.lower()

    def test_create_llm_health_check_unhealthy(self):
        """Test LLM health check when service is unavailable."""

        # Create an object that's not callable and has no model_id
        class BadLLM:
            pass

        llm_client = BadLLM()

        check = create_llm_health_check(llm_client)
        result = check()

        assert result.status == HealthStatus.UNHEALTHY
        assert result.name == "llm"

    def test_create_memory_health_check_healthy(self):
        """Test memory health check when store is healthy."""
        memory_store = Mock()
        memory_store.get_scopes = Mock(return_value=[])

        check = create_memory_health_check(memory_store)
        result = check()

        assert result.status == HealthStatus.HEALTHY
        assert result.name == "memory"

    def test_create_memory_health_check_unhealthy(self):
        """Test memory health check when store is unavailable."""
        memory_store = Mock()
        memory_store.get_scopes = Mock(side_effect=Exception("Connection failed"))

        check = create_memory_health_check(memory_store)
        result = check()

        assert result.status == HealthStatus.UNHEALTHY
        assert result.name == "memory"

    def test_create_cache_health_check_degraded(self):
        """Test cache health check when cache is degraded."""
        cache_store = Mock()
        cache_store.stats = Mock(return_value={"errors": 5})

        check = create_cache_health_check(cache_store)
        result = check()

        assert result.status == HealthStatus.DEGRADED
        assert result.name == "cache"

    def test_create_persistence_health_check_healthy(self):
        """Test persistence health check when store is healthy."""
        persistence_store = Mock()
        persistence_store.list_projects = Mock(return_value=["project1"])

        check = create_persistence_health_check(persistence_store)
        result = check()

        assert result.status == HealthStatus.HEALTHY
        assert result.name == "persistence"

    def test_create_tool_registry_health_check_healthy(self):
        """Test tool registry health check when registry is healthy."""
        tool_registry = Mock()
        tool_registry.list_tools = Mock(return_value=[{"id": "tool1"}])

        check = create_tool_registry_health_check(tool_registry)
        result = check()

        assert result.status == HealthStatus.HEALTHY
        assert result.name == "tool_registry"

    def test_create_tool_registry_health_check_degraded_empty(self):
        """Test tool registry health check when no tools registered."""
        tool_registry = Mock()
        tool_registry.list_tools = Mock(return_value=[])

        check = create_tool_registry_health_check(tool_registry)
        result = check()

        assert result.status == HealthStatus.DEGRADED
        assert result.name == "tool_registry"

    def test_create_event_bus_health_check_healthy(self):
        """Test event bus health check when bus is healthy."""
        event_bus = Mock()
        event_bus.listener_count = Mock(return_value=3)

        check = create_event_bus_health_check(event_bus)
        result = check()

        assert result.status == HealthStatus.HEALTHY
        assert result.name == "event_bus"


class TestOrchestrationHealthRegistry:
    """Test OrchestrationHealthRegistry."""

    def test_register_llm(self):
        """Test registering LLM health check."""
        registry = OrchestrationHealthRegistry()
        llm_client = Mock()
        llm_client.model_id = "gpt-4"

        registry.register_llm(llm_client)

        assert "llm" in registry.list_components()

    def test_register_multiple_components(self):
        """Test registering multiple components."""
        registry = OrchestrationHealthRegistry()
        llm_client = Mock()
        llm_client.model_id = "gpt-4"
        memory_store = Mock()
        memory_store.get_scopes = Mock(return_value=[])
        cache_store = Mock()
        cache_store.stats = Mock(return_value={})

        registry.register_llm(llm_client)
        registry.register_memory(memory_store)
        registry.register_cache(cache_store)

        components = registry.list_components()
        assert "llm" in components
        assert "memory" in components
        assert "cache" in components

    @pytest.mark.asyncio
    async def test_check_all_healthy(self):
        """Test checking all components when healthy."""
        registry = OrchestrationHealthRegistry()
        llm_client = Mock()
        llm_client.model_id = "gpt-4"
        memory_store = Mock()
        memory_store.get_scopes = Mock(return_value=[])

        registry.register_llm(llm_client)
        registry.register_memory(memory_store)

        result = await registry.check_all()

        assert result.status == HealthStatus.HEALTHY
        assert "llm" in result.details
        assert "memory" in result.details

    @pytest.mark.asyncio
    async def test_check_all_unhealthy_critical(self):
        """Test checking all components with unhealthy critical component."""

        class BadLLM:
            pass

        registry = OrchestrationHealthRegistry()
        llm_client = BadLLM()

        registry.register_llm(llm_client, component_name="llm")

        result = await registry.check_all()

        assert result.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_check_all_degraded_non_critical(self):
        """Test checking all components with degraded non-critical component."""
        registry = OrchestrationHealthRegistry()
        cache_store = Mock()
        cache_store.stats = Mock(return_value={"errors": 5})

        registry.register_cache(cache_store)

        result = await registry.check_all()

        assert result.status == HealthStatus.DEGRADED

    def test_unregister_component(self):
        """Test unregistering a component."""
        registry = OrchestrationHealthRegistry()
        llm_client = Mock()
        llm_client.model_id = "gpt-4"

        registry.register_llm(llm_client)
        assert "llm" in registry.list_components()

        registry.unregister_component("llm")
        assert "llm" not in registry.list_components()

    def test_unregister_all(self):
        """Test unregistering all components."""
        registry = OrchestrationHealthRegistry()
        llm_client = Mock()
        llm_client.model_id = "gpt-4"
        memory_store = Mock()
        memory_store.get_scopes = Mock(return_value=[])

        registry.register_llm(llm_client)
        registry.register_memory(memory_store)

        registry.unregister_all()

        assert len(registry.list_components()) == 0


class TestDAGExecutorHealthChecks:
    """Test DAGExecutor health check integration."""

    @pytest.mark.asyncio
    async def test_execute_with_healthy_dependencies(self, simple_dag, mock_node_executor):
        """Test DAG execution with healthy dependencies."""
        registry = OrchestrationHealthRegistry()
        llm_client = Mock()
        llm_client.model_id = "gpt-4"
        memory_store = Mock()
        memory_store.get_scopes = Mock(return_value=[])

        registry.register_llm(llm_client)
        registry.register_memory(memory_store)

        executor = DAGExecutor(
            node_executor=mock_node_executor,
            health_registry=registry,
            require_healthy=True,
        )

        result = await executor.run(simple_dag)

        assert result.status == RunStatus.COMPLETED
        assert result.health_check_metadata
        assert result.health_check_metadata["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_execute_with_unhealthy_dependencies(self, simple_dag, mock_node_executor):
        """Test DAG execution blocked by unhealthy critical dependency."""

        class BadLLM:
            pass

        registry = OrchestrationHealthRegistry()
        llm_client = BadLLM()

        registry.register_llm(llm_client)

        executor = DAGExecutor(
            node_executor=mock_node_executor,
            health_registry=registry,
            require_healthy=True,
        )

        result = await executor.run(simple_dag)

        assert result.status == RunStatus.FAILED
        assert "health check failed" in result.error.lower()
        assert result.node_results == ()  # No nodes executed

    @pytest.mark.asyncio
    async def test_execute_with_health_check_disabled(self, simple_dag, mock_node_executor):
        """Test DAG execution with health checks disabled."""

        class BadLLM:
            pass

        registry = OrchestrationHealthRegistry()
        llm_client = BadLLM()

        registry.register_llm(llm_client)

        executor = DAGExecutor(
            node_executor=mock_node_executor,
            health_registry=registry,
            require_healthy=False,  # Disabled
        )

        result = await executor.run(simple_dag)

        # Should attempt execution despite unhealthy dependencies
        assert result.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_without_health_registry(self, simple_dag, mock_node_executor):
        """Test DAG execution without health registry."""
        executor = DAGExecutor(
            node_executor=mock_node_executor,
            health_registry=None,
        )

        result = await executor.run(simple_dag)

        assert result.status == RunStatus.COMPLETED
        assert result.health_check_metadata == {}

    @pytest.mark.asyncio
    async def test_health_metadata_in_result(self, simple_dag, mock_node_executor):
        """Test that health metadata is included in execution result."""
        registry = OrchestrationHealthRegistry()
        llm_client = Mock()
        llm_client.model_id = "gpt-4"
        cache_store = Mock()
        cache_store.stats = Mock(return_value={"errors": 2})

        registry.register_llm(llm_client)
        registry.register_cache(cache_store)

        executor = DAGExecutor(
            node_executor=mock_node_executor,
            health_registry=registry,
            require_healthy=True,
        )

        result = await executor.run(simple_dag)

        assert result.health_check_metadata
        assert "name" in result.health_check_metadata
        assert "status" in result.health_check_metadata
        assert "details" in result.health_check_metadata
        assert "llm" in result.health_check_metadata["details"]
        assert "cache" in result.health_check_metadata["details"]


class TestHealthCheckScenarios:
    """Test realistic health check scenarios."""

    def test_llm_service_timeout(self):
        """Test detecting LLM service timeout."""

        class BadLLM:
            pass

        llm_client = BadLLM()

        check = create_llm_health_check(llm_client)
        result = check()

        assert result.status == HealthStatus.UNHEALTHY

    def test_persistence_disk_full(self):
        """Test detecting persistence layer disk full."""
        persistence_store = Mock()
        persistence_store.list_projects = Mock(side_effect=OSError("No space left on device"))

        check = create_persistence_health_check(persistence_store)
        result = check()

        assert result.status == HealthStatus.UNHEALTHY

    def test_cache_partial_failure(self):
        """Test cache in partially degraded state."""
        cache_store = Mock()
        cache_store.stats = Mock(return_value={"total": 1000, "errors": 50})

        check = create_cache_health_check(cache_store)
        result = check()

        # Cache failures are non-critical
        assert result.status in (HealthStatus.DEGRADED, HealthStatus.UNHEALTHY)
