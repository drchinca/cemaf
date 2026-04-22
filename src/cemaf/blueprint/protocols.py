"""Blueprint protocols — public interface surface for the blueprint module."""

from typing import Protocol, runtime_checkable

from cemaf.blueprint.core import Blueprint, SceneGoal, StyleGuide
from cemaf.blueprint.library import BlueprintEntry, BlueprintSource

__all__ = [
    "Blueprint",
    "BlueprintEntry",
    "BlueprintRegistry",
    "BlueprintSource",
    "SceneGoal",
    "StyleGuide",
]


@runtime_checkable
class BlueprintRegistry(Protocol):
    """Async key-value backend for individual `Blueprint` objects (legacy — prefer `BlueprintLibrary`)."""

    async def store(self, blueprint_id: str, blueprint: Blueprint) -> None:
        """Persist `blueprint` under `blueprint_id`."""
        ...

    async def retrieve(self, blueprint_id: str) -> Blueprint | None:
        """Fetch the blueprint with `blueprint_id`, or None if missing."""
        ...

    async def list_all(self) -> list[Blueprint]:
        """Return every stored blueprint."""
        ...
