"""
Blueprint protocols - Abstract interfaces for blueprint management.

Supports:
- Blueprint schema definitions
- Blueprint validation rules
- Blueprint registry for storage/retrieval (async key-value backend)
- Blueprint sources for library ingestion (sync generators)
- Scene goal and participant management

## Protocol-First Design

This module provides structural typing via @runtime_checkable protocols.
Any class that implements the required methods is automatically compatible.

Extension Point:
    Implement these protocols for custom blueprint storage and management.
    No registration needed - structural typing ensures compatibility.
"""

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

# Re-export data classes
from cemaf.blueprint.core import Blueprint, SceneGoal, StyleGuide
from cemaf.blueprint.library import BlueprintEntry

__all__ = [
    "BlueprintRegistry",
    "BlueprintSource",
    # Data classes
    "Blueprint",
    "BlueprintEntry",
    "SceneGoal",
    "StyleGuide",
]


@runtime_checkable
class BlueprintRegistry(Protocol):
    """
    Protocol for blueprint registry implementations.

    A BlueprintRegistry stores and retrieves blueprints:
    - Store blueprints by ID
    - Retrieve blueprints by ID
    - List all blueprints
    - Search blueprints by criteria

    Extension Point:
        - In-memory registry (testing)
        - Database registry (PostgreSQL, MongoDB)
        - File-based registry (JSON, YAML)
        - Distributed registry (Redis, DynamoDB)
        - Versioned registry (Git-based)

    Example:
        >>> class InMemoryBlueprintRegistry:
        ...     def __init__(self):
        ...         self._blueprints = {}
        ...
        ...     async def store(self, blueprint_id: str, blueprint: Blueprint) -> None:
        ...         self._blueprints[blueprint_id] = blueprint
        ...
        ...     async def retrieve(self, blueprint_id: str) -> Blueprint | None:
        ...         return self._blueprints.get(blueprint_id)
        ...
        ...     async def list_all(self) -> list[Blueprint]:
        ...         return list(self._blueprints.values())
        >>>
        >>> registry = InMemoryBlueprintRegistry()
        >>> assert isinstance(registry, BlueprintRegistry)
    """

    async def store(self, blueprint_id: str, blueprint: Blueprint) -> None:
        """
        Store a blueprint in the registry.

        Args:
            blueprint_id: Unique identifier for the blueprint
            blueprint: Blueprint instance to store

        Example:
            >>> blueprint = Blueprint(...)
            >>> await registry.store("scene-001", blueprint)
        """
        ...

    async def retrieve(self, blueprint_id: str) -> Blueprint | None:
        """
        Retrieve a blueprint by ID.

        Args:
            blueprint_id: Blueprint identifier

        Returns:
            Blueprint if found, None otherwise

        Example:
            >>> blueprint = await registry.retrieve("scene-001")
            >>> if blueprint:
            ...     print(f"Scene: {blueprint.scene_goal}")
        """
        ...

    async def list_all(self) -> list[Blueprint]:
        """
        List all blueprints in the registry.

        Returns:
            List of all stored blueprints

        Example:
            >>> blueprints = await registry.list_all()
            >>> print(f"Total blueprints: {len(blueprints)}")
        """
        ...


@runtime_checkable
class BlueprintSource(Protocol):
    """A source of `BlueprintEntry` records for a `BlueprintLibrary`.

    Implementations enumerate entries from a specific substrate — a JSON
    file on disk, a directory of YAML blueprints, a database query, a
    git-tracked registry, an HTTP API. The `BlueprintLibrary` composes
    any number of sources at construction time and treats them uniformly.

    Keep sources lazy-loading where possible: `load()` is synchronous
    (libraries are usually built at import time) but should not hold open
    file handles or network connections beyond the generator's lifetime.
    """

    @property
    def name(self) -> str:
        """Short identifier for this source (written to BlueprintEntry.source)."""
        ...

    def load(self) -> Iterable[BlueprintEntry]:
        """Yield every entry this source produces."""
        ...
