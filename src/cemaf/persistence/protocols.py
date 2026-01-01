"""
Storage protocols - Pluggable persistence backends.

Protocols allow swapping storage implementations:
- PostgresStore for production
- InMemoryStore for testing
- FileStore for development
"""

from typing import Protocol, runtime_checkable

from cemaf.core.enums import ContextArtifactType, RunStatus
from cemaf.core.types import ProjectID, RunID
from cemaf.persistence.entities import (
    ContentItem,
    ContentStatus,
    ContextArtifact,
    Project,
    ProjectStatus,
    Run,
)


@runtime_checkable
class ProjectStore(Protocol):
    """Protocol for project storage."""

    async def create(self, project: Project) -> Project:
        """Create a new project."""
        ...

    async def get(self, project_id: ProjectID) -> Project | None:
        """Get project by ID."""
        ...

    async def update(self, project: Project) -> Project:
        """Update an existing project."""
        ...

    async def delete(self, project_id: ProjectID) -> bool:
        """Delete a project. Returns True if existed."""
        ...

    async def list_by_status(
        self,
        status: ProjectStatus | None = None,
        limit: int = 100,
    ) -> tuple[Project, ...]:
        """List projects, optionally filtered by status."""
        ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Protocol for context artifact storage."""

    async def create(self, artifact: ContextArtifact) -> ContextArtifact:
        """Create a new artifact."""
        ...

    async def get(self, artifact_id: str) -> ContextArtifact | None:
        """Get artifact by ID."""
        ...

    async def get_latest(
        self,
        project_id: ProjectID,
        artifact_type: ContextArtifactType,
    ) -> ContextArtifact | None:
        """Get latest version of an artifact type for a project."""
        ...

    async def list_by_project(
        self,
        project_id: ProjectID,
        artifact_type: ContextArtifactType | None = None,
    ) -> tuple[ContextArtifact, ...]:
        """List artifacts for a project."""
        ...

    async def list_versions(
        self,
        project_id: ProjectID,
        artifact_type: ContextArtifactType,
    ) -> tuple[ContextArtifact, ...]:
        """List all versions of an artifact type."""
        ...


@runtime_checkable
class ContentStore(Protocol):
    """Protocol for content item storage."""

    async def create(self, content: ContentItem) -> ContentItem:
        """Create a new content item."""
        ...

    async def get(self, content_id: str) -> ContentItem | None:
        """Get content by ID."""
        ...

    async def update(self, content: ContentItem) -> ContentItem:
        """Update a content item."""
        ...

    async def list_by_project(
        self,
        project_id: ProjectID,
        status: ContentStatus | None = None,
        platform: str | None = None,
        limit: int = 100,
    ) -> tuple[ContentItem, ...]:
        """List content for a project."""
        ...

    async def list_scheduled(
        self,
        limit: int = 100,
    ) -> tuple[ContentItem, ...]:
        """List all scheduled content."""
        ...


@runtime_checkable
class RunStore(Protocol):
    """Protocol for run storage."""

    async def create(self, run: Run) -> Run:
        """Create a new run."""
        ...

    async def get(self, run_id: RunID) -> Run | None:
        """Get run by ID."""
        ...

    async def update(self, run: Run) -> Run:
        """Update a run."""
        ...

    async def list_by_project(
        self,
        project_id: ProjectID,
        status: RunStatus | None = None,
        limit: int = 100,
    ) -> tuple[Run, ...]:
        """List runs for a project."""
        ...

    async def get_latest(self, project_id: ProjectID) -> Run | None:
        """Get most recent run for a project."""
        ...
