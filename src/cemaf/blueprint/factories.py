"""
Factory functions for blueprint components.

Provides convenient ways to create blueprint registries with sensible defaults
while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. The create_blueprint_registry_from_config()
    function includes a clear "EXTEND HERE" section where you can add
    your own registry implementations (database-backed, file-based, etc.).
"""

import os
from pathlib import Path

from cemaf.blueprint.library import BlueprintLibrary
from cemaf.blueprint.mock import MockBlueprintRegistry
from cemaf.blueprint.protocols import BlueprintRegistry, BlueprintSource
from cemaf.blueprint.sources import JSONFileBlueprintSource
from cemaf.config.protocols import Settings


def create_blueprint_registry(
    backend: str = "mock",
    strict_validation: bool = False,
) -> BlueprintRegistry:
    """
    Factory for BlueprintRegistry with sensible defaults.

    Args:
        backend: Registry backend (mock, file, database, etc.)
        strict_validation: Enable strict validation of blueprints

    Returns:
        Configured BlueprintRegistry instance

    Example:
        # Mock registry for testing
        registry = create_blueprint_registry()

        # With strict validation
        registry = create_blueprint_registry(strict_validation=True)
    """
    if backend == "mock":
        # MockBlueprintRegistry doesn't support strict_validation parameter
        # Parameter is documented but not implemented in the mock
        return MockBlueprintRegistry()  # type: ignore[return-value]
    else:
        raise ValueError(f"Unsupported blueprint registry backend: {backend}")


def create_blueprint_registry_from_config(settings: Settings | None = None) -> BlueprintRegistry:
    """
    Create BlueprintRegistry from environment configuration.

    Reads from environment variables:
    - CEMAF_BLUEPRINT_BACKEND: Registry backend (default: "mock")
    - CEMAF_BLUEPRINT_STRICT_VALIDATION: Enable strict validation (default: False)
    - CEMAF_BLUEPRINT_REQUIRE_ALL_FIELDS: Require all fields (default: False)

    Returns:
        Configured BlueprintRegistry instance

    Example:
        # From environment
        registry = create_blueprint_registry_from_config()
    """
    backend = os.getenv("CEMAF_BLUEPRINT_BACKEND", "mock")
    strict_validation = os.getenv("CEMAF_BLUEPRINT_STRICT_VALIDATION", "false").lower() == "true"

    # BUILT-IN IMPLEMENTATIONS
    if backend == "mock":
        return create_blueprint_registry(
            backend=backend,
            strict_validation=strict_validation,
        )

    # ============================================================================
    # EXTEND HERE: Bring Your Own Blueprint Registry
    # ============================================================================
    # This is the extension point for custom blueprint registry backends.
    #
    # To add your own implementation:
    # 1. Implement the BlueprintRegistry protocol (see cemaf.blueprint.protocols)
    # 2. Add your backend case below
    # 3. Read configuration from environment variables
    #
    # Example (File-based):
    #   elif backend == "file":
    #       from your_package import FileBlueprintRegistry
    #
    #       blueprints_dir = os.getenv("CEMAF_BLUEPRINT_DIR", "./blueprints")
    #       return FileBlueprintRegistry(
    #           directory=blueprints_dir,
    #           strict_validation=strict_validation,
    #       )
    #
    # Example (Database):
    #   elif backend == "database":
    #       from your_package import DatabaseBlueprintRegistry
    #
    #       db_url = os.getenv("DATABASE_URL")
    #       return DatabaseBlueprintRegistry(
    #           connection_string=db_url,
    #           table_name="blueprints",
    #       )
    # ============================================================================

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
    """Build a `BlueprintLibrary`, optionally pre-loaded from sources.

    This is the standard composition-root entry point for applications
    that want a blueprint library wired up without hand-assembling one.

    Example:
        >>> from cemaf.blueprint.factories import create_blueprint_library
        >>> from cemaf.blueprint.sources import JSONFileBlueprintSource
        >>> library = create_blueprint_library(
        ...     sources=(JSONFileBlueprintSource(path=Path("blueprints.json")),),
        ... )
    """
    library = BlueprintLibrary()
    if sources:
        library.register_from(sources=sources)
    return library


def create_blueprint_library_from_env() -> BlueprintLibrary:
    """Build a `BlueprintLibrary` from environment configuration.

    Reads:
        CEMAF_BLUEPRINT_CATALOG — path to a JSON catalog file
                                  (see `JSONFileBlueprintSource`).

    If the env var is unset or the file is missing, returns an empty
    library. Callers that need a catalog should fail loudly themselves;
    the factory treats absence as "no curated catalog yet."
    """
    catalog_env = os.getenv("CEMAF_BLUEPRINT_CATALOG")
    sources: tuple[BlueprintSource, ...] = ()
    if catalog_env:
        sources = (JSONFileBlueprintSource(path=Path(catalog_env)),)
    return create_blueprint_library(sources=sources)
