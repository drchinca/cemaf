"""Registry-backed factories for persistence backends."""

import os
from typing import Any

from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.persistence.protocols import (
    ArtifactStore,
    ContentStore,
    ProjectStore,
    RunStore,
)

project_store_registry: ProviderRegistry[ProjectStore] = ProviderRegistry(name="project_store")
artifact_store_registry: ProviderRegistry[ArtifactStore] = ProviderRegistry(name="artifact_store")
content_store_registry: ProviderRegistry[ContentStore] = ProviderRegistry(name="content_store")
run_store_registry: ProviderRegistry[RunStore] = ProviderRegistry(name="run_store")


def _persistence_options() -> dict[str, str | None]:
    """Collect common persistence environment values for custom factories."""
    return {
        "database_url": os.getenv("DATABASE_URL"),
        "mongodb_uri": os.getenv("MONGODB_URI"),
        "mongodb_database": os.getenv("MONGODB_DATABASE", "cemaf"),
        "aws_region": os.getenv("AWS_REGION", "us-east-1"),
        "s3_artifacts_bucket": os.getenv("S3_ARTIFACTS_BUCKET"),
        "dynamodb_projects_table": os.getenv("DYNAMODB_PROJECTS_TABLE", "cemaf_projects"),
        "timescale_url": os.getenv("TIMESCALE_URL"),
    }


def create_project_store(backend: str = "mock", **backend_options: Any) -> ProjectStore:
    """Create a registered ProjectStore backend."""
    return project_store_registry.create(backend=backend, **backend_options)


def create_project_store_from_config(settings: Settings | None = None) -> ProjectStore:
    """
    Create ProjectStore from environment configuration.

    Reads from environment variables:
    - CEMAF_PERSISTENCE_PROJECT_STORE_BACKEND: Backend type (default: "mock")
    - DATABASE_URL: Database connection string (for database backends)

    Returns:
        Configured ProjectStore instance

    Example:
        # From environment
        store = create_project_store_from_config()
    """
    _ = settings
    backend = os.getenv("CEMAF_PERSISTENCE_PROJECT_STORE_BACKEND", "mock")
    return create_project_store(backend=backend, **_persistence_options())


def create_artifact_store(backend: str = "mock", **backend_options: Any) -> ArtifactStore:
    """Create a registered ArtifactStore backend."""
    return artifact_store_registry.create(backend=backend, **backend_options)


def create_artifact_store_from_config(settings: Settings | None = None) -> ArtifactStore:
    """
    Create ArtifactStore from environment configuration.

    Reads from environment variables:
    - CEMAF_PERSISTENCE_ARTIFACT_STORE_BACKEND: Backend type (default: "mock")
    - DATABASE_URL: Database connection string

    Returns:
        Configured ArtifactStore instance
    """
    _ = settings
    backend = os.getenv("CEMAF_PERSISTENCE_ARTIFACT_STORE_BACKEND", "mock")
    return create_artifact_store(backend=backend, **_persistence_options())


def create_content_store(backend: str = "mock", **backend_options: Any) -> ContentStore:
    """Create a registered ContentStore backend."""
    return content_store_registry.create(backend=backend, **backend_options)


def create_content_store_from_config(settings: Settings | None = None) -> ContentStore:
    """
    Create ContentStore from environment configuration.

    Reads from environment variables:
    - CEMAF_PERSISTENCE_CONTENT_STORE_BACKEND: Backend type (default: "mock")
    - DATABASE_URL: Database connection string

    Returns:
        Configured ContentStore instance
    """
    _ = settings
    backend = os.getenv("CEMAF_PERSISTENCE_CONTENT_STORE_BACKEND", "mock")
    return create_content_store(backend=backend, **_persistence_options())


def create_run_store(backend: str = "mock", **backend_options: Any) -> RunStore:
    """Create a registered RunStore backend."""
    return run_store_registry.create(backend=backend, **backend_options)


def create_run_store_from_config(settings: Settings | None = None) -> RunStore:
    """
    Create RunStore from environment configuration.

    Reads from environment variables:
    - CEMAF_PERSISTENCE_RUN_STORE_BACKEND: Backend type (default: "mock")
    - DATABASE_URL: Database connection string

    Returns:
        Configured RunStore instance
    """
    _ = settings
    backend = os.getenv("CEMAF_PERSISTENCE_RUN_STORE_BACKEND", "mock")
    return create_run_store(backend=backend, **_persistence_options())
