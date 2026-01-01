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
