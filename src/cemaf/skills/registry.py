"""
Skill Registry - Auto-discovery and dependency injection for skills.

Provides centralized management of skills with features:
- Auto-discovery from packages
- Dependency injection into skill constructors (tools + other dependencies)
- Namespace support to prevent ID collisions

Usage:
    # Basic registration
    registry = SkillRegistry()
    registry.register(MySkill)  # Auto-instantiate
    registry.register_instance(my_skill)  # Pre-constructed

    # With dependency injection (tools + other deps)
    registry = SkillRegistry(dependencies={
        "http_tool": http_tool,
        "llm_client": client
    })
    registry.register(SkillRequiringDeps)  # Auto-injects

    # Auto-discovery from package
    registry = SkillRegistry.auto_discover(
        "myapp.skills",
        dependencies={"tool": tool, "client": client}
    )

    # Namespace support (prevent ID collisions)
    registry = SkillRegistry(namespace="analytics")
    registry.register(DataSkill)  # Stored as "analytics.data"

    # Retrieve and execute
    skill = registry.get("my_skill")
    result = await skill.execute(input=data, context=ctx)
"""

import inspect
from typing import Any

from cemaf.core.registry import BaseRegistry, RegistryError
from cemaf.skills.protocols import Skill

__all__ = ["SkillRegistry", "RegistryError"]


class SkillRegistry(BaseRegistry[Skill]):
    """
    Registry for skill management with auto-discovery and dependency injection.

    Inherits all common registry functionality from BaseRegistry. Skills can
    have dependencies on tools and other objects that are injected automatically.

    Example:
        >>> registry = SkillRegistry(dependencies={
        ...     "http_tool": http_tool,
        ...     "client": llm_client
        ... })
        >>> registry.register(DataFetchSkill)  # Auto-injects dependencies
        >>> skill = registry.get("data_fetch")
        >>> result = await skill.execute(input=request, context=ctx)
    """

    def __init__(
        self,
        *,
        dependencies: dict[str, Any] | None = None,
        namespace: str = "",
    ) -> None:
        """
        Initialize skill registry.

        Args:
            dependencies: Dependencies to inject into skill constructors.
                         Keys are parameter names, values are injected.
                         Can include tools, clients, or other dependencies.
            namespace: Optional namespace prefix for skill IDs (e.g., "analytics.data")
        """
        super().__init__(
            item_type_name="Skill",
            id_attribute="id",
            dependencies=dependencies,
            namespace=namespace,
        )

    def list_skills(self) -> list[Skill]:
        """
        List all registered skills.

        Returns:
            List of all skill instances
        """
        return self.list_items()

    def _implements_protocol(self, obj: Any) -> bool:
        """
        Check if object implements Skill protocol.

        Args:
            obj: Object to check (class or instance)

        Returns:
            True if object implements Skill protocol
        """
        # For classes, check if they would implement the protocol when instantiated
        if inspect.isclass(obj):
            # Check for required attributes
            has_id = hasattr(obj, "id")
            has_description = hasattr(obj, "description")
            has_tools = hasattr(obj, "tools")
            has_execute = hasattr(obj, "execute")
            return has_id and has_description and has_tools and has_execute

        # For instances, use isinstance check
        return isinstance(obj, Skill)
