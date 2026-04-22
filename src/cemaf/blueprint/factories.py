"""Factory functions for blueprint components — composition-root helpers."""

import os
from pathlib import Path

from cemaf.blueprint.library import BlueprintLibrary, BlueprintSource
from cemaf.blueprint.mock import MockBlueprintRegistry
from cemaf.blueprint.protocols import BlueprintRegistry
from cemaf.blueprint.sources import JSONFileBlueprintSource
from cemaf.config.protocols import Settings


def create_blueprint_registry(
    backend: str = "mock",
    strict_validation: bool = False,
) -> BlueprintRegistry:
    """Build a legacy `BlueprintRegistry` (async kv backend); prefer `create_blueprint_library`."""
    if backend == "mock":
        return MockBlueprintRegistry()  # type: ignore[return-value]
    raise ValueError(f"Unsupported blueprint registry backend: {backend}")


def create_blueprint_registry_from_config(settings: Settings | None = None) -> BlueprintRegistry:
    """Build a legacy `BlueprintRegistry` from `CEMAF_BLUEPRINT_BACKEND` env."""
    backend = os.getenv("CEMAF_BLUEPRINT_BACKEND", "mock")
    strict_validation = os.getenv("CEMAF_BLUEPRINT_STRICT_VALIDATION", "false").lower() == "true"

    if backend == "mock":
        return create_blueprint_registry(
            backend=backend,
            strict_validation=strict_validation,
        )

    raise ValueError(
        f"Unsupported blueprint registry backend: {backend}. "
        f"Supported: mock. "
        f"To add your own, extend create_blueprint_registry_from_config() "
        f"in cemaf/blueprint/factories.py"
    )


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
    """Build a `BlueprintLibrary` from `CEMAF_BLUEPRINT_CATALOG` (JSON file path); empty if unset."""
    catalog_env = os.getenv("CEMAF_BLUEPRINT_CATALOG")
    sources: tuple[BlueprintSource, ...] = ()
    if catalog_env:
        sources = (JSONFileBlueprintSource(path=Path(catalog_env)),)
    return create_blueprint_library(sources=sources)
