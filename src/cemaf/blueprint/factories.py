"""Blueprint composition-root factories."""

import os
from pathlib import Path

from cemaf.blueprint.library import BlueprintLibrary, BlueprintSource
from cemaf.blueprint.sources import JSONFileBlueprintSource


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
