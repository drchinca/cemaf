"""Blueprint composition-root factories."""

import os
from pathlib import Path
from typing import Any

from cemaf.blueprint.harvest import (
    BlueprintDistiller,
    BlueprintHarvesterEngine,
    HarvestPolicy,
    RunCorrelator,
)
from cemaf.blueprint.harvest_defaults import (
    InMemoryRunCorrelator,
    RecipeBlueprintDistiller,
    ScoreThresholdHarvestPolicy,
)
from cemaf.blueprint.library import BlueprintLibrary, BlueprintSource, WritableBlueprintSource
from cemaf.blueprint.sources import InMemoryBlueprintSource, JSONFileBlueprintSource
from cemaf.blueprint.sqlite_source import SqliteBlueprintSource
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.events.protocols import EventBus

blueprint_source_registry: ProviderRegistry[BlueprintSource] = ProviderRegistry(name="blueprint_source")


def _create_in_memory_blueprint_source(**kwargs: Any) -> BlueprintSource:
    return InMemoryBlueprintSource(
        entries=kwargs.get("entries", ()),
        name=str(kwargs.get("name") or "in-memory"),
    )


def _create_json_file_blueprint_source(**kwargs: Any) -> BlueprintSource:
    path = (
        kwargs.get("path")
        or kwargs.get("file_path")
        or kwargs.get("catalog_path")
        or os.getenv("CEMAF_BLUEPRINT_CATALOG")
    )
    if not path:
        raise ValueError("json_file blueprint source requires path (or CEMAF_BLUEPRINT_CATALOG env).")
    return JSONFileBlueprintSource(
        path=Path(str(path)),
        name=str(kwargs["name"]) if kwargs.get("name") else None,
    )


def _create_sqlite_blueprint_source(**kwargs: Any) -> BlueprintSource:
    db_path = (
        kwargs.get("db_path")
        or kwargs.get("path")
        or os.getenv("CEMAF_BLUEPRINT_SQLITE_PATH")
        or os.getenv("CEMAF_BLUEPRINT_SOURCE_PATH")
        or "cemaf_blueprints.db"
    )
    return SqliteBlueprintSource(
        db_path=str(db_path),
        name=str(kwargs["name"]) if kwargs.get("name") else None,
        busy_timeout_ms=int(kwargs.get("busy_timeout_ms", 5000)),
        journal_mode=str(kwargs.get("journal_mode", "WAL")),
    )


blueprint_source_registry.register(backend="memory", factory=_create_in_memory_blueprint_source)
blueprint_source_registry.register(backend="json", factory=_create_json_file_blueprint_source)
blueprint_source_registry.register(backend="json_file", factory=_create_json_file_blueprint_source)
blueprint_source_registry.register(backend="sqlite", factory=_create_sqlite_blueprint_source)


def create_blueprint_source(
    source_type: str,
    **source_options: Any,
) -> BlueprintSource:
    """Build a `BlueprintSource` from the registry."""
    return blueprint_source_registry.create(backend=source_type, **source_options)


def create_blueprint_library(
    *,
    sources: tuple[BlueprintSource, ...] = (),
) -> BlueprintLibrary:
    """Build a `BlueprintLibrary`, optionally pre-loaded from `sources`."""
    library = BlueprintLibrary()
    if sources:
        library.register_from(sources=sources)
    return library


def create_blueprint_library_from_env() -> BlueprintLibrary:
    """Build a `BlueprintLibrary` from blueprint source environment config.

    `CEMAF_BLUEPRINT_SOURCE_BACKEND` selects a registered source backend. The
    legacy `CEMAF_BLUEPRINT_CATALOG` JSON path still works as a shortcut.
    """
    source_backend = os.getenv("CEMAF_BLUEPRINT_SOURCE_BACKEND")
    catalog_env = os.getenv("CEMAF_BLUEPRINT_CATALOG")
    sources: tuple[BlueprintSource, ...] = ()
    if source_backend:
        source = create_blueprint_source(
            source_backend,
            path=os.getenv("CEMAF_BLUEPRINT_SOURCE_PATH") or catalog_env,
            db_path=os.getenv("CEMAF_BLUEPRINT_SQLITE_PATH"),
            name=os.getenv("CEMAF_BLUEPRINT_SOURCE_NAME"),
            busy_timeout_ms=os.getenv("CEMAF_BLUEPRINT_SQLITE_BUSY_TIMEOUT_MS", "5000"),
            journal_mode=os.getenv("CEMAF_BLUEPRINT_SQLITE_JOURNAL_MODE", "WAL"),
        )
        sources = (source,)
    elif catalog_env:
        sources = (create_blueprint_source("json_file", path=catalog_env),)
    return create_blueprint_library(sources=sources)


def create_blueprint_harvester(
    *,
    writable_source: WritableBlueprintSource,
    event_bus: EventBus,
    library: BlueprintLibrary | None = None,
    threshold: float = 0.8,
    policy: HarvestPolicy | None = None,
    correlator: RunCorrelator | None = None,
    distiller: BlueprintDistiller | None = None,
    subscribe: bool = True,
) -> BlueprintHarvesterEngine:
    """Wire the blueprint-harvest flywheel with bundled defaults — the learn-from-runs loop.

    The harvester watches execution events and distills high-scoring runs into
    reusable blueprints, closing the loop from "run" back to "reusable recipe".
    This is the base-layer entry point so a harvest loop can be enabled without
    the self-hosting (`meta`) layer. Every decision is pluggable; omitted ones
    use the bundled defaults (`ScoreThresholdHarvestPolicy` at `threshold`,
    `InMemoryRunCorrelator`, `RecipeBlueprintDistiller`).

    When `subscribe=True` (default) the engine is wired onto `event_bus` immediately;
    pass `False` to subscribe later and own the lifecycle yourself.
    """
    engine = BlueprintHarvesterEngine(
        writable_source=writable_source,
        policy=policy or ScoreThresholdHarvestPolicy(threshold=threshold),
        correlator=correlator or InMemoryRunCorrelator(),
        distiller=distiller or RecipeBlueprintDistiller(),
        library=library,
    )
    if subscribe:
        engine.subscribe(event_bus=event_bus)
    return engine
