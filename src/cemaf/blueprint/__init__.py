"""
Blueprint module — semantic prompt engineering + a reusable blueprint library.

`Blueprint` (see `cemaf.blueprint.core`) is CEMAF's unit of structured
prompt engineering: scene goal + style + entities + policies, rendered
to a prompt via `to_prompt()`.

`BlueprintLibrary` (see `cemaf.blueprint.library`) is the curated,
searchable index over reusable `Blueprint`s. Entries come in three
representational kinds — SNAPSHOT (serialized inline), FACTORY (Python
import path), RECIPE (declarative dict) — and all resolve to the same
`Blueprint` type so consumers don't care how the entry was stored.

Pluggable ingestion via the `BlueprintSource` protocol
(`cemaf.blueprint.protocols`); concrete implementations for in-memory
and JSON-file sources live in `cemaf.blueprint.sources`.
"""

from cemaf.blueprint.builder import BlueprintBuilder
from cemaf.blueprint.core import Blueprint, SceneGoal, StyleGuide
from cemaf.blueprint.entities import ContextEntity, EntityType
from cemaf.blueprint.harvest import (
    BlueprintDistiller,
    BlueprintHarvesterEngine,
    HarvestContext,
    HarvestOutcome,
    HarvestPolicy,
    RunCorrelator,
)
from cemaf.blueprint.library import (
    BlueprintEntry,
    BlueprintEntryKind,
    BlueprintIdCollision,
    BlueprintLibrary,
    BlueprintLibraryError,
    BlueprintNotFound,
    BlueprintResolutionError,
    WritableBlueprintSource,
)
from cemaf.blueprint.mock import MockBlueprintRegistry, create_mock_blueprint
from cemaf.blueprint.protocols import BlueprintSource  # noqa: F401 re-export
from cemaf.blueprint.recipe import RecipeValidationError, parse_recipe
from cemaf.blueprint.rules import BlueprintContentRule, BlueprintSchemaRule
from cemaf.blueprint.sources import (
    InMemoryBlueprintSource,
    InMemoryWritableBlueprintSource,
    JSONFileBlueprintSource,
)
from cemaf.blueprint.sqlite_source import SqliteBlueprintSource

__all__ = [
    # Schema models
    "Blueprint",
    "ContextEntity",
    "EntityType",
    "SceneGoal",
    "StyleGuide",
    # Builder
    "BlueprintBuilder",
    # Library
    "BlueprintEntry",
    "BlueprintEntryKind",
    "BlueprintLibrary",
    "BlueprintSource",
    "WritableBlueprintSource",
    "InMemoryBlueprintSource",
    "InMemoryWritableBlueprintSource",
    "JSONFileBlueprintSource",
    "SqliteBlueprintSource",
    # Harvest engine
    "BlueprintHarvesterEngine",
    "BlueprintDistiller",
    "HarvestContext",
    "HarvestOutcome",
    "HarvestPolicy",
    "RunCorrelator",
    # Library errors
    "BlueprintIdCollision",
    "BlueprintLibraryError",
    "BlueprintNotFound",
    "BlueprintResolutionError",
    # Recipe parser
    "RecipeValidationError",
    "parse_recipe",
    # Validation rules
    "BlueprintContentRule",
    "BlueprintSchemaRule",
    # Mocks for testing
    "MockBlueprintRegistry",
    "create_mock_blueprint",
]
