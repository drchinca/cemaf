"""
Persistence module - Core entities and storage protocols.

**Extension Point** — This module defines protocols and entities for project persistence.
No concrete storage backends are included. Implement the protocols (ProjectStore, ArtifactStore,
ContentStore, RunStore) to connect to your storage layer (PostgreSQL, MongoDB, etc.).

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
]
