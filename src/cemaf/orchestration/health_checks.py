"""
Health checks for DAG orchestration dependencies.

Provides health check functions for all critical dependencies:
- LLM services
- Memory stores
- Cache services
- Persistence layers
- Tool/Skill registries
- Event bus
"""

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from cemaf.observability.health import (
    HealthCheckResult,
    HealthStatus,
    get_health_monitor,
)


@runtime_checkable
class HealthCheckable(Protocol):
    """Protocol for services that can report their health."""

    async def health_check(self) -> HealthCheckResult:
        """
        Check health of the service.

        Returns:
            HealthCheckResult with status and details
        """
        ...


def create_llm_health_check(llm_client: Any) -> Callable[[], HealthCheckResult]:
    """
    Create health check for LLM service.

    Args:
        llm_client: LLM client instance

    Returns:
        Health check function
    """

    def check() -> HealthCheckResult:
        try:
            # Try to access a basic property or method that validates connection
            if hasattr(llm_client, "health_check"):
                # If client has explicit health check, use it
                result = llm_client.health_check()
                if isinstance(result, HealthCheckResult):
                    return result
            elif hasattr(llm_client, "model_id"):
                # OpenAI/Anthropic clients have model_id
                _ = llm_client.model_id
            else:
                # Generic check: verify object exists and is callable
                if not callable(llm_client):
                    return HealthCheckResult(
                        "llm",
                        HealthStatus.UNHEALTHY,
                        message="LLM client not callable",
                    )

            return HealthCheckResult(
                "llm",
                HealthStatus.HEALTHY,
                message="LLM service available",
            )
        except Exception as e:
            return HealthCheckResult(
                "llm",
                HealthStatus.UNHEALTHY,
                message=f"LLM service unavailable: {str(e)}",
                details={"error_type": type(e).__name__},
            )

    return check


def create_memory_health_check(memory_store: Any) -> Callable[[], HealthCheckResult]:
    """
    Create health check for memory store.

    Args:
        memory_store: Memory store instance

    Returns:
        Health check function
    """

    def check() -> HealthCheckResult:
        try:
            if hasattr(memory_store, "health_check"):
                result = memory_store.health_check()
                if isinstance(result, HealthCheckResult):
                    return result

            # Test basic operations
            if hasattr(memory_store, "get_scopes"):
                _ = memory_store.get_scopes()

            return HealthCheckResult(
                "memory",
                HealthStatus.HEALTHY,
                message="Memory store available",
            )
        except Exception as e:
            return HealthCheckResult(
                "memory",
                HealthStatus.UNHEALTHY,
                message=f"Memory store unavailable: {str(e)}",
                details={"error_type": type(e).__name__},
            )

    return check


def create_cache_health_check(cache_store: Any) -> Callable[[], HealthCheckResult]:
    """
    Create health check for cache store.

    Args:
        cache_store: Cache store instance

    Returns:
        Health check function
    """

    def check() -> HealthCheckResult:
        try:
            if hasattr(cache_store, "health_check"):
                result = cache_store.health_check()
                if isinstance(result, HealthCheckResult):
                    return result

            # Cache is optional, so degraded is better than unhealthy
            if hasattr(cache_store, "stats"):
                stats = cache_store.stats()
                if stats.get("errors", 0) > 0:
                    return HealthCheckResult(
                        "cache",
                        HealthStatus.DEGRADED,
                        message=f"Cache has {stats['errors']} errors",
                        details=stats,
                    )

            return HealthCheckResult(
                "cache",
                HealthStatus.HEALTHY,
                message="Cache available",
            )
        except Exception as e:
            # Cache failures are non-critical
            return HealthCheckResult(
                "cache",
                HealthStatus.DEGRADED,
                message=f"Cache check failed: {str(e)}",
                details={"error_type": type(e).__name__},
            )

    return check


def create_persistence_health_check(
    persistence_store: Any,
) -> Callable[[], HealthCheckResult]:
    """
    Create health check for persistence store.

    Args:
        persistence_store: Persistence store instance

    Returns:
        Health check function
    """

    def check() -> HealthCheckResult:
        try:
            if hasattr(persistence_store, "health_check"):
                result = persistence_store.health_check()
                if isinstance(result, HealthCheckResult):
                    return result

            # Test basic operations
            if hasattr(persistence_store, "list_projects"):
                _ = persistence_store.list_projects()

            return HealthCheckResult(
                "persistence",
                HealthStatus.HEALTHY,
                message="Persistence store available",
            )
        except Exception as e:
            return HealthCheckResult(
                "persistence",
                HealthStatus.UNHEALTHY,
                message=f"Persistence store unavailable: {str(e)}",
                details={"error_type": type(e).__name__},
            )

    return check


def create_tool_registry_health_check(tool_registry: Any) -> Callable[[], HealthCheckResult]:
    """
    Create health check for tool registry.

    Args:
        tool_registry: Tool registry instance

    Returns:
        Health check function
    """

    def check() -> HealthCheckResult:
        try:
            if hasattr(tool_registry, "health_check"):
                result = tool_registry.health_check()
                if isinstance(result, HealthCheckResult):
                    return result

            # Test basic operations
            if hasattr(tool_registry, "list_tools"):
                tools = tool_registry.list_tools()
                if not tools:
                    return HealthCheckResult(
                        "tool_registry",
                        HealthStatus.DEGRADED,
                        message="No tools registered",
                    )

            return HealthCheckResult(
                "tool_registry",
                HealthStatus.HEALTHY,
                message="Tool registry available",
            )
        except Exception as e:
            return HealthCheckResult(
                "tool_registry",
                HealthStatus.UNHEALTHY,
                message=f"Tool registry unavailable: {str(e)}",
                details={"error_type": type(e).__name__},
            )

    return check


def create_event_bus_health_check(event_bus: Any) -> Callable[[], HealthCheckResult]:
    """
    Create health check for event bus.

    Args:
        event_bus: Event bus instance

    Returns:
        Health check function
    """

    def check() -> HealthCheckResult:
        try:
            if hasattr(event_bus, "health_check"):
                result = event_bus.health_check()
                if isinstance(result, HealthCheckResult):
                    return result

            # Event bus is optional, so degraded on failure
            if hasattr(event_bus, "listener_count"):
                count = event_bus.listener_count()
                return HealthCheckResult(
                    "event_bus",
                    HealthStatus.HEALTHY,
                    message=f"Event bus available ({count} listeners)",
                    details={"listener_count": count},
                )

            return HealthCheckResult(
                "event_bus",
                HealthStatus.HEALTHY,
                message="Event bus available",
            )
        except Exception as e:
            # Event bus failures are non-critical
            return HealthCheckResult(
                "event_bus",
                HealthStatus.DEGRADED,
                message=f"Event bus check failed: {str(e)}",
                details={"error_type": type(e).__name__},
            )

    return check


class OrchestrationHealthRegistry:
    """
    Registry for orchestration health checks.

    Manages health checks for all DAG execution dependencies.
    """

    def __init__(self) -> None:
        """Initialize registry."""
        self._monitor = get_health_monitor()
        self._registered_components: set[str] = set()

    def register_llm(self, llm_client: Any, component_name: str = "llm") -> None:
        """
        Register LLM service for health checks.

        Args:
            llm_client: LLM client instance
            component_name: Name for health check
        """
        if component_name not in self._registered_components:
            check_fn = create_llm_health_check(llm_client)
            self._monitor.register_check(component_name, check_fn, critical=True)
            self._registered_components.add(component_name)

    def register_memory(self, memory_store: Any, component_name: str = "memory") -> None:
        """
        Register memory store for health checks.

        Args:
            memory_store: Memory store instance
            component_name: Name for health check
        """
        if component_name not in self._registered_components:
            check_fn = create_memory_health_check(memory_store)
            self._monitor.register_check(component_name, check_fn, critical=True)
            self._registered_components.add(component_name)

    def register_cache(self, cache_store: Any, component_name: str = "cache") -> None:
        """
        Register cache store for health checks.

        Args:
            cache_store: Cache store instance
            component_name: Name for health check
        """
        if component_name not in self._registered_components:
            check_fn = create_cache_health_check(cache_store)
            self._monitor.register_check(component_name, check_fn, critical=False)
            self._registered_components.add(component_name)

    def register_persistence(
        self,
        persistence_store: Any,
        component_name: str = "persistence",
    ) -> None:
        """
        Register persistence store for health checks.

        Args:
            persistence_store: Persistence store instance
            component_name: Name for health check
        """
        if component_name not in self._registered_components:
            check_fn = create_persistence_health_check(persistence_store)
            self._monitor.register_check(component_name, check_fn, critical=True)
            self._registered_components.add(component_name)

    def register_tool_registry(
        self,
        tool_registry: Any,
        component_name: str = "tool_registry",
    ) -> None:
        """
        Register tool registry for health checks.

        Args:
            tool_registry: Tool registry instance
            component_name: Name for health check
        """
        if component_name not in self._registered_components:
            check_fn = create_tool_registry_health_check(tool_registry)
            self._monitor.register_check(component_name, check_fn, critical=False)
            self._registered_components.add(component_name)

    def register_event_bus(
        self,
        event_bus: Any,
        component_name: str = "event_bus",
    ) -> None:
        """
        Register event bus for health checks.

        Args:
            event_bus: Event bus instance
            component_name: Name for health check
        """
        if component_name not in self._registered_components:
            check_fn = create_event_bus_health_check(event_bus)
            self._monitor.register_check(component_name, check_fn, critical=False)
            self._registered_components.add(component_name)

    def unregister_component(self, component_name: str) -> None:
        """
        Unregister a component's health checks.

        Args:
            component_name: Name of component to unregister
        """
        self._monitor.unregister_check(component_name)
        self._registered_components.discard(component_name)

    def unregister_all(self) -> None:
        """Unregister all components."""
        for component_name in list(self._registered_components):
            self._monitor.unregister_check(component_name)
        self._registered_components.clear()

    async def check_all(self) -> HealthCheckResult:
        """
        Check health of all registered components.

        Returns:
            Aggregated health check result
        """
        return await self._monitor.check_all()

    async def check_one(self, component_name: str) -> HealthCheckResult:
        """
        Check health of a single component.

        Args:
            component_name: Name of component to check

        Returns:
            Health check result
        """
        return await self._monitor.check_one(component_name)

    def list_components(self) -> list[str]:
        """List all registered components."""
        return list(self._registered_components)
