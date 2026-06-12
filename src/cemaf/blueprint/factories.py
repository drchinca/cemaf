"""Blueprint composition-root factories."""

import os
from pathlib import Path

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
from cemaf.blueprint.sources import JSONFileBlueprintSource
from cemaf.events.protocols import EventBus


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
    """Build a `BlueprintLibrary` from `CEMAF_BLUEPRINT_CATALOG` (JSON path); empty if unset."""
    catalog_env = os.getenv("CEMAF_BLUEPRINT_CATALOG")
    sources: tuple[BlueprintSource, ...] = ()
    if catalog_env:
        sources = (JSONFileBlueprintSource(path=Path(catalog_env)),)
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
