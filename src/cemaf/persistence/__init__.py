"""
Persistence module - Core entities and storage protocols.

Core entities (from start.ini):
- Project: Multi-tenant project container
- ContextArtifact: Versioned context documents
- MemoryItem: Scoped memory entries
- ContentItem: Generated content
- Run: Pipeline execution record

Protocols for pluggable storage backends.
"""

from cemaf.persistence.entities import (
    Project,
    ContextArtifact,
    ContentItem,
    Run,
)
from cemaf.persistence.protocols import (
    ProjectStore,
    ArtifactStore,
    ContentStore,
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

