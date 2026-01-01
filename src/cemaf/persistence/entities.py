"""
Core entities - From start.ini specification.

Domain models for multi-tenant project management.
All entities are immutable (frozen Pydantic models).
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from cemaf.core.enums import ContextArtifactType, RunStatus
from cemaf.core.types import JSON, ProjectID, RunID
from cemaf.core.utils import generate_id, utc_now


class ProjectStatus(str, Enum):
    """Status of a project."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ContentStatus(str, Enum):
    """Status of content item."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"


class Project(BaseModel):
    """Multi-tenant project container."""

    model_config = {"frozen": True}

    id: ProjectID = Field(default_factory=lambda: ProjectID(generate_id("proj")))
    name: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.DRAFT
    created_at: datetime = Field(default_factory=utc_now)
    start_at: datetime | None = None
    end_at: datetime | None = None
    tenant_id: str | None = None
    owner_id: str | None = None
    metadata: JSON = Field(default_factory=dict)

    def with_status(self, status: ProjectStatus) -> Project:
        return self.model_copy(update={"status": status})


class ContextArtifact(BaseModel):
    """Versioned context document."""

    model_config = {"frozen": True}

    id: str = Field(default_factory=lambda: generate_id("art"))
    project_id: ProjectID
    type: ContextArtifactType
    content: str
    version: int = 1
    sha: str = ""
    source: str = ""
    source_url: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    metadata: JSON = Field(default_factory=dict)

    def with_new_version(self, content: str, sha: str) -> ContextArtifact:
        return self.model_copy(
            update={
                "id": generate_id("art"),
                "content": content,
                "version": self.version + 1,
                "sha": sha,
                "created_at": utc_now(),
            }
        )


class ContentItem(BaseModel):
    """Generated content ready for publishing."""

    model_config = {"frozen": True}

    id: str = Field(default_factory=lambda: generate_id("cnt"))
    project_id: ProjectID
    platform: str
    format: str
    brief: str
    title: str = ""
    body: str = ""
    caption: str = ""
    hashtags: tuple[str, ...] = ()
    assets: tuple[str, ...] = ()
    status: ContentStatus = ContentStatus.DRAFT
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    run_id: RunID | None = None
    metadata: JSON = Field(default_factory=dict)

    def with_status(self, status: ContentStatus) -> ContentItem:
        return self.model_copy(update={"status": status, "updated_at": utc_now()})


class Run(BaseModel):
    """Pipeline execution record."""

    model_config = {"frozen": True}

    id: RunID = Field(default_factory=lambda: RunID(generate_id("run")))
    project_id: ProjectID
    pipeline: str
    dag_name: str = ""
    inputs: JSON = Field(default_factory=dict)
    outputs: JSON = Field(default_factory=dict)
    evals: JSON = Field(default_factory=dict)
    traces: tuple[JSON, ...] = ()
    status: RunStatus = RunStatus.PENDING
    error: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0
    metadata: JSON = Field(default_factory=dict)

    @property
    def duration_seconds(self) -> float | None:
        if not self.completed_at:
            return None
        return (self.completed_at - self.started_at).total_seconds()

    def with_completion(self, status: RunStatus, outputs: JSON, error: str | None = None) -> Run:
        return self.model_copy(
            update={
                "status": status,
                "outputs": outputs,
                "error": error,
                "completed_at": utc_now(),
            }
        )
