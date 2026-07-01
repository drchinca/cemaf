"""
Persistence module - Core entities and storage protocols.

**Extension Point** — This module defines protocols and entities for project persistence.
No concrete storage backends are included. Implement the protocols (ProjectStore, ArtifactStore,
ContentStore, RunStore) and register factories to connect to your storage layer
(PostgreSQL, MongoDB, etc.).

Core entities:
- Project: Multi-tenant project container
- ContextArtifact: Versioned context documents
- ContentItem: Generated content
- Run: Pipeline execution record
"""

from cemaf.persistence.entities import (
    ContentItem,
    ContextArtifact,
    Project,
    Run,
)
from cemaf.persistence.factories import (
    artifact_store_registry,
    content_store_registry,
    create_artifact_store,
    create_artifact_store_from_config,
    create_content_store,
    create_content_store_from_config,
    create_project_store,
    create_project_store_from_config,
    create_run_store,
    create_run_store_from_config,
    project_store_registry,
    run_store_registry,
)
from cemaf.persistence.protocols import (
    ArtifactStore,
    ContentStore,
    ProjectStore,
    RunStore,
)

__all__ = [
    # Entities
    "Project",
    "ContextArtifact",
    "ContentItem",
    "Run",
    # Protocols
    "ProjectStore",
    "ArtifactStore",
    "ContentStore",
    "RunStore",
    # Factories
    "create_project_store",
    "create_project_store_from_config",
    "create_artifact_store",
    "create_artifact_store_from_config",
    "create_content_store",
    "create_content_store_from_config",
    "create_run_store",
    "create_run_store_from_config",
    # Registries
    "project_store_registry",
    "artifact_store_registry",
    "content_store_registry",
    "run_store_registry",
]
